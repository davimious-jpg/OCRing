# OCRing

OCRing is a Windows-first, game-agnostic external screen-reading inventory companion. It records visible game inventory frames, extracts OCR evidence after capture, reconstructs temporally distinct inventory identities, and routes uncertain results to review instead of inventing unsupported data. Defiance is the first supported profile.

```
Status: Active Development
Testing: In Progress
```

This repository is published as-is, at its current working state. It is not presented as production-complete.

## Recorded Workflow

The current primary capture workflow is a deferred record-then-extract pipeline, not live per-frame OCR:

```
Start Scan
-> Record
-> Stop
-> FINALIZING
-> RECORDED_VERIFIED
-> Extract
-> Review / Auto-store
```

Recording preserves external, visible pixels only. OCR runs after the recording is stopped and finalized, asynchronously off the UI thread, with progress reporting and a stall watchdog so the GUI stays responsive during extraction. A live per-frame scan path (see GUI Quick Start below) also remains available for a single, non-scrolling screen.

## Current Verified State

- recorder / finalization lifecycle: working (`RECORDED_VERIFIED` manifest gate, frame/summary reconciliation against the written spool)
- async recorded extraction: working (runs off the UI thread; the GUI stays responsive during extraction)
- extraction progress reporting and stall watchdog: working
- temporal same-frame preprocess collapse: repaired (multiple OCR preprocess variants of one observation now correctly count as a single observation, with full provenance preserved)
- row-level OCR text-quality gate: implemented (a second, evidence-only gate - confidence, cross-frame agreement, preprocess agreement - independent of temporal stability, that can route a *temporally stable but textually low-quality* reading to review; never a dictionary or word-plausibility check)
- recorded scrolling assembly: now supports multiple temporally distinct identities per reused screen row (a screen row is treated as an observation coordinate during a scroll, not a fixed inventory identity, so the same row can correctly yield several different real items observed at different times)
- SQLite persistence: working

Current full test suite:

```
343 passed, 0 failed
```

## Real Recorded Proof

A real Defiance recording (approximately 50 mods scrolled) was used for replay validation. The current temporal-identity-aware assembly, run against that same preserved recording, produced:

```
310 assembled records
206 auto-saved
32 needs review
72 HOLD/UNKNOWN
```

**These numbers are not yet considered final inventory-accuracy proof.** Further live validation against real gameplay is still in progress to measure:

- true capture coverage
- duplicate / over-fragmented records
- multiplicity accuracy
- practical scroll speed
- false positive / false negative rate

OCRing is not presented as production-complete.

## Safety / Design Boundary

OCRing:

- reads only visible pixels / windows / regions on screen
- does not read game process memory
- does not inject into games
- does not bypass anti-cheat
- does not sniff packets
- does not automate gameplay

## Truth Policy

**OCR observation is evidence, not truth.**

Unknown or uncertain data is routed to review rather than fabricated. Item names are never dictionary-corrected or synthesized; when evidence is ambiguous or a field cannot be temporally correlated to the right identity, the record is marked accordingly (`FIELD_NOT_VISIBLE`, `UNKNOWN`, `HOLD`, `NEEDS_REVIEW`) instead of guessed.

Systematic OCR errors are not claimed to be fully solved. An internally consistent, high-confidence misread - the OCR engine confidently and repeatedly reading the same text the same wrong way - is a documented, known limitation: evidence-only signals (confidence, cross-frame agreement, preprocess agreement) cannot distinguish a confident systematic error from a confident correct reading, and OCRing does not use a dictionary or reference catalogue to paper over that gap.

## GUI Quick Start

1. Launch the app:

   ```powershell
   python run_ocring.py
   ```

2. In the main window, stay on **Scan** and choose:
   - a game profile
   - a target window
   - a scan scope
   - a recognition mode

3. Click **Test Capture** to verify the preview image and confirm the selected region is correct.

4. If needed, click **Calibrate Region** and adjust the ROI before scanning.

5. Choose a capture path:
   - **Recorded (recommended for scrolling inventories):** click **Start Recording** (or the overlay's **Record** control), scroll the inventory, then **Stop Recording**. Once the overlay shows `RECORDED VERIFIED`, click **Extract From Recording**. Extraction runs asynchronously with visible progress and hands off to Review when finished.
   - **Live (a single, non-scrolling screen):** start a live scan with **Start Scan** or the global hotkey `Alt+F8`, and watch the live overlay switch to **LIVE**, showing runtime status such as capture rate, queue depth, continuity, and buffer health. Stop with `Alt+F8` or the stop path in the app.

6. In **Review**, accept, reject, or correct records, then use **Commit Inventory** to write verified records into the local SQLite inventory.

7. Use the built-in navigation to move to **Inventory**, **Profiles**, **Settings**, **Recovery**, or **Backup** as needed.

## What The App Includes

- Main window with app navigation
- Scan Setup with preview and ROI calibration
- Recorded capture (Start Recording / Stop Recording / Extract From Recording) for scrolling inventories, with a finalized-recording boundary and async, progress-reported extraction
- Global `Alt+F8` scan hotkey for the live scan path
- Live overlay with capture and processing metrics
- Temporal identity assembly (multiple distinct records per reused screen row during a recorded scroll) and a row-level text-quality gate ahead of auto-store
- Review-first verification and commit flow
- SQLite-backed verified inventory
- Profile management, recovery, backup, search, and export tools

## Advanced / Diagnostics

The primary OCRing experience is GUI-based. CLI commands remain available for diagnostics, replay fixtures, automation, and scripting.

Examples:

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
