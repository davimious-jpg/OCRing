from __future__ import annotations

from dataclasses import dataclass, field
import re

from .inventory_definition_engine import InventoryDefinitionEngine
from .profile import Profile


@dataclass(frozen=True)
class CandidateInventoryRecord:
    record_class: str
    field_values: dict[str, str]
    status: str
    confidence: float
    provenance: dict[str, object] = field(default_factory=dict)

    def as_dict(self) -> dict[str, object]:
        return {
            "record_class": self.record_class,
            "field_values": dict(self.field_values),
            "status": self.status,
            "confidence": self.confidence,
            "provenance": dict(self.provenance),
        }


class SemanticAllocator:
    def __init__(self, *, definition_engine: InventoryDefinitionEngine | None = None) -> None:
        self.definition_engine = definition_engine

    def allocate(
        self,
        repaired_fragments: tuple[str, ...] | list[str],
        contract: dict[str, object],
        *,
        profile_version: str = "",
    ) -> CandidateInventoryRecord:
        fragments = tuple(str(fragment).strip() for fragment in repaired_fragments if str(fragment).strip())
        allowed_rarities = tuple(str(value) for value in contract.get("allowed_rarities", ()))
        allowed_types = tuple(str(value) for value in contract.get("allowed_types", ()))
        allowed_classes = tuple(str(value) for value in contract.get("allowed_record_classes", ("Weapon", "WeaponMod", "Shield", "Grenade", "Consumable")))
        allowed_synergies = tuple(str(value) for value in contract.get("allowed_synergies", ()))
        allowed_mod_slots = tuple(str(value) for value in contract.get("allowed_mod_slots", ("Barrel", "Scope", "Magazine", "Stock")))

        rarity = _find_allowed_match(fragments, allowed_rarities) or _infer_rarity_label(fragments)
        item_type = _find_allowed_match(fragments, allowed_types, allow_embedded=False)
        mod_slot = _find_allowed_match(fragments, allowed_mod_slots)
        count = _find_count(fragments)
        slot = _find_slot(fragments)
        name = _find_name(fragments, excluded={rarity, item_type, count, slot})
        synergy = _find_allowed_match(fragments, allowed_synergies)
        if not synergy and allowed_synergies:
            synergy = _infer_synergy(
                fragments,
                excluded={rarity, item_type, mod_slot, name},
            )
        record_class = _classify_record_class(item_type, fragments, allowed_classes, mod_slot=mod_slot, item_name=name)

        matched_fields = {
            key: value
            for key, value in {
                "item_name": name,
                "item_rarity": rarity,
                "item_type": item_type,
                "item_synergy": synergy,
                "item_count": count,
                "item_slot": slot,
                "mod_slot": mod_slot,
            }.items()
            if value
        }
        confidence = _allocation_confidence(matched_fields, rarity=rarity, item_type=item_type or mod_slot, record_class=record_class)
        status = "READY"
        if record_class == "UNKNOWN" or confidence < 0.74:
            status = "NEEDS_REVIEW"
        prompt = self.build_prompt(record_class=record_class, contract=contract)

        return CandidateInventoryRecord(
            record_class=record_class,
            field_values=matched_fields,
            status=status,
            confidence=confidence,
            provenance={
                "allocated_by": "semantic_allocator",
                "contract_field_count": len(tuple(contract.get("field_definitions", ()))),
                "allowed_record_classes": list(allowed_classes),
                "prompt": prompt,
                "profile_version": profile_version,
            },
        )

    def build_prompt(self, *, record_class: str, contract: dict[str, object]) -> str:
        required_fields = []
        allowed_types = tuple(str(value) for value in contract.get("allowed_types", ()))
        if self.definition_engine is not None:
            try:
                required_fields = self.definition_engine.get_required_fields(record_class)
            except KeyError:
                required_fields = []
        if not required_fields:
            required_fields = [str(item.get("field_name") or item.get("canonical_id") or "") for item in contract.get("field_definitions", ()) if str(item.get("field_name") or item.get("canonical_id") or "").strip()]
        lines = [
            "You are interpreting a visible Defiance inventory record.",
            "",
            "Extract ONLY information that is visibly supported.",
            "",
            "Required output fields:",
        ]
        lines.extend(f"- {field_name}" for field_name in required_fields if field_name)
        if allowed_types:
            lines.extend(
                [
                    "",
                    "Allowed weapon types:",
                    ", ".join(allowed_types),
                ]
            )
        lines.extend(
            [
                "",
                "If a field is not visible:",
                "return UNKNOWN.",
                "",
                "Do not invent missing values.",
            ]
        )
        return "\n".join(lines)

    @classmethod
    def from_profile(cls, profile: Profile) -> "SemanticAllocator":
        return cls(definition_engine=InventoryDefinitionEngine(profile))


def _find_allowed_match(fragments: tuple[str, ...], allowed_values: tuple[str, ...], *, allow_embedded: bool = True) -> str:
    normalized_allowed = {re.sub(r"\s+", " ", value.strip().lower()): value for value in allowed_values if value}
    for fragment in fragments:
        normalized_fragment = re.sub(r"\s+", " ", fragment.strip().lower())
        if normalized_fragment in normalized_allowed:
            return normalized_allowed[normalized_fragment]
    if not allow_embedded:
        return ""
    for fragment in fragments:
        normalized_fragment = re.sub(r"\s+", " ", fragment.strip().lower())
        for normalized_value, original_value in normalized_allowed.items():
            if normalized_fragment in normalized_value or normalized_value in normalized_fragment:
                return original_value
    return ""


def _find_count(fragments: tuple[str, ...]) -> str:
    for fragment in fragments:
        match = re.fullmatch(r"\d+", fragment.strip())
        if match:
            return match.group(0)
        embedded = re.search(r"(\d+)", fragment.strip())
        if embedded:
            return embedded.group(1)
    return ""


def _find_slot(fragments: tuple[str, ...]) -> str:
    for fragment in fragments:
        if re.fullmatch(r"slot\s*\d+", fragment.strip().lower()):
            return fragment.strip()
    return ""


def _find_name(fragments: tuple[str, ...], *, excluded: set[str]) -> str:
    normalized_excluded = {value.strip().lower() for value in excluded if value}
    candidates = [
        fragment
        for fragment in fragments
        if fragment.strip().lower() not in normalized_excluded and not re.fullmatch(r"\d+", fragment.strip())
    ]
    if not candidates:
        return ""
    return max(candidates, key=lambda value: (_name_score(value), len(value.split()), len(value)))


def _classify_record_class(
    item_type: str,
    fragments: tuple[str, ...],
    allowed_classes: tuple[str, ...],
    *,
    mod_slot: str = "",
    item_name: str = "",
) -> str:
    joined = " ".join(fragments).lower()
    if item_type:
        if item_type.lower() in {"rocket launcher", "smg", "shotgun", "pistol", "assault rifle"} and "Weapon" in allowed_classes:
            return "Weapon"
    if mod_slot and "WeaponMod" in allowed_classes:
        return "WeaponMod"
    if _contains_mod_slot(item_name or joined) and "WeaponMod" in allowed_classes:
        return "WeaponMod"
    if "mod" in joined and "WeaponMod" in allowed_classes:
        return "WeaponMod"
    if item_type.lower() == "shield" and "Shield" in allowed_classes:
        return "Shield"
    if item_type.lower() == "grenade" and "Grenade" in allowed_classes:
        return "Grenade"
    if item_type.lower() == "consumable" and "Consumable" in allowed_classes:
        return "Consumable"
    return "UNKNOWN"


def _allocation_confidence(fields: dict[str, str], *, rarity: str, item_type: str, record_class: str) -> float:
    score = 0.35
    if fields.get("item_name"):
        score += 0.2
    if rarity:
        score += 0.15
    if item_type:
        score += 0.15
    if fields.get("item_count"):
        score += 0.05
    if record_class != "UNKNOWN":
        score += 0.15
    return round(min(1.0, score), 3)


def _infer_synergy(fragments: tuple[str, ...], *, excluded: set[str]) -> str:
    normalized_excluded = {value.strip().lower() for value in excluded if value}
    candidates = [
        fragment.strip()
        for fragment in fragments
        if fragment.strip()
        and fragment.strip().lower() not in normalized_excluded
        and not re.search(r"\b(?:barrel|scope|magazine|stock)\b", fragment.strip().lower())
        and not re.search(r"\b(?:tier|common|uncommon|rare|epic|legendary)\b", fragment.strip().lower())
        and not re.fullmatch(r"\d+", fragment.strip())
    ]
    if not candidates:
        return ""
    candidates = sorted(candidates, key=lambda value: (_name_score(value), len(value.split()), len(value)))
    return candidates[0]


def _contains_mod_slot(value: str) -> bool:
    return bool(re.search(r"\b(?:barrel|scope|magazine|stock)\b", value.strip().lower()))


def _name_score(value: str) -> int:
    score = 0
    if re.search(r"\b(?:I|II|III|IV|V|VI|VII|VIII|IX|X)\b", value):
        score += 4
    if _contains_mod_slot(value):
        score += 3
    score += min(3, len(value.split()))
    return score


def _infer_rarity_label(fragments: tuple[str, ...]) -> str:
    for fragment in fragments:
        normalized = fragment.strip().lower()
        if normalized in {"common", "uncommon", "rare", "epic", "legendary"}:
            return fragment.strip()
    return ""
