from __future__ import annotations

from ocring.ocr.semantic_allocator import SemanticAllocator


def test_semantic_allocator_classifies_weapon_using_profile_constrained_values() -> None:
    allocator = SemanticAllocator()
    contract = {
        "field_definitions": (
            {"canonical_id": "item_name"},
            {"canonical_id": "item_rarity"},
            {"canonical_id": "item_type"},
            {"canonical_id": "item_count"},
        ),
        "allowed_rarities": ("Tier IV", "Tier III"),
        "allowed_types": ("Rocket Launcher", "SMG"),
        "allowed_record_classes": ("Weapon", "Shield"),
        "allowed_synergies": (),
    }

    record = allocator.allocate(("Power Bore IV", "Tier IV", "Rocket Launcher", "2"), contract)

    assert record.record_class == "Weapon"
    assert record.status == "READY"
    assert record.field_values["item_name"] == "Power Bore IV"
    assert record.field_values["item_rarity"] == "Tier IV"
    assert record.field_values["item_type"] == "Rocket Launcher"
    assert record.provenance["allocated_by"] == "semantic_allocator"


def test_semantic_allocator_marks_unknown_as_needs_review() -> None:
    allocator = SemanticAllocator()
    contract = {
        "field_definitions": (),
        "allowed_rarities": ("Tier IV",),
        "allowed_types": ("Rocket Launcher",),
        "allowed_record_classes": ("Weapon",),
        "allowed_synergies": (),
    }

    record = allocator.allocate(("Mystery", "Artifact"), contract)

    assert record.record_class == "UNKNOWN"
    assert record.status == "NEEDS_REVIEW"


def test_semantic_allocator_builds_structured_weapon_mod_from_field_zone_fragments() -> None:
    allocator = SemanticAllocator()
    contract = {
        "field_definitions": (
            {"canonical_id": "item_name"},
            {"canonical_id": "item_rarity"},
            {"canonical_id": "item_synergy"},
            {"canonical_id": "item_count"},
        ),
        "allowed_rarities": ("Tier IV", "Tier III"),
        "allowed_types": (),
        "allowed_record_classes": ("Weapon", "WeaponMod"),
        "allowed_synergies": ("Ether Acceleration",),
        "allowed_mod_slots": ("Barrel", "Scope", "Magazine", "Stock"),
    }

    record = allocator.allocate(
        ("Critical Force Barrel IV", "Epic", "Ether Acceleration", "1"),
        contract,
    )

    assert record.record_class == "WeaponMod"
    assert record.status == "READY"
    assert record.field_values["item_name"] == "Critical Force Barrel IV"
    assert record.field_values["item_rarity"] == "Epic"
    assert record.field_values["item_synergy"] == "Ether Acceleration"
    assert record.field_values["item_count"] == "1"
    assert record.field_values["mod_slot"] == "Barrel"


def test_semantic_allocator_leaves_synergy_unknown_without_allowed_reference_values() -> None:
    allocator = SemanticAllocator()
    contract = {
        "field_definitions": (
            {"canonical_id": "item_name"},
            {"canonical_id": "item_rarity"},
            {"canonical_id": "item_type"},
            {"canonical_id": "item_count"},
            {"canonical_id": "item_synergy"},
        ),
        "allowed_rarities": ("Tier IV",),
        "allowed_types": ("Rocket Launcher",),
        "allowed_record_classes": ("Weapon",),
        "allowed_synergies": (),
    }

    record = allocator.allocate(("Power Bore", "Tier IV", "Rocket Launcher", "2"), contract)

    assert "item_synergy" not in record.field_values


def test_semantic_allocator_does_not_infer_grenade_type_from_contaminated_name_text() -> None:
    allocator = SemanticAllocator()
    contract = {
        "field_definitions": ({"canonical_id": "item_name"}, {"canonical_id": "item_type"}),
        "allowed_rarities": (),
        "allowed_types": ("Grenade", "Shield"),
        "allowed_record_classes": ("Weapon", "Shield", "Grenade"),
        "allowed_synergies": (),
    }

    record = allocator.allocate(("SHELDGRENADES SPIKESSTIMS",), contract)

    assert record.record_class == "UNKNOWN"
    assert record.status == "NEEDS_REVIEW"
    assert record.field_values == {"item_name": "SHELDGRENADES SPIKESSTIMS"}
