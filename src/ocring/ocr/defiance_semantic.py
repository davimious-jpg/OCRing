from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


DEFAULT_DEFIANCE_PROFILE = Path("E:/Ocring/profiles/defiance/profile.json")


@dataclass(frozen=True)
class RarityConflict:
    text_tier: str
    observed_color: str
    expected_color: str
    message: str


@dataclass(frozen=True)
class CompatibilityWarning:
    mod_slot: str
    weapon_type: str
    message: str


class DefianceSemantic:
    def __init__(
        self,
        *,
        mod_slot_compatibility: dict[str, list[str]],
        rarity_definitions: dict[str, dict[str, str]],
    ) -> None:
        self.mod_slot_compatibility = {
            _normalize_slot(slot): [_normalize_weapon_type(item) for item in supported]
            for slot, supported in mod_slot_compatibility.items()
        }
        self.rarity_definitions = {
            _normalize_tier(tier): {
                "color_name": str(values.get("color_name", "")).strip(),
                "color_hex": str(values.get("color_hex", "")).strip().lower(),
                "label": str(values.get("label", "")).strip(),
            }
            for tier, values in rarity_definitions.items()
        }

    @classmethod
    def load(cls, path: Path = DEFAULT_DEFIANCE_PROFILE) -> DefianceSemantic:
        payload = _default_profile_payload()
        if path.exists():
            try:
                loaded = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                loaded = {}
            if isinstance(loaded, dict):
                payload.update(loaded)
        return cls(
            mod_slot_compatibility=_dict_of_lists(payload.get("mod_slot_compatibility")),
            rarity_definitions=_rarity_definitions(payload.get("rarity_definitions")),
        )

    def is_slot_compatible(self, mod_slot: str, weapon_type: str) -> bool:
        normalized_slot = _normalize_slot(mod_slot)
        normalized_weapon = _normalize_weapon_type(weapon_type)
        supported = set(self.mod_slot_compatibility.get(normalized_slot, ()))
        explicitly_unsupported = set(self.mod_slot_compatibility.get(f"{normalized_slot}_unsupported", ()))
        if normalized_weapon in explicitly_unsupported:
            return False
        if not supported:
            return True
        return normalized_weapon in supported

    def get_supported_slots(self, weapon_type: str) -> list[str]:
        normalized_weapon = _normalize_weapon_type(weapon_type)
        supported: list[str] = []
        for slot, weapon_types in self.mod_slot_compatibility.items():
            if slot.endswith("_unsupported"):
                continue
            if normalized_weapon in weapon_types and normalized_weapon not in self.mod_slot_compatibility.get(f"{slot}_unsupported", ()):
                supported.append(slot)
        return sorted(dict.fromkeys(supported))

    def get_unsupported_slots(self, weapon_type: str) -> list[str]:
        normalized_weapon = _normalize_weapon_type(weapon_type)
        unsupported: list[str] = []
        for slot, weapon_types in self.mod_slot_compatibility.items():
            if not slot.endswith("_unsupported"):
                continue
            if normalized_weapon in weapon_types:
                unsupported.append(slot.removesuffix("_unsupported"))
        return sorted(dict.fromkeys(unsupported))

    def detect_rarity_conflict(self, text_tier: str, observed_color: str) -> RarityConflict | None:
        normalized_tier = _normalize_tier(text_tier)
        expected = self.rarity_definitions.get(normalized_tier)
        if not expected:
            return None
        observed = _normalize_color(observed_color)
        expected_color = _normalize_color(expected.get("color_name", "")) or _normalize_color(expected.get("label", ""))
        if not observed or not expected_color or observed == expected_color:
            return None
        return RarityConflict(
            text_tier=text_tier,
            observed_color=observed_color,
            expected_color=expected.get("color_name", "") or expected.get("label", ""),
            message=f"Rarity conflict: text says {text_tier}, color observed {observed_color}",
        )

    def detect_slot_compatibility_warning(self, mod_slot: str, weapon_type: str) -> CompatibilityWarning | None:
        if self.is_slot_compatible(mod_slot, weapon_type):
            return None
        return CompatibilityWarning(
            mod_slot=mod_slot,
            weapon_type=weapon_type,
            message=f"Slot compatibility warning: {mod_slot} mod on {weapon_type}",
        )


def _default_profile_payload() -> dict[str, Any]:
    return {
        "mod_slot_compatibility": {
            "stock": [
                "assault_rifle",
                "battle_rifle",
                "submachine_gun",
                "light_machine_gun",
                "shotgun",
                "sniper_rifle",
                "pistol",
            ],
            "barrel": [
                "assault_rifle",
                "battle_rifle",
                "submachine_gun",
                "light_machine_gun",
                "shotgun",
                "sniper_rifle",
                "pistol",
            ],
            "magazine": [
                "assault_rifle",
                "battle_rifle",
                "submachine_gun",
                "light_machine_gun",
                "shotgun",
                "sniper_rifle",
                "pistol",
            ],
            "scope": [
                "assault_rifle",
                "battle_rifle",
                "submachine_gun",
                "light_machine_gun",
                "shotgun",
                "sniper_rifle",
            ],
            "scope_unsupported": ["grenade_launcher", "infector"],
        },
        "rarity_definitions": {
            "Tier I": {"color_name": "Gray", "color_hex": "#9e9e9e", "label": "Common"},
            "Tier II": {"color_name": "Green", "color_hex": "#4caf50", "label": "Uncommon"},
            "Tier III": {"color_name": "Blue", "color_hex": "#2196f3", "label": "Rare"},
            "Tier IV": {"color_name": "Purple", "color_hex": "#9c27b0", "label": "Epic"},
            "Tier V": {"color_name": "Orange", "color_hex": "#ff9800", "label": "Legendary"},
        },
    }


def _dict_of_lists(value: Any) -> dict[str, list[str]]:
    if not isinstance(value, dict):
        return {}
    result: dict[str, list[str]] = {}
    for key, items in value.items():
        if isinstance(items, list):
            result[str(key)] = [str(item) for item in items]
    return result


def _rarity_definitions(value: Any) -> dict[str, dict[str, str]]:
    if not isinstance(value, dict):
        return {}
    result: dict[str, dict[str, str]] = {}
    for key, item in value.items():
        if isinstance(item, dict):
            result[str(key)] = {str(inner_key): str(inner_value) for inner_key, inner_value in item.items()}
    return result


def _normalize_slot(value: str) -> str:
    return str(value).strip().lower().replace(" ", "_")


def _normalize_weapon_type(value: str) -> str:
    return str(value).strip().lower().replace(" ", "_")


def _normalize_tier(value: str) -> str:
    return " ".join(str(value).strip().split())


def _normalize_color(value: str) -> str:
    normalized = str(value).strip().lower()
    aliases = {
        "grey": "gray",
        "#9e9e9e": "gray",
        "#4caf50": "green",
        "#2196f3": "blue",
        "#9c27b0": "purple",
        "#ff9800": "orange",
    }
    return aliases.get(normalized, normalized)
