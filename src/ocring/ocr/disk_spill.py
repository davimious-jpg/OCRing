from __future__ import annotations

import gzip
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


RAM_SPILL_THRESHOLD_BYTES = 3 * 1024 * 1024 * 1024


@dataclass(frozen=True)
class SpillResult:
    spilled_paths: tuple[Path, ...]
    spilled_count: int
    total_bytes: int


class DiskSpillCache:
    def __init__(self, cache_dir: Path) -> None:
        self.cache_dir = cache_dir
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def spill_if_needed(
        self,
        evidence_items: list[dict[str, Any]],
        *,
        ram_bytes: int,
    ) -> SpillResult:
        if ram_bytes < RAM_SPILL_THRESHOLD_BYTES:
            return SpillResult((), 0, 0)
        worthy = [item for item in evidence_items if _worth_preserving(item)]
        spilled: list[Path] = []
        total_bytes = 0
        for index, item in enumerate(worthy):
            path = self.cache_dir / f"spill-{index}.json.gz"
            payload = json.dumps(item, sort_keys=True).encode("utf-8")
            with gzip.open(path, "wb") as handle:
                handle.write(payload)
            spilled.append(path)
            total_bytes += path.stat().st_size
        return SpillResult(tuple(spilled), len(spilled), total_bytes)


def _worth_preserving(item: dict[str, Any]) -> bool:
    return bool(item.get("unresolved") or item.get("anchor") or item.get("contradiction"))

