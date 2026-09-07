from __future__ import annotations

from dataclasses import dataclass

from .models import CropEvidence, EvidenceKind


@dataclass(frozen=True)
class TrimConfig:
    ram_trim_threshold: float = 0.80
    cpu_trim_threshold: float = 0.90
    queue_depth_trim_threshold: int = 24
    buffer_occupancy_trim_threshold: float = 0.85
    aggressive_ram_threshold: float = 0.95
    aggressive_cpu_threshold: float = 0.98
    critical_queue_depth_threshold: int = 64
    critical_buffer_occupancy_threshold: float = 0.97


class TrimPolicy:
    def __init__(
        self,
        *,
        ram_pressure: float,
        cpu_pressure: float,
        queue_depth: int,
        buffer_occupancy: float,
        config: TrimConfig | None = None,
    ) -> None:
        self.ram_pressure = ram_pressure
        self.cpu_pressure = cpu_pressure
        self.queue_depth = queue_depth
        self.buffer_occupancy = buffer_occupancy
        self.config = config or TrimConfig()

    def should_trim(self) -> bool:
        return any(
            (
                self.ram_pressure >= self.config.ram_trim_threshold,
                self.cpu_pressure >= self.config.cpu_trim_threshold,
                self.queue_depth >= self.config.queue_depth_trim_threshold,
                self.buffer_occupancy >= self.config.buffer_occupancy_trim_threshold,
            )
        )

    def pressure_level(self) -> str:
        if any(
            (
                self.ram_pressure >= self.config.aggressive_ram_threshold,
                self.cpu_pressure >= self.config.aggressive_cpu_threshold,
                self.queue_depth >= self.config.critical_queue_depth_threshold,
                self.buffer_occupancy >= self.config.critical_buffer_occupancy_threshold,
            )
        ):
            return "critical"
        if self.should_trim():
            return "elevated"
        return "normal"

    def get_trim_targets(
        self,
        evidence_list: tuple[CropEvidence, ...] | list[CropEvidence],
        pressure_level: str,
    ) -> tuple[CropEvidence, ...]:
        evidence = list(evidence_list)
        trim_candidates = [item for item in evidence if self._priority(item) < 4]
        trim_candidates.sort(
            key=lambda item: (
                self._priority(item),
                item.quality_score,
                self._estimated_bytes(item),
            )
        )
        if not trim_candidates:
            return ()
        ratio = {"elevated": 0.25, "critical": 0.50}.get(pressure_level, 0.0)
        trim_count = max(1, int(len(trim_candidates) * ratio))
        return tuple(trim_candidates[:trim_count])

    def _priority(self, evidence: CropEvidence) -> int:
        metadata = evidence.metadata
        if metadata.get("user_pinned_debug"):
            return 4
        if evidence.evidence_kind in {EvidenceKind.ANCHOR, EvidenceKind.CONTRADICTION}:
            return 4
        if metadata.get("unresolved_record_only"):
            return 4
        if metadata.get("active_dependency"):
            return 4
        if metadata.get("duplicate_frame") or metadata.get("resolved_support") or evidence.quality_score < 0.20:
            return 1
        if metadata.get("partial_frame"):
            return 2
        if not metadata.get("active_dependency", False):
            return 3
        return 4

    def _estimated_bytes(self, evidence: CropEvidence) -> int:
        value = evidence.metadata.get("estimated_bytes")
        if value is not None:
            return int(value)
        return int(evidence.region.area * 3)

    def trim_to_compact_provenance(
        self,
        evidence_list: tuple[CropEvidence, ...] | list[CropEvidence],
    ) -> tuple[CropEvidence, ...]:
        compacted: list[CropEvidence] = []
        for evidence in evidence_list:
            metadata = dict(evidence.metadata)
            if metadata.get("resolved_support") or metadata.get("compact_provenance_requested"):
                metadata.pop("pixel_data", None)
                metadata["compact_provenance"] = True
                metadata["estimated_bytes"] = min(
                    int(metadata.get("estimated_bytes", self._estimated_bytes(evidence))),
                    256,
                )
                compacted.append(
                    CropEvidence(
                        crop_id=evidence.crop_id,
                        frame_id=evidence.frame_id,
                        row_id=evidence.row_id,
                        field_kind=evidence.field_kind,
                        region=evidence.region,
                        evidence_kind=evidence.evidence_kind,
                        quality_score=evidence.quality_score,
                        metadata=metadata,
                    )
                )
            else:
                compacted.append(evidence)
        return tuple(compacted)
