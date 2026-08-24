"""Health endpoint — sanity check for the orchestrator."""
from fastapi import APIRouter, Request

from app.config import get_settings

router = APIRouter()


@router.get("/health")
async def health(request: Request) -> dict[str, object]:
    """Cheap liveness probe. Does NOT touch DB / Redis / Ollama per request —
    `llm_fallback` is the result the startup probe already measured, read from
    app state, so this endpoint stays free to call."""
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
        # Whether the last-resort LLM can actually answer, for exactly the same
        # reason as the line above: the failure is invisible from outside. This
        # install ran with OLLAMA_ENABLED=true for twelve weeks while the server
        # was unreachable and the model was not downloaded.
        #
        # "off"           — deliberately not configured, not a fault
        # "unreachable"   — the port does not answer
        # "model-missing" — it answers, but not for OLLAMA_MODEL
        # "unknown"       — the startup probe has not run
        #
        # A word, never a URL or a key: this endpoint is unauthenticated.
        "llm_fallback": getattr(request.app.state, "llm_fallback", "unknown"),
    }
