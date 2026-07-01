# Window Capture Tool (Python)

A simple desktop app for automated window capture with post-capture key action.

## Features

- Select target window
- Set delay time (seconds)
- Select post-capture action (`None`, `Right Arrow`, `Down Arrow`, `Page Down`)
- Start/Stop capture loop
- Capture once manually
- Choose output folder

## Requirements

- Python 3.10+
- macOS or Windows

## Install

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -U pip
python -m pip install -r requirements.txt
```

## Run

```bash
source .venv/bin/activate
python main.py
```

or

```bash
source .venv/bin/activate
python screen_capture_app.py
```

## Notes for macOS

You may need to grant permissions in System Settings:

- Privacy & Security > Screen Recording
- Privacy & Security > Accessibility

Without these permissions, screenshot capture or key presses may fail.

If you see `ModuleNotFoundError: No module named '_tkinter'` on Homebrew Python:

```bash
brew install python-tk@3.14
```
