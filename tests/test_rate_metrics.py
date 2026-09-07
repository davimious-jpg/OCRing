from __future__ import annotations

from ocring.ocr.rate_metrics import RateMetrics


def test_rate_metrics_calculates_fps_efficiency_and_throughput() -> None:
    metrics = RateMetrics()
    metrics.record_capture(0.0)
    metrics.record_capture(1.0)
    metrics.record_capture(2.0)
    metrics.record_readable(0.0)
    metrics.record_readable(1.0)
    metrics.record_useful(1.0)
    metrics.record_extraction_event(1.5, field_types=("item_name", "item_rarity"))
    metrics.record_candidate(2.0, count=2, frame_capture_timestamp=1.0)
    metrics.record_verified(3.0, count=1, frame_capture_timestamp=1.0, candidate_produced_timestamp=2.0)

    snapshot = metrics.snapshot()

    assert round(metrics.capture_fps, 3) == 1.5
    assert round(metrics.readable_fps, 3) == 2.0
    assert round(metrics.useful_fps, 3) == 1.0
    assert round(metrics.extraction_efficiency, 3) == 0.333
    assert round(metrics.inventory_throughput, 3) == 1.0
    assert snapshot["frames_per_extraction"]["item_name"] == 3.0
    assert snapshot["latency"]["capture_to_candidate_avg"] == 1.0
    assert snapshot["latency"]["candidate_to_verified_avg"] == 1.0
    assert snapshot["latency"]["capture_to_verified_avg"] == 2.0
