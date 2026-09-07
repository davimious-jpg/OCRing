from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

from ocring.ocr.cropper import prepare_row_field_crops, prepare_selected_detail_field_crops
from ocring.ocr.layout import segment_inventory_rows
from ocring.ocr.models import FieldKind, FrameImage, FrameRecord, PreprocessVariant, Rect
from ocring.ocr.models import PreprocessVariant, Rect
from ocring.ocr.preprocess import preprocess_inventory_region


def test_preprocess_inventory_region_creates_expected_variants(tmp_path: Path) -> None:
    image_path = tmp_path / "frame.png"
    image = Image.new("RGB", (600, 400), color=(200, 200, 200))
    draw = ImageDraw.Draw(image)
    draw.rectangle((100, 80, 500, 320), fill=(30, 30, 30))
    draw.text((140, 120), "Power Bore IV", fill=(245, 245, 245))
    image.save(image_path)

    variants = preprocess_inventory_region(image_path, Rect(100, 80, 500, 320))

    assert {variant.variant for variant in variants} == {
        PreprocessVariant.GRAYSCALE,
        PreprocessVariant.HIGH_CONTRAST,
        PreprocessVariant.SHARPENED,
    }
    assert all(variant.width == 400 for variant in variants)
    assert all(variant.height == 240 for variant in variants)


def test_prepare_row_field_crops_creates_variant_per_field(tmp_path: Path) -> None:
    image_path = tmp_path / "frame.png"
    image = Image.new("RGB", (800, 600), color=(210, 210, 210))
    draw = ImageDraw.Draw(image)
    draw.rectangle((120, 100, 680, 500), fill=(20, 20, 20))
    draw.text((160, 140), "Power Bore IV", fill=(245, 245, 245))
    image.save(image_path)

    frame = FrameRecord(
        frame_id="frame-1",
        session_id="session-1",
        profile_id="defiance",
        timestamp_utc="2026-08-15T00:00:00+00:00",
        image=FrameImage(path=str(image_path), width=800, height=600),
        inventory_region=Rect(120, 100, 680, 500),
    )
    row_zones = segment_inventory_rows(frame, max_rows=2)

    crops = prepare_row_field_crops(image_path, row_zones, profile_id="defiance")

    expected_count = len(row_zones) * 2 * len(PreprocessVariant)
    assert len(crops) == expected_count
    assert any(crop.field_kind is FieldKind.ITEM_NAME for crop in crops)
    assert any(crop.field_kind is FieldKind.ITEM_RARITY for crop in crops)
    assert all(crop.field_kind in {FieldKind.ITEM_NAME, FieldKind.ITEM_RARITY} for crop in crops)
    assert all(crop.width > 0 and crop.height > 0 for crop in crops)


def test_prepare_row_field_crops_uses_profile_defined_defiance_field_zones(tmp_path: Path) -> None:
    image_path = tmp_path / "frame.png"
    image = Image.new("RGB", (1000, 400), color=(32, 32, 32))
    image.save(image_path)

    frame = FrameRecord(
        frame_id="frame-2",
        session_id="session-2",
        profile_id="defiance",
        timestamp_utc="2026-08-16T00:00:00+00:00",
        image=FrameImage(path=str(image_path), width=1000, height=400),
        inventory_region=Rect(100, 40, 900, 360),
    )
    row_zone = segment_inventory_rows(frame, max_rows=1)[0]

    crops = prepare_row_field_crops(image_path, (row_zone,), profile_id="defiance")

    first_by_kind = {}
    for crop in crops:
        first_by_kind.setdefault(crop.field_kind, crop)
    assert first_by_kind[FieldKind.ITEM_NAME].source_region.x1 == row_zone.row_bounds.x1 + int(row_zone.row_bounds.width * 0.16)
    assert first_by_kind[FieldKind.ITEM_NAME].source_region.x2 == row_zone.row_bounds.x1 + int(row_zone.row_bounds.width * 0.63)
    assert first_by_kind[FieldKind.ITEM_NAME].source_region.y1 == row_zone.row_bounds.y1 + int(row_zone.row_bounds.height * 0.2)
    assert first_by_kind[FieldKind.ITEM_NAME].source_region.y2 == row_zone.row_bounds.y1 + int(row_zone.row_bounds.height * 0.8)
    assert first_by_kind[FieldKind.ITEM_RARITY].source_region == first_by_kind[FieldKind.ITEM_NAME].source_region
    assert FieldKind.ITEM_SYNERGY not in first_by_kind
    assert FieldKind.ITEM_COUNT not in first_by_kind
    assert FieldKind.ITEM_TYPE not in first_by_kind


def test_prepare_selected_detail_field_crops_uses_profile_defined_detail_regions(tmp_path: Path) -> None:
    image_path = tmp_path / "frame.png"
    image = Image.new("RGB", (1366, 768), color=(24, 24, 24))
    image.save(image_path)

    inventory_region = Rect(51, 63, 982, 654)
    crops = prepare_selected_detail_field_crops(
        image_path,
        inventory_region,
        selected_row_id="frame-1:row:11",
        profile_id="defiance",
    )

    first_by_kind = {}
    for crop in crops:
        first_by_kind.setdefault(crop.field_kind, crop)

    assert first_by_kind[FieldKind.ITEM_NAME].source_region.x1 == int(1366 * 0.527)
    assert first_by_kind[FieldKind.ITEM_NAME].source_region.y1 == int(768 * 0.112)
    assert first_by_kind[FieldKind.ITEM_TYPE].source_region.x1 == int(1366 * 0.677)
    assert first_by_kind[FieldKind.ITEM_TYPE].source_region.y2 == int(768 * 0.344)
    assert first_by_kind[FieldKind.ITEM_SYNERGY].source_region.x2 == int(1366 * 0.663)
    assert first_by_kind[FieldKind.ITEM_RARITY].source_region == first_by_kind[FieldKind.ITEM_NAME].source_region


def test_prepare_selected_detail_field_crops_supports_named_right_panel_layout(tmp_path: Path) -> None:
    image_path = tmp_path / "frame.png"
    image = Image.new("RGB", (1366, 768), color=(24, 24, 24))
    image.save(image_path)

    crops = prepare_selected_detail_field_crops(
        image_path,
        Rect(51, 63, 982, 654),
        selected_row_id="frame-1:row:11",
        profile_id="defiance",
        layout_name="right_single_panel",
    )

    first_by_kind = {}
    for crop in crops:
        first_by_kind.setdefault(crop.field_kind, crop)

    assert first_by_kind[FieldKind.ITEM_NAME].source_region.x1 == int(1366 * 0.791)
    assert first_by_kind[FieldKind.ITEM_NAME].source_region.y1 == int(768 * 0.141)
    assert first_by_kind[FieldKind.ITEM_TYPE].source_region.x2 == int(1366 * 0.943)
    assert first_by_kind[FieldKind.ITEM_SYNERGY].source_region.x1 == int(1366 * 0.754)
