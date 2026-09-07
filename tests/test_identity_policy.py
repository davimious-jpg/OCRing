from __future__ import annotations

from ocring.ocr.identity_policy import (
    CanonicalItem,
    IdentityLevel,
    create_inventory_instance,
    create_stack,
    identity_resolver,
)


def test_identity_resolver_distinguishes_canonical_instance_and_stack() -> None:
    canonical = CanonicalItem("mod", "defiance.mod.power_bore", "Power Bore")
    same_canonical = CanonicalItem("mod", "defiance.mod.power_bore", "Power Bore")
    instance_a = create_inventory_instance(canonical.canonical_id, acquisition_timestamp="2026-08-16T00:00:00Z")
    instance_b = create_inventory_instance(canonical.canonical_id, acquisition_timestamp="2026-08-16T00:00:00Z")
    stack_a = create_stack(canonical.canonical_id, 3)
    stack_b = create_stack(canonical.canonical_id, 3)

    canonical_resolution = identity_resolver(canonical, same_canonical)
    instance_resolution = identity_resolver(instance_a, instance_b)
    stack_resolution = identity_resolver(stack_a, stack_b)

    assert canonical_resolution.level is IdentityLevel.CANONICAL_ITEM
    assert instance_resolution.level is IdentityLevel.INVENTORY_INSTANCE
    assert stack_resolution.level is IdentityLevel.STACK


def test_identity_resolver_marks_distinct_canonical_items() -> None:
    left = CanonicalItem("mod", "defiance.mod.power_bore", "Power Bore")
    right = CanonicalItem("mod", "defiance.mod.ionic_barrel", "Ionic Barrel")

    resolution = identity_resolver(left, right)

    assert resolution.same_identity is False
    assert resolution.level is IdentityLevel.DISTINCT

