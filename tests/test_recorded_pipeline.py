from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from PIL import Image

from ocring.ocr import pipeline
from ocring.ocr.models import CandidateDecision, FieldKind, PreprocessVariant, RankedFieldCandidate, TemporalSupportState
from ocring.ocr.recorded_frame_source import RecordedFrame
from ocring.ocr.temporal import merge_ranked_candidates


def _recorded_frame(sequence_id: int, path: Path) -> RecordedFrame:
    return RecordedFrame(
        sequence_id=sequence_id,
        frame_id=f"session-recorded-recorded-frame-{sequence_id:06d}",
        session_id="session-recorded",
        image_path=path,
        capture_timestamp=float(sequence_id),
        timestamp_utc=f"2026-09-03T00:00:0{sequence_id}+00:00",
        content_hash=f"hash-{sequence_id}",
    )


def _ranked_name(row_id: str, value: str, crop_id: str) -> RankedFieldCandidate:
    return RankedFieldCandidate(
        row_id=row_id,
        field_kind=FieldKind.ITEM_NAME,
        candidate_value=value,
        source_crop_id=crop_id,
        source_variant=PreprocessVariant.SHARPENED,
        source_engine="test",
        decision=CandidateDecision.SELECTED,
        confidence=0.9,
    )


def test_recorded_temporal_merge_allows_same_slot_reuse_without_conflict() -> None:
    candidates = (
        _ranked_name("frame-001:row:2", "Tight Guidance System IV", "crop-1"),
        _ranked_name("frame-002:row:2", "Tight Guidance System IV", "crop-2"),
        _ranked_name("frame-100:row:2", "Reserve Chamber IV", "crop-3"),
        _ranked_name("frame-101:row:2", "Reserve Chamber IV", "crop-4"),
    )

    current_page = merge_ranked_candidates(candidates)
    recorded = merge_ranked_candidates(candidates, allow_slot_reuse=True)

    assert {item.support_state for item in current_page} == {TemporalSupportState.CONFLICTED}
    assert {item.support_state for item in recorded} == {TemporalSupportState.SUPPORTED}


def test_recorded_temporal_merge_keeps_same_frame_variants_non_stable() -> None:
    candidates = (
        _ranked_name("frame-001:row:2", "Tight Guidance System IV", "crop-1"),
        _ranked_name("frame-001:row:2", "Reserve Chamber IV", "crop-2"),
    )

    recorded = merge_ranked_candidates(candidates, allow_slot_reuse=True)

    assert len(recorded) == 1
    assert recorded[0].support_state is TemporalSupportState.WEAK
    assert recorded[0].independent_support_count == 1


def test_temporal_merge_collapses_same_frame_preprocess_variants_before_conflict() -> None:
    candidates = (
        _ranked_name("frame-001:row:2", "Tight Guidance System IV", "crop-1"),
        _ranked_name("frame-001:row:2", "Tight Gudance System IN", "crop-2"),
        _ranked_name("frame-002:row:2", "Tight Guidance System IV", "crop-3"),
        _ranked_name("frame-002:row:2", "Tight Gudance System IN", "crop-4"),
    )

    aggregates = merge_ranked_candidates(candidates, allow_slot_reuse=True)

    assert len(aggregates) == 1
    assert aggregates[0].candidate_value == "Tight Guidance System IV"
    assert aggregates[0].support_state is TemporalSupportState.SUPPORTED
    assert aggregates[0].independent_support_count == 2


def test_recorded_frame_extraction_feeds_existing_session_report_builder(monkeypatch, tmp_path: Path) -> None:
    # Coverage-ledger row signatures come from post-OCR ITEM_NAME text now
    # (a raw pixel hash never matches between two real captures of
    # the same content, since screen capture is never byte-identical frame to
    # frame). Row 2 reads the same text in both frames -> CONTINUOUS overlap;
    # row 1 differs -> not part of the overlap, but doesn't block it either.
    frames = (_recorded_frame(1, tmp_path / "one.png"), _recorded_frame(2, tmp_path / "two.png"))
    image_sources: list[str] = []
    built_frame_ids: list[str] = []

    def fake_capture_frame_state(image_path, **kwargs):
        del image_path
        image_sources.append(kwargs["image_source"])
        return SimpleNamespace()

    def fake_build_frame_report(image_path, **kwargs):
        del image_path
        frame_id = kwargs["frame_id"]
        built_frame_ids.append(frame_id)
        index = 1 if frame_id.endswith("000001") else 2
        ranked = (
            _ranked_name(f"{frame_id}:row:1", f"Row One Text {index}", f"crop-{index}-1"),
            _ranked_name(f"{frame_id}:row:2", "Shared Row Text", f"crop-{index}-2"),
        )
        return SimpleNamespace(frame_id=frame_id, ranked_candidates=ranked)

    def fake_build_session_report(frame_reports, **kwargs):
        assert kwargs["profile_id"] == "defiance"
        assert kwargs["scan_scope"] is pipeline.ScanScope.FULL_INVENTORY
        return {"frame_reports": list(frame_reports), "assembled_records": [], "continuity_records": []}

    monkeypatch.setattr(pipeline, "_capture_frame_state", fake_capture_frame_state)
    monkeypatch.setattr(pipeline, "_build_frame_report", fake_build_frame_report)
    monkeypatch.setattr(pipeline, "_build_session_report", fake_build_session_report)

    report = pipeline.run_recorded_frame_extraction(frames, profile_id="defiance")

    assert image_sources == [pipeline.IMAGE_SOURCE_RECORDED_CAPTURE, pipeline.IMAGE_SOURCE_RECORDED_CAPTURE]
    assert built_frame_ids == ["session-recorded-recorded-frame-000001", "session-recorded-recorded-frame-000002"]
    assert report["recorded_capture_mode"] is True
    assert report["coverage_ledger"]["coverage_state"] == "CONTINUOUS"


def test_recorded_frame_extraction_reports_coverage_gap(monkeypatch, tmp_path: Path) -> None:
    frames = (_recorded_frame(1, tmp_path / "one.png"), _recorded_frame(2, tmp_path / "two.png"))

    def fake_build_frame_report(image_path, **kwargs):
        del image_path
        frame_id = kwargs["frame_id"]
        offset = 0 if frame_id.endswith("000001") else 8
        ranked = tuple(
            _ranked_name(f"{frame_id}:row:{row}", f"Item {100 + offset + row}", f"crop-{frame_id}-{row}")
            for row in range(1, 6)
        )
        return SimpleNamespace(frame_id=frame_id, ranked_candidates=ranked)

    monkeypatch.setattr(pipeline, "_capture_frame_state", lambda _path, **_kwargs: SimpleNamespace())
    monkeypatch.setattr(pipeline, "_build_frame_report", fake_build_frame_report)
    monkeypatch.setattr(
        pipeline,
        "_build_session_report",
        lambda _reports, **_kwargs: {"frame_reports": [], "assembled_records": [], "continuity_records": []},
    )

    report = pipeline.run_recorded_frame_extraction(frames, profile_id="defiance")

    assert report["coverage_ledger"]["coverage_state"] == "GAP"
    assert report["coverage_summary"]["coverage_gaps"] == 1


def test_recorded_frame_extraction_publishes_per_frame_progress(monkeypatch, tmp_path: Path) -> None:
    frames = (_recorded_frame(1, tmp_path / "one.png"), _recorded_frame(2, tmp_path / "two.png"))
    progress: list[dict[str, object]] = []

    def fake_capture_frame_state(image_path, **kwargs):
        del image_path, kwargs
        return SimpleNamespace()

    def fake_build_frame_report(image_path, **kwargs):
        del image_path
        return SimpleNamespace(frame_id=kwargs["frame_id"], row_zones=(), ocr_attempts=(), ranked_candidates=())

    monkeypatch.setattr(pipeline, "_capture_frame_state", fake_capture_frame_state)
    monkeypatch.setattr(pipeline, "_build_frame_report", fake_build_frame_report)
    monkeypatch.setattr(
        pipeline,
        "_build_session_report",
        lambda _reports, **_kwargs: {"frame_reports": [], "assembled_records": [], "continuity_records": []},
    )

    report = pipeline.run_recorded_frame_extraction(frames, profile_id="defiance", progress_callback=progress.append)

    ocr_progress = [item for item in progress if item["stage"] == "OCR"]
    assert [item["current_index"] for item in ocr_progress] == [0, 1, 2]
    assert report["ocr_frame_timing_summary"]["frames_timed"] == 2
    assert report["ocr_frame_timing_summary"]["top_slow_frames"]


def test_extract_from_recorded_frames_requires_finalized_recording(tmp_path: Path) -> None:
    Image.new("RGB", (8, 8), (10, 10, 10)).save(tmp_path / "frame-000001.png")

    try:
        pipeline.extract_from_recorded_frames(tmp_path, profile_id="defiance", session_id="session-recorded")
    except ValueError as error:
        assert "not finalized" in str(error)
    else:
        raise AssertionError("expected unfinalized recorded extraction to be rejected")
