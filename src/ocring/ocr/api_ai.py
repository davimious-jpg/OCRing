from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


FORBIDDEN_FRAME_KEYS = frozenset({"frame", "frame_path", "full_frame", "full_frame_path"})


@dataclass(frozen=True)
class ApiAiCrop:
    crop_id: str
    crop_path: str = ""
    crop_bytes: bytes = b""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ApiAiRequest:
    crop_id: str
    crop_path: str
    crop_bytes: bytes
    metadata: dict[str, Any]

    def as_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "crop_id": self.crop_id,
            "metadata": dict(self.metadata),
        }
        if self.crop_path:
            payload["crop_path"] = self.crop_path
        if self.crop_bytes:
            payload["crop_bytes"] = self.crop_bytes
        return payload


class ApiAiClient(Protocol):
    def submit_crop(self, request: ApiAiRequest) -> dict[str, Any]:
        ...


class RecordingApiAiClient:
    def __init__(self) -> None:
        self.requests: list[ApiAiRequest] = []

    def submit_crop(self, request: ApiAiRequest) -> dict[str, Any]:
        self.requests.append(request)
        return {
            "status": "submitted",
            "crop_id": request.crop_id,
            "payload": request.as_payload(),
        }


class ApiAiAnalyzer:
    def __init__(self, client: ApiAiClient | None = None) -> None:
        self.client = client or RecordingApiAiClient()

    def analyze(self, crop: ApiAiCrop | dict[str, Any]) -> dict[str, Any]:
        request = _coerce_crop_request(crop)
        return self.client.submit_crop(request)


def _coerce_crop_request(crop: ApiAiCrop | dict[str, Any]) -> ApiAiRequest:
    if isinstance(crop, ApiAiCrop):
        if not crop.crop_path and not crop.crop_bytes:
            raise ValueError("api_ai.analyze requires a pre-cropped region payload")
        return ApiAiRequest(
            crop_id=crop.crop_id,
            crop_path=crop.crop_path,
            crop_bytes=crop.crop_bytes,
            metadata=dict(crop.metadata),
        )
    if not isinstance(crop, dict):
        raise TypeError("api_ai.analyze expects ApiAiCrop or dict input")
    crop_id = str(crop.get("crop_id") or "").strip()
    crop_path = str(crop.get("crop_path") or "").strip()
    crop_bytes = crop.get("crop_bytes") or b""
    if not crop_id:
        raise ValueError("api_ai.analyze requires crop_id")
    if not crop_path and not crop_bytes:
        raise ValueError("api_ai.analyze requires crop_path or crop_bytes")
    metadata = {
        str(key): value
        for key, value in crop.items()
        if key not in {"crop_id", "crop_path", "crop_bytes"} and key not in FORBIDDEN_FRAME_KEYS
    }
    return ApiAiRequest(
        crop_id=crop_id,
        crop_path=crop_path,
        crop_bytes=bytes(crop_bytes) if isinstance(crop_bytes, (bytes, bytearray)) else b"",
        metadata=metadata,
    )
