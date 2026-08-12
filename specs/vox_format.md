# VOX format documentation

## Credits and status

This document began as **zacharied's** VOX format notes and was substantially rewritten and extended by **m0seng**, whose v10/v12-focused version is what this project inherited. Both were invaluable — most of the structure below is still theirs, and the parts this project has changed are changes to *their* groundwork, not a replacement for it.

**This project now maintains this document directly**, correcting inherited claims in place rather than annotating around them in other files.

Text marked **[corrected]**, **[added]** or **[verified]** comes from this project's own work — Ghidra decompilation of `modules/soundvoltex.dll`, cross-checked against all 8107 shipped charts in `data/music/` and, where audible, against cabinet recordings in `scripts/shared/reference/ksh/`. **Unmarked text is inherited and not necessarily re-verified**: treat it as a well-informed hypothesis. DSP-level detail lives in [`audio_engine.md`](audio_engine.md), camera detail in [`camera.md`](camera.md).

## Notes

These docs focus on the newer VOX versions v10 and v12, which combined make up virtually all charts found in EG (older charts appear to have been ported to v10). A newer **v13** exists (see "Format version 13" near the end of this document) — that section is this project's own survey, since v13 postdates the inherited notes.

Some terminology and conventions:

+ **Tabsep** is short for "tab-separated".

+ **Commasep** is short for "comma-separated".
    + Comma-separated lines in the VOX format seem to always have tabs following the commas.

+ **CX**, where X is a number, refers to a specific *0-indexed* column in tab- or comma-separated data.

+ **(v10)** and **(v12)** denote version-specific parts of the format.

+ **(Ndp)**, where N is a number, indicates a number to N decimal places.

## Encoding

VOX files use either **UTF-8** or **Shift-JIS** encoding. It is not obvious which one is used when, and attempting to open a VOX file in the wrong encoding will fail if there are Japanese comments in the file.

## Comments

**Comments** begin with `//`. Note that they don't necessarily start at the beginning of a line!

All VOX files begin with the following three lines:

```
//====================================
// SOUND VOLTEX OUTPUT TEXT FILE
//====================================
```

## Timings and time signatures

**Timings** are used throughout the VOX format to describe points in time in a chart. They appear in the following format:

```
 +---------- Measure: bar number (1-indexed)
 |  +------- Beat within the measure (1-indexed)
 |  |  +---- Cell within the beat (0-indexed)
 |  |  |
mmm,bb,cc
```

To understand timings we also have to understand **time signatures**, which describe the division of each measure into beats and cells. Time signatures are made up of a top number and a bottom number:

+ The top number is the **number of beats per measure**.

+ The bottom number is the **beat value**.
    + Let $x$ be the number of cells in a full 4/4 measure (= `BEAT RESOLUTION` * 4) (usually $x$ = 192).
    + Then the beat value can be thought of as "beats per full 4/4 measure", or "beats per $x$ cells".
    + This is usually a power of 2 (although other divisors of $x$ should work).
    + **Number of cells per beat** = $x$ / beat value

+ For example: with $x$ = 192, a bar with time signature 4/4 has 4 beats per measure, and 192/4 = 48 cells per beat.

Time signature changes throughout a chart can be found in `#BEAT INFO`, and BPM changes in `#BPM INFO`.

## Sections and tags

A VOX file is split into **sections** which describe different things about a chart. These can be broadly divided into:

+ **metadata sections**, which contain information about the whole chart, such as time signatures, BPMs, and FX definitions;
+ **tracks**, which contain the main timed elements, such as notes, FX, lasers, camera movements, etc.

Sections are enclosed by **tags**, which are lines beginning with `#`.

+ Each section starts with an **opening tag**, which has a name describing the section type.
+ Sections end with a **closing tag**, which is always `#END`.
    + Some official charts contain extra closing tags which do not close a section; these can be ignored.

## Metadata

The metadata sections of the VOX format are listed below in order of appearance.

### `#FORMAT VERSION`

Single integer denoting the VOX version.

### (v12) `#BEAT RESOLUTION`

> **[added] — do not hardcode 48.** The tag is absent on 8088 of 8107 charts, which makes "cells per beat is 48" a comfortable and wrong assumption. Distribution: `48` (absent) ×8088, `144` ×1, `240` ×10, `480` ×8. On those 19 charts, assuming 48 scales **every** position and length by the ratio — 10x on a 480 chart — so notes start at the wrong time and holds run an order of magnitude long. This project's audio renderer carried that bug and it distorted three separate measurements before being caught. See [`audio_engine.md`](audio_engine.md) §5.3.

(Optional) Single integer denoting the number of cells in a 1/4th note (48 by default).

### `#BEAT INFO`

(Tabsep) Defines time signature over the chart.

+ C0: Timing
    + This is always the start of a measure (no known counterexamples).
+ C1/C2: Time signature (see Timings)
    + C1: Top number (beats per measure)
    + C2: Bottom number (beat value)
+ For some reason, it is possible for entries to overlap in time; one example is Xevel MXM.

### `#BPM INFO`

(Tabsep) Defines BPM and pauses over the chart.

+ C0: Timing
+ C1: Beats per minute (4dp)
    + Actually, this might be 1/4th notes per minute? See Shockwave Syndrome.
    + Or it might be 1/nth notes where n is the number in C2...
+ C2: Pause (?)
    + This column seems to always be `4` or `4-` (no known counterexamples).
    + In particular, the `-` denotes a pause.
    + The `4` may be the beat value used for the BPM?
+ Of note here is the concept of "default BPM", which is the BPM which is matched to your global scroll speed setting in the game.
    + In KSH this is an explicit field, but in VOX there is no such field in chart files or `music_db.xml`.
    + Instead, the default BPM for VOX is whichever BPM lasts the longest in the chart, measured by time in seconds (NOT beats!).
+ Unlike time signatures, BPM changes can occur away from the start of a measure. This is even possible, albeit uncommon, with pauses (Xevel MXM is the only known example).

### `#TILT MODE INFO`

+ C0: Timing
+ C1: Tilt mode
    + `0`: Normal tilt with laser
    + `1`: Bigger tilt with laser
    + `2`: Bigger tilt with laser, stay at maximum tilt
    + This is just set to 0 for almost all recent charts.
        + Notable exceptions include Fiat Lux XCD and OVER+TURE MXM.

### `#LYRIC INFO`

(Tabsep) Obsolete?

+ zacharied says it "defines stuff like Two-Torial's LISTEN".
+ However, it is now empty, even in Two-Torial.
    + It has been replaced by `SpecialN` commands in `#SPCONTROLER`.

### `#END POSITION`

Single timing defining the end of the chart.

### `#TAB EFFECT INFO`

(Commasep) This section contains 5 lines, corresponding to laser effects 1-5 which can be referenced by laser tracks (`#TRACK1`/`#TRACK8`).

+ C0: Effect type
    + `1`: Lowpass filter
    + `2`: Highpass filter
        + Parameters for both filters:
        + C1: Mix % (2dp)
        + C2/C3: Lower/upper bounds of cutoff (2dp)
            + The laser's position is used as the interpolated value between the bounds.
            + Lowpass: Default side high, opposite side low
            + Highpass: Default side low, opposite side high
        + C4: Filter resonance (2dp)
    + `3`: Bitcrush
        + C1: Mix % (2dp)
        + C2: Sample rate reduction factor (integer)

### `#FXBUTTON EFFECT INFO`

(Commasep) This section contains 12 pairs of lines. Each pair of lines corresponds to a pair of effects which can be referenced by FX tracks (`#TRACK2`/`#TRACK7`/`#TRACK AUTO TAB`).

**Both lines of a pair are applied, in series** — [corrected]; the second line is all-zero on most charts, which made it look skippable, but the dispatcher (`FUN_18062e3d0`) loops its sub-index over {0, 1} and chains the second effect onto the first's output. Dropping the all-zero lines also shifts every later pair index by one, so a chart that does use the second slot breaks twice over.

+ C0: Effect type — **[corrected]**, the two TODOs that used to sit here are resolved. Four of the inherited names were wrong; the table below is traced from the setup function `FUN_18022db60`, which maps each id to an internal effect kind and parameter vector, through to the DSP routine that actually crunches the samples. Full derivation, per-effect parameter math and DLL addresses: [`audio_engine.md`](audio_engine.md) §3–§4.

    | id | inherited name | **actual** | evidence |
    |---|---|---|---|
    | `0` | No effect | No effect | — |
    | `1` | Retrigger | Retrigger | ✓ |
    | `2` | Gate | Gate | ✓ |
    | `3` | Phaser | **Flanger** | modulated fractional delay + feedback taps = flanger topology (`0x18063f420`) |
    | `4` | Tape stop | Tape Stop | ✓ |
    | `5` | Sidechain | Side Chain | ✓ — an amplitude envelope, no detector, not real compression |
    | `6` | Wobble | Wobble | ✓ — LFO sweeping one of the biquads |
    | `7` | Bitcrusher | Bit Crusher | ✓ — sample-and-hold decimator only, *no* bit-depth reduction despite the name |
    | `8` | Echo (?) | **Echo / Retrigger Ex** — the `(?)` resolves to yes | shares DSP `0x18063ffb0` with Retrigger, 7th field |
    | `9` | Pitchshift | Pitch Shift | ✓ — PSOLA (§4.10) |
    | `10` | Highpass | **Tape Stop Ex** | 5 float params with tape-stop-shaped clamps, not a filter (`0x180640c20`) |
    | `11` | Lowpass | Low Pass Filter | ✓ |
    | `12` | Flanger | **High Pass Filter** | setup case `0xc` → vec `+0x88` → kind 13 → `0x18063e500` |
    | `13` | *(absent)* | **[added]** composite / keyframed effect | own keyframe vector, dispatched as kind 14 |

    Chart data corroborates the swap independently: ids 11 and 12 both carry 4 params shaped `mix, freq, freq, Q` like filters, while id 3 carries 5.

+ The number of columns in each line depends on the number of parameters that the effect has, which varies between effect types. Exact per-type column order, from the reader `FUN_180239810`:

    ```
    1  -> %d, %d,  %f, %f, %f, %f, %f      2  -> %d, %f, %d, %f
    3  -> %d, %f,  %f, %f, %d, %f          4  -> %d, %f, %f, %f
    5  -> %d, %f,  %f, %d, %d, %d          6  -> %d, %d, %d, %f, %f, %f, %f, %f
    7  -> %d, %f,  %d                      8  -> %d, %d, %f, %f, %f, %f, %f, %f
    9  -> %d, %f,  %f                      10 -> %d, %f, %f, %f, %f, %f
    11 -> %d, %f,  %f, %f, %f              12 -> %d, %f, %f, %f, %f
    ```

+ **Units are not uniform, and are not all seconds** — [added]. Period/length fields are mostly in **beats** (converted with `60/BPM` by each effect's wrapper), but not all of them:

    | effect | field | unit |
    |---|---|---|
    | Retrigger / Echo | length | beats |
    | Gate | period | beats |
    | Side Chain | period | beats |
    | Wobble | period | beats |
    | Flanger | period | **measures** |
    | Tape Stop (id 4) | duration | **seconds** — passed through unconverted |
    | Tape Stop Ex (id 10) | duration, preroll, window | **beats** — unlike id 4 |
    | Bit Crusher | rate | raw sample count |

    The id 4 / id 10 split is a genuine trap: the two effects share a name and disagree on units. Reading id 10's fields as seconds makes its preroll outrun the note on any fast chart, and the effect then silently never fires.

### `#TAB PARAM ASSIGN INFO`

(Commasep) This section allows lasers to use the effects defined in `#FXBUTTON EFFECT INFO`, when enabled in `#TRACK AUTO TAB`.

**Always exactly 24 rows, in every one of the 8107 shipped charts** — [verified] — i.e. one row per `#FXBUTTON EFFECT INFO` line (12 pairs × 2), present whether used or not. Only **431 charts (5.3 %)** have any row whose C1–C3 are nonzero, so on ~95 % of charts this section is entirely inert padding. That rarity is worth knowing before spending effort here.

**This section has nothing to do with the ordinary laser filter sweep** — [added]. The 0–127 knob feeding `#TAB EFFECT INFO` filters is plain linear interpolation of laser position; this section applies only to effects borrowed from `#FXBUTTON EFFECT INFO` via `#TRACK AUTO TAB`.

+ C0: index of effect pair in `#FXBUTTON EFFECT INFO` (0-indexed) — [verified], the inherited `(?)` can be dropped. Across every shipped chart this column is never anything other than `0,0,1,1,2,2,…,11,11`, so it is a positional counter and the row-to-pair mapping is exactly the one the inherited note guessed.

+ C1: index of respective effect's parameter to be adjusted
    + `0`: no parameter to be adjusted
    + Otherwise, 0-indexed with respect to column (1-indexed w.r.t. parameter).

+ C2/C3: lower/upper bounds of parameter
    + The laser's position is used as the interpolated value between the bounds.
    + The inherited TODO ("left to right, or default side to opposite side?") is **still open** — the consumer that reads these bounds at playback was never located. Note that C2 > C3 occurs in real data (e.g. `6, 3, 3.00, 0.50` and `2, 2, 24.00, 4.00`), so "lower/upper" is not an ordering: the pair is a *from → to*, and which end the laser's home side maps to is exactly the question.
    + **Now testable.** `apply_chart.py` renders `#TRACK AUTO TAB` spans, so the two readings can be A/B'd against cabinet recordings on the ~5 % of charts carrying a nonzero row — which is how the effect-combination and grid-snap questions were settled. That is the cheapest route to closing this.

+ Worked example — `0002_broken_iroha` 4i, the smallest chart carrying a nonzero row:

    ```
    #TAB PARAM ASSIGN INFO row 12:   6, 3, 3.00, 0.50    -> pair 6 (a Wobble), param 3, swept 3.00 -> 0.50
    #TRACK AUTO TAB single row:      021,03,00  96  8    -> from 021,03,00 for 96 cells, laser uses pair 8
    ```

    Note the two do not refer to the same pair: the chart's one modulation entry is on pair 6, while its one AUTO TAB span borrows pair 8 (a Side Chain) with no modulation attached. So the two sections are **independently indexed, not a parent/child pair** — a laser span can borrow an effect with or without a parameter sweep configured for it.

### `#REVERB EFFECT PARAM`

Original purpose unknown; currently empty for all charts.

## Tracks

### `#TRACK1`/`#TRACK8`

(Tabsep) These tracks correspond to the left and right laser respectively.

+ C0: Timing

+ C1: Node position
    + Ranging from far left to far right
    + (v10) Integer, 0 - 127
    + (v12) Decimal, 0 - 1 (6dp)

+ C2: Node type
    + `0`: Continuing a laser
    + `1`: Starting a laser
    + `2`: Ending a laser

+ C3: Roll/swing type
    + In all of the lengths below, one beat refers to one 1/4th note.
    + Note that all of these lengths refer to the time it takes for the roll/swing to completely finish, including overshoots.
        + Thus, they are different from KSM roll lengths, where the overshoot occurs after the specified length has passed.
    + `0`: No roll
    + `1`: 6-beat roll
    + `2`: 2-beat roll
    + `3`: 3-beat roll
    + `4`: 12-beat triple roll
    + `5`: 3-beat swing (or 2.5 beats?)
    + `6`: (v12) 8x-speed roll (length must be specified in C8)
    + `7`: **[added]** — undocumented in the inherited notes but real: 49 rows across the corpus, v12 only. Behaves like type `6` (same `C8`/`C9` length mechanism), and this project's camera converter had a bug precisely because a `6`-only fallback was never extended to `7`.
    + **[corrected] — the per-type beat lengths above are names, not measurements.** They come from the inherited notes' own naming and do not all survive checking against hand-made reference conversions: types `2` and `5` have observed defaults (72, and 72–96) that contradict the 64 and 96 their names imply. This project's converter still carries the name-derived table as a working approximation, flagged as unresolved — see [`camera.md`](camera.md) "Spin/swing: length". Treat every number in this list as a hypothesis; only the *kind* mapping (roll vs swing) and the spin *direction* rule have been verified to 100 % against reference charts.

+ C4: Laser effect
    + The effect is applied until the timing of the next node.
    + `0`: Peak filter
        + Default side low, opposite side high
    + `1`-`5`: Index of effect in `#TAB EFFECT INFO` (1-indexed)
        + Low/high sides depend on filter type
    + `6`: No effect — [verified], the inherited `(?)` can be dropped
    + **[verified]** — this whole column is confirmed at the dispatcher, which keys its effect map on `noteField[4] - 1`, so C4 `1..5` becomes map key `0..4` = the five `#TAB EFFECT INFO` slots, and C4 `0` lands on a "nothing" sentinel.
    + **`0` (peak filter) is not an entry in `#TAB EFFECT INFO` and is not produced by the effect engine at all** — [added]. It is a DirectSound parametric-EQ living in the *sound device*, driven straight from the gameplay event dispatcher, lagging the knob by 80 ms and ducking the music while it runs. It is also the overwhelmingly common case in practice (870 of 894 laser nodes on the chart measured). Full transcription in [`audio_engine.md`](audio_engine.md) §7.1.
    + **Do not confuse this column with C7.** Both range 0–5 in practice, so mixing them up looks plausible and silently applies the wrong filters across an entire chart. C4 is the effect; C7 is the curve shape.

+ C5: Laser range
    + `1`: Normal laser
    + `2`: Wide laser

+ C6: Probably unused (always `0`, no known counterexamples)

+ C7: (v12) Curve type
    + `0`: No curve (linear)
    + `1`: Unknown (no known examples)
    + `2`: Cubic Hermite spline
        + This curve type seems to be missing information - the first derivatives (slopes) at the control nodes can probably be set in the in-house editor, but they are not found in the VOX file.
    + `3`: Interpolated linear (for sharp corners)
    + `4`: Sine ease out (start fast, end slow)
    + `5`: Sine ease in (start slow, end fast)
    + Note: this does not always reliably indicate the presence/absence of smooth lasers!
        + e.g.: in 緋色月下、狂咲ノ絶 (nayuta 2017 ver) MXM, some smooth lasers have curve type `0`.

+ C8: (v12) Roll/swing length
    + This is `0` by default which means that the default length of the roll/swing is used.
    + Otherwise, it specifies the length of the roll/swing in 1/4th notes.
    + For rolls of type `6` (8x-speed rolls), it instead specifies the length in 1/32nd notes. (?)
    + **Project survey (v10/v12 corpus, ~8100 charts, all `roll_type` values, not community-sourced)**: `C8` is essentially the *only* length source ever used in v10/v12. `C8=0` legitimately occurs for types 1/2/3/5 (matching "use default" above) but was found on only two charts total across the whole corpus for types 6/7 - both turned out to be misfiled v13 charts (see "Format version 13" below), so in genuine v10/v12 data `C8` is effectively always a real explicit length for types 6/7, matching this section's "must be specified" framing (§ discussion under "Format version 13" corrects this for v13 specifically, not for v10/v12). Type 4 (12-beat triple roll) never has `C8` absent or zero in the corpus (only 3 rows total, too few to generalize from, but consistent). In v10, `C8` (and C9) are usually entirely *absent* rather than present-and-zero - full field-count breakdown in "Format version 13" below, since that's where the contrast became relevant.

+ C9: (v12?) (Optional) Cells per chain
    + Denotes the number of cells per chain contributed by a laser segment.
    + If unspecified, this defaults to 12 for BPMs $< 255$, and 24 for BPMs $\geq 255$.
    + **Project survey**: co-occurring with a populated `C8` is rare in v10/v12 - isolated to two charters' charts across the whole corpus (`i_kuroma`/`madeinlove_kuroma` in v10, `littleredridinghood_roughsketch` in v12). In those charts `C9` holds small values (1-12) alongside a normal nonzero `C8`, consistent with this documented "cells per chain" meaning and unrelated to roll length - i.e. no evidence in v10/v12 of `C9` ever substituting for `C8`. That only happens in v13 - see below.

### `#TRACK2`/`#TRACK7`

(Tabsep) These tracks correspond to the FX-L and FX-R buttons respectively.

+ C0: Timing
+ C1: Note length in cells
    + This is `0` for chip notes.
+ C2:
    + For chip notes this refers to a sample to be played.
        + `0`: No sample
        + `1`: Big snare (quiet) (possibly unused)
        + `2`: Big clap
        + `3`: Short clap
        + `4`: Big snare
        + `5`: Short snare
        + `6`: Crash
        + `7`: Kick + crash + downlifter
        + `8`: Open hi-hat
        + `9`: Kick + crash (different)
        + `10`: Snare + click
        + `11`: Female "oh"
        + `12`: Male "hey"
        + `13`: Male "yeah"
        + `14`: Fireworks ???
        + ~~What other samples there are and where they are defined are not yet known.~~ **[added]** — resolved. There are exactly these 15 and they live in `data/sound/ver5/general_sampler.s3p`, registered as **bank 9** by the loader; the names above match the bank's own `.def` entries (`fs00_virtical_se01` … `fs14_shot13`). `sys_sd_shotfx.2dx` is bank 4 and carries the same 15 names. Each sample's playback level is authored in its own file header (an 8.8 fixed-point dB field), not in the game code — the chips sit 7.83 dB below the laser-slam sample. See [`audio_engine.md`](audio_engine.md) §6.1.
        + **`255` is silent too**, not just `0` — [added]. The trigger reads `if (0 < idx && idx != 255)`, so both ends are "no sample". `0` is overwhelmingly the common value in practice (110 of 111 FX-L chips on one measured chart).
    + For hold notes this is the index of an effect defined in `#FXBUTTON EFFECT INFO`.
        + This is **2-indexed**! (i.e.: `2` is the first effect) — [verified] at the dispatcher, which computes `noteField[4] - 2`.
        + `0` and `1` seem to be unused. (no known examples)
+ C3: (v12?) (Optional) Cells per chain
    + Denotes the number of cells per chain contributed by a hold note.
    + If unspecified, this defaults to 12 for BPMs $< 255$, and 24 for BPMs $\geq 255$.

### `#TRACK3`/`#TRACK4`/`#TRACK5`/`#TRACK6`

(Tabsep) These tracks correspond to BT-A, BT-B, BT-C and BT-D respectively.

+ C0: Timing
+ C1: Note length in cells
    + This is `0` for chip notes.
+ C2: ???
    + Probably unused?
    + Is set to non-zero values, usually `2`, for hold notes, but this does not seem to apply sound effects...
+ C3: (v12?) (Optional) Cells per chain
    + Denotes the number of cells per chain contributed by a hold note.
    + If unspecified, this defaults to 12 for BPMs $< 255$, and 24 for BPMs $\geq 255$.

### `#TRACK AUTO TAB`

(Tabsep) This track is used to apply FX hold effects to lasers.

**Used by 2738 of 8107 charts (33.8 %)** — [verified], which is more common than several effects that get far more attention. This project's audio renderer applies these spans (worth +1.07 dB); the parameter sweep described under `#TAB PARAM ASSIGN INFO` is not implemented.

+ C0: Timing
+ C1: Effect length in cells
+ C2: Effect index
    + This is the index of an effect defined in `#FXBUTTON EFFECT INFO`.
    + This is **2-indexed**! (i.e.: `2` is the first effect)
    + `0` and `1` seem to be unused.
    + **[verified]** corpus-wide, and worth getting right — reading it as 0-indexed inverts the apparent relationship between this track and `#TAB PARAM ASSIGN INFO`. Two checks over the 2128 AUTO TAB rows in charts that also carry modulation:
        + **Range**: C2 spans `2..13` — twelve consecutive values, matching the twelve pairs under `C2 - 2`. A 0-indexed reading would leave `12` and `13` pointing past the last pair.
        + **Correlation**: read as 2-indexed, a span lands on a pair carrying a modulation entry 40.7 % of the time; read as 0-indexed, 13.1 %, which is roughly chance.
    + A `254` also appears (5 rows), which looks like the same "none" sentinel as the FX chip column's `255`, plus one stray `0`.
+ Relationship to `#TAB PARAM ASSIGN INFO` — **[added]**: this track picks *which* effect pair a laser span runs; that section optionally says *which parameter of that pair the laser sweeps, and between what bounds*. Roughly 59 % of AUTO TAB spans land on a pair with no modulation configured, which is simply the "run the effect at its authored parameters" case. Worked example under `#TAB PARAM ASSIGN INFO` above.

### (v12) `#TRACK ORIGINAL L`/`#TRACK ORIGINAL R`

(Tabsep) These tracks have the same set of fields as `#TRACK1` and `#TRACK8`. However, while `#TRACK1` and `#TRACK8` contain the interpolated nodes of curved lasers, `#TRACK ORIGINAL L` and `#TRACK ORIGINAL R` do not; these tracks only contain the control nodes.

**Present in 2488 charts (30.7 %)** — [verified] — and almost certainly **safe to ignore for playback**. Since `#TRACK1`/`#TRACK8` already carry the fully-interpolated curve the game itself plays, anything reading a chart to reproduce gameplay (audio or notes) wants those, not these. The most natural reading is that these are the in-house editor's authoring data, kept so a curve can be reloaded and re-edited from its original control points. This project's converters read only `#TRACK1`/`#TRACK8` and no discrepancy has ever been traced to that choice — though note this is an argument from redundancy, not a positive trace of the game ignoring them.

### `#SPCONTROLER`

(Tabsep) Controls the appearance of the game in various ways, for example camera movement and backgrounds/Live2Ds.

+ Of note: entries in this section often appear out of order with respect to timing!
+ C0: Timing
+ C1: Control type
    + Known control types:
        + `Realize`
            + Controls how the camera approaches different positions?
            + C2 = 3: controls `CAM_Radi`?
            + C2 = 4: controls `CAM_RotX`?
            + C3, C4, C5 seem to correspond to "overshoot", "start" and "end" respectively?
        + `AIRL_ScaX`/`AIRR_ScaX`
            + Not yet known what these controls do.
        + `CAM_RotX`
            + Rotates the lane around the judgement line.
            + Roughly equivalent to KSM's `zoom_top`.
            + Entries of this type seem to span the whole chart combined.
            + C3: length of movement in cells
            + C4/C5: start/end positions of movement
                + Decimal, -1.00 - 1.00 (2dp)
                + Higher number = lane top is higher on screen
            + C2/C6/C7 appear unused.
        + `CAM_Radi`
            + Zooms in and out of the judgement line.
            + Roughly equivalent to KSM's `zoom_bottom`.
            + Entries of this type seem to span the whole chart combined.
            + C3: length of movement in cells
            + C4/C5: start/end positions of movement
                + Decimal, -1.00 - 1.00 (2dp)
                + Higher number = more zoomed out
            + C2/C6/C7 appear unused.
        + `BIL_RotZ`
            + Rotates the lane and judgement line around the camera (or vice versa?)
            + Only present in April Fools charts.
        + `Tilt`
            + Controls manual lane tilt.
            + C3: length of movement in cells
            + C4/C5: start/end positions of movement
                + Decimal, -1.00 - 1.00 (2dp)
                + Positive = tilt left (like moving red laser)
                + Negative = tilt right (like moving blue laser)
            + C6: node type
                + `0.00`: during a series of manual tilts
                + `1.00`: single manual tilt
                + `2.00`: begins a series of manual tilts
                + `3.00`: ends a series of manual tilts
            + C2/C7 appear unused.
        + `LaneY`
            + Controls position of lane in the y-axis; one way to hide the lane.
            + Note that the y-axis is parallel to the lane here; whereas it is vertically perpendicular to the lane in scripts.
        + `HudY`
            + Seems to hide the HUD, but only in KAC mode?
        + `BAROFF`
            + Hides bar lines (e.g.: in Shockwave Syndrome).
            + C4: `ON` (active)/`OFF` (inactive)
        + `BAR`
            + Manually adds a bar line at the specified time.
            + Not known whether this works when `BAROFF` is not active.
        + `Morphing2`
            + Controls lane split (such as in 666 MXM).
            + C3: length of movement in cells
            + C4/C5: start/end positions of movement
                + Decimal (1dp or 2dp)
                + `0.0`: default (no split)
                + `0.8`: just over 1 lane wide (as seen in 666 MXM)
                + `-2.82`: pairs of button lanes swapped (as seen in EXCEED April Fools MXM)
            + In VW, `Morphing0` and `Morphing1` bend the lane MUSECA-style, and `Morphing3` splits all four lanes; these no longer work in EG.
        + `ManualSpeed`
            + Sets scroll speed multiplier independent of BPM, similar to mania SV (e.g.: in APOCALYPSE RAY).
        + `SpecialN`
            + Controls a lot of things!
            + C4 determines `SpecialN` type. Currently known possible values of C4 are:
                + `EXBG`
                    + Controls the switching of non-Live2D background images.
                + `LANECLEARCOL`
                    + Controls the colour and opacity of the lane area shading that appears when the lane texture is hidden by `LaneY`.
                    + C5: ARGB colour of format `xAARRGGBB` in hexadecimal.
                        + `x80202020` is probably the default value.
                + `EXBGROTF` (April Fools only)
                    + Likely used to change the way the background image rotates with the lane.
                + `ADJRVZ` (April Fools only)
                + `SE` (April Fools only)
                    + Triggers a sound effect.
                    + C5: name of sample used
                + `EXBGTEX` (April Fools only)
                    + Likely used to control additional overlaid background images, such as the messages in EXCEED April Fools MXM.
                + `LIVE2D`
                    + Controls the animation of Live2D backgrounds.
                    + C5: Corresponds to Live2D motion names (although not exactly?)
                + `SIDE` (666 only)
                + `NEMSYS` (XHRONOXAPSULE only)
                + `SIDEBG` (XHRONOXAPSULE only)
                + `FRAME` (SuddeNDeath and Akasha only)
                + `SE2` (SuddeNDeath only)
                + `EXMC_LABEL` (APOCALYPSE RAY and HeaveN's Rain only)
                + `EXMC_PARAM` (APOCALYPSE RAY only)
                + `RENDER_PRESET` (Akasha only)
                + `LANECOL` (Akasha only)

### `#POSTEFFECT`

(Optional) (Tabsep) Controls post-processing effects of the game.

+ C0: Timing
+ C1: ??? (always 2?)
+ C2: Effect length
    + This can be in cells, or in milliseconds with suffix `ms`.
+ C3: Effect name
    + Currently known effect types are:
        + `ChromaticAbberation`
        + `CrtMonitorEffect`
        + `SimpleNoise`
        + `RadicalBlur`
        + `ColorConversion`
        + `SetFrameLabel`
        + `LuminousEffect`
        + `RandomShake`
    + All of these are so far only used on recent 20s and their respective lower difficulties.
+ C4: ??? (always either 0 or 1?)
+ C5: ??? (always 0?)
+ C6: Parameter name
    + Possible parameter names will vary depending on the specified effect.
+ C7: Start value
    + Specified as a float with suffix `f`.
+ C8: End value
    + Specified as a float with suffix `f`.

## `#SCRIPT_DEFINE`

(Optional) Contains scripts that can be applied to notes and lasers.

+ Syntax of a script:

```
@SCRIPTSTART n
<variable> = <expression> [when <expression> <comparison> <expression>]
// more lines...
@SCRIPTEND
```

+ **All tokens must be space-separated!**
+ Numeric values:
    + Integers, e.g.: `48000`
    + Floats, e.g.: `0.178` or `0.355f`
        + These seem to be limited to 3 decimal places.
+ Operators:
    + Arithmetic: `+`, `-`, `*`, `/`
    + Comparison: `==`, `!=`, `>`, `<`, `>=`, `<=`
    + Logical operators are not available.
+ Variables:
    + `$targetStep`: timing of the note in cells since the start.
    + `$offsetX`: note position offset in the X direction.
        + Positive is to the right, negative is to the left.
        + A lane seems to be `0.1775` units wide.
    + `$offsetY`: note position offset in the Y direction.
        + Positive is up, negative is down.
    + Changing these variables changes only the visible position of a note, not its judgement timing.
    + It is not possible to define other variables outside of these.
+ Constants:
    + `$currentStep`: current timing in cells since the start.
+ Expressions may consist of numeric values, arithmetic operators, variables/constants and parentheses.
+ An assignment is successful if the `when` clause is satisfied or absent.
+ Lines in a script are evaluated from top to bottom; **upon the first successful assignment, the script finishes and succeeding lines are ignored.** Therefore, each script performs at most one assignment, and a script can be treated as a chained if-else if statement.

## `#SCRIPTED_TRACK1` ~ `#SCRIPTED_TRACK8`

(Optional) Applies scripts from `#SCRIPT_DEFINE` to the contents of the corresponding one of `#TRACK1` ~ `#TRACK8`.

+ C0: Timing
+ This is followed by a space-separated list of script IDs, which are applied from left to right to anything with a matching timing in the corresponding track.
    + To apply a script to a hold or laser, it seems to be sufficient to apply it to the start timing.
    + An assignment performed by a script is visible to later scripts within a single run of script processing. (?)
        + From EXCEED April Fools MXM's comments: "複数のスクリプトが同じ変数を書き換える場合左のスクリプトから順に処理され、結果が重ね合わされる。"
    + However, assignments in one run of script processing are not visible in the next run.

## Format version 13

**This section is this project's own survey, not from the inherited community notes** (unlike the rest of this document - v13 postdates zacharied's/m0seng's notes). Source: 148 v13 charts from a separate content-pack download (`KFC-2026040700 to 2026071400`), plus the 4 v13 charts already present in the main install's `data/music` (`2393_alive_dadadaizu`, all 4 difficulties - the only v13 charts in that corpus as of this survey; the other 8103 charts there are v10/v12). `shared/vox.py` and `scripts/camera/camera.py` parse and convert all 148 sample files without error or code changes, so structurally v13 is a superset of v12, not a breaking change - everything below is either new or a shift in which fields charts actually populate, not a changed row shape for the sections already documented above.

+ **`#TRACK1`/`#TRACK8` (laser) rows always have all 10 fields (C0-C9) in v13** - C9 (`cells_per_chain`) is no longer omitted the way it usually was in v12 (where most rows had only 9 fields, C0-C8). Confirmed across every roll/swing row in the sample (`roll_type` 1-7 all showed `{10: <count>}` field-count distributions, no 9-field rows at all).
+ **`C8` is near-universally `0` for every `roll_type` in v13 - not just 6 and 7.** A closer follow-up survey (prompted by a question about whether this was 6/7-specific) checked `roll_type` 1-5 too: `C8=0` in 96-100% of rows for every type (`1`: 323/337, `2`: 3/3, `3`: 1/1, `4`: 2/2, `5`: 59/65, `6`: 60/62, `7`: 16/18). For types 1-5 this isn't new behaviour - `C8=0` already meant "use the type's default length" in v12 (see the `#TRACK1`/`#TRACK8` section above), so v13 charts just take that default far more often; camera.py's existing default-length fallback (`DEFAULT_BEATS`) already covers it unchanged.
+ **But `C9`'s value differs sharply by type, and this is where types 6/7 are genuinely different.** When `C8=0`, `C9` (`cells_per_chain`) is small for types 1-5 (sample mean ≈4.3, values mostly 1-8) - consistent with it staying ordinary chain-scoring metadata, unrelated to roll length. For types 6/7 it's consistently and substantially larger (sample mean ≈17.4, values 3-45) - **even within the same chart**: of 33 v13 charts with both a small-type and a 6/7 row, 31 show the 6/7 row's `C9` clearly larger (checked directly, not just corpus-wide averages, to rule out this being a cross-song artifact). This is the evidence for `scripts/camera/camera.py`'s `C9`-as-fallback-length for `roll_type` 6/7 specifically (not the other types) - see `specs/camera.md`'s "Spin/swing: length" for the exact ksh-side conversion and scale factor, and for the honest caveat that "C9 is read as length" is still an inference from magnitude, not confirmed against the renderer. The inherited community claim that type 6's "length must be specified in C8" (`vox_format.md`'s own `#TRACK1`/`#TRACK8` section above) is contradicted either way - `C8` is typically `0` in v13, not a real length, for every roll type including 6.
+ A **`roll_type=7` bug fell out of this follow-up survey**: `scripts/camera/camera.py`'s `C9` fallback was originally written for `roll_type=6` only (from the chart that surfaced this, `2393_alive_dadadaizu`, which happened to only exercise type 6). Type 7 rows with `C8=0` were silently falling through to a generic 3-beat guess instead. Fixed once the same `C8=0`/large-`C9` pattern was confirmed for type 7 too.
+ **`#BPM OPTION`** (new tag, tabsep, 2 rows, seen in 9/148 sample files):
    + `ConstantScroll` - `0` or `1`. `1` in every sample seen. Plausibly a "use a constant visual scroll speed regardless of BPM changes" flag, analogous to ksh's `scroll_speed`/kson's gravity-note concept, but not confirmed against the renderer.
    + `RepresentativeBpm` - a float (e.g. `249`, `174.0000`). Plausibly what ksh calls `to` (the standard tempo for hi-speed values) or vox's own "default BPM" concept (see `#BPM INFO` above), but not confirmed to be numerically identical to either.
+ **`#LOCKED_SPCONTROLER`** (new tag, seen in 4/148 sample files, all `2393_alive_dadadaizu` difficulties in this sample). Same tabsep row shape as `#SPCONTROLER`. Every example seen carries `SpecialN` rows with an `EXMC_LABEL` sub-type (`C4` in `#SPCONTROLER`'s existing `SpecialN` documentation above), e.g. `001,01,00\tSpecialN\t0\t0\tEXMC_LABEL\tx00010000\ti0\t0`. Purpose not investigated beyond noting it exists and parses like `#SPCONTROLER`; not camera-relevant (`SpecialN`/`EXMC_LABEL` is already out of this project's camera scope) and not otherwise explored.
+ **`Realize`'s payload is not always the fixed engine constant it appeared to be.** `specs/camera.md` originally ruled `Realize` out as a per-chart calibration factor because all 30 reference-matched charts (all v10/v12) had byte-identical payloads. In the 148-chart v13 sample, 143/148 files still use that same payload, but **5 files use one of three different payloads** (varying the `CAM_Radi` overshoot/end values specifically, e.g. `17.12`/`85.06`/`135.12` instead of the usual `36.12`/`110.12`). Rare, but a real correction to "always identical" - worth reopening if the zoom scale factor is revisited.
+ **Manual `Tilt` tracks are far more common in v13.** 53/148 sample files (36%) carry at least one manual `Tilt` row, versus 9% (758/8103) in the v10/v12 corpus. Node-type distribution (begins/ends-series counts still balanced at 176/176) and `#SPCONTROLER` row shape are otherwise unchanged - see `specs/camera.md` for what this does and doesn't affect.
+ **Everything else checked and found unchanged**: `#SPCONTROLER` row shape and field count (8, matching v12) for every control type including `CAM_RotX`/`CAM_Radi`/`Tilt`; `roll_type` value range (still 0-7, no new values); laser `curve_type` value range (still within 0,2,3,4,5, no new values); laser `width` (still 1/2 only); `#TRACK2`-`#TRACK7` (BT/FX) row shape (still 3 fields, C3 cells-per-chain not seen populated in this sample); `#FXBUTTON EFFECT INFO`/`#TAB EFFECT INFO` effect-type-id ranges (0-14 and 1-3 respectively, matching `audio_engine.md`'s inventory, no new ids); `#BEAT RESOLUTION` still optional and still varies when present (`240`, `144` seen in this sample, neither new to the concept - just confirming it isn't always 48).
