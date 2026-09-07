from __future__ import annotations

from pathlib import Path

import pytest

from ocring.ocr.fixture_catalog import discover_session_fixture_catalog
from pathlib import Path

from ocring.ocr.pipeline import run_fixture_diagnostic
from ocring.ocr.session_fixture import load_session_fixture


FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures" / "session_cases"
FIXTURE_PATH = FIXTURE_DIR / "live_ocr_probe_fixture.json"


def test_live_ocr_fixture_runs_honest_engine_path() -> None:
    fixture = load_session_fixture(FIXTURE_PATH)

    report = run_fixture_diagnostic(fixture)

    assert report["frame_reports"][0]["replay_mode"] == "live_ocr"
    engine = report["frame_reports"][0]["ocr_engine"]
    assert "engine_name" in engine
    assert "available" in engine
    if engine["available"]:
        assert engine["engine_name"] != "unavailable"
    else:
        assert engine["reason"] == "NO_LOCAL_OCR_ENGINE"
        attempts = report["frame_reports"][0]["ocr_attempts"]
        assert all(attempt["status"] == "unavailable" for attempt in attempts)


@pytest.mark.parametrize(
    "fixture_name",
    [
        entry.fixture_path.name
        for entry in discover_session_fixture_catalog(FIXTURE_DIR)
        if entry.is_live_ocr
    ],
)
def test_live_ocr_catalog_fixtures_preserve_engine_honesty_and_attempt_shape(fixture_name: str) -> None:
    fixture = load_session_fixture(FIXTURE_DIR / fixture_name)

    report = run_fixture_diagnostic(fixture)

    assert len(report["frame_reports"]) == len(fixture.frames)
    assert report["scan_integrity"]["scan_scope"] == fixture.scan_scope.value

    first_engine = report["frame_reports"][0]["ocr_engine"]
    for frame_report in report["frame_reports"]:
        assert frame_report["replay_mode"] == "live_ocr"
        assert frame_report["ocr_engine"]["engine_name"] == first_engine["engine_name"]
        assert frame_report["ocr_engine"]["available"] == first_engine["available"]
        assert "prepared_crops" in frame_report
        assert "ocr_attempts" in frame_report
        assert len(frame_report["ocr_attempts"]) == len(frame_report["prepared_crops"])
        assert len(frame_report["ocr_attempts"]) <= 24
        assert "retained_evidence" in frame_report
        if first_engine["available"]:
            assert all(
                attempt["engine_name"] == first_engine["engine_name"]
                and attempt["status"] != "unavailable"
                for attempt in frame_report["ocr_attempts"]
            )
        else:
            assert frame_report["ocr_engine"]["reason"] == "NO_LOCAL_OCR_ENGINE"
            assert all(
                attempt["status"] == "unavailable"
                and "NO_LOCAL_OCR_ENGINE" in attempt["reasons"]
                for attempt in frame_report["ocr_attempts"]
            )
