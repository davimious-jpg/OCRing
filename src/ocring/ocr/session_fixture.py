from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from .models import CandidateDecision, FieldKind, PreprocessVariant, RankedFieldCandidate, ReplayFrameMode, ScanScope


@dataclass(frozen=True)
class SessionFixtureFrame:
    image_path: Path
    frame_id: str
    session_id: str
    timestamp_utc: str
    replay_mode: ReplayFrameMode
    ranked_candidate_overrides: tuple[RankedFieldCandidate, ...] = ()


@dataclass(frozen=True)
class SessionFixture:
    fixture_id: str
    profile_id: str
    scan_scope: ScanScope
    frames: tuple[SessionFixtureFrame, ...]
    expected_overlaps: tuple[dict[str, object], ...] = ()


def load_session_fixture(fixture_path: Path) -> SessionFixture:
    payload = json.loads(fixture_path.read_text(encoding="utf-8"))
    fixture_dir = fixture_path.resolve().parent

    fixture_id = str(payload.get("fixture_id") or fixture_path.stem)
    profile_id = str(payload.get("profile_id") or "defiance")
    scan_scope = ScanScope(str(payload.get("scan_scope") or ScanScope.CURRENT_PAGE.value))

    frames_payload = payload.get("frames")
    if not isinstance(frames_payload, list) or not frames_payload:
        raise ValueError("Session fixture must define at least one frame.")

    frames: list[SessionFixtureFrame] = []
    for index, entry in enumerate(frames_payload, start=1):
        if not isinstance(entry, dict):
            raise ValueError(f"Fixture frame #{index} must be an object.")
        raw_image_path = entry.get("image_path")
        if not raw_image_path:
            raise ValueError(f"Fixture frame #{index} missing image_path.")
        image_path = (fixture_dir / str(raw_image_path)).resolve()
        frames.append(
            SessionFixtureFrame(
                image_path=image_path,
                frame_id=str(entry.get("frame_id") or f"{fixture_id}-frame-{index:03d}"),
                session_id=str(entry.get("session_id") or fixture_id),
                timestamp_utc=str(entry.get("timestamp_utc") or f"2026-08-15T00:00:{index:02d}+00:00"),
                replay_mode=_load_replay_mode(entry),
                ranked_candidate_overrides=_load_ranked_candidate_overrides(entry),
            )
        )

    return SessionFixture(
        fixture_id=fixture_id,
        profile_id=profile_id,
        scan_scope=scan_scope,
        frames=tuple(frames),
        expected_overlaps=_load_expected_overlaps(payload.get("expected_overlaps"), frames),
    )


def _load_replay_mode(entry: dict) -> ReplayFrameMode:
    if entry.get("replay_mode"):
        return ReplayFrameMode(str(entry["replay_mode"]))
    if entry.get("ranked_candidates"):
        return ReplayFrameMode.RANKED_OVERRIDE
    return ReplayFrameMode.LIVE_OCR


def _load_ranked_candidate_overrides(entry: dict) -> tuple[RankedFieldCandidate, ...]:
    payload = entry.get("ranked_candidates") or []
    if not isinstance(payload, list):
        raise ValueError("ranked_candidates must be a list when provided.")

    overrides: list[RankedFieldCandidate] = []
    for index, candidate in enumerate(payload, start=1):
        if not isinstance(candidate, dict):
            raise ValueError(f"ranked_candidate #{index} must be an object.")
        overrides.append(
            RankedFieldCandidate(
                row_id=str(candidate["row_id"]),
                field_kind=FieldKind(str(candidate["field_kind"])),
                candidate_value=str(candidate.get("candidate_value") or ""),
                source_crop_id=str(candidate.get("source_crop_id") or f"fixture-crop-{index}"),
                source_variant=PreprocessVariant(str(candidate.get("source_variant") or PreprocessVariant.HIGH_CONTRAST.value)),
                source_engine=str(candidate.get("source_engine") or "fixture"),
                decision=CandidateDecision(str(candidate.get("decision") or CandidateDecision.SELECTED.value)),
                confidence=float(candidate.get("confidence") or 0.0),
                reasons=tuple(str(reason) for reason in candidate.get("reasons") or ()),
            )
        )
    return tuple(overrides)


def _load_expected_overlaps(
    payload: object,
    frames: list[SessionFixtureFrame],
) -> tuple[dict[str, object], ...]:
    if payload is None:
        return ()
    if not isinstance(payload, list):
        raise ValueError("expected_overlaps must be a list when provided.")
    resolved: list[dict[str, object]] = []
    for index, item in enumerate(payload, start=1):
        if not isinstance(item, dict):
            raise ValueError(f"expected_overlap #{index} must be an object.")
        raw_rows = item.get("rows") or item.get("overlap_rows")
        if not isinstance(raw_rows, list) or not raw_rows:
            raise ValueError(f"expected_overlap #{index} must define rows.")
        rows: list[tuple[int, int]] = []
        for pair in raw_rows:
            if isinstance(pair, dict):
                row_slot_a = int(pair["row_slot_a"])
                row_slot_b = int(pair["row_slot_b"])
            else:
                row_slot_a = int(pair[0])
                row_slot_b = int(pair[1])
            rows.append((row_slot_a, row_slot_b))
        resolved.append(
            {
                "frame_a_id": _resolve_expected_frame_id(item.get("frame_a"), frames),
                "frame_b_id": _resolve_expected_frame_id(item.get("frame_b"), frames),
                "rows": tuple(rows),
            }
        )
    return tuple(resolved)


def _resolve_expected_frame_id(raw: object, frames: list[SessionFixtureFrame]) -> str:
    if isinstance(raw, int):
        if raw <= 0 or raw > len(frames):
            raise ValueError("expected_overlap frame index out of range.")
        return frames[raw - 1].frame_id
    if raw is None:
        raise ValueError("expected_overlap requires frame_a and frame_b.")
    return str(raw)


def validate_expected_overlaps(fixture: SessionFixture, report: dict[str, object]) -> None:
    if not fixture.expected_overlaps:
        return
    actual = []
    for overlap in report.get("frame_overlaps", []):
        actual.append(
            {
                "frame_a_id": str(overlap.get("frame_a_id")),
                "frame_b_id": str(overlap.get("frame_b_id")),
                "rows": tuple(
                    (int(pair["row_slot_a"]), int(pair["row_slot_b"]))
                    for pair in overlap.get("overlap_rows", [])
                ),
            }
        )
    expected = list(fixture.expected_overlaps)
    if actual != expected:
        raise ValueError(f"Fixture overlap validation failed. expected={expected!r} actual={actual!r}")
