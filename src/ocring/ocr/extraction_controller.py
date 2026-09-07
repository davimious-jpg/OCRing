from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ExtractionControlState:
    target_extraction_rate: float
    should_extract: bool
    warning: str
    continuity_status: str


class ExtractionRateController:
    def __init__(
        self,
        *,
        readable_threshold: float = 8.0,
        target_latency: float = 0.5,
    ) -> None:
        self.readable_threshold = readable_threshold
        self.target_latency = target_latency

    def evaluate(
        self,
        *,
        capture_fps: float,
        readable_fps: float,
        useful_fps: float,
        frame_queue_depth: int,
        ocr_queue_depth: int,
        motion_level: float,
        continuity_health: str,
        cpu_load: float,
        gpu_load: float,
        target_latency: float | None = None,
    ) -> ExtractionControlState:
        target_latency = self.target_latency if target_latency is None else target_latency
        redundancy = 0.0 if capture_fps <= 0 else max(0.0, 1.0 - min(1.0, useful_fps / max(capture_fps, 1e-6)))
        base_rate = min(capture_fps, max(0.0, useful_fps + (readable_fps * 0.25)))
        if redundancy >= 0.5:
            base_rate *= 0.5
        if frame_queue_depth > 4 or ocr_queue_depth > 4:
            base_rate *= 0.75
        if cpu_load > 0.85 or gpu_load > 0.85:
            base_rate *= 0.7
        if motion_level >= 0.7 and readable_fps < self.readable_threshold:
            base_rate = min(base_rate, useful_fps)
        elif useful_fps > 0:
            base_rate = max(base_rate, useful_fps)
        if continuity_health.upper() not in {"OK", "OVERLAP_DETECTED", "STABLE"}:
            base_rate = max(base_rate, useful_fps)
        if target_latency > 0 and ocr_queue_depth > 4:
            base_rate = min(base_rate, max(0.5, ocr_queue_depth / target_latency))
        warning = ""
        if readable_fps < self.readable_threshold and motion_level >= 0.7:
            warning = "WARN: SLOW DOWN"
        should_extract = useful_fps > 0 and base_rate >= 0.5
        continuity_status = "OK" if continuity_health.upper() in {"OK", "OVERLAP_DETECTED", "STABLE"} else continuity_health
        return ExtractionControlState(
            target_extraction_rate=round(max(0.0, base_rate), 3),
            should_extract=should_extract,
            warning=warning,
            continuity_status=continuity_status,
        )
