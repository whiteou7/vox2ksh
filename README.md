# vox2ksh

A Python tool that converts SOUND VOLTEX `.vox` charts to the `.ksh` format used by KSM/USC — and the reverse-engineering writeup that the conversion is based on.

---

## The three elements

Conversion splits into three independent problems. They share the `.vox` parser and nothing else.

| element | what it covers | status |
|---|---|---|
| **audio** | The FX/laser effect engine, the device ParamEq, the music duck, the layered SE bank, and the sample-level `S3V0` header gains. | **Largely done** — engine transcribed, reference implementation renders a real chart and scores 1.799 against a cabinet capture (floor 1.14). Three open items, all narrow. |
| **notes** | BT/FX/laser note data, timing, BPM and time-signature changes, laser slams, curve types, chip vs hold — the part that becomes `.ksh` chart body. | **Buttons and lasers done, crosschecked against 5 reference charts.** Roll/swing (spin) not yet attempted. |
| **camera** | `#CAMERA`/`#TILT`-class track data: lane tilt, spin, zoom, roll. `.ksh` expresses only a subset, so this needs a mapping decision, not just a transcription. | **Not started.** |

Audio was done first because it was the hardest to verify and the easiest to get silently wrong. Notes is the element the converter actually needs first.

---

## The writeup

This writeup discuss arcade game data but will not provide the location to get it.

Claude did the most heavy lifting in this project like analyzing the decompiled code. I'm not good at reverse engineering myself so I might not be able to catch all the shit the LLM can hallucinate. My main responsibility is to ensure the quality of the output it produces, which is thankfully made easy by numerous manual convert "samples" by the SDVX Community.

The majority of the game logics lives in `contents/modules/soundvoltex.dll`, which can be decompiled using Ghidra. Game assets are accessible at `contents/data` directory (`contents/` is the game data directory).

The rest of the findings live in `specs/`. Start by reading the file formats and `audio_engine_primer.md`.

## Requirements

* Python 3.12 
* `ffmpeg` on `PATH`

The scripts locate the game install relative to this directory (`vox2ksh/..`), so they work as long as the project sits inside `contents/`.

## Quick start

```bash
python scripts/audio/sdvx_fx.py --list
```

```bash
python scripts/audio/apply_chart.py ../data/music/2229_kamui_tjhangneil -d 5m -o output/kamui_fx.ogg
```

---

