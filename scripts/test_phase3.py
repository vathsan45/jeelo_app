"""End-to-end test of Phase 3: detailed report + failure testing (REAL Groq calls).

Scratch DB via ELO_DB_PATH. Run: python scripts/test_phase3.py
"""

import json
import os
import sys
import tempfile
from pathlib import Path

tmp_db = Path(tempfile.gettempdir()) / "phase3_test_scratch.db"
if tmp_db.exists():
    tmp_db.unlink()
os.environ["ELO_DB_PATH"] = str(tmp_db)

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402

failures = []


def check(label, cond):
    print(f"  [{'PASS' if cond else 'FAIL'}] {label}")
    if not cond:
        failures.append(label)


with TestClient(app) as client:
    pid = client.post("/api/players/create", json={"name": "TestKid"}).json()["player_id"]

    print("1) run a 4-question quiz: 2 right, 2 deliberately wrong")
    qsid = client.post(f"/api/quiz/{pid}/start", json={"num_questions": 4}).json()["session_id"]
    from app.database import SessionLocal
    from app.models import Question

    wrong_qids = []
    for i in range(4):
        nxt = client.get(f"/api/quiz/{qsid}/next").json()
        db = SessionLocal()
        correct = db.get(Question, nxt["question_id"]).correct_answer
        db.close()
        if i < 2:
            answer = correct
        else:
            answer = next(o for o in nxt["options"] if o != correct)
            wrong_qids.append(nxt["question_id"])
        client.post(f"/api/quiz/{qsid}/submit", json={
            "question_id": nxt["question_id"], "selected_answer": answer,
            "reaction_time_ms": 5000})
    check("2 wrong answers recorded", len(wrong_qids) == 2)

    print("\n2) detailed report")
    r = client.get(f"/api/reports/{qsid}").json()
    check("total_score 6 (2*4 - 2*1)", r["total_score"] == 6)
    check("accuracy 50%", r["accuracy_pct"] == 50.0)
    check("wrong_answers has 2 entries", len(r["wrong_answers"]) == 2)
    check("per_topic has avg_theta_q", all("avg_theta_q" in b for b in r["per_topic"].values()))
    check("wrong entries expose selected + correct answer",
          all(w["selected_answer"] and w["correct_answer"] for w in r["wrong_answers"]))
    check("0 failure tests used, max 3",
          r["failure_tests_used"] == 0 and r["failure_tests_max"] == 3)

    print("\n3) failure test: probe generation (REAL LLM call)")
    target = wrong_qids[0]
    r = client.post(f"/api/reports/{qsid}/failure_test/{target}")
    check("probe endpoint 200", r.status_code == 200)
    ft = r.json()
    if ft.get("fallback"):
        print("  !! LLM fell back to read-through — check keys/model. Continuing checks.")
        check("fallback still returns solution_steps", len(ft["solution_steps"]) >= 2)
    else:
        probes = ft["probes"]
        check("probes non-empty", len(probes) >= 2)
        check("probes have required fields",
              all("probe_question" in p and "step_order" in p for p in probes))
        print("  generated probes:")
        for p in probes:
            print(f"    step {p['step_order']}: {p['probe_question']}")

        print("\n4) idempotent restart returns same probes")
        again = client.post(f"/api/reports/{qsid}/failure_test/{target}").json()
        check("same probes returned", again["probes"] == probes)

        print("\5) respond one-at-a-time; last respond triggers diagnosis (REAL LLM call)")
        # Deliberately break down at step 2: first response right-ish, rest confused
        canned = ["The motion has constant acceleration and starts from rest."] + \
                 ["I don't know, I just guessed something here."] * (len(probes) - 1)
        final = None
        for p, resp_text in zip(probes, canned):
            rr = client.post(
                f"/api/reports/{qsid}/failure_test/{target}/respond",
                json={"step_order": p["step_order"], "player_response": resp_text},
            ).json()
            final = rr
        check("final respond complete", final["complete"] is True)
        d = final["diagnosis"]
        print(f"  diagnosis: step={d['gap_step_order']} conf={d['confidence']}")
        print(f"  gap: {d['gap_description']}")
        check("gap_description non-empty", bool(d["gap_description"]))
        check("confidence valid", d["confidence"] in ("high", "medium", "low"))
        check("solution steps included for reveal screen", len(final["solution_steps"]) >= 2)
        check("respond after complete -> 409",
              client.post(f"/api/reports/{qsid}/failure_test/{target}/respond",
                          json={"step_order": 1, "player_response": "x"}).status_code == 409)

        print("\n6) report reflects diagnostic status")
        r = client.get(f"/api/reports/{qsid}").json()
        target_entry = next(w for w in r["wrong_answers"] if w["question_id"] == target)
        check("status = diagnosed", target_entry["diagnostic_status"] == "diagnosed")
        check("failure_tests_used = 1", r["failure_tests_used"] == 1)

    print("\n7) guard rails")
    ok_q = [w["question_id"] for w in client.get(f"/api/reports/{qsid}").json()["wrong_answers"]]
    r = client.post(f"/api/reports/{qsid}/failure_test/physics_kinematics_nonexistent")
    check("failure test on unattempted question -> 404", r.status_code == 404)
    # a correctly-answered question can't be failure-tested
    all_attempted = client.get(f"/api/reports/{qsid}").json()
    correct_qid = None
    summary = client.get(f"/api/quiz/{qsid}/summary").json()
    correct_qid = next(q["question_id"] for q in summary["questions"] if q["was_correct"])
    r = client.post(f"/api/reports/{qsid}/failure_test/{correct_qid}")
    check("failure test on correct answer -> 404", r.status_code == 404)

print("\n" + ("ALL CHECKS PASSED" if not failures else f"{len(failures)} FAILURES: {failures}"))
sys.exit(0 if not failures else 1)
