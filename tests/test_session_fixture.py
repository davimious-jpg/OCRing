from __future__ import annotations

import json
from pathlib import Path

from PIL import Image

from ocring.ocr.models import ScanScope
from ocring.ocr.pipeline import run_fixture_diagnostic
from ocring.ocr.session_fixture import load_session_fixture


def test_load_session_fixture_reads_stable_metadata(tmp_path: Path) -> None:
    image_path = tmp_path / "frame.png"
    Image.new("RGB", (640, 480), color=(120, 120, 120)).save(image_path)
    fixture_path = tmp_path / "fixture.json"
    fixture_path.write_text(
        json.dumps(
            {
                "fixture_id": "fixture-alpha",
                "profile_id": "defiance",
                "scan_scope": "current_page",
                "frames": [
                    {
                        "image_path": "frame.png",
                        "frame_id": "frame-001",
                        "session_id": "session-123",
                        "timestamp_utc": "2026-08-15T01:00:00+00:00",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    fixture = load_session_fixture(fixture_path)

    assert fixture.fixture_id == "fixture-alpha"
    assert fixture.profile_id == "defiance"
    assert fixture.scan_scope is ScanScope.CURRENT_PAGE
    assert fixture.frames[0].frame_id == "frame-001"
    assert fixture.frames[0].session_id == "session-123"


def test_run_fixture_diagnostic_preserves_fixture_scope_and_ids(tmp_path: Path) -> None:
    image_path = tmp_path / "frame.png"
    Image.new("RGB", (640, 480), color=(80, 80, 80)).save(image_path)
    fixture_path = tmp_path / "fixture.json"
    fixture_path.write_text(
        json.dumps(
            {
                "fixture_id": "fixture-beta",
                "profile_id": "defiance",
                "scan_scope": "full_inventory",
                "frames": [
                    {
                        "image_path": "frame.png",
                        "frame_id": "frame-101",
                        "session_id": "session-xyz",
                        "timestamp_utc": "2026-08-15T02:00:00+00:00",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    fixture = load_session_fixture(fixture_path)
    report = run_fixture_diagnostic(fixture)

    assert report["scan_integrity"]["scan_scope"] == "full_inventory"
    assert report["frame_reports"][0]["frame"]["frame_id"] == "frame-101"
    assert report["frame_reports"][0]["frame"]["session_id"] == "session-xyz"
