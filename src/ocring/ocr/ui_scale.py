from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RelativePoint:
    x: float
    y: float


class UIScaleNormalizer:
    def to_relative(self, x: int, y: int, *, window_width: int, window_height: int) -> RelativePoint:
        return RelativePoint(
            x=round(x / max(1, window_width), 4),
            y=round(y / max(1, window_height), 4),
        )

    def from_anchor(
        self,
        anchor_x: float,
        anchor_y: float,
        offset_x: int,
        offset_y: int,
        *,
        window_width: int,
        window_height: int,
    ) -> RelativePoint:
        return self.to_relative(
            round(anchor_x * window_width) + offset_x,
            round(anchor_y * window_height) + offset_y,
            window_width=window_width,
            window_height=window_height,
        )

