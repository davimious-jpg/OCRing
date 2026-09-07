from __future__ import annotations

from ocring.ocr.ai_reconstructor import AIReconstructor


def test_ai_reconstructor_repairs_fragmented_terms() -> None:
    reconstructor = AIReconstructor()

    result = reconstructor.reconstruct(
        ("Epid", "emic", "Power", "Bore", "IV", "Rocket", "Launcher"),
        allowed_terms=("Epidemic", "Power Bore IV", "Rocket Launcher"),
    )

    assert result.status == "REPAIRED"
    assert "Epidemic" in result.repaired_fragments
    assert "Power Bore IV" in result.repaired_fragments
    assert "Rocket Launcher" in result.repaired_fragments


def test_ai_reconstructor_marks_low_confidence_as_review() -> None:
    reconstructor = AIReconstructor()

    result = reconstructor.reconstruct(("xq",), allowed_terms=("Rocket Launcher",))

    assert result.status == "NEEDS_REVIEW"
    assert result.provenance["engine_source"] == "classic_ocr_fallback"
