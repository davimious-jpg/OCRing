from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .models import ReplayFrameMode, ScanScope
from .session_fixture import SessionFixture, load_session_fixture


@dataclass(frozen=True)
class FixtureCatalogEntry:
    fixture_id: str
    fixture_path: Path
    profile_id: str
    scan_scope: ScanScope
    frame_count: int
    replay_modes: tuple[ReplayFrameMode, ...]

    @property
    def is_live_ocr(self) -> bool:
        return all(mode is ReplayFrameMode.LIVE_OCR for mode in self.replay_modes)


def discover_session_fixture_catalog(fixtures_dir: Path) -> tuple[FixtureCatalogEntry, ...]:
    entries: list[FixtureCatalogEntry] = []
    for fixture_path in sorted(fixtures_dir.glob("*_fixture.json")):
        fixture = load_session_fixture(fixture_path)
        entries.append(_build_catalog_entry(fixture_path, fixture))
    return tuple(entries)


def _build_catalog_entry(fixture_path: Path, fixture: SessionFixture) -> FixtureCatalogEntry:
    return FixtureCatalogEntry(
        fixture_id=fixture.fixture_id,
        fixture_path=fixture_path.resolve(),
        profile_id=fixture.profile_id,
        scan_scope=fixture.scan_scope,
        frame_count=len(fixture.frames),
        replay_modes=tuple(frame.replay_mode for frame in fixture.frames),
    )
