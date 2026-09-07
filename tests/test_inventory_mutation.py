from __future__ import annotations

from ocring.ocr.inventory_mutation import MutationType, create_mutation


def test_inventory_mutation_captures_semantics() -> None:
    mutation = create_mutation(
        MutationType.QUANTITY_CHANGE,
        session_id="s1",
        record_id="r1",
        old_state={"item_count": "1"},
        new_state={"item_count": "2"},
        reason="SCROLL_RECONCILIATION",
    )

    assert mutation.mutation_type is MutationType.QUANTITY_CHANGE
    assert mutation.old_state["item_count"] == "1"
    assert mutation.new_state["item_count"] == "2"
    assert mutation.reason == "SCROLL_RECONCILIATION"

