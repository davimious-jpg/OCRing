from __future__ import annotations

from ocring.ocr.calibration import ConfidenceCalibrator
from ocring.ocr.weight_governance import WeightGovernor


def test_three_layer_weight_logic_uses_profile_calibration_and_session_adjustment() -> None:
    governor = WeightGovernor(
        profile_weights={"classic_ocr": 0.8},
        calibrated_reliabilities={"classic_ocr": 0.9},
        session_adjustments={"classic_ocr": 0.5},
    )

    assert governor.effective_weight("classic_ocr") == 0.36


def test_permanent_weight_changes_require_verified_evidence() -> None:
    governor = WeightGovernor(profile_weights={"classic_ocr": 1.0})
    calibrator = ConfidenceCalibrator()
    calibrator.record_verification("classic_ocr", predicted_confidence=0.8, actual_correct=False)

    governor.apply_calibration(calibrator, verified=False)
    unchanged = governor.calibrated_reliabilities.get("classic_ocr")
    governor.apply_calibration(calibrator, verified=True)

    assert unchanged is None
    assert governor.calibrated_reliabilities["classic_ocr"] != 1.0
