import os
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

# Loaded here (not just in llm.py) because main.py imports this module first,
# before anything that would otherwise trigger load_dotenv() — without this,
# DATABASE_URL from backend/.env wouldn't be visible yet when the engine
# below gets built.
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

BACKEND_ROOT = Path(__file__).resolve().parent.parent  # backend/
DEFAULT_SQLITE_PATH = BACKEND_ROOT / "data" / "app.db"

# Priority, deliberately in this order:
#   1. ELO_DB_PATH — every test script (test_elo.py, test_phase2/3/4.py) sets
#      this to an isolated scratch SQLite file. It must always win over
#      DATABASE_URL, or running tests would silently hit the real production
#      Postgres database instead of a throwaway file.
#   2. DATABASE_URL — Neon/Postgres, used in production (Vercel) and locally
#      once configured, for a real persistent shared database.
#   3. Local SQLite default — zero-config fallback for local dev.
_elo_db_path_override = os.environ.get("ELO_DB_PATH")
_database_url = os.environ.get("DATABASE_URL")

if _elo_db_path_override:
    engine = create_engine(
        f"sqlite:///{_elo_db_path_override}",
        connect_args={"check_same_thread": False},
    )
elif _database_url:
    # some providers hand out the older "postgres://" scheme, which older
    # SQLAlchemy/psycopg2 versions reject — normalize defensively
    url = _database_url.replace("postgres://", "postgresql://", 1)
    engine = create_engine(url, pool_pre_ping=True)
else:
    engine = create_engine(
        f"sqlite:///{DEFAULT_SQLITE_PATH}",
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
