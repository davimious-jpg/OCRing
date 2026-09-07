from __future__ import annotations

from ocring.ocr.recognition_router import RecognitionRouter


def test_recognition_router_returns_field_specific_routes() -> None:
    router = RecognitionRouter()

    name_route = router.route("item_name", {"weapon_type": "Rocket Launcher"})
    rarity_route = router.route("item_rarity", {})
    count_route = router.route("item_count", {})

    assert name_route.primary_path == ("classic_ocr", "dictionary_match")
    assert name_route.fallback_path == ("local_ai_fallback",)
    assert rarity_route.primary_path == ("roman_numeral_ocr", "color_classifier", "text_ocr")
    assert count_route.primary_path == ("numeric_ocr", "regex")
    assert count_route.fallback_path == ()
