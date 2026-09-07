# Profile Creation

## Standard Profiles

Standard profiles define OCR rules for known inventory layouts.

Expected sections:

- `inventory_definitions`
- `screens`
- `parsing_rules`
- `rarity_rules`
- `compatibility_rules`

## Field Definitions

Each inventory definition should include:

- `canonical_id`
- `label`
- `required`
- `extraction_source`

Avoid duplicate `canonical_id` values.

## Screen Layouts And ROIs

Each screen entry should include:

- `screen_class`
- `roi` with `x1`, `y1`, `x2`, `y2`

ROIs must describe a positive-area rectangle.

## Rarity Rules

Each rarity rule should map:

- tier
- color
- display name

## Generic Profiles

Generic profiles are manual and lighter-weight.

They store:

- up to 5 custom fields
- `field_name`
- `field_type`
- `field_source`
- `region_roi`
- `scan_scope`
- `generic_session_id`

## Validation

Validate any profile with:

`ocring profile-validate --profile <profile_id>`
