from __future__ import annotations

from ocring.ocr.queue_limits import default_queue_limits, queue_has_capacity


def test_queue_limits_define_all_stage_caps() -> None:
    limits = default_queue_limits()

    assert limits.capture_queue > limits.database_queue
    assert limits.ocr_queue > 0
    assert limits.ai_queue > 0


def test_queue_capacity_helper_obeys_stage_limits() -> None:
    limits = default_queue_limits()

    assert queue_has_capacity("ocr_queue", limits.ocr_queue - 1, limits) is True
    assert queue_has_capacity("ocr_queue", limits.ocr_queue, limits) is False
