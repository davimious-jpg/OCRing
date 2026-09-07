from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from ocring.ocr.inventory import InventoryStore
from ocring.ocr.profile import Profile, list_profiles, load_profile
from ocring.ocr.review import ReviewSession, load_review_session_from_store
from ocring.ocr.search_engine import SearchEngine
from ocring.ocr.settings import DEFAULT_SETTINGS_PATH, RecognitionSettings, load_settings, save_settings


class CaptureService(Protocol):
    def list_windows(self) -> list[str]:
        ...

    def test_capture(self, window_id: str) -> dict[str, Any]:
        ...


class RecognitionService(Protocol):
    def set_mode(self, mode: str) -> None:
        ...

    def preview_modes(self) -> tuple[str, ...]:
        ...


class CorrectnessService(Protocol):
    def explain_record(self, record_id: str) -> dict[str, Any]:
        ...


class InventoryService(Protocol):
    def search(self, query: str, filters: dict[str, Any] | None = None) -> list[Any]:
        ...

    def accept_candidate(self, record_id: str) -> bool:
        ...


class SearchService(Protocol):
    def search(self, query: str, filters: dict[str, Any] | None = None) -> list[Any]:
        ...

    def suggest(self, text: str) -> list[str]:
        ...


class ProfileService(Protocol):
    def list_profiles(self) -> list[Profile]:
        ...

    def load_profile(self, profile_id: str) -> Profile:
        ...


class SessionService(Protocol):
    def load_review_session(self, session_id: str) -> ReviewSession:
        ...

    def list_sessions(self) -> list[str]:
        ...


class SettingsService(Protocol):
    def load(self) -> RecognitionSettings:
        ...

    def save(self, settings: RecognitionSettings) -> Path:
        ...


@dataclass
class InventoryStoreService:
    inventory_store: InventoryStore
    review_session: ReviewSession | None = None

    def search(self, query: str, filters: dict[str, Any] | None = None) -> list[Any]:
        engine = SearchEngine(self.inventory_store)
        return engine.search(query, filters or {})

    def accept_candidate(self, record_id: str) -> bool:
        if self.review_session is None:
            return False
        self.review_session.accept_record(record_id)
        return True


@dataclass
class SearchEngineService:
    search_engine: SearchEngine

    def search(self, query: str, filters: dict[str, Any] | None = None) -> list[Any]:
        return self.search_engine.search(query, filters or {})

    def suggest(self, text: str) -> list[str]:
        return self.search_engine.suggest(text)


@dataclass
class LocalProfileService:
    profiles_root: Path = Path("E:/Ocring/profiles")

    def list_profiles(self) -> list[Profile]:
        return list_profiles(profiles_root=self.profiles_root)

    def load_profile(self, profile_id: str) -> Profile:
        return load_profile(profile_id, profiles_root=self.profiles_root)


@dataclass
class LocalSessionService:
    sessions_root: Path = Path("E:/Ocring/sessions")

    def load_review_session(self, session_id: str) -> ReviewSession:
        return load_review_session_from_store(session_id, sessions_root=self.sessions_root)

    def list_sessions(self) -> list[str]:
        if not self.sessions_root.exists():
            return []
        return sorted(path.name for path in self.sessions_root.iterdir() if path.is_dir())


@dataclass
class LocalSettingsService:
    settings_path: Path = DEFAULT_SETTINGS_PATH

    def load(self) -> RecognitionSettings:
        return load_settings(path=self.settings_path)

    def save(self, settings: RecognitionSettings) -> Path:
        return save_settings(settings, path=self.settings_path)

