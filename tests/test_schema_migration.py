from __future__ import annotations

from ocring.ocr.schema_migration import SchemaMigration


def test_schema_migration_preserves_raw_observations_and_receipts() -> None:
    migration = SchemaMigration(current_version="v1")
    payload = {"schema_version": "v1", "records": [{"id": "r1"}], "raw_observations": ["frame-1"]}

    migrated, receipts = migration.migrate_to("v3", payload)

    assert migrated["schema_version"] == "v3"
    assert migrated["raw_observations"] == ["frame-1"]
    assert len(receipts) == 2
    assert receipts[0].from_version == "v1"
    assert receipts[1].to_version == "v3"

