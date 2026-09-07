from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageStat

from .models import Rect


def detect_inventory_region(image_path: Path) -> tuple[Rect, str]:
    with Image.open(image_path) as image:
        rgb = image.convert("RGB")
        width, height = rgb.size
        candidate = _detect_dark_panel(rgb)
        if candidate is not None:
            return candidate, "dark_panel_projection"
        return _default_inventory_region(width, height), "default_projection"


def _default_inventory_region(width: int, height: int) -> Rect:
    return Rect(
        x1=int(width * 0.15),
        y1=int(height * 0.15),
        x2=int(width * 0.85),
        y2=int(height * 0.88),
    )


def _detect_dark_panel(image: Image.Image) -> Rect | None:
    grayscale = image.convert("L")
    width, height = grayscale.size
    threshold = max(12, int(ImageStat.Stat(grayscale).mean[0] * 0.82))

    left = width
    top = height
    right = 0
    bottom = 0
    found = False
    step = max(2, min(width, height) // 200)
    pixels = grayscale.load()

    for y in range(0, height, step):
        for x in range(0, width, step):
            if pixels[x, y] <= threshold:
                found = True
                left = min(left, x)
                top = min(top, y)
                right = max(right, x)
                bottom = max(bottom, y)

    if not found:
        return None

    pad = max(8, min(width, height) // 100)
    rect = Rect(
        x1=max(0, left - pad),
        y1=max(0, top - pad),
        x2=min(width, right + pad),
        y2=min(height, bottom + pad),
    )

    if rect.area < int(width * height * 0.08):
        return None
    if rect.width < int(width * 0.25) or rect.height < int(height * 0.2):
        return None
    return rect

