from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class CapabilityLevel(str, Enum):
    SUPPORTED = "SUPPORTED"
    EXPERIMENTAL = "EXPERIMENTAL"
    PARTIAL = "PARTIAL"
    UNSUPPORTED = "UNSUPPORTED"


@dataclass(frozen=True)
class ProfileCapabilities:
    inventory_scan: CapabilityLevel
    weapon_scan: CapabilityLevel
    mod_scan: CapabilityLevel
    rarity_color: CapabilityLevel
    synergy: CapabilityLevel
    instance_tracking: CapabilityLevel
    full_inventory_completeness: CapabilityLevel

    @classmethod
    def for_profile(cls, profile_id: str) -> ProfileCapabilities:
        if str(profile_id).strip().lower() == "defiance":
            return cls(
                inventory_scan=CapabilityLevel.SUPPORTED,
                weapon_scan=CapabilityLevel.SUPPORTED,
                mod_scan=CapabilityLevel.SUPPORTED,
                rarity_color=CapabilityLevel.SUPPORTED,
                synergy=CapabilityLevel.SUPPORTED,
                instance_tracking=CapabilityLevel.PARTIAL,
                full_inventory_completeness=CapabilityLevel.EXPERIMENTAL,
            )
        return cls(
            inventory_scan=CapabilityLevel.PARTIAL,
            weapon_scan=CapabilityLevel.PARTIAL,
            mod_scan=CapabilityLevel.PARTIAL,
            rarity_color=CapabilityLevel.PARTIAL,
            synergy=CapabilityLevel.PARTIAL,
            instance_tracking=CapabilityLevel.UNSUPPORTED,
            full_inventory_completeness=CapabilityLevel.UNSUPPORTED,
        )

