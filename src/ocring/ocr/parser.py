from __future__ import annotations

from dataclasses import dataclass

from .inventory_definition_engine import InventoryDefinitionEngine
from .profile import Profile


@dataclass(frozen=True)
class ParsedField:
    value: str
    status: str
    source_text: str


@dataclass(frozen=True)
class ParsedRecord:
    record_class: str
    definition_used: str
    fields: dict[str, ParsedField]


class ProfileDrivenParser:
    def __init__(self, profile: Profile) -> None:
        self.profile = profile
        self.definition_engine = InventoryDefinitionEngine(profile)

    def parse_record(self, observed_fields: dict[str, str]) -> ParsedRecord:
        normalized_fields: dict[str, ParsedField] = {}
        cleaned_observed: dict[str, str] = {}
        for field_name, raw_value in observed_fields.items():
            normalized_name = self.definition_engine._normalize_field_name(field_name)
            cleaned_value = self.definition_engine.apply_alias(normalized_name, str(raw_value))
            cleaned_value = self.definition_engine.apply_patterns(normalized_name, cleaned_value)
            cleaned_observed[normalized_name] = cleaned_value
            normalized_fields[normalized_name] = ParsedField(
                value=cleaned_value,
                status="OBSERVED" if cleaned_value else "UNKNOWN",
                source_text=str(raw_value),
            )

        record_class = self.definition_engine.determine_record_class(cleaned_observed)
        definition = self.definition_engine.get_definition(record_class)
        for field in definition.fields:
            if field.field_name in normalized_fields and normalized_fields[field.field_name].value:
                continue
            if field.default:
                normalized_fields[field.field_name] = ParsedField(
                    value=field.default,
                    status=field.default_status or "DEFAULTED",
                    source_text="",
                )
            elif field.required and field.field_name not in normalized_fields:
                normalized_fields[field.field_name] = ParsedField(
                    value="",
                    status="UNKNOWN",
                    source_text="",
                )

        return ParsedRecord(
            record_class=record_class,
            definition_used=record_class,
            fields=normalized_fields,
        )
