"""Manual verification of elo.py before building routers on top of it.

Uses a throwaway SQLite DB (ELO_DB_PATH env var) — never touches data/app.db.
Run: python scripts/test_elo.py
"""

import os
import sys
import tempfile
from pathlib import Path

tmp_db = Path(tempfile.gettempdir()) / "elo_test_scratch.db"
if tmp_db.exists():
    tmp_db.unlink()
os.environ["ELO_DB_PATH"] = str(tmp_db)

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from app.database import Base, SessionLocal, engine  # noqa: E402
from app.elo import (  # noqa: E402
    apply_attempt_result,
    expected_probability,
    get_effective_rating,
    update_rating,
)
from app.models import Player, PlayerModeRating, PlayerTopicRating, Question  # noqa: E402

Base.metadata.create_all(bind=engine)

ok = True


def check(label, actual, expected, tol=1e-9):
    global ok
    passed = abs(actual - expected) <= tol
    ok = ok and passed
    print(f"  [{'PASS' if passed else 'FAIL'}] {label}: {actual:.4f} (expected {expected:.4f})")


print("1) expected_probability")
check("equal ratings -> 0.5", expected_probability(1200, 1200), 0.5)
check("+400 advantage -> ~0.909", expected_probability(1600, 1200), 10 / 11, 1e-6)
check("-400 disadvantage -> ~0.091", expected_probability(1200, 1600), 1 / 11, 1e-6)

print("\n2) update_rating")
t, r = update_rating(1200, 350, 1200, 1)  # fresh player beats equal question
check("win vs equal, full RD: theta 1200 -> 1220", t, 1220.0)
check("RD shrinks 350 -> 332.5", r, 332.5)
t, r = update_rating(1200, 350, 1200, 0)
check("loss vs equal, full RD: theta 1200 -> 1180", t, 1180.0)
t, r = update_rating(1200, 50, 1200, 1)  # confident player: K = 40*(50/350)
check("win at RD floor: much smaller swing (+2.857)", t, 1200 + 40 * (50 / 350) * 0.5, 1e-6)
t, r = update_rating(1200, 52, 1200, 1)
check("RD floors at 50", r, 50.0)

print("\n3) get_effective_rating (shrinkage)")
check("0 attempts -> pure parent", get_effective_rating(900, 350, 1300, 0), 1300.0)
check("15+ attempts -> pure specific", get_effective_rating(900, 100, 1300, 20), 900.0)
check("5 attempts -> 1/3 specific, 2/3 parent", get_effective_rating(900, 300, 1300, 5),
      (1 / 3) * 900 + (2 / 3) * 1300, 1e-6)

print("\n4) apply_attempt_result (all four updates, atomically)")
db = SessionLocal()
db.add(Player(player_id="p1", name="Test Player"))
db.add(Question(
    question_id="q1", text="test?", options=["a", "b", "c", "d"],
    correct_answer="a", subject="Physics", topic="Mechanics",
    sub_topic="Kinematics", difficulty_tag="hard", theta_q=1500.0,
    marking_scheme={"correct": 4, "incorrect": -1, "unattempted": 0},
    solution_steps=[], formulas_used=[],
))
db.commit()

deltas = apply_attempt_result("p1", "q1", mode="practice_quiz", correct=True, db_session=db)

p = db.get(Player, "p1")
q = db.get(Question, "q1")
topic_row = db.query(PlayerTopicRating).filter_by(player_id="p1", topic="Mechanics").one()
mode_row = db.query(PlayerModeRating).filter_by(player_id="p1", mode="practice_quiz").one()

# 1200 beats 1500: expected p = 1/(1+10^0.75) ~= 0.15098, K=40 -> +33.96
exp_gain = 40 * (1 - expected_probability(1200, 1500))
check("overall theta gain vs harder Q", p.theta_overall, 1200 + exp_gain, 1e-6)
check("overall rd shrank", p.rd_overall, 332.5)
check("topic row lazily created, same gain", topic_row.theta, 1200 + exp_gain, 1e-6)
check("topic attempts_count", topic_row.attempts_count, 1)
check("mode row lazily created, same gain", mode_row.theta, 1200 + exp_gain, 1e-6)
# question mirror: K = 40*(175/350) = 20, question "lost" (outcome 0 for it)
exp_q_drop = 20 * (0 - expected_probability(1500, 1200))
check("question theta_q dropped (mirror, K=20)", q.theta_q, 1500 + exp_q_drop, 1e-6)
check("deltas dict reports before-snapshot", deltas["theta_p_before"], 1200.0)

print("\n5) placement mode skips mode rating")
db.add(Question(
    question_id="q2", text="test2?", options=["a", "b", "c", "d"],
    correct_answer="a", subject="Physics", topic="Optics",
    sub_topic="Prism", difficulty_tag="easy", theta_q=900.0,
    marking_scheme={"correct": 4, "incorrect": -1, "unattempted": 0},
    solution_steps=[], formulas_used=[],
))
db.commit()
deltas2 = apply_attempt_result("p1", "q2", mode="placement", correct=False, db_session=db)
placement_mode_rows = db.query(PlayerModeRating).filter_by(player_id="p1", mode="placement").count()
check("no 'placement' mode-rating row created", placement_mode_rows, 0)
check("mode delta is None for placement", 0 if deltas2["mode"] is None else 1, 0)
optics_row = db.query(PlayerTopicRating).filter_by(player_id="p1", topic="Optics").one()
print(f"  info: wrong answer on easy Q dropped Optics topic theta to {optics_row.theta:.1f}")

print("\n6) unknown player rolls back cleanly")
try:
    apply_attempt_result("nope", "q1", mode="practice_quiz", correct=True, db_session=db)
    print("  [FAIL] expected ValueError")
    ok = False
except ValueError:
    print("  [PASS] raised ValueError, session rolled back")

db.close()
print("\n" + ("ALL CHECKS PASSED" if ok else "SOME CHECKS FAILED"))
sys.exit(0 if ok else 1)
