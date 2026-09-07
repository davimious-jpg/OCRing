from __future__ import annotations

from collections import deque
from dataclasses import dataclass, replace
from datetime import datetime, timezone
import logging
import os
import re
from pathlib import Path
from hashlib import sha1
import queue
import threading
import time
from difflib import SequenceMatcher
from types import SimpleNamespace
from typing import Callable
from uuid import uuid4

from .ai_reconstructor import AIReconstructor
from .assembler import apply_overlap_provenance, apply_semantic_provenance, assemble_candidate_records, merge_allocation_fields
from .buffer import EvidenceBuffer, FrameBufferState, ShortRawBuffer
from .checkpoint import CheckpointManager
from .capture_backend import CaptureBackend, CaptureTargetIdentity, RegionScreenshotFallback, WindowsGraphicsCapture, get_foreground_window_handle
from .continuity import analyze_frame_overlaps, build_continuity_records, continuity_health, estimate_motion_level
from .coverage_ledger import CoverageObservation, EvidenceCoverageLedger
from .correctness_engine import CorrectnessEngine
from .cropper import load_selected_detail_panel_layouts, prepare_row_field_crops, prepare_selected_detail_field_crops
from .detection import detect_inventory_region
from .evidence import build_representative_evidence
from .extraction_controller import ExtractionRateController
from .inventory_definition_engine import InventoryDefinitionEngine
from .layout import segment_inventory_rows
from .memory_governor import MemoryAction, MemoryDecision, MemoryGovernor
from .models import CandidateDecision, DiagnosticReport, FieldKind, FrameImage, FrameRecord, Rect, ReplayFrameMode, ScanScope, SessionDiagnosticReport
from .normalize import build_field_candidates
from .organization_pass import OrganizationPass
from .locking import build_scan_integrity_report
from .ocr_runner import get_ocr_engine_summary, run_ocr_attempts
from .overlay import OverlaySnapshot, render_corner_overlay
from .preprocess import preprocess_inventory_region
from .profile import create_default_template, load_profile
from .profile_version import ProfileVersion
from .privacy_policy import PrivacyPolicy
from .quality import assess_frame_quality
from .queue_limits import default_queue_limits, queue_has_capacity
from .rate_metrics import RateMetrics
from .ranking import rank_field_candidates
from .recognition_orchestrator import RecognitionOrchestrator
from .recorded_frame_source import RecordedFrame, RecordedFrameSource, capture_format_decision
from .recovery import ResumedSession
from .review import ReviewSession
from .screen_classifier import ScreenClass, ScreenClassifier, ScreenClassification
from .semantic_allocator import CandidateInventoryRecord, SemanticAllocator
from .session_fixture import SessionFixture, validate_expected_overlaps
from .session_store import commit_session_artifacts
from .settings import load_settings
from .event_bus import EventBus, UIEvent
from .temporal import merge_ranked_candidates
from .temporal_group import FrameObservation, SlidingTemporalGrouper
from .truth_state import TruthProgression, TruthState

LOGGER = logging.getLogger(__name__)
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
IMAGE_SOURCE_LIVE_CAPTURE = "live_capture"
IMAGE_SOURCE_RECORDED_CAPTURE = "recorded_capture"
IMAGE_SOURCE_REPLAY_FIXTURE = "replay_fixture"
IMAGE_SOURCE_GENERAL = "general_image"
RecordedExtractionProgressCallback = Callable[[dict[str, object]], None]


class SelectedDetailTemporalGuard:
    """Hold detail evidence until a selected row/detail identity stays coherent."""

    def __init__(self, *, required_consecutive_observations: int = 2) -> None:
        self.required_consecutive_observations = max(2, int(required_consecutive_observations))
        self._last_selection_key = ""
        self._last_pair_key = ""
        self._stable_observations = 0

    def observe(
        self,
        correlation: dict[str, object],
        *,
        frame_id: str,
        capture_timestamp: float,
        scrolling: bool,
    ) -> dict[str, object]:
        guarded = dict(correlation)
        row_name = _identity_text(dict(guarded.get("row_name_ocr", {})).get("normalized_text", ""))
        detail_title = _identity_text(dict(guarded.get("detail_title_ocr", {})).get("normalized_text", ""))
        row_slot = _row_slot_from_row_id(str(guarded.get("selected_row_id", "")))
        selection_key = f"{row_slot}:{row_name}" if row_slot and row_name else ""
        base_correlated = bool(guarded.get("correlated"))
        selection_changed = bool(selection_key and self._last_selection_key and selection_key != self._last_selection_key)

        if selection_key:
            self._last_selection_key = selection_key
        if scrolling:
            self._last_pair_key = ""
            self._stable_observations = 0
            return self._hold(guarded, "DETAIL_PANEL_SCROLLING_TRANSITION", frame_id, capture_timestamp, selection_changed)
        if not selection_key or not detail_title:
            self._last_pair_key = ""
            self._stable_observations = 0
            return self._hold(guarded, "DETAIL_PANEL_IDENTITY_UNAVAILABLE", frame_id, capture_timestamp, selection_changed)
        if not base_correlated:
            self._last_pair_key = ""
            self._stable_observations = 0
            reason = "DETAIL_PANEL_SELECTION_TRANSITION" if selection_changed else str(guarded.get("hold_reason") or "SELECTED_ROW_CORRELATION_NOT_PROVEN")
            return self._hold(guarded, reason, frame_id, capture_timestamp, selection_changed)

        pair_key = f"{selection_key}|{detail_title}"
        if pair_key == self._last_pair_key:
            self._stable_observations += 1
        else:
            self._last_pair_key = pair_key
            self._stable_observations = 1
        if self._stable_observations < self.required_consecutive_observations:
            return self._hold(guarded, "DETAIL_PANEL_SETTLING", frame_id, capture_timestamp, selection_changed)

        guarded["temporal_state"] = "STABLE_CORRELATED"
        guarded["temporal_observations"] = self._stable_observations
        guarded["temporal_required_observations"] = self.required_consecutive_observations
        guarded["temporal_frame_id"] = frame_id
        guarded["temporal_capture_timestamp"] = capture_timestamp
        return guarded

    def _hold(
        self,
        correlation: dict[str, object],
        reason: str,
        frame_id: str,
        capture_timestamp: float,
        selection_changed: bool,
    ) -> dict[str, object]:
        correlation["correlated"] = False
        correlation["hold_reason"] = reason
        correlation["temporal_state"] = "SELECTION_TRANSITION" if selection_changed else "DETAIL_PENDING"
        correlation["temporal_observations"] = self._stable_observations
        correlation["temporal_required_observations"] = self.required_consecutive_observations
        correlation["temporal_frame_id"] = frame_id
        correlation["temporal_capture_timestamp"] = capture_timestamp
        return correlation


class SelectedRowIdentityEpoch:
    """Reconcile bounded selected-row OCR observations without synthesizing text."""

    def __init__(self, *, required_observations: int = 3, max_observations: int = 4) -> None:
        self.required_observations = max(2, int(required_observations))
        self.max_observations = max(self.required_observations, int(max_observations))
        self._row_slot = 0
        self._observations: deque[dict[str, object]] = deque(maxlen=self.max_observations)

    @property
    def needs_observation(self) -> bool:
        return len(self._observations) < self.required_observations

    def observe(
        self,
        correlation: dict[str, object],
        *,
        frame_id: str,
        capture_timestamp: float,
        scrolling: bool,
    ) -> dict[str, object]:
        result = dict(correlation)
        row_slot = _row_slot_from_row_id(str(result.get("selected_row_id", "")))
        row_ocr = dict(result.get("row_name_ocr") or {})
        normalized = _identity_text(str(row_ocr.get("normalized_text", "")))
        if scrolling:
            self._reset()
            return self._hold(result, "ROW_IDENTITY_SCROLLING_TRANSITION")
        if not row_slot:
            self._reset()
            return self._hold(result, "ROW_IDENTITY_SELECTED_ROW_UNAVAILABLE")
        if self._row_slot and row_slot != self._row_slot:
            self._reset()
        self._row_slot = row_slot
        if not normalized:
            return self._hold(result, "ROW_IDENTITY_OCR_UNAVAILABLE")

        observation = {
            "frame_id": frame_id,
            "timestamp": capture_timestamp,
            "row_id": str(result.get("selected_row_id", "")),
            "row_slot": row_slot,
            "raw_text": str(row_ocr.get("raw_text", "")),
            "normalized_text": str(row_ocr.get("normalized_text", "")),
            "confidence": float(row_ocr.get("confidence", 0.0)),
            "crop_bounds": dict(row_ocr.get("crop_bounds") or {}),
            "preprocess_variant": str(row_ocr.get("preprocess_variant", "")),
        }
        self._observations.append(observation)
        observations = list(self._observations)
        compatible = [
            item
            for item in observations
            if _text_similarity(_identity_text(str(item["normalized_text"])), normalized) >= 0.80
        ]
        conflicting = [
            item
            for item in observations
            if _text_similarity(_identity_text(str(item["normalized_text"])), normalized) < 0.55
        ]
        evidence = {
            "epoch_row_slot": row_slot,
            "required_observations": self.required_observations,
            "observations": observations,
            "compatible_observation_count": len(compatible),
            "conflicting_observation_count": len(conflicting),
        }
        if len(conflicting) >= 2:
            result["row_identity_epoch"] = evidence
            return self._hold(result, "ROW_IDENTITY_CONFLICTED")
        if len(compatible) < self.required_observations:
            result["row_identity_epoch"] = evidence
            return self._hold(result, "ROW_IDENTITY_PENDING")

        chosen = max(compatible, key=lambda item: (float(item["confidence"]), str(item["normalized_text"])))
        chosen_identity = _identity_text(str(chosen["normalized_text"]))
        detail_ocr = dict(result.get("detail_title_ocr") or {})
        detail_identity = _identity_text(str(detail_ocr.get("normalized_text", "")))
        similarity = _text_similarity(chosen_identity, detail_identity)
        evidence["chosen_observation"] = chosen
        evidence["chosen_identity"] = str(chosen["normalized_text"])
        evidence["detail_similarity"] = similarity
        result["row_name_ocr"] = {
            "raw_text": chosen["raw_text"],
            "normalized_text": chosen["normalized_text"],
            "confidence": chosen["confidence"],
            "crop_bounds": chosen["crop_bounds"],
            "preprocess_variant": chosen["preprocess_variant"],
        }
        result["row_identity_epoch"] = evidence
        if not detail_identity or similarity < 0.72:
            return self._hold(result, "ROW_IDENTITY_DETAIL_INCOMPATIBLE")

        result["correlated"] = True
        result["hold_reason"] = ""
        result["best_similarity"] = similarity
        guards = dict(result.get("correlation_guards") or {})
        guards.update(
            {
                "temporal_row_identity_supported": True,
                "temporal_row_identity_required_observations": self.required_observations,
                "temporal_row_identity_observations": len(compatible),
                "temporal_row_identity_detail_similarity": similarity,
            }
        )
        result["correlation_guards"] = guards
        return result

    def _reset(self) -> None:
        self._row_slot = 0
        self._observations.clear()

    @staticmethod
    def _hold(correlation: dict[str, object], reason: str) -> dict[str, object]:
        correlation["correlated"] = False
        correlation["hold_reason"] = reason
        return correlation


class CaptureLoop:
    def __init__(
        self,
        *,
        event_bus: EventBus,
        capture_backend: CaptureBackend | None = None,
        session_id: str,
        target_window_handle: int | None,
        target_window_label: str = "",
        target_window_identity: CaptureTargetIdentity | None = None,
        profile_id: str = "defiance",
        scan_scope: str = "Full",
        persist_dir: Path | None = None,
        frame_interval_seconds: float = 0.10,
        buffer_limit_gb: float = 3.0,
    ) -> None:
        self.event_bus = event_bus
        self.capture_backend = capture_backend or RegionScreenshotFallback()
        self.session_id = session_id
        self.target_window_handle = target_window_handle
        self.target_window_label = target_window_label
        self.target_window_identity = target_window_identity
        self.profile_id = profile_id
        self.scan_scope = _normalize_live_scan_scope(scan_scope)
        self.persist_dir = persist_dir
        self.frame_interval_seconds = max(0.01, float(frame_interval_seconds))
        self.buffer_limit_gb = float(buffer_limit_gb)
        self.raw_buffer = ShortRawBuffer(max_items=64)
        self._thread: threading.Thread | None = None
        self._ocr_thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._frame_counter = 0
        self._running = False
        self._published_capture_loss = False
        self._capture_loss_timeout_seconds = 1.0
        self._last_successful_capture_at: float | None = None
        self._last_capture_failure_reason = ""
        self._pending_events: "queue.Queue[tuple[UIEvent, dict[str, object]]]" = queue.Queue()
        self._ocr_work_queue: "queue.Queue[dict[str, object]]" = queue.Queue()
        self._frame_reports: list[DiagnosticReport] = []
        self._frame_reports_lock = threading.Lock()
        self._processed_frame_ids: set[str] = set()
        self._previous_signatures: dict[int, str] = {}
        self._previous_frame_fingerprint = ""
        self._seen_capture_paths: set[str] = set()
        self._session_buffer = EvidenceBuffer()
        self._selected_detail_guard = SelectedDetailTemporalGuard()
        self._selected_row_identity_epoch = SelectedRowIdentityEpoch()
        self._metrics = RateMetrics()
        self._temporal_grouper = SlidingTemporalGrouper()
        self._controller = ExtractionRateController()
        self._memory_governor = MemoryGovernor()
        self._last_memory_decision = MemoryDecision(0, "NORMAL", MemoryAction.KEEP, 1.0, ("WITHIN_NORMAL_MEMORY_BOUNDS",))
        self._queue_warnings: list[str] = []
        self._last_candidate_timestamp: float | None = None
        self._last_committed_report: dict[str, object] | None = None
        self._capture_attempt_log: deque[dict[str, object]] = deque(maxlen=64)
        self._capture_attempt_count = 0
        self._accepted_capture_count = 0
        self._rejected_capture_count = 0
        self._reacquisition_count = 0
        self._capture_lost_count = 0
        self._capture_recovered_count = 0
        self._current_consecutive_accepted = 0
        self._max_consecutive_accepted = 0
        self._dimension_observations: set[tuple[int, int]] = set()
        self._unique_window_handles: set[int] = set()

    @property
    def running(self) -> bool:
        return self._running

    def start_capture_loop(self) -> bool:
        if self._thread is not None and self._thread.is_alive():
            return False
        self._stop_event.clear()
        self._ocr_thread = threading.Thread(target=self._run_ocr_loop, name=f"OCRingOcrLoop-{self.session_id}", daemon=True)
        self._ocr_thread.start()
        self._thread = threading.Thread(target=self._run_loop, name=f"OCRingCaptureLoop-{self.session_id}", daemon=True)
        self._running = True
        self._thread.start()
        self.event_bus.publish(
            UIEvent.SCAN_STARTED,
            {
                "session_id": self.session_id,
                "window_handle": self.target_window_handle,
                "window_id": self.target_window_label,
            },
        )
        return True

    def stop_capture_loop(self) -> dict[str, object]:
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
        if self._ocr_thread is not None:
            self._ocr_thread.join(timeout=5.0)
        self._thread = None
        self._ocr_thread = None
        self._running = False
        self.flush_pending_events()
        report = self._finalize_live_session_report()
        drained = self.raw_buffer.release_all_except(())
        diagnostics = self.raw_buffer.diagnostics()
        self.event_bus.publish(
            UIEvent.SCAN_STOPPED,
            {
                "session_id": self.session_id,
                "window_handle": self.target_window_handle,
                "window_id": self.target_window_label,
                "drained_frame_ids": list(drained),
                "buffer_items": diagnostics.get("item_count", 0),
                "buffer_bytes": diagnostics.get("total_bytes", 0),
                "assembled_record_count": len(report.get("assembled_records", [])) if report else 0,
            },
        )
        return {
            "drained_frame_ids": list(drained),
            "report": report,
            "capture_proof": self.capture_proof(),
            **diagnostics,
        }

    def diagnostics(self) -> dict[str, object]:
        diagnostics = self.raw_buffer.diagnostics()
        return {
            "session_id": self.session_id,
            "running": self.running,
            "target_window_handle": self.target_window_handle,
            "target_window_label": self.target_window_label,
            "capture_proof": self.capture_proof(),
            **diagnostics,
        }

    def capture_proof(self) -> dict[str, object]:
        attempts = list(self._capture_attempt_log)
        accepted = [entry for entry in attempts if entry.get("validity_result") == "accepted"]
        sequence_ids = [int(entry["sequence_id"]) for entry in attempts]
        timestamps = [float(entry["capture_timestamp"]) for entry in attempts]
        return {
            "attempted_frames": self._capture_attempt_count,
            "accepted_frames": self._accepted_capture_count,
            "rejected_frames": self._rejected_capture_count,
            "dimensions_observed": [
                {"width": width, "height": height}
                for width, height in sorted(self._dimension_observations)
            ],
            "unique_hwnds_observed": sorted(self._unique_window_handles),
            "reacquisitions": self._reacquisition_count,
            "consecutive_accepted_frame_max": self._max_consecutive_accepted,
            "capture_lost_events": self._capture_lost_count,
            "capture_recovered_events": self._capture_recovered_count,
            "unique_sequence_ids": len(set(sequence_ids)),
            "unique_timestamps": len(set(timestamps)),
            "unique_frame_fingerprints": len({str(entry.get("frame_fingerprint") or "") for entry in accepted if entry.get("frame_fingerprint")}),
            "static_frames": sum(1 for entry in accepted if entry.get("frame_change_classification") == "static"),
            "changed_frames": sum(1 for entry in accepted if entry.get("frame_change_classification") == "changed"),
            "sequence_gaps": sum(1 for left, right in zip(sequence_ids, sequence_ids[1:]) if right != left + 1),
            "out_of_order_frames": sum(1 for left, right in zip(timestamps, timestamps[1:]) if right <= left),
            "stale_frame_reuse": sum(1 for entry in accepted if entry.get("stale_path_reuse")),
            "attempt_log": attempts,
        }

    def flush_pending_events(self) -> int:
        delivered = 0
        while True:
            try:
                event_type, payload = self._pending_events.get_nowait()
            except queue.Empty:
                break
            self.event_bus.publish(event_type, payload)
            delivered += 1
        return delivered

    def _run_loop(self) -> None:
        while not self._stop_event.is_set():
            capture_timestamp = time.time()
            now = time.monotonic()
            frame = self.capture_backend.capture(
                target_window_handle=self.target_window_handle,
                foreground_window_handle=get_foreground_window_handle(),
                target_visible=True,
                target_identity=self.target_window_identity,
            )
            if frame.window_handle and frame.window_handle != int(self.target_window_handle or 0):
                self.target_window_handle = int(frame.window_handle)
            self._record_capture_attempt(frame=frame, capture_timestamp=capture_timestamp)
            if frame.status.value != "CAPTURE_ACTIVE":
                self._last_capture_failure_reason = frame.reason
                if self._last_successful_capture_at is None:
                    self._last_successful_capture_at = now
                elapsed_without_frame = now - self._last_successful_capture_at
                if elapsed_without_frame > self._capture_loss_timeout_seconds and not self._published_capture_loss:
                    self._pending_events.put(
                        (
                            UIEvent.CAPTURE_LOST,
                            {
                                "session_id": self.session_id,
                                "window_handle": self.target_window_handle,
                                "window_id": self.target_window_label,
                                "reason": frame.reason,
                                "elapsed_without_frame_seconds": round(elapsed_without_frame, 3),
                            },
                        )
                    )
                    self._published_capture_loss = True
                    self._capture_lost_count += 1
                time.sleep(self.frame_interval_seconds)
                continue

            self._last_successful_capture_at = now
            if self._published_capture_loss:
                self._pending_events.put(
                    (
                        UIEvent.CAPTURE_RECOVERED,
                        {
                            "session_id": self.session_id,
                            "window_handle": self.target_window_handle,
                            "window_id": self.target_window_label,
                            "reason": self._last_capture_failure_reason,
                        },
                    )
                )
                self._published_capture_loss = False
                self._capture_recovered_count += 1
            self._last_capture_failure_reason = ""

            self._frame_counter += 1
            frame_id = f"{self.session_id}-frame-{self._frame_counter:06d}"
            estimated_bytes = max(1, int(frame.width) * int(frame.height) * 3)
            self.raw_buffer.retain(
                frame_id,
                {
                    "frame_id": frame_id,
                    "session_id": self.session_id,
                    "capture_timestamp": capture_timestamp,
                    "image_path": frame.image_path,
                    "window_handle": frame.window_handle,
                    "window_title": frame.window_title,
                },
                estimated_bytes=estimated_bytes,
                state=FrameBufferState.RAW,
            )
            diagnostics = self.raw_buffer.diagnostics()
            self._ocr_work_queue.put(
                {
                    "frame_id": frame_id,
                    "image_path": frame.image_path,
                    "timestamp_utc": datetime.fromtimestamp(capture_timestamp, timezone.utc).isoformat(),
                    "capture_timestamp": capture_timestamp,
                }
            )
            self._pending_events.put(
                (
                    UIEvent.FRAME_CAPTURED,
                    {
                        "session_id": self.session_id,
                        "frame_id": frame_id,
                        "capture_timestamp": capture_timestamp,
                        "width": frame.width,
                        "height": frame.height,
                        "image_path": frame.image_path,
                        "window_handle": frame.window_handle,
                        "window_title": frame.window_title,
                        "capture_metadata": dict(frame.capture_metadata),
                        "buffer_items": diagnostics.get("item_count", 0),
                        "buffer_bytes": diagnostics.get("total_bytes", 0),
                        "buffer_limit_gb": self.buffer_limit_gb,
                        "queue_depth": diagnostics.get("item_count", 0),
                    },
                )
            )
            time.sleep(self.frame_interval_seconds)

        self._running = False

    def _run_ocr_loop(self) -> None:
        while not self._stop_event.is_set() or not self._ocr_work_queue.empty():
            try:
                payload = self._ocr_work_queue.get(timeout=0.1)
            except queue.Empty:
                continue
            try:
                self._process_live_frame(payload)
            except Exception:
                LOGGER.exception("Live OCR pipeline failed for session %s frame %s", self.session_id, payload.get("frame_id"))
            finally:
                self._ocr_work_queue.task_done()

    def _process_live_frame(self, payload: dict[str, object]) -> None:
        frame_id = str(payload.get("frame_id") or "")
        image_path_value = str(payload.get("image_path") or "")
        if not frame_id or not image_path_value:
            return
        if frame_id in self._processed_frame_ids:
            return

        image_path = Path(image_path_value)
        if not _is_valid_image_for_source(image_path, image_source=IMAGE_SOURCE_LIVE_CAPTURE):
            LOGGER.warning("Skipping unreadable capture for session %s frame %s at %s", self.session_id, frame_id, image_path)
            return

        self.raw_buffer.claim_by_ocr(frame_id)
        try:
            captured = _capture_frame_state(
                image_path,
                profile_id=self.profile_id,
                frame_id=frame_id,
                session_id=self.session_id,
                timestamp_utc=str(payload.get("timestamp_utc") or datetime.now(timezone.utc).isoformat()),
                image_source=IMAGE_SOURCE_LIVE_CAPTURE,
            )
            self._metrics.record_capture(captured.capture_timestamp)
            readable = _is_readable(captured)
            if readable:
                self._metrics.record_readable(captured.capture_timestamp)
            changed_row_ids = _changed_row_ids(captured.frame.frame_id, self._previous_signatures, captured.row_signatures)
            if changed_row_ids:
                self._metrics.record_useful(captured.capture_timestamp)
            self._temporal_grouper.add_frame(
                FrameObservation(
                    frame_id=captured.frame.frame_id,
                    timestamp=captured.capture_timestamp,
                    readability_score=_readability_score(captured),
                    row_signatures=dict(captured.row_signatures),
                )
            )
            current_pressure = _collect_runtime_pressure(
                buffer=self._session_buffer,
                ocr_queue=[frame_id] if readable else [],
                ai_queue=[],
            )
            self._last_memory_decision = self._memory_governor.evaluate(
                ram_used=self._session_buffer.total_bytes() + self.raw_buffer.total_bytes(),
                ram_limit=3 * 1024 * 1024 * 1024,
                capture_fps=self._metrics.capture_fps,
                retained_fps=self._metrics.readable_fps,
                extraction_rate=self._metrics.extraction_rate,
                raw_queue_depth=len(self._frame_reports),
                ocr_queue_depth=1 if readable else 0,
                ai_queue_depth=0,
                motion_rate=_estimate_change_motion(self._previous_signatures, captured.row_signatures),
                frame_uniqueness=_frame_uniqueness(self._previous_signatures, captured.row_signatures),
                readability=_readability_score(captured),
                continuity_anchors=1 if changed_row_ids else 0,
                unresolved_observations=len(changed_row_ids),
                cpu_load=float(current_pressure["cpu_pressure"]),
                gpu_load=0.0,
            )
            controller_state = self._controller.evaluate(
                capture_fps=self._metrics.capture_fps,
                readable_fps=self._metrics.readable_fps,
                useful_fps=self._metrics.useful_fps,
                frame_queue_depth=len(self._frame_reports),
                ocr_queue_depth=1 if readable else 0,
                motion_level=_estimate_change_motion(self._previous_signatures, captured.row_signatures),
                continuity_health="OK",
                cpu_load=float(current_pressure["cpu_pressure"]),
                gpu_load=0.0,
                target_latency=0.5,
            )
            should_extract = (
                readable
                and (
                    not self._processed_frame_ids
                    or self._selected_row_identity_epoch.needs_observation
                    # A changed row can be a new highlighted selection. It must
                    # reach the epoch guard even when throughput defers normal OCR.
                    or bool(changed_row_ids)
                )
                and self._last_memory_decision.action not in {MemoryAction.DEFER, MemoryAction.DROP}
            )
            if not should_extract:
                self._previous_signatures = dict(captured.row_signatures)
                self._processed_frame_ids.add(frame_id)
                return

            report = _build_frame_report(
                image_path,
                profile_id=self.profile_id,
                frame_id=frame_id,
                session_id=self.session_id,
                timestamp_utc=str(payload.get("timestamp_utc") or captured.frame.timestamp_utc),
                capture_state=captured,
                changed_row_ids=changed_row_ids,
                row_identity_epoch=self._selected_row_identity_epoch,
                # Raw row hashes are intentionally sensitive for continuity, but
                # Defiance UI animation makes them unsuitable as a scroll verdict.
                # Selection changes and incompatible identity observations still
                # reset or hold the epoch without this false-positive gate.
                scrolling=False,
            )
            report = _apply_selected_detail_temporal_guard(
                report,
                guard=self._selected_detail_guard,
                capture_timestamp=captured.capture_timestamp,
                scrolling=False,
            )
            if report.ranked_candidates:
                self._metrics.record_extraction_event(
                    captured.capture_timestamp,
                    field_types=tuple(sorted({candidate.field_kind.value for candidate in report.ranked_candidates})),
                )
                self._last_candidate_timestamp = captured.capture_timestamp
                self._metrics.record_candidate(
                    captured.capture_timestamp,
                    count=len(report.ranked_candidates),
                    frame_capture_timestamp=captured.capture_timestamp,
                )
            for item in report.retained_evidence:
                self._session_buffer.retain(item)
                if item.evidence_kind.value == "anchor":
                    self._session_buffer.pin(item.crop_id)
                else:
                    self._session_buffer.transition(item.crop_id, FrameBufferState.SELECTED)
            self._session_buffer.trim_evidence(current_pressure)
            with self._frame_reports_lock:
                self._frame_reports.append(report)
            self._pending_events.put(
                (
                    UIEvent.FRAME_ANALYZED,
                    {
                        "session_id": self.session_id,
                        "frame_id": frame_id,
                        "screen_class": str(getattr(report, "screen_class", "unknown")),
                        "screen_reason": str(getattr(report, "screen_reason", "")),
                        "recognition_hold": bool(getattr(report, "selected_detail_correlation", {}).get("hold_reason")),
                        "hold_reason": str(
                            getattr(report, "selected_detail_correlation", {}).get("hold_reason")
                            or getattr(report, "hold_reason", "")
                            or ""
                        ),
                    },
                )
            )
            self._previous_signatures = dict(captured.row_signatures)
            self._processed_frame_ids.add(frame_id)
        finally:
            self.raw_buffer.release_ocr_claim(frame_id)

    def _finalize_live_session_report(self) -> dict[str, object] | None:
        with self._frame_reports_lock:
            frame_reports = tuple(self._frame_reports)
        if not frame_reports:
            self._last_committed_report = None
            return None

        report = _build_session_report(
            frame_reports,
            profile_id=self.profile_id,
            scan_scope=self.scan_scope,
        )
        verified_count = sum(1 for item in report["assembled_records"] if item["state"] == "complete")
        if verified_count:
            final_timestamp = datetime.now(timezone.utc).timestamp()
            self._metrics.record_verified(
                final_timestamp,
                count=verified_count,
                frame_capture_timestamp=self._metrics.captured_timestamps[0] if self._metrics.captured_timestamps else None,
                candidate_produced_timestamp=self._last_candidate_timestamp,
            )
        self._session_buffer.trim_to_compact_provenance()
        _attach_throughput(
            report,
            metrics=self._metrics,
            temporal_windows=list(self._temporal_grouper.flush()),
            queue_depth=self._ocr_work_queue.qsize(),
            buffer_bytes=self._session_buffer.total_bytes() + self.raw_buffer.total_bytes(),
            memory_decision=self._last_memory_decision,
        )
        if self._queue_warnings:
            report["queue_warnings"] = list(self._queue_warnings)
        report["capture_proof"] = self.capture_proof()
        for index, record in enumerate(report.get("candidate_inventory", []), start=1):
            self._pending_events.put(
                (
                    UIEvent.RECORD_CANDIDATE_CREATED,
                    {
                        "session_id": self.session_id,
                        "record_index": index,
                        "record_class": record.get("record_class", "UNKNOWN"),
                        "field_values": dict(record.get("field_values", {})),
                        "confidence": float(record.get("confidence", 0.0)),
                        "status": record.get("status", "NEEDS_REVIEW"),
                    },
                )
            )
        commit_session_artifacts(report, self.persist_dir)
        self._last_committed_report = report
        return report

    def _record_capture_attempt(self, *, frame: object, capture_timestamp: float) -> None:
        self._capture_attempt_count += 1
        capture_frame = frame
        metadata = dict(getattr(capture_frame, "capture_metadata", {}) or {})
        resolved_window = dict(metadata.get("resolved_window") or {})
        actual_handle = int(
            getattr(capture_frame, "window_handle", 0)
            or resolved_window.get("hwnd")
            or metadata.get("reacquired_to_handle")
            or 0
        )
        if actual_handle > 0:
            self._unique_window_handles.add(actual_handle)
        dimensions = (
            max(0, int(getattr(capture_frame, "width", 0))),
            max(0, int(getattr(capture_frame, "height", 0))),
        )
        self._dimension_observations.add(dimensions)
        reacquired = bool(metadata.get("reacquired_to_handle"))
        if reacquired:
            self._reacquisition_count += 1
        accepted = getattr(capture_frame, "status", None) is not None and getattr(capture_frame.status, "value", "") == "CAPTURE_ACTIVE"
        image_path = Path(str(getattr(capture_frame, "image_path", "") or ""))
        image_path_key = str(image_path.resolve()) if image_path else ""
        stale_path_reuse = bool(accepted and image_path_key and image_path_key in self._seen_capture_paths)
        if accepted and image_path_key:
            self._seen_capture_paths.add(image_path_key)
        fingerprint = _frame_fingerprint(image_path) if accepted else ""
        previous_fingerprint = self._previous_frame_fingerprint
        change_classification = ""
        if fingerprint:
            change_classification = "static" if fingerprint == previous_fingerprint else "changed"
            self._previous_frame_fingerprint = fingerprint
        if accepted:
            self._accepted_capture_count += 1
            self._current_consecutive_accepted += 1
            self._max_consecutive_accepted = max(self._max_consecutive_accepted, self._current_consecutive_accepted)
        else:
            self._rejected_capture_count += 1
            self._current_consecutive_accepted = 0
        self._capture_attempt_log.append(
            {
                "sequence_id": self._capture_attempt_count,
                "capture_timestamp": capture_timestamp,
                "selected_hwnd": int(metadata.get("selected_window_handle") or self.target_window_handle or 0),
                "actual_hwnd": actual_handle,
                "window_title": str(getattr(capture_frame, "window_title", "") or resolved_window.get("title") or ""),
                "window_class": str(resolved_window.get("class_name") or ""),
                "pid": int(resolved_window.get("pid") or 0),
                "reacquisition_occurred": reacquired,
                "dimensions": {
                    "width": dimensions[0],
                    "height": dimensions[1],
                },
                "validity_result": "accepted" if accepted else "rejected",
                "frame_fingerprint": fingerprint,
                "previous_frame_fingerprint": previous_fingerprint,
                "frame_change_classification": change_classification,
                "stale_path_reuse": stale_path_reuse,
                "failure_reason": str(getattr(capture_frame, "reason", "") or ""),
                "surface_check": dict(metadata.get("surface_check") or {}),
                "returned_surface_check": dict(metadata.get("returned_surface_check") or {}),
                "client_screen_rect": dict((resolved_window.get("client_screen_rect") or {})),
                "capture_rect": dict((metadata.get("capture_rect") or {})),
                "returned_image_size": dict((metadata.get("returned_image_size") or {})),
            }
        )


@dataclass(frozen=True)
class _CapturedFrameState:
    frame: FrameRecord
    ocr_engine: object
    quality: object
    row_zones: tuple[object, ...]
    preprocessed_regions: tuple[object, ...]
    capture_timestamp: float
    row_signatures: dict[int, str]
    screen_classification: ScreenClassification
    debug_capture_enabled: bool


def _load_image_size(image_path: Path, *, image_source: str = IMAGE_SOURCE_GENERAL) -> tuple[int, int]:
    try:
        from PIL import Image
    except ImportError as exc:
        raise RuntimeError("Pillow is required to inspect frame dimensions.") from exc

    if not _is_valid_image_for_source(image_path, image_source=image_source):
        if image_source == IMAGE_SOURCE_LIVE_CAPTURE:
            raise ValueError(f"Invalid live PNG frame: {image_path}")
        raise ValueError(f"Invalid image frame: {image_path}")
    with Image.open(image_path) as image:
        image.verify()
    with Image.open(image_path) as image:
        width, height = image.size
    return int(width), int(height)


def run_frame_diagnostic(image_path: Path, *, profile_id: str) -> dict[str, object]:
    return _build_frame_report(
        image_path,
        profile_id=profile_id,
        image_source=IMAGE_SOURCE_GENERAL,
    ).as_dict()


def run_session_diagnostic(image_paths: tuple[Path, ...], *, profile_id: str) -> dict[str, object]:
    return run_session_diagnostic_with_recovery(image_paths, profile_id=profile_id)


def extract_from_recorded_frames(
    recording_dir: Path,
    *,
    profile_id: str,
    session_id: str | None = None,
    persist_dir: Path | None = None,
    progress_callback: RecordedExtractionProgressCallback | None = None,
) -> dict[str, object]:
    extraction_started = time.perf_counter()
    stage_timings: list[dict[str, object]] = []
    _record_extraction_stage(
        progress_callback,
        stage_timings,
        stage="Loading recording",
        input_count=1,
        output_count=0,
        current_index=0,
        total_count=0,
        extraction_started=extraction_started,
        complete=False,
    )
    source = RecordedFrameSource.from_directory(
        recording_dir,
        session_id=session_id or f"recording-{uuid4().hex[:8]}",
        require_finalized=True,
    )
    frames = source.frames()
    _record_extraction_stage(
        progress_callback,
        stage_timings,
        stage="Loading recording",
        input_count=1,
        output_count=len(frames),
        current_index=0,
        total_count=len(frames),
        extraction_started=extraction_started,
    )
    _record_extraction_stage(
        progress_callback,
        stage_timings,
        stage="Selecting useful frames",
        input_count=len(frames),
        output_count=0,
        current_index=0,
        total_count=len(frames),
        extraction_started=extraction_started,
        complete=False,
    )
    selection_report = source.useful_frame_selection_report()
    useful_frames = tuple(selection_report["useful_frames"])
    _record_extraction_stage(
        progress_callback,
        stage_timings,
        stage="Selecting useful frames",
        input_count=len(frames),
        output_count=len(useful_frames),
        current_index=len(frames),
        total_count=len(frames),
        extraction_started=extraction_started,
    )
    report = run_recorded_frame_extraction(
        useful_frames,
        profile_id=profile_id,
        progress_callback=progress_callback,
        stage_timings=stage_timings,
        extraction_started=extraction_started,
    )
    _record_extraction_stage(
        progress_callback,
        stage_timings,
        stage="Building inventory",
        input_count=len(useful_frames),
        output_count=len(report.get("assembled_records", [])),
        current_index=len(useful_frames),
        total_count=len(useful_frames),
        extraction_started=extraction_started,
    )
    report["recorded_frame_source"] = {
        **source.as_dict(),
        "useful_frame_count": len(useful_frames),
        "duplicate_static_frames_suppressed": int(selection_report["duplicate_static_frames_suppressed"]),
        "exact_duplicates_removed": int(selection_report["exact_duplicates_removed"]),
        "static_redundant_frames_removed": int(selection_report["static_redundant_frames_removed"]),
        "temporal_redundant_frames_removed": int(selection_report["temporal_redundant_frames_removed"]),
        "dwell_reobservation_frames_kept": int(selection_report["dwell_reobservation_frames_kept"]),
        "static_frame_diff_threshold": float(selection_report["static_frame_diff_threshold"]),
        "min_useful_frame_interval_seconds": float(selection_report["min_useful_frame_interval_seconds"]),
        "high_motion_diff_threshold": float(selection_report["high_motion_diff_threshold"]),
        "dwell_reobservation_interval_seconds": float(selection_report["dwell_reobservation_interval_seconds"]),
        "max_kept_frames_per_dwell": int(selection_report["max_kept_frames_per_dwell"]),
        "capture_format_decision": capture_format_decision().as_dict(),
    }
    _record_extraction_stage(
        progress_callback,
        stage_timings,
        stage="Finalizing Review",
        input_count=len(report.get("assembled_records", [])),
        output_count=0,
        current_index=len(useful_frames),
        total_count=len(useful_frames),
        extraction_started=extraction_started,
        complete=False,
    )
    review_session = ReviewSession.from_report(report)
    review_summary = review_session.apply_auto_store_policy(load_settings().review_mode)
    report["review_summary"] = review_summary
    if "coverage_summary" in report:
        report["coverage_summary"]["auto_saved"] = int(review_summary.get("automatically_stored", 0))
        report["coverage_summary"]["needs_review"] = int(review_summary.get("needs_manual_review", 0))
        report["coverage_summary"]["unknown"] = int(review_summary.get("hold_unknown", 0))
    report["recorded_sqlite_commit"] = {
        "attempted": False,
        "path": "",
        "records_committed": 0,
    }
    if persist_dir is not None and review_summary.get("automatically_stored", 0) > 0:
        sqlite_path = persist_dir / "review_inventory.db"
        committed = review_session.commit_to_sqlite(sqlite_path)
        report["recorded_sqlite_commit"] = {
            "attempted": True,
            "path": str(sqlite_path.resolve()),
            "records_committed": committed,
        }
    if persist_dir is not None:
        report["persistence_commit_dir"] = str(commit_session_artifacts(report, persist_dir).resolve())
    _record_extraction_stage(
        progress_callback,
        stage_timings,
        stage="Finalizing Review",
        input_count=len(report.get("assembled_records", [])),
        output_count=int(review_summary.get("automatically_stored", 0)) + int(review_summary.get("needs_manual_review", 0)),
        current_index=len(useful_frames),
        total_count=len(useful_frames),
        extraction_started=extraction_started,
    )
    report["recorded_extraction_timings"] = stage_timings
    return report


def run_recorded_frame_extraction(
    frames: tuple[RecordedFrame, ...],
    *,
    profile_id: str,
    progress_callback: RecordedExtractionProgressCallback | None = None,
    stage_timings: list[dict[str, object]] | None = None,
    extraction_started: float | None = None,
) -> dict[str, object]:
    frame_reports: list[DiagnosticReport] = []
    coverage_ledger = EvidenceCoverageLedger()
    timings = stage_timings if stage_timings is not None else []
    started_at = extraction_started if extraction_started is not None else time.perf_counter()
    frame_timings: list[dict[str, object]] = []
    total_frames = len(frames)
    _record_extraction_stage(
        progress_callback,
        timings,
        stage="OCR",
        input_count=total_frames,
        output_count=0,
        current_index=0,
        total_count=total_frames,
        extraction_started=started_at,
        complete=False,
    )
    for index, frame in enumerate(frames, start=1):
        frame_started = time.perf_counter()
        captured = _capture_frame_state(
            frame.image_path,
            profile_id=profile_id,
            frame_id=frame.frame_id,
            session_id=frame.session_id,
            timestamp_utc=frame.timestamp_utc,
            image_source=IMAGE_SOURCE_RECORDED_CAPTURE,
        )
        report = _build_frame_report(
            frame.image_path,
            profile_id=profile_id,
            frame_id=frame.frame_id,
            session_id=frame.session_id,
            timestamp_utc=frame.timestamp_utc,
            capture_state=captured,
            image_source=IMAGE_SOURCE_RECORDED_CAPTURE,
        )
        coverage_ledger.observe(
            CoverageObservation(
                frame_id=frame.frame_id,
                sequence_id=frame.sequence_id,
                timestamp=frame.capture_timestamp,
                row_signatures=_ocr_text_row_signatures(report.ranked_candidates),
            )
        )
        frame_reports.append(report)
        frame_elapsed = round(time.perf_counter() - frame_started, 4)
        frame_timings.append(
            {
                "frame_id": frame.frame_id,
                "sequence_id": frame.sequence_id,
                "elapsed_seconds": frame_elapsed,
                "row_zones": len(getattr(frame_reports[-1], "row_zones", ())),
                "ocr_attempts": len(getattr(frame_reports[-1], "ocr_attempts", ())),
            }
        )
        _record_extraction_stage(
            progress_callback,
            timings,
            stage="OCR",
            input_count=total_frames,
            output_count=len(frame_reports),
            current_index=index,
            total_count=total_frames,
            extraction_started=started_at,
            metadata={
                "frame_id": frame.frame_id,
                "sequence_id": frame.sequence_id,
                "frame_elapsed_seconds": frame_elapsed,
                "ocr_attempts": len(getattr(frame_reports[-1], "ocr_attempts", ())),
                "row_zones": len(getattr(frame_reports[-1], "row_zones", ())),
            },
        )
    report = _build_session_report(
        tuple(frame_reports),
        profile_id=profile_id,
        scan_scope=ScanScope.FULL_INVENTORY,
        allow_recorded_slot_reuse=True,
    )
    report["recorded_capture_mode"] = True
    report["coverage_ledger"] = coverage_ledger.as_dict()
    report["coverage_summary"] = {
        "unique_entries_observed": len(report.get("continuity_records", [])),
        "stable_identities": sum(
            1
            for record in report.get("assembled_records", [])
            if str(dict(record.get("field_details", {})).get("item_name", {}).get("identity_status", "")) == "OBSERVED_STABLE"
        ),
        "auto_saved": 0,
        "needs_review": sum(1 for record in report.get("assembled_records", []) if str(record.get("state", "")) != "complete"),
        "unknown": sum(1 for record in report.get("assembled_records", []) if str(dict(record.get("fields", {})).get("item_name", "")).upper() == "UNKNOWN"),
        "coverage_gaps": len(report["coverage_ledger"]["gaps"]),
    }
    report["ocr_frame_timing_summary"] = _frame_timing_summary(frame_timings)
    return report


def _record_extraction_stage(
    callback: RecordedExtractionProgressCallback | None,
    stage_timings: list[dict[str, object]],
    *,
    stage: str,
    input_count: int,
    output_count: int,
    current_index: int,
    total_count: int,
    extraction_started: float,
    complete: bool = True,
    metadata: dict[str, object] | None = None,
) -> None:
    now = time.perf_counter()
    payload = {
        "stage": stage,
        "start_timestamp": datetime.now(timezone.utc).isoformat(),
        "end_timestamp": datetime.now(timezone.utc).isoformat() if complete else "",
        "input_count": input_count,
        "output_count": output_count,
        "current_index": current_index,
        "total_count": total_count,
        "cumulative_elapsed_seconds": round(now - extraction_started, 3),
        **(metadata or {}),
    }
    stage_timings.append(dict(payload))
    if callback is not None:
        callback(dict(payload))


def _frame_timing_summary(frame_timings: list[dict[str, object]]) -> dict[str, object]:
    if not frame_timings:
        return {
            "frames_timed": 0,
            "median_seconds": 0.0,
            "slowest_seconds": 0.0,
            "top_slow_frames": [],
        }
    elapsed = sorted(float(item["elapsed_seconds"]) for item in frame_timings)
    midpoint = len(elapsed) // 2
    median = elapsed[midpoint] if len(elapsed) % 2 else (elapsed[midpoint - 1] + elapsed[midpoint]) / 2
    top_slow = sorted(frame_timings, key=lambda item: float(item["elapsed_seconds"]), reverse=True)[:5]
    return {
        "frames_timed": len(frame_timings),
        "median_seconds": round(median, 4),
        "slowest_seconds": round(max(elapsed), 4),
        "top_slow_frames": top_slow,
    }


def run_session_diagnostic_with_recovery(
    image_paths: tuple[Path, ...],
    *,
    profile_id: str,
    resumed_session: ResumedSession | None = None,
    checkpoint_manager: CheckpointManager | None = None,
    checkpoint_interval_frames: int = 10,
) -> dict[str, object]:
    session_buffer = EvidenceBuffer()
    raw_buffer = ShortRawBuffer()
    ocr_queue: list[object] = []
    ai_queue: list[object] = []
    frame_reports = []
    metrics = RateMetrics()
    temporal_grouper = SlidingTemporalGrouper()
    controller = ExtractionRateController()
    memory_governor = MemoryGovernor()
    previous_signatures: dict[int, str] = {}
    temporal_windows: list[tuple[object, ...]] = []
    last_candidate_timestamp: float | None = None
    last_memory_decision = MemoryDecision(0, "NORMAL", MemoryAction.KEEP, 1.0, ("WITHIN_NORMAL_MEMORY_BOUNDS",))
    queue_limits = default_queue_limits()
    queue_warnings: list[str] = []
    start_index = resumed_session.next_frame_index if resumed_session is not None else 0
    for index, image_path in enumerate(image_paths[start_index:], start=start_index + 1):
        if not queue_has_capacity("frame_analysis_queue", len(frame_reports), queue_limits):
            queue_warnings.append(f"FRAME_ANALYSIS_QUEUE_FULL:{index}")
            continue
        captured = _capture_frame_state(
            image_path,
            profile_id=profile_id,
            image_source=IMAGE_SOURCE_GENERAL,
        )
        if captured.debug_capture_enabled:
            raw_buffer.retain(
                captured.frame.frame_id,
                {
                    "frame_id": captured.frame.frame_id,
                    "session_id": captured.frame.session_id,
                    "timestamp_utc": captured.frame.timestamp_utc,
                },
                estimated_bytes=max(1, captured.frame.image.width * captured.frame.image.height * 3),
                state=FrameBufferState.READABLE if _is_readable(captured) else FrameBufferState.RAW,
            )
        metrics.record_capture(captured.capture_timestamp)
        if _is_readable(captured):
            metrics.record_readable(captured.capture_timestamp)
        changed_row_ids = _changed_row_ids(captured.frame.frame_id, previous_signatures, captured.row_signatures)
        if changed_row_ids:
            metrics.record_useful(captured.capture_timestamp)
        temporal_windows.extend(
            temporal_grouper.add_frame(
                FrameObservation(
                    frame_id=captured.frame.frame_id,
                    timestamp=captured.capture_timestamp,
                    readability_score=_readability_score(captured),
                    row_signatures=dict(captured.row_signatures),
                )
            )
        )
        controller_state = controller.evaluate(
            capture_fps=metrics.capture_fps,
            readable_fps=metrics.readable_fps,
            useful_fps=metrics.useful_fps,
            frame_queue_depth=len(frame_reports),
            ocr_queue_depth=len(ocr_queue),
            motion_level=_estimate_change_motion(previous_signatures, captured.row_signatures),
            continuity_health="OK",
            cpu_load=float(_collect_runtime_pressure(buffer=session_buffer, ocr_queue=ocr_queue, ai_queue=ai_queue)["cpu_pressure"]),
            gpu_load=0.0,
            target_latency=0.5,
        )
        current_pressure = _collect_runtime_pressure(
            buffer=session_buffer,
            ocr_queue=ocr_queue,
            ai_queue=ai_queue,
        )
        last_memory_decision = memory_governor.evaluate(
            ram_used=session_buffer.total_bytes() + raw_buffer.total_bytes(),
            ram_limit=3 * 1024 * 1024 * 1024,
            capture_fps=metrics.capture_fps,
            retained_fps=metrics.readable_fps,
            extraction_rate=metrics.extraction_rate,
            raw_queue_depth=len(frame_reports),
            ocr_queue_depth=len(ocr_queue),
            ai_queue_depth=len(ai_queue),
            motion_rate=_estimate_change_motion(previous_signatures, captured.row_signatures),
            frame_uniqueness=_frame_uniqueness(previous_signatures, captured.row_signatures),
            readability=_readability_score(captured),
            continuity_anchors=1 if changed_row_ids else 0,
            unresolved_observations=len(changed_row_ids),
            cpu_load=float(current_pressure["cpu_pressure"]),
            gpu_load=0.0,
        )
        should_extract = (
            (index == start_index + 1 or (bool(changed_row_ids) and controller_state.should_extract))
            and last_memory_decision.action not in {MemoryAction.DEFER, MemoryAction.DROP}
        )
        if should_extract and not queue_has_capacity("ocr_queue", len(ocr_queue), queue_limits):
            queue_warnings.append(f"OCR_QUEUE_FULL:{captured.frame.frame_id}")
            should_extract = False
        report = _build_frame_report(
            image_path,
            profile_id=profile_id,
            capture_state=captured,
            image_source=IMAGE_SOURCE_GENERAL,
            changed_row_ids=changed_row_ids if should_extract else (),
        )
        if should_extract:
            ocr_queue.append(captured.frame.frame_id)
            metrics.record_extraction_event(
                captured.capture_timestamp,
                field_types=tuple(sorted({candidate.field_kind.value for candidate in report.ranked_candidates})),
            )
            last_candidate_timestamp = captured.capture_timestamp
            metrics.record_candidate(
                captured.capture_timestamp,
                count=len(report.ranked_candidates),
                frame_capture_timestamp=captured.capture_timestamp,
            )
            ocr_queue.pop()
        frame_reports.append(report)
        for item in report.retained_evidence:
            session_buffer.retain(item)
            if item.evidence_kind.value == "anchor":
                session_buffer.pin(item.crop_id)
            else:
                session_buffer.transition(item.crop_id, FrameBufferState.SELECTED)
        session_buffer.trim_evidence(current_pressure)
        released_from_windows = tuple(
            frame_id
            for window in temporal_windows
            for observation in window
            for frame_id in getattr(observation, "released_frame_ids", ())
        )
        if released_from_windows:
            raw_buffer.release_all_except({captured.frame.frame_id})
        _maybe_save_checkpoint(
            checkpoint_manager=checkpoint_manager,
            profile_id=profile_id,
            frame_reports=tuple(frame_reports),
            session_buffer=session_buffer,
            frame_index=index,
            scan_scope=ScanScope.CURRENT_PAGE if len(image_paths) <= 8 else ScanScope.FULL_INVENTORY,
            checkpoint_interval_frames=checkpoint_interval_frames,
        )
        previous_signatures = dict(captured.row_signatures)
    scan_scope = ScanScope.CURRENT_PAGE if len(image_paths) <= 8 else ScanScope.FULL_INVENTORY
    temporal_windows.extend(temporal_grouper.flush())
    report = _build_session_report(tuple(frame_reports), profile_id=profile_id, scan_scope=scan_scope)
    verified_count = sum(1 for item in report["assembled_records"] if item["state"] == "complete")
    if verified_count:
        final_timestamp = datetime.now(timezone.utc).timestamp()
        metrics.record_verified(
            final_timestamp,
            count=verified_count,
            frame_capture_timestamp=metrics.captured_timestamps[0] if metrics.captured_timestamps else None,
            candidate_produced_timestamp=last_candidate_timestamp,
        )
    session_buffer.trim_to_compact_provenance()
    _attach_throughput(
        report,
        metrics=metrics,
        temporal_windows=temporal_windows,
        queue_depth=len(ocr_queue) + len(ai_queue),
        buffer_bytes=session_buffer.total_bytes() + raw_buffer.total_bytes(),
        memory_decision=last_memory_decision,
    )
    if queue_warnings:
        report["queue_warnings"] = queue_warnings
    return report


def run_fixture_diagnostic(fixture: SessionFixture) -> dict[str, object]:
    return run_fixture_diagnostic_with_recovery(fixture)


def run_fixture_diagnostic_with_recovery(
    fixture: SessionFixture,
    *,
    resumed_session: ResumedSession | None = None,
    checkpoint_manager: CheckpointManager | None = None,
    checkpoint_interval_frames: int = 10,
) -> dict[str, object]:
    session_buffer = EvidenceBuffer()
    raw_buffer = ShortRawBuffer()
    ocr_queue: list[object] = []
    ai_queue: list[object] = []
    frame_reports = []
    metrics = RateMetrics()
    temporal_grouper = SlidingTemporalGrouper()
    memory_governor = MemoryGovernor()
    last_memory_decision = MemoryDecision(0, "NORMAL", MemoryAction.KEEP, 1.0, ("WITHIN_NORMAL_MEMORY_BOUNDS",))
    queue_limits = default_queue_limits()
    queue_warnings: list[str] = []
    start_index = resumed_session.next_frame_index if resumed_session is not None else 0
    for index, frame in enumerate(fixture.frames[start_index:], start=start_index + 1):
        if not queue_has_capacity("frame_analysis_queue", len(frame_reports), queue_limits):
            queue_warnings.append(f"FRAME_ANALYSIS_QUEUE_FULL:{index}")
            continue
        report = _build_frame_report(
            frame.image_path,
            profile_id=fixture.profile_id,
            frame_id=frame.frame_id,
            session_id=frame.session_id,
            timestamp_utc=frame.timestamp_utc,
            replay_mode=frame.replay_mode,
            ranked_candidates_override=frame.ranked_candidate_overrides,
            image_source=IMAGE_SOURCE_REPLAY_FIXTURE,
        )
        if report.frame.image.path:
            raw_buffer.retain(
                report.frame.frame_id,
                {"frame_id": report.frame.frame_id, "session_id": report.frame.session_id},
                estimated_bytes=max(1, report.frame.image.width * report.frame.image.height * 3),
                state=FrameBufferState.READABLE if report.quality.action.value != "drop" else FrameBufferState.RAW,
            )
        metrics.record_capture(datetime.now(timezone.utc).timestamp())
        if report.quality.action.value != "drop":
            metrics.record_readable(datetime.now(timezone.utc).timestamp())
        if report.ranked_candidates:
            metrics.record_useful(datetime.now(timezone.utc).timestamp())
            metrics.record_extraction_event(
                datetime.now(timezone.utc).timestamp(),
                field_types=tuple(sorted({candidate.field_kind.value for candidate in report.ranked_candidates})),
            )
            metrics.record_candidate(datetime.now(timezone.utc).timestamp(), count=len(report.ranked_candidates))
        temporal_grouper.add_frame(
            FrameObservation(
                frame_id=report.frame.frame_id,
                timestamp=datetime.now(timezone.utc).timestamp(),
                readability_score=max(0.0, float(report.quality.sharpness) - float(report.quality.motion_penalty)),
                row_signatures={index + 1: f"{report.frame.frame_id}:{index + 1}" for index, _ in enumerate(report.row_zones)},
            )
        )
        frame_reports.append(report)
        for item in report.retained_evidence:
            session_buffer.retain(item)
            if item.evidence_kind.value == "anchor":
                session_buffer.pin(item.crop_id)
            else:
                session_buffer.transition(item.crop_id, FrameBufferState.SELECTED)
        current_pressure = _collect_runtime_pressure(
            buffer=session_buffer,
            ocr_queue=ocr_queue,
            ai_queue=ai_queue,
        )
        last_memory_decision = memory_governor.evaluate(
            ram_used=session_buffer.total_bytes() + raw_buffer.total_bytes(),
            ram_limit=3 * 1024 * 1024 * 1024,
            capture_fps=metrics.capture_fps,
            retained_fps=metrics.readable_fps,
            extraction_rate=metrics.extraction_rate,
            raw_queue_depth=len(frame_reports),
            ocr_queue_depth=len(ocr_queue),
            ai_queue_depth=len(ai_queue),
            motion_rate=0.0,
            frame_uniqueness=1.0,
            readability=max(0.0, float(report.quality.sharpness) - float(report.quality.motion_penalty)),
            continuity_anchors=len(report.row_zones[:1]),
            unresolved_observations=len(report.ranked_candidates),
            cpu_load=float(current_pressure["cpu_pressure"]),
            gpu_load=0.0,
        )
        session_buffer.trim_evidence(current_pressure)
        _maybe_save_checkpoint(
            checkpoint_manager=checkpoint_manager,
            profile_id=fixture.profile_id,
            frame_reports=tuple(frame_reports),
            session_buffer=session_buffer,
            frame_index=index,
            scan_scope=fixture.scan_scope,
            checkpoint_interval_frames=checkpoint_interval_frames,
        )
    report = _build_session_report(
        tuple(frame_reports),
        profile_id=fixture.profile_id,
        scan_scope=fixture.scan_scope,
    )
    verified_count = sum(1 for item in report["assembled_records"] if item["state"] == "complete")
    if verified_count:
        metrics.record_verified(datetime.now(timezone.utc).timestamp(), count=verified_count)
    session_buffer.trim_to_compact_provenance()
    _attach_throughput(
        report,
        metrics=metrics,
        temporal_windows=list(temporal_grouper.flush()),
        queue_depth=len(ocr_queue) + len(ai_queue),
        buffer_bytes=session_buffer.total_bytes() + raw_buffer.total_bytes(),
        memory_decision=last_memory_decision,
    )
    if queue_warnings:
        report["queue_warnings"] = queue_warnings
    validate_expected_overlaps(fixture, report)
    return report


def _build_session_report(
    frame_reports: tuple[DiagnosticReport, ...],
    *,
    profile_id: str,
    scan_scope: ScanScope,
    allow_recorded_slot_reuse: bool = False,
) -> SessionDiagnosticReport:
    scan_timestamp = (
        frame_reports[0].frame.timestamp_utc
        if frame_reports
        else datetime.now(timezone.utc).isoformat()
    )
    profile_version = ProfileVersion.for_scan(profile_id, scan_timestamp=scan_timestamp)
    frame_order = {
        report.frame.frame_id: index
        for index, report in enumerate(frame_reports)
    }
    ranked_candidates = tuple(
        candidate
        for report in frame_reports
        for candidate in report.ranked_candidates
    )
    temporal_aggregates = merge_ranked_candidates(ranked_candidates, allow_slot_reuse=allow_recorded_slot_reuse)
    try:
        definition_engine = InventoryDefinitionEngine(load_profile(profile_id))
    except (FileNotFoundError, OSError, ValueError, KeyError):
        definition_engine = None
    assembled_records = assemble_candidate_records(
        temporal_aggregates,
        profile_id=profile_id,
        profile_version=profile_version.profile_version,
        scan_timestamp=profile_version.scan_timestamp,
        definition_engine=definition_engine,
        temporal_identity_aware=allow_recorded_slot_reuse,
    )
    candidate_inventory, organization_summary, reconstruction_results, allocation_results = _run_semantic_allocation(
        assembled_records,
        ranked_candidates=ranked_candidates,
        profile_id=profile_id,
    )
    assembled_records = merge_allocation_fields(assembled_records, allocation_results)
    assembled_records = apply_semantic_provenance(
        assembled_records,
        reconstruction_results=reconstruction_results,
        allocation_results=allocation_results,
    )
    continuity_records = build_continuity_records(
        assembled_records,
        profile_id=profile_id,
        frame_order=frame_order,
    )
    continuity_records, frame_overlaps, overlap_count, overlap_confidence, continuity_summary = analyze_frame_overlaps(
        continuity_records,
        frame_order=frame_order,
    )
    assembled_records = apply_overlap_provenance(assembled_records, frame_overlaps)
    assembled_records = _apply_field_provenance(assembled_records, frame_reports)
    correctness = CorrectnessEngine().evaluate(
        ranked_candidates=ranked_candidates,
        temporal_aggregates=temporal_aggregates,
        assembled_records=assembled_records,
        continuity_records=continuity_records,
        profile_id=profile_id,
    )
    assembled_records = _apply_truth_progression(
        assembled_records,
        continuity_records=continuity_records,
        correctness=correctness,
    )
    scan_integrity = build_scan_integrity_report(continuity_records, scan_scope=scan_scope)
    session_report = SessionDiagnosticReport(
        profile_id=profile_id,
        profile_version=profile_version.as_dict(),
        frame_reports=frame_reports,
        temporal_aggregates=temporal_aggregates,
        assembled_records=assembled_records,
        continuity_records=continuity_records,
        scan_integrity=scan_integrity,
        frame_overlaps=frame_overlaps,
        overlap_count=overlap_count,
        overlap_confidence=overlap_confidence,
        continuity_summary=continuity_summary,
    )
    payload = session_report.as_dict()
    payload["motion_level"] = estimate_motion_level(frame_overlaps)
    payload["continuity_health"] = continuity_health(continuity_records)
    payload["correctness"] = correctness
    payload["escalation_chain"] = list(correctness.get("escalation_chain", []))
    payload["screen_summary"] = _screen_summary(frame_reports)
    payload["recognition_mode"] = _recognition_mode_summary(frame_reports)
    payload["candidate_inventory"] = [record.as_dict() for record in candidate_inventory]
    payload["organization_summary"] = organization_summary
    for index, record in enumerate(payload.get("assembled_records", [])):
        provenance = assembled_records[index].overlap_provenance
        record["reconstruction_provenance"] = provenance.get("reconstruction_provenance", {})
        record["allocation_provenance"] = provenance.get("allocation_provenance", {})
        record["record_class"] = record["allocation_provenance"].get("record_class", "UNKNOWN")
    if any(report.screen_class == ScreenClass.UNKNOWN.value for report in frame_reports):
        payload["hold_reason"] = "UNKNOWN_SCREEN"
    return payload


def _build_frame_report(
    image_path: Path,
    *,
    profile_id: str,
    frame_id: str | None = None,
    session_id: str | None = None,
    timestamp_utc: str | None = None,
    replay_mode: ReplayFrameMode = ReplayFrameMode.LIVE_OCR,
    ranked_candidates_override=(),
    capture_state: _CapturedFrameState | None = None,
    changed_row_ids: tuple[str, ...] | set[str] | None = None,
    row_identity_epoch: SelectedRowIdentityEpoch | None = None,
    scrolling: bool = False,
    image_source: str = IMAGE_SOURCE_GENERAL,
) -> DiagnosticReport:
    captured = capture_state or _capture_frame_state(
        image_path,
        profile_id=profile_id,
        frame_id=frame_id,
        session_id=session_id,
        timestamp_utc=timestamp_utc,
        image_source=image_source,
    )
    frame = captured.frame
    ocr_engine = captured.ocr_engine
    quality = captured.quality
    row_zones = captured.row_zones
    preprocessed_regions = captured.preprocessed_regions
    selected_rows = row_zones
    if changed_row_ids is not None:
        changed = set(changed_row_ids)
        selected_rows = tuple(zone for zone in row_zones if zone.row_id in changed)
    prepared_crops = prepare_row_field_crops(image_path, selected_rows, profile_id=profile_id) if captured.screen_classification.screen_class is ScreenClass.INVENTORY else ()
    selected_detail_correlation: dict[str, object] = {}
    if captured.screen_classification.screen_class is not ScreenClass.INVENTORY:
        ocr_attempts = ()
        field_candidates = ()
        ranked_candidates = ()
        recognition_mode = "Offline"
    elif ranked_candidates_override:
        ocr_attempts = ()
        field_candidates = ()
        ranked_candidates = tuple(ranked_candidates_override)
        replay_mode = ReplayFrameMode.RANKED_OVERRIDE
        recognition_mode = "Classic-Only"
    else:
        recognition = RecognitionOrchestrator().run(
            image_path=image_path,
            prepared_crops=prepared_crops,
            profile_id=profile_id,
            settings=load_settings(),
            contract=_recognition_contract(profile_id),
            quality_metrics=quality,
            profile_version=ProfileVersion.for_scan(profile_id, scan_timestamp=frame.timestamp_utc).profile_version,
        )
        ocr_attempts = recognition.ocr_attempts
        field_candidates = recognition.field_candidates
        ranked_candidates = rank_field_candidates(field_candidates, profile_id=profile_id)
        recognition_mode = recognition.recognition_mode_used
        if not _has_credible_item_name_candidates(ranked_candidates):
            row_zones = ()
            preprocessed_regions = ()
            prepared_crops = ()
            ocr_attempts = ()
            field_candidates = ()
            ranked_candidates = ()
            recognition_mode = "Offline"
            screen_classification = ScreenClassification(ScreenClass.UNKNOWN, "NO_CREDIBLE_ITEM_NAME_EVIDENCE")
        else:
            screen_classification = captured.screen_classification
            (
                prepared_crops,
                ocr_attempts,
                field_candidates,
                ranked_candidates,
                selected_detail_correlation,
            ) = _augment_with_selected_detail_panel(
                image_path,
                profile_id=profile_id,
                captured=captured,
                selected_rows=selected_rows,
                prepared_crops=prepared_crops,
                ocr_attempts=ocr_attempts,
                field_candidates=field_candidates,
                ranked_candidates=ranked_candidates,
                quality=quality,
                timestamp_utc=frame.timestamp_utc,
                row_identity_epoch=row_identity_epoch,
                scrolling=scrolling,
            )
    if captured.screen_classification.screen_class is not ScreenClass.INVENTORY or ranked_candidates_override:
        screen_classification = captured.screen_classification
    evidence = build_representative_evidence(frame, row_zones)
    buffer = EvidenceBuffer()
    for item in evidence:
        buffer.retain(item)

    return DiagnosticReport(
        frame=frame,
        replay_mode=replay_mode,
        ocr_engine=ocr_engine,
        quality=quality,
        row_zones=row_zones,
        preprocessed_regions=preprocessed_regions,
        prepared_crops=prepared_crops,
        ocr_attempts=ocr_attempts,
        field_candidates=field_candidates,
        ranked_candidates=ranked_candidates,
        retained_evidence=buffer.items(),
        screen_class=screen_classification.screen_class.value,
        screen_reason=screen_classification.reason,
        hold_reason=screen_classification.hold_reason,
        recognition_mode=recognition_mode,
        selected_detail_correlation=selected_detail_correlation,
    )


def _augment_with_selected_detail_panel(
    image_path: Path,
    *,
    profile_id: str,
    captured: "_CapturedFrameState",
    selected_rows: tuple[object, ...],
    prepared_crops: tuple[object, ...],
    ocr_attempts: tuple[object, ...],
    field_candidates: tuple[object, ...],
    ranked_candidates: tuple[object, ...],
    quality: object,
    timestamp_utc: str,
    row_identity_epoch: SelectedRowIdentityEpoch | None = None,
    scrolling: bool = False,
) -> tuple[tuple[object, ...], tuple[object, ...], tuple[object, ...], tuple[object, ...], dict[str, object]]:
    correlation = _correlate_selected_row_detail_panel(
        image_path,
        captured=captured,
        selected_rows=selected_rows,
        prepared_crops=prepared_crops,
        ocr_attempts=ocr_attempts,
    )
    if row_identity_epoch is not None:
        correlation = row_identity_epoch.observe(
            correlation,
            frame_id=captured.frame.frame_id,
            capture_timestamp=captured.capture_timestamp,
            scrolling=scrolling,
        )
    if not correlation.get("correlated"):
        return prepared_crops, ocr_attempts, field_candidates, ranked_candidates, correlation

    selected_row_id = str(correlation.get("selected_row_id", ""))
    selected_row = next(
        (zone for zone in getattr(captured, "row_zones", ()) if getattr(zone, "row_id", "") == selected_row_id),
        None,
    )
    if selected_row is None:
        return prepared_crops, ocr_attempts, field_candidates, ranked_candidates, correlation

    detail_crops = prepare_selected_detail_field_crops(
        image_path,
        captured.frame.inventory_region,
        selected_row_id=str(getattr(selected_row, "row_id", "")),
        profile_id=profile_id,
        layout_name=str(correlation.get("layout_name", "")) or None,
    )
    if not detail_crops:
        correlation["hold_reason"] = "DETAIL_PANEL_PROFILE_REGIONS_MISSING"
        correlation["correlated"] = False
        return prepared_crops, ocr_attempts, field_candidates, ranked_candidates, correlation

    settings = load_settings()
    detail_recognition = RecognitionOrchestrator().run(
        image_path=image_path,
        prepared_crops=detail_crops,
        profile_id=profile_id,
        settings=settings,
        contract=_recognition_contract(profile_id),
        quality_metrics=quality,
        profile_version=ProfileVersion.for_scan(profile_id, scan_timestamp=timestamp_utc).profile_version,
    )
    detail_ranked = rank_field_candidates(detail_recognition.field_candidates, profile_id=profile_id)
    title_crop_ids = {
        crop.crop_id
        for crop in detail_crops
        if getattr(crop.field_kind, "value", "") == "item_name"
    }
    detail_ranked = tuple(
        candidate
        for candidate in detail_ranked
        if getattr(candidate, "source_crop_id", "") not in title_crop_ids
    )
    correlation["detail_regions"] = {
        crop.crop_id: dict(
            field_kind=crop.field_kind.value,
            source_region=crop.source_region.as_dict(),
        )
        for crop in detail_crops
    }
    return (
        tuple(prepared_crops) + tuple(detail_crops),
        tuple(ocr_attempts) + tuple(detail_recognition.ocr_attempts),
        tuple(field_candidates) + tuple(detail_recognition.field_candidates),
        tuple(ranked_candidates) + tuple(detail_ranked),
        correlation,
    )


def _apply_selected_detail_temporal_guard(
    report: DiagnosticReport,
    *,
    guard: SelectedDetailTemporalGuard,
    capture_timestamp: float,
    scrolling: bool,
) -> DiagnosticReport:
    correlation = dict(getattr(report, "selected_detail_correlation", {}))
    if not correlation:
        return report
    guarded = guard.observe(
        correlation,
        frame_id=report.frame.frame_id,
        capture_timestamp=capture_timestamp,
        scrolling=scrolling,
    )
    if guarded.get("correlated"):
        return replace(report, selected_detail_correlation=guarded)

    # A frame-local match can still be stale immediately after selection changes.
    # Remove detail crops and their derivatives until the temporal guard releases them.
    detail_crop_ids = {
        str(crop.crop_id)
        for crop in report.prepared_crops
        if str(crop.crop_id).startswith("detail-")
    }
    if not detail_crop_ids:
        return replace(report, selected_detail_correlation=guarded)
    return replace(
        report,
        prepared_crops=tuple(crop for crop in report.prepared_crops if str(crop.crop_id) not in detail_crop_ids),
        ocr_attempts=tuple(attempt for attempt in report.ocr_attempts if str(attempt.crop_id) not in detail_crop_ids),
        field_candidates=tuple(candidate for candidate in report.field_candidates if _candidate_crop_id(candidate) not in detail_crop_ids),
        ranked_candidates=tuple(candidate for candidate in report.ranked_candidates if _candidate_crop_id(candidate) not in detail_crop_ids),
        selected_detail_correlation=guarded,
    )


def _candidate_crop_id(candidate: object) -> str:
    return str(getattr(candidate, "source_crop_id", getattr(candidate, "crop_id", "")))


def _correlate_selected_row_detail_panel(
    image_path: Path,
    *,
    captured: "_CapturedFrameState",
    selected_rows: tuple[object, ...],
    prepared_crops: tuple[object, ...],
    ocr_attempts: tuple[object, ...],
) -> dict[str, object]:
    row_zones = tuple(getattr(captured, "row_zones", ()))
    if not row_zones:
        return {"correlated": False, "hold_reason": "NO_ROW_ZONES"}

    selected_row_id_set = {str(getattr(zone, "row_id", "")) for zone in selected_rows}
    highlight_profiles = _selected_row_highlight_scores(image_path, row_zones)
    if not highlight_profiles:
        return {"correlated": False, "hold_reason": "NO_HIGHLIGHT_SCORES"}
    layouts = load_selected_detail_panel_layouts(captured.frame.profile_id)
    if not layouts:
        return {"correlated": False, "hold_reason": "DETAIL_TITLE_REGION_MISSING", "highlight_scores": highlight_profiles}
    evaluations = [
        _evaluate_selected_detail_layout(
            image_path,
            captured=captured,
            row_zones=row_zones,
            prepared_crops=prepared_crops,
            ocr_attempts=ocr_attempts,
            highlight_profiles=highlight_profiles,
            selected_row_id_set=selected_row_id_set,
            layout=layout,
        )
        for layout in layouts
    ]
    passed = [evaluation for evaluation in evaluations if evaluation.get("correlated")]
    if passed:
        passed.sort(
            key=lambda item: (
                float(item.get("best_similarity", 0.0)),
                float(dict(item.get("detail_title_ocr", {})).get("confidence", 0.0)),
                int(item.get("best_score", 0)),
            ),
            reverse=True,
        )
        return passed[0]

    evaluations.sort(
        key=lambda item: (
            float(item.get("best_similarity", 0.0)),
            float(dict(item.get("detail_title_ocr", {})).get("confidence", 0.0)),
            int(item.get("best_score", 0)),
        ),
        reverse=True,
    )
    best_failed = dict(evaluations[0]) if evaluations else {"correlated": False, "hold_reason": "SELECTED_ROW_CORRELATION_NOT_PROVEN"}
    best_failed["layout_candidates"] = [
        {
            "layout_name": str(item.get("layout_name", "")),
            "detail_title_ocr": dict(item.get("detail_title_ocr", {})),
            "selected_row_id": str(item.get("selected_row_id", "")),
            "hold_reason": str(item.get("hold_reason", "")),
            "best_similarity": float(item.get("best_similarity", 0.0)),
        }
        for item in evaluations
    ]
    return best_failed


def _evaluate_selected_detail_layout(
    image_path: Path,
    *,
    captured: "_CapturedFrameState",
    row_zones: tuple[object, ...],
    prepared_crops: tuple[object, ...],
    ocr_attempts: tuple[object, ...],
    highlight_profiles: dict[str, dict[str, int | bool]],
    selected_row_id_set: set[str],
    layout: dict[str, object],
) -> dict[str, object]:
    layout_name = str(layout.get("name", "") or "default")
    detail_title_crops = prepare_selected_detail_field_crops(
        image_path,
        captured.frame.inventory_region,
        selected_row_id=str(getattr(row_zones[0], "row_id", "")),
        profile_id=captured.frame.profile_id,
        layout_name=layout_name,
    )
    title_only_crops = tuple(crop for crop in detail_title_crops if getattr(crop.field_kind, "value", "") == "item_name")
    if not title_only_crops:
        return {
            "layout_name": layout_name,
            "correlated": False,
            "hold_reason": "DETAIL_TITLE_REGION_MISSING",
            "highlight_scores": highlight_profiles,
            "detail_title_ocr": {},
            "row_matches": [],
            "best_similarity": 0.0,
        }
    title_attempts = run_ocr_attempts(image_path, title_only_crops, max_attempts=len(title_only_crops))
    detail_title_attempt = _best_successful_attempt(title_attempts)
    detail_title = _identity_text(getattr(detail_title_attempt, "normalized_text", ""))
    row_matches: list[dict[str, object]] = []
    for zone in row_zones:
        row_id = str(getattr(zone, "row_id", ""))
        row_name_attempt = _best_attempt_for_row_field(
            row_id=row_id,
            field_kind="item_name",
            prepared_crops=prepared_crops,
            ocr_attempts=ocr_attempts,
        )
        row_name_crop = next(
            (
                crop
                for crop in prepared_crops
                if str(getattr(crop, "row_id", "")) == row_id
                and getattr(getattr(crop, "field_kind", None), "value", "") == "item_name"
                and str(getattr(crop, "crop_id", "")) == str(getattr(row_name_attempt, "crop_id", ""))
            ),
            None,
        )
        row_title = _identity_text(getattr(row_name_attempt, "normalized_text", ""))
        similarity = _text_similarity(row_title, detail_title)
        highlight = highlight_profiles.get(row_id, {"combined": 0, "balanced": False, "top": 0, "bottom": 0, "right": 0})
        row_matches.append(
            {
                "row_id": row_id,
                "row_name_ocr": {
                    "raw_text": str(getattr(row_name_attempt, "raw_text", "")),
                    "normalized_text": str(getattr(row_name_attempt, "normalized_text", "")),
                    "confidence": float(getattr(row_name_attempt, "confidence", 0.0)),
                    "crop_bounds": getattr(getattr(row_name_crop, "source_region", None), "as_dict", lambda: {})(),
                    "preprocess_variant": getattr(getattr(row_name_crop, "variant", None), "value", ""),
                },
                "similarity": similarity,
                "highlight": highlight,
            }
        )
    row_matches.sort(
        key=lambda item: (
            bool(item["highlight"].get("horizontal_border")),
            int(item["highlight"].get("horizontal_score", 0)),
            int(item["highlight"].get("left", 0)) >= 40,
            int(item["highlight"].get("left", 0)),
            bool(item["highlight"].get("balanced")),
            float(item["similarity"]),
            int(item["highlight"].get("combined", 0)),
            float(item["row_name_ocr"].get("confidence", 0.0)),
        ),
        reverse=True,
    )
    best_match = row_matches[0] if row_matches else None
    second_match = row_matches[1] if len(row_matches) > 1 else None
    best_row_id = str(best_match.get("row_id", "")) if best_match else ""
    best_highlight = dict(best_match.get("highlight", {})) if best_match else {}
    best_score = int(best_highlight.get("combined", 0))
    second_best_score = int(dict(second_match.get("highlight", {})).get("combined", 0)) if second_match else 0
    best_left = int(best_highlight.get("left", 0))
    best_horizontal = int(best_highlight.get("horizontal_score", 0))
    second_best_horizontal = max((int(dict(item.get("highlight", {})).get("horizontal_score", 0)) for item in row_matches[1:]), default=0)
    second_best_left = max((int(dict(item.get("highlight", {})).get("left", 0)) for item in row_matches[1:]), default=0)
    similarity_threshold = 0.72
    similarity_margin = 0.08
    similarity_ok = bool(best_match and float(best_match.get("similarity", 0.0)) >= similarity_threshold)
    left_edge_unique = best_left >= max(40, second_best_left + 20)
    horizontal_border_unique = bool(best_highlight.get("horizontal_border")) and best_horizontal >= max(80, second_best_horizontal + 20)
    dominant_outline = best_score >= max(60, second_best_score + 40)
    distinct_match = bool(
        best_match and (
            second_match is None
            or float(best_match.get("similarity", 0.0)) >= float(second_match.get("similarity", 0.0)) + similarity_margin
            or left_edge_unique
            or horizontal_border_unique
        )
    )
    max_row_slot = max((_row_slot_from_row_id(str(getattr(zone, "row_id", ""))) for zone in row_zones), default=0)
    highlight_ok = bool(
        best_match and (
            int(best_highlight.get("left", 0)) >= 40
            or bool(best_highlight.get("horizontal_border"))
            or bool(best_highlight.get("balanced"))
            or (int(best_highlight.get("bottom", 0)) >= 60 and _row_slot_from_row_id(best_row_id) == max_row_slot)
            or dominant_outline
        )
    )
    title_match = bool(best_match and detail_title)
    selected_row = next((zone for zone in row_zones if getattr(zone, "row_id", "") == best_row_id), None)
    detail_title_payload = {
        "raw_text": str(getattr(detail_title_attempt, "raw_text", "")),
        "normalized_text": str(getattr(detail_title_attempt, "normalized_text", "")),
        "confidence": float(getattr(detail_title_attempt, "confidence", 0.0)),
    }
    if selected_row is None or not (similarity_ok and distinct_match and highlight_ok):
        return {
            "layout_name": layout_name,
            "correlated": False,
            "hold_reason": "SELECTED_ROW_CORRELATION_NOT_PROVEN",
            "highlight_scores": highlight_profiles,
            "detail_title_ocr": detail_title_payload,
            "row_matches": row_matches,
            "selected_row_id": best_row_id,
            "best_score": best_score,
            "second_best_score": second_best_score,
            "best_similarity": float(best_match.get("similarity", 0.0)) if best_match else 0.0,
            "row_name_ocr": dict(best_match.get("row_name_ocr", {})) if best_match else {},
            "correlation_guards": {
                "selected_row_highlight_proven": highlight_ok,
                "row_name_detail_title_similarity_threshold": similarity_threshold,
                "row_name_detail_title_similarity_ok": similarity_ok,
                "row_name_detail_title_unique_best": distinct_match,
            },
        }
    if selected_row_id_set and best_row_id not in selected_row_id_set:
        return {
            "layout_name": layout_name,
            "correlated": False,
            "hold_reason": "SELECTED_ROW_NOT_IN_CHANGED_SET",
            "highlight_scores": highlight_profiles,
            "detail_title_ocr": detail_title_payload,
            "row_matches": row_matches,
            "selected_row_id": best_row_id,
            "best_score": best_score,
            "second_best_score": second_best_score,
            "best_similarity": float(best_match.get("similarity", 0.0)) if best_match else 0.0,
            "row_name_ocr": dict(best_match.get("row_name_ocr", {})) if best_match else {},
            "correlation_guards": {
                "selected_row_highlight_proven": highlight_ok,
                "row_name_detail_title_similarity_threshold": similarity_threshold,
                "row_name_detail_title_similarity_ok": similarity_ok,
                "row_name_detail_title_unique_best": distinct_match,
            },
        }
    return {
        "layout_name": layout_name,
        "correlated": title_match,
        "hold_reason": "" if title_match else "DETAIL_TITLE_ROW_NAME_MISMATCH",
        "selected_row_id": best_row_id,
        "highlight_scores": highlight_profiles,
        "best_score": best_score,
        "second_best_score": second_best_score,
        "best_similarity": float(best_match.get("similarity", 0.0)) if best_match else 0.0,
        "row_name_ocr": dict(best_match.get("row_name_ocr", {})) if best_match else {},
        "detail_title_ocr": detail_title_payload,
        "row_matches": row_matches,
        "correlation_guards": {
            "selected_row_highlight_balanced_border": highlight_ok,
            "selected_row_left_edge_unique": left_edge_unique,
            "selected_row_horizontal_border_unique": horizontal_border_unique,
            "selected_row_dominant_outline": dominant_outline,
            "row_name_detail_title_similarity_threshold": similarity_threshold,
            "row_name_detail_title_similarity_ok": similarity_ok,
            "row_name_detail_title_similarity_margin": similarity_margin,
            "row_name_detail_title_unique_best": distinct_match,
        },
    }


def _selected_row_highlight_scores(image_path: Path, row_zones: tuple[object, ...]) -> dict[str, dict[str, int | bool]]:
    from PIL import Image

    if not row_zones:
        return {}
    scores: dict[str, dict[str, int | bool]] = {}
    with Image.open(image_path) as image:
        rgb = image.convert("RGB")
        for zone in row_zones:
            row_bounds = getattr(zone, "row_bounds", None)
            if row_bounds is None or getattr(row_bounds, "height", 0) <= 0 or getattr(row_bounds, "width", 0) <= 0:
                continue
            strip_height = min(6, max(1, int(row_bounds.height * 0.12)))
            left_band_width = min(40, max(12, int(row_bounds.width * 0.045)))
            corner_width = min(72, max(18, int(row_bounds.width * 0.08)))
            safe_bottom = max(row_bounds.y2 - strip_height, row_bounds.y1)
            safe_top = min(row_bounds.y1 + strip_height, row_bounds.y2)
            safe_left_band = min(row_bounds.x1 + left_band_width, row_bounds.x2)
            safe_corner = min(row_bounds.x1 + corner_width, row_bounds.x2)
            bottom_strip = rgb.crop((row_bounds.x1, safe_bottom, row_bounds.x2, row_bounds.y2))
            top_strip = rgb.crop((row_bounds.x1, row_bounds.y1, row_bounds.x2, safe_top))
            right_strip = rgb.crop((max(row_bounds.x2 - 4, row_bounds.x1), row_bounds.y1, row_bounds.x2, row_bounds.y2))
            left_strip = rgb.crop((row_bounds.x1, row_bounds.y1, safe_left_band, row_bounds.y2))
            top_left_strip = rgb.crop((row_bounds.x1, row_bounds.y1, safe_corner, safe_top))
            bottom_left_strip = rgb.crop((row_bounds.x1, safe_bottom, safe_corner, row_bounds.y2))
            top_score = _count_orange_pixels(list(top_strip.getdata()))
            bottom_score = _count_orange_pixels(list(bottom_strip.getdata()))
            right_score = _count_orange_pixels(list(right_strip.getdata()))
            left_score = _count_orange_pixels(list(left_strip.getdata()))
            top_left_score = _count_orange_pixels(list(top_left_strip.getdata()))
            bottom_left_score = _count_orange_pixels(list(bottom_left_strip.getdata()))
            horizontal_score = top_score + bottom_score
            edge_score = (left_score * 3) + (top_left_score * 2) + (bottom_left_score * 3)
            scores[str(getattr(zone, "row_id", ""))] = {
                "top": top_score,
                "bottom": bottom_score,
                "left": left_score,
                "right": right_score,
                "top_left": top_left_score,
                "bottom_left": bottom_left_score,
                "horizontal_score": horizontal_score,
                "horizontal_border": top_score >= 60 and bottom_score >= 60,
                "combined": edge_score,
                "balanced": left_score >= 60 or (top_left_score >= 10 and bottom_left_score >= 10),
            }
    return scores


def _count_orange_pixels(pixels: object) -> int:
    total = 0
    for red, green, blue in pixels:
        if red >= 170 and green >= 90 and blue <= 120 and (red - blue) >= 70 and (red - green) >= 25:
            total += 1
    return total


def _best_attempt_for_row_field(
    *,
    row_id: str,
    field_kind: str,
    prepared_crops: tuple[object, ...],
    ocr_attempts: tuple[object, ...],
):
    crop_ids = {
        getattr(crop, "crop_id", "")
        for crop in prepared_crops
        if getattr(crop, "row_id", "") == row_id and getattr(getattr(crop, "field_kind", None), "value", "") == field_kind
    }
    attempts = tuple(attempt for attempt in ocr_attempts if getattr(attempt, "crop_id", "") in crop_ids)
    return _best_successful_attempt(attempts)


def _best_successful_attempt(attempts: tuple[object, ...]):
    ranked = [
        attempt
        for attempt in attempts
        if str(getattr(getattr(attempt, "status", None), "value", "")) == "ok"
        and str(getattr(attempt, "normalized_text", "")).strip()
    ]
    if not ranked:
        return None
    ranked.sort(key=lambda attempt: (float(getattr(attempt, "confidence", 0.0)), str(getattr(attempt, "normalized_text", ""))), reverse=True)
    return ranked[0]


def _identity_text(value: str) -> str:
    return " ".join(str(value).split()).strip().lower()


def _text_similarity(left: str, right: str) -> float:
    if not left or not right:
        return 0.0
    return round(SequenceMatcher(a=left, b=right).ratio(), 3)


def _capture_frame_state(
    image_path: Path,
    *,
    profile_id: str,
    frame_id: str | None = None,
    session_id: str | None = None,
    timestamp_utc: str | None = None,
    image_source: str = IMAGE_SOURCE_GENERAL,
) -> _CapturedFrameState:
    width, height = _load_image_size(image_path, image_source=image_source)
    privacy_policy = PrivacyPolicy()
    capture_frame = WindowsGraphicsCapture().capture(
        target_window_handle=1,
        foreground_window_handle=1,
        target_visible=True,
        privacy_policy=privacy_policy,
    )
    inventory_region, detector_name, expected_rows = _resolve_inventory_layout(
        image_path,
        profile_id=profile_id,
        image_width=width,
        image_height=height,
        image_source=image_source,
    )
    frame = FrameRecord(
        frame_id=frame_id or uuid4().hex[:12],
        session_id=session_id or uuid4().hex[:12],
        profile_id=profile_id,
        timestamp_utc=timestamp_utc or datetime.now(timezone.utc).isoformat(),
        image=FrameImage(path=str(image_path.resolve()), width=width, height=height),
        inventory_region=inventory_region,
        detector_name=detector_name,
    )
    # Replay fixtures encode their inventory contract as structured fixture data,
    # not as live screen pixels. Never use this compatibility path for capture.
    screen_classification = (
        ScreenClassification(ScreenClass.INVENTORY, "REPLAY_FIXTURE_LAYOUT")
        if image_source == IMAGE_SOURCE_REPLAY_FIXTURE
        else ScreenClassifier().classify(frame)
    )
    quality = assess_frame_quality(frame)
    row_zones = (
        segment_inventory_rows(frame, max_rows=expected_rows)
        if screen_classification.screen_class is ScreenClass.INVENTORY
        else ()
    )
    preprocessed_regions = preprocess_inventory_region(image_path, frame.inventory_region) if screen_classification.screen_class is ScreenClass.INVENTORY else ()
    row_signatures = _row_signatures(image_path, row_zones, image_source=image_source) if row_zones else {}
    return _CapturedFrameState(
        frame=frame,
        ocr_engine=get_ocr_engine_summary(),
        quality=quality,
        row_zones=row_zones,
        preprocessed_regions=preprocessed_regions,
        capture_timestamp=datetime.now(timezone.utc).timestamp(),
        row_signatures=row_signatures,
        screen_classification=screen_classification,
        debug_capture_enabled=capture_frame.debug_capture_enabled,
    )


def _resolve_inventory_layout(
    image_path: Path,
    *,
    profile_id: str,
    image_width: int,
    image_height: int,
    image_source: str,
) -> tuple[object, str, int]:
    try:
        profile = load_profile(profile_id)
    except OSError:
        profile = create_default_template()
        profile.profile_id = profile_id
    screen = next(
        (
            entry
            for entry in profile.screens
            if str(entry.get("screen_class") or "").strip().lower() == "inventory"
        ),
        profile.screens[0] if profile.screens else {},
    )
    expected_rows = max(1, int(screen.get("rows", 8) or 8))
    preferred_region = _scale_profile_roi(screen.get("roi"), image_width=image_width, image_height=image_height)
    if image_source in {IMAGE_SOURCE_LIVE_CAPTURE, IMAGE_SOURCE_RECORDED_CAPTURE} and preferred_region is not None:
        return preferred_region, "profile_roi_projection", expected_rows
    detected_region, detector_name = detect_inventory_region(image_path)
    return detected_region, detector_name, expected_rows


def _scale_profile_roi(
    raw_roi: object,
    *,
    image_width: int,
    image_height: int,
) -> Rect | None:
    if not isinstance(raw_roi, dict):
        return None
    try:
        x1 = float(raw_roi.get("x1", 0))
        y1 = float(raw_roi.get("y1", 0))
        x2 = float(raw_roi.get("x2", 0))
        y2 = float(raw_roi.get("y2", 0))
    except (TypeError, ValueError):
        return None
    if x2 <= x1 or y2 <= y1:
        return None

    if max(x1, y1, x2, y2) <= 1.0:
        scaled = (
            int(round(x1 * image_width)),
            int(round(y1 * image_height)),
            int(round(x2 * image_width)),
            int(round(y2 * image_height)),
        )
    else:
        scale_x = image_width / 1920.0
        scale_y = image_height / 1080.0
        scaled = (
            int(round(x1 * scale_x)),
            int(round(y1 * scale_y)),
            int(round(x2 * scale_x)),
            int(round(y2 * scale_y)),
        )

    region = Rect(
        x1=max(0, min(image_width, scaled[0])),
        y1=max(0, min(image_height, scaled[1])),
        x2=max(0, min(image_width, scaled[2])),
        y2=max(0, min(image_height, scaled[3])),
    )
    if region.x2 <= region.x1 or region.y2 <= region.y1:
        return None
    return region


def _collect_runtime_pressure(
    *,
    buffer: EvidenceBuffer,
    ocr_queue: list[object],
    ai_queue: list[object],
) -> dict[str, float | int]:
    try:
        import psutil  # type: ignore
    except ImportError:
        LOGGER.exception("psutil runtime pressure collection is unavailable; falling back to zero pressure.")
        ram_pressure = 0.0
        cpu_pressure = 0.0
    else:
        ram_pressure = float(psutil.virtual_memory().percent) / 100.0
        cpu_pressure = float(psutil.cpu_percent(interval=None)) / 100.0
    queue_depth = len(ocr_queue) + len(ai_queue)
    diagnostics = buffer.diagnostics()
    del diagnostics
    max_items = max(1, buffer.max_items)
    buffer_occupancy = min(1.0, len(buffer.items()) / max_items)
    return {
        "ram_pressure": ram_pressure,
        "cpu_pressure": cpu_pressure,
        "queue_depth": queue_depth,
        "buffer_occupancy": buffer_occupancy,
    }


def _maybe_save_checkpoint(
    *,
    checkpoint_manager: CheckpointManager | None,
    profile_id: str,
    frame_reports: tuple[DiagnosticReport, ...],
    session_buffer: EvidenceBuffer,
    frame_index: int,
    scan_scope: ScanScope,
    checkpoint_interval_frames: int,
) -> None:
    if checkpoint_manager is None:
        return
    if frame_index % checkpoint_interval_frames != 0:
        return
    report = _build_session_report(frame_reports, profile_id=profile_id, scan_scope=scan_scope)
    state = checkpoint_manager.build_session_state(
        report=report,
        buffer_metadata=session_buffer.diagnostics(),
        profile_version=str(report.get("profile_version", {}).get("profile_version") or "1"),
    )
    checkpoint_path = checkpoint_manager.checkpoint_path_for_session(state.session_id)
    checkpoint_manager.save_checkpoint(state, checkpoint_path)


def _apply_truth_progression(
    records: tuple[object, ...],
    *,
    continuity_records: tuple[object, ...],
    correctness: dict[str, object],
) -> tuple[object, ...]:
    continuity_by_slot = {
        record.row_slots[0] if record.row_slots else 0: record
        for record in continuity_records
    }
    correctness_by_slot = {
        int(item.get("record", {}).get("row_slot") or 0): item
        for item in correctness.get("record_correctness", [])
    }
    progressed = []
    for record in records:
        current = TruthState(record.truth_state)
        progression = TruthProgression(current_state=current)
        if current is TruthState.OBSERVED and record.fields:
            progression.advance_to(TruthState.RECOGNIZED, "FIELDS_RECOGNIZED_FROM_TEMPORAL_EVIDENCE")
        if progression.current_state is TruthState.RECOGNIZED:
            progression.advance_to(TruthState.MATCHED, "VALUES_MATCHED_PROFILE_RULES")
        if progression.current_state is TruthState.MATCHED and continuity_by_slot.get(record.row_slot) is not None:
            progression.advance_to(TruthState.RECONCILED, "SCROLL_AND_DUPLICATE_RELATIONSHIP_RESOLVED")
        record_action = str(correctness_by_slot.get(record.row_slot, {}).get("action") or "")
        if progression.current_state is TruthState.RECONCILED and record_action == "accept":
            progression.advance_to(TruthState.USER_VERIFIED, "LOCAL_CORRECTNESS_ACCEPTED_PENDING_COMMIT")
        progressed.append(
            type(record)(
                row_slot=record.row_slot,
                profile_id=record.profile_id,
                state=record.state,
                fields=record.fields,
                support_summary=record.support_summary,
                source_frame_ids=record.source_frame_ids,
                source_row_ids=record.source_row_ids,
                missing_fields=record.missing_fields,
                overlap_provenance={
                    **record.overlap_provenance,
                    "truth_progression": progression.progression_reasons,
                },
                reasons=record.reasons,
                truth_state=progression.current_state.value,
                progression_reason=progression.latest_reason or record.progression_reason,
                profile_version=record.profile_version,
                scan_timestamp=record.scan_timestamp,
                definition_used=getattr(record, "definition_used", ""),
                field_details=getattr(record, "field_details", {}),
                semantic_notes=getattr(record, "semantic_notes", ()),
            )
        )
    return tuple(progressed)


def _screen_summary(frame_reports: tuple[DiagnosticReport, ...]) -> dict[str, int]:
    summary: dict[str, int] = {}
    for report in frame_reports:
        summary[report.screen_class] = summary.get(report.screen_class, 0) + 1
    return summary


def _recognition_mode_summary(frame_reports: tuple[DiagnosticReport, ...]) -> str:
    modes = {getattr(report, "recognition_mode", "") for report in frame_reports if getattr(report, "recognition_mode", "")}
    if "Hybrid" in modes:
        return "Hybrid"
    if "Local-AI" in modes:
        return "Local-AI"
    if "Offline" in modes and len(modes) == 1:
        return "Offline"
    return "Classic-Only"


def _apply_field_provenance(
    records: tuple[object, ...],
    frame_reports: tuple[DiagnosticReport, ...],
) -> tuple[object, ...]:
    crop_lookup: dict[str, object] = {}
    attempt_lookup: dict[str, object] = {}
    ranked_lookup: dict[str, object] = {}
    ranked_any_lookup: dict[str, list[object]] = {}
    correlation_by_frame: dict[str, dict[str, object]] = {}
    for report in frame_reports:
        correlation_by_frame[report.frame.frame_id] = dict(getattr(report, "selected_detail_correlation", {}))
        for crop in report.prepared_crops:
            crop_lookup[crop.crop_id] = crop
        for attempt in report.ocr_attempts:
            attempt_lookup[attempt.crop_id] = attempt
        for candidate in report.ranked_candidates:
            ranked_any_lookup.setdefault(candidate.source_crop_id, []).append(candidate)
            if getattr(candidate, "decision", None) is CandidateDecision.SELECTED:
                ranked_lookup[candidate.source_crop_id] = candidate

    enriched = []
    tracked_fields = (
        FieldKind.ITEM_NAME,
        FieldKind.ITEM_RARITY,
        FieldKind.ITEM_COUNT,
        FieldKind.ITEM_TYPE,
        FieldKind.ITEM_SYNERGY,
    )
    for record in records:
        field_details = dict(getattr(record, "field_details", {}))
        field_map = getattr(record, "fields", {})
        support_summary = getattr(record, "support_summary", {})
        source_row_ids = tuple(getattr(record, "source_row_ids", ()))
        frame_id = str(getattr(record, "source_frame_ids", ("",))[0] if getattr(record, "source_frame_ids", ()) else "")
        correlation = correlation_by_frame.get(frame_id, {})
        for field_kind in tracked_fields:
            field_name = field_kind.value
            detail = dict(field_details.get(field_name, {}))
            summary = support_summary.get(field_name, {})
            crop_ids = tuple(str(item) for item in summary.get("source_crop_ids", ()))
            evidence_entries: list[dict[str, object]] = []
            for crop_id in crop_ids:
                crop = crop_lookup.get(crop_id)
                attempt = attempt_lookup.get(crop_id)
                ranked = ranked_lookup.get(crop_id)
                if crop is None:
                    continue
                evidence_source = "detail_panel" if str(crop_id).startswith("detail-") else "row_list"
                policy_result = list(getattr(ranked, "reasons", ()) or getattr(attempt, "reasons", ()))
                entry = {
                    "frame_id": _frame_id_from_row_id(str(getattr(crop, "row_id", ""))),
                    "row_id": str(getattr(crop, "row_id", "")),
                    "candidate_id": f"row-{getattr(record, 'row_slot', 0)}:{field_name}",
                    "crop_id": crop_id,
                    "crop_bounds": getattr(crop, "source_region").as_dict(),
                    "raw_ocr": str(getattr(attempt, "raw_text", "")),
                    "normalized_value": str(getattr(ranked, "candidate_value", getattr(attempt, "normalized_text", ""))),
                    "confidence": float(getattr(ranked, "confidence", getattr(attempt, "confidence", 0.0))),
                    "policy_result": policy_result,
                    "source_variant": getattr(getattr(crop, "variant", None), "value", ""),
                    "source_engine": str(getattr(attempt, "engine_name", "")),
                    "evidence_source": evidence_source,
                }
                if evidence_source == "detail_panel" and correlation.get("correlated"):
                    entry["correlation"] = {
                        "selected_row_id": correlation.get("selected_row_id", ""),
                        "row_name_ocr": correlation.get("row_name_ocr", {}),
                        "detail_title_ocr": correlation.get("detail_title_ocr", {}),
                        "correlation_guards": correlation.get("correlation_guards", {}),
                        "best_score": correlation.get("best_score", 0),
                        "second_best_score": correlation.get("second_best_score", 0),
                    }
                evidence_entries.append(entry)
            if field_kind in field_map and evidence_entries:
                best_entry = max(evidence_entries, key=lambda item: float(item.get("confidence", 0.0)))
                detail["field_confidence"] = float(best_entry.get("confidence", 0.0))
                detail["source_text"] = str(field_map.get(field_kind, ""))
                if field_kind is FieldKind.ITEM_NAME and _summary_is_unresolved_identity(summary):
                    detail["status"] = "UNRESOLVED_IDENTITY"
                    detail["direct_observation"] = False
                    detail["raw_observation"] = str(best_entry.get("normalized_value", ""))
                else:
                    detail["status"] = "OBSERVED"
                    detail["direct_observation"] = True
                detail["policy_result"] = best_entry.get("policy_result", [])
                detail["evidence_source"] = best_entry.get("evidence_source", "row_list")
                detail["evidence"] = evidence_entries
                if field_kind is FieldKind.ITEM_RARITY:
                    observed_color = str(best_entry.get("raw_ocr", "")).strip()
                    if observed_color:
                        detail["observed_color"] = observed_color
            elif field_kind not in field_map:
                detail = _classify_missing_field_detail(
                    field_kind=field_kind,
                    source_row_ids=source_row_ids,
                    crop_lookup=crop_lookup,
                    attempt_lookup=attempt_lookup,
                    ranked_lookup=ranked_any_lookup,
                    existing_detail=detail,
                )
            if detail:
                field_details[field_name] = detail
        enriched.append(
            type(record)(
                row_slot=record.row_slot,
                profile_id=record.profile_id,
                state=record.state,
                fields=record.fields,
                support_summary=record.support_summary,
                source_frame_ids=record.source_frame_ids,
                source_row_ids=record.source_row_ids,
                missing_fields=record.missing_fields,
                overlap_provenance=record.overlap_provenance,
                reasons=record.reasons,
                truth_state=record.truth_state,
                progression_reason=record.progression_reason,
                profile_version=record.profile_version,
                scan_timestamp=record.scan_timestamp,
                definition_used=getattr(record, "definition_used", ""),
                field_details=field_details,
                semantic_notes=getattr(record, "semantic_notes", ()),
            )
        )
    return tuple(enriched)


def _classify_missing_field_detail(
    *,
    field_kind: FieldKind,
    source_row_ids: tuple[str, ...],
    crop_lookup: dict[str, object],
    attempt_lookup: dict[str, object],
    ranked_lookup: dict[str, list[object]],
    existing_detail: dict[str, object],
) -> dict[str, object]:
    relevant_crops = [
        crop
        for crop in crop_lookup.values()
        if getattr(crop, "row_id", "") in source_row_ids and getattr(getattr(crop, "field_kind", None), "value", "") == field_kind.value
    ]
    if not relevant_crops:
        existing_detail.setdefault("status", "FIELD_NOT_VISIBLE")
        return existing_detail
    attempts = [attempt_lookup.get(getattr(crop, "crop_id", "")) for crop in relevant_crops if attempt_lookup.get(getattr(crop, "crop_id", "")) is not None]
    if not attempts:
        existing_detail.setdefault("status", "OCR_FAILURE")
        return existing_detail
    if all(str(getattr(getattr(attempt, "status", None), "value", "")) != "ok" for attempt in attempts):
        existing_detail.setdefault("status", "OCR_FAILURE")
        existing_detail["reasons"] = list(dict.fromkeys(reason for attempt in attempts for reason in getattr(attempt, "reasons", ())))
        return existing_detail
    if all(not str(getattr(attempt, "normalized_text", "")).strip() for attempt in attempts):
        existing_detail.setdefault("status", "NORMALIZATION_FAILURE")
        return existing_detail
    ranked = [candidate for crop in relevant_crops for candidate in ranked_lookup.get(getattr(crop, "crop_id", ""), [])]
    if ranked and all("REFERENCE_DATA_MISSING" in getattr(candidate, "reasons", ()) for candidate in ranked):
        existing_detail.setdefault("status", "REFERENCE_DATA_MISSING")
        return existing_detail
    existing_detail.setdefault("status", "VALIDATION_FAILURE")
    return existing_detail


def _summary_is_unresolved_identity(summary: object) -> bool:
    if not isinstance(summary, dict):
        return False
    support_state = str(summary.get("support_state", "")).lower()
    try:
        independent_support = int(summary.get("independent_support_count") or 0)
    except (TypeError, ValueError):
        independent_support = 0
    return support_state in {"weak", "conflicted"} or (support_state and independent_support < 2)


def _frame_id_from_row_id(row_id: str) -> str:
    return str(row_id).split(":row:", 1)[0]


def _run_semantic_allocation(
    records: tuple[object, ...],
    *,
    ranked_candidates: tuple[object, ...],
    profile_id: str,
) -> tuple[tuple[CandidateInventoryRecord, ...], dict[str, object], dict[str, dict[str, object]], dict[str, dict[str, object]]]:
    contract = _inventory_definition_contract(profile_id)
    reconstructor = AIReconstructor()
    allocator = SemanticAllocator()
    organizer = OrganizationPass()
    candidate_records: list[CandidateInventoryRecord] = []
    # Keyed by record.temporal_identity_id, not row_slot: temporal-identity-
    # aware assembly can emit several records for the same row_slot (one per
    # temporally distinct item that occupied that screen position at a
    # different time). Keying by row_slot here would let a later record's
    # reconstruction/allocation silently overwrite an earlier record's entry,
    # and every record sharing that row_slot would then read back whichever
    # one was computed last - a "borrowed a neighboring slot occupant's data"
    # failure. temporal_identity_id defaults to str(row_slot) in the legacy
    # (non-recorded) assembly path, so this is a no-op there (still one entry
    # per row_slot, just keyed by its string).
    reconstruction_results: dict[str, dict[str, object]] = {}
    allocation_results: dict[str, dict[str, object]] = {}
    ranked_by_row: dict[int, list[tuple[int | None, str]]] = {}
    for candidate in ranked_candidates:
        row_slot = _row_slot_from_row_id(str(getattr(candidate, "row_id", "")))
        if row_slot <= 0:
            continue
        value = str(getattr(candidate, "candidate_value", "")).strip()
        if value:
            sequence = _frame_sequence_number(str(getattr(candidate, "row_id", "")))
            ranked_by_row.setdefault(row_slot, []).append((sequence, value))
    for record in records:
        identity_key = str(getattr(record, "temporal_identity_id", "") or record.row_slot)
        assembled_fragments = _assembled_semantic_fragments(record)
        ranked_fragments = tuple(
            value
            for sequence, value in ranked_by_row.get(record.row_slot, ())
            if _sequence_within_record_window(sequence, record)
        )
        if _has_unresolved_item_name_identity(record):
            fragments = assembled_fragments
        else:
            fragments = assembled_fragments or ranked_fragments or _record_fragments(record)
        reconstruction = reconstructor.reconstruct(fragments, allowed_terms=tuple(contract.get("allowed_terms", ())))
        allocation = allocator.allocate(reconstruction.repaired_fragments, contract, profile_version=record.profile_version)
        reconstruction_results[identity_key] = {
            "status": reconstruction.status,
            "confidence": reconstruction.confidence,
            "repaired_fragments": list(reconstruction.repaired_fragments),
            "provenance": reconstruction.provenance,
        }
        allocation_results[identity_key] = {
            "record_class": allocation.record_class,
            "status": allocation.status,
            "confidence": allocation.confidence,
            "field_values": dict(allocation.field_values),
            "provenance": allocation.provenance,
        }
        candidate_records.append(allocation)
    organization_summary = organizer.summarize(candidate_records)
    return tuple(candidate_records), organization_summary, reconstruction_results, allocation_results


def _sequence_within_record_window(sequence: int | None, record: object) -> bool:
    if sequence is None:
        return True
    source_frame_ids = tuple(getattr(record, "source_frame_ids", ()) or ())
    if not source_frame_ids:
        return True
    sequences = [seq for seq in (_frame_sequence_number(frame_id) for frame_id in source_frame_ids) if seq is not None]
    if not sequences:
        return True
    return min(sequences) <= sequence <= max(sequences)


def _frame_sequence_number(value: str) -> int | None:
    frame_id = value.split(":row:", 1)[0]
    match = re.search(r"(\d+)$", frame_id)
    if not match:
        return None
    try:
        return int(match.group(1))
    except ValueError:
        return None


def _inventory_definition_contract(profile_id: str) -> dict[str, object]:
    try:
        profile = load_profile(profile_id)
    except OSError:
        profile = create_default_template()
        profile.profile_id = profile_id
    allowed_rarities = tuple(
        dict.fromkeys(
            str(rule.get("tier") or "")
            for rule in profile.rarity_rules
            if str(rule.get("tier") or "").strip()
        )
    )
    allowed_types = tuple(
        dict.fromkeys(
            [
                "Rocket Launcher",
                "SMG",
                "Shotgun",
                "Pistol",
                "Assault Rifle",
                "Shield",
                "Grenade",
                "Consumable",
            ]
        )
    )
    allowed_terms = tuple(
        dict.fromkeys(
            list(allowed_rarities)
            + list(allowed_types)
        )
    )
    return {
        "field_definitions": tuple(profile.inventory_definitions),
        "allowed_rarities": allowed_rarities,
        "allowed_types": allowed_types,
        "allowed_names": (),
        "allowed_counts": tuple(str(index) for index in range(0, 100)),
        "allowed_record_classes": ("Weapon", "WeaponMod", "Shield", "Grenade", "Consumable"),
        "allowed_synergies": (),
        "allowed_terms": allowed_terms,
    }


def _recognition_contract(profile_id: str) -> dict[str, object]:
    contract = _inventory_definition_contract(profile_id)
    contract["allowed_names"] = tuple(
        str(definition.get("label") or "")
        for definition in contract.get("field_definitions", ())
        if str(definition.get("canonical_id") or "") == "item_name" and str(definition.get("label") or "").strip()
    )
    return contract


def _record_fragments(record: object) -> tuple[str, ...]:
    fragments: list[str] = []
    for value in record.fields.values():
        text = str(value).strip()
        if not text:
            continue
        fragments.extend(part for part in text.split() if part)
    return tuple(fragments)


def _has_unresolved_item_name_identity(record: object) -> bool:
    support_summary = getattr(record, "support_summary", {})
    summary = support_summary.get("item_name", {}) if isinstance(support_summary, dict) else {}
    support_state = str(summary.get("support_state", "")).lower() if isinstance(summary, dict) else ""
    independent_support = int(summary.get("independent_support_count") or 0) if isinstance(summary, dict) else 0
    return support_state in {"weak", "conflicted"} or (support_state and independent_support < 2)


def _has_credible_item_name_candidates(ranked_candidates: tuple[object, ...]) -> bool:
    for candidate in ranked_candidates:
        field_kind = getattr(candidate, "field_kind", None)
        if getattr(field_kind, "value", "") != "item_name":
            continue
        candidate_value = str(getattr(candidate, "candidate_value", "") or "").strip()
        if candidate_value:
            return True
    return False


def _assembled_semantic_fragments(record: object) -> tuple[str, ...]:
    ordered_field_names = (
        "item_name",
        "item_rarity",
        "item_synergy",
        "item_type",
        "item_count",
        "mod_slot",
    )
    field_map = getattr(record, "fields", {})
    field_details = getattr(record, "field_details", {})
    fragments: list[str] = []
    seen: set[str] = set()

    for field_name in ordered_field_names:
        detail = field_details.get(field_name, {})
        candidate = ""
        if isinstance(detail, dict):
            status = str(detail.get("status") or "").strip().upper()
            if status == "UNRESOLVED_IDENTITY":
                continue
            candidate = str(detail.get("source_text") or "").strip()
        if not candidate:
            for field_kind, value in field_map.items():
                if getattr(field_kind, "value", "") == field_name:
                    candidate = str(value).strip()
                    break
        normalized = candidate.lower()
        if not candidate or normalized in {"unknown", "<unknown>"} or normalized in seen:
            continue
        seen.add(normalized)
        fragments.append(candidate)

    return tuple(fragments)


def _row_slot_from_row_id(row_id: str) -> int:
    parts = str(row_id).split(":row:")
    if len(parts) != 2:
        return 0
    try:
        return int(parts[1])
    except ValueError:
        return 0


def _ocr_text_row_signatures(ranked_candidates: tuple[object, ...]) -> dict[int, str]:
    """Row-level continuity signature for the recorded-extraction coverage ledger.

    EvidenceCoverageLedger's job is to say whether the same on-screen row still
    shows the same item between two retained frames. A raw pixel hash cannot
    answer that: a real screen capture of unchanged content is never
    byte-identical frame to frame (font anti-aliasing / sub-pixel rendering
    variance persists even with zero motion), so an exact-hash signature
    reports every frame as unique regardless of content (confirmed on a real
    owner recording: 201/201 transitions read NO_ROW_SIGNATURE_OVERLAP, some
    only ~0.1s apart). OCR text is the signal this codebase already treats as
    "what item is this" everywhere else (temporal clustering, auto-store), so
    reusing it here - the best SELECTED/SECONDARY ITEM_NAME reading per row,
    case/whitespace-normalized only, never dictionary-corrected - makes the
    ledger's overlap check consistent with the rest of the pipeline and
    immune to pixel-level rendering noise. When OCR genuinely could not read
    a row, or the row changed, no false overlap is manufactured: the
    comparison stays a plain exact-string check (EvidenceCoverageLedger is
    unchanged), so anything other than a matching reading still and honestly
    reports GAP rather than assuming continuity.
    """
    best_by_slot: dict[int, tuple[int, str]] = {}
    for candidate in ranked_candidates:
        if candidate.field_kind is not FieldKind.ITEM_NAME:
            continue
        if candidate.decision not in {CandidateDecision.SELECTED, CandidateDecision.SECONDARY}:
            continue
        text = candidate.candidate_value.strip().casefold()
        if not text:
            continue
        slot = _row_slot_from_row_id(candidate.row_id)
        rank = 2 if candidate.decision is CandidateDecision.SELECTED else 1
        existing = best_by_slot.get(slot)
        if existing is None or rank > existing[0]:
            best_by_slot[slot] = (rank, text)
    return {slot: text for slot, (_rank, text) in best_by_slot.items()}


def _row_signatures(
    image_path: Path,
    row_zones: tuple[object, ...],
    *,
    image_source: str = IMAGE_SOURCE_GENERAL,
) -> dict[int, str]:
    # NOTE: this exact pixel hash is intentionally left as-is here. It is
    # shared with the live-capture change/motion-detection path
    # (_changed_row_ids / _estimate_change_motion / _frame_uniqueness), which
    # was not verified against a change to this function. The
    # recorded-extraction EvidenceCoverageLedger no longer uses this
    # function's output for its row-signature overlap check — see
    # _ocr_text_row_signatures() and its use in run_recorded_frame_extraction
    # below, which fixed a confirmed defect where this exact hash made the
    # ledger report NO_ROW_SIGNATURE_OVERLAP on every single transition of a
    # real recorded session, even between frames ~0.1s apart, because a real
    # screen capture of the same row is never byte-identical frame to frame.
    from PIL import Image

    if not _is_valid_image_for_source(image_path, image_source=image_source):
        return {}
    signatures: dict[int, str] = {}
    with Image.open(image_path) as image:
        rgb = image.convert("RGB")
        for index, zone in enumerate(row_zones, start=1):
            crop = rgb.crop((zone.row_bounds.x1, zone.row_bounds.y1, zone.row_bounds.x2, zone.row_bounds.y2))
            digest = sha1(crop.tobytes()).hexdigest()[:16]
            signatures[index] = digest
    return signatures


def _changed_row_ids(frame_id: str, previous_signatures: dict[int, str], current_signatures: dict[int, str]) -> tuple[str, ...]:
    if not previous_signatures:
        return tuple(f"{frame_id}:row:{row_slot}" for row_slot in sorted(current_signatures))
    changed: list[str] = []
    for row_slot, signature in sorted(current_signatures.items()):
        if previous_signatures.get(row_slot) != signature:
            changed.append(f"{frame_id}:row:{row_slot}")
    return tuple(changed)


def _is_valid_png_file(image_path: Path) -> bool:
    try:
        if not image_path.exists():
            return False
        if image_path.suffix.lower() == ".tmp":
            return False
        size = os.path.getsize(image_path)
        if size <= 0:
            return False
        with image_path.open("rb") as handle:
            signature = handle.read(len(PNG_SIGNATURE))
            if signature != PNG_SIGNATURE:
                return False
        from PIL import Image

        with Image.open(image_path) as image:
            image.verify()
        return True
    except OSError:
        return False
    except Exception:
        return False


def _is_valid_image_for_source(image_path: Path, *, image_source: str) -> bool:
    if image_source == IMAGE_SOURCE_LIVE_CAPTURE:
        return _is_valid_png_file(image_path)
    return _is_valid_general_image_file(image_path)


def _is_valid_general_image_file(image_path: Path) -> bool:
    try:
        if not image_path.exists():
            return False
        if os.path.getsize(image_path) <= 0:
            return False
        from PIL import Image

        with Image.open(image_path) as image:
            image.verify()
        return True
    except OSError:
        return False
    except Exception:
        return False


def _estimate_change_motion(previous_signatures: dict[int, str], current_signatures: dict[int, str]) -> float:
    if not previous_signatures or not current_signatures:
        return 0.0
    changed = sum(1 for row_slot, signature in current_signatures.items() if previous_signatures.get(row_slot) != signature)
    return round(changed / max(1, len(current_signatures)), 3)


def _frame_uniqueness(previous_signatures: dict[int, str], current_signatures: dict[int, str]) -> float:
    if not current_signatures:
        return 0.0
    if not previous_signatures:
        return 1.0
    changed = sum(1 for row_slot, signature in current_signatures.items() if previous_signatures.get(row_slot) != signature)
    return round(changed / max(1, len(current_signatures)), 3)


def _frame_fingerprint(image_path: Path) -> str:
    """Return a compact content fingerprint, never an image-path or object identity."""
    if not image_path or not _is_valid_png_file(image_path):
        return ""
    try:
        from PIL import Image

        with Image.open(image_path) as image:
            # Grayscale thresholding tolerates minor capture noise while retaining visible UI changes.
            pixels = list(image.convert("L").resize((16, 9)).getdata())
        if not pixels:
            return ""
        average = sum(pixels) / len(pixels)
        bits = bytes(1 if pixel >= average else 0 for pixel in pixels)
        # Preserve coarse luminance too: a uniform but visibly different surface
        # must not collapse into the same threshold-only fingerprint.
        brightness_bucket = int(average // 16)
        return sha1(bits + bytes([brightness_bucket])).hexdigest()[:16]
    except (OSError, ValueError):
        return ""


def _is_readable(captured: _CapturedFrameState) -> bool:
    return getattr(captured.quality, "action").value != "drop"


def _readability_score(captured: _CapturedFrameState) -> float:
    return max(0.0, float(captured.quality.sharpness) - float(captured.quality.motion_penalty) - float(captured.quality.partial_row_penalty))


def _normalize_live_scan_scope(value: str | ScanScope) -> ScanScope:
    if isinstance(value, ScanScope):
        return value
    normalized = str(value).strip().lower().replace(" ", "_")
    if normalized in {"full", "full_inventory"}:
        return ScanScope.FULL_INVENTORY
    if normalized in {"current", "current_page", "page"}:
        return ScanScope.CURRENT_PAGE
    return ScanScope.FULL_INVENTORY


def _attach_throughput(
    report: dict[str, object],
    *,
    metrics: RateMetrics,
    temporal_windows: list[tuple[object, ...]],
    queue_depth: int,
    buffer_bytes: int,
    memory_decision: MemoryDecision,
) -> None:
    continuity_status = str(report.get("continuity_summary") or "CONTINUITY_LOST")
    overlay = render_corner_overlay(
        OverlaySnapshot(
            capture_fps=metrics.capture_fps,
            useful_fps=metrics.useful_fps,
            extraction_rate=metrics.extraction_rate,
            verified_rate=metrics.verified_rate,
            queue_depth=queue_depth,
            continuity_status="OK" if continuity_status == "OVERLAP_DETECTED" else continuity_status,
            buffer_gb=round(buffer_bytes / (1024 * 1024 * 1024), 1),
            buffer_limit_gb=3.0,
            warning="SLOW DOWN - extraction falling behind" if memory_decision.level >= 5 else "",
        )
    )
    report["throughput"] = {
        "rate_metrics": metrics.snapshot(),
        "memory_governor": {
            "level": memory_decision.level,
            "level_name": memory_decision.level_name,
            "action": memory_decision.action.value,
            "retained_budget_ratio": memory_decision.retained_budget_ratio,
            "reasons": list(memory_decision.reasons),
        },
        "temporal_windows": [
            [
                {
                    "row_slot": observation.row_slot,
                    "support_count": observation.support_count,
                    "agreement_score": observation.agreement_score,
                    "best_source_frame_id": observation.best_source_frame_id,
                    "released_frame_ids": list(getattr(observation, "released_frame_ids", ())),
                }
                for observation in window
            ]
            for window in temporal_windows
        ],
        "overlay": overlay,
        "queue_depth": queue_depth,
    }
