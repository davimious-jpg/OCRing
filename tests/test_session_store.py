from __future__ import annotations

import json
from pathlib import Path

from ocring.ocr.pipeline import run_fixture_diagnostic
from ocring.ocr.session_fixture import load_session_fixture
from ocring.ocr.session_store import commit_session_artifacts, load_committed_session
from ocring.ocr.snapshot import build_replay_snapshot


FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures" / "session_cases"


def test_commit_session_artifacts_writes_transaction_bundle(tmp_path: Path) -> None:
    fixture = load_session_fixture(FIXTURE_DIR / "stable_current_page_fixture.json")
    report = run_fixture_diagnostic(fixture)

    commit_dir = commit_session_artifacts(report, tmp_path)

    assert commit_dir.exists()
    assert (commit_dir / "report.json").exists()
    assert (commit_dir / "snapshot.json").exists()
    assert (commit_dir / "manifest.json").exists()
    assert not any(path.name.endswith(".staging") for path in commit_dir.parent.iterdir())

    manifest = json.loads((commit_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["session_id"] == fixture.frames[0].session_id
    assert manifest["profile_id"] == fixture.profile_id
    assert manifest["frame_ids"] == [frame.frame_id for frame in fixture.frames]
    assert manifest["scan_scope"] == fixture.scan_scope.value
    assert manifest["artifacts"]["report"] == "report.json"
    assert commit_dir.parent.name == fixture.frames[0].session_id

    snapshot = json.loads((commit_dir / "snapshot.json").read_text(encoding="utf-8"))
    assert snapshot == build_replay_snapshot(report)


def test_load_committed_session_returns_manifest_report_and_snapshot(tmp_path: Path) -> None:
    fixture = load_session_fixture(FIXTURE_DIR / "conflicted_current_page_fixture.json")
    report = run_fixture_diagnostic(fixture)

    commit_dir = commit_session_artifacts(report, tmp_path)
    bundle = load_committed_session(commit_dir)

    assert bundle["report"] == report
    assert bundle["snapshot"] == build_replay_snapshot(report)
    assert bundle["manifest"]["session_id"] == fixture.frames[0].session_id


def test_commit_session_artifacts_cleans_orphaned_staging_directories(tmp_path: Path) -> None:
    fixture = load_session_fixture(FIXTURE_DIR / "stable_current_page_fixture.json")
    report = run_fixture_diagnostic(fixture)

    orphan = tmp_path / "stale-session" / ".orphan.staging"
    orphan.mkdir(parents=True)
    (orphan / "partial.json").write_text("{}", encoding="utf-8")

    commit_session_artifacts(report, tmp_path)

    assert not orphan.exists()


def test_commit_session_artifacts_retries_rename_on_transient_failure(tmp_path: Path, monkeypatch) -> None:
    fixture = load_session_fixture(FIXTURE_DIR / "stable_current_page_fixture.json")
    report = run_fixture_diagnostic(fixture)
    attempts = {"count": 0}

    from ocring.ocr import session_store as session_store_module

    real_rename = session_store_module.os.rename

    def flaky_rename(source, destination):
        attempts["count"] += 1
        if attempts["count"] < 3:
            raise OSError("temporary lock")
        return real_rename(source, destination)

    monkeypatch.setattr(session_store_module.os, "rename", flaky_rename)
    monkeypatch.setattr(session_store_module.time, "sleep", lambda _seconds: None)

    commit_dir = commit_session_artifacts(report, tmp_path)

    assert commit_dir.exists()
    assert attempts["count"] == 3


def test_commit_session_artifacts_defaults_to_output_workspace(tmp_path: Path) -> None:
    fixture = load_session_fixture(FIXTURE_DIR / "stable_current_page_fixture.json")
    report = run_fixture_diagnostic(fixture)
    settings_path = tmp_path / "settings.json"
    output_root = tmp_path / "output"
    settings_path.write_text(json.dumps({"output_root": str(output_root)}), encoding="utf-8")

    commit_dir = commit_session_artifacts(report, settings_path=settings_path)

    assert commit_dir.exists()
    assert output_root / "sessions" in commit_dir.parents
