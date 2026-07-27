"""End-to-end test of Phase 4: Risk Arena (one real Groq call in coach report).

Scratch DB via ELO_DB_PATH. Run: python scripts/test_phase4.py
"""

import os
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
import tempfile
from pathlib import Path

tmp_db = Path(tempfile.gettempdir()) / "phase4_test_scratch.db"
if tmp_db.exists():
    tmp_db.unlink()
os.environ["ELO_DB_PATH"] = str(tmp_db)

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from fastapi.testclient import TestClient  # noqa: E402

from app.bots import ARCHETYPES, bot_decide  # noqa: E402
from app.main import app  # noqa: E402

failures = []


def check(label, cond):
    print(f"  [{'PASS' if cond else 'FAIL'}] {label}")
    if not cond:
        failures.append(label)


print("0) bot_decide sanity")
scheme = {"correct": 4, "incorrect": -1, "unattempted": 0}
# breakeven = 1/5 = 0.2. Rusher at equal rating: p≈0.5+bias → attempts easily
att, ms = bot_decide(1200, ARCHETYPES["rusher"], 1200, scheme)
check("rusher attempts an equal question", att is True)
check("rusher reaction in range", 300 <= ms <= 600)
# skipper vs much harder question: perceived p tiny, threshold 0.36 → skips
att, _ = bot_decide(1200, ARCHETYPES["skipper"], 1700, scheme)
check("skipper skips a much harder question", att is False)
# calibrated: p=0.5 > 0.2 → attempts equal question
att, _ = bot_decide(1200, ARCHETYPES["calibrated"], 1200, scheme)
check("calibrated attempts an equal question", att is True)

with TestClient(app) as client:
    pid = client.post("/api/players/create", json={"name": "Arena Ace"}).json()["player_id"]

    print("\n1) start arena session")
    r = client.post(f"/api/risk_arena/{pid}/start",
                    json={"num_rounds": 7, "first_session": True})
    check("start 200", r.status_code == 200)
    arena = r.json()
    sid = arena["session_id"]
    check("7 rounds prepared", arena["num_rounds"] == 7)
    check("decide/answer second durations returned",
          arena["decide_seconds"] == 10 and arena["answer_seconds"] == 15)
    check("3 fixed bots on first session",
          sorted(b["archetype"] for b in arena["bots"]) == ["calibrated", "rusher", "skipper"])

    print("\n2) play rounds: attempt correct, attempt wrong, skip, ...")
    from app.database import SessionLocal
    from app.models import Question

    # "timeout" exercises the new rule: raised hand + no answer in time -> wrong
    plan = ["correct", "wrong", "skip", "correct", "skip", "timeout"]
    for n, action in enumerate(plan, start=1):
        rd = client.get(f"/api/risk_arena/{sid}/round/{n}").json()
        check(f"round {n}: no answer leaked", "correct_answer" not in rd)
        check(f"round {n}: theta_q + marking_scheme present",
              "theta_q" in rd and rd["marking_scheme"]["correct"] == 4)
        db = SessionLocal()
        correct_ans = db.get(Question, rd["question_id"]).correct_answer
        db.close()

        if action == "skip":
            res = client.post(f"/api/risk_arena/{sid}/round/{n}/decide",
                              json={"hand_raised": False, "reaction_time_ms": 3000}).json()
            check(f"round {n}: decide(skip) resolves immediately", res["phase"] == "resolved")
        else:
            decide_res = client.post(f"/api/risk_arena/{sid}/round/{n}/decide",
                                     json={"hand_raised": True, "reaction_time_ms": 2000}).json()
            check(f"round {n}: decide(raise) returns 'raised'", decide_res["phase"] == "raised")
            check(f"round {n}: answer_seconds present", decide_res["answer_seconds"] == 15)

            if action == "timeout":
                res = client.post(f"/api/risk_arena/{sid}/round/{n}/answer",
                                  json={"selected_answer": None, "reaction_time_ms": 15000}).json()
            else:
                pick = correct_ans if action == "correct" else \
                    next(o for o in rd["options"] if o != correct_ans)
                res = client.post(f"/api/risk_arena/{sid}/round/{n}/answer",
                                  json={"selected_answer": pick, "reaction_time_ms": 2500}).json()
            check(f"round {n}: answer resolves", res["phase"] == "resolved")

        if action == "skip":
            check(f"round {n}: skip scored 0", res["player"]["points_delta"] == 0)
        elif action == "correct":
            check(f"round {n}: correct scored +4", res["player"]["points_delta"] == 4)
        else:  # wrong or timeout
            check(f"round {n}: {action} scored -1", res["player"]["points_delta"] == -1)
        check(f"round {n}: leaderboard has 4 rows", len(res["leaderboard"]) == 4)
        check(f"round {n}: leaderboard sorted",
              all(res["leaderboard"][i]["score"] >= res["leaderboard"][i + 1]["score"]
                  for i in range(3)))

    check("player total = 4-1+0+4+0-1 = 6 after 6 rounds", res["player"]["total_score"] == 6)
    check("not yet complete (7 rounds prepared, 6 played)", res["session_complete"] is False)

    print("\n3) guards")
    dup = client.post(f"/api/risk_arena/{sid}/round/1/decide",
                      json={"hand_raised": False})
    check("resubmit round -> 409", dup.status_code == 409)
    out_of_range = client.post(f"/api/risk_arena/{sid}/round/8/decide",
                               json={"hand_raised": True})
    check("round out of range -> 404", out_of_range.status_code == 404)
    orphan_answer = client.post(f"/api/risk_arena/{sid}/round/7/answer",
                                json={"selected_answer": "x"})
    check("answer without prior decide/raise -> 409", orphan_answer.status_code == 409)

    # finish round 7 (untouched) so the session completes for the coach report
    client.post(f"/api/risk_arena/{sid}/round/7/decide", json={"hand_raised": False})
    check("session now complete", True)

    print("\n4) elo: mode rating exists, skips didn't update it")
    prof = client.get(f"/api/players/{pid}").json()
    check("risk_arena mode rating exists", "risk_arena" in prof["mode_ratings"])
    check("mode attempts_count == 4 (skips excluded)",
          prof["mode_ratings"]["risk_arena"]["attempts_count"] == 4)

    print("\n5) coach report (REAL Groq call)")
    r = client.get(f"/api/risk_arena/{sid}/coach_report")
    check("coach report 200", r.status_code == 200)
    cr = r.json()
    check("actual_score == 6", cr["actual_score"] == 6)
    check("optimal >= 0", cr["optimal_score"] >= 0)
    check("gap = optimal - actual",
          abs(cr["gap"] - (cr["optimal_score"] - cr["actual_score"])) < 0.01)
    check("7 rounds in log", len(cr["rounds"]) == 7)
    check("every round has p/breakeven/ev",
          all("p_success" in r_ and "breakeven" in r_ and "optimal_ev" in r_
              for r_ in cr["rounds"]))
    check("3 coaching points", len(cr["coaching_points"]) == 3)
    check("final leaderboard present", cr["final_leaderboard"] is not None)
    print(f"  actual={cr['actual_score']} optimal={cr['optimal_score']} gap={cr['gap']}")
    for p in cr["coaching_points"]:
        print(f"  coach: {p}")
    if cr["biggest_divergence"]:
        bd = cr["biggest_divergence"]
        print(f"  biggest divergence: round {bd['round_num']} "
              f"(p={bd['p_success']}, attempted={bd['attempted']})")

print("\n" + ("ALL CHECKS PASSED" if not failures else f"{len(failures)} FAILURES: {failures}"))
sys.exit(0 if not failures else 1)
