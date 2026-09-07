from __future__ import annotations

from ocring.ocr.ui_scale import UIScaleNormalizer


def test_ui_scale_normalizer_converts_fixed_pixels_to_relative() -> None:
    normalizer = UIScaleNormalizer()
    point = normalizer.to_relative(420, 180, window_width=1000, window_height=1000)

    assert point.x == 0.42
    assert point.y == 0.18


def test_ui_scale_normalizer_supports_anchor_coordinates() -> None:
    normalizer = UIScaleNormalizer()
    point = normalizer.from_anchor(0.4, 0.1, 20, 80, window_width=1000, window_height=1000)

    assert point.x == 0.42
    assert point.y == 0.18

