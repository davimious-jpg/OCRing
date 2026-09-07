from __future__ import annotations

from ocring.ocr.models import FrameImage, FrameQualityAction, FrameRecord, Rect
from ocring.ocr.quality import assess_frame_quality


def test_quality_defers_small_inventory_region() -> None:
    frame = FrameRecord(
        frame_id="frame-1",
        session_id="session-1",
        profile_id="defiance",
        timestamp_utc="2026-08-15T00:00:00+00:00",
        image=FrameImage(path="frame.png", width=1920, height=1080),
        inventory_region=Rect(10, 10, 210, 120),
    )

    quality = assess_frame_quality(frame)

    assert quality.action in {FrameQualityAction.DEFER, FrameQualityAction.DROP}
    assert quality.reasons
