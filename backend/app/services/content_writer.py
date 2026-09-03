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
import re
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
from app.services.content_studio import advance, not_our_rail, text_violations
from app.services.content_topics import Topic, next_topic, rotation_index
from app.services.lang_guard import wrong_language
from app.services.llm import generate_reply

log = logging.getLogger(__name__)


class Scene(BaseModel):
    """One shot: what is on screen, and the few words over it.

    `visual_prompt` is what an image model is asked for, so it goes through the
    same Fair Housing filter as the script AND through a denylist of person
    descriptors. Housing advertising is regulated in pictures as much as in
    words: a video whose every frame shows one kind of household says something
    about who is welcome, and it says it without a single sentence anybody
    could edit.
    """

    visual_prompt: str = Field(min_length=1, max_length=200)
    on_screen_text: str = Field(min_length=1, max_length=60)


class DraftPayload(BaseModel):
    """What the model must return. Anything else is a refusal, not a draft."""

    hook: str = Field(min_length=1, max_length=300)
    script: str = Field(min_length=1, max_length=4000)
    caption: str = Field(min_length=1, max_length=1500)
    # Optional so a model that answers with the older shape still produces a
    # usable draft: the piece simply has no lane B plan and stays a clip
    # somebody films. Requiring them would turn a prompt drift into zero
    # content.
    scenes: list[Scene] = Field(default_factory=list, max_length=8)
    # What the narrator says, WHEN it differs from the written script. The
    # prompt no longer asks for it: a model given both writes the same words
    # twice, which doubled the longest field in every response and truncated
    # the first real generation into an unparseable draft. Kept in the schema
    # because a model that volunteers one costs nothing, and because the
    # difference that mattered — "$450,000" becoming words — is done
    # deterministically by `worker/spoken.py`, not by asking nicely.
    narration: str | None = Field(default=None, max_length=4000)


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
        "hashtags, plus \"scenes\": 4 to 6 objects with \"visual_prompt\" and "
        "\"on_screen_text\". A visual_prompt describes a PLACE or an OBJECT — "
        "a house, a street, the Front Range, keys, a document, a for-sale sign. "
        "NEVER describe people in it: no families, couples, children, "
        "professionals, retirees, or anyone's appearance or background. Never "
        "write a web address or a phone number in any field."
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
        "palabras, caption de 1-2 frases sin hashtags, más \"scenes\": de 4 a 6 objetos "
        "con \"visual_prompt\" y \"on_screen_text\". Un visual_prompt describe un "
        "LUGAR o un OBJETO — una casa, una calle, las montañas, unas llaves, un "
        "documento, un cartel de se vende. NUNCA describas personas: ni "
        "familias, ni parejas, ni niños, ni profesionales, ni jubilados, ni el "
        "aspecto ni el origen de nadie. Nunca escribas una dirección web ni un "
        "teléfono en ningún campo."
    ),
}


_FENCE = re.compile(r"^\s*```(?:json)?\s*|\s*```\s*$", re.IGNORECASE)


def _parse(raw: str) -> DraftPayload | None:
    """The model's text, or None. Never an exception.

    The fence is stripped first. Asked for JSON, a model returns JSON — and
    sometimes returns it wrapped in a markdown code block, because that is how
    it has seen JSON written a million times. `json.loads` cannot read that,
    and the first real rewrite in production was discarded over three
    backticks: a generation billed, a draft lost, and a log line nobody was
    watching as the only trace.
    """
    try:
        return DraftPayload.model_validate(json.loads(_FENCE.sub("", raw)))
    except (json.JSONDecodeError, ValidationError):
        log.warning("Content writer: model returned something that is not a "
                    "draft; dropping it. Raw (truncated): %.200s", raw)
        return None


async def _ask(topic: Topic, language: ContentLanguage,
               feedback: str | None = None,
               cta_index: int = 0) -> DraftPayload | None:
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
            # 900 was the cap when a draft was three short strings. Lane B
            # added a scene plan, and the first real generation came back
            # TRUNCATED mid-sentence and was dropped as malformed — a whole
            # generation billed for nothing, with the reason visible only in a
            # log line. Sized for the shape actually asked for, with room for a
            # model that formats its JSON generously.
            max_tokens=2000,
        )
    except Exception:  # noqa: BLE001 — the loop must survive a provider outage
        log.exception("Content writer: both providers failed for topic %s",
                      topic.key)
        return None
    return _with_cta(_parse(result.text), language, cta_index)


# The sentence that turns a view into a visit. Kept OUT of the model's hands on
# purpose: an LLM asked to reproduce a URL will eventually drop a character, and
# a broken link on a video that took quota to make is a silent total loss.
_CTA = {
    ContentLanguage.EN: "Thinking about selling in Denver? Start here: {url}",
    ContentLanguage.ES: "¿Estás pensando en vender en Denver? Empieza aquí: {url}",
}

# The domain AS IT IS SPOKEN, and that is the whole trick. `worker/spoken.py`
# strips anything shaped like a web address before the narrator sees it —
# rightly: read aloud, a URL is "denverhomestory dot com" at best. Written as
# words there is nothing to strip, the narrator says it naturally, and it
# reaches the yellow captions for free because those are transcribed from the
# audio rather than from the script.
_SPOKEN_DOMAIN = {
    ContentLanguage.EN: "Denver Home Story dot com",
    ContentLanguage.ES: "Denver Home Story punto com",
}

# Three sign-offs, rotated. One fixed line would be heard thirty times a month
# by anyone who follows the channel; a line the model invents each day is a
# line that one day promises more than the funnel delivers. Written by hand,
# and deliberately promising nothing beyond the site existing: the owner's own
# draft said "they will answer all your questions", and what actually happens
# is that Natalia calls back within a few hours.
_SPOKEN_CTA = {
    ContentLanguage.EN: (
        "Buying or selling in Denver? Visit {domain}.",
        "If you want to know what your home is worth today, start at {domain}.",
        "Let's talk about your numbers. {domain}.",
    ),
    ContentLanguage.ES: (
        "¿Compras o vendes en Denver? Visita {domain}.",
        "Si quieres saber cuánto vale tu casa hoy, empieza en {domain}.",
        "Hablemos de tus números. {domain}.",
    ),
}

# Said in the caption of every generated piece, because saying it is cheaper
# than being asked. All three platforms take `isAiGenerated` through Buffer as
# well, and it is sent; the caption is where a viewer can actually read it.
#
# **It names the voice, not the pictures, because that is what is true.** This
# read "Contains AI-generated visuals" until a published caption was checked
# against the video it described: every picture in it is a licensed photograph
# from Pexels, and nothing in the frame was generated. The narration is
# synthetic in every piece this lane makes, whatever draws the pictures. A
# disclosure that overstates is still a false statement on the channel of two
# licensed agents — and this one was about to go out three times.
# If Kling ever draws the scenes, the visuals belong back in this sentence.
_AI_DISCLOSURE = {
    ContentLanguage.EN: "Narrated with a synthetic voice.",
    ContentLanguage.ES: "Narrado con una voz sintética.",
}


def _with_cta(
    draft: DraftPayload | None,
    language: ContentLanguage,
    cta_index: int = 0,
) -> DraftPayload | None:
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
    caption = draft.caption.rstrip()

    url = (get_settings().CONTENT_CTA_URL or "").strip()
    if url and url not in caption:
        caption = f"{caption}\n\n{_CTA[language].format(url=url)}"

    # Only when there is a plan to generate pictures from. A clip somebody
    # filmed is not AI-generated, and saying it is would be a false statement
    # on the agency's own channel.
    disclosure = _AI_DISCLOSURE[language]
    if draft.scenes and disclosure not in caption:
        caption = f"{caption}\n{disclosure}"

    # The spoken sign-off, appended to the narration for the same reason and in
    # the same place as the caption's: the caller runs the Fair Housing filter
    # on what comes back, and `_all_violations` reads this narration through
    # `_scene_plan`. Appended anywhere later — in `_scene_plan`, or in the
    # worker — and the words a person hears would be words no filter read.
    #
    # **Materialised from `script`, not appended to `narration`.** The model
    # does not return a `narration` field at all: measured on every generated
    # piece in production, `length(narration) == length(script)` exactly,
    # because `_scene_plan` falls back. Appending to the raw None would have
    # produced a narration consisting of the sign-off ALONE — a four-second
    # video that says nothing but "Buying or selling in Denver?".
    narration = draft.narration
    if draft.scenes and url:
        lines = _SPOKEN_CTA[language]
        sign_off = lines[cta_index % len(lines)].format(
            domain=_SPOKEN_DOMAIN[language]
        )
        spoken = (draft.narration or draft.script or "").rstrip()
        if sign_off not in spoken:
            narration = f"{spoken} {sign_off}".strip()

    if caption == draft.caption and narration == draft.narration:
        return draft
    return draft.model_copy(update={"caption": caption, "narration": narration})


def _all_violations(
    draft: DraftPayload, language: ContentLanguage
) -> list[dict[str, str]]:
    """Everything wrong with this draft, in one list.

    The Fair Housing checks come from `content_studio.text_violations`, which
    is the SAME function the console and the publish gate use — three copies of
    "which fields count" is how a field gets added to the product and forgotten
    by the filter.

    The language check lives here because it is about a draft rather than about
    a stored piece: it reads the NARRATION, because the text that will be
    spoken is the one the audience hears, and a correct hook over a script in
    another language is exactly the bug this guard was written for.
    """
    found = text_violations(
        hook=draft.hook,
        script=draft.script,
        caption=draft.caption,
        scenes=_scene_plan(draft),
        language=language,
    )

    spoken = draft.narration or draft.script
    reason = wrong_language(spoken, language.value)
    if reason is not None:
        found.append({"phrase": reason, "category": "language"})
    return found


def _scene_plan(draft: DraftPayload) -> dict[str, object] | None:
    """The shot list, as plain JSON for the column. None when there is none.

    A dict with named keys rather than a bare list, because the narration is
    not a scene and appending it to the list would make every reader special-
    case the last element.
    """
    if not draft.scenes:
        return None
    return {
        "narration": draft.narration or draft.script,
        "scenes": [
            {
                "visual_prompt": scene.visual_prompt,
                "on_screen_text": scene.on_screen_text,
            }
            for scene in draft.scenes
        ],
    }


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

    # Whose rail is this. `run_for_every_org` visits every tenant by design,
    # and without this the demo organization got its own draft every day — a
    # second LLM bill for content nobody would ever look at, and which the
    # publisher would refuse anyway.
    blocked = await not_our_rail()
    if blocked is not None:
        return None

    made_today = await _generated_today(db)
    if made_today >= settings.CONTENT_MAX_DRAFTS_PER_DAY:
        log.info("Content writer: daily cap reached (%d/%d), not generating",
                 made_today, settings.CONTENT_MAX_DRAFTS_PER_DAY)
        return None

    topic = await next_topic(db)
    language = await _language_for(db)
    # Read once and passed to BOTH calls below. The rewrite path replaces the
    # draft wholesale, so a sign-off chosen inside only the first call would be
    # lost on exactly the drafts that needed a second look.
    cta_index = await rotation_index(db)

    draft = await _ask(topic, language, cta_index=cta_index)
    if draft is None:
        return None

    violations = _all_violations(draft, language)
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
            cta_index=cta_index,
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
            violations = _all_violations(draft, language)

    piece = ContentPiece(
        kind=ContentKind.GENERATED,
        language=language,
        status=ContentStatus.DRAFT,
        hook=draft.hook,
        script=draft.script,
        caption=draft.caption,
        scenes=_scene_plan(draft),
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
