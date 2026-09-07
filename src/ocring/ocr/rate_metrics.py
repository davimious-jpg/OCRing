from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any


@dataclass
class RateMetrics:
    captured_timestamps: list[float] = field(default_factory=list)
    readable_timestamps: list[float] = field(default_factory=list)
    useful_timestamps: list[float] = field(default_factory=list)
    extraction_timestamps: list[float] = field(default_factory=list)
    candidate_timestamps: list[float] = field(default_factory=list)
    verified_timestamps: list[float] = field(default_factory=list)
    field_extraction_counts: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    latency_capture_to_candidate: list[float] = field(default_factory=list)
    latency_candidate_to_verified: list[float] = field(default_factory=list)
    latency_capture_to_verified: list[float] = field(default_factory=list)

    def record_capture(self, timestamp: float) -> None:
        self.captured_timestamps.append(float(timestamp))

    def record_readable(self, timestamp: float) -> None:
        self.readable_timestamps.append(float(timestamp))

    def record_useful(self, timestamp: float) -> None:
        self.useful_timestamps.append(float(timestamp))

    def record_extraction_event(self, timestamp: float, *, field_types: tuple[str, ...] = ()) -> None:
        self.extraction_timestamps.append(float(timestamp))
        for field_type in dict.fromkeys(field_types):
            self.field_extraction_counts[str(field_type)] += 1

    def record_candidate(
        self,
        timestamp: float,
        *,
        count: int = 1,
        frame_capture_timestamp: float | None = None,
    ) -> None:
        for _ in range(max(0, count)):
            self.candidate_timestamps.append(float(timestamp))
            if frame_capture_timestamp is not None:
                self.latency_capture_to_candidate.append(float(timestamp) - float(frame_capture_timestamp))

    def record_verified(
        self,
        timestamp: float,
        *,
        count: int = 1,
        frame_capture_timestamp: float | None = None,
        candidate_produced_timestamp: float | None = None,
    ) -> None:
        for _ in range(max(0, count)):
            self.verified_timestamps.append(float(timestamp))
            if candidate_produced_timestamp is not None:
                self.latency_candidate_to_verified.append(float(timestamp) - float(candidate_produced_timestamp))
            if frame_capture_timestamp is not None:
                self.latency_capture_to_verified.append(float(timestamp) - float(frame_capture_timestamp))

    @property
    def capture_fps(self) -> float:
        return _rate(self.captured_timestamps)

    @property
    def readable_fps(self) -> float:
        return _rate(self.readable_timestamps)

    @property
    def useful_fps(self) -> float:
        return _rate(self.useful_timestamps)

    @property
    def extraction_rate(self) -> float:
        return _rate(self.extraction_timestamps)

    @property
    def candidate_rate(self) -> float:
        return _rate(self.candidate_timestamps)

    @property
    def verified_rate(self) -> float:
        return _rate(self.verified_timestamps)

    @property
    def extraction_efficiency(self) -> float:
        if not self.captured_timestamps:
            return 0.0
        return len(self.useful_timestamps) / len(self.captured_timestamps)

    @property
    def inventory_throughput(self) -> float:
        return self.verified_rate

    @property
    def frames_per_extraction(self) -> dict[str, float]:
        captured = len(self.captured_timestamps)
        result: dict[str, float] = {}
        for field_type, count in self.field_extraction_counts.items():
            result[field_type] = 0.0 if count <= 0 else captured / count
        return result

    def snapshot(self) -> dict[str, Any]:
        return {
            "capture_fps": round(self.capture_fps, 3),
            "readable_fps": round(self.readable_fps, 3),
            "useful_fps": round(self.useful_fps, 3),
            "extraction_rate": round(self.extraction_rate, 3),
            "candidate_rate": round(self.candidate_rate, 3),
            "verified_rate": round(self.verified_rate, 3),
            "extraction_efficiency": round(self.extraction_efficiency, 3),
            "inventory_throughput": round(self.inventory_throughput, 3),
            "frames_per_extraction": {key: round(value, 3) for key, value in self.frames_per_extraction.items()},
            "latency": {
                "capture_to_candidate_avg": round(_average(self.latency_capture_to_candidate), 3),
                "candidate_to_verified_avg": round(_average(self.latency_candidate_to_verified), 3),
                "capture_to_verified_avg": round(_average(self.latency_capture_to_verified), 3),
            },
        }


def _rate(timestamps: list[float]) -> float:
    if not timestamps:
        return 0.0
    if len(timestamps) == 1:
        return 1.0
    span = timestamps[-1] - timestamps[0]
    if span <= 0:
        return float(len(timestamps))
    return len(timestamps) / span


def _average(values: list[float]) -> float:
    if not values:
        return 0.0
    return sum(values) / len(values)
