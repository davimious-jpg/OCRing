from __future__ import annotations

from pathlib import Path

from ocring.ocr.inventory import InventoryRecord
from ocring.ocr.review import ReviewRecord, ReviewSession
from ocring.ocr.search_engine import SearchEngine
from ocring.ui.services import InventoryStoreService, LocalSettingsService, SearchEngineService


class _FakeInventoryStore:
    def __init__(self) -> None:
        self.records = [
            InventoryRecord(
                session_id="s1",
                record_id="r1",
                row_slot=1,
                review_status="ACCEPTED",
                fields={"item_name": "Power Bore", "item_rarity": "Tier IV", "item_type": "Rocket Launcher", "item_count": "1"},
                corrections={},
                added_order=1,
            )
        ]

    def get_all_verified_records(self) -> list[InventoryRecord]:
        return list(self.records)

    def get_records_by_filter(self, filters: dict[str, object]) -> list[InventoryRecord]:
        return [
            record
            for record in self.records
            if all(str(record.fields.get(key, "")).lower() == str(value).lower() for key, value in filters.items())
        ]


def test_inventory_and_search_services_delegate_to_backend_shapes(tmp_path: Path) -> None:
    fake_store = _FakeInventoryStore()
    review_session = ReviewSession("session-1", [ReviewRecord("r1", 1, {"item_name": "Power Bore"}, {}, [], [], {}, [])])
    inventory_service = InventoryStoreService(fake_store, review_session=review_session)  # type: ignore[arg-type]
    search_service = SearchEngineService(SearchEngine(fake_store))  # type: ignore[arg-type]

    results = inventory_service.search("Power", {})
    suggestions = search_service.suggest("Pow")
    accepted = inventory_service.accept_candidate("r1")

    assert results[0].record_id == "r1"
    assert isinstance(suggestions, list)
    assert accepted is True
    assert review_session.get_record("r1").review_status == "ACCEPTED"


def test_settings_service_loads_and_saves() -> None:
    service = LocalSettingsService(settings_path=Path.home() / "Ocring" / ".tmp-test-settings.json")
    settings = service.load()
    saved_path = service.save(settings)

    assert saved_path.name == ".tmp-test-settings.json"
    if saved_path.exists():
        saved_path.unlink()
