# VOX format documentation

## Credits

This document began as **zacharied's** VOX format notes and was substantially rewritten and extended by **m0seng**, whose v10/v12-focused version is what this project inherited.

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
+ Unlike time signatures, BPM changes can occur away from the start of a measure. This is possible, though uncommon, with pauses too (Xevel MXM is the only known example).

### (v13) `#BPM OPTION`

+ `ConstantScroll` — `0` or `1`
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
        + C1: Mix % (2dp
        + C2/C3: Lower/upper bounds of cutoff (2dp)
            + The laser's position is the interpolated value between the bounds.
            + Lowpass: default side high, opposite side low. Highpass: default side low, opposite side high.
        + C4: Filter resonance (2dp)
    + `3`: Bitcrush
        + C1: Mix % (2dp)
        + C2: Sample rate reduction factor (integer)

### `#FXBUTTON EFFECT INFO`

(Commasep) 12 pairs of lines. Each pair corresponds to a pair of effects referenced by FX tracks (`#TRACK2`/`#TRACK7`/`#TRACK AUTO TAB`). Both effects in each pair are applied in series.

+ C0: Effect type.

| id   | actual                       |
| ---- | ---------------------------- |
| `0`  | No effect                    |
| `1`  | Retrigger                    |
| `2`  | Gate                         |
| `3`  | Flange                       |
| `4`  | Tape Stop                    |
| `5`  | Side Chain                   |
| `6`  | Wobble                       |
| `7`  | Bit Crusher                  |
| `8`  | Echo / Retrigger Ex          |
| `9`  | Pitch Shift                  |
| `10` | Tape Stop Ex                 |
| `11` | Low Pass Filter              |
| `12` | High Pass Filter             |
| `13` | composite / keyframed effect |

+ The number of columns per line depends on the effect type. Exact per-type column order:

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

### `#TAB PARAM ASSIGN INFO`

(Commasep) Lets lasers modulate a parameter of the effects defined in `#FXBUTTON EFFECT INFO`, when enabled in `#TRACK AUTO TAB`.

Always exactly 24 rows, one row per `#FXBUTTON EFFECT INFO` line, present whether used or not.

+ C0: index of effect pair in `#FXBUTTON EFFECT INFO` (0-indexed).`0,0,1,1,2,2,…,11,11`.
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

(Tabsep) The left and right laser respectively. In v10 and v12 most rows carry 9 fields (C0-C8) and C9 is omitted; in v13 every row carries all 10 (C0-C9).

**The columns from C8 on are not the same quantity in every format version.** Format 13 inserted one new column after the curve type and pushed the roll length and cells-per-chain one place right, so the length lives in C8 up to v12 and in C9 from v13. 

+ C0: Timing

+ C1: Node position, far left to far right
    + (v10) Integer, 0 - 127
    + (v12) Decimal, 0 - 1 (6dp)

+ C2: Node type
    + `0`: Continuing a laser
    + `1`: Starting a laser
    + `2`: Ending a laser
    + Two points on the same tick create a laser slam

+ C3: Roll/swing type. Lengths below are in 1/4th notes and refer to the time the roll takes to *completely* finish, including overshoots — unlike KSM roll lengths, where the overshoot occurs after the specified length. These values refer to default length if it's not defined in C8/C9.
    + `0`: No roll
    + `1`: 6-beat roll
    + `2`: 2-beat roll
    + `3`: 3-beat roll
    + `4`: 12-beat triple roll
    + `5`: 3-beat swing
    + `6`: (v12) 8x-speed roll (length from C8, or C9 in v13)
    + `7`: (v12) undocumented, behaves like type 6

+ C4: Laser effect, applied until the timing of the next node
    + `0`: Peak filter, default side low, opposite side high
    + `1`-`5`: Index of effect in `#TAB EFFECT INFO` (1-indexed)
    + `6`: No filter of its own, but **not inert** — a C4 = 6 laser is the control source for the `#TAB PARAM ASSIGN INFO` sweep on whichever FX effect a `#TRACK AUTO TAB` span is running.

+ C5: Laser range — `1`: normal, `2`: wide

+ C6: Unused (always `0`, no known counterexamples)

+ C7: (v12) Curve type
    + `0`: No curve (linear)
    + `1`: Unknown (no known examples)
    + `2`: Cubic Hermite spline.
    + `3`: Interpolated linear (for sharp corners)
    + `4`: Sine ease out (start fast, end slow)
    + `5`: Sine ease in (start slow, end fast)
    + This does not always reliably indicate the presence/absence of smooth lasers — e.g. in 緋色月下、狂咲ノ絶 (nayuta 2017 ver) MXM some smooth lasers have curve type `0`.

+ C8:
    + **(v10/v12) Roll/swing length**, in 1/4th notes; `0` means "use the type's default length". This is the only length source those versions have.
    + **(v13)** Unknown purpose

+ C9:
    + **(v10/v12) (Optional) Cells per chain** — the number of cells per chain contributed by a laser segment. If unspecified, defaults to 12 for BPMs $< 255$ and 24 for BPMs $\geq 255$. Rare, and isolated to three charters (`i_kuroma`/`madeinlove_kuroma` in v10, `littleredridinghood_roughsketch` in v12), holding small values (1-12) consistent with the chain meaning and unrelated to roll length.
    + **(v13) Roll/swing length**, shifted from C8 

+ C10: (v13) Cells per chain, shifted from C9 (unverified)

### `#TRACK2`/`#TRACK7`

(Tabsep) FX-L and FX-R respectively.

+ C0: Timing
+ C1: Note length in cells; `0` for chip notes.
+ C2:
    + For **chip** notes, the sample to play. Both `0` and `255` mean no sample.
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
    + For **hold** notes, the index of an effect defined in `#FXBUTTON EFFECT INFO`. This is **2-indexed** (`2` is the first effect)
+ C3: (v12?) (Optional) Cells per chain contributed by a hold note. If unspecified, defaults to 12 for BPMs $< 255$ and 24 for BPMs $\geq 255$.

### `#TRACK3`/`#TRACK4`/`#TRACK5`/`#TRACK6`

(Tabsep) BT-A, BT-B, BT-C and BT-D respectively.

+ C0: Timing
+ C1: Note length in cells; `0` for chip notes.
+ C2: Purpose unknown. Set to non-zero values, usually `2`, for hold notes, but does not appear to apply sound effects.
+ C3: (v12?) (Optional) Cells per chain, as for `#TRACK2`/`#TRACK7`.

### `#TRACK AUTO TAB`

(Tabsep) Applies FX hold effects to lasers.

+ C0: Timing
+ C1: Effect length in cells
+ C2: Index of an effect defined in `#FXBUTTON EFFECT INFO`, **2-indexed** (`2` is the first effect); `0` and `1` are unused.
+ This track picks *which* effect pair a laser span runs; `#TAB PARAM ASSIGN INFO` optionally says *which parameter of that pair the laser sweeps, and between what bounds*.

### (v12) `#TRACK ORIGINAL L`/`#TRACK ORIGINAL R`

(Tabsep) Same fields as `#TRACK1`/`#TRACK8`, but holding only the *control* nodes of curved lasers rather than the interpolated ones.

Safe to ignore for playback.

### `#SPCONTROLER`

(Tabsep) Controls the appearance of the game in various ways — camera movement, backgrounds, Live2Ds. Entries often appear out of order with respect to timing.

+ C0: Timing
+ C1: Control type
    + `Realize`
        + Controls how the camera approaches different positions.
        + C2 = 3 controls `CAM_Radi`, C2 = 4 controls `CAM_RotX`; C3, C4, C5 appear to be "overshoot", "start" and "end".
    + `AIRL_ScaX`/`AIRR_ScaX` — purpose unknown.
    + `CAM_RotX`
        + Rotates the lane around the judgement line; roughly KSM's `zoom_top`. 
        + C3: length of movement in cells
        + C4/C5: start/end positions, decimal -1.00 - 1.00 (2dp). Higher = lane top higher on screen.
        + C2/C6/C7 appear unused.
    + `CAM_Radi`
        + Zooms in and out of the judgement line; roughly KSM's `zoom_bottom`.
        + C3: length of movement in cells
        + C4/C5: start/end positions, decimal -1.00 - 1.00 (2dp). Higher = more zoomed out.
        + C2/C6/C7 appear unused.
    + `BIL_RotZ` — rotates the lane and judgement line around the camera (or vice versa). Only present in April Fools charts.
    + `Tilt`
        + Manual lane tilt.
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

### (v13) `#LOCKED_SPCONTROLER`

Unknown.

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