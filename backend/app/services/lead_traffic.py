"""Exclude explicitly noncommercial first touches from agency work."""
from sqlalchemy import and_, func, or_

from app.models import Lead


def is_noncommercial(meta: object) -> bool:
    attribution = meta.get("attribution") if isinstance(meta, dict) else None
    if not isinstance(attribution, dict):
        return False
    return attribution.get("traffic_class") in ("test", "automated") or (
        attribution.get("utm_source") == "eko_qa" and attribution.get("utm_medium") == "test"
    )


def commercial_lead():
    source = func.json_extract_path_text(Lead.meta, "attribution", "utm_source")
    medium = func.json_extract_path_text(Lead.meta, "attribution", "utm_medium")
    traffic_class = func.json_extract_path_text(Lead.meta, "attribution", "traffic_class")
    return and_(
        or_(func.coalesce(source, "") != "eko_qa", func.coalesce(medium, "") != "test"),
        func.coalesce(traffic_class, "unknown").not_in(("test", "automated")),
    )
