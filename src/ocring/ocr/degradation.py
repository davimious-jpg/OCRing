from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class DegradationMode(str, Enum):
    FULL = "FULL"
    LOCAL = "LOCAL"
    CLASSIC = "CLASSIC"
    CAPTURE_ONLY = "CAPTURE_ONLY"
    REVIEW_ONLY = "REVIEW_ONLY"


_FALLBACK_ORDER = (
    DegradationMode.FULL,
    DegradationMode.LOCAL,
    DegradationMode.CLASSIC,
    DegradationMode.CAPTURE_ONLY,
    DegradationMode.REVIEW_ONLY,
)


@dataclass(frozen=True)
class EngineAvailability:
    ocr_available: bool = True
    local_ai_available: bool = True
    api_ai_allowed: bool = True
    capture_available: bool = True


@dataclass(frozen=True)
class DegradationResult:
    mode: DegradationMode
    reasons: tuple[str, ...]


def resolve_degradation_mode(availability: EngineAvailability) -> DegradationResult:
    if availability.ocr_available and availability.local_ai_available and availability.api_ai_allowed:
        return DegradationResult(DegradationMode.FULL, ("FULL_STACK_AVAILABLE",))
    if availability.ocr_available and availability.local_ai_available:
        return DegradationResult(DegradationMode.LOCAL, ("API_UNAVAILABLE_OR_DISALLOWED",))
    if availability.ocr_available:
        return DegradationResult(DegradationMode.CLASSIC, ("LOCAL_AI_UNAVAILABLE",))
    if availability.capture_available:
        return DegradationResult(DegradationMode.CAPTURE_ONLY, ("OCR_UNAVAILABLE",))
    return DegradationResult(DegradationMode.REVIEW_ONLY, ("CAPTURE_UNAVAILABLE",))


def degrade_mode(current_mode: DegradationMode) -> DegradationMode:
    try:
        index = _FALLBACK_ORDER.index(current_mode)
    except ValueError:
        return DegradationMode.REVIEW_ONLY
    if index >= len(_FALLBACK_ORDER) - 1:
        return DegradationMode.REVIEW_ONLY
    return _FALLBACK_ORDER[index + 1]

