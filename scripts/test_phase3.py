"""End-to-end test of Phase 3 + auth: detailed report + MCQ failure testing
(REAL Groq calls). Scratch DB via ELO_DB_PATH.

Run: python scripts/test_phase3.py
"""

import json
import os
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
import tempfile
from pathlib import Path

tmp_db = Path(tempfile.gettempdir()) / "phase3_test_scratch.db"
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
    headers = auth_headers("user_testkid", "TestKid", auth_module=auth)

    print("1) run a 4-question quiz: 2 right, 2 deliberately wrong")
    qsid = client.post("/api/quiz/start", headers=headers,
                      json={"num_questions": 4}).json()["session_id"]
    from app.database import SessionLocal
    from app.models import Question

    wrong_qids = []
    for i in range(4):
        nxt = client.get(f"/api/quiz/{qsid}/next", headers=headers).json()
        db = SessionLocal()
        correct = db.get(Question, nxt["question_id"]).correct_answer
        db.close()
        if i < 2:
            answer = correct
        else:
            answer = next(o for o in nxt["options"] if o != correct)
            wrong_qids.append(nxt["question_id"])
        client.post(f"/api/quiz/{qsid}/submit", headers=headers, json={
            "question_id": nxt["question_id"], "selected_answer": answer,
            "reaction_time_ms": 5000})
    check("2 wrong answers recorded", len(wrong_qids) == 2)

    print("\n2) detailed report")
    r = client.get(f"/api/reports/{qsid}", headers=headers).json()
    check("total_score 6 (2*4 - 2*1)", r["total_score"] == 6)
    check("accuracy 50%", r["accuracy_pct"] == 50.0)
    check("wrong_answers has 2 entries", len(r["wrong_answers"]) == 2)
    check("per_topic has avg_theta_q", all("avg_theta_q" in b for b in r["per_topic"].values()))
    check("wrong entries expose selected + correct answer",
          all(w["selected_answer"] and w["correct_answer"] for w in r["wrong_answers"]))
    check("0 failure tests used, max 3",
          r["failure_tests_used"] == 0 and r["failure_tests_max"] == 3)

    print("\n2b) another authenticated player cannot read this report (IDOR check)")
    other_headers = auth_headers("user_snooper", "Snooper", auth_module=auth)
    snoop = client.get(f"/api/reports/{qsid}", headers=other_headers)
    check("cross-player report access -> 403", snoop.status_code == 403)

    print("\n3) failure test: MCQ probe generation (REAL LLM call)")
    target = wrong_qids[0]
    r = client.post(f"/api/reports/{qsid}/failure_test/{target}", headers=headers)
    check("probe endpoint 200", r.status_code == 200)
    ft = r.json()
    if ft.get("fallback"):
        print("  !! LLM fell back to read-through — check keys/model. Continuing checks.")
        check("fallback still returns solution_steps", len(ft["solution_steps"]) >= 2)
    else:
        probes = ft["probes"]
        check("probes non-empty", len(probes) >= 2)
        check("probes have MCQ fields",
              all("options" in p and "correct_option" in p and "misconceptions" in p
                  for p in probes))
        check("every probe has >=2 options, correct_option among them",
              all(len(p["options"]) >= 2 and p["correct_option"] in p["options"]
                  for p in probes))
        check("every wrong option has a tagged misconception",
              all(all(o in p["misconceptions"] for o in p["options"] if o != p["correct_option"])
                  for p in probes))
        print("  generated probes:")
        for p in probes:
            print(f"    step {p['step_order']}: {p['probe_question']} "
                  f"(correct: {p['correct_option']!r})")

        print("\n4) idempotent restart returns same probes")
        again = client.post(f"/api/reports/{qsid}/failure_test/{target}",
                           headers=headers).json()
        check("same probes returned", again["probes"] == probes)

        print("\n5) respond one-at-a-time (MCQ); deliberately break at the 2nd checkpoint")
        # probes before break_index: answered correctly. break_index onward:
        # deliberately wrong, to confirm the diagnosis picks the EARLIEST
        # wrong step (break_index) rather than the last one.
        break_index = 1 if len(probes) > 1 else 0
        final = None
        for i, p in enumerate(probes):
            if i < break_index:
                choice = p["correct_option"]
            else:
                wrong_opts = [o for o in p["options"] if o != p["correct_option"]]
                choice = wrong_opts[0] if wrong_opts else p["correct_option"]
            rr = client.post(
                f"/api/reports/{qsid}/failure_test/{target}/respond",
                headers=headers,
                json={"step_order": p["step_order"], "selected_option": choice},
            ).json()
            check(f"  probe {i}: correct flag matches choice",
                  rr["correct"] == (choice == p["correct_option"]))
            final = rr
        check("final respond complete", final["complete"] is True)
        d = final["diagnosis"]
        print(f"  diagnosis: step={d['gap_step_order']} conf={d['confidence']}")
        print(f"  gap: {d['gap_description']}")
        check("gap_description non-empty", bool(d["gap_description"]))
        check("confidence valid", d["confidence"] in ("high", "medium", "low"))
        check("gap correctly identifies the EARLIEST wrong step (deterministic, no LLM)",
              d["gap_step_order"] == probes[break_index]["step_order"])
        check("solution steps included for reveal screen", len(final["solution_steps"]) >= 2)
        check("respond after complete -> 409",
              client.post(f"/api/reports/{qsid}/failure_test/{target}/respond",
                          headers=headers,
                          json={"step_order": probes[0]["step_order"],
                                "selected_option": probes[0]["correct_option"]}
                          ).status_code == 409)

        print("\n6) report reflects diagnostic status")
        r = client.get(f"/api/reports/{qsid}", headers=headers).json()
        target_entry = next(w for w in r["wrong_answers"] if w["question_id"] == target)
        check("status = diagnosed", target_entry["diagnostic_status"] == "diagnosed")
        check("failure_tests_used = 1", r["failure_tests_used"] == 1)

    print("\n7) guard rails")
    r = client.post(f"/api/reports/{qsid}/failure_test/physics_kinematics_nonexistent",
                    headers=headers)
    check("failure test on unattempted question -> 404", r.status_code == 404)
    # a correctly-answered question can't be failure-tested
    summary = client.get(f"/api/quiz/{qsid}/summary", headers=headers).json()
    correct_qid = next(q["question_id"] for q in summary["questions"] if q["was_correct"])
    r = client.post(f"/api/reports/{qsid}/failure_test/{correct_qid}", headers=headers)
    check("failure test on correct answer -> 404", r.status_code == 404)

print("\n" + ("ALL CHECKS PASSED" if not failures else f"{len(failures)} FAILURES: {failures}"))
sys.exit(0 if not failures else 1)
