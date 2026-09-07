from __future__ import annotations

from ocring.ocr.color_normalization import ColorNormalizer


def test_color_normalizer_uses_tolerant_color_regions() -> None:
    normalizer = ColorNormalizer()
    normalized = normalizer.normalize((120, 80, 200), hdr_detected=True, gamma=2.4, brightness=1.05)

    assert normalized.hdr_detected is True
    assert normalizer.within_tolerant_region((100, 98, 202), (110, 110, 210), tolerance=15) is True
    assert normalizer.within_tolerant_region((50, 50, 50), (110, 110, 210), tolerance=15) is False

