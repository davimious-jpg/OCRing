from __future__ import annotations

from ocring.ocr.recognition_flow_controller import RecognitionFlowController


def test_recognition_flow_controller_accepts_fast_path_when_confident() -> None:
    decision = RecognitionFlowController().decide(
        image_quality=0.8,
        motion_blur=0.1,
        ocr_confidence=0.91,
        dictionary_match=True,
        field_validity=True,
        continuity_confidence=0.8,
        local_ai_available=True,
        api_ai_allowed=True,
        queue_pressure=0.1,
    )

    assert decision.selected_tier == "classic_ocr"
    assert decision.final_action == "accept"


def test_recognition_flow_controller_escalates_to_local_then_api_then_review() -> None:
    controller = RecognitionFlowController()

    local = controller.decide(
        image_quality=0.7,
        motion_blur=0.2,
        ocr_confidence=0.5,
        dictionary_match=False,
        field_validity=False,
        continuity_confidence=0.6,
        local_ai_available=True,
        api_ai_allowed=False,
        queue_pressure=0.2,
    )
    api = controller.decide(
        image_quality=0.4,
        motion_blur=0.7,
        ocr_confidence=0.4,
        dictionary_match=False,
        field_validity=False,
        continuity_confidence=0.4,
        local_ai_available=False,
        api_ai_allowed=True,
        queue_pressure=0.2,
    )
    review = controller.decide(
        image_quality=0.4,
        motion_blur=0.8,
        ocr_confidence=0.2,
        dictionary_match=False,
        field_validity=False,
        continuity_confidence=0.1,
        local_ai_available=False,
        api_ai_allowed=False,
        queue_pressure=1.0,
    )

    assert local.selected_tier == "local_ai"
    assert api.selected_tier == "api_ai"
    assert review.selected_tier == "review"
