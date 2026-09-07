from __future__ import annotations

from pathlib import Path

from ocring.ocr.fixture_catalog import discover_session_fixture_catalog


FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures" / "session_cases"


def test_discover_session_fixture_catalog_finds_ranked_and_live_fixture_sets() -> None:
    catalog = discover_session_fixture_catalog(FIXTURE_DIR)

    assert [entry.fixture_id for entry in catalog] == [
        "conflicted-current-page",
        "live-ocr-probe",
        "live-ocr-scroll",
        "stable-current-page",
    ]

    live_entries = [entry for entry in catalog if entry.is_live_ocr]
    assert [entry.fixture_id for entry in live_entries] == [
        "live-ocr-probe",
        "live-ocr-scroll",
    ]

    scroll_entry = next(entry for entry in catalog if entry.fixture_id == "live-ocr-scroll")
    assert scroll_entry.frame_count == 2
    assert scroll_entry.scan_scope.value == "full_inventory"
