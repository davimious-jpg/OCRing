from __future__ import annotations

import json
from pathlib import Path

from ocring.ocr.pipeline import run_fixture_diagnostic
from ocring.ocr.session_fixture import load_session_fixture


FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures" / "session_cases"


def test_stable_current_page_fixture_matches_expected_outputs() -> None:
    fixture_path = FIXTURE_DIR / "stable_current_page_fixture.json"
    raw = json.loads(fixture_path.read_text(encoding="utf-8"))
    fixture = load_session_fixture(fixture_path)

    report = run_fixture_diagnostic(fixture)

    expected = raw["expected"]
    assert report["scan_integrity"]["completeness_state"] == expected["completeness_state"]
    assert report["continuity_records"][0]["state"] == expected["continuity_state"]
    assert report["continuity_records"][0]["support_count"] == expected["support_count"]


def test_conflicted_current_page_fixture_matches_expected_outputs() -> None:
    fixture_path = FIXTURE_DIR / "conflicted_current_page_fixture.json"
    raw = json.loads(fixture_path.read_text(encoding="utf-8"))
    fixture = load_session_fixture(fixture_path)

    report = run_fixture_diagnostic(fixture)

    expected = raw["expected"]
    assert report["scan_integrity"]["completeness_state"] == expected["completeness_state"]
    assert report["continuity_records"][0]["state"] == expected["continuity_state"]
    contradiction_codes = {
        contradiction["contradiction_code"]
        for contradiction in report["scan_integrity"]["contradictions"]
    }
    assert expected["contradiction_code"] in contradiction_codes
