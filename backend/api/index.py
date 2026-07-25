"""Vercel entrypoint. Vercel's zero-config Python builder expects a serverless
function under api/ — this just re-exports the real FastAPI app so nothing
about app/main.py needs to know it's being deployed this way."""

from app.main import app  # noqa: F401
