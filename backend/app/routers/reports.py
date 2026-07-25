import json
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session as DBSession

from ..database import get_db
from ..llm import call_llm_json
from ..models import AttemptLog, FailureDiagnostic, Question, Session

router = APIRouter(prefix="/reports", tags=["reports"])

MAX_FAILURE_TESTS_PER_SESSION = 3

PROBE_SYSTEM_PROMPT = (
    "You are a Socratic physics tutor. You will be given a question the student "
    "answered WRONG, along with the correct step-by-step solution. Your job is to "
    "generate a short sequence of diagnostic probing questions — one per solution "
    "step — phrased so that asking them in order will reveal exactly which step the "
    "student's understanding broke down at. Each probing question should test "
    "understanding of that specific step's concept/formula, not just ask 'did you "
    "get this step right.' Keep each probe question short (under 25 words) and "
    "answerable in one sentence or a quick multiple-choice-style response.\n\n"
    "Return ONLY valid JSON, no markdown, no commentary:\n"
    '{"probes": [{"step_order": int, "probe_question": str, "concept_tested": str}]}'
)

DIAGNOSIS_SYSTEM_PROMPT = (
    "Given these diagnostic probe questions, the correct solution steps, and the "
    "student's responses to each probe, identify the EARLIEST step where their "
    "response indicates a misunderstanding. Return ONLY valid JSON:\n"
    '{"gap_step_order": int, "gap_description": str (max 30 words, specific, '
    "e.g. 'Correctly identified the scenario as projectile motion but applied the "
    "wrong component of initial velocity in the range formula'), "
    '"confidence": "high"|"medium"|"low"}'
)


class RespondBody(BaseModel):
    step_order: int
    player_response: str


def _get_session(db, session_id):
    session = db.get(Session, session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="session not found")
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


# ---------- DETAILED REPORT ----------

@router.get("/{session_id}")
def get_report(session_id: str, db: DBSession = Depends(get_db)):
    session = _get_session(db, session_id)
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
                       db: DBSession = Depends(get_db)):
    session = _get_session(db, session_id)
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

    user_message = json.dumps({
        "question": question.text,
        "options": question.options,
        "students_wrong_answer": attempt.selected_answer,
        "correct_answer": question.correct_answer,
        "solution_steps": question.solution_steps,
    }, ensure_ascii=False)

    result = call_llm_json(PROBE_SYSTEM_PROMPT, user_message)

    probes = None
    if result and isinstance(result.get("probes"), list) and result["probes"]:
        cleaned = []
        for p in result["probes"]:
            if isinstance(p, dict) and "probe_question" in p:
                cleaned.append({
                    "step_order": int(p.get("step_order", len(cleaned) + 1)),
                    "probe_question": str(p["probe_question"]),
                    "concept_tested": str(p.get("concept_tested", "")),
                })
        if cleaned:
            probes = sorted(cleaned, key=lambda p: p["step_order"])

    if probes is None:
        # LLM failed twice — read-through fallback, nothing stored so a
        # retry later can still go interactive
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
                         db: DBSession = Depends(get_db)):
    _get_session(db, session_id)
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

    responses = list(diag.player_responses or [])
    responses.append({"step_order": body.step_order,
                      "player_response": body.player_response})
    diag.player_responses = responses  # reassign so SQLAlchemy tracks the JSON change
    db.commit()

    total = len(diag.generated_probe_questions)
    if len(responses) < total:
        return {"complete": False, "answered": len(responses), "total": total}

    # all probes answered — ONE interpretation call
    question = db.get(Question, question_id)
    user_message = json.dumps({
        "question": question.text,
        "correct_solution_steps": question.solution_steps,
        "probe_questions": diag.generated_probe_questions,
        "student_responses": responses,
    }, ensure_ascii=False)

    result = call_llm_json(DIAGNOSIS_SYSTEM_PROMPT, user_message)

    if result and "gap_description" in result:
        gap_step: Optional[int]
        try:
            gap_step = int(result.get("gap_step_order"))
        except (TypeError, ValueError):
            gap_step = None
        confidence = result.get("confidence")
        if confidence not in ("high", "medium", "low"):
            confidence = "low"
        diagnosis = {
            "gap_step_order": gap_step,
            "gap_description": str(result["gap_description"]),
            "confidence": confidence,
        }
    else:
        # LLM failed twice — generic fallback, never crash the report screen
        diagnosis = {
            "gap_step_order": None,
            "gap_description": ("Couldn't pinpoint the exact step automatically — "
                                "walk through the full solution below."),
            "confidence": "low",
        }

    diag.identified_gap_step = diagnosis["gap_step_order"]
    diag.identified_gap_description = diagnosis["gap_description"]
    db.commit()

    return {
        "complete": True,
        "diagnosis": diagnosis,
        "solution_steps": question.solution_steps,
    }
