# vox2ksh

Converts SOUND VOLTEX `.vox` charts to `.ksh` (KSM/USC), with the reverse-engineering notes behind it.

## What it converts

| part | covers | status |
|---|---|---|
| audio | FX/laser effects, ParamEq, music duck, SE bank, per-sample gains | Done, except the Pitch & Speed effect (id 13), whose phase vocoder is a stand-in |
| notes | BT/FX/laser notes, timing, BPM/time-signature changes, slams, curves | Done |
| camera | lane tilt, spin/swing, zoom | Zoom done. Spin lengths are approximate. Pretilt removal is optional and conservative |

## Layout

* `specs/`: the notes. `specs/evidence/` holds the measurements behind them. `vox_format.md` and `ksh_format.md` cover the formats, `audio_engine.md`, `audio_engine_primer.md`, `camera.md` and `notes.md` cover the conversion.
* `scripts/audio`, `scripts/notes`, `scripts/camera`: the three converters. `scripts/shared` has the `.vox` parser, path resolution and the DLL analysis tools. Each script describes itself in its header.
* `gui/`: the Tkinter app. `build/`: packaging, see [`build/README.md`](build/README.md).
* `output/`: everything scripts write. Git-ignored and safe to delete, except `scripts/audio/reference/kamui_goal.ogg`, which lives elsewhere because it can't be regenerated.

Conventions for the specs:

* Addresses are virtual addresses in `modules/soundvoltex.dll` (x64, ImageBase `0x180000000`). `FUN_*` names are Ghidra's.
* Say where a fact came from: the binary, a measurement, or an assumption. Record dead ends.
* The binary outranks community notes. Correct a document in place. Uncertain items go in its open-questions section.
* Scripts never hard-code paths; they use `scripts/shared/game_paths.py`. Findings go in `specs/`, not in code.

Most of the game logic comes from `modules/soundvoltex.dll`, decompiled with Ghidra. This repo does not say where to get the game data.

Most of the decompilation work was done by Claude, and I can't verify all of it myself. What I can check is the output against the community's hand-made conversions.

## Credits

* **zacharied**: original `.vox` format notes
* **m0seng**: rewrite and v10/v12 extension of those notes
* **Rosemoe**: [`sdvx-sfx-renderer`](https://github.com/Rosemoe/sdvx-sfx-renderer), used to cross-check

The reference `.ksh` files and recordings in `scripts/shared/reference/` are community hand-work. The audio is measured against them.

## Requirements

* Python 3.12
* `ffmpeg` on `PATH`

Keep this folder inside the game's `contents/` directory; scripts find the game data relative to it.

## Usage

```bash
pip install -r requirements-gui.txt
python gui/main.py
```

Single chart, from the command line:

```bash
python scripts/audio/render_chart.py ../data/music/2229_kamui_tjhangneil -d 5m -o output/kamui_fx.ogg
```
