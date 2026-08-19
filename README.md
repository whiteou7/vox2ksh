 # vox2ksh

A Python tool that converts SOUND VOLTEX `.vox` charts to the `.ksh` format used by KSM/USC — and the reverse-engineering writeup the conversion is based on.

## The three elements

Conversion splits into three independent problems. They share the `.vox` parser and nothing else.

| element | what it covers | status |
|---|---|---|
| **audio** | The FX/laser effect engine, the device ParamEq, the music duck, the layered SE bank, the per-sample `S3V0` header gains. | **Largely done.** Composite kind 14 (id 13) is still only partly transcribed. |
| **notes** | BT/FX/laser note data, timing, BPM and time-signature changes, slams, curve types, chip vs hold — the `.ksh` chart body. | **Done** |
| **camera** | `#SPCONTROLER` track data: lane tilt, spin/swing, top/bottom zoom. `.ksh` expresses only a subset, so this needs mapping decisions on top of transcription. | **Largely done.** Zoom top/bottom is implemented. Spin needs more researching on types. Pretilt is a massive headache. |

## The writeup

The findings live in `specs/`. Start with the file formats and [`specs/audio_engine_primer.md`](specs/audio_engine_primer.md).

This writeup discusses arcade game data but will not provide the location to get it. Most of the game logic lives in `contents/modules/soundvoltex.dll`, decompiled with Ghidra; assets are in `contents/data` (`contents/` is the game data directory).

Claude did the heavy lifting here, mostly the decompiled stuff. I am not a reverse engineer myself so I cannot always catch what the LLM can hallucinates. My job is the quality of the output, which the SDVX community's manual conversion "samples" make checkable.

## Credits

* **zacharied** — the original `.vox` format notes.
* **m0seng** — the substantial rewrite and v10/v12 extension of those notes.
* **Rosemoe** — [`sdvx-sfx-renderer`](https://github.com/Rosemoe/sdvx-sfx-renderer) helped with crosschecking works.

The reference `.ksh` conversions and gameplay recordings under `scripts/shared/reference/` are community hand-work, and everything in the audio element is measured against them.

## Requirements

* Python 3.12
* `ffmpeg` on `PATH`

The scripts locate the game install relative to this directory (`vox2ksh/..`), so they work as long as the project sits inside `contents/`.

## Quick start

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
