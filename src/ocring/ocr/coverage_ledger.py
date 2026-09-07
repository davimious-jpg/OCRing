from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class CoverageState(str, Enum):
    CONTINUOUS = "CONTINUOUS"
    UNCERTAIN = "UNCERTAIN"
    GAP = "GAP"


@dataclass(frozen=True)
class CoverageObservation:
    frame_id: str
    sequence_id: int
    timestamp: float
    row_signatures: dict[int, str]


@dataclass(frozen=True)
class CoverageTransition:
    frame_a_id: str
    frame_b_id: str
    sequence_a: int
    sequence_b: int
    state: CoverageState
    overlap_count: int
    row_count_a: int
    row_count_b: int
    reason: str

    def as_dict(self) -> dict[str, object]:
        return {
            "frame_a_id": self.frame_a_id,
            "frame_b_id": self.frame_b_id,
            "sequence_a": self.sequence_a,
            "sequence_b": self.sequence_b,
            "state": self.state.value,
            "overlap_count": self.overlap_count,
            "row_count_a": self.row_count_a,
            "row_count_b": self.row_count_b,
            "reason": self.reason,
        }


@dataclass
class EvidenceCoverageLedger:
    min_overlap_rows: int = 1
    observations: list[CoverageObservation] = field(default_factory=list)
    transitions: list[CoverageTransition] = field(default_factory=list)

    def observe(self, observation: CoverageObservation) -> CoverageTransition | None:
        previous = self.observations[-1] if self.observations else None
        self.observations.append(observation)
        if previous is None:
            return None
        transition = self._compare(previous, observation)
        self.transitions.append(transition)
        return transition

    def _compare(self, previous: CoverageObservation, current: CoverageObservation) -> CoverageTransition:
        previous_values = {value for value in previous.row_signatures.values() if value}
        current_values = {value for value in current.row_signatures.values() if value}
        overlap_count = len(previous_values & current_values)
        if not previous_values or not current_values:
            state = CoverageState.UNCERTAIN
            reason = "MISSING_ROW_SIGNATURES"
        elif overlap_count >= self.min_overlap_rows:
            state = CoverageState.CONTINUOUS
            reason = "ROW_SIGNATURE_OVERLAP"
        else:
            state = CoverageState.GAP
            reason = "NO_ROW_SIGNATURE_OVERLAP"
        return CoverageTransition(
            frame_a_id=previous.frame_id,
            frame_b_id=current.frame_id,
            sequence_a=previous.sequence_id,
            sequence_b=current.sequence_id,
            state=state,
            overlap_count=overlap_count,
            row_count_a=len(previous.row_signatures),
            row_count_b=len(current.row_signatures),
            reason=reason,
        )

    def as_dict(self) -> dict[str, object]:
        counts = {
            CoverageState.CONTINUOUS.value: 0,
            CoverageState.UNCERTAIN.value: 0,
            CoverageState.GAP.value: 0,
        }
        for transition in self.transitions:
            counts[transition.state.value] += 1
        return {
            "observation_count": len(self.observations),
            "transition_count": len(self.transitions),
            "state_counts": counts,
            "coverage_state": self.coverage_state().value,
            "gaps": [transition.as_dict() for transition in self.transitions if transition.state is CoverageState.GAP],
            "transitions": [transition.as_dict() for transition in self.transitions],
        }

    def coverage_state(self) -> CoverageState:
        if any(transition.state is CoverageState.GAP for transition in self.transitions):
            return CoverageState.GAP
        if any(transition.state is CoverageState.UNCERTAIN for transition in self.transitions):
            return CoverageState.UNCERTAIN
        if self.transitions:
            return CoverageState.CONTINUOUS
        return CoverageState.UNCERTAIN
