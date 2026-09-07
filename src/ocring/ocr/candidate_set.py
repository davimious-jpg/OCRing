from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class CandidateOption:
    candidate_value: str
    candidate_score: float
    source_lineage: tuple[str, ...]
    reason: str
    metadata: dict[str, Any] = field(default_factory=dict)


class CandidateSet:
    def __init__(self, *, top_k: int = 3) -> None:
        self.top_k = max(1, top_k)
        self._items: list[CandidateOption] = []

    def add_candidate(
        self,
        *,
        candidate_value: str,
        candidate_score: float,
        source_lineage: tuple[str, ...],
        reason: str,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        option = CandidateOption(
            candidate_value=candidate_value,
            candidate_score=float(candidate_score),
            source_lineage=source_lineage,
            reason=reason,
            metadata=dict(metadata or {}),
        )
        self._items.append(option)
        self._items.sort(key=lambda item: (-item.candidate_score, item.candidate_value))
        self._items = self._items[: self.top_k]

    def collapse(self) -> CandidateOption | None:
        if not self._items:
            return None
        return self._items[0]

    def as_list(self) -> list[CandidateOption]:
        return list(self._items)
