# OCRing Release Notes

## v1.0.0 - 2026-08-16

OCRing v1.0.0 is the first consolidated release cut for the governed OCR workflow.

## Key Features

- scan diagnostics and session reports
- human review workflow
- checkpoint and recovery
- search and export
- profile editor
- generic game mode
- community profile sharing through local package export/import

## Implementation Summary

- project continuity and OCR subsystem architecture and roadmap
- field locking and scan integrity
- foundational OCR subsystem implementation (fixture replay, evidence provenance, scroll identity)
- completeness overstatement and identity-collapse repair
- scroll-overlap identity
- runtime trim pressure handling
- review UI scaffolding
- session checkpoint and recovery
- search and export enhancements
- profile editor
- generic game mode
- community profile sharing

## Known Limitations

- OCR quality still depends heavily on input capture quality and profile accuracy
- generic mode is manual-first and does not yet include AI-assisted field discovery
- installer verification depends on local availability of Inno Setup

## Upgrade Path

- existing local profile folders remain usable
- packaged profile imports can be used to move profiles between installs
- no database migration path is currently required for this release
