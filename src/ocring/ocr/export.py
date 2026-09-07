from __future__ import annotations

import csv
import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

from .inventory import InventoryRecord
from .settings import DEFAULT_SETTINGS_PATH, ensure_output_workspace


@dataclass(frozen=True)
class ExportMetadata:
    session_id: str
    profile_version: str
    export_timestamp: str


class Exporter:
    def export_csv(self, records: list[InventoryRecord], path: Path, *, metadata: ExportMetadata) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        fieldnames = [
            "session_id",
            "record_id",
            "row_slot",
            "review_status",
            "item_name",
            "item_rarity",
            "item_type",
            "item_count",
            "item_synergy",
        ]
        with path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            writer.writeheader()
            for record in records:
                writer.writerow(
                    {
                        "session_id": record.session_id,
                        "record_id": record.record_id,
                        "row_slot": record.row_slot,
                        "review_status": record.review_status,
                        "item_name": record.fields.get("item_name", ""),
                        "item_rarity": record.fields.get("item_rarity", ""),
                        "item_type": record.fields.get("item_type", ""),
                        "item_count": record.fields.get("item_count", ""),
                        "item_synergy": record.fields.get("item_synergy", ""),
                    }
                )
        return path

    def export_json(self, records: list[InventoryRecord], path: Path, *, metadata: ExportMetadata) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "metadata": asdict(metadata),
            "records": [_record_to_dict(record) for record in records],
        }
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        return path

    def export_ocring_package(
        self,
        records: list[InventoryRecord],
        session_metadata: dict[str, str],
        path: Path,
    ) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        manifest = {
            "session_id": session_metadata["session_id"],
            "profile_version": session_metadata["profile_version"],
            "export_timestamp": session_metadata["export_timestamp"],
            "record_count": len(records),
        }
        with ZipFile(path, "w", compression=ZIP_DEFLATED) as archive:
            archive.writestr("manifest.json", json.dumps(manifest, indent=2))
            archive.writestr("records.json", json.dumps([_record_to_dict(record) for record in records], indent=2))
        return path


def build_export_metadata(*, session_id: str, profile_version: str = "1") -> ExportMetadata:
    return ExportMetadata(
        session_id=session_id,
        profile_version=profile_version,
        export_timestamp=datetime.now(timezone.utc).isoformat(),
    )


def filter_export_records(records: list[InventoryRecord], *, review_status: str | None = None) -> list[InventoryRecord]:
    if not review_status:
        return records
    return [record for record in records if record.review_status.lower() == review_status.lower()]


def default_export_path(
    export_format: str,
    *,
    session_id: str,
    settings_path: Path = DEFAULT_SETTINGS_PATH,
) -> Path:
    workspace = ensure_output_workspace(path=settings_path)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    suffix = {
        "csv": ".csv",
        "json": ".json",
        "package": ".ocrpkg",
    }.get(export_format, ".dat")
    safe_session_id = "".join(character if character.isalnum() or character in {"-", "_"} else "_" for character in session_id) or "ocring"
    return workspace.export_dir / f"{safe_session_id}-{timestamp}{suffix}"


def _record_to_dict(record: InventoryRecord) -> dict[str, object]:
    return {
        "session_id": record.session_id,
        "record_id": record.record_id,
        "row_slot": record.row_slot,
        "review_status": record.review_status,
        "fields": record.fields,
        "corrections": record.corrections,
        "added_order": record.added_order,
    }
