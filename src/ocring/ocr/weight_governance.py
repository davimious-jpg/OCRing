from __future__ import annotations

from dataclasses import dataclass, field

from .calibration import ConfidenceCalibrator


@dataclass
class WeightGovernor:
    profile_weights: dict[str, float] = field(default_factory=dict)
    calibrated_reliabilities: dict[str, float] = field(default_factory=dict)
    session_adjustments: dict[str, float] = field(default_factory=dict)

    def effective_weight(self, source_key: str) -> float:
        profile_weight = self.profile_weights.get(source_key, 1.0)
        calibrated = self.calibrated_reliabilities.get(source_key, 1.0)
        session_adjustment = self.session_adjustments.get(source_key, 1.0)
        return round(profile_weight * calibrated * session_adjustment, 3)

    def field_weight_distribution(self, source_keys: tuple[str, ...]) -> dict[str, float]:
        distribution = {source_key: self.effective_weight(source_key) for source_key in source_keys}
        total = sum(distribution.values())
        if total <= 0:
            return {source_key: 0.0 for source_key in source_keys}
        return {source_key: round(weight / total, 3) for source_key, weight in distribution.items()}

    def apply_calibration(self, calibrator: ConfidenceCalibrator, *, verified: bool = True) -> None:
        if not verified:
            return
        for source_key in list(self.profile_weights) + list(self.calibrated_reliabilities):
            self.calibrated_reliabilities[source_key] = round(calibrator.calibrated_reliability(source_key), 3)
