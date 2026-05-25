"""Eko AI Inmobiliario — FastAPI entrypoint."""
import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1 import health
from app.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    description=(
        "Backend for Eko AI Inmobiliario — the on-prem AI agent for real-estate offices. "
        "WhatsApp + local LLM (Ollama) + lead capture + intent classification."
    ),
    docs_url="/docs" if settings.DEBUG else None,
    redoc_url=None,
)

# CORS: dev allows localhost; production tightens via env.
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Routers
app.include_router(health.router, prefix="/api/v1", tags=["health"])


@app.get("/")
async def root() -> dict[str, str]:
    """Tiny root endpoint so a healthcheck against / never returns 404."""
    return {"app": settings.APP_NAME, "version": settings.APP_VERSION, "docs": "/docs"}
