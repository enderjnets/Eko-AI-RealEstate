"""File import — extract business leads from an uploaded file in (almost) any format.

extract_text routes by extension to a small, stable parser: PDF → pypdf, XLSX →
openpyxl, images (jpg/png/…) → OCR (pytesseract + system tesseract-ocr), and
CSV/TXT/JSON/HTML/anything-else → utf-8 decode (HTML tags stripped). The extracted
text is then structured into leads by the LLM (json_mode), degrading to [] on
empty/garbled input — never crashing (mirrors classifier.py).
"""
from __future__ import annotations

import io
import json
import logging
import os
import re

from app.services.discovery import BusinessDTO, sanitize_email
from app.services.llm import LLMUnavailable, generate_reply

log = logging.getLogger(__name__)

_IMAGE_EXT = {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".tif", ".tiff"}
_MAX_TEXT = 12000  # chars fed to the LLM


def extract_text(filename: str, content: bytes) -> str:
    """Best-effort conversion of an uploaded file to plain text."""
    ext = os.path.splitext(filename or "")[1].lower()
    if ext in _IMAGE_EXT:
        return _ocr_image(content)
    if ext == ".pdf":
        return _pdf_text(content)
    if ext in (".xlsx", ".xlsm"):
        return _xlsx_text(content)
    # csv / txt / tsv / json / html / unknown → decode; strip tags for HTML.
    try:
        text = content.decode("utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        return ""
    if ext in (".html", ".htm"):
        text = re.sub(r"<[^>]+>", " ", text)
        text = re.sub(r"\s+", " ", text)
    return text.strip()


def _pdf_text(content: bytes) -> str:
    try:
        from pypdf import PdfReader

        reader = PdfReader(io.BytesIO(content))
        return "\n".join((page.extract_text() or "") for page in reader.pages).strip()
    except Exception as exc:  # noqa: BLE001
        log.warning("PDF text extraction failed: %s", exc)
        return ""


def _xlsx_text(content: bytes) -> str:
    try:
        import openpyxl

        wb = openpyxl.load_workbook(io.BytesIO(content), read_only=True, data_only=True)
        lines: list[str] = []
        for ws in wb.worksheets:
            for row in ws.iter_rows(values_only=True):
                cells = [str(c) for c in row if c is not None]
                if cells:
                    lines.append(", ".join(cells))
        return "\n".join(lines).strip()
    except Exception as exc:  # noqa: BLE001
        log.warning("XLSX extraction failed: %s", exc)
        return ""


def _ocr_image(content: bytes) -> str:
    try:
        import pytesseract
        from PIL import Image

        return (pytesseract.image_to_string(Image.open(io.BytesIO(content))) or "").strip()
    except Exception as exc:  # noqa: BLE001
        log.warning("OCR failed: %s", exc)
        return ""


_EXTRACT_SYSTEM = (
    "Sos un extractor de contactos/negocios. Recibís el texto de una base de datos o lista "
    "de contactos (en cualquier formato) y extraés TODOS los contactos como un array JSON. "
    "Cada item DEBE tener estas claves: "
    '{"business_name": string, "phone": string|null, "email": string|null, '
    '"website": string|null, "address": string|null, "city": string|null, "category": string|null}. '
    "Usá el nombre del negocio o de la persona como business_name. Si no encontrás contactos, "
    "devolvé []. SALIDA: únicamente el array JSON, sin markdown ni texto alrededor."
)


async def extract_leads(text: str) -> list[BusinessDTO]:
    """Turn extracted text into BusinessDTOs via the LLM. [] on any failure."""
    text = (text or "").strip()
    if not text:
        return []
    try:
        result = await generate_reply(
            messages=[{"role": "user", "content": text[:_MAX_TEXT]}],
            system=_EXTRACT_SYSTEM,
            max_tokens=2000,
            temperature=0.2,
            json_mode=True,
        )
    except LLMUnavailable as exc:
        log.error("File-import extraction failed — LLM unavailable: %s", exc)
        return []

    match = re.search(r"\[.*\]", result.text, re.DOTALL)
    if not match:
        # Length, not content: the model is quoting an uploaded lead list back,
        # so the first 200 characters are somebody's name and phone number.
        log.warning("File-import: no JSON array in LLM output (%d chars)", len(result.text))
        return []
    try:
        rows = json.loads(match.group(0))
    except json.JSONDecodeError:
        log.warning("File-import: invalid JSON in LLM output (%d chars)", len(result.text))
        return []
    if not isinstance(rows, list):
        return []

    out: list[BusinessDTO] = []
    for r in rows:
        if not isinstance(r, dict):
            continue
        name = str(r.get("business_name") or r.get("name") or "").strip()
        if not name:
            continue
        phone = r.get("phone")
        out.append(
            BusinessDTO(
                business_name=name,
                source="import",
                category=(str(r["category"]).strip() if r.get("category") else None),
                email=sanitize_email(r.get("email")),
                phone=(str(phone).strip() if phone else None),
                website=(str(r["website"]).strip() if r.get("website") else None),
                address=(str(r["address"]).strip() if r.get("address") else None),
                city=(str(r["city"]).strip() if r.get("city") else None),
                raw=r,
            )
        )
    return out
