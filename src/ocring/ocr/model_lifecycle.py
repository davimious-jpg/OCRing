from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ModelRegistration:
    model_id: str
    version: str
    checksum: str
    hardware_requirements: dict[str, str]
    enabled: bool
    benchmark_score: float | None = None
    calibration_result: str = ""


class ModelRegistry:
    def __init__(self) -> None:
        self._models: dict[str, ModelRegistration] = {}

    def register(self, model: ModelRegistration) -> None:
        self._models[model.model_id] = model

    def get(self, model_id: str) -> ModelRegistration:
        return self._models[model_id]

    def promote(self, model_id: str) -> ModelRegistration:
        model = self.get(model_id)
        if model.benchmark_score is None:
            raise ValueError("Benchmark score required before promotion.")
        model.enabled = True
        return model

    def disable(self, model_id: str) -> ModelRegistration:
        model = self.get(model_id)
        model.enabled = False
        return model

