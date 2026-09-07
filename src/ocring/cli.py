from __future__ import annotations

import argparse
import json
from pathlib import Path

from .ocr.checkpoint import CheckpointManager
from .ocr.export import Exporter, build_export_metadata, default_export_path, filter_export_records
from .ocr.generic_profile import load_generic_profile
from .ocr.inventory import InventoryStore
from .ocr.pipeline import extract_from_recorded_frames, run_fixture_diagnostic, run_frame_diagnostic, run_session_diagnostic
from .ocr.profile import DEFAULT_PROFILES_ROOT, list_profiles, load_profile, resolve_profile_runtime
from .ocr.profile_package import ProfilePackage
from .ocr.profile_validator import validate_profile
from .ocr.recovery import RecoveryManager
from .ocr.review import load_review_session_from_store
from .ocr.search import SearchEngine
from .ocr.session_fixture import load_session_fixture
from .ocr.session_store import commit_session_artifacts
from .ocr.settings import DEFAULT_SETTINGS_PATH, ensure_output_workspace
from .ui.generic_region_selector import GenericRegionSelectorWindow
from .ui.profile_editor import ProfileEditorWindow
from .ui.review_window import ReviewWindow


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="OCRing OCR subsystem diagnostic CLI")
    parser.add_argument(
        "command",
        nargs="?",
        choices=(
            "review",
            "recover",
            "checkpoint",
            "search",
            "export",
            "saved-search",
            "profile-editor",
            "profile-validate",
            "generic-mode",
            "scan",
            "profile-export",
            "profile-import",
            "profile-list",
            "extract-recording",
        ),
        help="Optional subcommand",
    )
    parser.add_argument(
        "--input",
        type=Path,
        nargs="+",
        help="Path(s) to one or more frame images",
    )
    parser.add_argument(
        "--profile",
        default="defiance",
        help="Game profile identifier used for OCR policy selection",
    )
    parser.add_argument(
        "--fixture",
        type=Path,
        help="Path to a JSON session fixture file",
    )
    parser.add_argument(
        "--persist-dir",
        type=Path,
        help="Optional directory used to transactionally persist report, snapshot, and manifest artifacts",
    )
    parser.add_argument(
        "--session",
        help="Session id used with `ocring review|recover|checkpoint --session <session_id>`",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Force checkpoint creation when using `ocring checkpoint`",
    )
    parser.add_argument(
        "--discard",
        action="store_true",
        help="Discard the latest checkpoint when using `ocring recover`",
    )
    parser.add_argument(
        "--query",
        help="Search query string",
    )
    parser.add_argument(
        "--export",
        choices=("csv", "json", "package"),
        help="Optional export format for search results",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Output path for export commands",
    )
    parser.add_argument(
        "--format",
        choices=("csv", "json", "package"),
        help="Export format used with `ocring export`",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="List saved searches",
    )
    parser.add_argument(
        "--save",
        help="Name for a saved search",
    )
    parser.add_argument(
        "--generic",
        action="store_true",
        help="Run the command in generic profile mode",
    )
    parser.add_argument(
        "--region",
        help="Region override in x1,y1,x2,y2 format",
    )
    parser.add_argument(
        "--package",
        type=Path,
        help="Path to a .ocring-profile package",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Overwrite an existing local profile during import",
    )
    parser.add_argument(
        "--session-id",
        help="Optional session id used with `ocring extract-recording`",
    )
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    workspace = ensure_output_workspace(path=DEFAULT_SETTINGS_PATH)
    sessions_root = workspace.sessions_dir
    checkpoints_root = workspace.checkpoints_dir
    inventory_path = workspace.inventory_db

    if args.command == "review":
        if not args.session:
            parser.error("--session is required for `ocring review`")
        review_session = load_review_session_from_store(args.session, sessions_root=sessions_root)
        ReviewWindow(review_session, sessions_root=sessions_root).run()
        return 0
    if args.command == "recover":
        if not args.session:
            parser.error("--session is required for `ocring recover`")
        recovery_manager = RecoveryManager(checkpoints_root)
        if args.discard:
            removed = recovery_manager.discard_and_start_fresh(args.session)
            print(json.dumps({"session_id": args.session, "action": "discard", "removed": [str(path) for path in removed]}, indent=2))
            return 0
        options = recovery_manager.get_recovery_options(args.session)
        if "resume" not in options:
            print(json.dumps({"session_id": args.session, "options": list(options)}, indent=2))
            return 0
        resumed = recovery_manager.resume_from_last_checkpoint(args.session)
        print(
            json.dumps(
                {
                    "session_id": args.session,
                    "action": "resume",
                    "next_frame_index": resumed.next_frame_index,
                    "last_frame_id": resumed.session_state.last_frame_id,
                },
                indent=2,
            )
        )
        return 0
    if args.command == "checkpoint":
        if not args.session:
            parser.error("--session is required for `ocring checkpoint`")
        if not args.force:
            parser.error("--force is required for `ocring checkpoint`")
        review_session = load_review_session_from_store(args.session, sessions_root=sessions_root)
        report = {
            "profile_id": "defiance",
            "frame_reports": [{"frame": {"session_id": review_session.session_id, "frame_id": review_session.records[-1].record_id if review_session.records else ""}}],
            "assembled_records": [
                {
                    "row_slot": record.row_slot,
                    "fields": record.fields,
                    "support_summary": record.support_summary,
                    "source_frame_ids": record.source_frame_ids,
                    "source_row_ids": record.source_row_ids,
                    "overlap_provenance": record.overlap_provenance,
                    "reasons": record.reasons,
                }
                for record in review_session.records
            ],
            "continuity_records": [],
            "frame_overlaps": [],
        }
        checkpoint_manager = CheckpointManager(checkpoints_root)
        state = checkpoint_manager.build_session_state(report=report, buffer_metadata={}, profile_version="1")
        checkpoint_path = checkpoint_manager.checkpoint_path_for_session(args.session)
        checkpoint_manager.save_checkpoint(state, checkpoint_path)
        print(json.dumps({"session_id": args.session, "checkpoint_path": str(checkpoint_path)}, indent=2))
        return 0
    if args.command == "search":
        if not args.query:
            parser.error("--query is required for `ocring search`")
        inventory = InventoryStore(inventory_path)
        engine = SearchEngine(inventory)
        records = engine.search(args.query, {})
        if args.export:
            output_path = args.output or default_export_path(args.export, session_id=records[0].session_id if records else "search", settings_path=DEFAULT_SETTINGS_PATH)
            exporter = Exporter()
            metadata = build_export_metadata(session_id=records[0].session_id if records else "search")
            if args.export == "csv":
                exporter.export_csv(records, output_path, metadata=metadata)
            elif args.export == "json":
                exporter.export_json(records, output_path, metadata=metadata)
            else:
                exporter.export_ocring_package(records, {"session_id": metadata.session_id, "profile_version": metadata.profile_version, "export_timestamp": metadata.export_timestamp}, output_path)
            print(json.dumps({"count": len(records), "output": str(output_path)}, indent=2))
            return 0
        print(json.dumps([_inventory_record_to_dict(record) for record in records], indent=2))
        return 0
    if args.command == "export":
        if not args.session:
            parser.error("--session is required for `ocring export`")
        if not args.format:
            parser.error("--format is required for `ocring export`")
        inventory = InventoryStore(inventory_path)
        records = inventory.get_records_by_filter({"session_id": args.session})
        exporter = Exporter()
        metadata = build_export_metadata(session_id=args.session)
        output_path = args.output or default_export_path(args.format, session_id=args.session, settings_path=DEFAULT_SETTINGS_PATH)
        if args.format == "csv":
            exporter.export_csv(records, output_path, metadata=metadata)
        elif args.format == "json":
            exporter.export_json(records, output_path, metadata=metadata)
        else:
            exporter.export_ocring_package(records, {"session_id": metadata.session_id, "profile_version": metadata.profile_version, "export_timestamp": metadata.export_timestamp}, output_path)
        print(json.dumps({"count": len(records), "output": str(output_path)}, indent=2))
        return 0
    if args.command == "saved-search":
        inventory = InventoryStore(inventory_path)
        engine = SearchEngine(inventory)
        if args.list:
            print(json.dumps([{"name": item.name, "query": item.query, "filters": item.filters, "smart_folder": item.smart_folder} for item in engine.list_saved_searches()], indent=2))
            return 0
        if args.save:
            if not args.query:
                parser.error("--query is required when using --save")
            engine.save_search(args.save, args.query, {})
            print(json.dumps({"saved": args.save, "query": args.query}, indent=2))
            return 0
        parser.error("use --list or --save with `ocring saved-search`")
    if args.command == "profile-editor":
        ProfileEditorWindow(profiles_root=DEFAULT_PROFILES_ROOT).run()
        return 0
    if args.command == "profile-validate":
        if not args.profile:
            parser.error("--profile is required for `ocring profile-validate`")
        profile = load_profile(args.profile, profiles_root=DEFAULT_PROFILES_ROOT)
        issues = validate_profile(profile)
        print(json.dumps([{"severity": issue.severity, "field": issue.field, "message": issue.message} for issue in issues], indent=2))
        return 0
    if args.command == "generic-mode":
        GenericRegionSelectorWindow(profiles_root=DEFAULT_PROFILES_ROOT).run()
        return 0
    if args.command == "scan":
        if not args.generic:
            parser.error("--generic is required for `ocring scan`")
        if not args.profile:
            parser.error("--profile is required for `ocring scan`")
        if not args.input:
            parser.error("--input is required for `ocring scan`")
        generic_profile = load_generic_profile(args.profile, profiles_root=DEFAULT_PROFILES_ROOT)
        runtime = resolve_profile_runtime(generic_profile.profile_id, profiles_root=DEFAULT_PROFILES_ROOT)
        report = run_frame_diagnostic(args.input[0], profile_id=generic_profile.profile_id)
        report = {
            **report,
            "generic_mode": True,
            "generic_runtime": runtime,
            "generic_region_override": _parse_region_override(args.region) if args.region else dict(generic_profile.region_roi),
        }
        print(json.dumps(report, indent=2))
        return 0
    if args.command == "profile-export":
        if not args.profile:
            parser.error("--profile is required for `ocring profile-export`")
        if args.output is None:
            parser.error("--output is required for `ocring profile-export`")
        package_manager = ProfilePackage(profiles_root=DEFAULT_PROFILES_ROOT)
        package_path = package_manager.export_profile(args.profile, str(args.output))
        print(json.dumps({"profile_id": args.profile, "package_path": str(package_path)}, indent=2))
        return 0
    if args.command == "profile-import":
        if args.package is None:
            parser.error("--package is required for `ocring profile-import`")
        package_manager = ProfilePackage(profiles_root=DEFAULT_PROFILES_ROOT)
        imported_profile_id = package_manager.import_profile(str(args.package), overwrite=args.overwrite)
        print(
            json.dumps(
                {
                    "package_path": str(args.package),
                    "profile_id": imported_profile_id,
                    "overwrite": args.overwrite,
                },
                indent=2,
            )
        )
        return 0
    if args.command == "profile-list":
        profiles = list_profiles(profiles_root=DEFAULT_PROFILES_ROOT)
        print(
            json.dumps(
                [
                    {
                        "profile_id": profile.profile_id,
                        "profile_name": profile.profile_name,
                        "version": profile.version,
                        "generic": getattr(profile, "profile_kind", "") == "generic",
                    }
                    for profile in profiles
                ],
                indent=2,
            )
        )
        return 0
    if args.command == "extract-recording":
        if not args.input or len(args.input) != 1:
            parser.error("--input <recording_dir> is required for `ocring extract-recording`")
        report = extract_from_recorded_frames(
            args.input[0],
            profile_id=args.profile,
            session_id=args.session_id,
            persist_dir=args.persist_dir or sessions_root,
        )
        print(json.dumps(report, indent=2))
        return 0

    if args.fixture is not None:
        fixture = load_session_fixture(args.fixture)
        report = run_fixture_diagnostic(fixture)
    else:
        if not args.input:
            parser.error("either --input or --fixture is required")
        report = run_frame_diagnostic(args.input[0], profile_id=args.profile)
        if len(args.input) > 1:
            report = run_session_diagnostic(tuple(args.input), profile_id=args.profile)
    if args.persist_dir is not None:
        commit_dir = commit_session_artifacts(report, args.persist_dir)
        report = {
            **report,
            "persistence_commit_dir": str(commit_dir.resolve()),
        }
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


def _inventory_record_to_dict(record) -> dict[str, object]:
    return {
        "session_id": record.session_id,
        "record_id": record.record_id,
        "row_slot": record.row_slot,
        "review_status": record.review_status,
        "fields": record.fields,
        "corrections": record.corrections,
    }


def _parse_region_override(value: str) -> dict[str, int]:
    parts = [segment.strip() for segment in value.split(",")]
    if len(parts) != 4:
        raise ValueError("region override must use x1,y1,x2,y2")
    x1, y1, x2, y2 = (int(part) for part in parts)
    return {"x1": x1, "y1": y1, "x2": x2, "y2": y2}
