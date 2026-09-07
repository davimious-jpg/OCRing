from __future__ import annotations

from dataclasses import dataclass

from .generic_profile import GenericProfile
from .profile import Profile


@dataclass(frozen=True)
class ValidationIssue:
    severity: str
    message: str
    field: str


def validate_profile(profile: Profile) -> list[ValidationIssue]:
    if isinstance(profile, GenericProfile):
        return _validate_generic_profile(profile)
    issues: list[ValidationIssue] = []
    issues.extend(_validate_inventory_definitions(profile))
    issues.extend(_validate_rarity_rules(profile))
    issues.extend(_validate_compatibility_rules(profile))
    issues.extend(_validate_screen_layouts(profile))
    if not issues:
        issues.append(ValidationIssue(severity="INFO", message="Profile validation passed.", field="profile"))
    return issues


def _validate_inventory_definitions(profile: Profile) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    canonical_ids: list[str] = []
    for index, definition in enumerate(profile.inventory_definitions):
        canonical_id = str(definition.get("canonical_id") or "").strip()
        if not canonical_id:
            issues.append(ValidationIssue("ERROR", "Inventory definition is missing canonical_id.", f"inventory_definitions[{index}].canonical_id"))
            continue
        canonical_ids.append(canonical_id)
        if bool(definition.get("required")) and not str(definition.get("extraction_source") or "").strip():
            issues.append(
                ValidationIssue(
                    "ERROR",
                    f"Required field '{canonical_id}' must define an extraction_source.",
                    f"inventory_definitions[{index}].extraction_source",
                )
            )
    duplicates = sorted({item for item in canonical_ids if canonical_ids.count(item) > 1})
    for canonical_id in duplicates:
        issues.append(ValidationIssue("ERROR", f"Duplicate canonical_id '{canonical_id}' detected.", "inventory_definitions"))
    return issues


def _validate_rarity_rules(profile: Profile) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    for index, rule in enumerate(profile.rarity_rules):
        tier = str(rule.get("tier") or "").strip()
        color = str(rule.get("color") or "").strip()
        name = str(rule.get("name") or "").strip()
        if tier and not color:
            issues.append(ValidationIssue("ERROR", f"Rarity tier '{tier}' is missing a color mapping.", f"rarity_rules[{index}].color"))
        if tier and not name:
            issues.append(ValidationIssue("WARNING", f"Rarity tier '{tier}' is missing a display name.", f"rarity_rules[{index}].name"))
    return issues


def _validate_compatibility_rules(profile: Profile) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    screen_classes = {str(screen.get("screen_class") or "").strip() for screen in profile.screens if str(screen.get("screen_class") or "").strip()}
    for index, rule in enumerate(profile.compatibility_rules):
        screen_class = str(rule.get("screen_class") or "").strip()
        if not screen_class:
            issues.append(ValidationIssue("WARNING", "Compatibility rule should name a screen_class.", f"compatibility_rules[{index}].screen_class"))
            continue
        if screen_classes and screen_class not in screen_classes:
            issues.append(
                ValidationIssue(
                    "ERROR",
                    f"Compatibility rule references unknown screen_class '{screen_class}'.",
                    f"compatibility_rules[{index}].screen_class",
                )
            )
    return issues


def _validate_screen_layouts(profile: Profile) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    for index, screen in enumerate(profile.screens):
        screen_class = str(screen.get("screen_class") or "").strip()
        roi = screen.get("roi")
        if not screen_class:
            issues.append(ValidationIssue("ERROR", "Screen definition is missing screen_class.", f"screens[{index}].screen_class"))
        if not isinstance(roi, dict):
            issues.append(ValidationIssue("ERROR", "Screen definition is missing roi bounds.", f"screens[{index}].roi"))
            continue
        try:
            x1 = int(roi["x1"])
            y1 = int(roi["y1"])
            x2 = int(roi["x2"])
            y2 = int(roi["y2"])
        except (KeyError, TypeError, ValueError):
            issues.append(ValidationIssue("ERROR", "ROI must include numeric x1, y1, x2, and y2.", f"screens[{index}].roi"))
            continue
        if x2 <= x1 or y2 <= y1:
            issues.append(ValidationIssue("ERROR", "ROI bounds must define a positive area.", f"screens[{index}].roi"))
    return issues


def _validate_generic_profile(profile: GenericProfile) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    if len(profile.custom_fields) > 5:
        issues.append(ValidationIssue("ERROR", "Generic profiles may define at most 5 custom fields.", "custom_fields"))
    for index, field in enumerate(profile.custom_fields):
        field_name = str(field.get("field_name") or "").strip()
        field_type = str(field.get("field_type") or "").strip()
        field_source = str(field.get("field_source") or "").strip()
        if not field_name:
            issues.append(ValidationIssue("ERROR", "Generic field is missing field_name.", f"custom_fields[{index}].field_name"))
        if field_type not in {"text", "number", "boolean"}:
            issues.append(ValidationIssue("ERROR", f"Unsupported generic field_type '{field_type}'.", f"custom_fields[{index}].field_type"))
        if not field_source:
            issues.append(ValidationIssue("ERROR", "Generic field is missing field_source.", f"custom_fields[{index}].field_source"))
    try:
        x1 = int(profile.region_roi.get("x1", 0))
        y1 = int(profile.region_roi.get("y1", 0))
        x2 = int(profile.region_roi.get("x2", 0))
        y2 = int(profile.region_roi.get("y2", 0))
    except (TypeError, ValueError):
        issues.append(ValidationIssue("ERROR", "Generic region ROI must contain integer bounds.", "region_roi"))
    else:
        if x2 <= x1 or y2 <= y1:
            issues.append(ValidationIssue("ERROR", "Generic region ROI must define a positive area.", "region_roi"))
    if not issues:
        issues.append(ValidationIssue(severity="INFO", message="Profile validation passed.", field="profile"))
    return issues
