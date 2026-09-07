# OCRing

OCRing is a Windows-first, game-agnostic external screen-reading inventory companion. It records visible game inventory frames, extracts OCR evidence after capture, reconstructs temporally distinct inventory identities, and routes uncertain results to review instead of inventing unsupported data. Defiance is the first supported profile.

```
Status: Active Development
Testing: In Progress
License: MIT
```

This repository is published as-is, at its current working state. It is not presented as production-complete.

## Quick Start

```
Launch OCRing
-> Select game window
-> Start Scan
-> Record
-> Scroll inventory
-> Stop
-> Wait for RECORDED VERIFIED
-> Extract
-> Wait for processing
-> Review results
```

This is the recommended path for scrolling inventories. See [Using Recorded Inventory Capture](#using-recorded-inventory-capture) below for the full step-by-step walkthrough, including the exact on-screen labels.

## Installation / Requirements

- **OS:** Windows-first. OCRing relies on Windows-specific window capture and overlay behavior; other platforms are not currently supported.
- **Python:** 3.11 or newer.
- **OCR engine:** OCRing shells out to a local [Tesseract OCR](https://github.com/tesseract-ocr/tesseract) installation. Install Tesseract separately and make sure the `tesseract` executable is on your system `PATH`. (If Tesseract isn't found, OCRing will fall back to the optional `rapidocr_onnxruntime` package if it happens to be installed, but Tesseract is the supported default path.)

Run from source:

```powershell
git clone https://github.com/davimious-jpg/OCRing.git
cd OCRing
python -m pip install -e .
python run_ocring.py
```

`python run_ocring.py` with no arguments launches the OCRing GUI. Installing with `pip install -e .` also registers an `ocring` command for the CLI utilities described in [Advanced / CLI](#advanced--cli).

Dependencies (installed automatically by `pip install -e .`): `keyboard`, `Pillow`, `psutil`, `pytesseract`.

## Using Recorded Inventory Capture

Recorded capture is the primary workflow, built for scrolling inventories that don't fit on one screen.

1. Open the game and its inventory screen.
2. Start OCRing (`python run_ocring.py`).
3. On the **Scan** tab, choose the game profile and select the correct game window from the **Window** dropdown (use **Refresh Windows** if it isn't listed yet).
4. Click **Start Scan**.
5. Return to the game.
6. Use the OCRing overlay that appears over the game window.
7. Click the overlay's **Record** button.
8. Scroll through the inventory at a controlled, steady pace.
9. Click **Stop** on the overlay.
10. Wait while the overlay shows `FINALIZING...`.
11. Wait for the overlay to show `RECORDED ✓` (it will also show a frame count, e.g. `RECORDED ✓ | F:120`).
12. Click **Extract** on the overlay (or **Extract From Recording** back on the **Scan** tab).
13. Watch the extraction progress indicator while OCRing processes the recording off the UI thread.
14. Review the extracted records once extraction completes.

**Important:** the number shown during and after recording (`F:<count>`) is a **frame count** — how many video frames were captured — not a count of inventory items. A single item is normally observed across many frames while it stays on screen; extraction is what turns those frames into individual item records.

## Review and Auto-Save

After extraction, OCRing does not treat every reading as final:

- Records with strong, stable, high-confidence evidence across multiple frames may be **auto-saved** directly into your inventory.
- Records where the evidence is uncertain, conflicting, or too weak are sent to **Review** instead of being guessed.
- OCRing never invents or dictionary-corrects unresolved text — if it can't be confidently read, it's marked as unresolved rather than filled in.
- You should still look over anything routed to Review before accepting it, especially for unusual or hard-to-read item names.

Keep this distinction in mind:

```
recorded frames != inventory items
```

Many frames can (and normally do) correspond to one item; extraction and review are what resolve frames down to actual inventory records.

## Search / Inventory

Once records are committed, use the **Inventory** tab (in the app's left-hand navigation) to view and search them. It provides:

- A **Search** field with a **Run** button to query saved records.
- **Saved** searches, which can be reloaded with **Load**.
- Filters and a **Sort** control to narrow and order results.
- **Export CSV** / **Export JSON** buttons to export the current results, and **Show In Folder** to locate the exported file.

## Tips for Better Results

- Keep each item row visible on screen long enough to be observed across multiple frames before scrolling past it.
- Avoid extremely fast scrolling — give OCRing time to capture each row.
- Pause briefly every so often while scrolling rather than scrolling in one continuous motion.
- Keep the inventory panel unobstructed by other windows, tooltips, or in-game popups.
- Use a normal, readable UI scale in-game; very small or very large scaling can hurt OCR accuracy.
- Avoid letting other overlays or UI elements cover item names during capture.

## Current Limitations

- Testing is still in progress; OCRing is not presented as production-complete.
- OCR can make systematic text-reading mistakes, and confident-but-wrong readings are not always distinguishable from confident-and-correct ones.
- Coverage (how much of a scrolled inventory is actually captured) and duplicate/multiplicity handling are still being validated against real gameplay.
- Unusual game UI layouts may require additional calibration or a dedicated profile.
- OCRing does not currently guarantee complete inventory capture.

A real Defiance recording (approximately 50 mods scrolled) was used for replay validation. The current temporal-identity-aware assembly, run against that same preserved recording, produced:

```
310 assembled records
206 auto-saved
32 needs review
72 HOLD/UNKNOWN
```

These numbers are not yet considered final inventory-accuracy proof. Further validation against real gameplay is still in progress to measure true capture coverage, duplicate/over-fragmented records, multiplicity accuracy, practical scroll speed, and false positive/negative rates.

## Safety

OCRing reads visible pixels only and does not:

- access game process memory
- inject into the game
- bypass anti-cheat
- sniff packets
- automate gameplay

## Truth Policy

**OCR observation is evidence, not truth.**

Unknown or uncertain data is routed to review rather than fabricated. Item names are never dictionary-corrected or synthesized; when evidence is ambiguous or a field cannot be matched to the right record, it is marked accordingly instead of guessed.

Systematic OCR errors are not claimed to be fully solved. An internally consistent, high-confidence misread is a documented, known limitation: evidence-only signals (confidence, cross-frame agreement, preprocess agreement) cannot always distinguish a confident systematic error from a confident correct reading, and OCRing does not use a dictionary or reference catalogue to paper over that gap.

## What The App Includes

- Main window with app navigation (Scan, Inventory, Review, Profiles, Settings, Recovery, Backup)
- Scan Setup with preview and ROI calibration
- Recorded capture (Start Recording / Stop Recording / Extract From Recording) for scrolling inventories, with a finalized-recording boundary and async, progress-reported extraction
- Global `Alt+F8` scan hotkey for the live scan path
- Live overlay with capture and processing metrics
- Temporal identity assembly (multiple distinct records per reused screen row during a recorded scroll) and a row-level text-quality gate ahead of auto-store
- Review-first verification and commit flow
- SQLite-backed verified inventory
- Profile management, recovery, backup, search, and export tools

## Advanced / CLI

The primary OCRing experience is GUI-based. CLI commands remain available for diagnostics, replay fixtures, automation, and scripting.

```powershell
python run_ocring.py --input frame.png --profile defiance
python run_ocring.py --fixture fixtures/example_session.json
python -m ocring.cli extract-recording --input <recording_dir> --profile defiance
python -m ocring.cli review --session <session_id>
python -m ocring.cli search --query "rarity:Tier IV"
```

See the full references here:

- [User Guide](./docs/USER_GUIDE.md)
- [CLI Reference](./docs/CLI_REFERENCE.md)
- [GUI Walkthrough](./docs/GUI_WALKTHROUGH.md)
