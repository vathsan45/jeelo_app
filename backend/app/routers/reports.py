import json
import random

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session as DBSession

from ..auth import get_current_player
from ..database import get_db
from ..llm import call_llm_json
from ..models import AttemptLog, FailureDiagnostic, Player, Question, Session

router = APIRouter(prefix="/reports", tags=["reports"])

MAX_FAILURE_TESTS_PER_SESSION = 3

# Each probe is now a multiple-choice checkpoint, not a free-text question.
# This is what lets diagnosis be resolved deterministically in Python once all
# probes are answered (see respond_failure_test) — no second LLM call needed:
# the student's own selection either matches the correct option for that step,
# or matches a pre-tagged misconception, so there's nothing left to interpret.
PROBE_SYSTEM_PROMPT = (
    "You are a Socratic physics tutor. You will be given a question the student "
    "answered WRONG, the option they chose, the correct answer, and the correct "
    "step-by-step solution (optionally with a known misconception for the "
    "student's specific wrong answer, if available — use it to sharpen your "
    "checkpoints). Generate one multiple-choice checkpoint question PER solution "
    "step, in order, that tests whether the student correctly understood or "
    "executed THAT specific step — not the final answer.\n\n"
    "Each checkpoint must have exactly one correct option (what that step's "
    "correct reasoning produces) and 1-2 deliberately wrong options, each "
    "representing a SPECIFIC, plausible misunderstanding a student could have "
    "at that exact step (never a random or absurd value). Keep each "
    "probe_question under 25 words. Keep every option short — a value, a "
    "formula name, or a short phrase, never a full sentence.\n\n"
    "Return ONLY valid JSON, no markdown, no commentary:\n"
    '{"probes": [{"step_order": int, "probe_question": str, "concept_tested": str, '
    '"options": [str, ...], "correct_option": str (must exactly match one option), '
    '"misconceptions": {"<each wrong option, verbatim>": "<short specific '
    'misconception>", ...}}]}'
)


class RespondBody(BaseModel):
    step_order: int
    selected_option: str


def _get_owned_session(db, session_id, player):
    session = db.get(Session, session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="session not found")
    if session.player_id != player.player_id:
        raise HTTPException(status_code=403, detail="this session belongs to another player")
    return session


def _wrong_attempts(db, session_id):
    return (
        db.query(AttemptLog)
        .filter_by(session_id=session_id, attempted=True, correct=False)
        .order_by(AttemptLog.round_num)
        .all()
    )


def _session_diagnostics(db, session_id):
    attempt_ids = [
        a.id for a in db.query(AttemptLog).filter_by(session_id=session_id).all()
    ]
    if not attempt_ids:
        return []
    return (
        db.query(FailureDiagnostic)
        .filter(FailureDiagnostic.attempt_log_id.in_(attempt_ids))
        .all()
    )


def _clean_probe(raw, fallback_index):
    """Validate + normalize one LLM-generated MCQ probe. Returns None (and the
    whole probe set gets dropped by the caller) if anything doesn't check out
    — malformed probes can't be safely graded deterministically, so a bad one
    poisons the batch rather than silently degrading to a guess."""
    if not isinstance(raw, dict) or not raw.get("probe_question"):
        return None

    options = raw.get("options")
    if not isinstance(options, list) or len(options) < 2:
        return None
    options = [str(o) for o in options]
    if len(set(options)) != len(options):
        return None  # duplicate option text — can't key misconceptions reliably

    correct_option = raw.get("correct_option")
    if correct_option not in options:
        return None

    wrong_options = [o for o in options if o != correct_option]
    misconceptions_raw = raw.get("misconceptions")
    if not isinstance(misconceptions_raw, dict):
        return None
    misconceptions = {}
    for wo in wrong_options:
        if not misconceptions_raw.get(wo):
            return None  # every wrong option needs a tagged misconception
        misconceptions[wo] = str(misconceptions_raw[wo])

    random.shuffle(options)  # LLM tends to list the correct option first
    return {
        "step_order": int(raw.get("step_order", fallback_index + 1)),
        "probe_question": str(raw["probe_question"]),
        "concept_tested": str(raw.get("concept_tested", "")),
        "options": options,
        "correct_option": correct_option,
        "misconceptions": misconceptions,
    }


# ---------- DETAILED REPORT ----------

@router.get("/{session_id}")
def get_report(session_id: str, player: Player = Depends(get_current_player),
              db: DBSession = Depends(get_db)):
    session = _get_owned_session(db, session_id, player)
    attempts = (
        db.query(AttemptLog)
        .filter_by(session_id=session_id)
        .order_by(AttemptLog.round_num)
        .all()
    )
    if not attempts:
        return {"session_id": session_id, "mode": session.mode, "attempts": 0,
                "total_score": 0, "accuracy_pct": 0, "avg_reaction_time_ms": None,
                "per_topic": {}, "wrong_answers": [], "failure_tests_used": 0,
                "failure_tests_max": MAX_FAILURE_TESTS_PER_SESSION}

    questions = {
        q.question_id: q
        for q in db.query(Question)
        .filter(Question.question_id.in_([a.question_id for a in attempts]))
        .all()
    }

    answered = [a for a in attempts if a.attempted]
    per_topic = {}
    for a in answered:
        topic = questions[a.question_id].topic
        b = per_topic.setdefault(topic, {"attempted": 0, "correct": 0, "theta_q_sum": 0.0})
        b["attempted"] += 1
        b["correct"] += 1 if a.correct else 0
        b["theta_q_sum"] += a.theta_q_before
    for b in per_topic.values():
        b["accuracy_pct"] = round(100 * b["correct"] / b["attempted"], 1)
        b["avg_theta_q"] = round(b["theta_q_sum"] / b["attempted"])
        del b["theta_q_sum"]

    diagnostics = _session_diagnostics(db, session_id)
    diag_by_attempt = {d.attempt_log_id: d for d in diagnostics}

    wrong_answers = []
    for a in _wrong_attempts(db, session_id):
        q = questions[a.question_id]
        d = diag_by_attempt.get(a.id)
        wrong_answers.append({
            "question_id": a.question_id,
            "text": q.text,
            "topic": q.topic,
            "sub_topic": q.sub_topic,
            "selected_answer": a.selected_answer,
            "correct_answer": q.correct_answer,
            "theta_q": round(a.theta_q_before),
            "diagnostic_status": (
                "none" if d is None
                else "diagnosed" if d.identified_gap_description is not None
                else "in_progress"
            ),
        })

    reaction_times = [a.reaction_time_ms for a in answered if a.reaction_time_ms is not None]
    return {
        "session_id": session_id,
        "mode": session.mode,
        "attempts": len(answered),
        "total_score": sum(a.points_delta for a in answered),
        "accuracy_pct": round(100 * sum(1 for a in answered if a.correct) / len(answered), 1)
        if answered else 0,
        "avg_reaction_time_ms": (
            round(sum(reaction_times) / len(reaction_times)) if reaction_times else None
        ),
        "per_topic": per_topic,
        "wrong_answers": wrong_answers,
        "failure_tests_used": len(diagnostics),
        "failure_tests_max": MAX_FAILURE_TESTS_PER_SESSION,
    }


# ---------- FAILURE TESTING ----------

@router.post("/{session_id}/failure_test/{question_id}")
def start_failure_test(session_id: str, question_id: str,
                       player: Player = Depends(get_current_player),
                       db: DBSession = Depends(get_db)):
    session = _get_owned_session(db, session_id, player)
    attempt = (
        db.query(AttemptLog)
        .filter_by(session_id=session_id, question_id=question_id,
                   attempted=True, correct=False)
        .first()
    )
    if attempt is None:
        raise HTTPException(status_code=404,
                            detail="no wrong attempt for this question in this session")
    question = db.get(Question, question_id)

    # idempotent: return the existing diagnostic if one was already started
    existing = (
        db.query(FailureDiagnostic).filter_by(attempt_log_id=attempt.id).first()
    )
    if existing is not None:
        return {
            "fallback": False,
            "probes": existing.generated_probe_questions,
            "answered": len(existing.player_responses or []),
            "solution_steps": question.solution_steps,
        }

    if len(_session_diagnostics(db, session_id)) >= MAX_FAILURE_TESTS_PER_SESSION:
        raise HTTPException(status_code=409,
                            detail=f"max {MAX_FAILURE_TESTS_PER_SESSION} failure tests per session")

    # ground the probes in the pre-authored misconception for this exact wrong
    # answer, when we have one, so the LLM isn't guessing from scratch
    known_misconception = None
    if question.distractor_analysis:
        entry = question.distractor_analysis.get(attempt.selected_answer)
        if entry:
            known_misconception = entry.get("misconception")

    user_message = json.dumps({
        "question": question.text,
        "options": question.options,
        "students_wrong_answer": attempt.selected_answer,
        "correct_answer": question.correct_answer,
        "known_misconception_for_students_answer": known_misconception,
        "solution_steps": question.solution_steps,
    }, ensure_ascii=False)

    result = call_llm_json(PROBE_SYSTEM_PROMPT, user_message)

    probes = None
    if result and isinstance(result.get("probes"), list) and result["probes"]:
        cleaned = [
            c for c in (
                _clean_probe(p, i) for i, p in enumerate(result["probes"])
            ) if c is not None
        ]
        if cleaned:
            probes = sorted(cleaned, key=lambda p: p["step_order"])

    if probes is None:
        # LLM failed twice (or every probe was malformed) — read-through
        # fallback, nothing stored so a retry later can still go interactive
        return {"fallback": True, "solution_steps": question.solution_steps}

    diag = FailureDiagnostic(
        attempt_log_id=attempt.id,
        question_id=question_id,
        player_id=session.player_id,
        generated_probe_questions=probes,
        player_responses=[],
    )
    db.add(diag)
    db.commit()

    return {"fallback": False, "probes": probes, "answered": 0,
            "solution_steps": question.solution_steps}


@router.post("/{session_id}/failure_test/{question_id}/respond")
def respond_failure_test(session_id: str, question_id: str, body: RespondBody,
                         player: Player = Depends(get_current_player),
                         db: DBSession = Depends(get_db)):
    _get_owned_session(db, session_id, player)
    attempt = (
        db.query(AttemptLog)
        .filter_by(session_id=session_id, question_id=question_id)
        .first()
    )
    diag = (
        db.query(FailureDiagnostic)
        .filter_by(attempt_log_id=attempt.id if attempt else -1)
        .first()
    )
    if diag is None or not diag.generated_probe_questions:
        raise HTTPException(status_code=404, detail="failure test not started")
    if diag.identified_gap_description is not None:
        raise HTTPException(status_code=409, detail="diagnosis already complete")

    probes_by_step = {p["step_order"]: p for p in diag.generated_probe_questions}
    probe = probes_by_step.get(body.step_order)
    if probe is None:
        raise HTTPException(status_code=422, detail="unknown step_order for this diagnostic")
    if body.selected_option not in probe["options"]:
        raise HTTPException(status_code=422,
                            detail="selected_option is not one of this probe's options")

    responses = list(diag.player_responses or [])
    if any(r["step_order"] == body.step_order for r in responses):
        raise HTTPException(status_code=409, detail="this step was already answered")

    correct = body.selected_option == probe["correct_option"]
    misconception = None if correct else probe["misconceptions"].get(body.selected_option)

    responses.append({
        "step_order": body.step_order,
        "selected_option": body.selected_option,
        "correct": correct,
        "misconception": misconception,
    })
    diag.player_responses = responses  # reassign so SQLAlchemy tracks the JSON change
    db.commit()

    total = len(diag.generated_probe_questions)
    if len(responses) < total:
        return {"complete": False, "answered": len(responses), "total": total,
                "correct": correct, "misconception": misconception,
                "correct_option": probe["correct_option"]}

    # all probes answered — deterministic diagnosis, no interpretation call
    # needed: every wrong pick already carries its own tagged misconception.
    question = db.get(Question, question_id)
    ordered = sorted(responses, key=lambda r: r["step_order"])
    first_wrong = next((r for r in ordered if not r["correct"]), None)

    if first_wrong is not None:
        gap_probe = probes_by_step[first_wrong["step_order"]]
        description = first_wrong["misconception"]
        if gap_probe.get("concept_tested"):
            description = f"{gap_probe['concept_tested']}: {description}"
        diagnosis = {
            "gap_step_order": first_wrong["step_order"],
            "gap_description": description,
            "confidence": "high",
        }
    else:
        diagnosis = {
            "gap_step_order": None,
            "gap_description": (
                "You answered every checkpoint correctly — the mistake was "
                "likely a careless slip (arithmetic or a misread value) rather "
                "than a conceptual gap. Recheck your work against the solution "
                "below."
            ),
            "confidence": "medium",
        }

    diag.identified_gap_step = diagnosis["gap_step_order"]
    diag.identified_gap_description = diagnosis["gap_description"]
    db.commit()

    return {
        "complete": True,
        "diagnosis": diagnosis,
        "solution_steps": question.solution_steps,
        "correct": correct,
        "misconception": misconception,
        "correct_option": probe["correct_option"],
    }
