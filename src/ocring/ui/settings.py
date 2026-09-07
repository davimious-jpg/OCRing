from __future__ import annotations

from dataclasses import dataclass, field

from ocring.ocr.settings import RecognitionSettings


SETTINGS_CATEGORIES = (
    "General",
    "Capture",
    "Recognition",
    "AI",
    "Performance",
    "Memory",
    "Overlay",
    "Privacy",
    "Storage",
    "Hotkeys",
    "Profiles",
    "Search",
    "Developer",
)


@dataclass(frozen=True)
class SettingsSection:
    name: str
    values: dict[str, str] = field(default_factory=dict)


def build_settings_sections(settings: RecognitionSettings) -> tuple[SettingsSection, ...]:
    return (
        SettingsSection("Recognition", {"recognition_mode": settings.recognition_mode}),
        SettingsSection("AI", {"api_escalation": settings.api_escalation}),
        SettingsSection("Privacy", {"privacy": settings.privacy}),
        SettingsSection("General", {}),
        SettingsSection("Capture", {}),
        SettingsSection("Performance", {}),
        SettingsSection("Memory", {}),
        SettingsSection("Overlay", {}),
        SettingsSection("Storage", {}),
        SettingsSection("Hotkeys", {}),
        SettingsSection("Profiles", {}),
        SettingsSection("Search", {}),
        SettingsSection("Developer", {}),
    )

