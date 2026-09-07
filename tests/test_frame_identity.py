from __future__ import annotations

from ocring.ocr.frame_identity import FrameIdentity, PipelineClock


def test_frame_identity_includes_pipeline_timebase() -> None:
    identity = FrameIdentity.create(
        session_id="s1",
        window_id="wnd-1",
        profile_version="1.0",
        region_id="inventory-main",
        monotonic_time=12.5,
    )

    assert identity.session_id == "s1"
    assert identity.window_id == "wnd-1"
    assert identity.profile_version == "1.0"
    assert identity.monotonic_time == 12.5


def test_pipeline_clock_is_monotonic() -> None:
    clock = PipelineClock()

    first = clock.now()
    second = clock.now()

    assert second >= first

