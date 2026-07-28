import random
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session as DBSession

from ..auth import get_current_player
from ..database import get_db
from ..elo import apply_attempt_result, get_effective_rating
from ..models import (
    AttemptLog,
    Player,
    PlayerTopicRating,
    Question,
    Session,
)
from ..question_selector import select_next_question

router = APIRouter(tags=["quiz"])

PLACEMENT_NUM_QUESTIONS = 8


class SubmitBody(BaseModel):
    question_id: str
    selected_answer: str
    reaction_time_ms: Optional[int] = None


class QuizStartBody(BaseModel):
    topic_filter: Optional[str] = None
    num_questions: int = 10


def _get_owned_session(db, session_id, expected_mode, player):
    session = db.get(Session, session_id)
    if session is None or session.mode != expected_mode:
        raise HTTPException(status_code=404, detail=f"{expected_mode} session not found")
    if session.player_id != player.player_id:
        raise HTTPException(status_code=403, detail="this session belongs to another player")
    return session


def _session_attempts(db, session_id):
    return (
        db.query(AttemptLog)
        .filter_by(session_id=session_id)
        .order_by(AttemptLog.round_num)
        .all()
    )


def _next_question(db, session, num_questions):
    attempts = _session_attempts(db, session.session_id)
    if len(attempts) >= num_questions:
        if session.ended_at is None:
            session.ended_at = datetime.utcnow()
            db.commit()
        return {"complete": True}

    topic_filter = (session.config or {}).get("topic_filter")
    q = select_next_question(
        player_id=session.player_id,
        mode=session.mode,
        topic_filter=topic_filter,
        exclude_ids=[a.question_id for a in attempts],
        db_session=db,
    )
    if q is None:  # pool exhausted
        if session.ended_at is None:
            session.ended_at = datetime.utcnow()
            db.commit()
        return {"complete": True}

    # raw data always lists the correct answer first — shuffle at serve time
    # (correctness is checked by string match, so display order is free)
    options = list(q.options)
    random.shuffle(options)

    return {
        "complete": False,
        "question_id": q.question_id,
        "text": q.text,
        "options": options,
        "topic": q.topic,
        "sub_topic": q.sub_topic,
        "round": len(attempts) + 1,
        "total": num_questions,
    }


def _submit(db, session, body: SubmitBody, scored: bool):
    question = db.get(Question, body.question_id)
    if question is None:
        raise HTTPException(status_code=404, detail="question not found")
    already = (
        db.query(AttemptLog)
        .filter_by(session_id=session.session_id, question_id=body.question_id)
        .first()
    )
    if already is not None:
        raise HTTPException(status_code=409, detail="question already answered in this session")

    correct = body.selected_answer == question.correct_answer

    deltas = apply_attempt_result(
        player_id=session.player_id,
        question_id=body.question_id,
        mode=session.mode,
        correct=correct,
        db_session=db,
    )

    if scored:
        scheme = question.marking_scheme
        points_delta = scheme["correct"] if correct else scheme["incorrect"]
    else:
        points_delta = 0.0

    round_num = db.query(AttemptLog).filter_by(session_id=session.session_id).count() + 1
    db.add(AttemptLog(
        session_id=session.session_id,
        player_id=session.player_id,
        question_id=body.question_id,
        round_num=round_num,
        mode=session.mode,
        theta_p_before=deltas["theta_p_before"],
        theta_q_before=deltas["theta_q_before"],
        hand_raised=None,
        reaction_time_ms=body.reaction_time_ms,
        attempted=True,
        correct=correct,
        points_delta=float(points_delta),
        selected_answer=body.selected_answer,
    ))
    db.commit()

    return {
        "correct": correct,
        "correct_answer": question.correct_answer,
        "points_delta": points_delta if scored else None,
        "rating": {
            "theta_overall": deltas["overall"]["theta"],
            "delta_overall": deltas["overall"]["delta"],
            "topic": deltas["topic"]["name"],
            "theta_topic": deltas["topic"]["theta"],
            "delta_topic": deltas["topic"]["delta"],
        },
    }


# ---------- PLACEMENT ----------

@router.post("/placement/start")
def placement_start(player: Player = Depends(get_current_player), db: DBSession = Depends(get_db)):
    session = Session(player_id=player.player_id, mode="placement",
                      config={"num_questions": PLACEMENT_NUM_QUESTIONS})
    db.add(session)
    db.commit()
    db.refresh(session)
    return {"session_id": session.session_id, "num_questions": PLACEMENT_NUM_QUESTIONS}


@router.get("/placement/{session_id}/next")
def placement_next(session_id: str, player: Player = Depends(get_current_player),
                   db: DBSession = Depends(get_db)):
    session = _get_owned_session(db, session_id, "placement", player)
    return _next_question(db, session, PLACEMENT_NUM_QUESTIONS)


@router.post("/placement/{session_id}/submit")
def placement_submit(session_id: str, body: SubmitBody,
                     player: Player = Depends(get_current_player),
                     db: DBSession = Depends(get_db)):
    session = _get_owned_session(db, session_id, "placement", player)
    return _submit(db, session, body, scored=False)


@router.get("/placement/{session_id}/summary")
def placement_summary(session_id: str, player: Player = Depends(get_current_player),
                      db: DBSession = Depends(get_db)):
    session = _get_owned_session(db, session_id, "placement", player)
    attempts = _session_attempts(db, session_id)

    topics = [t[0] for t in db.query(Question.topic).distinct().all()]
    per_topic = {}
    for topic in topics:
        row = (
            db.query(PlayerTopicRating)
            .filter_by(player_id=player.player_id, topic=topic)
            .first()
        )
        if row is None:
            per_topic[topic] = {
                "theta_effective": player.theta_overall,
                "rd": player.rd_overall,
                "attempts_count": 0,
            }
        else:
            per_topic[topic] = {
                "theta_effective": get_effective_rating(
                    row.theta, row.rd, player.theta_overall, row.attempts_count
                ),
                "rd": row.rd,
                "attempts_count": row.attempts_count,
            }

    return {
        "player_id": player.player_id,
        "name": player.name,
        "questions_answered": len(attempts),
        "correct_count": sum(1 for a in attempts if a.correct),
        "theta_overall": player.theta_overall,
        "rd_overall": player.rd_overall,
        "per_topic": per_topic,
    }


# ---------- PRACTICE QUIZ ----------

@router.post("/quiz/start")
def quiz_start(body: QuizStartBody, player: Player = Depends(get_current_player),
               db: DBSession = Depends(get_db)):
    if body.topic_filter is not None:
        topics = {t[0] for t in db.query(Question.topic).distinct().all()}
        if body.topic_filter not in topics:
            raise HTTPException(status_code=422,
                                detail=f"unknown topic; valid: {sorted(topics)}")
    session = Session(
        player_id=player.player_id, mode="practice_quiz",
        config={"topic_filter": body.topic_filter, "num_questions": body.num_questions},
    )
    db.add(session)
    db.commit()
    db.refresh(session)
    return {"session_id": session.session_id, "num_questions": body.num_questions,
            "topic_filter": body.topic_filter}


@router.get("/quiz/{session_id}/next")
def quiz_next(session_id: str, player: Player = Depends(get_current_player),
             db: DBSession = Depends(get_db)):
    session = _get_owned_session(db, session_id, "practice_quiz", player)
    num_questions = (session.config or {}).get("num_questions", 10)
    return _next_question(db, session, num_questions)


@router.post("/quiz/{session_id}/submit")
def quiz_submit(session_id: str, body: SubmitBody,
                player: Player = Depends(get_current_player),
                db: DBSession = Depends(get_db)):
    session = _get_owned_session(db, session_id, "practice_quiz", player)
    return _submit(db, session, body, scored=True)


@router.get("/quiz/{session_id}/summary")
def quiz_summary(session_id: str, player: Player = Depends(get_current_player),
                 db: DBSession = Depends(get_db)):
    session = _get_owned_session(db, session_id, "practice_quiz", player)
    attempts = _session_attempts(db, session_id)
    if not attempts:
        return {"session_id": session_id, "total_score": 0, "accuracy_pct": 0,
                "avg_reaction_time_ms": None, "per_topic": {}, "questions": []}

    questions = {
        q.question_id: q
        for q in db.query(Question)
        .filter(Question.question_id.in_([a.question_id for a in attempts]))
        .all()
    }

    per_topic = {}
    for a in attempts:
        topic = questions[a.question_id].topic
        bucket = per_topic.setdefault(topic, {"attempted": 0, "correct": 0})
        bucket["attempted"] += 1
        bucket["correct"] += 1 if a.correct else 0
    for bucket in per_topic.values():
        bucket["accuracy_pct"] = round(100 * bucket["correct"] / bucket["attempted"], 1)

    reaction_times = [a.reaction_time_ms for a in attempts if a.reaction_time_ms is not None]
    return {
        "session_id": session_id,
        "total_score": sum(a.points_delta for a in attempts),
        "accuracy_pct": round(100 * sum(1 for a in attempts if a.correct) / len(attempts), 1),
        "avg_reaction_time_ms": (
            round(sum(reaction_times) / len(reaction_times)) if reaction_times else None
        ),
        "per_topic": per_topic,
        "questions": [
            {"question_id": a.question_id, "was_correct": bool(a.correct),
             "points_delta": a.points_delta,
             "topic": questions[a.question_id].topic}
            for a in attempts
        ],
    }
