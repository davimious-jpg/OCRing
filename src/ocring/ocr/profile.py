from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any
from uuid import uuid4


DEFAULT_PROFILES_ROOT = Path("E:/Ocring/profiles")


@dataclass
class Profile:
    profile_id: str
    profile_name: str
    version: str
    inventory_definitions: list[dict[str, Any]] = field(default_factory=list)
    record_definitions: list[dict[str, Any]] = field(default_factory=list)
    field_aliases: dict[str, dict[str, str]] = field(default_factory=dict)
    field_patterns: dict[str, list[str]] = field(default_factory=dict)
    screens: list[dict[str, Any]] = field(default_factory=list)
    parsing_rules: dict[str, Any] = field(default_factory=dict)
    rarity_rules: list[dict[str, Any]] = field(default_factory=list)
    compatibility_rules: list[dict[str, Any]] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def load_profile(profile_id: str, *, profiles_root: Path = DEFAULT_PROFILES_ROOT) -> Profile:
    path = profiles_root / profile_id / "profile.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    if str(payload.get("profile_kind") or "").lower() == "generic":
        from .generic_profile import load_generic_profile

        return load_generic_profile(profile_id, profiles_root=profiles_root)
    return Profile(
        profile_id=str(payload.get("profile_id") or profile_id),
        profile_name=str(payload.get("profile_name") or profile_id),
        version=str(payload.get("version") or "1"),
        inventory_definitions=_as_list_of_dicts(payload.get("inventory_definitions")),
        record_definitions=_as_list_of_dicts(payload.get("record_definitions")),
        field_aliases=_as_nested_dict(payload.get("field_aliases")),
        field_patterns=_as_dict_of_lists(payload.get("field_patterns")),
        screens=_as_list_of_dicts(payload.get("screens")),
        parsing_rules=_as_dict(payload.get("parsing_rules")),
        rarity_rules=_as_list_of_dicts(payload.get("rarity_rules")),
        compatibility_rules=_as_list_of_dicts(payload.get("compatibility_rules")),
    )


def save_profile(profile: Profile, *, profiles_root: Path = DEFAULT_PROFILES_ROOT) -> Path:
    profile_dir = profiles_root / profile.profile_id
    profile_dir.mkdir(parents=True, exist_ok=True)
    profile_path = profile_dir / "profile.json"
    profile_path.write_text(json.dumps(profile.as_dict(), indent=2, sort_keys=True), encoding="utf-8")
    return profile_path


def create_default_template() -> Profile:
    profile_id = f"profile-{uuid4().hex[:8]}"
    return Profile(
        profile_id=profile_id,
        profile_name="Generic Profile",
        version="1",
        inventory_definitions=[
            {
                "canonical_id": "item_name",
                "label": "Item Name",
                "required": True,
                "extraction_source": "ocr.item_name",
            },
            {
                "canonical_id": "item_rarity",
                "label": "Item Rarity",
                "required": True,
                "extraction_source": "ocr.item_rarity",
            },
            {
                "canonical_id": "item_type",
                "label": "Item Type",
                "required": True,
                "extraction_source": "ocr.item_type",
            },
            {
                "canonical_id": "item_count",
                "label": "Item Count",
                "required": False,
                "extraction_source": "ocr.item_count",
            },
        ],
        record_definitions=[
            {
                "record_class": "Weapon",
                "fields": [
                    {
                        "field_name": "item_name",
                        "required": True,
                        "sources": ["visible_text", "dictionary_match", "AI_reconstruction"],
                    },
                    {
                        "field_name": "item_rarity",
                        "required": True,
                        "sources": ["visible_text", "color", "roman_numeral"],
                        "allowed_values": ["Tier I", "Tier II", "Tier III", "Tier IV"],
                    },
                    {
                        "field_name": "item_type",
                        "required": True,
                        "sources": ["visible_text", "dictionary_match"],
                        "allowed_values": ["Rocket Launcher", "SMG", "Shotgun", "Pistol", "Assault Rifle"],
                    },
                    {
                        "field_name": "item_count",
                        "required": False,
                        "sources": ["visible_text", "regex"],
                        "patterns": ["x{number}", "{number}x", "Quantity: {number}", "Qty: {number}"],
                        "default": "1",
                        "default_status": "DEFAULTED",
                    },
                    {
                        "field_name": "item_synergy",
                        "required": False,
                        "sources": ["visible_text", "dictionary_match", "AI_reconstruction"],
                    },
                ],
            },
            {
                "record_class": "WeaponMod",
                "fields": [
                    {
                        "field_name": "item_name",
                        "required": True,
                        "sources": ["visible_text", "dictionary_match", "AI_reconstruction"],
                    },
                    {
                        "field_name": "mod_slot",
                        "required": False,
                        "sources": ["visible_text", "dictionary_match"],
                        "allowed_values": ["Barrel", "Scope"],
                    },
                ],
            },
        ],
        field_aliases={
            "item_rarity": {"epic": "Tier IV", "legendary": "Tier V"},
            "item_count": {"qty": "Qty:"},
        },
        field_patterns={
            "item_count": ["x{number}", "{number}x", "Quantity: {number}", "Qty: {number}"],
        },
        screens=[
            {
                "screen_class": "inventory",
                "roi": {"x1": 0, "y1": 0, "x2": 1920, "y2": 1080},
                "rows": 8,
            }
        ],
        parsing_rules={
            "count_pattern": r"\d+",
            "normalize_whitespace": True,
        },
        rarity_rules=[
            {"tier": "Tier I", "color": "#9e9e9e", "name": "Common"},
            {"tier": "Tier II", "color": "#4caf50", "name": "Uncommon"},
            {"tier": "Tier III", "color": "#2196f3", "name": "Rare"},
            {"tier": "Tier IV", "color": "#9c27b0", "name": "Epic"},
        ],
        compatibility_rules=[
            {"screen_class": "inventory", "supports_counts": True, "supports_rarity": True}
        ],
    )


def list_profiles(*, profiles_root: Path = DEFAULT_PROFILES_ROOT) -> list[Profile]:
    if not profiles_root.exists():
        return []
    profiles: list[Profile] = []
    for profile_path in sorted(profiles_root.glob("*/profile.json")):
        try:
            profiles.append(load_profile(profile_path.parent.name, profiles_root=profiles_root))
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            continue
    return profiles


def is_generic(profile_id: str, *, profiles_root: Path = DEFAULT_PROFILES_ROOT) -> bool:
    path = profiles_root / profile_id / "profile.json"
    if not path.exists():
        return profile_id.startswith("generic-")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    return str(payload.get("profile_kind") or "").lower() == "generic"


def resolve_profile_runtime(profile_id: str, *, profiles_root: Path = DEFAULT_PROFILES_ROOT) -> dict[str, Any]:
    if is_generic(profile_id, profiles_root=profiles_root):
        from .generic_profile import load_generic_profile

        profile = load_generic_profile(profile_id, profiles_root=profiles_root)
        return {
            "profile_id": profile.profile_id,
            "mode": "generic",
            "apply_defiance_policy": False,
            "field_rules": list(profile.custom_fields),
            "region_roi": dict(profile.region_roi),
            "scan_scope": profile.scan_scope,
            "generic_session_id": profile.generic_session_id,
        }
    return {
        "profile_id": profile_id,
        "mode": "standard",
        "apply_defiance_policy": profile_id == "defiance",
        "field_rules": [],
        "region_roi": {},
        "scan_scope": "",
        "generic_session_id": "",
    }


def delete_profile(profile_id: str, *, profiles_root: Path = DEFAULT_PROFILES_ROOT) -> bool:
    profile_dir = profiles_root / profile_id
    profile_path = profile_dir / "profile.json"
    if not profile_path.exists():
        return False
    profile_path.unlink()
    try:
        profile_dir.rmdir()
    except OSError:
        pass
    return True


def _as_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    return {}


def _as_list_of_dicts(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    items: list[dict[str, Any]] = []
    for entry in value:
        if isinstance(entry, dict):
            items.append(dict(entry))
    return items


def _as_nested_dict(value: Any) -> dict[str, dict[str, str]]:
    if not isinstance(value, dict):
        return {}
    nested: dict[str, dict[str, str]] = {}
    for key, entry in value.items():
        if not isinstance(entry, dict):
            continue
        nested[str(key)] = {
            str(inner_key): str(inner_value)
            for inner_key, inner_value in entry.items()
        }
    return nested


def _as_dict_of_lists(value: Any) -> dict[str, list[str]]:
    if not isinstance(value, dict):
        return {}
    result: dict[str, list[str]] = {}
    for key, entry in value.items():
        if not isinstance(entry, list):
            continue
        result[str(key)] = [str(item) for item in entry]
    return result
