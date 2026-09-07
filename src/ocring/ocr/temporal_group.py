from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class FrameObservation:
    frame_id: str
    timestamp: float
    readability_score: float
    row_signatures: dict[int, str]


@dataclass(frozen=True)
class TemporalObservation:
    row_slot: int
    support_count: int
    agreement_score: float
    best_source_frame_id: str
    source_frame_ids: tuple[str, ...]
    source_row_ids: tuple[str, ...]
    signature: str
    released_frame_ids: tuple[str, ...] = ()


class SlidingTemporalGrouper:
    def __init__(self, *, window_size: int = 8, overlap_ratio: float = 0.5) -> None:
        self.window_size = max(1, window_size)
        self.overlap_ratio = overlap_ratio
        self.step_size = max(1, int(round(self.window_size * (1.0 - overlap_ratio))))
        self._frames: list[FrameObservation] = []
        self._next_window_start = 0

    def add_frame(self, frame: FrameObservation) -> tuple[tuple[TemporalObservation, ...], ...]:
        self._frames.append(frame)
        emitted: list[tuple[TemporalObservation, ...]] = []
        while len(self._frames) >= self._next_window_start + self.window_size:
            window = self._frames[self._next_window_start : self._next_window_start + self.window_size]
            emitted.append(self._emit_window(window))
            self._next_window_start += self.step_size
        return tuple(emitted)

    def flush(self) -> tuple[tuple[TemporalObservation, ...], ...]:
        if not self._frames:
            return ()
        if self._next_window_start == 0 and len(self._frames) < self.window_size:
            return (self._emit_window(self._frames),)
        if self._next_window_start < len(self._frames):
            window = self._frames[max(0, len(self._frames) - self.window_size) :]
            if window:
                return (self._emit_window(window),)
        return ()

    def _emit_window(self, window: list[FrameObservation]) -> tuple[TemporalObservation, ...]:
        grouped: dict[tuple[int, str], list[tuple[FrameObservation, float]]] = {}
        for frame in window:
            for row_slot, signature in frame.row_signatures.items():
                grouped.setdefault((row_slot, signature), []).append((frame, frame.readability_score))

        observations: list[TemporalObservation] = []
        window_length = max(1, len(window))
        for (row_slot, signature), entries in sorted(grouped.items(), key=lambda item: item[0][0]):
            best_frame = sorted(entries, key=lambda item: (item[1], item[0].timestamp, item[0].frame_id), reverse=True)[0][0]
            source_frame_ids = tuple(entry.frame_id for entry, _ in entries)
            source_row_ids = tuple(f"{entry.frame_id}:row:{row_slot}" for entry, _ in entries)
            observations.append(
                TemporalObservation(
                    row_slot=row_slot,
                    support_count=len(entries),
                    agreement_score=round(len(entries) / window_length, 3),
                    best_source_frame_id=best_frame.frame_id,
                    source_frame_ids=source_frame_ids,
                    source_row_ids=source_row_ids,
                    signature=signature,
                    released_frame_ids=tuple(
                        entry.frame_id
                        for entry, _ in entries
                        if entry.frame_id != best_frame.frame_id
                    ),
                )
            )
        return tuple(observations)
