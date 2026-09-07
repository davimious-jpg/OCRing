from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class AnchorMatch:
    anchor_name: str
    x: int
    y: int
    confidence: float


class AnchorRecoveryEngine:
    def recover_roi(
        self,
        saved_roi: dict[str, int],
        frame: dict[str, Any],
        *,
        anchors: tuple[dict[str, Any], ...],
    ) -> dict[str, int]:
        frame_anchors = {
            str(anchor.get("name")): anchor
            for anchor in tuple(frame.get("anchors", ()))
        }
        for anchor in anchors:
            name = str(anchor.get("name"))
            if name not in frame_anchors:
                continue
            saved_x = int(anchor.get("x", 0))
            saved_y = int(anchor.get("y", 0))
            current = frame_anchors[name]
            delta_x = int(current.get("x", 0)) - saved_x
            delta_y = int(current.get("y", 0)) - saved_y
            return {
                "x1": int(saved_roi.get("x1", 0)) + delta_x,
                "y1": int(saved_roi.get("y1", 0)) + delta_y,
                "x2": int(saved_roi.get("x2", 0)) + delta_x,
                "y2": int(saved_roi.get("y2", 0)) + delta_y,
            }
        return dict(saved_roi)

