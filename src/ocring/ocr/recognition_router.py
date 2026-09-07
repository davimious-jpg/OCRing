from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RecognitionRoute:
    primary_path: tuple[str, ...]
    fallback_path: tuple[str, ...]


class RecognitionRouter:
    def route(self, field_name: str, context: dict[str, str] | None = None) -> RecognitionRoute:
        del context
        routes = {
            "item_name": RecognitionRoute(
                primary_path=("classic_ocr", "dictionary_match"),
                fallback_path=("local_ai_fallback",),
            ),
            "item_rarity": RecognitionRoute(
                primary_path=("roman_numeral_ocr", "color_classifier", "text_ocr"),
                fallback_path=("local_ai_fallback",),
            ),
            "item_synergy": RecognitionRoute(
                primary_path=("classic_ocr", "known_synergy_dictionary"),
                fallback_path=("local_ai_fallback",),
            ),
            "item_count": RecognitionRoute(
                primary_path=("numeric_ocr", "regex"),
                fallback_path=(),
            ),
            "item_type": RecognitionRoute(
                primary_path=("dictionary_classification", "context_from_item_name"),
                fallback_path=("local_ai_fallback",),
            ),
        }
        return routes.get(
            field_name,
            RecognitionRoute(primary_path=("classic_ocr",), fallback_path=("local_ai_fallback",)),
        )
