from __future__ import annotations

from ocring.ocr.inventory_definition_engine import InventoryDefinitionEngine
from ocring.ocr.parser import ProfileDrivenParser
from ocring.ocr.profile import Profile
from ocring.ocr.semantic_allocator import SemanticAllocator


def _profile() -> Profile:
    return Profile(
        profile_id="defiance",
        profile_name="Defiance",
        version="1",
        inventory_definitions=[
            {"canonical_id": "item_name", "label": "Item Name", "required": True, "extraction_source": "ocr.item_name"},
            {"canonical_id": "item_rarity", "label": "Item Rarity", "required": True, "extraction_source": "ocr.item_rarity"},
            {"canonical_id": "item_type", "label": "Item Type", "required": True, "extraction_source": "ocr.item_type"},
            {"canonical_id": "item_count", "label": "Item Count", "required": False, "extraction_source": "ocr.item_count"},
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
                        "allowed_values": ["Tier IV", "Tier V"],
                        "aliases": {"epic": "Tier IV"},
                    },
                    {
                        "field_name": "item_type",
                        "required": True,
                        "sources": ["visible_text", "dictionary_match"],
                        "allowed_values": ["Rocket Launcher", "SMG"],
                    },
                    {
                        "field_name": "item_count",
                        "required": False,
                        "sources": ["visible_text", "regex"],
                        "patterns": ["x{number}", "{number}x", "Quantity: {number}", "Qty: {number}"],
                        "default": "1",
                        "default_status": "DEFAULTED",
                    },
                ],
            }
        ],
        field_aliases={"item_rarity": {"epic": "Tier IV"}},
        field_patterns={"item_count": ["x{number}", "{number}x", "Quantity: {number}", "Qty: {number}"]},
        rarity_rules=[
            {"tier": "Tier IV", "color": "#9c27b0", "name": "Epic"},
            {"tier": "Tier V", "color": "#ff9800", "name": "Legendary"},
        ],
    )


def test_inventory_definition_engine_loads_definitions_and_aliases() -> None:
    engine = InventoryDefinitionEngine(_profile())

    definition = engine.get_definition("Weapon")
    rarity_field = engine.get_field_definition("item_rarity")

    assert definition.record_class == "Weapon"
    assert rarity_field.allowed_values == ("Tier IV", "Tier V")
    assert engine.apply_alias("item_rarity", "epic") == "Tier IV"
    assert engine.get_required_fields("Weapon") == ["item_name", "item_rarity", "item_type"]


def test_inventory_definition_engine_patterns_and_defaults() -> None:
    engine = InventoryDefinitionEngine(_profile())

    assert engine.apply_patterns("item_count", "Qty: 4") == "4"
    assert engine.default_for("item_count") == ("1", "DEFAULTED")


def test_parser_applies_aliases_and_defaulted_status() -> None:
    parser = ProfileDrivenParser(_profile())

    parsed = parser.parse_record(
        {
            "item_name": "Power Bore",
            "item_rarity": "epic",
            "item_type": "Rocket Launcher",
        }
    )

    assert parsed.record_class == "Weapon"
    assert parsed.definition_used == "Weapon"
    assert parsed.fields["item_rarity"].value == "Tier IV"
    assert parsed.fields["item_count"].value == "1"
    assert parsed.fields["item_count"].status == "DEFAULTED"


def test_semantic_allocator_builds_prompt_from_definition_engine() -> None:
    allocator = SemanticAllocator.from_profile(_profile())

    prompt = allocator.build_prompt(
        record_class="Weapon",
        contract={
            "field_definitions": (
                {"field_name": "item_name"},
                {"field_name": "item_rarity"},
                {"field_name": "item_type"},
            ),
            "allowed_types": ("Rocket Launcher", "SMG"),
        },
    )

    assert "Required output fields:" in prompt
    assert "- item_name" in prompt
    assert "Allowed weapon types:" in prompt
    assert "Rocket Launcher, SMG" in prompt
