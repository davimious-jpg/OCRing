# OCRing User Guide

## Start Here

OCRing is now a GUI-first application. The normal user flow is:

1. Launch the OCRing app.
2. Configure the scan in **Scan Setup**.
3. Verify the capture region with **Test Capture**.
4. Start a live scan.
5. Scroll the inventory while OCRing watches the screen.
6. Stop the scan and move into **Review**.
7. Accept, reject, or correct records.
8. Commit verified results into the local SQLite inventory.

## Launch OCRing

Start the app from the project root:

```powershell
python run_ocring.py
```

This opens the main OCRing window and lands on **Scan Setup**.

## Configure Scan Setup

In the **Scan** screen, choose the active scan context:

- **Game Profile**: the profile that defines how OCRing interprets the game inventory
- **Window**: the target game window
- **Scan Scope**: the section you intend to scan
- **Recognition Mode**: fast, balanced, or accurate behavior
- **Memory Limit**: the current retention budget used by the app

If the region needs adjustment, use **Calibrate Region** to set the ROI stored with the profile.

## Test Capture

Before running a live scan, click **Test Capture**.

Expected result:

- the preview panel updates with a sample capture
- the current ROI is drawn over the preview
- the status line reports that the test capture completed

If the preview is wrong, recalibrate the region or choose the correct window before continuing.

## Start A Live Scan

You can start a scan in either of these ways:

- click **Start Scan**
- press the global hotkey `Alt+F8`

When the scan starts:

- the app status changes to **LIVE**
- the overlay appears
- capture and processing metrics begin updating

## Watch The Live Overlay

During a scan, the overlay provides a quick view of runtime health, including:

- capture rate
- useful/retained frames
- extraction and verified record rates
- queue depth
- continuity state
- buffer usage

If capture is interrupted or focus is lost, the status can move out of **LIVE** and the app may pause capture.

## Scroll Through The Inventory

With the scan active, scroll through the inventory normally. OCRing uses visible screen evidence only and builds candidate records from what it can observe in motion.

For best results:

- keep the inventory visible
- scroll steadily enough for readable frames
- let the overlay warnings guide you if processing falls behind

## Stop The Scan

Stop the scan with:

- `Alt+F8`, or
- the app stop path

When the scan ends, OCRing transitions from **Scan** into the **Review** screen automatically and loads the candidate session that was just produced.

## Review Records

The **Review** screen is where OCRing becomes authoritative.

For each candidate record, you can:

- **Accept** it
- **Reject** it
- **Correct** one or more fields

The review tools show the candidate summary, status, and supporting provenance/evidence details for the selected record.

## Commit To Inventory

After reviewing the records, click **Commit Inventory**.

This writes accepted and corrected records into the local SQLite inventory database. Rejected records are not committed.

By default, OCRing now saves user-visible files under `E:/Ocring/output/`:

- `E:/Ocring/output/export/` for CSV, JSON, and package exports
- `E:/Ocring/output/sessions/` for committed session bundles and manifests
- `E:/Ocring/output/evidence/` for saved evidence/debug artifacts when debug capture is enabled

## Search, Export, And Manage Data

After commit, use the main app navigation to move to:

- **Inventory** for search and export workflows
- **Profiles** for profile management
- **Settings** for hotkeys, recognition preferences, privacy, and storage settings
- **Recovery** for session recovery and checkpoint handling
- **Backup** for backup-related actions

In **Settings > Storage**, use **Open Output Folder** to jump directly to the current save location in Explorer.

## Appendix: CLI Commands

The CLI is still supported, but it is now the advanced and diagnostic path rather than the default workflow.

### Diagnostic Inputs

```powershell
python run_ocring.py --input frame.png --profile defiance
python run_ocring.py --fixture fixtures/example_session.json
```

### Review

```powershell
python -m ocring.cli review --session <session_id>
```

### Recovery And Checkpoints

```powershell
python -m ocring.cli recover --session <session_id>
python -m ocring.cli checkpoint --session <session_id> --force
```

### Search And Export

```powershell
python -m ocring.cli search --query "rarity:Tier IV AND type:Rocket Launcher"
python -m ocring.cli export --session <session_id> --format csv --output inventory.csv
```

### Profiles

```powershell
python -m ocring.cli profile-editor
python -m ocring.cli profile-validate --profile <id>
python -m ocring.cli profile-export --profile <id> --output shared.ocring-profile
python -m ocring.cli profile-import --package shared.ocring-profile
```
