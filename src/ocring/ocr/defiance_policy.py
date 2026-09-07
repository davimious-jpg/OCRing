from __future__ import annotations

from dataclasses import dataclass
import re

from .models import FieldKind


@dataclass(frozen=True)
class DefiancePolicy:
    allowed_weapon_types: frozenset[str]
    allowed_mod_slot_types: frozenset[str]
    allowed_rarity_values: frozenset[str]
    known_name_tokens: frozenset[str]
    known_synergies: frozenset[str]
    name_type_expectations: dict[str, frozenset[str]]


def load_defiance_policy() -> DefiancePolicy:
    return DefiancePolicy(
        allowed_weapon_types=frozenset(
            {
                "Assault Rifle",
                "Battle Rifle",
                "Submachine Gun",
                "Light Machine Gun",
                "Shotgun",
                "Sniper Rifle",
                "Pistol",
                "Rocket Launcher",
                "Detonator",
                "Infector",
                "Grenade Launcher",
            }
        ),
        allowed_mod_slot_types=frozenset(
            {
                "Barrel",
                "Magazine",
                "Scope",
                "Stock",
            }
        ),
        allowed_rarity_values=frozenset(
            {
                "Common",
                "Uncommon",
                "Rare",
                "Epic",
                "Legendary",
                "Tier I",
                "Tier II",
                "Tier III",
                "Tier IV",
                "Tier V",
            }
        ),
        known_name_tokens=frozenset(
            {
                "Power",
                "Bore",
                "Hellbug",
                "Rocket",
                "Guerrilla",
                "Buttstock",
                "Recoil",
                "Dampener",
                "Ionic",
                "Barrel",
                "Munitions",
                "Interchanger",
                "Tactical",
                "Scope",
                "Stabilization",
                "Sight",
            }
        ),
        known_synergies=frozenset(
            {
                "Epidemic",
                "Ether Acceleration",
            }
        ),
        name_type_expectations={
            "Rocket": frozenset({"Rocket Launcher"}),
            "Scope": frozenset({"Unknown"}),
            "Sight": frozenset({"Unknown"}),
            "Barrel": frozenset({"Unknown"}),
            "Buttstock": frozenset({"Unknown"}),
            "Magazine": frozenset({"Unknown"}),
        },
    )


def validate_candidate(field_kind: FieldKind, candidate_value: str, *, policy: DefiancePolicy) -> tuple[bool, tuple[str, ...]]:
    if not candidate_value:
        return False, ("EMPTY_CANDIDATE",)

    if field_kind is FieldKind.ITEM_RARITY:
        if candidate_value in policy.allowed_rarity_values:
            return True, ()
        return False, ("RARITY_NOT_ALLOWED",)

    if field_kind is FieldKind.ITEM_TYPE:
        if candidate_value in policy.allowed_weapon_types or candidate_value in policy.allowed_mod_slot_types:
            return True, ()
        return False, ("WEAPON_TYPE_NOT_ALLOWED",)

    if field_kind is FieldKind.ITEM_COUNT:
        if candidate_value.isdigit():
            return True, ()
        return False, ("COUNT_NOT_NUMERIC",)

    if field_kind is FieldKind.ITEM_NAME:
        tokens = [token for token in candidate_value.split() if token]
        if not tokens:
            return False, ("ITEM_NAME_EMPTY",)
        overlap = sum(1 for token in tokens if token in policy.known_name_tokens)
        if overlap >= 1:
            return True, ()
        if _looks_like_plausible_item_name(candidate_value):
            return True, ("REFERENCE_DATA_MISSING",)
        return False, ("ITEM_NAME_UNKNOWN_TOKENS",)

    if field_kind is FieldKind.ITEM_SYNERGY:
        if candidate_value in policy.known_synergies:
            return True, ()
        if _looks_like_plausible_synergy(candidate_value):
            return True, ("REFERENCE_DATA_MISSING",)
        return False, ("SYNERGY_NOT_ALLOWED",)

    return False, ("FIELD_KIND_UNSUPPORTED",)


def _looks_like_plausible_item_name(candidate_value: str) -> bool:
    tokens = re.findall(r"[A-Za-z0-9]+", candidate_value)
    if len(tokens) < 2:
        return False
    alpha_tokens = [token for token in tokens if any(char.isalpha() for char in token)]
    if len(alpha_tokens) < 2:
        return False
    if any(len(token) >= 4 for token in alpha_tokens):
        return True
    return False


def _looks_like_plausible_synergy(candidate_value: str) -> bool:
    tokens = re.findall(r"[A-Za-z0-9']+", candidate_value)
    if len(tokens) < 2:
        return False
    alpha_tokens = [token for token in tokens if any(char.isalpha() for char in token)]
    if len(alpha_tokens) < 2:
        return False
    if any(len(token) >= 4 for token in alpha_tokens):
        return True
    return False


def detect_semantic_contradictions(fields: dict[FieldKind, str], *, policy: DefiancePolicy) -> tuple[tuple[FieldKind, str, str], ...]:
    contradictions: list[tuple[FieldKind, str, str]] = []

    count_value = fields.get(FieldKind.ITEM_COUNT, "")
    if count_value == "0":
        contradictions.append((FieldKind.ITEM_COUNT, count_value, "COUNT_ZERO_INVALID"))

    item_name = fields.get(FieldKind.ITEM_NAME, "")
    item_type = fields.get(FieldKind.ITEM_TYPE, "")
    if item_name and item_type:
        for token, expected_types in policy.name_type_expectations.items():
            if token.lower() not in item_name.lower():
                continue
            if "Unknown" in expected_types:
                if item_type in {
                    "Rocket Launcher",
                    "Shotgun",
                    "Assault Rifle",
                    "Battle Rifle",
                    "Submachine Gun",
                    "Light Machine Gun",
                    "Sniper Rifle",
                    "Pistol",
                    "Detonator",
                    "Infector",
                    "Grenade Launcher",
                }:
                    contradictions.append((FieldKind.ITEM_TYPE, item_type, f"NAME_TOKEN_{token.upper()}_LOOKS_NON_WEAPON"))
            elif item_type not in expected_types:
                contradictions.append((FieldKind.ITEM_TYPE, item_type, f"NAME_TOKEN_{token.upper()}_TYPE_MISMATCH"))

    return tuple(dict.fromkeys(contradictions))
