from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class NormalizedColor:
    red: int
    green: int
    blue: int
    hdr_detected: bool
    gamma: float
    brightness: float


class ColorNormalizer:
    def normalize(
        self,
        rgb: tuple[int, int, int],
        *,
        hdr_detected: bool = False,
        gamma: float = 2.2,
        brightness: float = 1.0,
    ) -> NormalizedColor:
        adjusted = tuple(max(0, min(255, round(channel / max(0.5, gamma / 2.2) * brightness))) for channel in rgb)
        return NormalizedColor(adjusted[0], adjusted[1], adjusted[2], hdr_detected, gamma, brightness)

    def within_tolerant_region(
        self,
        observed: tuple[int, int, int],
        expected: tuple[int, int, int],
        *,
        tolerance: int = 24,
    ) -> bool:
        return all(abs(left - right) <= tolerance for left, right in zip(observed, expected))

