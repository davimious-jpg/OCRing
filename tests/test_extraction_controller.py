from __future__ import annotations

from ocring.ocr.extraction_controller import ExtractionRateController


def test_controller_idle_state_decreases_extraction_rate() -> None:
    controller = ExtractionRateController()

    state = controller.evaluate(
        capture_fps=60.0,
        readable_fps=5.0,
        useful_fps=0.0,
        frame_queue_depth=0,
        ocr_queue_depth=0,
        motion_level=0.0,
        continuity_health="OK",
        cpu_load=0.2,
        gpu_load=0.1,
    )

    assert state.should_extract is False
    assert state.target_extraction_rate < 5.0


def test_controller_normal_scroll_increases_extraction_rate() -> None:
    controller = ExtractionRateController()

    state = controller.evaluate(
        capture_fps=60.0,
        readable_fps=18.0,
        useful_fps=12.0,
        frame_queue_depth=1,
        ocr_queue_depth=1,
        motion_level=0.3,
        continuity_health="OK",
        cpu_load=0.35,
        gpu_load=0.2,
    )

    assert state.should_extract is True
    assert state.target_extraction_rate >= 12.0
    assert state.warning == ""


def test_controller_fast_scroll_does_not_over_escalate_when_motion_is_high() -> None:
    controller = ExtractionRateController()

    state = controller.evaluate(
        capture_fps=60.0,
        readable_fps=10.0,
        useful_fps=15.0,
        frame_queue_depth=2,
        ocr_queue_depth=2,
        motion_level=0.8,
        continuity_health="OK",
        cpu_load=0.3,
        gpu_load=0.2,
    )

    assert state.should_extract is True
    assert state.target_extraction_rate <= 15.0


def test_controller_warns_on_unreadable_scroll() -> None:
    controller = ExtractionRateController()

    state = controller.evaluate(
        capture_fps=60.0,
        readable_fps=4.0,
        useful_fps=6.0,
        frame_queue_depth=3,
        ocr_queue_depth=2,
        motion_level=0.9,
        continuity_health="WEAK",
        cpu_load=0.4,
        gpu_load=0.2,
    )

    assert state.warning == "WARN: SLOW DOWN"
