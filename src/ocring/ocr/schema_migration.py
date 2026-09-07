from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class MigrationReceipt:
    from_version: str
    to_version: str
    migrated_keys: tuple[str, ...]
    preserved_raw_observations: bool


class SchemaMigration:
    def __init__(self, current_version: str = "v1") -> None:
        self.current_version = current_version

    def migrate_v1_to_v2(self, payload: dict[str, Any]) -> tuple[dict[str, Any], MigrationReceipt]:
        migrated = dict(payload)
        migrated["schema_version"] = "v2"
        migrated["record_count"] = len(tuple(migrated.get("records", ())))
        migrated.setdefault("raw_observations", payload.get("raw_observations", ()))
        receipt = MigrationReceipt("v1", "v2", ("schema_version", "record_count", "raw_observations"), True)
        return migrated, receipt

    def migrate_v2_to_v3(self, payload: dict[str, Any]) -> tuple[dict[str, Any], MigrationReceipt]:
        migrated = dict(payload)
        migrated["schema_version"] = "v3"
        provenance = dict(migrated.get("provenance") or {})
        provenance.setdefault("migration_chain", []).append("v2_to_v3")
        migrated["provenance"] = provenance
        migrated.setdefault("raw_observations", payload.get("raw_observations", ()))
        receipt = MigrationReceipt("v2", "v3", ("schema_version", "provenance", "raw_observations"), True)
        return migrated, receipt

    def migrate_to(self, target_version: str, payload: dict[str, Any]) -> tuple[dict[str, Any], tuple[MigrationReceipt, ...]]:
        version = str(payload.get("schema_version") or self.current_version)
        migrated = dict(payload)
        receipts: list[MigrationReceipt] = []
        while version != target_version:
            if version == "v1" and target_version in {"v2", "v3"}:
                migrated, receipt = self.migrate_v1_to_v2(migrated)
                version = "v2"
                receipts.append(receipt)
                continue
            if version == "v2" and target_version == "v3":
                migrated, receipt = self.migrate_v2_to_v3(migrated)
                version = "v3"
                receipts.append(receipt)
                continue
            raise ValueError(f"Unsupported migration path: {version} -> {target_version}")
        return migrated, tuple(receipts)

