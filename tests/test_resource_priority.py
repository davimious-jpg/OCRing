from __future__ import annotations

from ocring.ocr.resource_priority import PRIORITY_HIERARCHY, adjust_for_game_fps


def test_resource_priority_preserves_hierarchy_and_reduces_load_when_fps_drops() -> None:
    adjustment = adjust_for_game_fps(baseline_fps=60.0, current_fps=40.0)

    assert PRIORITY_HIERARCHY[0] == "Do not harm game responsiveness"
    assert adjustment.retained_fps_scale < 1.0
    assert adjustment.ocr_concurrency_scale < 1.0
    assert adjustment.preprocessing_quality_scale < 1.0

