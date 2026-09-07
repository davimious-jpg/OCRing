from __future__ import annotations

import json
import shutil
from collections import OrderedDict
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

from .models import CropEvidence, EvidenceKind
from .settings import DEFAULT_SETTINGS_PATH, ensure_output_workspace
from .trim_policy import TrimConfig, TrimPolicy


class FrameBufferState(str, Enum):
    RAW = "RAW"
    READABLE = "READABLE"
    ANCHOR = "ANCHOR"
    SELECTED = "SELECTED"
    PROCESSING = "PROCESSING"
    EXTRACTED = "EXTRACTED"
    REDUNDANT = "REDUNDANT"
    DISCARDABLE = "DISCARDABLE"
    RELEASEABLE = "RELEASEABLE"
    PINNED = "PINNED"
    CLAIMED_BY_OCR = "CLAIMED_BY_OCR"
    CLAIMED_BY_AI = "CLAIMED_BY_AI"


@dataclass
class RawFrameEntry:
    frame_id: str
    payload: dict[str, Any]
    estimated_bytes: int
    state: FrameBufferState = FrameBufferState.RAW
    pinned: bool = False
    ref_count: int = 0
    claim_counts: dict[str, int] = field(default_factory=lambda: {"ocr": 0, "ai": 0, "pin": 0})


class ShortRawBuffer:
    def __init__(self, max_items: int = 16, *, memory_budget_ratio: float = 0.20) -> None:
        self.max_items = max_items
        self.memory_budget_ratio = memory_budget_ratio
        self._items: "OrderedDict[str, RawFrameEntry]" = OrderedDict()

    def retain(
        self,
        frame_id: str,
        payload: dict[str, Any],
        *,
        estimated_bytes: int,
        state: FrameBufferState = FrameBufferState.RAW,
    ) -> None:
        self._items[frame_id] = RawFrameEntry(
            frame_id=frame_id,
            payload=dict(payload),
            estimated_bytes=estimated_bytes,
            state=state,
        )
        self._items.move_to_end(frame_id)
        self._evict_unpinned()

    def pin(self, frame_id: str) -> None:
        entry = self._items.get(frame_id)
        if entry is not None:
            entry.pinned = True
            entry.claim_counts["pin"] += 1
            entry.ref_count += 1
            entry.state = FrameBufferState.PINNED

    def unpin(self, frame_id: str) -> None:
        entry = self._items.get(frame_id)
        if entry is not None:
            entry.pinned = False
            if entry.claim_counts["pin"] > 0:
                entry.claim_counts["pin"] -= 1
                entry.ref_count = max(0, entry.ref_count - 1)
            self._set_releaseable_if_clear(entry)

    def claim_by_ocr(self, frame_id: str) -> None:
        self._claim(frame_id, owner="ocr", state=FrameBufferState.CLAIMED_BY_OCR)

    def claim_by_ai(self, frame_id: str) -> None:
        self._claim(frame_id, owner="ai", state=FrameBufferState.CLAIMED_BY_AI)

    def release_ocr_claim(self, frame_id: str) -> None:
        self._release_claim(frame_id, owner="ocr")

    def release_ai_claim(self, frame_id: str) -> None:
        self._release_claim(frame_id, owner="ai")

    def transition(self, frame_id: str, state: FrameBufferState) -> None:
        entry = self._items.get(frame_id)
        if entry is not None:
            if state is FrameBufferState.RELEASEABLE and entry.ref_count > 0:
                return
            entry.state = state

    def release_all_except(self, frame_ids: tuple[str, ...] | list[str] | set[str]) -> tuple[str, ...]:
        keep = set(frame_ids)
        removed: list[str] = []
        for frame_id in list(self._items.keys()):
            entry = self._items[frame_id]
            if entry.pinned or entry.ref_count > 0 or frame_id in keep:
                continue
            removed.append(frame_id)
            del self._items[frame_id]
        return tuple(removed)

    def total_bytes(self) -> int:
        return sum(item.estimated_bytes for item in self._items.values())

    def diagnostics(self) -> dict[str, Any]:
        return {
            "buffer_kind": "short_raw",
            "memory_budget_ratio": self.memory_budget_ratio,
            "item_count": len(self._items),
            "total_bytes": self.total_bytes(),
            "states": {frame_id: entry.state.value for frame_id, entry in self._items.items()},
            "ref_counts": {frame_id: entry.ref_count for frame_id, entry in self._items.items()},
        }

    def _evict_unpinned(self) -> None:
        while len(self._items) > self.max_items:
            oldest_id = next(iter(self._items))
            if self._items[oldest_id].pinned or self._items[oldest_id].ref_count > 0:
                break
            self._items.popitem(last=False)

    def _claim(self, frame_id: str, *, owner: str, state: FrameBufferState) -> None:
        entry = self._items.get(frame_id)
        if entry is None:
            return
        entry.claim_counts[owner] += 1
        entry.ref_count += 1
        entry.state = state

    def _release_claim(self, frame_id: str, *, owner: str) -> None:
        entry = self._items.get(frame_id)
        if entry is None:
            return
        if entry.claim_counts[owner] > 0:
            entry.claim_counts[owner] -= 1
            entry.ref_count = max(0, entry.ref_count - 1)
        self._set_releaseable_if_clear(entry)

    def _set_releaseable_if_clear(self, entry: RawFrameEntry) -> None:
        if entry.ref_count == 0 and not entry.pinned:
            entry.state = FrameBufferState.RELEASEABLE


class EvidenceBuffer:
    def __init__(
        self,
        max_items: int = 64,
        *,
        trim_config: TrimConfig | None = None,
        memory_budget_ratio: float = 0.55,
        debug_output_dir: Path | None = None,
        settings_path: Path = DEFAULT_SETTINGS_PATH,
    ) -> None:
        self.max_items = max_items
        self.memory_budget_ratio = memory_budget_ratio
        self.trim_config = trim_config or TrimConfig()
        self.debug_output_dir = debug_output_dir or ensure_output_workspace(path=settings_path).evidence_dir
        self._items: "OrderedDict[str, CropEvidence]" = OrderedDict()
        self._states: dict[str, FrameBufferState] = {}
        self._pins: set[str] = set()
        self._ref_counts: dict[str, int] = {}
        self._claim_counts: dict[str, dict[str, int]] = {}
        self.trim_count = 0
        self.total_trimmed_bytes = 0
        self.last_trim_reason = ""
        self._trim_events: list[dict[str, Any]] = []

    def retain(self, evidence: CropEvidence) -> None:
        self._items[evidence.crop_id] = evidence
        self._states.setdefault(evidence.crop_id, FrameBufferState.RAW)
        self._ref_counts.setdefault(evidence.crop_id, 0)
        self._claim_counts.setdefault(evidence.crop_id, {"ocr": 0, "ai": 0, "pin": 0})
        self._items.move_to_end(evidence.crop_id)
        self._persist_debug_evidence(evidence)
        while len(self._items) > self.max_items:
            oldest_id = next(iter(self._items))
            if oldest_id in self._pins or self._ref_counts.get(oldest_id, 0) > 0:
                break
            self._items.popitem(last=False)
            self._states.pop(oldest_id, None)
            self._ref_counts.pop(oldest_id, None)
            self._claim_counts.pop(oldest_id, None)

    def items(self) -> tuple[CropEvidence, ...]:
        return tuple(self._items.values())

    def pin(self, crop_id: str) -> None:
        if crop_id in self._items:
            self._pins.add(crop_id)
            self._claim_counts[crop_id]["pin"] += 1
            self._ref_counts[crop_id] = self._ref_counts.get(crop_id, 0) + 1
            self._states[crop_id] = FrameBufferState.PINNED

    def unpin(self, crop_id: str) -> None:
        self._pins.discard(crop_id)
        if crop_id in self._states:
            if self._claim_counts.get(crop_id, {}).get("pin", 0) > 0:
                self._claim_counts[crop_id]["pin"] -= 1
                self._ref_counts[crop_id] = max(0, self._ref_counts.get(crop_id, 0) - 1)
            self._set_releaseable_if_clear(crop_id)

    def claim_by_ocr(self, crop_id: str) -> None:
        self._claim(crop_id, owner="ocr", state=FrameBufferState.CLAIMED_BY_OCR)

    def claim_by_ai(self, crop_id: str) -> None:
        self._claim(crop_id, owner="ai", state=FrameBufferState.CLAIMED_BY_AI)

    def release_ocr_claim(self, crop_id: str) -> None:
        self._release_claim(crop_id, owner="ocr")

    def release_ai_claim(self, crop_id: str) -> None:
        self._release_claim(crop_id, owner="ai")

    def transition(self, crop_id: str, state: FrameBufferState) -> None:
        if crop_id in self._items:
            if state is FrameBufferState.RELEASEABLE and self._ref_counts.get(crop_id, 0) > 0:
                return
            self._states[crop_id] = state

    def diagnostics(self) -> dict[str, Any]:
        return {
            "buffer_kind": "evidence",
            "memory_budget_ratio": self.memory_budget_ratio,
            "item_count": len(self._items),
            "total_bytes": self.total_bytes(),
            "trim_count": self.trim_count,
            "total_trimmed_bytes": self.total_trimmed_bytes,
            "last_trim_reason": self.last_trim_reason,
            "trim_events": list(self._trim_events),
            "states": {crop_id: state.value for crop_id, state in self._states.items() if crop_id in self._items},
            "ref_counts": {crop_id: self._ref_counts.get(crop_id, 0) for crop_id in self._items},
        }

    def trim_evidence(self, current_pressure: dict[str, float | int]) -> tuple[CropEvidence, ...]:
        if not self._items:
            return ()
        policy = TrimPolicy(
            ram_pressure=float(current_pressure.get("ram_pressure", 0.0)),
            cpu_pressure=float(current_pressure.get("cpu_pressure", 0.0)),
            queue_depth=int(current_pressure.get("queue_depth", 0)),
            buffer_occupancy=float(current_pressure.get("buffer_occupancy", self._buffer_occupancy())),
            config=self.trim_config,
        )
        if not policy.should_trim():
            return ()
        pressure_level = policy.pressure_level()
        targets = policy.get_trim_targets(self.items(), pressure_level)
        if not targets:
            self.last_trim_reason = f"TRIM_SKIPPED:{pressure_level}"
            return ()

        freed_bytes = 0
        removed: list[CropEvidence] = []
        for evidence in targets:
            current = self._items.get(evidence.crop_id)
            if current is None:
                continue
            if evidence.crop_id in self._pins:
                continue
            if self._ref_counts.get(evidence.crop_id, 0) > 0:
                continue
            if current.metadata.get("active_dependency"):
                continue
            removed.append(current)
            freed_bytes += self._estimated_bytes(current)
            del self._items[evidence.crop_id]
            self._states.pop(evidence.crop_id, None)
            self._ref_counts.pop(evidence.crop_id, None)
            self._claim_counts.pop(evidence.crop_id, None)

        if removed:
            self.trim_count += 1
            self.total_trimmed_bytes += freed_bytes
            self.last_trim_reason = f"TRIM_EVENT:{pressure_level}"
            self._trim_events.append(
                {
                    "event": "TRIM_EVENT",
                    "count": len(removed),
                    "pressure_level": pressure_level,
                    "freed_bytes": freed_bytes,
                }
            )
        return tuple(removed)

    def trim_to_compact_provenance(self) -> tuple[CropEvidence, ...]:
        compacted = TrimPolicy(
            ram_pressure=0.0,
            cpu_pressure=0.0,
            queue_depth=0,
            buffer_occupancy=self._buffer_occupancy(),
            config=self.trim_config,
        ).trim_to_compact_provenance(self.items())
        for evidence in compacted:
            self._items[evidence.crop_id] = evidence
            self._states[evidence.crop_id] = FrameBufferState.EXTRACTED
        if compacted:
            self.last_trim_reason = "TRIM_EVENT:compact_provenance"
        return compacted

    def total_bytes(self) -> int:
        return sum(self._estimated_bytes(item) for item in self._items.values())

    def _estimated_bytes(self, evidence: CropEvidence) -> int:
        value = evidence.metadata.get("estimated_bytes")
        if value is not None:
            return int(value)
        return int(evidence.region.area * 3)

    def _buffer_occupancy(self) -> float:
        if self.max_items <= 0:
            return 1.0
        return min(1.0, len(self._items) / self.max_items)

    def _claim(self, crop_id: str, *, owner: str, state: FrameBufferState) -> None:
        if crop_id not in self._items:
            return
        claims = self._claim_counts.setdefault(crop_id, {"ocr": 0, "ai": 0, "pin": 0})
        claims[owner] += 1
        self._ref_counts[crop_id] = self._ref_counts.get(crop_id, 0) + 1
        self._states[crop_id] = state

    def _release_claim(self, crop_id: str, *, owner: str) -> None:
        if crop_id not in self._items:
            return
        claims = self._claim_counts.setdefault(crop_id, {"ocr": 0, "ai": 0, "pin": 0})
        if claims[owner] > 0:
            claims[owner] -= 1
            self._ref_counts[crop_id] = max(0, self._ref_counts.get(crop_id, 0) - 1)
        self._set_releaseable_if_clear(crop_id)

    def _set_releaseable_if_clear(self, crop_id: str) -> None:
        if crop_id not in self._items:
            return
        if self._ref_counts.get(crop_id, 0) == 0 and crop_id not in self._pins:
            self._states[crop_id] = FrameBufferState.RELEASEABLE

    def _persist_debug_evidence(self, evidence: CropEvidence) -> None:
        if evidence.evidence_kind is not EvidenceKind.DEBUG and not evidence.metadata.get("debug_capture_opt_in"):
            return

        self.debug_output_dir.mkdir(parents=True, exist_ok=True)
        source_path = evidence.metadata.get("image_path") or evidence.metadata.get("source_path")
        if source_path:
            candidate = Path(str(source_path))
            if candidate.exists() and candidate.is_file():
                destination = self.debug_output_dir / f"{evidence.crop_id}{candidate.suffix or '.bin'}"
                if candidate.resolve() != destination.resolve():
                    shutil.copy2(candidate, destination)

        manifest_path = self.debug_output_dir / f"{evidence.crop_id}.json"
        manifest_path.write_text(
            json.dumps(
                {
                    "crop_id": evidence.crop_id,
                    "frame_id": evidence.frame_id,
                    "row_id": evidence.row_id,
                    "field_kind": evidence.field_kind.value,
                    "evidence_kind": evidence.evidence_kind.value,
                    "quality_score": evidence.quality_score,
                    "region": evidence.region.as_dict(),
                    "metadata": evidence.metadata,
                },
                indent=2,
                sort_keys=True,
            ),
            encoding="utf-8",
        )
