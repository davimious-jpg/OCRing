from __future__ import annotations

from ocring.ocr.profile_capabilities import CapabilityLevel, ProfileCapabilities


def test_defiance_profile_capabilities_are_declared() -> None:
    capabilities = ProfileCapabilities.for_profile("defiance")

    assert capabilities.inventory_scan is CapabilityLevel.SUPPORTED
    assert capabilities.weapon_scan is CapabilityLevel.SUPPORTED
    assert capabilities.mod_scan is CapabilityLevel.SUPPORTED
    assert capabilities.rarity_color is CapabilityLevel.SUPPORTED
    assert capabilities.synergy is CapabilityLevel.SUPPORTED
    assert capabilities.instance_tracking is CapabilityLevel.PARTIAL
    assert capabilities.full_inventory_completeness is CapabilityLevel.EXPERIMENTAL

