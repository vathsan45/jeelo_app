import json
import random
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session as DBSession

from ..auth import get_current_player
from ..bots import ARCHETYPES, BOT_NAMES, bot_answer_correct, bot_decide
from ..database import get_db
from ..elo import apply_attempt_result, expected_probability, get_effective_rating
from ..llm import call_llm_json
from ..models import AttemptLog, Player, PlayerModeRating, Question, Session
from ..question_selector import select_next_question

router = APIRouter(prefix="/risk_arena", tags=["risk_arena"])

# In-memory arena state per session (bots don't need DB persistence).
# Lost on server restart — sessions must then be restarted; fine for a demo.
ARENA_STATE = {}

DECIDE_SECONDS = 10  # time to raise hand or skip
ANSWER_SECONDS = 15  # time to pick an option, once hand is raised

COACH_SYSTEM_PROMPT = (
    "You are a decision-making coach for a quiz risk game. Players choose to "
    "attempt (+4 correct / -1 wrong) or skip (0) each question. You are given "
    "their session stats: actual score, the optimal expected-value score a "
    "perfectly calibrated player would get with the same questions, the gap, "
    "and their worst divergent decision. Write 3 short coaching points (each "
    "under 30 words) referencing the actual numbers given. Be specific and "
    "encouraging, not generic. Return ONLY valid JSON:\n"
    '{"coaching_points": [str, str, str]}'
)


class StartBody(BaseModel):
    num_rounds: int = 8
    first_session: bool = True


class DecideBody(BaseModel):
    hand_raised: bool
    reaction_time_ms: Optional[int] = None


class AnswerBody(BaseModel):
    # None means the answer-phase timer ran out before a selection was made
    selected_answer: Optional[str] = None
    reaction_time_ms: Optional[int] = None


def _get_owned_arena_session(db, session_id, player):
    session = db.get(Session, session_id)
    if session is None or session.mode != "risk_arena":
        raise HTTPException(status_code=404, detail="risk_arena session not found")
    if session.player_id != player.player_id:
        raise HTTPException(status_code=403, detail="this session belongs to another player")
    return session


def _get_arena(session_id):
    state = ARENA_STATE.get(session_id)
    if state is None:
        raise HTTPException(
            status_code=410,
            detail="arena state lost (server restarted) — start a new session",
        )
    return state


def _leaderboard(state, player_name):
    rows = [{"name": player_name, "score": state["player_score"], "is_player": True,
             "last_action": state.get("player_last_action")}]
    for b in state["bots"]:
        rows.append({"name": b["name"], "score": b["score"], "is_player": False,
                     "last_action": b.get("last_action")})
    return sorted(rows, key=lambda r: r["score"], reverse=True)


def _resolve_bots(state, question):
    """Bots decide (attempt or not) and resolve immediately — they don't need
    a separate answer phase, their 'reaction time' already models the whole
    decision. Called exactly once per round, from /decide."""
    scheme = question.marking_scheme
    bot_results = []
    for b in state["bots"]:
        attempt, reaction_ms = bot_decide(b["theta"], ARCHETYPES[b["archetype"]],
                                          question.theta_q, scheme)
        if attempt:
            correct = bot_answer_correct(b["theta"], question.theta_q)
            delta = scheme["correct"] if correct else scheme["incorrect"]
            b["score"] += delta
            b["last_action"] = "correct" if correct else "wrong"
        else:
            correct = None
            delta = 0
            b["last_action"] = "skipped"
        bot_results.append({"name": b["name"], "attempted": attempt,
                            "correct": correct, "points_delta": delta,
                            "reaction_time_ms": reaction_ms})
    return bot_results


@router.post("/start")
def start(body: StartBody, player: Player = Depends(get_current_player),
         db: DBSession = Depends(get_db)):
    session = Session(player_id=player.player_id, mode="risk_arena",
                      config={"num_rounds": body.num_rounds})
    db.add(session)
    db.commit()
    db.refresh(session)

    # select all round questions up-front, targeting the player's EFFECTIVE
    # risk_arena rating (blends toward overall when there's little history)
    exclude = []
    question_ids = []
    for _ in range(body.num_rounds):
        q = select_next_question(player.player_id, "risk_arena", None, exclude, db)
        if q is None:
            break
        question_ids.append(q.question_id)
        exclude.append(q.question_id)

    # first_session: fixed archetype lineup
    archetype_names = ["calibrated", "rusher", "skipper"]
    if not body.first_session:
        archetype_names = random.sample(list(ARCHETYPES), 3)

    ARENA_STATE[session.session_id] = {
        "question_ids": question_ids,
        "bots": [
            {"name": BOT_NAMES[a], "archetype": a, "theta": 1200.0, "score": 0.0}
            for a in archetype_names
        ],
        "player_score": 0.0,
        "submitted_rounds": set(),
        "pending": {},  # round_num -> {bot_results} once hand is raised, awaiting an answer
    }

    return {
        "session_id": session.session_id,
        "num_rounds": len(question_ids),
        "decide_seconds": DECIDE_SECONDS,
        "answer_seconds": ANSWER_SECONDS,
        "bots": [{"name": b["name"], "archetype": b["archetype"]}
                 for b in ARENA_STATE[session.session_id]["bots"]],
    }


@router.get("/{session_id}/round/{n}")
def get_round(session_id: str, n: int, player: Player = Depends(get_current_player),
             db: DBSession = Depends(get_db)):
    _get_owned_arena_session(db, session_id, player)
    state = _get_arena(session_id)
    if not (1 <= n <= len(state["question_ids"])):
        raise HTTPException(status_code=404, detail="round out of range")
    q = db.get(Question, state["question_ids"][n - 1])

    options = list(q.options)
    random.shuffle(options)  # raw data lists correct answer first

    return {
        "round": n,
        "total": len(state["question_ids"]),
        "question_id": q.question_id,
        "text": q.text,
        "options": options,
        "topic": q.topic,
        "sub_topic": q.sub_topic,
        "theta_q": round(q.theta_q),
        "marking_scheme": q.marking_scheme,
        "decide_seconds": DECIDE_SECONDS,
        "answer_seconds": ANSWER_SECONDS,
    }


def _finish_round(db, session, state, player, question, n, hand_raised, correct,
                  points_delta, selected_answer, reaction_time_ms, theta_p_before,
                  theta_q_before, bot_results):
    round_num = db.query(AttemptLog).filter_by(session_id=session.session_id).count() + 1
    db.add(AttemptLog(
        session_id=session.session_id,
        player_id=session.player_id,
        question_id=question.question_id,
        round_num=round_num,
        mode="risk_arena",
        theta_p_before=theta_p_before,
        theta_q_before=theta_q_before,
        hand_raised=hand_raised,
        reaction_time_ms=reaction_time_ms,
        attempted=hand_raised,
        correct=correct,
        points_delta=float(points_delta),
        selected_answer=selected_answer,
    ))
    state["submitted_rounds"].add(n)
    state["pending"].pop(n, None)

    is_last = len(state["submitted_rounds"]) >= len(state["question_ids"])
    if is_last and session.ended_at is None:
        session.ended_at = datetime.utcnow()
    db.commit()

    db.refresh(player)
    mode_row = (db.query(PlayerModeRating)
                .filter_by(player_id=session.player_id, mode="risk_arena").first())
    if mode_row is not None:
        effective_theta = get_effective_rating(mode_row.theta, mode_row.rd,
                                               player.theta_overall,
                                               mode_row.attempts_count)
    else:
        effective_theta = player.theta_overall

    return {
        "correct_answer": question.correct_answer,
        "player": {
            "attempted": hand_raised,
            "correct": correct,
            "points_delta": points_delta,
            "total_score": state["player_score"],
            "effective_arena_theta": round(effective_theta, 1),
        },
        "bots": bot_results,
        "leaderboard": _leaderboard(state, player.name),
        "session_complete": is_last,
    }


@router.post("/{session_id}/round/{n}/decide")
def decide_round(session_id: str, n: int, body: DecideBody,
                 player: Player = Depends(get_current_player),
                 db: DBSession = Depends(get_db)):
    """Phase 1 (10s): raise your hand to commit to answering, or let it pass
    to skip. Bots resolve here regardless — their 'decision' is instant."""
    session = _get_owned_arena_session(db, session_id, player)
    state = _get_arena(session_id)
    if not (1 <= n <= len(state["question_ids"])):
        raise HTTPException(status_code=404, detail="round out of range")
    if n in state["submitted_rounds"]:
        raise HTTPException(status_code=409, detail="round already submitted")
    if n in state["pending"]:
        raise HTTPException(status_code=409, detail="hand already raised for this round")

    question = db.get(Question, state["question_ids"][n - 1])
    bot_results = _resolve_bots(state, question)

    if not body.hand_raised:
        # skip: no elo update, but log EVERY round with ratings captured
        state["player_last_action"] = "skipped"
        result = _finish_round(
            db, session, state, player, question, n,
            hand_raised=False, correct=None, points_delta=0.0,
            selected_answer=None, reaction_time_ms=body.reaction_time_ms,
            theta_p_before=player.theta_overall, theta_q_before=question.theta_q,
            bot_results=bot_results,
        )
        return {"phase": "resolved", **result}

    # hand raised: hold the round open for the answer phase. Nothing about
    # the player/question is mutated yet, so the before-snapshot captured now
    # is still valid whenever /answer eventually resolves it.
    state["pending"][n] = {
        "bot_results": bot_results,
        "decide_reaction_time_ms": body.reaction_time_ms,
    }
    return {"phase": "raised", "answer_seconds": ANSWER_SECONDS}


@router.post("/{session_id}/round/{n}/answer")
def answer_round(session_id: str, n: int, body: AnswerBody,
                 player: Player = Depends(get_current_player),
                 db: DBSession = Depends(get_db)):
    """Phase 2 (15s): pick an option having already raised your hand. Running
    out the clock here counts as a wrong answer — raising your hand is a
    commitment, not a free look."""
    session = _get_owned_arena_session(db, session_id, player)
    state = _get_arena(session_id)
    if not (1 <= n <= len(state["question_ids"])):
        raise HTTPException(status_code=404, detail="round out of range")
    if n in state["submitted_rounds"]:
        raise HTTPException(status_code=409, detail="round already submitted")
    pending = state["pending"].get(n)
    if pending is None:
        raise HTTPException(status_code=409,
                            detail="hand not raised for this round — call /decide first")

    question = db.get(Question, state["question_ids"][n - 1])
    correct = bool(body.selected_answer) and body.selected_answer == question.correct_answer

    deltas = apply_attempt_result(session.player_id, question.question_id,
                                  "risk_arena", correct, db)
    scheme = question.marking_scheme
    points_delta = scheme["correct"] if correct else scheme["incorrect"]
    state["player_score"] += points_delta
    state["player_last_action"] = "correct" if correct else "wrong"

    result = _finish_round(
        db, session, state, player, question, n,
        hand_raised=True, correct=correct, points_delta=points_delta,
        selected_answer=body.selected_answer, reaction_time_ms=body.reaction_time_ms,
        theta_p_before=deltas["theta_p_before"], theta_q_before=deltas["theta_q_before"],
        bot_results=pending["bot_results"],
    )
    return {"phase": "resolved", **result}


@router.get("/{session_id}/coach_report")
def coach_report(session_id: str, player: Player = Depends(get_current_player),
                 db: DBSession = Depends(get_db)):
    session = _get_owned_arena_session(db, session_id, player)
    attempts = (db.query(AttemptLog).filter_by(session_id=session_id)
                .order_by(AttemptLog.round_num).all())
    if not attempts:
        raise HTTPException(status_code=404, detail="no rounds played")

    questions = {q.question_id: q for q in db.query(Question).filter(
        Question.question_id.in_([a.question_id for a in attempts])).all()}

    rounds = []
    actual_score = 0.0
    optimal_score = 0.0
    per_topic = {}
    for a in attempts:
        q = questions[a.question_id]
        scheme = q.marking_scheme
        reward = scheme["correct"]
        penalty = abs(scheme["incorrect"])
        p = expected_probability(a.theta_p_before, a.theta_q_before)
        breakeven = penalty / (reward + penalty)
        optimal_ev = max(0, p * reward - (1 - p) * penalty)
        should_attempt = p > breakeven
        divergent = (a.attempted and not should_attempt) or (not a.attempted and should_attempt)

        actual_score += a.points_delta
        optimal_score += optimal_ev

        t = per_topic.setdefault(q.topic, {"rounds": 0, "actual": 0.0, "optimal": 0.0})
        t["rounds"] += 1
        t["actual"] += a.points_delta
        t["optimal"] += optimal_ev

        rounds.append({
            "round_num": a.round_num,
            "question_id": a.question_id,
            "topic": q.topic,
            "p_success": round(p, 3),
            "breakeven": round(breakeven, 3),
            "optimal_ev": round(optimal_ev, 2),
            "attempted": a.attempted,
            "correct": a.correct,
            "points_delta": a.points_delta,
            "divergent": divergent,
        })

    for t in per_topic.values():
        t["actual"] = round(t["actual"], 2)
        t["optimal"] = round(t["optimal"], 2)

    divergent_rounds = [r for r in rounds if r["divergent"]]
    biggest = max(divergent_rounds,
                  key=lambda r: abs(r["optimal_ev"] - r["points_delta"]),
                  default=None)

    gap = optimal_score - actual_score

    # ONE Groq call for coaching points, hardcoded fallback
    result = call_llm_json(COACH_SYSTEM_PROMPT, json.dumps({
        "actual_score": round(actual_score, 2),
        "optimal_score": round(optimal_score, 2),
        "gap": round(gap, 2),
        "rounds_played": len(rounds),
        "rounds_attempted": sum(1 for r in rounds if r["attempted"]),
        "divergent_decisions": len(divergent_rounds),
        "biggest_divergence": biggest,
    }))

    points = None
    if result and isinstance(result.get("coaching_points"), list):
        points = [str(p) for p in result["coaching_points"]][:3]
    if not points or len(points) < 3:
        skips_bad = sum(1 for r in divergent_rounds if not r["attempted"])
        rushes = sum(1 for r in divergent_rounds if r["attempted"])
        points = [
            f"You scored {actual_score:.0f}; perfectly calibrated play was worth "
            f"{optimal_score:.1f} — a gap of {gap:.1f} points.",
            f"{rushes} attempt(s) had below-breakeven odds and {skips_bad} skip(s) "
            "were actually favorable — check the round log below.",
            "Rule of thumb: at +4/-1 scoring, attempt whenever your win chance "
            "beats 20%.",
        ]

    state = ARENA_STATE.get(session_id)
    return {
        "player_name": player.name,
        "actual_score": round(actual_score, 2),
        "optimal_score": round(optimal_score, 2),
        "gap": round(gap, 2),
        "per_topic": per_topic,
        "biggest_divergence": biggest,
        "coaching_points": points,
        "rounds": rounds,
        "final_leaderboard": _leaderboard(state, player.name) if state else None,
    }
