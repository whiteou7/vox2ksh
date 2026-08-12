# specs/

| file | what it is |
|---|---|
| [`vox_format.md`](vox_format.md) | The `.vox` container: encoding, sections, track layout, column meanings. **Inherited from zacharied and m0seng, now maintained here** — corrections from this project's own binary/corpus work are applied *in place* and marked `[corrected]`/`[added]`/`[verified]`; unmarked text is inherited and not necessarily re-verified. Covers v10/v12, plus a "Format version 13" section that is this project's own survey. |
| [`ksh_format.md`](ksh_format.md) | The `.ksh` target format, and the conversion decisions that follow from it. |
| [`audio_engine.md`](audio_engine.md) | The audio element in full: effect inventory with DLL addresses, transcribed DSP math, chart→DSP unit conversions, the device ParamEq, the SE bank, calibration against a cabinet capture. |
| [`audio_engine_primer.md`](audio_engine_primer.md) | The same material with no assembly or audio-engineering background assumed. |
| [`camera.md`](camera.md) | The camera element: tilt/spin/zoom/roll → whatever `.ksh` can express. |
| [`notes.md`](notes.md) | The notes element: BT/FX/laser → `.ksh` chart body, and the laser decimation problem. |

## Conventions

* **Addresses are virtual addresses** in `modules/soundvoltex.dll` (PE32+ x64, ImageBase `0x180000000`, build 2025-06-19). `FUN_xxxxxxxxx` names are Ghidra's.
* **Say where a fact came from.** A transcription from the binary, a measurement against the capture, and an assumption are three different things and the writeup marks which is which. `audio_engine.md` §3 is a good model: where the community notes and the binary disagree, it tabulates both and cites the address that settles it.
* **Record what was ruled out**, not just what was found. Several sections of `audio_engine.md` exist purely to stop someone re-running a dead end.
* Community notes are cited but do not outrank the binary. Four `.vox` effect ids are mislabelled in the inherited notes; `vox_format.md`'s `#FXBUTTON EFFECT INFO` table lists the corrections alongside the original names, with `audio_engine.md` §3 holding the derivation.
* **Correct inherited docs in place, don't annotate around them.** `vox_format.md` is ours to maintain now; a correction belongs in the section it corrects, marked and credited, not appended to a different file. Leaving a known-wrong claim standing because "it's someone else's document" is how the same mistake gets rediscovered three times — which is exactly what happened with the effect-id names.
* **Credit survives editing.** zacharied and m0seng wrote most of `vox_format.md`'s structure; correcting a claim of theirs does not make it ours.

## Where things live outside this directory

* [`../HANDOFF.md`](../HANDOFF.md) — the entry point for a new session: what is done, what is unresolved, what is untouched. Read before any spec.
* `../../sdvx_audio_fx_re/` — **frozen predecessor** of the audio work. Carries banners pointing here. Do not start from it; it is kept only for provenance and for a handful of one-off probe scripts that were never carried across.
