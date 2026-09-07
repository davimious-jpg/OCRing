from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .inventory import InventoryRecord, InventoryStore
from .profile import DEFAULT_PROFILES_ROOT
from .search_definition import SearchDefinition


@dataclass(frozen=True)
class SavedSearch:
    name: str
    query: str
    filters: dict[str, Any]
    smart_folder: bool = False


@dataclass(frozen=True)
class SearchQuery:
    name: str
    query: str
    filters: dict[str, Any]


class SearchEngine:
    def __init__(
        self,
        inventory_store: InventoryStore,
        *,
        saved_search_path: Path | None = None,
        profile_id: str = "defiance",
        profiles_root: Path = DEFAULT_PROFILES_ROOT,
    ) -> None:
        self.inventory_store = inventory_store
        self.saved_search_path = saved_search_path or Path("E:/Ocring/sessions/saved_searches.json")
        self.search_definition = SearchDefinition.load_active_profile(profile_id, profiles_root=profiles_root)

    def search(self, query: str, filters: dict[str, Any]) -> list[InventoryRecord]:
        combined_filters = dict(filters)
        text_terms: list[str] = []
        for clause in [item.strip() for item in query.split("AND") if item.strip()]:
            if ":" in clause:
                raw_field, raw_value = clause.split(":", 1)
                field = _normalize_field_name(raw_field.strip())
                if not self.search_definition.validate_field(field):
                    raise ValueError(f"Unknown search field: {raw_field.strip()}")
                combined_filters[field] = raw_value.strip()
            else:
                text_terms.append(clause.lower())

        records = self.inventory_store.get_all_verified_records()
        if combined_filters:
            records = [record for record in records if _matches_search_filters(record, combined_filters)]
        if text_terms:
            records = [
                record
                for record in records
                if all(term in record.fields.get("item_name", "").lower() for term in text_terms)
            ]
        if combined_filters.get("recently_added"):
            records = sorted(records, key=lambda record: record.added_order, reverse=True)[:10]
        return records

    def suggest(self, partial_input: str) -> list[str]:
        return self.search_definition.suggest(partial_input)

    def quick_tab_query(self, tab_name: str) -> SearchQuery:
        query, filters = self.search_definition.quick_tab_query(tab_name)
        return SearchQuery(name=tab_name, query=query, filters=filters)

    def save_search(self, name: str, query: str, filters: dict[str, Any]) -> None:
        searches = {item.name: item for item in self.list_saved_searches() if not item.smart_folder}
        searches[name] = SavedSearch(name=name, query=query, filters=dict(filters))
        self.saved_search_path.parent.mkdir(parents=True, exist_ok=True)
        payload = [
            {"name": item.name, "query": item.query, "filters": item.filters}
            for item in sorted(searches.values(), key=lambda item: item.name.lower())
        ]
        self.saved_search_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def list_saved_searches(self) -> list[SavedSearch]:
        searches = list(_smart_folders(self.search_definition))
        if self.saved_search_path.exists():
            payload = json.loads(self.saved_search_path.read_text(encoding="utf-8"))
            for item in payload:
                searches.append(
                    SavedSearch(
                        name=str(item["name"]),
                        query=str(item.get("query") or ""),
                        filters=dict(item.get("filters") or {}),
                    )
                )
        return searches

    def load_search(self, name: str) -> SearchQuery:
        for item in self.list_saved_searches():
            if item.name == name:
                return SearchQuery(name=item.name, query=item.query, filters=item.filters)
        raise KeyError(f"Unknown saved search: {name}")


def _smart_folders(definition: SearchDefinition) -> tuple[SavedSearch, ...]:
    quick_tabs = []
    for tab in definition.quick_tabs:
        query, filters = definition.quick_tab_query(tab)
        quick_tabs.append(SavedSearch(name=tab, query=query, filters=filters, smart_folder=True))
    first_rarity = definition.suggestions.get("tier", ("Tier III",))[0] if definition.suggestions.get("tier") else "Tier III"
    rocket_launcher = definition.suggestions.get("item_type", ("Rocket Launcher",))[0] if definition.suggestions.get("item_type") else "Rocket Launcher"
    quick_tabs.append(SavedSearch(name="Epic+", query="", filters={"item_rarity": first_rarity}, smart_folder=True))
    quick_tabs.append(SavedSearch(name="Legendary Rocket Launchers", query=f"rarity:{first_rarity} AND type:{rocket_launcher}", filters={}, smart_folder=True))
    quick_tabs.append(SavedSearch(name="Needs Review", query="", filters={"review_status": "PENDING"}, smart_folder=True))
    quick_tabs.append(SavedSearch(name="Recently Added", query="", filters={"recently_added": True}, smart_folder=True))
    return tuple(quick_tabs)


def _matches_search_filters(record: InventoryRecord, filters: dict[str, Any]) -> bool:
    for key, value in filters.items():
        if value in (None, ""):
            continue
        if key == "review_status":
            actual = record.review_status
        elif key == "recently_added":
            actual = True
        else:
            actual = record.fields.get(key, "")
        if str(actual).lower() != str(value).lower():
            return False
    return True


def _normalize_field_name(field: str) -> str:
    mapping = {
        "rarity": "item_rarity",
        "type": "item_type",
        "name": "item_name",
        "count": "item_count",
        "synergy": "item_synergy",
        "status": "review_status",
        "tier": "tier",
    }
    return mapping.get(field.lower(), field)
