# Handoff — vox2ksh

Three sections: **what is done** (do not redo), **what is unresolved** (tried, not closed — the notes say what was already ruled out), and **what is to do** (not started).

---

## 1. Done

### 1.1 Audio — the effect engine

Full writeup in [`specs/audio_engine.md`](specs/audio_engine.md); plain-language version in [`specs/audio_engine_primer.md`](specs/audio_engine_primer.md). Summary of what is settled:

* **Effect inventory.** Every `.vox` effect id → internal kind → wrapper → DSP leaf, with DLL addresses. §3.
* **The DSP math**, transcribed float-for-float including clamps: LPF/HPF/BPF biquads (RBJ cookbook, Direct Form I), BitCrusher, Retrigger/Echo, Gate, TapeStop, SideChain, Flanger, Wobble. §4.
* **Chart → DSP unit conversions**, each verified at its call site: Retrigger/Echo, Gate, SideChain and Wobble periods are in **beats**; Flanger is in **measures**; TapeStop is already seconds; BitCrusher rate is a raw sample count. §5.
* **Signal path.** Fixed 44100 Hz, single-precision float throughout, and the scratch buffers hold **raw int16 magnitudes (±32768) with no normalisation** — copy the formulas into a ±1.0 domain and several effects come out wrong. Per-effect `out = (1-mix)*dry + mix*wet`. Coefficients recompute once per **block**, so output is block-size dependent. Output stage `CGainWithHardLimiter` is a gain followed by a hard clip — no knee, no lookahead — so the shipped game clips its own output. §2, §6.2.
* **`.vox` layout facts that the notes element will need too**: `#TRACK1` = VOL-L, `#TRACK2` = FX-L, `#TRACK3..6` = BT-A..D, `#TRACK7` = FX-R, `#TRACK8` = VOL-R; cell resolution 48 per 1/4 note. On a laser note **C4 is the effect index and C7 is the curve type** (they are easy to confuse — both range 0..5 in practice, and getting it wrong put filters at the wrong times across a whole chart). FX chip C2 = sample index with 0 and 255 silent; FX hold C2 = effect definition index + 2. `#FXBUTTON EFFECT INFO` is 12 **pairs**. §6.
* **A laser slam is not an effect.** It is a zero-duration event that puts a step discontinuity in the knob curve of the run it sits in. The knob curve must be built from events and left as a step — do not smooth or resample it — and a run must be split wherever the per-point effect index changes. §5.1. **This one matters directly for the notes element.**
* **The default laser "peak filter" — solved and transcribed.** It is not in the SVO effect generator at all. `Game::GameAudio::Update` (`FUN_180407200`) case 3 accumulates `max(pos_L, 1 - pos_R)` per tick, queues it, pops it **80 ms** later, and hands `knob * 127` to `FUN_1805c7a00`, which indexes a 128-entry centre-frequency table at `DAT_18090c050`, clamps to `[80, 16000]`, derives bandwidth and gain from piecewise- linear curves, and writes a `_DSFXParamEq` into slot 0 of the device's 7. The same call ducks the music voice. §7.1.
* **The layered SE bank.** Laser slams play `virtical_shot[0]` from bank `0xd`; FX chip notes play `general_sampler[C2]` from bank 9. Full bank-id → file table from `FUN_1805c5960`. §6.1.
* **Per-sample levels live in the sample files, not in the DLL.** Every `S3V0` header carries an 8.8 fixed-point decibel field at `+0x14`, converted with `powf(10, dB/20)` at bank-load time and written to the voice's *mixer connection* — which is why every hunt through `Play` / `SetVolume` / `voice+0x70` came up empty. §6.1.4.
* **One voice per `(bank, sampleIndex)`.** SE re-triggers restart the voice rather than layering, and two lasers slamming on the same tick are one sound, not two. §6.1.3.

Reference implementation: [`scripts/audio/sdvx_fx.py`](scripts/audio/sdvx_fx.py) (the DSP) and [`scripts/audio/apply_chart.py`](scripts/audio/apply_chart.py) (drives it from a real chart, including the non-generator parts: device ParamEq, its 80 ms lag, the music duck, the SE bank).

Against the cabinet capture, lower is closer:

```
untouched track            3.169
current render             1.799
floor (codec noise)        1.14
```

### 1.2 Rejected by measurement — do not revisit

Laser reading dry and overwriting FX; parallel/additive effect combination (both `--laser-mode`, see §2.5 — the verdict stands but the margin was never recorded); an int16 round-trip between stages; scaling the mix depth (1.0 is optimal); putting the device EQ *after* the SE mix (2.029 vs 1.924 before); additive SE layering (1.889 vs 1.858); freezing the duck target between lasers (`--duck-hold`, costs 0.34).

---

## 2. Unresolved

All three are in the audio element. None blocks conversion work.

### 2.1 SE level is derived but lands ~2 dB under the fit

The per-sample gain is authored in the `S3V0` header (§6.1.4):

```
gain = 10 ^ ( ( (i16)hdr[0x14] + (i16)hdr[0x16] ) / 256 / 20 )

slam   virtical_shot[0]        -1324  ->  -5.172 dB  ->  0.5513
chips  general_sampler[2..13]  -3328  -> -13.000 dB  ->  0.2239
music  the song's own .s3v          0 ->   0.000 dB  ->  1.0000
```

The capture wants ~0.69 for the slam, not 0.5513 — a clean factor of ~1.25 (+2 dB). It is not a metric artefact: a slam-local score, with the level offset taken only from frames far from any slam, gives the same answer. Since the metric can only see the SE:music *ratio*, a constant ×0.8 on the music path would explain it exactly.

`apply_chart.py` mixes each SE at `header_gain * --se-trim`, with the trim defaulting to **1.25** — that flag *is* the unexplained 2 dB, isolated so it can be deleted the day someone explains it. `--se-trim 1.0` plays what the files literally say (scores 1.826).

*Already ruled out, do not redo*: a per-bank gain in `FUN_1805c63b0` / `FUN_1805c5960`; the duck resting below unity (`0x1805c7b3d` loads 1.0 and jumps to the tail when knob < 4, so §7.1's transcription is right); `--duck-hold`; `--se-polyphonic`; another module owning the mixer (`S3P0`/`S3V0`/`2DX9` appear only in `soundvoltex.dll`).

*Where to look next*: the music voice is bank 2, loaded by `FUN_1805c63b0(this, 2, path)` through the **standalone `.s3v`** loader at `0x1805cf8c8` — a different function from the `.s3p` bank loader, doing the same header arithmetic but with a second `powf` result at `[rsp+0x60]` whose consumer was never traced. The `.s3p` loader has the same loose end: it appends the per-sample gain into a `std::vector<float>` (`0x1805ced2c`) *in addition to* setting the connection, and where that vector is read is unknown. One of those two is the most likely home for a missing music-side factor.

### 2.2 What selects `fs00_virtical_se01` vs `fs01_virtical_se02`

The slam play path is fully traced (§6.1.1): gameplay event **kind 6** (variant tag 5, at `0x18040773a`) is a *scheduled play* request, turned into a queue entry at `gameAudio+0x80` and drained by `FUN_1805c6ec0(snd, 0xd, entry.index, 0)`. **The sample index is authored into the event** (`event+0x08`, verbatim), not computed at play time — so whatever builds that 28-byte event vector decides.

That producer was never found: the vector arrives as the second argument of `Game::GameAudio::Update` (`FUN_180407200`, vtable slot 1 @ `0x1808cb848`), and neither scanning for the field stores (`mov dword [reg+4], 6` / `mov byte [reg+0x18], 5`) nor chasing xrefs from the `Game::GameAudio` vtable reached it. `FUN_18041c220` constructs the object and stores it at `world+0xb8`, if that helps.

Measured: this chart uses index 0 for every slam, so it does not block rendering.

**Worth a second look during the notes element** — that same 28-byte event vector is very likely where note/laser gameplay events live too, so finding its producer may pay for itself twice.

### 2.3 Effect state continuity

Effect internal state (LFO phase, sample-and-hold position, gate step) restarts at every note in the reimplementation, whereas the game's counters are object members that run continuously. [`scripts/audio/blendfit.py`](scripts/audio/blendfit.py) shows Echo matching exactly (β = 1.00) while Wobble (0.03) and BitCrusher (0.23) are at the wrong *phase*, not the wrong depth. Fixing it means threading persistent per-effect state through `apply_chart.py`.

### 2.4 Smaller gaps in the audio writeup

* **Pitch Shift** (`.vox` id 9) and the **composite kind 14** (id 13) are identified but not transcribed to the sample level. Observed ranges across all 8103 charts, if you want to probe them: id 13 `p1 ∈ [0,100]` (mix), `p2 ∈ [-24,24]`, `p3 ∈ {0,0.5,1,2}` (316 occurrences); id 9 `p1 ∈ [4,100]`, `p2 ∈ [-12,100]` (1283 occurrences).
* **Tape Stop Ex** (id 10) is structurally understood but its envelope constants are not fully transcribed.
* **The laser-position → 0..127 knob assignment** from `#TAB PARAM ASSIGN INFO` is not documented; only the 0..127 → cutoff mapping is.
* `#TRACK AUTO TAB` (applies FX-hold effects to lasers) and `#TRACK ORIGINAL L/R` are not handled by `apply_chart.py`.

### 2.5 How a laser effect combines with an FX-button effect

Written up in [`specs/audio_engine.md`](specs/audio_engine.md) §8.1. The short version: when a tab-laser effect (C4 = 1..5) overlaps an FX-button hold, the disassembly says the laser reads the **dry** track and overwrites the FX result (`FUN_18062e3d0` restores the generator's source pointer on the way out, and `FUN_18062ea60` then `memcpy`s over the destination), but against the capture that model loses to plain **series chaining**. `chain` is what `apply_chart.py` ships, i.e. the default contradicts the apparent reading of the binary.

This is the only place in the audio element where transcription and measurement disagree and measurement won, which makes it worth more scepticism than its one-line entry in §1.2 suggests.

**First thing to do if you reopen it**: the three `--laser-mode` scores were never recorded, only the verdict, so the margin is unknown. Re-run `chain` / `dry` / `add` through `metric.py` and put the numbers in §8.1. Second: count how many frames of this chart actually have an FX hold and a C4 = 1..5 laser live at the same time — if the overlap is small, the measurement is weaker than it looks and neither model is really established. `blendfit.py` already reports the FX+laser and FX-L+FX-R overlap cases.

Not in doubt, for contrast: FX-L + FX-R chain genuinely (same dispatcher, source pointer swapped to the partial result), and the default peak filter is a separate device stage that always stacks on top of the generator (§7.1).

---

## 3. To do

### 3.1 The notes element

Figure out how to convert vox to ksh and resolve discrepancies.

### 3.2 The camera element

Try to map vox camera values to ksm without having to reverse engineer the graphic engine.

### 3.3 The Tkinter application

---
