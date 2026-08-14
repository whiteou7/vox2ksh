# vox2ksh

A Python tool that converts SOUND VOLTEX `.vox` charts to the `.ksh` format used by KSM/USC — and the reverse-engineering writeup the conversion is based on.

## The three elements

Conversion splits into three independent problems. They share the `.vox` parser and nothing else.

| element | what it covers | status |
|---|---|---|
| **audio** | The FX/laser effect engine, the device ParamEq, the music duck, the layered SE bank, the per-sample `S3V0` header gains. | **Largely done.** Every FX-button effect is implemented; composite kind 14 (id 13) is still only partly transcribed. |
| **notes** | BT/FX/laser note data, timing, BPM and time-signature changes, slams, curve types, chip vs hold — the `.ksh` chart body. | **Done** |
| **camera** | `#SPCONTROLER` track data: lane tilt, spin/swing, top/bottom zoom. `.ksh` expresses only a subset, so this needs mapping decisions on top of transcription. | **In progress.** Zoom top/bottom are reliable, and spin *kind* and *direction* verified at 100 % against the reference set. Spin *length* is still name-derived rather than fitted and needs a ground-up re-derivation; tilt needs review. |

## The writeup

The findings live in `specs/` — see [`specs/README.md`](specs/README.md) for what is in there. Start with the file formats and [`specs/audio_engine_primer.md`](specs/audio_engine_primer.md).

This writeup discusses arcade game data but will not provide the location to get it. Most of the game logic lives in `contents/modules/soundvoltex.dll`, decompilable with Ghidra; assets are in `contents/data` (`contents/` is the game data directory).

Claude did the heavy lifting here, particularly the decompiled-code analysis. I am not a reverse engineer myself, so I cannot always catch what an LLM hallucinates — my job is the quality of the output, which the SDVX community's manual conversion "samples" make checkable.

## Credits


* **zacharied** — the original `.vox` format notes.
* **m0seng** — the substantial rewrite and v10/v12 extension of those notes.
* **Rosemoe** — [`sdvx-sfx-renderer`](https://github.com/Rosemoe/sdvx-sfx-renderer), an independent IDA-based reimplementation of the same audio engine. Cross-checking against it confirmed most of this project's trace, supplied the Wobble rate fix, and resolved the `#TAB PARAM ASSIGN INFO` sweep direction. 

The reference `.ksh` conversions and gameplay recordings under `scripts/shared/reference/` are community hand-work, and everything in the audio element is measured against them.

## Requirements

* Python 3.12
* `ffmpeg` on `PATH`

The scripts locate the game install relative to this directory (`vox2ksh/..`), so they work as long as the project sits inside `contents/`.

## Quick start

The GUI (`gui/`) is the batch/end-user interface: point it at a game or update folder and an output folder, pick songs and difficulties, convert. See [`gui/README.md`](gui/README.md) to run it from source and [`build/README.md`](build/README.md) to package it into an exe.

```bash
pip install -r requirements-gui.txt
python gui/main.py
```

For one chart at a time, or for the diagnostic flags the GUI's Advanced panel exposes, the scripts are still the direct interface:

```bash
python scripts/audio/sdvx_fx.py --list
```

```bash
python scripts/audio/apply_chart.py ../data/music/2229_kamui_tjhangneil -d 5m -o output/kamui_fx.ogg
```
