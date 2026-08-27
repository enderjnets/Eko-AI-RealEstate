"""The daily draft, with both of its gates in front of the human one.

`generate_draft()` produces at most one piece per call and stops itself two
ways before any text reaches the approval queue:

* **Budget.** `CONTENT_STUDIO_ENABLED` is off by default and
  `CONTENT_MAX_DRAFTS_PER_DAY` bounds the LLM spend from day one — the lesson
  from a pipeline next door that ran ten days broken because nobody had put a
  number on it.
* **Fair Housing.** The draft is filtered; a violating draft gets exactly one
  rewrite, with the offending phrases named to the model; if it still violates,
  it stays a DRAFT carrying its `violations` for a person to edit. It never
  walks itself into NEEDS_APPROVAL.

Model output is treated as hostile input: parsed, validated against a schema,
and dropped on the floor with a log line when malformed. A generation that
crashes the loop is a generation that stops tomorrow's piece too.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime, time
from typing import Any

from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models import (
    AgentSettings,
    ContentKind,
    ContentLanguage,
    ContentPiece,
    ContentStatus,
)
from app.services.content_studio import advance
from app.services.content_topics import Topic, next_topic
from app.services.fair_housing import find_violations
from app.services.llm import generate_reply

log = logging.getLogger(__name__)


class DraftPayload(BaseModel):
    """What the model must return. Anything else is a refusal, not a draft."""

    hook: str = Field(min_length=1, max_length=300)
    script: str = Field(min_length=1, max_length=4000)
    caption: str = Field(min_length=1, max_length=1500)


_SYSTEM = {
    ContentLanguage.EN: (
        "You write 30-45 second short-form video scripts for two licensed real "
        "estate agents in Denver, Colorado. Plain, warm, specific. Never "
        "invent numbers, prices or statistics. Fair Housing rules apply "
        "strictly: never describe who should live somewhere (families, "
        "professionals, any group), never characterise neighborhoods as safe, "
        "desirable or exclusive, never mention schools, churches or the kind "
        "of people in an area. Talk about process and market mechanics, not "
        "about people. Reply ONLY with JSON: "
        '{"hook": "...", "script": "...", "caption": "..."} — hook under 300 '
        "characters, script 60-120 words, caption 1-2 sentences with no "
        "hashtags."
    ),
    ContentLanguage.ES: (
        "Escribes guiones de vídeo corto (30-45 segundos) para dos agentes "
        "inmobiliarios con licencia en Denver, Colorado. Lenguaje llano, "
        "cálido y concreto. Nunca inventes números, precios ni estadísticas. "
        "Las reglas de Fair Housing aplican estrictamente: nunca describas "
        "quién debería vivir en un sitio (familias, profesionales, ningún "
        "grupo), nunca califiques barrios de seguros, deseables o exclusivos, "
        "nunca menciones escuelas, iglesias ni el tipo de gente de una zona. "
        "Habla del proceso y de la mecánica del mercado, no de personas. "
        'Responde SOLO con JSON: {"hook": "...", "script": "...", '
        '"caption": "..."} — hook de menos de 300 caracteres, guion de 60-120 '
        "palabras, caption de 1-2 frases sin hashtags."
    ),
}


def _parse(raw: str) -> DraftPayload | None:
    """The model's text, or None. Never an exception."""
    try:
        return DraftPayload.model_validate(json.loads(raw))
    except (json.JSONDecodeError, ValidationError):
        log.warning("Content writer: model returned something that is not a "
                    "draft; dropping it. Raw (truncated): %.200s", raw)
        return None


async def _ask(topic: Topic, language: ContentLanguage,
               feedback: str | None = None) -> DraftPayload | None:
    brief = topic.brief_en if language is ContentLanguage.EN else topic.brief_es
    messages: list[dict[str, Any]] = [{"role": "user", "content": brief}]
    if feedback:
        messages.append({
            "role": "user",
            "content": feedback,
        })
    try:
        result = await generate_reply(
            messages,
            system=_SYSTEM[language],
            json_mode=True,
            temperature=0.6,
            max_tokens=900,
        )
    except Exception:  # noqa: BLE001 — the loop must survive a provider outage
        log.exception("Content writer: both providers failed for topic %s",
                      topic.key)
        return None
    return _with_cta(_parse(result.text), language)


# The sentence that turns a view into a visit. Kept OUT of the model's hands on
# purpose: an LLM asked to reproduce a URL will eventually drop a character, and
# a broken link on a video that took quota to make is a silent total loss.
_CTA = {
    ContentLanguage.EN: "Thinking about selling in Denver? Start here: {url}",
    ContentLanguage.ES: "¿Estás pensando en vender en Denver? Empieza aquí: {url}",
}


def _with_cta(draft: DraftPayload | None, language: ContentLanguage) -> DraftPayload | None:
    """Append the call to action to the caption.

    Applied HERE, before the caller runs `find_violations`, so the filter sees
    the caption that will actually be published. Appending it afterwards would
    publish text the Fair Housing gate never read, which is the exact shape of
    the defect this project fixed in v0.56.0 — the filter existed and did not
    cover the live lane.

    Inert until `CONTENT_CTA_URL` is set, in the same spirit as the landing
    page: a section with no data disappears rather than inventing one. A CTA
    pointing at a domain that does not resolve yet is worse than no CTA.
    """
    if draft is None:
        return None
    url = (get_settings().CONTENT_CTA_URL or "").strip()
    if not url or url in draft.caption:
        return draft
    return draft.model_copy(
        update={"caption": f"{draft.caption.rstrip()}\n\n{_CTA[language].format(url=url)}"}
    )


async def _generated_today(db: AsyncSession) -> int:
    midnight = datetime.combine(datetime.now(UTC).date(), time.min, tzinfo=UTC)
    return (
        await db.execute(
            select(func.count())
            .select_from(ContentPiece)
            .where(
                ContentPiece.kind == ContentKind.GENERATED,
                ContentPiece.created_at >= midnight,
            )
        )
    ).scalar_one()


async def _language_for(db: AsyncSession) -> ContentLanguage:
    """Alternate through the languages the agency actually works in."""
    settings_row = (
        await db.execute(select(AgentSettings))
    ).scalars().first()
    configured = [
        lang for lang in (settings_row.languages if settings_row else [])
        if lang in ("en", "es")
    ] or ["en", "es"]
    count = (
        await db.execute(
            select(func.count())
            .select_from(ContentPiece)
            .where(ContentPiece.kind == ContentKind.GENERATED)
        )
    ).scalar_one()
    return ContentLanguage(configured[count % len(configured)])


async def generate_draft(db: AsyncSession) -> ContentPiece | None:
    """One draft, gated, or None with the reason in the log."""
    settings = get_settings()
    if not settings.CONTENT_STUDIO_ENABLED:
        return None

    made_today = await _generated_today(db)
    if made_today >= settings.CONTENT_MAX_DRAFTS_PER_DAY:
        log.info("Content writer: daily cap reached (%d/%d), not generating",
                 made_today, settings.CONTENT_MAX_DRAFTS_PER_DAY)
        return None

    topic = await next_topic(db)
    language = await _language_for(db)

    draft = await _ask(topic, language)
    if draft is None:
        return None

    violations = find_violations(
        f"{draft.hook} {draft.script} {draft.caption}", language
    )
    if violations:
        # One rewrite, with the phrases named. Not a loop: a model that failed
        # twice with the phrases in front of it is not going to converge, and
        # every retry is billed.
        phrases = ", ".join(f'"{v["phrase"]}"' for v in violations)
        log.info("Content writer: draft for %s violates fair housing (%s); "
                 "asking for one rewrite", topic.key, phrases)
        rewritten = await _ask(
            topic,
            language,
            feedback=(
                "Your draft contained phrasing that cannot appear in housing "
                f"advertising: {phrases}. Rewrite the whole draft without "
                "these phrases or anything equivalent — do not describe who "
                "an area or home is for, and do not characterise "
                "neighborhoods. Reply with the same JSON shape."
            ),
        )
        if rewritten is not None:
            draft = rewritten
            violations = find_violations(
                f"{draft.hook} {draft.script} {draft.caption}", language
            )

    piece = ContentPiece(
        kind=ContentKind.GENERATED,
        language=language,
        status=ContentStatus.DRAFT,
        hook=draft.hook,
        script=draft.script,
        caption=draft.caption,
        violations=violations or None,
        publications=[],
    )
    db.add(piece)

    if not violations:
        # Clean work moves itself to the queue; the human gate is still ahead
        # of it. Dirty work stays a DRAFT wearing its findings, for a person.
        advance(piece, ContentStatus.NEEDS_APPROVAL)

    await db.commit()
    log.info("Content writer: drafted %s (%s) -> %s", topic.key,
             language.value, piece.status.value)
    return piece
