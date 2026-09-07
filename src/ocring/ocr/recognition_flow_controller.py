from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RecognitionDecision:
    selected_tier: str
    final_action: str
    reason: str


class RecognitionFlowController:
    def decide(
        self,
        *,
        image_quality: float,
        motion_blur: float,
        ocr_confidence: float,
        dictionary_match: bool,
        field_validity: bool,
        continuity_confidence: float,
        local_ai_available: bool,
        api_ai_allowed: bool,
        queue_pressure: float,
    ) -> RecognitionDecision:
        if ocr_confidence >= 0.85 and field_validity and image_quality >= 0.5 and motion_blur <= 0.4:
            return RecognitionDecision("classic_ocr", "accept", "FAST_PATH_CONFIDENT")
        if local_ai_available and (ocr_confidence < 0.85 or not dictionary_match or not field_validity):
            if queue_pressure < 0.9 and continuity_confidence >= 0.2:
                return RecognitionDecision("local_ai", "escalate", "CLASSIC_WEAK_LOCAL_AI_AVAILABLE")
        if api_ai_allowed and (ocr_confidence < 0.7 or not field_validity or motion_blur > 0.55):
            return RecognitionDecision("api_ai", "escalate", "LOCAL_AI_UNCERTAIN_OR_SKIPPED")
        return RecognitionDecision("review", "review", "ALL_PATHS_WEAK")
