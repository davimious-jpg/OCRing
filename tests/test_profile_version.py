from __future__ import annotations

from pathlib import Path

from ocring.ocr.assembler import assemble_candidate_records
from ocring.ocr.models import FieldKind, TemporalFieldAggregate, TemporalSupportState
from ocring.ocr.profile import create_default_template, save_profile
from ocring.ocr.profile_version import ProfileVersion


def test_profile_version_binds_profile_version_and_scan_timestamp(tmp_path: Path) -> None:
    profile = create_default_template()
    profile.profile_id = "defiance"
    profile.version = "7"
    save_profile(profile, profiles_root=tmp_path)

    version = ProfileVersion.for_scan("defiance", scan_timestamp="2026-08-16T00:00:00+00:00", profiles_root=tmp_path)

    assert version.profile_id == "defiance"
    assert version.profile_version == "7"
    assert version.scan_timestamp == "2026-08-16T00:00:00+00:00"


def test_profile_version_is_attached_to_assembled_records() -> None:
    aggregates = (
        TemporalFieldAggregate(
            temporal_key="1:item_name:Power Bore",
            row_slot=1,
            field_kind=FieldKind.ITEM_NAME,
            candidate_value="Power Bore",
            support_state=TemporalSupportState.SUPPORTED,
            support_count=2,
            independent_support_count=2,
            best_confidence=0.9,
            contributing_frame_ids=("f1", "f2"),
            contributing_row_ids=("f1:row:1", "f2:row:1"),
        ),
    )

    records = assemble_candidate_records(
        aggregates,
        profile_id="defiance",
        profile_version="7",
        scan_timestamp="2026-08-16T00:00:00+00:00",
    )

    assert records[0].profile_version == "7"
    assert records[0].scan_timestamp == "2026-08-16T00:00:00+00:00"
    assert records[0].truth_state == "recognized"
