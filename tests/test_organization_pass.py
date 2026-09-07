from __future__ import annotations

from ocring.ocr.organization_pass import OrganizationPass
from ocring.ocr.semantic_allocator import CandidateInventoryRecord


def test_organization_pass_groups_categories_and_unresolved_items() -> None:
    records = (
        CandidateInventoryRecord("Weapon", {"item_name": "Power Bore"}, "READY", 0.91, {"allocated_by": "semantic_allocator"}),
        CandidateInventoryRecord("WeaponMod", {"item_name": "Stability Mod"}, "READY", 0.88, {"allocated_by": "semantic_allocator"}),
        CandidateInventoryRecord("Shield", {"item_name": "Bulwark"}, "READY", 0.87, {"allocated_by": "semantic_allocator"}),
        CandidateInventoryRecord("UNKNOWN", {"item_name": "Mystery"}, "NEEDS_REVIEW", 0.42, {"allocated_by": "semantic_allocator"}),
    )

    summary = OrganizationPass().summarize(records)

    assert summary["category_counts"]["Weapons"] == 1
    assert summary["category_counts"]["WeaponMods"] == 1
    assert summary["category_counts"]["Shields"] == 1
    assert summary["category_counts"]["Needs Review"] == 1
    assert summary["unresolved_count"] == 1
