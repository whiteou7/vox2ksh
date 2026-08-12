# Handoff — vox2ksh

**What is done** (do not redo), **what is unresolved** (tried, not closed), **what is to do** (not started). Specs hold the detail; this file holds the state.

Read [`§0`](#0-how-to-measure-anything-here) before running any experiment — several conclusions in this project's history were wrong because the metric was read at the wrong granularity.

---

## 0. How to measure anything here

`scripts/audio/xcheck.py <song folder> <recording>` renders a chart and scores it against a cabinet recording, per effect. `masscheck.py` aggregates that across every reference folder it can match to `data/music`. `scripts/shared/reference/ksh/` holds 713 gameplay recordings (`mxm.ogg` etc. — the difficulty tag names the take; `music.ogg` is bare song audio, not a capture).

Three rules, each learned the hard way:

1. **Read the `excl` column, not `gain`.** Effects overlap constantly, so a region's raw score measures everything live in it. Echo once scored −0.457 raw / +2.046 exclusive and was wrongly declared broken.
2. **Never judge a localized fix by `ALL`.** A +0.639 win on 65 Retrigger frames shows as +0.010 across 5157. It looks like noise because it is diluted, not because it is small.
3. **The metric ranks; it cannot diagnose.** A chart broken by one wrong global constant and a chart with several bad DSPs score identically — uniformly awful. If a chart is bad in *every* region while its alignment is fine, suspect a chart-global input (beat resolution, BPM list, parsing) and **listen to it**. Do not exclude it as an outlier: that reflex hid the `#BEAT RESOLUTION` bug through three separate experiments, and reversed one of their conclusions.

`moved` distinguishes "doing nothing" from "doing plenty, wrongly": large `moved` with ~zero `gain` is a wrong algorithm, not an idle one.

---

## 1. Done

### 1.1 Audio — the effect engine

Full writeup: [`specs/audio_engine.md`](specs/audio_engine.md); plain-language version: [`specs/audio_engine_primer.md`](specs/audio_engine_primer.md). Implementation: [`scripts/audio/sdvx_fx.py`](scripts/audio/sdvx_fx.py) (DSP) and [`scripts/audio/apply_chart.py`](scripts/audio/apply_chart.py) (drives it from a chart, including the parts outside the effect generator).

Settled, with section references into the spec:

* **Effect inventory** — every `.vox` id → internal kind → wrapper → DSP leaf, with addresses. Four ids are mislabelled in the inherited community notes. §3.
* **DSP math**, transcribed float-for-float with clamps: biquads, BitCrusher, Retrigger/Echo, Gate, TapeStop, TapeStopEx, SideChain, Flanger, Wobble, Pitch Shift. §4.
* **Unit conversions**, verified per call site — most periods are in **beats**, Flanger is in **measures**, Tape Stop (id 4) is in **seconds**, Tape Stop Ex (id 10) is in **beats**. §5.
* **Signal path** — 44100 Hz, float holding raw int16 magnitudes (**no** /32768), per-effect `out = (1-mix)·dry + mix·wet`, coefficients per *block*, output stage is a gain then a hard clip. §2, §6.2.
* **Retrigger is grid-locked** — its cycle runs on the song's grid, so a note starting mid-cycle joins partway through. Confirmed on 14/14 capture-matched charts, mean +0.88 dB. §5.2.
* **`#BEAT RESOLUTION` is per-chart** — cells-per-beat is 48 on 8088 of 8107 charts and 240/480 on the rest. Assuming 48 corrupts every time in those charts. §5.3.
* **A laser slam is not an effect** — a zero-duration event putting a step in the knob curve. Build the curve from events and leave it stepped; split runs wherever the effect index changes. §5.1. **Matters for the notes element too.**
* **The default laser sound is not in the effect generator** — it is a device ParamEq driven from the gameplay event dispatcher, lagging the knob 80 ms, ducking the music. §7.1.
* **Layered SE** — slams play `virtical_shot[0]` (bank `0xd`), FX chips play `general_sampler[C2]` (bank 9); one voice per `(bank, index)`, so re-triggers restart rather than layer. §6.1, §6.1.3.
* **Per-sample levels live in the sample files** — an 8.8 fixed-point dB field in every `S3V0` header, applied at bank-load time to the voice's mixer connection. §6.1.4.
* **`#TRACK AUTO TAB`** — lasers borrowing an FX-button effect pair; applied by default, worth +1.07 dB. §6.3.

Against the kamui capture (lower is closer): untouched track **3.169**, current render **1.822**, codec floor **1.14**.

### 1.2 Rejected by measurement — do not revisit

Parallel/additive effect combination (`--laser-mode add`, 0 wins of 16); an int16 round-trip between stages; scaling mix depth (1.0 optimal); the device EQ *after* the SE mix (2.029 vs 1.924); additive SE layering (1.889 vs 1.858); freezing the duck between lasers (`--duck-hold`, −0.34); Tape Stop Ex with envelope floor 0.0 (+1.92 vs +3.22).

### 1.3 Notes — buttons and lasers

Writeup: [`specs/notes.md`](specs/notes.md). Implementation: [`scripts/notes/`](scripts/notes/).

Converts BT/FX/laser tracks to a playable `.ksh` body; song metadata and sound-fx parameters are placeholder by direction. Crosschecked against 30 chart/difficulty pairs: BT/FX/laser-run counts match almost exactly, laser point counts within ~4 % mean (decimation approximates a curve's shape, not one charter's exact point choices). Four bugs found and fixed against charts outside that set, each reverified against the full aggregate — see the spec's "Bugs found and fixed".

Roll/swing belongs to the camera element (§1.4), not here.

### 1.4 Camera — zoom and spin

Writeup: [`specs/camera.md`](specs/camera.md). Implementation: [`scripts/camera/`](scripts/camera/). Scope is lane tilt, spin/swing and top/bottom zoom; `zoom_side`/`center_split`/`rotation_deg`/`*_curve` are out of scope (KSMv2-only or unused), and **pretilt is out of scope by direction** — KSM tilts in anticipation of any laser at all, which is an engine behaviour a chart mapping cannot detect or cancel.

Confirmed against the 30-chart reference set via `correlate.py`:

* **Zoom direction** — `CAM_RotX` correlates positively with `zoom_top`, `CAM_Radi` *negatively* with `zoom_bottom`. Scale is a deliberate approximation (~140 / ~−125); the reference conversions are hand-made, so there is no single exact constant to fit.
* **Spin kind** — vox roll (`roll_type` 1,2,3,4,6,7) → ksh full spin, vox swing (5) → half spin. **100 %, 49/49 + 17/17.** `S<`/`S>` intentionally never emitted.
* **Spin direction** — the roll tag sits on the point immediately *before* a same-tick slam, and the slam's direction sets clockwise/counterclockwise. **100 %, 66/66.**
* **Corpus facts** — 82 % of charts use `CAM_RotX`/`CAM_Radi`, 9 % use manual `Tilt`. `roll_type` **7** exists (v12, 49 rows) and is undocumented in the inherited notes.
* **v13 surveyed** — structurally a superset of v12; `C8` is near-universally `0` for every `roll_type`; new `#BPM OPTION` and `#LOCKED_SPCONTROLER` tags; manual `Tilt` usage rises to 36 %.

Three bugs found and fixed, all the same class — a dropped or overwritten middle point silently changes the interpolated shape. See the spec.

### 1.5 Tape Stop Ex — implemented

`.vox` id 10, spec §4.6b. Unimplemented for the project's whole life; now renders, worth **+2.2 dB** on the frames it touches (12 of 13 charts improved, none worse). It ramps *up* from a floor while accelerating — the opposite motion to plain Tape Stop — and its times are in beats, not seconds.

Its envelope floor is **fitted, not transcribed** (`this+0x46`, never traced). `--tapestop-ex-floor` isolates it. The sweep found a **plateau, not an optimum**: 0.4–0.75 all score within 0.08 dB with charts disagreeing in opposite directions, so 0.5 is a midpoint. All the data supports is "not silence"; do not tune it further against this metric.

---

## 2. Unresolved

None of these block conversion work. **§2.1 is the only known defect** — everything else is a refinement or an untraced detail.

### 2.1 Wobble moves the audio hard, in the wrong direction — the top open item

Wobble is *not* inactive and not too subtle to hear. It changes the audio more than any other effect measured; what it fails to do is move the render *toward* the recording. On feelsseasickness, over frames where Wobble is the only effect running:

```
              d(dry, ref)   d(render, ref)   d(dry, render)
Wobble           5.330          5.723            6.382
Gate             5.244          2.416            4.082
Retrigger        7.206          2.700            6.220
```

Gate and Retrigger start far from the reference and end close. Wobble travels **further than either** and ends up slightly *worse* than doing nothing. That rules out a whole class of causes — it is not "not applied", "mix too low", or "mistimed". The *shape* is wrong: filter type, sweep waveform, frequency mapping, or phase.

Aggregated over 6 charts (`masscheck.py`, exclusive-frame gain, higher is better):

```
Wobble     +0.024    Flanger    +1.278    BitCrusher +2.250    TapeStop  +2.329
SideChain  +2.714    Retrigger  +2.884    Gate       +3.200
```

Every other DSP buys +1.3 to +4.1. Wobble buys nothing, and is negative on some charts. This reproduces across independent songs, so it is not one chart's quirk — and it is not the recordings, since the same files give every other effect a healthy margin.

**Ruled out:** LFO phase continuity (implemented, moved it −0.425 → −0.392); block size (64/128/512 all ≈ −0.4); period units (the wrapper computes `(60/BPM)·period`, i.e. beats — the code was already right).

**What to check, in order:**

1. **The frequency computation, term by term.** Disassemble `0x1806414f0` against §4.9's five waveform cases rather than testing hypotheses one at a time. Start with log-triangle (`wave_type 3`), which every observed chart uses.
2. **The `filterType`/`waveType` column assignment.** `run_fx` reads `ftype = p[0]`, `wtype = p[1]`. That is *inferred*, and self-consistent only because the observed rows happen to be valid either way round. Verify at the wrapper which slot feeds the filter selector.
3. **The resonance trim.** `filter_blocked` applies `(1 − Q·0.04)` to the mixed signal for LPF/HPF; if Wobble's leaf differs, level is wrong throughout.

### 2.2 SE level is derived but lands ~2 dB under the fit

Per-sample gain is authored in the `S3V0` header (§6.1.4): slam 0.5513, chips 0.2239, music 1.0000. The capture wants ~0.69 for the slam — a clean ×1.25. Not a metric artefact: a slam-local score with the offset taken from frames far from any slam gives the same answer. Since the metric only sees the SE:music *ratio*, a constant ×0.8 on the music path would explain it exactly.

`--se-trim` **is** that unexplained 2 dB, isolated so it can be deleted once someone explains it.

*Ruled out:* a per-bank gain; the duck resting below unity; `--duck-hold`; `--se-polyphonic`; another module owning the mixer.

*Where to look:* the music voice is bank 2, loaded through the **standalone `.s3v`** loader at `0x1805cf8c8` — a different function from the `.s3p` bank loader, with a second `powf` result at `[rsp+0x60]` whose consumer was never traced. The `.s3p` loader has the same loose end: it appends the gain into a `std::vector<float>` (`0x1805ced2c`) in addition to setting the connection, and where that vector is read is unknown. One of those two is the likely home.

### 2.3 What selects `fs00_virtical_se01` vs `fs01_virtical_se02`

The play path is fully traced (§6.1.1): the sample index is **authored into the gameplay event** (`event+0x08`, verbatim), not computed at play time. Whatever builds that 28-byte event vector decides, and that producer was never found — the vector arrives as `Game::GameAudio::Update`'s second argument, and neither field-store scans nor vtable xref-chasing reached it. `FUN_18041c220` constructs the object at `world+0xb8`, if that helps.

Does not block rendering: every measured chart uses index 0. **Worth a second look during the notes element** — note and laser gameplay events very likely live in that same vector, so finding its producer may pay twice.

### 2.4 Effect state continuity — done for Wobble, open for BitCrusher and Gate

The engine's LFO/hold/step counters are object members that run continuously; the reimplementation restarted them per note. Wobble is now threaded (`this+0x238`, written back every block; `--no-persist` restores the old behaviour).

BitCrusher's sample-and-hold position and Gate's step counter are almost certainly members too, but were not traced and are not threaded. Both score well (+2.3 / +3.2), so there is no measured pressure — **do not touch them without a measurement to justify it**.

### 2.5 Transcription gaps

* **Pitch Shift** (id 9) — algorithm identified as PSOLA and written up (§4.10), but **not implemented**. The grain-count/hop bookkeeping on the upward-shift branch and the cross-call ring-buffer indexing were not extracted; the decompilation is 631 lines of auto-vectorized pointer code.
* **Composite kind 14** (id 13) — stores `{tick, value}` keyframes and interpolates between them, dispatched like any other effect kind. What the interpolated value ultimately modulates was not reached. `p2 ∈ [-24,24]` reads plausibly as semitones, making an animated pitch bend the leading guess — unconfirmed.
* **Echo's 7th chart field** is unexplained. §3 describes it as "grid alignment/update period", but the Echo wrapper demonstrably does not call the snap, so that description is at best imprecise. It is `0.00` on every row of every chart examined.
* **`Timeline` uses a float-seconds clock; the engine uses integer samples** with a truncating `samplesPerBeat = trunc(2646000/BPM)`. On charts whose BPM does not divide 2646000 evenly the two drift, so `grid_snap_offset` returns a few tens of samples where it should return zero. Inaudible, but wrong wherever position arithmetic is compared. The fix is an integer-sample clock.

### 2.6 `#TRACK AUTO TAB` — the parameter sweep half is missing

The span-and-effect half is implemented and on by default (§6.3), worth +1.07 dB across 11 of 11 charts. What is missing is `#TAB PARAM ASSIGN INFO`'s laser-driven parameter sweep, where the knob slides one of the borrowed effect's parameters between two bounds.

Blocked on direction: real charts have C2 > C3 about as often as not, so the pair is a *from → to* rather than a lo/hi, and which end maps to the laser's home side was never determined. Borrowed effects currently run at their authored parameters — correct for the ~59 % of spans with no modulation configured, incomplete for the rest.

Now that the spans render, the direction is **testable by A/B** rather than needing the untraced runtime consumer: implement both readings and score them on the ~5 % of charts carrying a nonzero assign row, the same way §2.7 and the grid-snap question were settled.

### 2.7 Laser + FX combination: the binary and the measurement still disagree

Spec §8.1. When a tab-laser effect overlaps an FX-button hold, the disassembly reads as `dry` (the laser reads the original track and overwrites), but measurement says `chain` — now decisively: **13 of 16 charts, and `add` wins none.**

So this is no longer "a soft signal whose margin is unknown". The measurement is solid and **the binary reading is what deserves re-examination** — specifically whether `FUN_18062e3d0`'s source-pointer restore applies only to the FX sub-chain, or whether `param_2` already points at the FX result by the time it is restored.

Not in doubt: FX-L + FX-R genuinely chain, and the default peak filter is a separate device stage that always stacks on top.

### 2.8 No measured floor for the non-kamui recordings

kamui has a codec floor of 1.14, which is what makes "1.822" interpretable. The recordings in `scripts/shared/reference/ksh/` have no such floor measured, so "+1.07 gain" has no yardstick — nobody knows whether 0.2 or 2.0 of headroom remains. Cheapest estimate: score a chart's *idle* frames, where the render is the dry track by construction.

### 2.9 Camera — spin length needs a ground-up re-derivation

Full detail: `specs/camera.md` "Spin/swing: length". `camera.py`'s `DEFAULT_BEATS` table is lifted from the inherited notes' *naming* ("6-beat roll", "2-beat roll") rather than fit from data, and is already known wrong for types 2 and 5, whose observed defaults (72, and 72–96) contradict the 64 and 96 those names predict. Types 6/7 use a different mechanism entirely (`C9` fallback, inferred from magnitude, never confirmed against the renderer). Nothing here was derived; each piece was patched onto the last.

**By direction:** treat every `roll_type`/`C8`/`C9` claim in `vox_format.md` as a hypothesis. Re-derive all seven from regression against the reference conversions — the method that already got kind mapping and direction to 100 %. Expect thin samples for types 2/4/5 and *zero* reference coverage for 6/7; closing those may need more reference charts or the DLL.

---

## 3. To do

### 3.0 Bundle the layered SE with the tkinter app build

### 3.1 The Tkinter application
