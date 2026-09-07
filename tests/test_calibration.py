from __future__ import annotations

from pathlib import Path

from ocring.ocr.calibration import CalibrationStore, ConfidenceCalibrator


def test_calibration_marks_overconfidence_and_adjusts_reliability() -> None:
    calibrator = ConfidenceCalibrator()
    calibrator.record_verification("classic_ocr", predicted_confidence=0.95, actual_correct=False)
    calibrator.record_verification("classic_ocr", predicted_confidence=0.95, actual_correct=True)

    assert calibrator.is_overconfident(predicted_confidence=0.95, actual_correctness=0.80) is True
    assert calibrator.calibrated_reliability("classic_ocr") < 1.0
    assert calibrator.calibrate_confidence(0.95, source_keys=("classic_ocr",)) < 0.95


def test_calibration_store_records_corrections_and_adjusts_reliability_after_threshold(tmp_path: Path) -> None:
    store = CalibrationStore(tmp_path / "calibration.db", min_verified_corrections=2)
    store.record_correction("Power Bore", "Power Core", "classic_ocr", 0.95, field_id="field-1", field_type="item_name")
    assert store.get_reliability("classic_ocr", "item_name") == 1.0

    store.record_correction("Power Bore", "Power Core", "classic_ocr", 0.95, field_id="field-2", field_type="item_name")

    reliability = store.get_reliability("classic_ocr", "item_name")
    report = store.get_confident_vs_correct()

    assert 0.70 <= reliability <= 0.95
    assert report["classic_ocr:item_name"]["total"] == 2
    assert report["classic_ocr:item_name"]["overconfident"] is True


def test_calibration_store_applies_bounded_adjustment_history(tmp_path: Path) -> None:
    store = CalibrationStore(tmp_path / "calibration.db", min_verified_corrections=1)
    store.record_correction("A", "B", "local_ai", 0.95, field_id="field-1", field_type="item_name")
    first = store.get_reliability("local_ai", "item_name")
    store.record_correction("A", "B", "local_ai", 0.95, field_id="field-2", field_type="item_name")
    second = store.get_reliability("local_ai", "item_name")

    assert round(1.0 - first, 3) <= 0.05
    assert round(first - second, 3) <= 0.05
