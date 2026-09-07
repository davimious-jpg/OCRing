from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class EvidenceRequirement:
    field_name: str
    description: str

    def satisfied_by(self, evidence: dict[str, object]) -> bool:
        raise NotImplementedError


@dataclass(frozen=True)
class VisibleTextRequirement(EvidenceRequirement):
    def satisfied_by(self, evidence: dict[str, object]) -> bool:
        return bool(str(evidence.get("visible_text") or "").strip())


@dataclass(frozen=True)
class AnyOfRequirement(EvidenceRequirement):
    required_groups: tuple[tuple[str, ...], ...]

    def satisfied_by(self, evidence: dict[str, object]) -> bool:
        for group in self.required_groups:
            if all(_truthy(evidence.get(key)) for key in group):
                return True
        return False


FIELD_REQUIREMENTS: dict[str, EvidenceRequirement] = {
    "item_name": VisibleTextRequirement("item_name", "visible_text"),
    "item_rarity": AnyOfRequirement("item_rarity", "visible_text OR (tier + color)", (("visible_text",), ("tier", "color"))),
    "item_count": AnyOfRequirement("item_count", "visible_numeric OR explicit_default", (("visible_numeric",), ("explicit_default",))),
    "rarity": AnyOfRequirement("rarity", "visible_text OR (tier + color)", (("visible_text",), ("tier", "color"))),
    "quantity": AnyOfRequirement("quantity", "visible_numeric OR explicit_default", (("visible_numeric",), ("explicit_default",))),
}


def get_requirement(field_name: str) -> EvidenceRequirement:
    normalized = _normalize_field_name(field_name)
    if normalized not in FIELD_REQUIREMENTS:
        return VisibleTextRequirement(normalized, "visible_text")
    return FIELD_REQUIREMENTS[normalized]


def satisfies_evidence_requirement(field_name: str, evidence: dict[str, object]) -> bool:
    return get_requirement(field_name).satisfied_by(evidence)


def required_evidence_summary(field_name: str) -> str:
    return get_requirement(field_name).description


def _normalize_field_name(field_name: str) -> str:
    mapping = {
        "name": "item_name",
        "item_name": "item_name",
        "rarity": "item_rarity",
        "item_rarity": "item_rarity",
        "quantity": "item_count",
        "count": "item_count",
        "item_count": "item_count",
    }
    return mapping.get(str(field_name).strip().lower(), str(field_name).strip().lower())


def _truthy(value: object) -> bool:
    if isinstance(value, bool):
        return value
    return bool(str(value or "").strip())

