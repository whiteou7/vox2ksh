# VOX format documentation

Taken from m0seng so credit to them

## Notes

These docs are based on zacharied's VOX format notes, which have been an invaluable resource in learning about the format.

However, these docs will focus on the newer VOX versions v10 and v12, which combined make up virtually all charts found in EG (older charts appear to have been ported to v10).

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

TODO: actually verify these are accurate?

TODO: investigate parameters of each effect

+ C0: Effect type
    + `0`: No effect
    + `1`: Retrigger
    + `2`: Gate
    + `3`: Phaser
    + `4`: Tape stop
    + `5`: Sidechain
    + `6`: Wobble
    + `7`: Bitcrusher
    + `8`: Echo (?)
    + `9`: Pitchshift
    + `10`: Highpass
    + `11`: Lowpass
    + `12`: Flanger

+ The number of columns in each line depends on the number of parameters that the effect has, which varies between effect types.

### `#TAB PARAM ASSIGN INFO`

(Commasep) This section allows lasers to use the effects defined in `#FXBUTTON EFFECT INFO`, when enabled in `#TRACK AUTO TAB`.

+ C0: index of effect pair in `#FXBUTTON EFFECT INFO` (0-indexed) (?)
    + This column starts at 0 and increments every other line.
    + Most likely, each line of `#TAB PARAM ASSIGN INFO` maps to the same (non-empty) line of `#FXBUTTON EFFECT INFO`.

+ C1: index of respective effect's parameter to be adjusted
    + `0`: no parameter to be adjusted
    + Otherwise, 0-indexed with respect to column (1-indexed w.r.t. parameter).

+ C2/C3: lower/upper bounds of parameter
    + The laser's position is used as the interpolated value between the bounds.
    + TODO: Does this range from left to right, or from default side to opposite side?

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

+ C4: Laser effect
    + The effect is applied until the timing of the next node.
    + `0`: Peak filter
        + Default side low, opposite side high
    + `1`-`5`: Index of effect in `#TAB EFFECT INFO` (1-indexed)
        + Low/high sides depend on filter type
    + `6`: No effect (?)

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

+ C9: (v12?) (Optional) Cells per chain
    + Denotes the number of cells per chain contributed by a laser segment.
    + If unspecified, this defaults to 12 for BPMs $< 255$, and 24 for BPMs $\geq 255$.

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
        + What other samples there are and where they are defined are not yet known.
    + For hold notes this is the index of an effect defined in `#FXBUTTON EFFECT INFO`.
        + This is **2-indexed**! (i.e.: `2` is the first effect)
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

+ C0: Timing
+ C1: Effect length in cells
+ C2: Effect index
    + This is the index of an effect defined in `#FXBUTTON EFFECT INFO`.
    + This is **2-indexed**! (i.e.: `2` is the first effect)
    + `0` and `1` seem to be unused.

### (v12) `#TRACK ORIGINAL L`/`#TRACK ORIGINAL R`

(Tabsep) These tracks have the same set of fields as `#TRACK1` and `#TRACK8`. However, while `#TRACK1` and `#TRACK8` contain the interpolated nodes of curved lasers, `#TRACK ORIGINAL L` and `#TRACK ORIGINAL R` do not; these tracks only contain the control nodes.

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
