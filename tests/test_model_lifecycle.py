from __future__ import annotations

import pytest

from ocring.ocr.model_lifecycle import ModelRegistration, ModelRegistry


def test_model_registry_requires_benchmark_before_promotion() -> None:
    registry = ModelRegistry()
    registry.register(ModelRegistration("m1", "1.0", "abc", {"gpu": "optional"}, False))

    with pytest.raises(ValueError):
        registry.promote("m1")


def test_model_registry_promotes_when_benchmarked() -> None:
    registry = ModelRegistry()
    registry.register(ModelRegistration("m1", "1.0", "abc", {"gpu": "optional"}, False, benchmark_score=0.91, calibration_result="OK"))

    promoted = registry.promote("m1")

    assert promoted.enabled is True

