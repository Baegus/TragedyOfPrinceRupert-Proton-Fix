# Tragedy of Prince Rupert - Proton performance fix

This patch fixes severe performance degradation in the Windows version of
*Tragedy of Prince Rupert* when running on Steam Deck through Proton.

## Cause

The game uses Delphi and GLScene. It renders explicitly from its main loop,
but GLScene also requests a Windows repaint whenever the scene changes. Under
Proton, active gameplay can generate more than 60,000 redundant
`InvalidateRect` calls per second. Those calls consume most of the frame time
and cause the game's fixed-step update loop to fall behind and repeatedly try
to catch up.

## Fix

The patch disables only the redundant repaint request made by GLScene's
`TGLSceneViewer` buffer-change callback. Explicit rendering, other repaint
paths, scene updates, input, resizing, and graphics features remain unchanged.

The patch has been tested on the Steam Deck, where it removes
the progressive slowdown without breaking rendering or gameplay.

## Patching

Requirements:

- Python 3
- [`pefile`](https://pypi.org/project/pefile/)
- An unmodified Steam copy of `topr.exe`

Install the dependency:

```sh
python -m pip install pefile
```

Place `deck_patch.py` beside the original game executable and run:

```sh
python deck_patch.py
```

The script creates `topr-original.exe` as a backup, then safely replaces
`topr.exe` with the patched version. After it finishes, launch the game
normally. Running the script again detects that the game is already patched
and makes no changes.

To patch an installation in another directory, specify its executable:

```sh
python deck_patch.py --input /path/to/topr.exe
```

The patcher refuses files it does not recognize and never overwrites an
existing backup unless it exactly matches the supported original executable.

The supported original executable has this SHA-256 fingerprint:

```text
ca846f1a08c9da22d2aa6f877fe691e98b1e83da6e492557c5f8d410fa419cd8
```

Steam updates may replace the game executable. Run the patcher again against
the updated file only if its fingerprint is supported by this repository.

## Related project

- [HROT - Proton performance fix](https://github.com/Baegus/HROT-Proton-Fix)
