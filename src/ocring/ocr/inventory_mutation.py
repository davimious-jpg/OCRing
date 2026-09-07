from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any


class MutationType(str, Enum):
    ADD = "ADD"
    REMOVE = "REMOVE"
    QUANTITY_CHANGE = "QUANTITY_CHANGE"
    RECLASSIFY = "RECLASSIFY"
    CORRECT = "CORRECT"
    MERGE_DUPLICATE = "MERGE_DUPLICATE"
    SPLIT_RECORD = "SPLIT_RECORD"
    NO_CHANGE = "NO_CHANGE"


@dataclass(frozen=True)
class InventoryMutation:
    mutation_type: MutationType
    session_id: str
    record_id: str
    old_state: dict[str, Any]
    new_state: dict[str, Any]
    reason: str
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"))


def create_mutation(
    mutation_type: MutationType,
    *,
    session_id: str,
    record_id: str,
    old_state: dict[str, Any],
    new_state: dict[str, Any],
    reason: str,
) -> InventoryMutation:
    return InventoryMutation(
        mutation_type=mutation_type,
        session_id=session_id,
        record_id=record_id,
        old_state=dict(old_state),
        new_state=dict(new_state),
        reason=reason,
    )
