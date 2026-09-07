from __future__ import annotations

from dataclasses import dataclass


PRIORITY_HIERARCHY = (
    "Do not harm game responsiveness",
    "Do not lose continuity",
    "Preserve unresolved evidence",
    "Maximize extraction throughput",
    "Improve visual/OCR quality",
)


@dataclass(frozen=True)
class ResourceAdjustment:
    retained_fps_scale: float
    ocr_concurrency_scale: float
    ai_concurrency_scale: float
    preprocessing_quality_scale: float


def adjust_for_game_fps(*, baseline_fps: float, current_fps: float) -> ResourceAdjustment:
    if baseline_fps <= 0 or current_fps >= baseline_fps * 0.9:
        return ResourceAdjustment(1.0, 1.0, 1.0, 1.0)
    if current_fps >= baseline_fps * 0.75:
        return ResourceAdjustment(0.85, 0.8, 0.8, 0.9)
    return ResourceAdjustment(0.6, 0.5, 0.4, 0.7)

