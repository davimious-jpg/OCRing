from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

from ocring.ocr.models import FieldKind, OcrAttempt, OcrEngineStatus, PreparedFieldCrop, PreprocessVariant, Rect
from ocring.ocr.ocr_runner import run_ocr_attempts


def test_ocr_runner_returns_unavailable_attempts_without_engine(tmp_path: Path, monkeypatch) -> None:
    from ocring.ocr import ocr_runner as ocr_runner_module

    image_path = tmp_path / "frame.png"
    Image.new("RGB", (400, 300), color=(200, 200, 200)).save(image_path)
    monkeypatch.setattr(ocr_runner_module.shutil, "which", lambda _name: None)
    monkeypatch.setattr(ocr_runner_module, "_rapidocr_available", lambda: False)

    crops = (
        PreparedFieldCrop(
            crop_id="crop-1",
            row_id="row-1",
            field_kind=FieldKind.ITEM_NAME,
            variant=PreprocessVariant.HIGH_CONTRAST,
            source_region=Rect(10, 10, 200, 50),
            width=190,
            height=40,
            stats={"mean_luma": 120.0},
        ),
    )

    attempts = run_ocr_attempts(image_path, crops, max_attempts=4)

    assert len(attempts) == 1
    assert attempts[0].status is OcrEngineStatus.UNAVAILABLE
    assert "NO_LOCAL_OCR_ENGINE" in attempts[0].reasons


def test_ocr_runner_respects_max_attempts(tmp_path: Path) -> None:
    image_path = tmp_path / "frame.png"
    Image.new("RGB", (400, 300), color=(200, 200, 200)).save(image_path)

    crops = tuple(
        PreparedFieldCrop(
            crop_id=f"crop-{index}",
            row_id=f"row-{index}",
            field_kind=FieldKind.ITEM_NAME,
            variant=PreprocessVariant.HIGH_CONTRAST,
            source_region=Rect(10, 10, 200, 50),
            width=190,
            height=40,
            stats={"mean_luma": 120.0},
        )
        for index in range(10)
    )

    attempts = run_ocr_attempts(image_path, crops, max_attempts=3)

    assert len(attempts) == 3


def test_ocr_runner_prioritizes_field_coverage_before_extra_name_variants(tmp_path: Path, monkeypatch) -> None:
    from ocring.ocr import ocr_runner as ocr_runner_module

    image_path = tmp_path / "frame.png"
    Image.new("RGB", (400, 300), color=(200, 200, 200)).save(image_path)

    class FakeRapidEngine:
        name = "rapidocr"

        def run(self, image_path: Path, crop: PreparedFieldCrop) -> OcrAttempt:
            del image_path
            return OcrAttempt(
                crop_id=crop.crop_id,
                row_id=crop.row_id,
                field_kind=crop.field_kind,
                variant=crop.variant,
                engine_name="rapidocr",
                status=OcrEngineStatus.OK,
                raw_text=crop.field_kind.value,
                normalized_text=crop.field_kind.value,
                confidence=0.8,
                reasons=(),
            )

    monkeypatch.setattr(ocr_runner_module.shutil, "which", lambda _name: None)
    monkeypatch.setattr(ocr_runner_module, "_rapidocr_available", lambda: True)
    monkeypatch.setattr(ocr_runner_module, "RapidOcrEngine", FakeRapidEngine)

    crops = (
        PreparedFieldCrop(
            crop_id="name-a",
            row_id="row-1",
            field_kind=FieldKind.ITEM_NAME,
            variant=PreprocessVariant.HIGH_CONTRAST,
            source_region=Rect(10, 10, 200, 50),
            width=190,
            height=40,
            stats={"mean_luma": 120.0},
        ),
        PreparedFieldCrop(
            crop_id="name-b",
            row_id="row-1",
            field_kind=FieldKind.ITEM_NAME,
            variant=PreprocessVariant.SHARPENED,
            source_region=Rect(10, 10, 200, 50),
            width=190,
            height=40,
            stats={"mean_luma": 120.0},
        ),
        PreparedFieldCrop(
            crop_id="count-a",
            row_id="row-1",
            field_kind=FieldKind.ITEM_COUNT,
            variant=PreprocessVariant.HIGH_CONTRAST,
            source_region=Rect(210, 10, 260, 50),
            width=50,
            height=40,
            stats={"mean_luma": 120.0},
        ),
        PreparedFieldCrop(
            crop_id="type-a",
            row_id="row-1",
            field_kind=FieldKind.ITEM_TYPE,
            variant=PreprocessVariant.HIGH_CONTRAST,
            source_region=Rect(270, 10, 360, 50),
            width=90,
            height=40,
            stats={"mean_luma": 120.0},
        ),
        PreparedFieldCrop(
            crop_id="rarity-a",
            row_id="row-1",
            field_kind=FieldKind.ITEM_RARITY,
            variant=PreprocessVariant.HIGH_CONTRAST,
            source_region=Rect(365, 10, 390, 50),
            width=25,
            height=40,
            stats={"mean_luma": 120.0},
        ),
    )

    attempts = run_ocr_attempts(image_path, crops, max_attempts=4)

    assert len(attempts) == 4
    attempted_fields = {attempt.field_kind for attempt in attempts}
    assert FieldKind.ITEM_NAME in attempted_fields
    assert FieldKind.ITEM_COUNT in attempted_fields
    assert FieldKind.ITEM_TYPE in attempted_fields
    assert FieldKind.ITEM_RARITY in attempted_fields


def test_ocr_runner_uses_rapidocr_when_available(tmp_path: Path, monkeypatch) -> None:
    from ocring.ocr import ocr_runner as ocr_runner_module

    image_path = tmp_path / "frame.png"
    Image.new("RGB", (400, 300), color=(200, 200, 200)).save(image_path)

    crop = PreparedFieldCrop(
        crop_id="crop-1",
        row_id="row-1",
        field_kind=FieldKind.ITEM_NAME,
        variant=PreprocessVariant.HIGH_CONTRAST,
        source_region=Rect(10, 10, 200, 50),
        width=190,
        height=40,
        stats={"mean_luma": 120.0},
    )

    class FakeRapidEngine:
        name = "rapidocr"

        def run(self, image_path: Path, crop: PreparedFieldCrop) -> OcrAttempt:
            del image_path
            return OcrAttempt(
                crop_id=crop.crop_id,
                row_id=crop.row_id,
                field_kind=crop.field_kind,
                variant=crop.variant,
                engine_name="rapidocr",
                status=OcrEngineStatus.OK,
                raw_text="Power Bore",
                normalized_text="Power Bore",
                confidence=0.77,
                reasons=(),
            )

    monkeypatch.setattr(ocr_runner_module.shutil, "which", lambda _name: None)
    monkeypatch.setattr(ocr_runner_module, "_rapidocr_available", lambda: True)
    monkeypatch.setattr(ocr_runner_module, "RapidOcrEngine", FakeRapidEngine)

    attempts = run_ocr_attempts(image_path, (crop,), max_attempts=1)

    assert len(attempts) == 1
    assert attempts[0].engine_name == "rapidocr"
    assert attempts[0].normalized_text == "Power Bore"


def test_ocr_runner_classifies_rarity_from_color_region(tmp_path: Path) -> None:
    image_path = tmp_path / "rarity.png"
    image = Image.new("RGB", (240, 80), color=(16, 16, 16))
    draw = ImageDraw.Draw(image)
    draw.rectangle((20, 10, 120, 60), fill=(156, 39, 176))
    image.save(image_path)

    crop = PreparedFieldCrop(
        crop_id="crop-rarity",
        row_id="row-1",
        field_kind=FieldKind.ITEM_RARITY,
        variant=PreprocessVariant.HIGH_CONTRAST,
        source_region=Rect(20, 10, 120, 60),
        width=100,
        height=50,
        stats={"mean_luma": 90.0},
    )

    attempts = run_ocr_attempts(image_path, (crop,), max_attempts=1)

    assert len(attempts) == 1
    assert attempts[0].engine_name == "color_classifier"
    assert attempts[0].normalized_text == "Epic"
    assert attempts[0].status is OcrEngineStatus.OK


def test_ocr_runner_rejects_low_saturation_rarity_background(tmp_path: Path) -> None:
    image_path = tmp_path / "rarity-background.png"
    image = Image.new("RGB", (240, 80), color=(64, 128, 128))
    image.save(image_path)

    crop = PreparedFieldCrop(
        crop_id="crop-rarity-bg",
        row_id="row-1",
        field_kind=FieldKind.ITEM_RARITY,
        variant=PreprocessVariant.HIGH_CONTRAST,
        source_region=Rect(20, 10, 120, 60),
        width=100,
        height=50,
        stats={"mean_luma": 90.0},
    )

    attempts = run_ocr_attempts(image_path, (crop,), max_attempts=1)

    assert len(attempts) == 1
    assert attempts[0].engine_name == "color_classifier"
    assert attempts[0].normalized_text == ""
    assert attempts[0].status is OcrEngineStatus.ERROR
