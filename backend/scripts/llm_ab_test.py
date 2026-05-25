#!/usr/bin/env python3
"""Side-by-side LLM A/B for Spanish real-estate prompts.

Runs 5 prompts representative of the realtor agent's job through BOTH providers
(Kimi 2.6 and MiniMax M2.7) and prints outputs + latency + token counts so you
can eyeball which one feels better before committing the model choice to MVP.

Requires both KIMI_API_KEY and MINIMAX_API_KEY set in .env. Run from inside
the backend container:

  docker compose exec backend python scripts/llm_ab_test.py
"""
from __future__ import annotations

import asyncio
import os
import sys
import time
from dataclasses import dataclass
from typing import Any

# Allow running with cwd=/app (typical inside the container).
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from anthropic import AsyncAnthropic  # noqa: E402

from app.config import get_settings  # noqa: E402


SYSTEM_PROMPT = (
    "Eres el asistente virtual de la inmobiliaria Inmobiliaria Pérez en Madrid. "
    "Atiendes en castellano natural, cercano y profesional. Tu objetivo es captar "
    "leads, entender qué buscan (alquiler / compra / tasación), capturar zona y "
    "presupuesto, y agendar visitas cuando proceda. Respuestas cortas (1-3 frases) "
    "salvo que pidan detalles. Nunca inventes datos sobre propiedades concretas; "
    "si no sabes algo, dilo y ofrece consultar con un agente humano."
)


PROMPTS: list[tuple[str, list[dict[str, str]]]] = [
    (
        "1. Saludo inicial — lead curiosea",
        [{"role": "user", "content": "Hola, vi vuestro anuncio en Idealista. ¿Qué tenéis en Chamberí?"}],
    ),
    (
        "2. Captura intent — alquiler + presupuesto",
        [
            {"role": "user", "content": "Hola"},
            {"role": "assistant", "content": "¡Hola! ¿En qué puedo ayudarte? ¿Buscas alquiler, compra o quieres tasar una propiedad?"},
            {"role": "user", "content": "Alquiler, busco piso de 2 habitaciones en Malasaña por 1200 al mes máximo."},
        ],
    ),
    (
        "3. Manejo de objeción — precio percibido alto",
        [
            {"role": "user", "content": "Vi un piso vuestro en Lavapiés por 1500€. Me parece carísimo, ¿no se puede negociar?"},
        ],
    ),
    (
        "4. Sugerir cita de visita",
        [
            {"role": "user", "content": "Hola, me interesa el piso de Conde Duque que tenéis publicado. ¿Puedo ir a verlo?"},
        ],
    ),
    (
        "5. Follow-up post-visita (24h después)",
        [
            {"role": "assistant", "content": "Hola Juan, soy el asistente de Inmobiliaria Pérez. Ayer visitaste el piso de Conde Duque. ¿Qué tal te pareció?"},
            {"role": "user", "content": "Pues la verdad es que me gustó la zona pero el piso me resultó pequeño. ¿Tenéis algo más grande por la misma zona?"},
        ],
    ),
]


@dataclass
class Run:
    provider: str
    model: str
    latency_ms: int
    input_tokens: int
    output_tokens: int
    text: str
    error: str | None = None


def _client(base_url: str, api_key: str) -> AsyncAnthropic:
    return AsyncAnthropic(api_key=api_key, base_url=base_url, timeout=45.0, max_retries=0)


async def _run_one(client: AsyncAnthropic, model: str, provider: str, messages: list[dict[str, str]]) -> Run:
    t0 = time.perf_counter()
    try:
        resp = await client.messages.create(
            model=model,
            system=SYSTEM_PROMPT,
            messages=messages,  # type: ignore[arg-type]
            max_tokens=400,
            temperature=0.7,
        )
        elapsed = int((time.perf_counter() - t0) * 1000)
        text = "".join(getattr(b, "text", "") for b in resp.content if getattr(b, "type", "") == "text").strip()
        usage: Any = getattr(resp, "usage", None)
        return Run(
            provider=provider,
            model=model,
            latency_ms=elapsed,
            input_tokens=getattr(usage, "input_tokens", 0) or 0,
            output_tokens=getattr(usage, "output_tokens", 0) or 0,
            text=text,
        )
    except Exception as exc:  # noqa: BLE001
        elapsed = int((time.perf_counter() - t0) * 1000)
        return Run(
            provider=provider,
            model=model,
            latency_ms=elapsed,
            input_tokens=0,
            output_tokens=0,
            text="",
            error=f"{type(exc).__name__}: {exc}",
        )


def _bar() -> None:
    print("─" * 100)


def _truncate(text: str, n: int = 800) -> str:
    return text if len(text) <= n else text[:n].rstrip() + " …(truncated)"


async def main() -> int:
    s = get_settings()
    if not s.KIMI_API_KEY:
        print("ERROR: KIMI_API_KEY not set in .env", file=sys.stderr)
        return 1
    if not s.MINIMAX_API_KEY:
        print("ERROR: MINIMAX_API_KEY not set in .env", file=sys.stderr)
        return 1

    print(f"\n=== Eko AI Realtors · LLM A/B (Spanish prompts) ===")
    print(f"  Kimi    base={s.KIMI_BASE_URL}    model={s.KIMI_MODEL}")
    print(f"  MiniMax base={s.MINIMAX_BASE_URL} model={s.MINIMAX_MODEL}\n")

    kimi = _client(s.KIMI_BASE_URL, s.KIMI_API_KEY)
    minimax = _client(s.MINIMAX_BASE_URL, s.MINIMAX_API_KEY)

    totals = {"kimi": {"lat": 0, "in": 0, "out": 0, "ok": 0, "err": 0},
              "minimax": {"lat": 0, "in": 0, "out": 0, "ok": 0, "err": 0}}

    for title, msgs in PROMPTS:
        _bar()
        print(f"\n## {title}\n")
        print(f"USER: {msgs[-1]['content']}\n")

        kimi_run, mm_run = await asyncio.gather(
            _run_one(kimi, s.KIMI_MODEL, "kimi", msgs),
            _run_one(minimax, s.MINIMAX_MODEL, "minimax", msgs),
        )

        for run in (kimi_run, mm_run):
            stat = totals[run.provider]
            stat["lat"] += run.latency_ms
            stat["in"] += run.input_tokens
            stat["out"] += run.output_tokens
            if run.error:
                stat["err"] += 1
            else:
                stat["ok"] += 1

            print(f"### {run.provider.upper():<8} ({run.latency_ms} ms · in={run.input_tokens} out={run.output_tokens})")
            if run.error:
                print(f"  ERROR: {run.error}\n")
            else:
                print(f"  {_truncate(run.text)}\n")

    _bar()
    print("\n## Totals\n")
    for prov, t in totals.items():
        n = t["ok"] + t["err"] or 1
        print(
            f"  {prov.upper():<8}  ok={t['ok']}/{t['ok']+t['err']}  "
            f"avg_latency={t['lat']//n} ms  "
            f"total_tokens=in:{t['in']} out:{t['out']}"
        )
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
