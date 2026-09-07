from __future__ import annotations

import json
from pathlib import Path
from zipfile import ZipFile

from ocring.ocr.export import Exporter, build_export_metadata, default_export_path, filter_export_records
from ocring.ocr.inventory import InventoryRecord


def _records() -> list[InventoryRecord]:
    return [
        InventoryRecord(
            session_id="s1",
            record_id="r1",
            row_slot=1,
            review_status="ACCEPTED",
            fields={"item_name": "Alpha Rocket", "item_rarity": "Tier IV", "item_type": "Rocket Launcher", "item_count": "1"},
            corrections={},
            added_order=1,
        ),
        InventoryRecord(
            session_id="s1",
            record_id="r2",
            row_slot=2,
            review_status="REJECTED",
            fields={"item_name": "Bravo SMG", "item_rarity": "Tier III", "item_type": "SMG", "item_count": "2"},
            corrections={},
            added_order=2,
        ),
    ]


def test_export_csv_writes_rows(tmp_path: Path) -> None:
    exporter = Exporter()
    output = tmp_path / "inventory.csv"
    exporter.export_csv(_records(), output, metadata=build_export_metadata(session_id="s1"))

    content = output.read_text(encoding="utf-8")

    assert "Alpha Rocket" in content
    assert "Bravo SMG" in content


def test_export_json_includes_metadata(tmp_path: Path) -> None:
    exporter = Exporter()
    output = tmp_path / "inventory.json"
    exporter.export_json(_records(), output, metadata=build_export_metadata(session_id="s1"))

    payload = json.loads(output.read_text(encoding="utf-8"))

    assert payload["metadata"]["session_id"] == "s1"
    assert len(payload["records"]) == 2


def test_export_package_writes_manifest_and_records(tmp_path: Path) -> None:
    exporter = Exporter()
    output = tmp_path / "inventory.ocrpkg"
    exporter.export_ocring_package(
        _records(),
        {"session_id": "s1", "profile_version": "1", "export_timestamp": "2026-08-15T00:00:00+00:00"},
        output,
    )

    with ZipFile(output) as archive:
        names = archive.namelist()
        manifest = json.loads(archive.read("manifest.json").decode("utf-8"))

    assert "manifest.json" in names
    assert "records.json" in names
    assert manifest["record_count"] == 2


def test_filtering_before_export_returns_only_matching_status(tmp_path: Path) -> None:
    del tmp_path
    records = filter_export_records(_records(), review_status="ACCEPTED")

    assert [record.record_id for record in records] == ["r1"]


def test_default_export_path_uses_output_workspace(tmp_path: Path) -> None:
    settings_path = tmp_path / "settings.json"
    output_root = tmp_path / "output"
    settings_path.write_text(json.dumps({"output_root": str(output_root)}), encoding="utf-8")

    output_path = default_export_path("csv", session_id="session-001", settings_path=settings_path)

    assert output_path.parent == output_root / "export"
    assert output_path.suffix == ".csv"
    assert "session-001" in output_path.name
