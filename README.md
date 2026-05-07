# Paragon Clicker

Windows Python GUI for board-by-board paragon clicking.

This tool accepts a D2Core planner URL such as `https://www.d2core.com/d4/planner?bd=1Tok`, parses the paragon layout directly from D2Core, and then clicks one board at a time inside Diablo IV.

## Requirements

- Windows 10 or Windows 11
- Python 3.11+
- `uv`
- Diablo IV running in a visible window

## Install uv

PowerShell:

```powershell
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

## Install

```bash
uv sync
```

## Run

```bash
uv run paragon-clicker
```

## Download Prebuilt EXE

- Prebuilt Windows single-file builds are published in GitHub Releases
- Download the latest `paragon-clicker-windows-x64.zip`
- Extract it and run `paragon-clicker.exe`
- Python is not required when using the release build

## What The App Does

- Parses a D2Core planner URL and extracts the `bd` build id
- Calls D2Core planner APIs directly
- Downloads paragon data definitions
- Builds a board-by-board click sequence in Python
- Lets you select the board rectangle on screen
- Splits the board rectangle into a `21 x 21` grid
- Clicks the center of each target cell in sequence

## CI And Release

- GitHub Actions builds a Windows single-file executable on every push to `main`
- Pushing a tag like `v0.1.0` also creates a GitHub Release and uploads the built zip artifact

## Workflow

1. Paste a D2Core planner URL like `https://www.d2core.com/d4/planner?bd=1Tok`
2. Click `Parse URL`
3. Choose a variant
4. Enter your current available paragon points in `Current Points`
5. Click `Apply Strategy`
6. Confirm `Target Process` is `Diablo IV.exe`
7. Choose one board from the dropdown
8. Click `Select Region`
9. Drag from the board rectangle's top-left corner to the bottom-right corner while watching the live `21 x 21` overlay preview
10. Click `Preview Grid Clicks` to show the on-screen `21 x 21` overlay and click points
11. Set delay / interval
12. Start clicking

## Progression Strategy

- The app first spends the minimum required points to connect selected legendary nodes and glyph socket nodes
- After that, any remaining points are allocated toward the remaining planned nodes by rarity priority
- Higher-rarity nodes are preferred before lower-rarity nodes
- Connector nodes on the path are still included when needed to reach a higher-priority target

## Region Selection Rule

- The selected region must be the full visible rectangular board area
- Start from the board rectangle top-left corner
- End at the board rectangle bottom-right corner
- The tool divides that rectangle evenly into `21 x 21`
- Each click is performed at the center of the matched grid cell
- During dragging, the selection overlay already shows the live grid and target click points to help alignment

## Grid Overlay Preview

- `Preview Grid Clicks` hides the main window and shows a full-screen overlay
- Cyan lines show the `21 x 21` grid
- Gold dots show the click centers that will be used
- `Start` and `End` markers highlight the first and last click
- Click anywhere or press `Esc` to close the overlay and return to the app

## Safety Notes

- Before clicking, the app tries to activate the visible window owned by `Target Process`
- Window activation now only moves focus to an already visible, non-minimized target window and does not restore or reposition it
- Default target process is `Diablo IV.exe`
- If no visible window for that process is found, clicking is aborted
- A built-in fail-safe stays enabled: moving the mouse to the top-left corner of the primary screen should interrupt clicking
- Selection, preview, and actual clicks are all based on physical screen coordinates to reduce DPI-related offset issues across different Windows machines
- For first-time testing, use a larger start delay such as `5s`
- For first-time testing, use a larger click interval such as `0.2s`

## Troubleshooting

### ImportError or missing package

Run:

```bash
uv sync
```

### The app cannot activate Diablo IV

- Confirm the process name is really `Diablo IV.exe` in Task Manager
- If needed, change `Target Process` in the app
- If Diablo IV is running as Administrator, launch this tool as Administrator too

### Clicks land in the wrong place

- Re-select the board region carefully
- Make sure you selected the whole board rectangle, not only the internal node area
- Make sure the board stays in the same screen position before clicking starts
- Re-test with a simpler board first

### The parser fails for a planner URL

- Confirm the link contains `?bd=`
- Confirm the build is still accessible on D2Core
- Retry in case of temporary network failure

## Notes

- The app fetches D2Core build data and paragon data directly from the planner URL.
- Before clicking, the app tries to activate the visible window owned by the target process name.
- The selected rectangle is evenly split into a 21x21 logical grid.
- Each click targets the center of its grid cell.
- Click positions are computed from `rotatedCoord` so they match the board orientation already visible on screen.
- A built-in fail-safe stays enabled. Moving the mouse to the top-left corner of the primary screen should abort further clicks.
