# OCRing

![Release](https://img.shields.io/badge/release-1.0.0-blue)

OCRing is a Windows-first external inventory OCR companion focused on capture, review, continuity, and export workflows for game inventories.

## Overview

OCRing now ships with:

- OCR scan diagnostics and session reports
- human review workflow with inventory commit
- checkpoint and recovery support
- search and export tooling
- profile editor and generic game mode
- local profile package export and import

## Installation

1. Install Python 3.11 or newer on Windows.
2. Install dependencies with `python -m pip install -e .`
3. Run the CLI with `ocring --help` or `python run_ocring.py --help`
4. For packaged delivery, build `run_ocring.exe` with PyInstaller and compile `installer/installer.iss`

## Quick Start

1. Launch the profile editor: `ocring profile-editor`
2. Validate a profile: `ocring profile-validate --profile defiance`
3. Run a frame diagnostic: `ocring --input path\to\frame.png --profile defiance`
4. Review a saved session: `ocring review --session <session_id>`
5. Export inventory results: `ocring export --session <session_id> --format csv --output inventory.csv`

## More Docs

- [USER_GUIDE.md](./USER_GUIDE.md)
- [CLI_REFERENCE.md](./CLI_REFERENCE.md)
- [PROFILE_CREATION.md](./PROFILE_CREATION.md)
