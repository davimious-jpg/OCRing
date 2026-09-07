from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class AcceptanceMetrics:
    capture_continuity: float
    item_name_precision: float
    required_field_completeness: float
    false_inventory_insertion: float
    average_extraction_latency: float
    dropped_continuity_anchors: int
    ram_usage: float
    game_performance_impact: float


def compute_acceptance_metrics(
    *,
    captured_frames: int,
    continuity_frames: int,
    correct_item_names: int,
    evaluated_item_names: int,
    complete_required_fields: int,
    total_required_fields: int,
    false_insertions: int,
    total_insertions: int,
    latencies_ms: list[float],
    dropped_continuity_anchors: int,
    ram_usage_mb: float,
    game_performance_impact_pct: float,
) -> AcceptanceMetrics:
    return AcceptanceMetrics(
        capture_continuity=_ratio(continuity_frames, captured_frames),
        item_name_precision=_ratio(correct_item_names, evaluated_item_names),
        required_field_completeness=_ratio(complete_required_fields, total_required_fields),
        false_inventory_insertion=_ratio(false_insertions, total_insertions),
        average_extraction_latency=round(sum(latencies_ms) / len(latencies_ms), 3) if latencies_ms else 0.0,
        dropped_continuity_anchors=dropped_continuity_anchors,
        ram_usage=round(ram_usage_mb, 3),
        game_performance_impact=round(game_performance_impact_pct, 3),
    )


def _ratio(numerator: int, denominator: int) -> float:
    if denominator <= 0:
        return 0.0
    return round(numerator / denominator, 3)

