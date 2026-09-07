from __future__ import annotations

from ocring.ocr.coverage_ledger import CoverageObservation, CoverageState, EvidenceCoverageLedger


def test_coverage_ledger_marks_continuous_when_rows_overlap() -> None:
    ledger = EvidenceCoverageLedger()
    ledger.observe(CoverageObservation("frame-a", 1, 1.0, {1: "100", 2: "101", 3: "102"}))
    transition = ledger.observe(CoverageObservation("frame-b", 2, 1.1, {1: "101", 2: "102", 3: "103"}))

    assert transition is not None
    assert transition.state is CoverageState.CONTINUOUS
    assert transition.overlap_count == 2
    assert ledger.as_dict()["coverage_state"] == "CONTINUOUS"


def test_coverage_ledger_marks_gap_when_row_signatures_jump() -> None:
    ledger = EvidenceCoverageLedger()
    ledger.observe(CoverageObservation("frame-a", 1, 1.0, {1: "100", 2: "101", 3: "102", 4: "103", 5: "104"}))
    transition = ledger.observe(CoverageObservation("frame-b", 2, 1.1, {1: "108", 2: "109", 3: "110", 4: "111", 5: "112"}))

    assert transition is not None
    assert transition.state is CoverageState.GAP
    assert transition.reason == "NO_ROW_SIGNATURE_OVERLAP"
    assert ledger.as_dict()["coverage_state"] == "GAP"
    assert len(ledger.as_dict()["gaps"]) == 1


def test_coverage_ledger_keeps_inventory_coverage_separate_from_item_count() -> None:
    ledger = EvidenceCoverageLedger()
    ledger.observe(CoverageObservation("frame-a", 1, 1.0, {1: "x3", 2: "name-a"}))
    ledger.observe(CoverageObservation("frame-b", 2, 1.1, {1: "name-b", 2: "name-c"}))
    payload = ledger.as_dict()

    assert "item_count" not in payload
    assert payload["coverage_state"] == "GAP"
