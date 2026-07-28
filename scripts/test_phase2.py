"""End-to-end test of Phase 2 + auth: placement, practice quiz, session
ownership. Uses FastAPI TestClient on a scratch DB (ELO_DB_PATH) — real
app.db untouched. Fake-but-valid Clerk tokens via _auth_helper, no real
sign-in or network call needed.

Run: python scripts/test_phase2.py
"""

import os
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
import tempfile
from pathlib import Path

tmp_db = Path(tempfile.gettempdir()) / "phase2_test_scratch.db"
if tmp_db.exists():
    tmp_db.unlink()
os.environ["ELO_DB_PATH"] = str(tmp_db)
os.environ.setdefault("CLERK_ISSUER", "https://test-instance.clerk.accounts.dev")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from fastapi.testclient import TestClient  # noqa: E402

from app import auth  # noqa: E402
from app.main import app  # noqa: E402
from _auth_helper import auth_headers, patch_jwks  # noqa: E402

patch_jwks(auth)

failures = []


def check(label, cond):
    print(f"  [{'PASS' if cond else 'FAIL'}] {label}")
    if not cond:
        failures.append(label)


with TestClient(app) as client:
    print("1) health + first-login player creation (via auth, not /players/create)")
    r = client.get("/api/health").json()
    check("questions seeded", r["questions_loaded"] > 0)

    headers = auth_headers("user_asha", "Asha", auth_module=auth)
    r = client.get("/api/players/me", headers=headers)
    check("first /me call 200", r.status_code == 200)
    player = r.json()
    pid = player["player_id"]
    check("starts at 1200/350", player["theta_overall"] == 1200 and player["rd_overall"] == 350)

    r2 = client.get("/api/players/me", headers=headers)
    check("second /me call returns same player_id", r2.json()["player_id"] == pid)

    print("\n2) full placement flow (8 questions, always pick option A)")
    r = client.post("/api/placement/start", headers=headers)
    sid = r.json()["session_id"]
    topics_seen, rounds = set(), 0
    while True:
        nxt = client.get(f"/api/placement/{sid}/next", headers=headers).json()
        if nxt.get("complete"):
            break
        rounds += 1
        check(f"round {nxt['round']}: no correct_answer leaked",
              "correct_answer" not in nxt)
        topics_seen.add(nxt["topic"])
        sub = client.post(f"/api/placement/{sid}/submit", headers=headers, json={
            "question_id": nxt["question_id"],
            "selected_answer": nxt["options"][0],
            "reaction_time_ms": 4000,
        }).json()
        check(f"round {nxt['round']}: placement unscored (points_delta null)",
              sub["points_delta"] is None)
    check("exactly 8 rounds served", rounds == 8)
    check("placement spans multiple topics", len(topics_seen) >= 2)

    r = client.get(f"/api/placement/{sid}/summary", headers=headers).json()
    check("summary has 4 topics", len(r["per_topic"]) == 4)
    check("theta_overall moved off 1200", r["theta_overall"] != 1200)
    check("rd_overall shrank (8 x 0.95)", abs(r["rd_overall"] - 350 * 0.95 ** 8) < 1e-6)
    print(f"  info: after placement theta={r['theta_overall']:.1f} rd={r['rd_overall']:.1f} "
          f"({r['correct_count']}/8 correct)")

    print("\n3) resubmitting same question is rejected")
    r2 = client.post("/api/placement/start", headers=headers)
    sid2 = r2.json()["session_id"]
    nxt2 = client.get(f"/api/placement/{sid2}/next", headers=headers).json()
    client.post(f"/api/placement/{sid2}/submit", headers=headers, json={
        "question_id": nxt2["question_id"], "selected_answer": nxt2["options"][0]})
    dup = client.post(f"/api/placement/{sid2}/submit", headers=headers, json={
        "question_id": nxt2["question_id"], "selected_answer": nxt2["options"][1]})
    check("duplicate submit -> 409", dup.status_code == 409)

    print("\n3b) another authenticated player cannot touch this session (IDOR check)")
    other_headers = auth_headers("user_intruder", "Intruder", auth_module=auth)
    intrude = client.get(f"/api/placement/{sid2}/next", headers=other_headers)
    check("cross-player session access -> 403", intrude.status_code == 403)

    print("\n4) practice quiz, Mechanics only, 5 questions, always correct")
    r = client.post("/api/quiz/start", headers=headers,
                    json={"topic_filter": "Mechanics", "num_questions": 5})
    qsid = r.json()["session_id"]
    theta_before = client.get("/api/players/me", headers=headers).json()["theta_overall"]
    rounds = 0
    while True:
        nxt = client.get(f"/api/quiz/{qsid}/next", headers=headers).json()
        if nxt.get("complete"):
            break
        rounds += 1
        check(f"round {rounds}: topic filter respected", nxt["topic"] == "Mechanics")
        # cheat: look up correct answer directly in scratch DB
        from app.database import SessionLocal
        from app.models import Question
        db = SessionLocal()
        correct = db.get(Question, nxt["question_id"]).correct_answer
        db.close()
        sub = client.post(f"/api/quiz/{qsid}/submit", headers=headers, json={
            "question_id": nxt["question_id"], "selected_answer": correct,
            "reaction_time_ms": 3000 + rounds * 100,
        }).json()
        check(f"round {rounds}: correct scored +4", sub["points_delta"] == 4)
        check(f"round {rounds}: rating delta positive", sub["rating"]["delta_overall"] > 0)
    check("5 rounds served", rounds == 5)

    r = client.get(f"/api/quiz/{qsid}/summary", headers=headers).json()
    check("total score 20", r["total_score"] == 20)
    check("accuracy 100%", r["accuracy_pct"] == 100.0)
    check("avg reaction computed", r["avg_reaction_time_ms"] == 3300)
    check("per_topic has Mechanics only", list(r["per_topic"].keys()) == ["Mechanics"])
    check("questions list has 5 entries", len(r["questions"]) == 5)
    theta_after = client.get("/api/players/me", headers=headers).json()["theta_overall"]
    check("overall theta rose after 5 correct", theta_after > theta_before)
    print(f"  info: theta {theta_before:.1f} -> {theta_after:.1f}")

    print("\n5) mode rating created for practice_quiz but not placement")
    pr = client.get("/api/players/me", headers=headers).json()
    check("practice_quiz mode rating exists", "practice_quiz" in pr["mode_ratings"])
    check("no placement mode rating", "placement" not in pr["mode_ratings"])

    print("\n6) wrong answer scores -1")
    r = client.post("/api/quiz/start", headers=headers, json={"num_questions": 1})
    qsid = r.json()["session_id"]
    nxt = client.get(f"/api/quiz/{qsid}/next", headers=headers).json()
    from app.database import SessionLocal
    from app.models import Question
    db = SessionLocal()
    correct = db.get(Question, nxt["question_id"]).correct_answer
    db.close()
    wrong = next(o for o in nxt["options"] if o != correct)
    sub = client.post(f"/api/quiz/{qsid}/submit", headers=headers, json={
        "question_id": nxt["question_id"], "selected_answer": wrong}).json()
    check("wrong scored -1", sub["points_delta"] == -1)
    check("reveal has correct_answer", sub["correct_answer"] == correct)

    print("\n7) requests with no token are rejected")
    unauth = client.post("/api/quiz/start", json={"num_questions": 1})
    check("no auth header -> 401", unauth.status_code == 401)

print("\n" + ("ALL CHECKS PASSED" if not failures else f"{len(failures)} FAILURES: {failures}"))
sys.exit(0 if not failures else 1)
