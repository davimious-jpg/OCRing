from __future__ import annotations

from ocring.ocr.api_ai import ApiAiAnalyzer, RecordingApiAiClient


def test_api_ai_analyze_submits_only_crop_payload() -> None:
    client = RecordingApiAiClient()
    analyzer = ApiAiAnalyzer(client)

    result = analyzer.analyze(
        {
            "crop_id": "crop-1",
            "crop_path": "E:/Ocring/crops/crop-1.png",
            "frame_path": "E:/Ocring/frames/frame-1.png",
            "full_frame": {"pixels": "do-not-send"},
            "field_kind": "item_name",
        }
    )

    assert result["status"] == "submitted"
    assert result["payload"]["crop_path"].endswith("crop-1.png")
    assert "frame_path" not in result["payload"]
    assert "full_frame" not in result["payload"]
    assert result["payload"]["metadata"]["field_kind"] == "item_name"

