from __future__ import annotations

from collections import Counter

from .semantic_allocator import CandidateInventoryRecord


class OrganizationPass:
    def summarize(self, records: tuple[CandidateInventoryRecord, ...] | list[CandidateInventoryRecord]) -> dict[str, object]:
        counts = Counter()
        unresolved: list[dict[str, object]] = []
        for record in records:
            if record.status == "NEEDS_REVIEW" or record.record_class == "UNKNOWN":
                counts["Needs Review"] += 1
                unresolved.append(record.as_dict())
                continue
            counts[f"{record.record_class}s"] += 1
        return {
            "category_counts": dict(counts),
            "unresolved_count": len(unresolved),
            "unresolved_items": unresolved,
        }
