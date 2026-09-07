from __future__ import annotations

import logging
import shutil
import subprocess
import tempfile
import importlib.util
import json
from pathlib import Path
from typing import Protocol

from PIL import Image, ImageEnhance, ImageFilter

from .models import OcrAttempt, OcrEngineStatus, OcrEngineSummary, PreparedFieldCrop, PreprocessVariant


LOGGER = logging.getLogger(__name__)


class OcrEngine(Protocol):
    name: str

    def run(self, image_path: Path, crop: PreparedFieldCrop) -> OcrAttempt:
        ...


def run_ocr_attempts(
    image_path: Path,
    prepared_crops: tuple[PreparedFieldCrop, ...],
    *,
    max_attempts: int = 60,
) -> tuple[OcrAttempt, ...]:
    selected = _select_crops(prepared_crops, max_attempts=max_attempts)
    attempts: list[OcrAttempt] = []
    engine = None
    for crop in selected:
        if crop.field_kind.value == "item_rarity":
            attempts.append(_classify_rarity_attempt(image_path, crop))
            continue
        if engine is None:
            engine = _resolve_engine()
        attempts.append(engine.run(image_path, crop))
    return tuple(attempts)


def get_ocr_engine_summary() -> OcrEngineSummary:
    tesseract_path = shutil.which("tesseract")
    if tesseract_path:
        return OcrEngineSummary(engine_name="tesseract", available=True, reason=tesseract_path)
    if _rapidocr_available():
        return OcrEngineSummary(engine_name="rapidocr", available=True, reason="rapidocr_onnxruntime")
    return OcrEngineSummary(engine_name="unavailable", available=False, reason="NO_LOCAL_OCR_ENGINE")


class TesseractEngine:
    name = "tesseract"

    def __init__(self, binary_path: str) -> None:
        self.binary_path = binary_path

    def run(self, image_path: Path, crop: PreparedFieldCrop) -> OcrAttempt:
        try:
            with Image.open(image_path) as image:
                crop_image = _render_crop_variant(image.convert("RGB"), crop)
                with tempfile.TemporaryDirectory(prefix="ocring_ocr_") as temp_dir:
                    temp_root = Path(temp_dir)
                    input_path = temp_root / "crop.png"
                    output_base = temp_root / "ocr_output"
                    crop_image.save(input_path)
                    command = [
                        self.binary_path,
                        str(input_path),
                        str(output_base),
                        "--psm",
                        _page_segmentation_mode(crop.field_kind),
                    ]
                    if crop.field_kind.value == "item_count":
                        command.extend(["-c", "tessedit_char_whitelist=0123456789xX"])
                    completed = subprocess.run(
                        command,
                        capture_output=True,
                        text=True,
                        timeout=2.0,
                        check=False,
                    )
                    if completed.returncode != 0:
                        return _unavailable_attempt(
                            crop,
                            engine_name=self.name,
                            status=OcrEngineStatus.ERROR,
                            reasons=("OCR_ENGINE_ERROR",),
                        )
                    text_path = output_base.with_suffix(".txt")
                    raw_text = text_path.read_text(encoding="utf-8") if text_path.exists() else ""
                    normalized = _normalize_text(raw_text, count_mode=crop.field_kind.value == "item_count")
                    LOGGER.info(
                        "OCR[%s] %s %s -> %s",
                        self.name,
                        crop.row_id,
                        crop.field_kind.value,
                        normalized or "<empty>",
                    )
                    return OcrAttempt(
                        crop_id=crop.crop_id,
                        row_id=crop.row_id,
                        field_kind=crop.field_kind,
                        variant=crop.variant,
                        engine_name=self.name,
                        status=OcrEngineStatus.OK,
                        raw_text=raw_text.strip(),
                        normalized_text=normalized,
                        confidence=0.55 if normalized else 0.15,
                        reasons=() if normalized else ("EMPTY_OCR_TEXT",),
                    )
        except subprocess.TimeoutExpired:
            return _unavailable_attempt(
                crop,
                engine_name=self.name,
                status=OcrEngineStatus.TIMEOUT,
                reasons=("OCR_TIMEOUT",),
            )
        except Exception:
            return _unavailable_attempt(
                crop,
                engine_name=self.name,
                status=OcrEngineStatus.ERROR,
                reasons=("OCR_ENGINE_EXCEPTION",),
            )


class RapidOcrEngine:
    name = "rapidocr"

    def __init__(self) -> None:
        from rapidocr_onnxruntime import RapidOCR

        self.engine = RapidOCR()

    def run(self, image_path: Path, crop: PreparedFieldCrop) -> OcrAttempt:
        try:
            with Image.open(image_path) as image:
                crop_image = _render_crop_variant(image.convert("RGB"), crop)
                with tempfile.TemporaryDirectory(prefix="ocring_rapidocr_") as temp_dir:
                    input_path = Path(temp_dir) / "crop.png"
                    crop_image.save(input_path)
                    result, _elapsed = self.engine(input_path, use_det=False, use_cls=False, use_rec=True)
            raw_text, confidence = _rapidocr_text_and_confidence(result)
            normalized = _normalize_text(raw_text, count_mode=crop.field_kind.value == "item_count")
            LOGGER.info(
                "OCR[%s] %s %s -> %s",
                self.name,
                crop.row_id,
                crop.field_kind.value,
                normalized or "<empty>",
            )
            return OcrAttempt(
                crop_id=crop.crop_id,
                row_id=crop.row_id,
                field_kind=crop.field_kind,
                variant=crop.variant,
                engine_name=self.name,
                status=OcrEngineStatus.OK if normalized else OcrEngineStatus.ERROR,
                raw_text=raw_text.strip(),
                normalized_text=normalized,
                confidence=confidence if normalized else 0.15,
                reasons=() if normalized else ("EMPTY_OCR_TEXT",),
            )
        except Exception:
            return _unavailable_attempt(
                crop,
                engine_name=self.name,
                status=OcrEngineStatus.ERROR,
                reasons=("OCR_ENGINE_EXCEPTION",),
            )


class UnavailableOcrEngine:
    name = "unavailable"

    def run(self, image_path: Path, crop: PreparedFieldCrop) -> OcrAttempt:
        del image_path
        return _unavailable_attempt(
            crop,
            engine_name=self.name,
            status=OcrEngineStatus.UNAVAILABLE,
            reasons=("NO_LOCAL_OCR_ENGINE",),
        )


def _resolve_engine() -> OcrEngine:
    tesseract_path = shutil.which("tesseract")
    if tesseract_path:
        return TesseractEngine(tesseract_path)
    if _rapidocr_available():
        return RapidOcrEngine()
    return UnavailableOcrEngine()


def _rapidocr_available() -> bool:
    return importlib.util.find_spec("rapidocr_onnxruntime") is not None


def _select_crops(
    prepared_crops: tuple[PreparedFieldCrop, ...],
    *,
    max_attempts: int,
) -> tuple[PreparedFieldCrop, ...]:
    preferred_variant_order = {"high_contrast": 0, "sharpened": 1, "grayscale": 2}
    preferred_field_order = {"item_name": 0, "item_count": 1, "item_type": 2, "item_rarity": 3, "item_synergy": 4}
    ranked = sorted(
        prepared_crops,
        key=lambda crop: (
            preferred_field_order.get(crop.field_kind.value, 99),
            preferred_variant_order.get(crop.variant.value, 99),
            crop.row_id,
        ),
    )
    if len(ranked) <= max_attempts:
        return tuple(ranked)

    selected: list[PreparedFieldCrop] = []
    seen_field_slots: set[tuple[str, str]] = set()
    seen_crop_ids: set[str] = set()

    # First pass: guarantee one preferred crop per row/field combination.
    for crop in ranked:
        field_slot = (crop.row_id, crop.field_kind.value)
        if field_slot in seen_field_slots:
            continue
        selected.append(crop)
        seen_field_slots.add(field_slot)
        seen_crop_ids.add(crop.crop_id)
        if len(selected) >= max_attempts:
            return tuple(selected)

    # Second pass: spend any remaining budget on additional variants in priority order.
    for crop in ranked:
        if crop.crop_id in seen_crop_ids:
            continue
        selected.append(crop)
        seen_crop_ids.add(crop.crop_id)
        if len(selected) >= max_attempts:
            break

    return tuple(selected)


def _page_segmentation_mode(field_kind) -> str:
    if field_kind.value == "item_count":
        return "7"
    return "6"


def _normalize_text(text: str, *, count_mode: bool) -> str:
    cleaned = " ".join(text.replace("\n", " ").split()).strip()
    if count_mode:
        digits = "".join(ch for ch in cleaned if ch.isdigit() or ch in {"x", "X"})
        return digits.lower()
    return cleaned


def _classify_rarity_attempt(image_path: Path, crop: PreparedFieldCrop) -> OcrAttempt:
    try:
        with Image.open(image_path) as image:
            region = image.convert("RGB").crop(
                (
                    crop.source_region.x1,
                    crop.source_region.y1,
                    crop.source_region.x2,
                    crop.source_region.y2,
                )
            )
        color_name, label, confidence = _classify_rarity_region(region)
        LOGGER.info(
            "OCR[color_classifier] %s %s -> %s",
            crop.row_id,
            crop.field_kind.value,
            label or "<empty>",
        )
        return OcrAttempt(
            crop_id=crop.crop_id,
            row_id=crop.row_id,
            field_kind=crop.field_kind,
            variant=crop.variant,
            engine_name="color_classifier",
            status=OcrEngineStatus.OK if label else OcrEngineStatus.ERROR,
            raw_text=color_name,
            normalized_text=label,
            confidence=confidence,
            reasons=() if label else ("RARITY_COLOR_UNRESOLVED",),
        )
    except Exception:
        return _unavailable_attempt(
            crop,
            engine_name="color_classifier",
            status=OcrEngineStatus.ERROR,
            reasons=("RARITY_COLOR_EXCEPTION",),
        )


def _render_crop_variant(image: Image.Image, crop: PreparedFieldCrop) -> Image.Image:
    region = (
        crop.source_region.x1,
        crop.source_region.y1,
        crop.source_region.x2,
        crop.source_region.y2,
    )
    base = image.crop(region)
    if crop.variant is PreprocessVariant.GRAYSCALE:
        variant_image = base.convert("L")
    elif crop.variant is PreprocessVariant.HIGH_CONTRAST:
        variant_image = ImageEnhance.Contrast(base.convert("L")).enhance(1.8)
    elif crop.variant is PreprocessVariant.SHARPENED:
        variant_image = base.convert("L").filter(ImageFilter.SHARPEN)
    else:
        variant_image = base.convert("L")
    width = max(1, int(variant_image.width * 2))
    height = max(1, int(variant_image.height * 2))
    return variant_image.resize((width, height), Image.Resampling.LANCZOS)


def _classify_rarity_region(region: Image.Image) -> tuple[str, str, float]:
    palette = _load_defiance_rarity_palette()
    pixels = list(region.getdata())
    if not pixels:
        return "", "", 0.0
    saturated_pixels = []
    for red, green, blue in pixels:
        max_channel = max(red, green, blue)
        min_channel = min(red, green, blue)
        if max_channel < 140:
            continue
        if max_channel - min_channel < 36:
            continue
        saturated_pixels.append((red, green, blue))
    if len(saturated_pixels) < max(12, len(pixels) // 40):
        return "", "", 0.0
    average = (
        sum(red for red, _, _ in saturated_pixels) / len(saturated_pixels),
        sum(green for _, green, _ in saturated_pixels) / len(saturated_pixels),
        sum(blue for _, _, blue in saturated_pixels) / len(saturated_pixels),
    )
    best_name = ""
    best_label = ""
    best_distance = float("inf")
    for color_name, label, rgb in palette:
        distance = sum((average[index] - rgb[index]) ** 2 for index in range(3)) ** 0.5
        if distance < best_distance:
            best_distance = distance
            best_name = color_name
            best_label = label
    confidence = round(max(0.0, 1.0 - min(best_distance, 255.0) / 255.0), 3)
    if confidence < 0.9:
        return "", "", 0.0
    return best_name, best_label, confidence


def _load_defiance_rarity_palette() -> tuple[tuple[str, str, tuple[int, int, int]], ...]:
    profile_path = Path(__file__).resolve().parents[3] / "profiles" / "defiance" / "profile.json"
    try:
        payload = json.loads(profile_path.read_text(encoding="utf-8"))
    except OSError:
        return (
            ("Purple", "Epic", (156, 39, 176)),
            ("Orange", "Legendary", (255, 152, 0)),
            ("Blue", "Rare", (33, 150, 243)),
            ("Green", "Uncommon", (76, 175, 80)),
            ("Gray", "Common", (158, 158, 158)),
        )
    rules = []
    for tier, definition in dict(payload.get("rarity_definitions", {})).items():
        del tier
        color_hex = str(definition.get("color_hex") or "").strip()
        color_name = str(definition.get("color_name") or "").strip()
        label = str(definition.get("label") or "").strip()
        rgb = _hex_to_rgb(color_hex)
        if color_name and label and rgb is not None:
            rules.append((color_name, label, rgb))
    return tuple(rules)


def _hex_to_rgb(value: str) -> tuple[int, int, int] | None:
    cleaned = value.lstrip("#")
    if len(cleaned) != 6:
        return None
    try:
        return tuple(int(cleaned[index:index + 2], 16) for index in (0, 2, 4))
    except ValueError:
        return None


def _rapidocr_text_and_confidence(result: object) -> tuple[str, float]:
    if not isinstance(result, list) or not result:
        return "", 0.0
    first = result[0]
    if isinstance(first, (list, tuple)):
        if len(first) >= 2 and isinstance(first[0], str):
            return str(first[0]), float(first[1]) if isinstance(first[1], (int, float)) else 0.55
        if len(first) >= 2 and isinstance(first[1], str):
            confidence = 0.55
            if len(first) >= 3 and isinstance(first[2], (int, float)):
                confidence = float(first[2])
            return str(first[1]), confidence
    if isinstance(first, str):
        return first, 0.55
    return "", 0.0


def _unavailable_attempt(
    crop: PreparedFieldCrop,
    *,
    engine_name: str,
    status: OcrEngineStatus,
    reasons: tuple[str, ...],
) -> OcrAttempt:
    return OcrAttempt(
        crop_id=crop.crop_id,
        row_id=crop.row_id,
        field_kind=crop.field_kind,
        variant=crop.variant,
        engine_name=engine_name,
        status=status,
        raw_text="",
        normalized_text="",
        confidence=0.0,
        reasons=reasons,
    )
