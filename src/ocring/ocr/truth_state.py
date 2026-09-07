from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class TruthState(str, Enum):
    OBSERVED = "observed"
    RECOGNIZED = "recognized"
    MATCHED = "matched"
    RECONCILED = "reconciled"
    USER_VERIFIED = "user_verified"
    ACCEPTED = "accepted"


_TRUTH_ORDER = (
    TruthState.OBSERVED,
    TruthState.RECOGNIZED,
    TruthState.MATCHED,
    TruthState.RECONCILED,
    TruthState.USER_VERIFIED,
    TruthState.ACCEPTED,
)


@dataclass
class TruthProgression:
    current_state: TruthState = TruthState.OBSERVED
    progression_reasons: list[str] = field(default_factory=list)

    def advance_to(self, next_state: TruthState, reason: str) -> TruthState:
        current_index = _TRUTH_ORDER.index(self.current_state)
        next_index = _TRUTH_ORDER.index(next_state)
        if next_index < current_index:
            raise ValueError("Truth state cannot regress.")
        if next_index > current_index + 1:
            raise ValueError("Truth state cannot skip progression order.")
        self.current_state = next_state
        self.progression_reasons.append(reason)
        return self.current_state

    @property
    def latest_reason(self) -> str:
        if not self.progression_reasons:
            return ""
        return self.progression_reasons[-1]

    def as_dict(self) -> dict[str, object]:
        return {
            "truth_state": self.current_state.value,
            "progression_reason": self.latest_reason,
            "progression_chain": list(self.progression_reasons),
        }
