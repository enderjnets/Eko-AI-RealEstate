from __future__ import annotations

from app.models import ContentLanguage
from app.services.content_calculated import plan_for, scene_fields


def test_calculated_pieces_have_eight_distinct_visual_beats() -> None:
    plan = plan_for(4, ContentLanguage.EN)
    scenes = scene_fields(plan)

    assert len(scenes) == 8
    assert len({visual.casefold() for visual, _ in scenes}) == 8
    assert len({text.casefold() for _, text in scenes}) == 8


def test_calculated_visuals_forbid_readable_generated_details() -> None:
    plan = plan_for(4, ContentLanguage.EN)

    for visual, _ in scene_fields(plan):
        lowered = visual.casefold()
        assert "no readable" in lowered or "no signs" in lowered
        assert "denver" in lowered or "front range" in lowered
