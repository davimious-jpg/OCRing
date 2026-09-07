from __future__ import annotations

import pytest

from ocring.ocr.truth_state import TruthProgression, TruthState


def test_truth_progression_enforces_order_and_reasons() -> None:
    progression = TruthProgression()

    progression.advance_to(TruthState.RECOGNIZED, "OCR_VALUES_EXTRACTED")
    progression.advance_to(TruthState.MATCHED, "PROFILE_MATCH_CONFIRMED")

    assert progression.current_state is TruthState.MATCHED
    assert progression.latest_reason == "PROFILE_MATCH_CONFIRMED"
    assert progression.progression_reasons == ["OCR_VALUES_EXTRACTED", "PROFILE_MATCH_CONFIRMED"]


def test_truth_progression_rejects_skipped_state() -> None:
    progression = TruthProgression()

    with pytest.raises(ValueError):
        progression.advance_to(TruthState.ACCEPTED, "SKIP_NOT_ALLOWED")
