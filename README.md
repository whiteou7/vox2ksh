# vox2ksh

Converts SOUND VOLTEX `.vox` charts to `.ksh` (KSM/USC), with the reverse-engineering notes behind it.

## Content

| part | covers | status |
|---|---|---|
| audio | FX/laser effects, ParamEq, music duck, SE bank, per-sample gains | Done, except the Pitch & Speed effect (id 13), whose phase vocoder is a stand-in |
| notes | BT/FX/laser notes, timing, BPM/time-signature changes, slams, curves | Done |
| camera | lane tilt, spin/swing, zoom | Zoom done. Spin lengths are approximate. Pretilt removal is optional. |

## The writeup

The findings live in `specs/`. Start with the file formats and [`specs/audio_engine_primer.md`](specs/audio_engine_primer.md).

This writeup discusses arcade game data but will not provide the location to get it. Most of the game logic lives in `contents/modules/soundvoltex.dll`, decompiled with Ghidra; assets are in `contents/data` (`contents/` is the game data directory).

Claude did the heavy lifting here, mostly the decompiled stuff. I am not a reverse engineer myself so I cannot always catch what the LLM can hallucinates. My job is the quality of the output, which the SDVX community's manual conversion "samples" make checkable.

## Credits

* **zacharied**: original `.vox` format notes
* **m0seng**: rewrite and v10/v12 extension of those notes
* **Rosemoe**: [`sdvx-sfx-renderer`](https://github.com/Rosemoe/sdvx-sfx-renderer)

The reference `.ksh` files and recordings in `scripts/shared/reference/` are community hand-work.

## Requirements

* Python 3.12
* `ffmpeg` on `PATH`

Keep this folder inside the game's `contents/` directory; scripts find the game data relative to it.

## Usage

```bash
pip install -r requirements-gui.txt
python gui/main.py
```
