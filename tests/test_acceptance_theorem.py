from __future__ import annotations

from ocring.ocr.acceptance_theorem import AcceptanceResult, evaluate_acceptance


def test_acceptance_theorem_accepts_valid_record() -> None:
    evaluation = evaluate_acceptance(
        {
            "definition_used": "Weapon",
            "required_fields": ("item_name", "item_rarity", "item_count"),
            "field_evidence": {
                "item_name": {"visible_text": "Power Bore"},
                "item_rarity": {"tier": "Tier IV", "color": "Purple"},
                "item_count": {"visible_numeric": "2"},
            },
            "hard_profile_constraint_violated": False,
            "unresolved_contradictions": 0,
            "permitted_contradictions": 0,
            "identity_established": True,
            "scan_provenance_exists": True,
            "acceptance_policy_permits": True,
        }
    )

    assert evaluation.result is AcceptanceResult.ACCEPTED
    assert "ACCEPTANCE_THEOREM_SATISFIED" in evaluation.reasons


def test_acceptance_theorem_routes_evidence_failure_to_review() -> None:
    evaluation = evaluate_acceptance(
        {
            "definition_used": "Weapon",
            "required_fields": ("item_name", "item_count"),
            "field_evidence": {
                "item_name": {"visible_text": "Power Bore"},
                "item_count": {},
            },
            "hard_profile_constraint_violated": False,
            "unresolved_contradictions": 0,
            "permitted_contradictions": 0,
            "identity_established": True,
            "scan_provenance_exists": True,
            "acceptance_policy_permits": True,
        }
    )

    assert evaluation.result is AcceptanceResult.NEEDS_REVIEW
    assert "EVIDENCE_REQUIREMENT_FAILED:item_count" in evaluation.reasons


def test_acceptance_theorem_rejects_hard_constraint_violation() -> None:
    evaluation = evaluate_acceptance(
        {
            "definition_used": "Weapon",
            "required_fields": (),
            "field_evidence": {},
            "hard_profile_constraint_violated": True,
            "identity_established": True,
            "scan_provenance_exists": True,
            "acceptance_policy_permits": True,
        }
    )

    assert evaluation.result is AcceptanceResult.REJECTED


def test_acceptance_theorem_user_verification_overrides_policy() -> None:
    evaluation = evaluate_acceptance(
        {
            "definition_used": "Weapon",
            "required_fields": (),
            "field_evidence": {},
            "hard_profile_constraint_violated": False,
            "unresolved_contradictions": 0,
            "permitted_contradictions": 0,
            "identity_established": True,
            "scan_provenance_exists": True,
            "acceptance_policy_permits": False,
            "user_verified": True,
        }
    )

    assert evaluation.result is AcceptanceResult.ACCEPTED
    assert "USER_VERIFIED_OVERRIDE" in evaluation.reasons
