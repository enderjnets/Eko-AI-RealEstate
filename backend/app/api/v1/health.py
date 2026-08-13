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
        # Whether the public capture form's captcha is actually verifying.
        #
        # Worth a field of its own because the failure is invisible from
        # outside: with the secret unset the endpoint accepts every submission
        # without checking, which looks exactly like a captcha that works. The
        # only other signal was one line in the startup log, so a later rebuild
        # that dropped the value would go unnoticed until the spam arrived.
        # A boolean, not the value — this endpoint is unauthenticated.
        "captcha": "on" if (s.TURNSTILE_SECRET or "").strip() else "off",
    }
