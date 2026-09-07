from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

from ocring.ocr.detection import detect_inventory_region


def test_detect_inventory_region_finds_dark_panel(tmp_path: Path) -> None:
    image_path = tmp_path / "frame.png"
    image = Image.new("RGB", (1000, 700), color=(220, 220, 220))
    draw = ImageDraw.Draw(image)
    draw.rectangle((200, 120, 820, 620), fill=(25, 25, 25))
    image.save(image_path)

    region, detector_name = detect_inventory_region(image_path)

    assert detector_name == "dark_panel_projection"
    assert region.x1 <= 210
    assert region.y1 <= 130
    assert region.x2 >= 810
    assert region.y2 >= 610

