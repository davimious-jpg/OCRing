from __future__ import annotations

import json
from pathlib import Path

from ocring.ocr.pipeline import run_fixture_diagnostic
from ocring.ocr.session_fixture import load_session_fixture
from ocring.ocr.snapshot import build_replay_snapshot


FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures" / "session_cases"


def test_stable_fixture_matches_golden_snapshot() -> None:
    fixture = load_session_fixture(FIXTURE_DIR / "stable_current_page_fixture.json")
    expected = json.loads((FIXTURE_DIR / "stable_current_page_snapshot.json").read_text(encoding="utf-8"))

    report = run_fixture_diagnostic(fixture)
    snapshot = build_replay_snapshot(report)

    assert snapshot == expected


def test_conflicted_fixture_matches_golden_snapshot() -> None:
    fixture = load_session_fixture(FIXTURE_DIR / "conflicted_current_page_fixture.json")
    expected = json.loads((FIXTURE_DIR / "conflicted_current_page_snapshot.json").read_text(encoding="utf-8"))

    report = run_fixture_diagnostic(fixture)
    snapshot = build_replay_snapshot(report)

    assert snapshot == expected
