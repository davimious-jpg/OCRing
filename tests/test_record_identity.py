from __future__ import annotations

from ocring.ocr.record_identity import build_record_identity


def test_record_identity_builds_cross_scan_fingerprint() -> None:
    identity = build_record_identity(
        canonical_item_id="defiance.weapon.power_bore",
        observation_ids=("scan1:row1", "scan2:row4"),
        name="Power Bore",
        rarity="Tier IV",
        synergy="Epidemic",
        item_type="Rocket Launcher",
        mods=("Scope", "Magazine"),
        stats=("Damage+10",),
    )

    assert identity.canonical_item_id == "defiance.weapon.power_bore"
    assert len(identity.instance_fingerprint) == 40
    assert identity.scan_observation_ids == ("scan1:row1", "scan2:row4")

