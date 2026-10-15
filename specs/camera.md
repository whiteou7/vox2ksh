# Camera: tilt, spin and zoom

Code: [`../scripts/camera/`](../scripts/camera/). Numbers and examples: [`evidence/camera.md`](evidence/camera.md).

Spin (kind, direction and length) is solved. Zoom is approximate. Pretilt removal exists, but it's conservative and off by default. The arcade's lane tilt can be baked into manual ksh tilt (`--simulate-tilt`), also off by default.

Scope: lane tilt, spin and swing, and top/bottom zoom. Not covered: `zoom_side`, `center_split`, `rotation_deg`, `scroll_speed` and the `*_curve` options (KSM v2 only).

The reference conversions are hand-made, so values like zoom scale are subjective and differ between charters. `camera_events.py` approximates and says where it's guessing. The DLL was read for three things: the laser row parser (which column holds the roll length), `Game::AngleUpdater`'s spin, and, in the NABLA build, its lane tilt.

`shared/vox_parser.py` parses four control types into `VoxChart.camera`: `tilt`, `cam_rotx`, `cam_radi` and `bil_rotz`, plus the `#TILT MODE INFO` rows as `tilt_mode`. It reads `#LOCKED_SPCONTROLER` like `#SPCONTROLER` and splits rows on any whitespace, as the game does. `Realize`, `SpecialN`, `Morphing2`, `LaneY` and the rest stay raw.

```
C0=timing  C1=control-type  C2=2 (rarely 1 or 3)  C3=length(cells)  C4=start  C5=end  C6=node-type(Tilt only)  C7=0
```

## Takeaways

* Most charts rely on the engine's auto-tilt. Manual `Tilt` is rare.
* The arcade's lane tilt is fully determined by chart data (lasers, `Tilt`, `#TILT MODE INFO`, `BIL_RotZ`), with no look-ahead, so it can be written out as manual ksh tilt.
* `roll_type` 7 exists, but `vox_format.md` lists only 0 to 6.
* Zoom scale varies by charter, so any fixed constant is an approximation.

## Zoom

* `CAM_RotX` maps positively to `zoom_top`. `CAM_Radi` maps negatively to `zoom_bottom`.
* `ROTX_TO_ZOOM_TOP = 140.0` and `RADI_TO_ZOOM_BOTTOM = -125.0`, picked as central values.
* Both endpoints of every segment are emitted. Duplicates are dropped where consecutive segments hand off the same value, and values are spaced one cell apart where a same-tick snap needs two of them.

## Tilt

By default `compute_tilt_events` emits `tilt=normal` as the baseline and passes manual `Tilt` segments through as floats at each segment's start and end. ksh's own auto-tilt stands in for the arcade's; `--simulate-tilt` (next section) replaces all of this.

The two formats measure tilt in opposite directions: vox `+1.0` is ksh `-1`. The default magnitude is `TILT_VOX_TO_KSH = -1.5` in `camera_events.py`, which follows the reference charters. The game's own factor is -2.375: a vox unit is 23.75 degrees and a KSM manual unit is 10 degrees, so the charters understate manual tilt by about a third. The default keeps -1.5.

## Simulated tilt

`compute_tilt_events(chart, simulate=True)` (`convert_camera.py --simulate-tilt`) replaces `tilt=normal` and the passthrough with manual `tilt=<float>` points for the whole chart, reproducing NABLA's `Game::AngleUpdater`. Every point is manual, so KSM's auto-tilt and pretilt never run, and `pretilt_fix` is ignored. Constants and DLL addresses are in the evidence file.

The model, in real time (the game's rates are wall-clock):

1. Target `r`. While a manual `Tilt` series runs, from its first point to its last, `r` is the series value times -2.375, or times -1 when the tilt mode isn't 0. Otherwise `r` is the sum over the laser sections active at that moment (first point <= t < last point, so no look-ahead) of `x` for the left laser and `x - 1` for the right, where `x` is the 0..1 position, interpolated linearly in time between points.
2. Series. `Tilt` rows are read in time order. Node type 1 is one segment from (start, C4) to (end, C5). Types 0 and 2 open a series that takes (start, C4) from each `Tilt` row, the opener included, up to the next type-3 row, which also adds (end, C5); the other rows' C5 is ignored. Values with magnitude 0.01 or less become 0. A series that starts replaces the running one.
3. Smoothing. `s` moves linearly toward `r` at 3.75/s, doubled while a series runs. When `|r| < 1/127` it moves at 0.9375/s (also doubled during a series) and snaps to 0 once `|s| < 1/127`.
4. `#TILT MODE INFO` filters `d = 10 s` degrees into `o`. Mode 0 passes `d` through. Mode 1 follows `2.375 d` at 90 degrees/s. Mode 2 does the same but takes its direction from the first `|d| > 1/127` after the mode row, then only moves that way, holding its peak; until then it holds. A row switching back to 0 makes `o` follow `d` at 90 degrees/s until within 1/127, then pass through, and the manual factor stays -1 until it does.
5. `BIL_RotZ` adds on top, unsmoothed, in degrees (the `d` prefix). Each row is a linear graph from C4, or from the current value when C2 isn't 2, to C5 over its span, held until the next row. The game reads these rows from `#LOCKED_SPCONTROLER` as well as `#SPCONTROLER`.
6. ksh `tilt = (o + BIL_RotZ) / 10`, rounded to 3 decimals: a KSM manual tilt of 1.0 is 10 degrees, with the same sign as KSM's auto-tilt (ksm-v2 `HighwayTiltManual`, `kTiltRadians`).

The model runs in 1 ms steps, is sampled on a 48-per-beat tick grid through the tempo map, and is reduced to the points of a piecewise-linear graph that stays within `SIM_TOLERANCE = 0.005` of every sample. The rate limits already make the motion piecewise linear, so a chart needs only a few hundred points. A `BIL_RotZ` jump becomes two `tilt=` lines on one tick, ksh's immediate change. Every BPM change gets a point, and the first point after tick 0 carries an immediate change of 0.001, a hundredth of a degree; both are for USC (next section). Points stop once the tilt has settled after the last event, and never run past `#END POSITION`.

Spin and swing tokens are unchanged. A type-4 ramp (0 to ±72 over `D`) is added on top of the simulated tilt and drops back to it on the ramp's last tick, a 720-degree jump that doesn't show.

The default output is unchanged byte for byte.

Unproven:

* That KSM v1.6x also uses 10 degrees per manual unit. The source is ksm-v2.
* Wide lasers use the stored 0..1 position. Whether the game rescales it for 2x lasers isn't checked.
* Curved laser segments (`curve_type`) count as straight, which assumes the game's tilt reads only the points.
* `BIL_RotZ` turns reach ksh tilt ±36, which relies on manual tilt being unclamped. The type-4 ramp relies on the same thing.
* The ksh gets denser: a measure holding tilt points often needs the full 192-line grid.
* Nobody has played the output in KSM.

### In USC

USC reads a float `tilt=` the same way as KSM in scale and sign: one unit is 10 degrees, the same as a full auto tilt at normal intensity. Two lines on one tick are an immediate change, and the last value holds. It differs in two ways, and the simulated output allows for both:

* It interpolates between points in time, where KSM uses ticks, so a segment that spans a BPM change bends differently in the two engines. A point at every BPM change keeps each segment within one tempo, where the two agree.
* It applies manual tilt directly only if the first point after the switch to manual is an immediate change. Otherwise the lane chases the value at 100 degrees/s, speeding up once it's more than 10 degrees behind, which would lag fast `BIL_RotZ` turns and play the 360- and 720-degree drops (the `BIL_RotZ` reset, the type-4 ramp end) as a reverse spin of about 0.2 s. The 0.001 immediate change on the first point after tick 0 turns direct application on for the whole chart.

## Pretilt

KSM tilts a lane early toward the first point of a laser section that's still two beats away. The arcade doesn't, and `--simulate-tilt` avoids the problem entirely. From KSM v2's `HighwayTiltAuto.cpp`: each frame, for each laser lane, take the laser value under the crit line. If the lane has no active section, take the first point of any section starting within `kResolution4 / 2` = 480 pulses = 2 quarter notes. Then add `v` for the left lane or `-(1 - v)` for the right.

* The size of the tilt depends on how far the first point is from the lane's home edge. A left laser opening at the left edge gives 0.0, the centre 0.5 and the right edge 1.0. The right lane mirrors this.
* The trigger is per lane. An idle lane pretilts even while the other lane has a laser.
* The lead time is measured in beats but the tilt moves in real time, so a slow song completes the pretilt and a fast one barely starts it. Returning to flat is 5x slower than swinging away.
* `tilt=zero` fades the auto path out over about 250 ms. `tilt=0` is a manual graph that takes over in 40 ms with no smoothing.

The effect is worst when a section opens with a slam after an idle lane, the opening is off the home edge, and the BPM is low.

An earlier version of this document claimed pretilt fires on any laser and so can't be cancelled from chart data. That was wrong. The trigger is exactly computable.

The reference charters flatten the run-up, then restore tilt exactly on the laser's first point (details in the evidence file). `_pretilt_brackets` does the same with a `tilt=zero` ... `tilt=normal` pair, behind `pretilt_fix`, for each laser section that:

* has its lane idle for `PRETILT_WINDOW_BEATS = 2.0`;
* opens anywhere off the home edge (a left laser above 0, a right laser below 1);
* has the window clear of lasers on both lanes, except a straight laser resting on the other lane's home edge (left at 0, right at 1), which adds no tilt and is ignored. ksh's tilt is global while KSM's look-ahead is per lane, so cancelling while the other lane holds a tilting laser would flatten tilt the arcade really had. That's why this fires far less often than the charters do.

The bracket closes on the section's first point and opens `PRETILT_WINDOW_BEATS + PRETILT_LEAD_BEATS` earlier, so the 250 ms fade finishes before the window opens. The opening tick is snapped to a 1/16 note (`PRETILT_SNAP_BEATS`) and never lands inside the preceding laser. Brackets that overlap a manual `Tilt` segment are skipped. Lengths are quarter notes times the chart's `tl.res`.

Unproven:

* The source is KSM v2, but the charters used v1.6x. Tilt relaxation and keep semantics changed across 1.20, 1.20b and 1.21.
* "Cancel KSM pretilt" and "reproduce an untilted SDVX passage" are the same edit.
* USC looks two beats ahead for an idle lane too, so it pretilts like KSM and the brackets apply there as well.
* Nobody has played the brackets in KSM.

## Spin

**Kind:** rolls (`roll_type` 1, 2, 3, 4, 6, 7) become the full spin `@(`/`@)`, and swing (5) becomes the half spin `@<`/`@>`. This matches the reference charts almost perfectly. Charters never use `S<`/`S>`, so it isn't emitted.

**Direction:** the tag goes on the laser point just before a same-tick slam. Direction is the sign of the next position change (`_outgoing_dirsign`). Right to left is clockwise (`@(` or `@<`) and left to right is counterclockwise. This also matches the references almost perfectly.

### From the DLL

The system is `Game::AngleUpdater` (vftables `0x1808c92b0` and `0x1808c92c8`), driven by gameplay event kind 8.

`FUN_1803b1180` rewrites `roll_type` at `0x1803b1a0c` into an internal kind. Types 2 and 3 swap:

| vox | 1 | 2 | 3 | 4 | 5 | 6 | 7 |
|---|---|---|---|---|---|---|---|
| internal | 1 | 3 | 2 | 4 | 5 | 6 | 7 |

Ghidra shows the case bodies as denormal floats because it types the destination as `float`; they're really ints. Every DLL constant uses the internal number. This document uses vox numbering.

`FUN_18011f320(kind, bpm, length)` returns the duration in seconds. It's purely musical, with no wall-clock term:

```c
if (length == 0) {
  switch (kind) {                        // internal numbering
    case 1: case 6:          return 420.0f / bpm;          //  7 beats
    case 2: case 5: case 7:  return 180.0f / bpm;          //  3 beats
    case 3:                  return 60.0f/bpm + 60.0f/bpm; //  2 beats
    case 4:                  return 720.0f / bpm;          // 12 beats
    default:                 return 0.0f;
  }
}
return ((kind - 6u < 2 ? 6.0f : 60.0f) / bpm) * (float)length;
```

So length 0 means the type's default (7, 2, 3, 12 and 3 beats for types 1 to 5), types 1 to 5 count in beats, and types 6 and 7 count in tenths of a beat.

`CurrentRotationEffect` is built when the event fires and dispatches at `0x1803a4a1e` to one of three motion lambdas (formulas in the evidence file):

* A normal roll (1, 2, 3, 6) turns once, 360 degrees, in the first 3/7 of the duration, then a damped sine settles.
* Type 4 turns three times, each turn taking a quarter of the duration, then settles.
* A swing (5, 7) never completes a turn. Type 7 runs this curve, so "type 7 is like type 6" is only half right: the length column and unit match, but the motion differs.

### Type 4 in ksh

A spin token fires only when a laser slam is judged on its line (`CamPatternMain::onLaserSlamJudged`). A type-4 row has one slam, so three spin tokens would leave two inert. They look right in the file and do nothing in game.

The converter emits one spin token plus a manual `tilt=` ramp instead. KSM applies manual tilt to the highway rotation directly, unclamped (`HighwayTiltManual.cpp`):

```
tick          tilt=0          plus the spin token, on the slam
tick + D      tilt=+/-72      linear ramp across the declared duration
tick + D      tilt=0          same tick: back to level
tick + D + 1  tilt=normal     one cell later: back to auto tilt
```

`D` is the declared duration in quarter notes (C8, or 12 if 0) at the chart's resolution. `+72` is clockwise (`@(`) and `-72` is anticlockwise (`@)`).

Two things here were chosen, not derived:

* `72` comes from testing in the target KSM build. `kTiltRadians` isn't in the files consulted.
* The ramp spans all of `D`, not the `3D/4` the turns actually occupy.

The type-4 token is the one length that isn't halved: `48 * D` instead of `24 * D`, so it ends where the ramp ends. The ramp owns its span, so `compute_tilt_events` drops any other tilt point strictly inside it (manual passthrough, series-end revert, pretilt bracket) and reports the count on stderr. `data/music` has no format-13 charts, so checks need both roots.

Type 7 emits a half spin. Its length stays at `3 * C8` rather than the DLL's tenth-of-a-beat unit, for the reason in the next section.

### The scale question

KSM's spin has a different shape from SDVX's. SDVX completes its turn at 3/7 of the declared duration. KSM v2 (`CamPatternSpin.cpp`) completes it at 360/675 = 0.5333 of the ksh length, then overshoots and recovers by 1.0. So KSM's length includes the recovery, which contradicts the `vox_format.md` C3 note that overshoot comes after.

Three scales disagree: 24 (from the hand-charted samples), 20.6 (SDVX rotation time) and 38.6 (a rotation-rate match against ksm-v2, though the charters used v1.6x). The converter stays on 24: `BEAT_TO_KSH192 = 24`, `TYPE67_UNIT_TO_KSH192 = 3`, and `DEFAULT_BEATS` keeps type 1 at 6 instead of the DLL's 7. The reference scale is a half and the DLL's share is 3/7, so 6 halved and 7 times 3/7 both give 3 beats. Changing only one of them would make type 1 wrong. Settling this takes a test chart played in KSM.

### Length law

A ksh spin lasts half the vox-declared duration, in 192nds, except type 4. One quarter note is 48 192nds, so the rule is `24 * quarter notes`. `python correlate_camera.py` prints the derivation.

| roll_type | vox length | ksh length |
|---|---|---|
| 1 to 5 | length column in quarter notes, or the default (`DEFAULT_BEATS` = 6, 2, 3, 12, 3) when 0 | `24 * beats` |
| 6, 7 | length column in 1/32 notes | `3 * units` |

The reason for the half: `vox_format.md` says vox lengths include the overshoot, unlike KSM's, and the overshoot takes as long as the rotation.

Each charter picks one scale per song, so pooling samples hides the law. 24 is the most common scale in most songs, though it matches only about two thirds of samples exactly. BPM and time signature don't affect the length. The length-0 defaults do match the names in `vox_format.md` after all (`{1:6, 2:2, 3:3, 4:12, 5:3}` quarter notes); `vox_format.md` was wrong about types 2 and 5.

### Which column holds the length

The length is `C8` up to format 12 and `C9` from format 13, for every roll type. An earlier version said this applied only to types 6 and 7, so converted v13 charts dropped every explicit length and fell back to the default.

The shift comes from the game's row parser, which reads all ten columns before it looks at the roll type. Details are in `vox_format.md`. `shared/vox_parser.py` resolves this per chart, so `camera_events.py` has no version test. The v13 length unit is assumed to match v10 and v12, since no v13 chart has hand-chart coverage.

## Bugs found and fixed

1. A zero-length vox segment is an instant jump, like a slam. The zoom and tilt code kept one value per tick, so a neighbour on the same tick overwrote it and the peak became a shallow ramp. `_place_track` now puts distinct same-tick values one cell apart.
2. Dedup kept only the first point of a same-value run, so a hold before a ramp collapsed into a long diagonal. Both the first and last point of each run now survive.
3. Camera rows were split on single tabs, so a row with an empty field before C4 (two tabs) crashed the parser and the whole camera conversion. The game reads rows with `sscanf`, where any run of whitespace separates fields, so the empty field doesn't exist. Rows now split on whitespace. Only the two tutorial charts change: they used to crash.

## Status

`convert_camera.py` produces notes plus camera. No authoritative hand-charted reference with heavy camera work exists, so the output is checked only against the structure of the vox data itself.

Known gap: spin tokens sit on the roll point's exact tick, but `laser_curves.py` decimation may drop that point and leave the token on a `:` continuation instead of a position character. Nobody has checked how often this happens or whether KSM renders it.

## Open items

1. The auto-tilt formula is modelled only behind `--simulate-tilt`, and nobody has played the result in KSM.
2. The ksh scale for every spin type (24, 20.6 or 38.6) needs a test chart in KSM. The v13 length units have no reference coverage.
3. Whether decimation can drop a roll point's grid line.
4. DLL leads: the gameplay-event kinds in `FUN_180407200`; the producer of event kind 8 (to confirm the field order `[4]` BPM, `[5]` direction, `[6]` kind, `[7]` length); and the consumer of the v13-only `+0x34` field, which `FUN_1802409f0` uses to group laser points into runs, with track-dependent values 1 and 2 (`0x180240c15`). `FUN_1803b1180` also turns it into a 0.0/1.0/2.0 scale per laser point.
5. Type-4 ramp: `72` is tested, not derived. A manual `tilt=` suppresses auto laser-tilt for the whole duration, and the linear ramp turns the lane during the settle, where the DLL's rotation is linear only for the first 3/4. Playing it would settle these.
6. Pretilt while the other lane is busy: `--simulate-tilt` has no pretilt at all.
7. Tilt magnitude: the DLL gives -2.375, which `--simulate-tilt` uses. The default keeps the charters' -1.5. Whether KSM v1.6x shares ksm-v2's 10 degrees per unit needs playback.
8. Whether the v2 constants (two-beat window, 4.0 scale fade, 40 ms takeover) match v1.6x.
