from __future__ import annotations

from pathlib import Path

from PIL import Image

from ocring.ocr.models import FieldKind, PreparedFieldCrop, PreprocessVariant, Rect
from ocring.ocr.recognition_orchestrator import RecognitionOrchestrator
from ocring.ocr.settings import RecognitionSettings


def _crop(field_kind: FieldKind) -> PreparedFieldCrop:
    return PreparedFieldCrop(
        crop_id=f"crop-{field_kind.value}",
        row_id="frame-1:row:1",
        field_kind=field_kind,
        variant=PreprocessVariant.GRAYSCALE,
        source_region=Rect(0, 0, 80, 30),
        width=80,
        height=30,
        stats={},
    )


def test_recognition_orchestrator_runs_full_flow(tmp_path: Path, monkeypatch) -> None:
    image_path = tmp_path / "sample.png"
    Image.new("RGB", (120, 60), (255, 255, 255)).save(image_path)

    monkeypatch.setattr("ocring.ocr.ocr_runner.shutil.which", lambda name: None)

    result = RecognitionOrchestrator().run(
        image_path=image_path,
        prepared_crops=(_crop(FieldKind.ITEM_NAME), _crop(FieldKind.ITEM_COUNT)),
        profile_id="defiance",
        settings=RecognitionSettings(recognition_mode="Balanced"),
        contract={
            "allowed_names": ("Item Name",),
            "allowed_rarities": ("Tier IV",),
            "allowed_types": ("Rocket Launcher",),
            "allowed_counts": ("1", "2"),
            "allowed_synergies": (),
        },
        quality_metrics=type("Q", (), {"sharpness": 0.7, "motion_penalty": 0.1})(),
    )

    assert len(result.ocr_attempts) == 2
    assert len(result.field_candidates) == 2
    assert len(result.records) == 2
    assert result.recognition_mode_used in {"Classic-Only", "Local-AI", "Hybrid", "Offline"}
    assert result.records[0].final_status in {"ok", "needs_review"}
    assert result.records[0].provenance["profile_version"] == "1.0"
