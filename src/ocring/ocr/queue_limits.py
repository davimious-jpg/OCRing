from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class QueueLimits:
    capture_queue: int
    frame_analysis_queue: int
    ocr_queue: int
    ai_queue: int
    correctness_queue: int
    database_queue: int


def default_queue_limits() -> QueueLimits:
    return QueueLimits(
        capture_queue=120,
        frame_analysis_queue=60,
        ocr_queue=32,
        ai_queue=16,
        correctness_queue=24,
        database_queue=12,
    )


def queue_has_capacity(stage: str, depth: int, limits: QueueLimits | None = None) -> bool:
    limits = limits or default_queue_limits()
    limit_map = {
        "capture_queue": limits.capture_queue,
        "frame_analysis_queue": limits.frame_analysis_queue,
        "ocr_queue": limits.ocr_queue,
        "ai_queue": limits.ai_queue,
        "correctness_queue": limits.correctness_queue,
        "database_queue": limits.database_queue,
    }
    return int(depth) < limit_map[stage]
