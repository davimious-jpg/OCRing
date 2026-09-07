from __future__ import annotations

from ocring.ocr.layout import segment_inventory_rows
from ocring.ocr.models import FieldKind, FrameImage, FrameRecord, Rect


def test_segment_inventory_rows_creates_expected_zone_count() -> None:
    frame = FrameRecord(
        frame_id="frame-1",
        session_id="session-1",
        profile_id="defiance",
        timestamp_utc="2026-08-15T00:00:00+00:00",
        image=FrameImage(path="frame.png", width=1920, height=1080),
        inventory_region=Rect(300, 100, 1500, 900),
    )

    zones = segment_inventory_rows(frame, max_rows=8)

    assert len(zones) == 8
    assert FieldKind.ITEM_NAME in zones[0].fields
    assert FieldKind.ITEM_COUNT in zones[0].fields

