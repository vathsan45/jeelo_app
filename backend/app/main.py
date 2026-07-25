import json
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .database import Base, SessionLocal, engine
from .models import Question
from .routers import players, quiz, reports, risk_arena

QUESTIONS_MASTER = Path(__file__).resolve().parent.parent / "data" / "questions_master.json"


def seed_questions_if_empty():
    db = SessionLocal()
    try:
        if db.query(Question).count() > 0:
            return
        data = json.loads(QUESTIONS_MASTER.read_text(encoding="utf-8"))
        for q in data:
            db.add(Question(
                question_id=q["question_id"],
                text=q["text"],
                options=q["options"],
                correct_answer=q["correct_answer"],
                subject=q["subject"],
                topic=q["topic"],
                sub_topic=q["sub_topic"],
                difficulty_tag=q["difficulty_tag"],
                theta_q=float(q["theta_q_seed"]),
                marking_scheme=q["marking_scheme"],
                solution_steps=q["solution_steps"],
                formulas_used=q["formulas_used"],
            ))
        db.commit()
        print(f"Seeded {len(data)} questions from {QUESTIONS_MASTER.name}")
    finally:
        db.close()


@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(bind=engine)
    seed_questions_if_empty()
    yield


app = FastAPI(title="JEE Physics Adaptive Learning API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    # local demo: Vite may land on 5173/5174/... depending on what's free
    allow_origin_regex=r"http://(localhost|127\.0\.0\.1):\d+",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(players.router)
app.include_router(quiz.router)
app.include_router(risk_arena.router)
app.include_router(reports.router)


@app.get("/health")
def health():
    db = SessionLocal()
    try:
        question_count = db.query(Question).count()
    finally:
        db.close()
    return {"status": "ok", "questions_loaded": question_count}
