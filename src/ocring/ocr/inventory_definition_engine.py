from __future__ import annotations

from dataclasses import dataclass, field
import re
from typing import Any

from .profile import Profile


@dataclass(frozen=True)
class FieldDefinition:
    field_name: str
    required: bool
    sources: tuple[str, ...] = ()
    allowed_values: tuple[str, ...] = ()
    patterns: tuple[str, ...] = ()
    aliases: dict[str, str] = field(default_factory=dict)
    default: str = ""
    default_status: str = ""


@dataclass(frozen=True)
class InventoryDefinition:
    record_class: str
    fields: tuple[FieldDefinition, ...]


class InventoryDefinitionEngine:
    def __init__(self, profile: Profile) -> None:
        self.profile = profile
        self._definitions = self._load_definitions(profile)
        self._field_map = self._build_field_map(self._definitions)

    def get_definition(self, record_class: str) -> InventoryDefinition:
        for definition in self._definitions:
            if definition.record_class == record_class:
                return definition
        raise KeyError(f"Unknown record class: {record_class}")

    def get_field_definition(self, field_name: str) -> FieldDefinition:
        normalized = self._normalize_field_name(field_name)
        if normalized not in self._field_map:
            raise KeyError(f"Unknown field definition: {field_name}")
        return self._field_map[normalized]

    def get_allowed_values(self, field_name: str) -> list[str]:
        return list(self.get_field_definition(field_name).allowed_values)

    def get_required_fields(self, record_class: str) -> list[str]:
        definition = self.get_definition(record_class)
        return [field.field_name for field in definition.fields if field.required]

    def apply_alias(self, field_name: str, value: str) -> str:
        field = self.get_field_definition(field_name)
        lookup = value.strip().lower()
        if lookup in field.aliases:
            return field.aliases[lookup]
        return value.strip()

    def apply_patterns(self, field_name: str, value: str) -> str:
        field = self.get_field_definition(field_name)
        text = value.strip()
        for pattern in field.patterns:
            match = _pattern_to_regex(pattern).fullmatch(text)
            if match:
                number = match.groupdict().get("number", "")
                if number:
                    return number
        return text

    def default_for(self, field_name: str) -> tuple[str, str]:
        field = self.get_field_definition(field_name)
        return field.default, field.default_status

    def determine_record_class(self, observed_fields: dict[str, str]) -> str:
        item_type = str(observed_fields.get("item_type") or "").strip().lower()
        joined = " ".join(str(value) for value in observed_fields.values()).lower()
        for definition in self._definitions:
            record_class = definition.record_class.lower()
            if record_class == "weapon" and item_type in {"rocket launcher", "smg", "shotgun", "pistol", "assault rifle"}:
                return definition.record_class
            if record_class == "weaponmod" and "mod" in joined:
                return definition.record_class
            if record_class == "shield" and "shield" in joined:
                return definition.record_class
        return self._definitions[0].record_class if self._definitions else "UNKNOWN"

    @property
    def definitions(self) -> tuple[InventoryDefinition, ...]:
        return self._definitions

    def _load_definitions(self, profile: Profile) -> tuple[InventoryDefinition, ...]:
        raw_definitions = list(profile.record_definitions)
        if not raw_definitions:
            raw_definitions = [_fallback_definition(profile)]
        definitions: list[InventoryDefinition] = []
        for raw_definition in raw_definitions:
            fields: list[FieldDefinition] = []
            for field_payload in raw_definition.get("fields", []):
                field_name = self._normalize_field_name(str(field_payload.get("field_name") or field_payload.get("canonical_id") or ""))
                if not field_name:
                    continue
                fields.append(
                    FieldDefinition(
                        field_name=field_name,
                        required=bool(field_payload.get("required", False)),
                        sources=tuple(str(item) for item in field_payload.get("sources", ()) if str(item).strip()),
                        allowed_values=tuple(str(item) for item in field_payload.get("allowed_values", ()) if str(item).strip()),
                        patterns=tuple(str(item) for item in field_payload.get("patterns", ()) if str(item).strip()),
                        aliases={
                            str(key).strip().lower(): str(value).strip()
                            for key, value in dict(field_payload.get("aliases") or {}).items()
                            if str(key).strip()
                        },
                        default=str(field_payload.get("default") or ""),
                        default_status=str(field_payload.get("default_status") or ""),
                    )
                )
            definitions.append(
                InventoryDefinition(
                    record_class=str(raw_definition.get("record_class") or "Weapon"),
                    fields=tuple(fields),
                )
            )
        return tuple(definitions)

    def _build_field_map(self, definitions: tuple[InventoryDefinition, ...]) -> dict[str, FieldDefinition]:
        mapping: dict[str, FieldDefinition] = {}
        for definition in definitions:
            for field in definition.fields:
                mapping.setdefault(field.field_name, field)
        return mapping

    def _normalize_field_name(self, field_name: str) -> str:
        mapping = {
            "rarity": "item_rarity",
            "type": "item_type",
            "name": "item_name",
            "count": "item_count",
            "synergy": "item_synergy",
            "slot": "mod_slot",
        }
        normalized = field_name.strip().lower()
        return mapping.get(normalized, normalized)


def _fallback_definition(profile: Profile) -> dict[str, Any]:
    rarity_values = [str(rule.get("tier") or "").strip() for rule in profile.rarity_rules if str(rule.get("tier") or "").strip()]
    return {
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
                "allowed_values": rarity_values,
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
    }


def _pattern_to_regex(pattern: str) -> re.Pattern[str]:
    escaped = re.escape(pattern).replace("\\{number\\}", r"(?P<number>\d+)")
    return re.compile(escaped, re.IGNORECASE)
