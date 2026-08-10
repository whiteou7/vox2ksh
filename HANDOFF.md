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

### 1.3 Notes — buttons and lasers

Full writeup: [`specs/notes.md`](specs/notes.md). Implementation: [`scripts/notes/`](scripts/notes/) (`convert.py`, `laser.py`, `xcheck.py`).

Converts `.vox` BT/FX/laser tracks to a playable `.ksh` body; timing/BPM/beat just enough to build the grid, everything else (song metadata, every sound-fx parameter) is placeholder, as directed. The three named risks (width, continuity, the unrepresentable 32nd slam) all landed - see `specs/notes.md` for how.

Crosschecked against 30 chart/difficulty pairs (every reference folder `xcheck.py` can match to a `data/music` chart, same by-name matching as `scripts/audio/masscheck.py`, times every difficulty present - not a hand-picked handful). BT/FX/laser-run counts match almost exactly; laser point counts land within ~4% mean, which is expected (decimation approximates a curve's shape, not one charter's exact point choices).

Four real bugs found and fixed along the way, all against charts *outside* the 30-chart set (user-reported), all reverified against the full aggregate before being called done - see `specs/notes.md` §"Bugs found and fixed" for what each one was and, for the trickiest of the four, the two broken interim fixes the aggregate caught before a correct one shipped.

Roll/swing is not part of this element - it's camera-domain (vox's per-point roll type driving lane spin/tilt visuals); see 1.4. `#TRACK AUTO TAB` (FX-hold effects applied to lasers) also unread - effect data doesn't matter yet, but the track's note-length data might, if that ever changes.

### 1.4 Camera — zoom and spin

Full writeup: [`specs/camera.md`](specs/camera.md). Implementation: [`scripts/camera/`](scripts/camera/) (`camera.py`, `convert.py`, `survey.py`, `correlate.py`). Scope: lane tilt, spin/swing, top/bottom zoom; `zoom_side`/`center_split`/`rotation_deg`/`*_curve` explicitly out of scope (KSMv2-only or unneeded - confirmed zero usage in the reference set for `zoom_side`). **Pretilt** (KSM tilting in anticipation of an upcoming laser, before the arcade would) **is also out of scope, by direction**: it's triggered by any laser at all, not a chart-detectable condition, so it's a game-engine problem rather than something a `.vox` -> `.ksh` mapping could fix - the converter doesn't attempt to cancel or reproduce it.

`shared/vox.py` now parses `#SPCONTROLER` (`Tilt`/`CAM_RotX`/`CAM_Radi`) into `VoxChart.camera`, matching the documented row layout exactly. A converter exists: `scripts/camera/convert.py`, or `notes/convert.py`'s `convert(..., camera=True)` — additive, `notes/xcheck.py` confirmed byte-for-byte unaffected when `camera=False` (the default).

What's solid, all confirmed against the 30-chart reference set via `correlate.py`:

* **Zoom sign/direction**: `CAM_RotX` correlates positively with `zoom_top`, `CAM_Radi` *negatively* with `zoom_bottom` (a real sign flip between the two formats' conventions). Scale is an approximation on purpose — per direction, exact accuracy isn't the bar here — `camera.py` uses ~140 / ~-125 as central-tendency constants; the reference conversions are hand-made, not derived, so per-song regressed slopes vary and there's no single exact constant to fit.
* **Spin kind mapping**: vox "roll" (`roll_type` 1,2,3,4,6,7) → ksh full spin (`@(`/`@)`); vox "swing" (`roll_type` 5) → ksh half spin (`@<`/`@>`). **100% match, 49/49 + 17/17.** `S<`/`S>` intentionally never emitted — unused in every reference chart, even for genuine vox swings.
* **Spin direction**: the roll/swing tag sits on the laser point immediately *before* a same-tick slam (not after — this took a fix to get right), and the slam's direction determines clockwise/counterclockwise (right-to-left = clockwise = `@(`/`@<`; left-to-right = counterclockwise = `@)`/`@>`). **100% match, 66/66.**
* Corpus survey facts (all 8103 charts, `survey.py`): 82% of charts have `CAM_RotX`/`CAM_Radi`, only 9% have any manual `Tilt`. A `roll_type` value of **7** exists (v12, 49 rows) — undocumented in the inherited `vox_format.md` notes, a correction in the spirit of `audio_engine.md` §3's effect-id fixes.
* **Vox chart format 13 surveyed** (`vox_format.md`'s "Format version 13" section — this project's own survey, not community-sourced, since v13 postdates the inherited notes). Structurally a superset of v12 (`shared/vox.py`/`camera.py` parse and convert all sample files unchanged), but: `#TRACK1`/`#TRACK8` rows always carry all 10 fields now; `C8` (roll/swing length) is near-universally `0` for *every* `roll_type` (not just 6/7 — an early, narrower version of this finding was corrected mid-session, see `specs/camera.md`); two new tags (`#BPM OPTION`, `#LOCKED_SPCONTROLER`); manual `Tilt` usage jumps from 9% to 36% of charts; `Realize`'s payload, previously assumed a fixed engine constant, varies on a small minority (5/148 sample) of charts.

Two bugs found and fixed (both in `specs/camera.md` "Bugs found and fixed", both the same *class* of mistake as notes.md bug #3 — a middle point silently dropped/overwritten changes the interpolated shape): a same-tick vox snap (zero-length segment, `start != end`) got overwritten instead of spaced onto two adjacent grid lines; and a dedup pass dropped the *last* point of a same-value run, which is what stops ksh's linear interpolation from blending a flat hold straight into the next ramp. Both confirmed and fixed against `2226_gryphone_etia_5m.vox`'s raw segments directly (a file initially and wrongly treated as an independent hand reference — it's actually prior machine-placeholder output; see the doc for the retraction). A third, smaller bug from the v13 survey: the `roll_type=6` `C9`-length fallback (below) was never extended to `roll_type=7`, which shares the identical pattern — fixed.

---

## 2. Unresolved

Mostly the audio element, plus one camera item (§2.9). None blocks conversion work.

**Start with §2.6** for audio, **§2.9** for camera. Wobble (§2.6) is the one audio effect measurably failing to reproduce the game, established across independent charts rather than inferred. Everything else in the audio section is a refinement; that one is a defect.

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

### 2.3 Effect state continuity — done for Wobble, still open for the rest

Effect internal state (LFO phase, sample-and-hold position, gate step) restarted at every note in the reimplementation, whereas the game's counters are object members that run continuously. [`scripts/audio/blendfit.py`](scripts/audio/blendfit.py) shows Echo matching exactly (β = 1.00) while Wobble (0.03) and BitCrusher (0.23) are at the wrong *phase*, not the wrong depth.

**Wobble is now threaded.** Its LFO counter is a member at `this+0x238`, written back every block (`0x1806416b1` / `0x1806416c2`), so it resumes rather than restarting. `sdvx_fx.fx_wobble` takes an optional `state` dict and `apply_chart.FXSTATE` carries it, keyed by effect type — one counter per type, matching the single member in the engine. `--no-persist` restores the old behaviour.

Measured on feelsseasickness: Wobble exclusive gain −0.425 → −0.392. Correct per the binary, but **nowhere near enough** — see §2.6.

Still open: BitCrusher's sample-and-hold position and Gate's step counter are almost certainly members too, but were not traced and are not threaded. Both currently score well (+2.0 / +2.8), so there is no measured pressure to change them — do not touch them without a measurement to justify it.

### 2.4 Smaller gaps in the audio writeup

* **Pitch Shift** (`.vox` id 9) and the **composite kind 14** (id 13) are identified but not transcribed to the sample level. Observed ranges across all 8103 charts, if you want to probe them: id 13 `p1 ∈ [0,100]` (mix), `p2 ∈ [-24,24]`, `p3 ∈ {0,0.5,1,2}` (316 occurrences); id 9 `p1 ∈ [4,100]`, `p2 ∈ [-12,100]` (1283 occurrences).
* **Tape Stop Ex** (id 10) is structurally understood but its envelope constants are not fully transcribed.
* **The laser-position → 0..127 knob assignment** from `#TAB PARAM ASSIGN INFO` is not documented; only the 0..127 → cutoff mapping is.
* `#TRACK AUTO TAB` (applies FX-hold effects to lasers) and `#TRACK ORIGINAL L/R` are not handled by `apply_chart.py`.

### 2.4b Retrigger grid-locking — implemented, but untested against the capture

`specs/audio_engine.md` §5.2. Retrigger's repeat cycle is locked to the musical grid rather than to the note (`FUN_18062e310`), so a note starting mid-cycle joins partway through and replays audio from before itself. Now implemented in `apply_chart.py`, with `--no-grid-snap` to A/B it.

**It cannot be scored.** `2229_kamui` has exactly one Retrigger note and it sits on a period boundary, so the render is bit-identical either way and `metric.py` has nothing to say. The code path was verified on `0001_albida_muryoku` 1n (6 off-grid notes, 0.89 % of samples change) — but that chart has no capture, so "correct per the disassembly" is as far as this goes. Scoring it needs a capture of a chart with off-grid Retrigger notes.

Two things fell out of that work and are still open:

* **Echo's 7th chart field is unexplained.** §3 claims the wrapper uses it "for grid alignment/update period", but the Echo wrapper demonstrably does not call the snap, so that description is at best imprecise. The field is `0.00` on every row of this chart, so nothing here exercises it.
* **`Timeline` uses a float-seconds clock, the engine uses integer samples** with a truncating `samplesPerBeat = trunc(2646000/BPM)`. On charts whose BPM does not divide 2646000 evenly the two drift, which makes `grid_snap_offset` return a few tens of samples where it should return zero. Inaudible, but wrong, and it would matter more anywhere else position arithmetic is compared. The fix is an integer-sample clock in `Timeline`.

### 2.5 How a laser effect combines with an FX-button effect

Written up in [`specs/audio_engine.md`](specs/audio_engine.md) §8.1. The short version: when a tab-laser effect (C4 = 1..5) overlaps an FX-button hold, the disassembly says the laser reads the **dry** track and overwrites the FX result (`FUN_18062e3d0` restores the generator's source pointer on the way out, and `FUN_18062ea60` then `memcpy`s over the destination), but against the capture that model loses to plain **series chaining**. `chain` is what `apply_chart.py` ships, i.e. the default contradicts the apparent reading of the binary.

This is the only place in the audio element where transcription and measurement disagree and measurement won, which makes it worth more scepticism than its one-line entry in §1.2 suggests.

**First thing to do if you reopen it**: the three `--laser-mode` scores were never recorded, only the verdict, so the margin is unknown. Re-run `chain` / `dry` / `add` through `metric.py` and put the numbers in §8.1. Second: count how many frames of this chart actually have an FX hold and a C4 = 1..5 laser live at the same time — if the overlap is small, the measurement is weaker than it looks and neither model is really established. `blendfit.py` already reports the FX+laser and FX-L+FX-R overlap cases.

Not in doubt, for contrast: FX-L + FX-R chain genuinely (same dispatcher, source pointer swapped to the partial result), and the default peak filter is a separate device stage that always stacks on top of the generator (§7.1).

---

### 2.6 Wobble moves the audio hard, in the wrong direction — the top open item

**Read this before the numbers, because the obvious misreading is wrong.** Wobble is *not* inactive, and it is not too subtle to hear. It changes the audio more than any other effect measured. What it fails to do is move the render *toward* the recording. On feelsseasickness, over the frames where Wobble is the only effect running:

```
              d(dry, ref)   d(render, ref)   d(dry, render)
Wobble           5.330          5.723            6.382
Gate             5.244          2.416            4.082
Retrigger        7.206          2.700            6.220
```

Gate and Retrigger start at some distance from the reference and end up much closer. Wobble travels **further than either of them** (6.382, the largest movement of the three) and ends up slightly *further away* than doing nothing. Large, audible, wrong direction.

That rules out a whole class of causes — it is not "the effect isn't being applied", "the mix is too low", or "the region is mistimed". Something about the *shape* of what it does is wrong: the filter type, the sweep waveform, the frequency mapping, or the phase.

`xcheck.py` now reports this directly as the `moved` column, so the distinction is visible without a special script: big `moved` with ~zero `gain` means a wrong algorithm, not an idle one.

**The defect, aggregated.** Measured with [`scripts/audio/masscheck.py`](scripts/audio/masscheck.py) over 6 charts with gameplay recordings, as exclusive-frame gain (`dry − render`, higher is better):

```
effect               mean   median    worst  charts
Wobble             +0.024   +0.005   -0.657       5
Flanger            +1.278   +1.408   +1.015       6
BitCrusher         +2.250   +1.920   +1.061       6
TapeStop           +2.329   +2.743   +1.137       4
SideChain          +2.714   +3.639   +1.070       4
Retrigger          +2.884   +3.141   +1.843       6
Gate               +3.200   +3.313   +2.200       6
```

Every other DSP buys +1.3 to +4.1. Wobble buys nothing, and on some charts is negative. This is not one chart's quirk — it reproduces across independent songs.

**Ruled out, do not redo:**

* *LFO phase continuity* — implemented (§2.3), moved it −0.425 → −0.392. Correct, but not the cause.
* *Block size* — the LFO only updates once per block, so this was a prime suspect. 64 / 128 / 512 all land at ≈ −0.4 on feelsseasickness. Not it.
* *Period units* — §4.9's prose claimed "4 s period"; that was wrong and is corrected. The wrapper computes `xmm6 = (60/BPM) * period` at `0x180632ab6`, i.e. **beats**, which is what `apply_chart` already did. At 248 BPM the two readings differ 4x, so this was worth checking, but the code was right.

**What is left to check**, in the order worth trying:

1. **The frequency computation, term by term.** Disassemble the DSP at `0x1806414f0` and compare against §4.9's five waveform cases rather than testing hypotheses one at a time. The log-triangle case (`wave_type 3`, the one every observed chart uses) is the place to start.
2. **The `filterType` / `waveType` column assignment.** `apply_chart.run_fx` reads `ftype = p[0]`, `wtype = p[1]`. This is *inferred*, not verified: it is self-consistent only because the observed `6, 0, 3, …` rows give a valid filter type either way round only for `ftype=0`. Verify at the wrapper which slot feeds the filter selector.
3. **The resonance trim.** `filter_blocked` applies `(1 − Q·0.04)` to the mixed signal for LPF/HPF. If Wobble's leaf applies it differently, the level would be wrong throughout.

**Do not** attribute this to the reference recordings. The same tooling gives +1.3 to +4.1 on every other effect using those exact files.

### 2.7 No known floor for the non-kamui references

kamui has a measured codec floor of 1.14 — the score an untouched track gets from coding noise alone, which is what makes "1.799" interpretable. The reference recordings in `scripts/shared/reference/ksh/` and the feelsseasickness YouTube rip have **no such floor measured**, so a score of "+1.05 gain" has no yardstick: nobody knows whether there is 0.2 or 2.0 of headroom left.

Worth establishing, because without it the mass numbers can only be compared to each other, never to "correct". The cheapest estimate is to score a chart's *idle* frames — where the chart does nothing, the render is the dry track, so whatever the metric reports there is the floor for that recording.

### 2.8 Reading the metric: never judge a localized fix by the ALL column

Recorded because it caused a wrong conclusion in the session that added these tools.

`xcheck.py` reports each region twice: the raw mask, and **exclusive** frames where that effect is the only FX running. Effects overlap constantly — feelsseasickness has Echo running under HPF+Gate — so the raw column measures everything active in a region, not the named effect. Read the exclusive column for attribution.

Two concrete ways this misleads:

* Echo scored **−0.457** on its raw mask and **+2.046** exclusive. The raw number was the HPF+Gate on top of it. Echo is fine; a session concluded it was broken.
* A real fix worth **+0.639** on Retrigger exclusive frames showed as **+0.010** on ALL, because 65 improved frames are diluted across 5157. Judged on ALL it looks like noise.

Validated end to end: rendering feelsseasickness before and after the §2.3 + §2.4b fixes, with alignment and dry track held fixed, the metric preferred "after" on every region that changed and got worse on none — agreeing with a listener who picked "after" blind. The tool tracks perception when read at the right granularity.

### 2.9 Camera — spin length for `roll_type` 1-7 needs a ground-up re-derivation, distrusting `vox_format.md`

Full detail: `specs/camera.md` "Spin/swing: length". Current state is a patchwork, not a derivation: `camera.py`'s `DEFAULT_BEATS` table (`{1:6, 2:2, 3:3, 4:12, 5:3}`) is lifted straight from the *inherited community notes'* naming ("6-beat roll", "2-beat roll", etc.) rather than fit from data, and is already known wrong for types 2 and 5 specifically (their observed reference-set defaults, 72 and 72-96, don't match the 64 and 96 those names predict — see the doc). Types 6/7 use a completely different mechanism (`C9` fallback, itself only an inference from magnitude, not confirmed against the renderer — see `vox_format.md`'s "Format version 13"). Nothing here has been re-derived from scratch; each piece was patched onto the last as new charts surfaced problems with it.

**Next task, by direction**: treat every claim in `vox_format.md` about `roll_type`/`C8`/`C9` as a hypothesis to verify, not a given — the inherited notes have already been wrong about other sections (audio effect ids, the undocumented `roll_type=7`, the "C8 required for type 6" claim now contradicted by v13). Re-derive the length formula for **all seven `roll_type` values** from first principles: regression against `scripts/shared/reference/ksh`'s hand-charted conversions (the same method that already nailed the kind mapping and direction rule at 100% each — `correlate.py` is the existing tool, but its spin-length handling so far only really dug into type 1 and 3), rather than assuming the community-doc-derived per-type default durations. `correlate.py`'s `--dump` output and `specs/camera.md`'s existing per-type sample dumps are the starting point; expect to need more reference charts or a wider tick-matching tolerance for types 2/4/5, since sample sizes there are thin (single digits to low tens of matched tokens per type in the current 30-chart reference set). Types 6/7 have zero reference-chart coverage at all (never used in any of the 30 matched charts) — for those, the corpus C8/C9 magnitude survey in `vox_format.md` is the only evidence that exists; closing this properly may require either more reference charts that happen to use 6/7, or accepting the DLL as the only way to confirm it.

## 3. To do

### 3.0 Bundle the layered SE with the tkinter app build

### 3.1 The Tkinter application

---
