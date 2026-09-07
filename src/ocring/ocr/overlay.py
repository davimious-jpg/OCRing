from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class OverlaySnapshot:
    capture_fps: float
    useful_fps: float
    extraction_rate: float
    verified_rate: float
    queue_depth: int
    continuity_status: str
    buffer_gb: float = 0.0
    buffer_limit_gb: float = 3.0
    warning: str = ""


def render_corner_overlay(snapshot: OverlaySnapshot) -> str:
    lines = [
        f"Capture:    {int(round(snapshot.capture_fps))} FPS",
        f"Useful:     {int(round(snapshot.useful_fps))} FPS",
        f"Extract:    {int(round(snapshot.extraction_rate))}/s",
        f"Verified:   {int(round(snapshot.verified_rate))}/s",
        f"Buffer:     {round(snapshot.buffer_gb, 1)} / {int(round(snapshot.buffer_limit_gb))} GB",
        f"Queue:      {int(snapshot.queue_depth)}",
        f"Continuity: {snapshot.continuity_status}",
    ]
    if snapshot.warning:
        lines.append(snapshot.warning)
    return "\n".join(lines)
