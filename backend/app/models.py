import uuid
from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
)

from .database import Base


def _uuid():
    return str(uuid.uuid4())


class Question(Base):
    __tablename__ = "questions"

    question_id = Column(String, primary_key=True)
    text = Column(String, nullable=False)
    options = Column(JSON, nullable=False)
    correct_answer = Column(String, nullable=False)
    subject = Column(String, default="Physics")
    topic = Column(String, nullable=False)
    sub_topic = Column(String, nullable=False)
    difficulty_tag = Column(String, nullable=False)
    # LIVE, updating global content difficulty rating (seeded from theta_q_seed)
    theta_q = Column(Float, nullable=False)
    marking_scheme = Column(JSON, nullable=False)
    solution_steps = Column(JSON, nullable=False)
    formulas_used = Column(JSON, nullable=False)
    # per-wrong-option misconception map, used for MCQ-based failure diagnosis;
    # nullable since older/hand-authored questions may not have it yet
    distractor_analysis = Column(JSON, nullable=True)


class Player(Base):
    __tablename__ = "players"

    player_id = Column(String, primary_key=True, default=_uuid)
    name = Column(String, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    theta_overall = Column(Float, default=1200.0, nullable=False)
    rd_overall = Column(Float, default=350.0, nullable=False)


class PlayerTopicRating(Base):
    __tablename__ = "player_topic_ratings"

    id = Column(Integer, primary_key=True, autoincrement=True)
    player_id = Column(String, ForeignKey("players.player_id"), nullable=False)
    topic = Column(String, nullable=False)
    theta = Column(Float, default=1200.0, nullable=False)
    rd = Column(Float, default=350.0, nullable=False)
    attempts_count = Column(Integer, default=0, nullable=False)


class PlayerModeRating(Base):
    __tablename__ = "player_mode_ratings"

    id = Column(Integer, primary_key=True, autoincrement=True)
    player_id = Column(String, ForeignKey("players.player_id"), nullable=False)
    mode = Column(String, nullable=False)
    theta = Column(Float, default=1200.0, nullable=False)
    rd = Column(Float, default=350.0, nullable=False)
    attempts_count = Column(Integer, default=0, nullable=False)


class Session(Base):
    __tablename__ = "sessions"

    session_id = Column(String, primary_key=True, default=_uuid)
    player_id = Column(String, ForeignKey("players.player_id"), nullable=False)
    mode = Column(String, nullable=False)  # placement | practice_quiz | risk_arena
    started_at = Column(DateTime, default=datetime.utcnow)
    ended_at = Column(DateTime, nullable=True)
    config = Column(JSON, nullable=True)  # per-session settings (topic_filter, num_questions, ...)


class AttemptLog(Base):
    __tablename__ = "attempt_log"

    id = Column(Integer, primary_key=True, autoincrement=True)
    session_id = Column(String, ForeignKey("sessions.session_id"), nullable=False)
    player_id = Column(String, ForeignKey("players.player_id"), nullable=False)
    question_id = Column(String, ForeignKey("questions.question_id"), nullable=False)
    round_num = Column(Integer, nullable=False)
    mode = Column(String, nullable=False)
    theta_p_before = Column(Float, nullable=False)
    theta_q_before = Column(Float, nullable=False)
    hand_raised = Column(Boolean, nullable=True)  # risk_arena only, else null
    reaction_time_ms = Column(Integer, nullable=True)
    attempted = Column(Boolean, nullable=False)
    correct = Column(Boolean, nullable=True)
    points_delta = Column(Float, default=0.0, nullable=False)
    selected_answer = Column(String, nullable=True)
    timestamp = Column(DateTime, default=datetime.utcnow)


class FailureDiagnostic(Base):
    __tablename__ = "failure_diagnostics"

    id = Column(Integer, primary_key=True, autoincrement=True)
    attempt_log_id = Column(Integer, ForeignKey("attempt_log.id"), nullable=False)
    question_id = Column(String, ForeignKey("questions.question_id"), nullable=False)
    player_id = Column(String, ForeignKey("players.player_id"), nullable=False)
    generated_probe_questions = Column(JSON, nullable=True)
    player_responses = Column(JSON, nullable=True)
    identified_gap_step = Column(Integer, nullable=True)
    identified_gap_description = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
