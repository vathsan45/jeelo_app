import os
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

ROOT = Path(__file__).resolve().parent.parent.parent  # project root (d:/elo_fable)
DEFAULT_DB_PATH = ROOT / "data" / "app.db"
DB_PATH = Path(os.environ.get("ELO_DB_PATH", DEFAULT_DB_PATH))

engine = create_engine(
    f"sqlite:///{DB_PATH}",
    connect_args={"check_same_thread": False},
)
SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)
Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
