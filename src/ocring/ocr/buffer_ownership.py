from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class OwnershipState(str, Enum):
    CAPTURED = "CAPTURED"
    BUFFERED = "BUFFERED"
    CLAIMED_BY_OCR = "CLAIMED_BY_OCR"
    CLAIMED_BY_AI = "CLAIMED_BY_AI"
    RESOLVED = "RESOLVED"
    RELEASEABLE = "RELEASEABLE"


@dataclass
class BufferOwnership:
    frame_id: str
    state: OwnershipState = OwnershipState.CAPTURED
    reference_count: int = 1

    def transition(self, state: OwnershipState) -> OwnershipState:
        self.state = state
        return self.state

    def acquire(self) -> int:
        self.reference_count += 1
        return self.reference_count

    def release(self) -> int:
        self.reference_count = max(0, self.reference_count - 1)
        if self.reference_count == 0 and self.state in {
            OwnershipState.RESOLVED,
            OwnershipState.BUFFERED,
            OwnershipState.CAPTURED,
        }:
            self.state = OwnershipState.RELEASEABLE
        return self.reference_count

