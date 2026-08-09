# specs/

| file | what it is |
|---|---|
| [`vox_format.md`](vox_format.md) | The `.vox` container: encoding, sections, track layout, column meanings. Based on zacharied's community notes, covering v10 and v12. |
| [`ksh_format.md`](ksh_format.md) | The `.ksh` target format, and the conversion decisions that follow from it. |
| [`audio_engine.md`](audio_engine.md) | The audio element in full: effect inventory with DLL addresses, transcribed DSP math, chart→DSP unit conversions, the device ParamEq, the SE bank, calibration against a cabinet capture. |
| [`audio_engine_primer.md`](audio_engine_primer.md) | The same material with no assembly or audio-engineering background assumed. |
| [`camera.md`](camera.md) | The camera element: tilt/spin/zoom/roll → whatever `.ksh` can express. |

## Conventions

* **Addresses are virtual addresses** in `modules/soundvoltex.dll` (PE32+ x64, ImageBase `0x180000000`, build 2025-06-19). `FUN_xxxxxxxxx` names are Ghidra's.
* **Say where a fact came from.** A transcription from the binary, a measurement against the capture, and an assumption are three different things and the writeup marks which is which. `audio_engine.md` §3 is a good model: where the community notes and the binary disagree, it tabulates both and cites the address that settles it.
* **Record what was ruled out**, not just what was found. Several sections of `audio_engine.md` exist purely to stop someone re-running a dead end.
* Community notes are cited but do not outrank the binary. Two `.vox` effect ids are mislabelled in the inherited notes; `audio_engine.md` §3 lists the corrections.
