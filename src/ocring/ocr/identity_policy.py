from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from uuid import uuid4


@dataclass(frozen=True)
class CanonicalItem:
    kind: str
    canonical_id: str
    display_name: str


@dataclass(frozen=True)
class InventoryInstance:
    canonical_item_id: str
    acquisition_timestamp: str
    instance_id: str = field(default_factory=lambda: str(uuid4()))


@dataclass(frozen=True)
class Stack:
    canonical_item_id: str
    count: int
    stack_id: str = field(default_factory=lambda: str(uuid4()))


class IdentityLevel(str, Enum):
    DISTINCT = "DISTINCT"
    CANONICAL_ITEM = "CANONICAL_ITEM"
    INVENTORY_INSTANCE = "INVENTORY_INSTANCE"
    STACK = "STACK"


@dataclass(frozen=True)
class IdentityResolution:
    level: IdentityLevel
    same_identity: bool
    reasons: tuple[str, ...]


def identity_resolver(observation_a: object, observation_b: object) -> IdentityResolution:
    canonical_a = _canonical_item_id(observation_a)
    canonical_b = _canonical_item_id(observation_b)
    if not canonical_a or not canonical_b or canonical_a != canonical_b:
        return IdentityResolution(IdentityLevel.DISTINCT, False, ("CANONICAL_ITEM_MISMATCH",))

    if isinstance(observation_a, InventoryInstance) and isinstance(observation_b, InventoryInstance):
        if observation_a.instance_id == observation_b.instance_id:
            return IdentityResolution(IdentityLevel.INVENTORY_INSTANCE, True, ("INSTANCE_ID_MATCH",))
        if observation_a.acquisition_timestamp == observation_b.acquisition_timestamp:
            return IdentityResolution(IdentityLevel.INVENTORY_INSTANCE, True, ("INSTANCE_ACQUISITION_MATCH",))
        return IdentityResolution(IdentityLevel.CANONICAL_ITEM, True, ("CANONICAL_ONLY",))

    if isinstance(observation_a, Stack) and isinstance(observation_b, Stack):
        if observation_a.count == observation_b.count:
            return IdentityResolution(IdentityLevel.STACK, True, ("STACK_COUNT_MATCH",))
        return IdentityResolution(IdentityLevel.CANONICAL_ITEM, True, ("STACK_COUNT_DIFFERENT",))

    return IdentityResolution(IdentityLevel.CANONICAL_ITEM, True, ("CANONICAL_ITEM_MATCH",))


def create_inventory_instance(canonical_item_id: str, *, acquisition_timestamp: str | None = None) -> InventoryInstance:
    timestamp = acquisition_timestamp or datetime.utcnow().isoformat(timespec="seconds") + "Z"
    return InventoryInstance(canonical_item_id=canonical_item_id, acquisition_timestamp=timestamp)


def create_stack(canonical_item_id: str, count: int) -> Stack:
    return Stack(canonical_item_id=canonical_item_id, count=max(0, int(count)))


def _canonical_item_id(observation: object) -> str:
    if isinstance(observation, CanonicalItem):
        return observation.canonical_id
    if isinstance(observation, InventoryInstance):
        return observation.canonical_item_id
    if isinstance(observation, Stack):
        return observation.canonical_item_id
    return ""

