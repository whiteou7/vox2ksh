# VOX format documentation

## Credits

This document began as **zacharied's** VOX format notes and was substantially rewritten and extended by **m0seng**, whose v10/v12-focused version is what this project inherited. Most of the structure below is still theirs, and the parts this project has changed are changes to *their* groundwork, not a replacement for it. It is now maintained here, with corrections applied in place.

DSP-level detail lives in [`audio_engine.md`](audio_engine.md), camera detail in [`camera.md`](camera.md). Anything still unsettled is collected under "Open questions" at the end; everything else here is what the format does.

## Coverage and sources

Corpus figures quoted below ("8107 charts", "33.8 % of charts") come from `data/music/` in the EG install: 8103 v10/v12 charts plus the four difficulties of one v13 chart. Structural claims are cross-checked against `modules/soundvoltex.dll` where a reader or consumer could be traced.

v10 and v12 together make up virtually all charts in EG (older charts appear to have been ported to v10). **v13** postdates the inherited notes; what is documented about it comes from a 148-chart sample out of a separate content-pack download (`KFC-2026040700` to `KFC-2026071400`) plus the four v13 charts in the main install. v13 is structurally a superset of v12 — same row shapes, no new tag values in the sections already documented here — so v13 notes appear inline under the section they affect rather than in a chapter of their own.

## Conventions

+ **Tabsep** is short for "tab-separated".
+ **Commasep** is short for "comma-separated". Comma-separated lines in the VOX format seem to always have tabs following the commas.
+ **CX**, where X is a number, refers to a specific *0-indexed* column in tab- or comma-separated data.
+ **(v10)**, **(v12)** and **(v13)** denote version-specific parts of the format.
+ **(Ndp)**, where N is a number, indicates a number to N decimal places.

## Encoding

VOX files use either **UTF-8** or **Shift-JIS**. It is not obvious which one is used when, and opening a file in the wrong encoding will fail if it contains Japanese comments.

## Comments

**Comments** begin with `//`, and do not necessarily start at the beginning of a line.

All VOX files begin with the following three lines:

```
//====================================
// SOUND VOLTEX OUTPUT TEXT FILE
//====================================
```

## Timings and time signatures

**Timings** describe points in time throughout the format:

```
 +---------- Measure: bar number (1-indexed)
 |  +------- Beat within the measure (1-indexed)
 |  |  +---- Cell within the beat (0-indexed)
 |  |  |
mmm,bb,cc
```

**Time signatures** describe the division of each measure into beats and cells, and are made up of a top and a bottom number:

+ The top number is the **number of beats per measure**.
+ The bottom number is the **beat value**.
    + Let $x$ be the number of cells in a full 4/4 measure (= `BEAT RESOLUTION` * 4) (usually $x$ = 192).
    + The beat value is then "beats per full 4/4 measure", or "beats per $x$ cells".
    + This is usually a power of 2 (although other divisors of $x$ should work).
    + **Number of cells per beat** = $x$ / beat value

For example: with $x$ = 192, a bar with time signature 4/4 has 4 beats per measure and 192/4 = 48 cells per beat.

Time signature changes live in `#BEAT INFO`, BPM changes in `#BPM INFO`.

## Sections and tags

A VOX file is split into **sections**, broadly divided into:

+ **metadata sections**, which describe the whole chart — time signatures, BPMs, FX definitions;
+ **tracks**, which contain timed elements — notes, FX, lasers, camera movements.

Sections are enclosed by **tags**, lines beginning with `#`. Each section starts with an opening tag naming the section type and ends with `#END`. Some official charts contain extra closing tags which do not close a section; these can be ignored.

## Metadata

Listed in order of appearance.

### `#FORMAT VERSION`

Single integer denoting the VOX version.

### (v12) `#BEAT RESOLUTION`

(Optional) Single integer denoting the number of cells in a 1/4th note, 48 by default.

**Do not hardcode 48.** The tag is absent on 8088 of 8107 charts, which makes 48 a comfortable and wrong assumption. Distribution: `48` (absent) ×8088, `144` ×1, `240` ×10, `480` ×8. On those 19 charts, assuming 48 scales **every** position and length by the ratio — 10× on a 480 chart — so notes start at the wrong time and holds run an order of magnitude long. v13 charts also carry the tag with non-48 values (`240` and `144` seen in the sample).

### `#BEAT INFO`

(Tabsep) Defines time signature over the chart.

+ C0: Timing. Always the start of a measure (no known counterexamples).
+ C1/C2: Time signature (see Timings)
    + C1: Top number (beats per measure)
    + C2: Bottom number (beat value)
+ Entries can overlap in time; one example is Xevel MXM.

### `#BPM INFO`

(Tabsep) Defines BPM and pauses over the chart.

+ C0: Timing
+ C1: Beats per minute (4dp)
+ C2: Pause. Always `4` or `4-` (no known counterexamples); the `-` denotes a pause.
+ "Default BPM" — the BPM matched to the global scroll speed setting — is an explicit field in KSH but has no field in VOX chart files or `music_db.xml`. It is whichever BPM lasts the longest in the chart, measured by time in seconds (**not** beats).
+ Unlike time signatures, BPM changes can occur away from the start of a measure. This is possible, though uncommon, with pauses too (Xevel MXM is the only known example).

### (v13) `#BPM OPTION`

(Tabsep) New in v13, present in 9 of 148 sampled files. Two rows:

+ `ConstantScroll` — `0` or `1`; `1` in every sample seen.
+ `RepresentativeBpm` — a float, e.g. `249` or `174.0000`.

### `#TILT MODE INFO`

+ C0: Timing
+ C1: Tilt mode
    + `0`: Normal tilt with laser
    + `1`: Bigger tilt with laser
    + `2`: Bigger tilt with laser, stay at maximum tilt
    + Set to `0` for almost all recent charts; notable exceptions include Fiat Lux XCD and OVER+TURE MXM.

### `#LYRIC INFO`

(Tabsep) Obsolete. zacharied notes it "defines stuff like Two-Torial's LISTEN", but it is now empty even in Two-Torial — replaced by `SpecialN` commands in `#SPCONTROLER`.

### `#END POSITION`

Single timing defining the end of the chart. This is the arcade chart's official end and often runs measures past the last note, into silence.

### `#TAB EFFECT INFO`

(Commasep) Five lines, corresponding to laser effects 1-5 referenced by laser tracks (`#TRACK1`/`#TRACK8`).

+ C0: Effect type
    + `1`: Lowpass filter
    + `2`: Highpass filter
        + Parameters for both filters:
        + C1: Mix % (2dp)
        + C2/C3: Lower/upper bounds of cutoff (2dp)
            + The laser's position is the interpolated value between the bounds.
            + Lowpass: default side high, opposite side low. Highpass: default side low, opposite side high.
        + C4: Filter resonance (2dp)
    + `3`: Bitcrush
        + C1: Mix % (2dp)
        + C2: Sample rate reduction factor (integer)

The knob-to-cutoff mapping is exponential rather than linear, and the laser bitcrush ignores C2 once the knob moves — see [`audio_engine.md`](audio_engine.md) §4.2.

### `#FXBUTTON EFFECT INFO`

(Commasep) 12 pairs of lines. Each pair corresponds to a pair of effects referenced by FX tracks (`#TRACK2`/`#TRACK7`/`#TRACK AUTO TAB`).

**Both lines of a pair are applied, in series.** The second line is all-zero on most charts, which makes it look skippable, but the dispatcher (`FUN_18062e3d0`) loops its sub-index over {0, 1} and chains the second effect onto the first's output. Dropping the all-zero lines also shifts every later pair index by one, so a chart that does use the second slot breaks twice over.

+ C0: Effect type. Four of the inherited names were wrong; the table below is traced from the setup function `FUN_18022db60`, which maps each id to an internal effect kind and parameter vector, through to the DSP routine that crunches the samples. Full derivation, per-effect parameter math and DLL addresses: [`audio_engine.md`](audio_engine.md) §3–§4.

    | id | inherited name | actual | evidence |
    |---|---|---|---|
    | `0` | No effect | No effect | — |
    | `1` | Retrigger | Retrigger | ✓ |
    | `2` | Gate | Gate | ✓ |
    | `3` | Phaser | **Flanger** | modulated fractional delay + feedback taps = flanger topology (`0x18063f420`) |
    | `4` | Tape stop | Tape Stop | ✓ |
    | `5` | Sidechain | Side Chain | ✓ — an amplitude envelope, no detector, not real compression |
    | `6` | Wobble | Wobble | ✓ — LFO sweeping one of the biquads |
    | `7` | Bitcrusher | Bit Crusher | ✓ — sample-and-hold decimator only, *no* bit-depth reduction despite the name |
    | `8` | Echo (?) | **Echo / Retrigger Ex** | shares DSP `0x18063ffb0` with Retrigger, plus a 7th field |
    | `9` | Pitchshift | Pitch Shift | ✓ — PSOLA (§4.10) |
    | `10` | Highpass | **Tape Stop Ex** | 5 float params with tape-stop-shaped clamps, not a filter (`0x180640c20`) |
    | `11` | Lowpass | Low Pass Filter | ✓ |
    | `12` | Flanger | **High Pass Filter** | setup case `0xc` → vec `+0x88` → kind 13 → `0x18063e500` |
    | `13` | *(absent)* | composite / keyframed effect | own keyframe vector, dispatched as kind 14 |

    Chart data corroborates the swap independently: ids 11 and 12 both carry 4 params shaped `mix, freq, freq, Q` like filters, while id 3 carries 5.

+ The number of columns per line depends on the effect type. Exact per-type column order, from the reader `FUN_180239810`:

    ```
    1  -> %d, %d,  %f, %f, %f, %f, %f      2  -> %d, %f, %d, %f
    3  -> %d, %f,  %f, %f, %d, %f          4  -> %d, %f, %f, %f
    5  -> %d, %f,  %f, %d, %d, %d          6  -> %d, %d, %d, %f, %f, %f, %f, %f
    7  -> %d, %f,  %d                      8  -> %d, %d, %f, %f, %f, %f, %f, %f
    9  -> %d, %f,  %f                      10 -> %d, %f, %f, %f, %f, %f
    11 -> %d, %f,  %f, %f, %f              12 -> %d, %f, %f, %f, %f
    ```

+ **Units are not uniform, and are not all seconds.** Period/length fields are mostly in **beats** (converted with `60/BPM` by each effect's wrapper), but not all:

    | effect | field | unit |
    |---|---|---|
    | Retrigger / Echo | length | beats |
    | Gate | period | beats |
    | Side Chain | period | beats |
    | Wobble | rate | **cycles per beat** — a rate, not a period; the wrapper takes its reciprocal |
    | Flanger | period | **measures** |
    | Tape Stop (id 4) | duration | **seconds** — passed through unconverted |
    | Tape Stop Ex (id 10) | duration, preroll, window | **beats** — unlike id 4 |
    | Bit Crusher | rate | raw sample count |

    The id 4 / id 10 split is a genuine trap: the two effects share a name and disagree on units. Reading id 10's fields as seconds makes its preroll outrun the note on any fast chart, and the effect then silently never fires.

### `#TAB PARAM ASSIGN INFO`

(Commasep) Lets lasers modulate a parameter of the effects defined in `#FXBUTTON EFFECT INFO`, when enabled in `#TRACK AUTO TAB`.

**Always exactly 24 rows, in every one of the 8107 shipped charts** — one row per `#FXBUTTON EFFECT INFO` line (12 pairs × 2), present whether used or not. Only **431 charts (5.3 %)** have any row whose C1–C3 are nonzero, so on ~95 % of charts this section is inert padding.

**This has nothing to do with the ordinary laser filter sweep.** The 0–127 knob feeding `#TAB EFFECT INFO` filters is plain interpolation of laser position; this section applies only to effects borrowed from `#FXBUTTON EFFECT INFO` via `#TRACK AUTO TAB`.

+ C0: index of effect pair in `#FXBUTTON EFFECT INFO` (0-indexed). Across every shipped chart this column is never anything other than `0,0,1,1,2,2,…,11,11`, so it is a positional counter.
+ C1: index of the pair's parameter to be adjusted
    + `0`: no parameter to be adjusted
    + Otherwise, 0-indexed with respect to column (1-indexed w.r.t. parameter).
+ C2/C3: the bounds the parameter is swept between, as a *from → to* pair rather than an ordering — C2 > C3 occurs in real data (e.g. `6, 3, 3.00, 0.50` and `2, 2, 24.00, 4.00`). The laser drives it as `value = C2 + (C3 - C2) · clamp(laserPosition, 0, 1)`, refreshed every 512 samples, with C1 selecting which of the pair's two effects is modulated by chain position. The control source is a laser with C4 = 6.
+ Worked example — `0002_broken_iroha` 4i, the smallest chart carrying a nonzero row:

    ```
    #TAB PARAM ASSIGN INFO row 12:   6, 3, 3.00, 0.50    -> pair 6 (a Flanger), param 3, swept 3.00 -> 0.50
    #TRACK AUTO TAB single row:      021,03,00  96  8    -> from 021,03,00 for 96 cells, laser uses pair 8-2 = 6
    ```

    The two sections are **independently indexed** (C0 here is 0-indexed, AUTO TAB's C2 is 2-indexed) and not a parent/child pair: a laser span can borrow an effect with or without a parameter sweep configured for it. Roughly 59 % of AUTO TAB spans land on a pair with no modulation, which is simply the "run the effect at its authored parameters" case.

### `#REVERB EFFECT PARAM`

Empty for all charts; purpose unknown.

## Tracks

### `#TRACK1`/`#TRACK8`

(Tabsep) The left and right laser respectively. In v10 and v12 most rows carry 9 fields (C0-C8) and C9 is omitted; **in v13 every row carries all 10** (C0-C9).

**The columns from C8 on are not the same quantity in every format version.** Format 13 inserted one new column after the curve type and pushed the roll length and cells-per-chain one place right, so the length lives in C8 up to v12 and in C9 from v13. This is a property of the row layout, not of any particular roll type — see the C8/C9/C10 entries below, and read them together rather than one at a time.

+ C0: Timing

+ C1: Node position, far left to far right
    + (v10) Integer, 0 - 127
    + (v12) Decimal, 0 - 1 (6dp)

+ C2: Node type
    + `0`: Continuing a laser
    + `1`: Starting a laser
    + `2`: Ending a laser
    + Two points on the same tick are a **slam**: a step discontinuity in the knob curve, not an event of its own. See [`audio_engine.md`](audio_engine.md) §5.1 and [`notes.md`](notes.md).

+ C3: Roll/swing type. Lengths below are in 1/4th notes and refer to the time the roll takes to *completely* finish, including overshoots — unlike KSM roll lengths, where the overshoot occurs after the specified length.
    + `0`: No roll
    + `1`: 6-beat roll
    + `2`: 2-beat roll
    + `3`: 3-beat roll
    + `4`: 12-beat triple roll
    + `5`: 3-beat swing
    + `6`: (v12) 8x-speed roll (length from C8, or C9 in v13)
    + `7`: (v12) undocumented in the inherited notes but real: 49 rows across the corpus. Behaves like type `6`, with the same C8/C9 length mechanism.
    + The durations given for types `1`, `2`, `3` and `5` are confirmed against the reference conversions: each reproduces its stated length at medians of 6.00, 2.00, 3.00 and 3.00 quarter notes, holding a ratio of exactly 6:3:3 between types `1`, `3` and `5` within a single chart. Type `4`'s 12 beats is a name only — one reference sample, 25 rows corpus-wide.
    + Because this column covers the overshoot and KSM's does not, a `.ksh` spin token's length is half the duration declared here: `24 * beats`, in ksh 192nds. See [`camera.md`](camera.md).

+ C4: Laser effect, applied until the timing of the next node
    + `0`: Peak filter, default side low, opposite side high
    + `1`-`5`: Index of effect in `#TAB EFFECT INFO` (1-indexed)
    + `6`: No filter of its own, but **not inert** — a C4 = 6 laser is the control source for the `#TAB PARAM ASSIGN INFO` sweep on whichever FX effect a `#TRACK AUTO TAB` span is running.
    + Confirmed at the dispatcher, which keys its effect map on `noteField[4] - 1`, so C4 `1..5` becomes map key `0..4` = the five `#TAB EFFECT INFO` slots, and C4 `0` lands on a "nothing" sentinel.
    + **`0` is not an entry in `#TAB EFFECT INFO` and is not produced by the effect engine at all.** It is a DirectSound parametric EQ living in the *sound device*, driven from the gameplay event dispatcher, lagging the knob by 80 ms and ducking the music while it runs. It is also the overwhelmingly common case (870 of 894 laser nodes on one measured chart). Full transcription in [`audio_engine.md`](audio_engine.md) §7.1.
    + **Do not confuse this column with C7.** Both range 0–5 in practice, so mixing them up looks plausible and silently applies the wrong filters across an entire chart. C4 is the effect; C7 is the curve shape.

+ C5: Laser range — `1`: normal, `2`: wide

+ C6: Unused (always `0`, no known counterexamples)

+ C7: (v12) Curve type
    + `0`: No curve (linear)
    + `1`: Unknown (no known examples)
    + `2`: Cubic Hermite spline. This curve type is missing information — the first derivatives at the control nodes can probably be set in the in-house editor but are not in the VOX file.
    + `3`: Interpolated linear (for sharp corners)
    + `4`: Sine ease out (start fast, end slow)
    + `5`: Sine ease in (start slow, end fast)
    + This does not always reliably indicate the presence/absence of smooth lasers — e.g. in 緋色月下、狂咲ノ絶 (nayuta 2017 ver) MXM some smooth lasers have curve type `0`.

+ C8:
    + **(v10/v12) Roll/swing length**, in 1/4th notes; `0` means "use the type's default length". This is the only length source those versions have. `C8=0` occurs legitimately for types 1/2/3/5, and for types 6/7 it is effectively always a real explicit length (the only two corpus counterexamples turned out to be misfiled v13 charts). In v10, C8 and C9 are usually *absent* rather than present-and-zero.
    + **(v13) Not the length — a different field entirely, meaning unknown.** It takes only the values `0`, `1` and `2` (5806 and 3707 nonzero rows out of 93,574), across 106 of the 148 format-13 charts, all three node types, all curve types, both laser widths, and with no BPM relationship. Unlike a length it appears freely on rows carrying no roll at all (9489 of 93,086), and unlike cells-per-chain it never exceeds 2. This is the column an earlier pass here mistook for a still-mostly-empty length column.
    + The v13 length is C9. Do not read a v13 `C8=0` as "use the type's default": the default applies when the *length column* is 0, which in v13 means C9.

+ C9:
    + **(v10/v12) (Optional) Cells per chain** — the number of cells per chain contributed by a laser segment. If unspecified, defaults to 12 for BPMs $< 255$ and 24 for BPMs $\geq 255$. Rare, and isolated to three charters (`i_kuroma`/`madeinlove_kuroma` in v10, `littleredridinghood_roughsketch` in v12), holding small values (1-12) consistent with the chain meaning and unrelated to roll length.
    + **(v13) Roll/swing length**, for *every* roll type — the same quantity in the same unit as v10/v12's C8, one column to the right. The ksh conversion is unchanged: `24 * C9` for types 1-5 (C9 in quarter notes), `3 * C9` for types 6/7 (C9 in 1/32 notes). In v13 this is the last column any row carries.
    + A v13 row can carry both C8 and C9 (23 rows corpus-wide, across types 1, 5 and 6). C8 is `1` or `2` on every one of them; C9 is the length. See [`camera.md`](camera.md).

+ C10: (v13) Cells per chain, shifted right along with the length. **No corpus row carries it** — and a row that did would be discarded whole, because the parser's accepted-conversion check (below) rejects a ten-data-column row.

#### How the version shift was settled

Not by inference from the values — by reading the game's own row parser, `FUN_18023baa0` in `modules/soundvoltex.dll` (the current chart reader; `FUN_180239810` and `FUN_1802380f0` are earlier generations, for older formats). Its laser-row loop at `0x18023d470` picks one of three format strings by version and scans the row into one fixed record at `rbp+0x330`:

| version gate | conversions | position column |
| --- | --- | --- |
| `< 12` | 12 | int 0-127, rescaled by `* 0.007874016` (= 1/127) |
| `== 12` | 12 | float 0-1 |
| `>= 13` | 13 | float 0-1 |

The record slots each branch fills, in column order (data columns, so column 1 is C1):

| data column | 1 (pos) | 2 | 3 | 4 | 5 | 6 | 7 | 8 | 9 | 10 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| v10/v12 fills | `+0x18` | `+0x1c` | `+0x20` | `+0x24` | `+0x28` | `+0x2c` | `+0x30` | `+0x38` | `+0x3c` | — |
| v13 fills | `+0x18` | `+0x1c` | `+0x20` | `+0x24` | `+0x28` | `+0x2c` | `+0x30` | `+0x34` | `+0x38` | `+0x3c` |

`+0x38` is the roll length — v10/v12 feed it from C8, and that column is validated as the length against 1354 hand-chart samples (see [`camera.md`](camera.md), "Spin/swing: length") — and v13 feeds the same field from C9. `+0x34` is written *only* by the v13 branch, which is why that new column has no older meaning to inherit. Two things make this decisive: the shift lives in the row reader, which has not looked at C3 yet, so **it cannot be per-roll-type**; and both branches scan into one compile-time record, so a column's meaning is exactly the slot it lands in.

The corpus agrees, by a test that needs no binary at all. A length can only mean something on a row that *has* a roll, while cells-per-chain is a property of the laser segment and appears regardless — so ask which column is dead on non-roll rows (`python scripts/camera/survey.py --lasercols`):

| version | C8 nonzero, roll rows | C8 nonzero, non-roll rows | C9 nonzero, roll rows | C9 nonzero, non-roll rows |
| --- | --- | --- | --- | --- |
| v10 | 2 / 12,034 | **0 / 1,145,121** | 17 / 12,034 | 2872 / 1,145,121 |
| v12 | 4700 / 6352 | **0 / 1,716,795** | 8 / 6352 | 1853 / 1,716,795 |
| v13 | 24 / 488 | 9489 / 93,086 | 467 / 488 | **0 / 93,086** |

Unambiguous in both directions, and it flips exactly at v13. Two further cross-checks. Per roll type, v13's C9 reproduces v12's C8 distribution (quartiles `[min, q25, median, q75, max]` — type 1: `[1,1,2,4,46]` mean 3.6 against `[1,2,3,5,21]` mean 4.1; type 6: `[5,12,15,25,135]` mean 17.7 against `[3,12,15,25,35]` mean 18.2; type 7: `[5,7,15,25,32]` mean 15.7 against `[10,12,18,28,45]` mean 20.4). And the row-shape census matches the parser's accepted-conversion check exactly: that check keeps a row whose scan consumed 9, 11 or 12 conversions and drops every other count, i.e. 7, 9 or 10 tab tokens, and the corpus holds only those three shapes (v10 `{7: 1141535, 9: 12731, 10: 2889}`, v12 `{9: 1721286, 10: 1861}`, v13 `{10: 93574}`). An 8-token row would be dropped; none exists.

What this does *not* settle is the v13 length's **unit**. No format-13 chart has hand-chart coverage in `scripts/shared/reference/ksh` (they are all recent update-folder songs), so the quarter-note reading carries over from v10/v12 on the strength of being the same record field with the same value distribution, not from an independent measurement.

### `#TRACK2`/`#TRACK7`

(Tabsep) FX-L and FX-R respectively.

+ C0: Timing
+ C1: Note length in cells; `0` for chip notes.
+ C2:
    + For **chip** notes, the sample to play, from `data/sound/ver5/general_sampler.s3p` (bank 9; `sys_sd_shotfx.2dx` is bank 4 and carries the same 15 names). Both `0` and `255` mean no sample — the trigger reads `if (0 < idx && idx != 255)` — and `0` is overwhelmingly the common value (110 of 111 FX-L chips on one measured chart).
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
        + `14`: Fireworks
        + These 15 are all of them, and the names match the bank's own `.def` entries (`fs00_virtical_se01` … `fs14_shot13`). Each sample's playback level is authored in its own file header as an 8.8 fixed-point dB field, not in game code — the chips sit 7.83 dB below the laser-slam sample. See [`audio_engine.md`](audio_engine.md) §6.1.
    + For **hold** notes, the index of an effect defined in `#FXBUTTON EFFECT INFO`. This is **2-indexed** (`2` is the first effect), confirmed at the dispatcher, which computes `noteField[4] - 2`. `0` and `1` are unused (no known examples).
+ C3: (v12?) (Optional) Cells per chain contributed by a hold note. If unspecified, defaults to 12 for BPMs $< 255$ and 24 for BPMs $\geq 255$.

### `#TRACK3`/`#TRACK4`/`#TRACK5`/`#TRACK6`

(Tabsep) BT-A, BT-B, BT-C and BT-D respectively.

+ C0: Timing
+ C1: Note length in cells; `0` for chip notes.
+ C2: Purpose unknown. Set to non-zero values, usually `2`, for hold notes, but does not appear to apply sound effects.
+ C3: (v12?) (Optional) Cells per chain, as for `#TRACK2`/`#TRACK7`.

### `#TRACK AUTO TAB`

(Tabsep) Applies FX hold effects to lasers. Used by **2738 of 8107 charts (33.8 %)**.

+ C0: Timing
+ C1: Effect length in cells
+ C2: Index of an effect defined in `#FXBUTTON EFFECT INFO`, **2-indexed** (`2` is the first effect); `0` and `1` are unused. Two corpus checks over the 2128 AUTO TAB rows in charts that also carry modulation confirm the base:
    + **Range**: C2 spans `2..13` — twelve consecutive values matching the twelve pairs under `C2 - 2`. A 0-indexed reading would leave `12` and `13` pointing past the last pair.
    + **Correlation**: read as 2-indexed, a span lands on a pair carrying a modulation entry 40.7 % of the time; read as 0-indexed, 13.1 %, which is roughly chance.
    + A `254` also appears (5 rows), which looks like the same "none" sentinel as the FX chip column's `255`, plus one stray `0`.
+ This track picks *which* effect pair a laser span runs; `#TAB PARAM ASSIGN INFO` optionally says *which parameter of that pair the laser sweeps, and between what bounds*.

### (v12) `#TRACK ORIGINAL L`/`#TRACK ORIGINAL R`

(Tabsep) Same fields as `#TRACK1`/`#TRACK8`, but holding only the *control* nodes of curved lasers rather than the interpolated ones. Present in **2488 charts (30.7 %)**.

Safe to ignore for playback: `#TRACK1`/`#TRACK8` already carry the fully-interpolated curve the game plays, so anything reproducing gameplay wants those. The natural reading is that these are the in-house editor's authoring data, kept so a curve can be reloaded and re-edited from its original control points — an argument from redundancy rather than a positive trace of the game ignoring them.

### `#SPCONTROLER`

(Tabsep) Controls the appearance of the game in various ways — camera movement, backgrounds, Live2Ds. Entries often appear out of order with respect to timing.

+ C0: Timing
+ C1: Control type
    + `Realize`
        + Controls how the camera approaches different positions.
        + C2 = 3 controls `CAM_Radi`, C2 = 4 controls `CAM_RotX`; C3, C4, C5 appear to be "overshoot", "start" and "end".
        + The payload is **near-constant but not fixed**: all 8103 v10/v12 charts and 143 of 148 sampled v13 files carry byte-identical values, but 5 v13 files use one of three different payloads, varying the `CAM_Radi` overshoot/end values (`17.12`/`85.06`/`135.12` instead of the usual `36.12`/`110.12`).
    + `AIRL_ScaX`/`AIRR_ScaX` — purpose unknown.
    + `CAM_RotX`
        + Rotates the lane around the judgement line; roughly KSM's `zoom_top`. Entries of this type span the whole chart combined.
        + C3: length of movement in cells
        + C4/C5: start/end positions, decimal -1.00 - 1.00 (2dp). Higher = lane top higher on screen.
        + C2/C6/C7 appear unused.
    + `CAM_Radi`
        + Zooms in and out of the judgement line; roughly KSM's `zoom_bottom`. Entries of this type span the whole chart combined.
        + C3: length of movement in cells
        + C4/C5: start/end positions, decimal -1.00 - 1.00 (2dp). Higher = more zoomed out.
        + C2/C6/C7 appear unused.
    + `BIL_RotZ` — rotates the lane and judgement line around the camera (or vice versa). Only present in April Fools charts.
    + `Tilt`
        + Manual lane tilt. Used by 9 % of v10/v12 charts (758/8103) and **36 % of v13 charts** (53/148 sampled).
        + C3: length of movement in cells
        + C4/C5: start/end positions, decimal -1.00 - 1.00 (2dp). Positive = tilt left (like moving red laser), negative = tilt right.
        + C6: node type — `0.00` during a series of manual tilts, `1.00` single, `2.00` begins a series, `3.00` ends a series.
        + C2/C7 appear unused.
    + `LaneY` — position of the lane on the y-axis; one way to hide the lane. Note the y-axis is parallel to the lane here, whereas it is vertically perpendicular to the lane in scripts.
    + `HudY` — appears to hide the HUD, but only in KAC mode.
    + `BAROFF` — hides bar lines (e.g. Shockwave Syndrome). C4: `ON`/`OFF`.
    + `BAR` — manually adds a bar line at the specified time. Not known whether this works when `BAROFF` is not active.
    + `Morphing2`
        + Lane split (such as in 666 MXM).
        + C3: length of movement in cells
        + C4/C5: start/end positions, decimal (1dp or 2dp) — `0.0` default (no split), `0.8` just over 1 lane wide (666 MXM), `-2.82` pairs of button lanes swapped (EXCEED April Fools MXM).
        + In VW, `Morphing0`/`Morphing1` bent the lane MUSECA-style and `Morphing3` split all four lanes; these no longer work in EG.
    + `ManualSpeed` — scroll speed multiplier independent of BPM, similar to mania SV (e.g. APOCALYPSE RAY).
    + `SpecialN` — controls a lot of things. C4 determines the type:
        + `EXBG` — switching of non-Live2D background images.
        + `LANECLEARCOL` — colour and opacity of the lane area shading that appears when the lane texture is hidden by `LaneY`. C5: ARGB colour `xAARRGGBB` in hexadecimal; `x80202020` is probably the default.
        + `EXBGROTF` (April Fools only) — likely changes how the background image rotates with the lane.
        + `ADJRVZ` (April Fools only)
        + `SE` (April Fools only) — triggers a sound effect. C5: name of the sample.
        + `EXBGTEX` (April Fools only) — likely additional overlaid background images, such as the messages in EXCEED April Fools MXM.
        + `LIVE2D` — animation of Live2D backgrounds. C5: Live2D motion names (although not exactly?).
        + `SIDE` (666 only), `NEMSYS` / `SIDEBG` (XHRONOXAPSULE only), `FRAME` (SuddeNDeath and Akasha only), `SE2` (SuddeNDeath only), `EXMC_LABEL` (APOCALYPSE RAY and HeaveN's Rain only), `EXMC_PARAM` (APOCALYPSE RAY only), `RENDER_PRESET` / `LANECOL` (Akasha only).

Row shape is 8 fields for every control type, unchanged in v13.

### (v13) `#LOCKED_SPCONTROLER`

(Tabsep) New in v13; seen in 4 of 148 sampled files. Same row shape as `#SPCONTROLER`. Every example carries `SpecialN` rows with an `EXMC_LABEL` sub-type, e.g. `001,01,00\tSpecialN\t0\t0\tEXMC_LABEL\tx00010000\ti0\t0`.

### `#POSTEFFECT`

(Optional) (Tabsep) Controls post-processing effects.

+ C0: Timing
+ C1: Unknown (always 2?)
+ C2: Effect length, in cells or in milliseconds with suffix `ms`
+ C3: Effect name — `ChromaticAbberation`, `CrtMonitorEffect`, `SimpleNoise`, `RadicalBlur`, `ColorConversion`, `SetFrameLabel`, `LuminousEffect`, `RandomShake`. So far only used on recent 20s and their lower difficulties.
+ C4: Unknown (always 0 or 1?)
+ C5: Unknown (always 0?)
+ C6: Parameter name, varying by effect
+ C7: Start value, a float with suffix `f`
+ C8: End value, a float with suffix `f`

## `#SCRIPT_DEFINE`

(Optional) Scripts that can be applied to notes and lasers.

```
@SCRIPTSTART n
<variable> = <expression> [when <expression> <comparison> <expression>]
// more lines...
@SCRIPTEND
```

+ **All tokens must be space-separated.**
+ Numeric values: integers (`48000`) and floats (`0.178`, `0.355f`), the latter limited to 3 decimal places.
+ Operators: arithmetic `+`, `-`, `*`, `/`; comparison `==`, `!=`, `>`, `<`, `>=`, `<=`. No logical operators.
+ Variables — these change only the visible position of a note, not its judgement timing, and no others can be defined:
    + `$targetStep`: timing of the note in cells since the start.
    + `$offsetX`: note position offset in X. Positive is right; a lane is about `0.1775` units wide.
    + `$offsetY`: note position offset in Y. Positive is up.
+ Constants: `$currentStep`, the current timing in cells since the start.
+ Expressions may consist of numeric values, arithmetic operators, variables/constants and parentheses.
+ An assignment is successful if the `when` clause is satisfied or absent.
+ Lines are evaluated top to bottom, and **upon the first successful assignment the script finishes** — so each script performs at most one assignment and reads as a chained if-else.

## `#SCRIPTED_TRACK1` ~ `#SCRIPTED_TRACK8`

(Optional) Applies scripts from `#SCRIPT_DEFINE` to the contents of the corresponding one of `#TRACK1` ~ `#TRACK8`.

+ C0: Timing
+ Followed by a space-separated list of script IDs, applied left to right to anything with a matching timing in the corresponding track.
    + Applying a script to the start timing appears to be sufficient for a hold or laser.
    + An assignment is visible to later scripts within a single run of script processing — from EXCEED April Fools MXM's comments: "複数のスクリプトが同じ変数を書き換える場合左のスクリプトから順に処理され、結果が重ね合わされる。" Assignments in one run are not visible in the next.

## Open questions

Things this document does not settle. Everything above is what the format does; this is what is still guessed at.

+ **Roll/swing lengths for types `4` and `7`.** Type `4`'s stated 12 beats is contradicted by the only reference sample carrying it, and type `7` has no reference coverage at all — its length behaviour is assumed identical to type `6`'s. Neither is confirmed against the renderer. See [`camera.md`](camera.md), "Spin/swing: length".
+ **The v13-only C8 column.** Measured as a 0/1/2 per-point flag with no roll, node-type, curve, width or BPM correlation. Which record field it lands in is known (`+0x34`); what reads that field is not. Finding its consumer needs the gameplay/graphics code, which is outside this project's decompiled dumps.
+ **The v13 length's unit** — inherited from v10/v12 rather than measured, for want of any format-13 hand chart to measure against.
+ **Laser curve type `1`** — no known examples in any chart.
+ **BT tracks' C2** — non-zero (usually `2`) on holds, with no observed effect.
+ **`#BPM OPTION`'s two fields.** `ConstantScroll` plausibly means "use a constant visual scroll speed regardless of BPM changes", analogous to ksh's `scroll_speed`; `RepresentativeBpm` plausibly matches ksh's `to` or VOX's own default-BPM concept. Neither is confirmed against the renderer.
+ **`#LOCKED_SPCONTROLER`'s purpose** — parses like `#SPCONTROLER`, but why a separate locked section exists is unknown.
+ **`#REVERB EFFECT PARAM`** — empty in every chart.
+ **`AIRL_ScaX`/`AIRR_ScaX`**, and whether `BAR` works without `BAROFF`.
+ **Echo's 7th field (id 8).** Described as a grid alignment / update period, but the Echo wrapper demonstrably does not call the grid snap, so that reading is at best imprecise. It is `0.00` on every row of every chart examined.
+ **Composite effect id 13.** Stores `{tick, value}` keyframes and interpolates between them, dispatched like any other effect kind; what the interpolated value modulates was never reached. `p2 ∈ [-24,24]` reads plausibly as semitones, making an animated pitch bend the leading guess. See [`audio_engine.md`](audio_engine.md) §8.
