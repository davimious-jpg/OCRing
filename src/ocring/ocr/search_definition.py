from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .profile import DEFAULT_PROFILES_ROOT, Profile, create_default_template, load_profile


DEFAULT_QUICK_TABS = ("All", "Weapons", "Mods", "Synergy", "Rarity", "Weapon Type")
DEFAULT_SEARCHABLE_FIELDS = ("item_name", "item_rarity", "item_synergy", "item_type", "item_count", "mod_slot", "tier")
DEFAULT_FILTERABLE_FIELDS = ("item_rarity", "item_synergy", "item_type", "mod_slot", "tier")
DEFAULT_SORTABLE_FIELDS = ("item_name", "item_rarity", "item_type", "item_count", "recently_added")


@dataclass(frozen=True)
class SearchDefinition:
    searchable_fields: tuple[str, ...]
    quick_tabs: tuple[str, ...]
    filterable_fields: tuple[str, ...]
    sortable_fields: tuple[str, ...]
    suggestions: dict[str, tuple[str, ...]]

    @classmethod
    def load_active_profile(
        cls,
        profile_id: str,
        *,
        profiles_root: Path = DEFAULT_PROFILES_ROOT,
    ) -> "SearchDefinition":
        try:
            profile = load_profile(profile_id, profiles_root=profiles_root)
        except OSError:
            profile = create_default_template()
            profile.profile_id = profile_id
        return cls.from_profile(profile)

    @classmethod
    def from_profile(cls, profile: Profile) -> "SearchDefinition":
        searchable = _ordered_union(
            DEFAULT_SEARCHABLE_FIELDS,
            tuple(
                str(definition.get("canonical_id") or "").strip()
                for definition in profile.inventory_definitions
                if str(definition.get("canonical_id") or "").strip()
            ),
        )
        suggestions = {
            "item_synergy": _known_synergies(profile),
            "item_type": _known_weapon_types(profile),
            "mod_slot": _known_mod_slots(profile),
            "item_rarity": _known_rarities(profile),
            "tier": _known_tiers(profile),
        }
        return cls(
            searchable_fields=searchable,
            quick_tabs=DEFAULT_QUICK_TABS,
            filterable_fields=tuple(field for field in DEFAULT_FILTERABLE_FIELDS if field in searchable or field in suggestions),
            sortable_fields=DEFAULT_SORTABLE_FIELDS,
            suggestions=suggestions,
        )

    def validate_field(self, field_name: str) -> bool:
        normalized = _normalize_field_name(field_name)
        return normalized in self.searchable_fields or normalized in {"review_status", "recently_added"}

    def suggest(self, partial_input: str) -> list[str]:
        needle = partial_input.strip().lower()
        if not needle:
            return []
        matches: list[str] = []
        for key in ("item_synergy", "item_type", "mod_slot", "item_rarity", "tier"):
            values = self.suggestions.get(key, ())
            category_matches: list[str] = []
            for value in values:
                if value.lower().startswith(needle) and value not in category_matches:
                    category_matches.append(value)
            if category_matches:
                matches.extend(category_matches)
                break
        return matches

    def quick_tab_query(self, tab_name: str) -> tuple[str, dict[str, object]]:
        mapping = {
            "All": ("", {}),
            "Weapons": ("", {"item_type": "Rocket Launcher"}),
            "Mods": ("", {"mod_slot": "Barrel"}),
            "Synergy": ("", {"item_synergy": "Epidemic"}),
            "Rarity": ("", {"item_rarity": self.suggestions.get("item_rarity", ("",))[0] or ""}),
            "Weapon Type": ("", {"item_type": self.suggestions.get("item_type", ("",))[0] or ""}),
        }
        return mapping.get(tab_name, ("", {}))


def _known_synergies(profile: Profile) -> tuple[str, ...]:
    parsing = profile.parsing_rules if isinstance(profile.parsing_rules, dict) else {}
    values = parsing.get("known_synergies", ["Epidemic", "Ether Acceleration"])
    return tuple(_clean_values(values))


def _known_weapon_types(profile: Profile) -> tuple[str, ...]:
    parsing = profile.parsing_rules if isinstance(profile.parsing_rules, dict) else {}
    values = parsing.get("known_weapon_types", ["Rocket Launcher", "SMG"])
    return tuple(_clean_values(values))


def _known_mod_slots(profile: Profile) -> tuple[str, ...]:
    parsing = profile.parsing_rules if isinstance(profile.parsing_rules, dict) else {}
    values = parsing.get("known_mod_slots", ["Barrel", "Scope"])
    return tuple(_clean_values(values))


def _known_rarities(profile: Profile) -> tuple[str, ...]:
    values = [str(rule.get("name") or "").strip() for rule in profile.rarity_rules]
    cleaned = tuple(_clean_values(values))
    return cleaned or ("Legendary", "Epic")


def _known_tiers(profile: Profile) -> tuple[str, ...]:
    values = [str(rule.get("tier") or "").strip() for rule in profile.rarity_rules]
    cleaned = tuple(_clean_values(values))
    return cleaned or ("Tier IV", "Tier III")


def _clean_values(values: object) -> list[str]:
    if not isinstance(values, (list, tuple)):
        return []
    cleaned: list[str] = []
    for value in values:
        text = str(value).strip()
        if text and text not in cleaned:
            cleaned.append(text)
    return cleaned


def _ordered_union(primary: tuple[str, ...], secondary: tuple[str, ...]) -> tuple[str, ...]:
    seen: list[str] = []
    for value in primary + secondary:
        normalized = _normalize_field_name(value)
        if normalized and normalized not in seen:
            seen.append(normalized)
    return tuple(seen)


def _normalize_field_name(field_name: str) -> str:
    mapping = {
        "rarity": "item_rarity",
        "type": "item_type",
        "name": "item_name",
        "count": "item_count",
        "synergy": "item_synergy",
    }
    return mapping.get(field_name.strip().lower(), field_name.strip().lower())
