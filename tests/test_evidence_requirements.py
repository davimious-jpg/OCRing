from __future__ import annotations

from ocring.ocr.evidence_requirements import required_evidence_summary, satisfies_evidence_requirement


def test_item_name_requires_visible_text() -> None:
    assert satisfies_evidence_requirement("item_name", {"visible_text": "Power Bore"}) is True
    assert satisfies_evidence_requirement("item_name", {"visible_text": ""}) is False


def test_rarity_accepts_visible_text_or_tier_plus_color() -> None:
    assert satisfies_evidence_requirement("item_rarity", {"visible_text": "Tier IV"}) is True
    assert satisfies_evidence_requirement("item_rarity", {"tier": "Tier IV", "color": "Purple"}) is True
    assert satisfies_evidence_requirement("item_rarity", {"tier": "Tier IV"}) is False


def test_quantity_accepts_visible_numeric_or_explicit_default() -> None:
    assert satisfies_evidence_requirement("item_count", {"visible_numeric": "2"}) is True
    assert satisfies_evidence_requirement("item_count", {"explicit_default": True}) is True
    assert "explicit_default" in required_evidence_summary("item_count")

