from __future__ import annotations

from ocring.ocr.acceptance_metrics import compute_acceptance_metrics


def test_acceptance_metrics_compute_product_success_values() -> None:
    metrics = compute_acceptance_metrics(
        captured_frames=100,
        continuity_frames=92,
        correct_item_names=45,
        evaluated_item_names=50,
        complete_required_fields=180,
        total_required_fields=200,
        false_insertions=1,
        total_insertions=100,
        latencies_ms=[100.0, 120.0, 110.0],
        dropped_continuity_anchors=2,
        ram_usage_mb=512.5,
        game_performance_impact_pct=3.2,
    )

    assert metrics.capture_continuity == 0.92
    assert metrics.item_name_precision == 0.9
    assert metrics.required_field_completeness == 0.9
    assert metrics.false_inventory_insertion == 0.01
    assert metrics.average_extraction_latency == 110.0
