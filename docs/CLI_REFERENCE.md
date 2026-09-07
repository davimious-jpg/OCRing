# OCRing CLI Reference

The primary OCRing experience is GUI-based. These commands are for diagnostics, automation, and scripting.

## Launch Modes

Launch the GUI shell:

```powershell
python run_ocring.py
```

Use CLI behavior instead of the GUI when you pass diagnostic flags or supported commands:

```powershell
python run_ocring.py --input frame.png --profile defiance
python run_ocring.py --fixture fixtures/example_session.json
```

## Core Diagnostic Commands

- `ocring --input <frame.png> --profile <profile_id>`
- `ocring --input <frame1.png> <frame2.png> --profile <profile_id>`
- `ocring --fixture <fixture.json>`

## Review

- `ocring review --session <session_id>`

## Recovery

- `ocring recover --session <session_id>`
- `ocring recover --session <session_id> --discard`
- `ocring checkpoint --session <session_id> --force`

## Search And Export

- `ocring search --query "<query>"`
- `ocring search --query "<query>" --export csv --output results.csv`
- `ocring export --session <session_id> --format csv --output inventory.csv`
- `ocring saved-search --list`
- `ocring saved-search --save "Epic SMGs" --query "rarity:Tier III AND type:SMG"`

## Profiles

- `ocring profile-editor`
- `ocring profile-validate --profile <profile_id>`
- `ocring profile-list`
- `ocring profile-export --profile <profile_id> --output shared.ocring-profile`
- `ocring profile-import --package shared.ocring-profile`
- `ocring profile-import --package shared.ocring-profile --overwrite`

## Generic Mode

- `ocring generic-mode`
- `ocring scan --generic --profile <generic_id> --input frame.png --region x1,y1,x2,y2`

## Notes

- Use the GUI for the normal scan-review-commit workflow.
- Use the CLI when you need fixture replay, scripted validation, automation, or targeted diagnostics outside the main shell.
