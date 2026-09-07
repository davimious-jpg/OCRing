from __future__ import annotations


def build_accept_reason(*, candidate_value: str, evidence_lines: tuple[str, ...], contradictions: tuple[str, ...]) -> str:
    lines = [candidate_value, "", "Accepted because:"]
    lines.extend(f"- {line}" for line in evidence_lines)
    if not contradictions:
        lines.append("- no contradictions detected")
    return "\n".join(lines)


def build_review_reason(*, evidence_lines: tuple[str, ...], uncertainty_lines: tuple[str, ...]) -> str:
    lines = ["Needs Review", "", "Reason:"]
    lines.extend(f"- {line}" for line in evidence_lines)
    lines.extend(f"- {line}" for line in uncertainty_lines)
    return "\n".join(lines)
