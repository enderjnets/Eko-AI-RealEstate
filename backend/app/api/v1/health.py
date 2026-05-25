"""Health endpoint — sanity check for the orchestrator."""
from fastapi import APIRouter

from app.config import get_settings

router = APIRouter()


@router.get("/health")
async def health() -> dict[str, object]:
    """Cheap liveness probe. Does NOT touch DB / Redis / Ollama — that is the readiness probe."""
    s = get_settings()
    return {
        "status": "ok",
        "app": s.APP_NAME,
        "version": s.APP_VERSION,
        "env": s.APP_ENV,
    }
