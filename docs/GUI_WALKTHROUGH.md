# OCRing GUI Walkthrough

## Main Window

Launch OCRing with:

```powershell
python run_ocring.py
```

The main shell provides top-level navigation for:

- Scan
- Inventory
- Review
- Profiles
- Settings
- Recovery
- Backup

Suggested screenshot placeholder:

- `[Main window screenshot goes here]`

## Scan Setup

The **Scan** screen is the normal starting point.

It includes:

- game/profile selection
- target window selection
- scan scope
- recognition mode
- memory limit
- **Test Capture**
- **Calibrate Region**
- **Start Scan**
- a preview panel for the selected window and ROI

Suggested screenshot placeholder:

- `[Scan Setup screenshot goes here]`

## Test Capture And Calibration

Use **Test Capture** before a live run to confirm:

- the correct window is selected
- the capture path is working
- the ROI is aligned correctly

Use **Calibrate Region** if the preview or region is off.

Suggested screenshot placeholder:

- `[Capture preview screenshot goes here]`

## Live Overlay

When you start a scan, OCRing shows the live overlay with status and runtime metrics.

Typical status progression:

- READY
- LIVE
- PAUSED

The overlay is intended to stay readable while you scroll through the inventory.

Suggested screenshot placeholder:

- `[Overlay screenshot goes here]`

## Review Flow

When the scan stops, OCRing transitions into **Review** automatically for the finished session.

The review screen lets you:

- inspect candidate records
- accept valid records
- reject bad records
- correct fields that need adjustment
- commit the reviewed inventory

Suggested screenshot placeholder:

- `[Review screen screenshot goes here]`

## Inventory And Utilities

After commit, the other screens support the broader workflow:

- **Inventory** for searching and exporting verified records
- **Profiles** for profile management
- **Settings** for hotkeys and app preferences
- **Recovery** for session recovery and checkpoint handling
- **Backup** for backup-related operations

The default output workspace is:

- `E:/Ocring/output/export/` for exports
- `E:/Ocring/output/sessions/` for committed session bundles
- `E:/Ocring/output/evidence/` for saved evidence/debug artifacts

Use **Settings > Storage > Open Output Folder** to open the workspace directly.

Suggested screenshot placeholder:

- `[Inventory / Settings / Recovery screenshot set goes here]`
