# Camera: tilt, spin and zoom

Code: [`../scripts/camera/`](../scripts/camera/). Spin (kind, direction, length) is solved. Zoom is approximate. Pretilt removal exists but is conservative and off by default.

Scope: lane tilt, spin/swing and top/bottom zoom. Out of scope: `zoom_side`, `center_split`, `rotation_deg`, `scroll_speed` and the `*_curve` options (KSM v2 only). No reference chart uses `zoom_side`.

Approach: use the reference conversions and domain knowledge first, and the DLL only when they can't answer. The DLL was read for two things: the laser row parser (which column holds the roll length) and `Game::AngleUpdater` (the spin). Everything else here is reference-derived.

Camera is a mapping problem more than a transcription problem. The references are hand-made, so values like zoom scale are subjective and vary by charter. `camera_events.py` uses documented approximations and says where it guesses.

## Tools

| file | what it does |
|---|---|
| `scripts/camera/survey_camera.py` | Tallies `#SPCONTROLER` types, `Tilt`/`CAM_RotX`/`CAM_Radi` ranges and roll/swing x length distributions per format version. `--locate <types>` finds occurrences, `--lasercols` prints the length columns. Format-13 charts need `--root <update folder>/data/music` |
| `scripts/camera/correlate_camera.py` | Matches each reference pair to its `.vox` and correlates camera data by tick: zoom and tilt regressions, spin kind/direction tables, and `spin_length_report` |
| `scripts/camera/camera_events.py` | `compute_tilt_events`, `compute_zoom_events`, `compute_spin_tokens`, each over a `VoxChart` |
| `scripts/camera/convert_camera.py` | `python convert_camera.py <chart.vox> [-o out.ksh] [--pretilt-fix]`, a wrapper over `notes/convert_notes.py`'s `convert(..., camera=True)` |

`shared/vox_parser.py` parses three control types into `VoxChart.camera`: `tilt`, `cam_rotx`, `cam_radi` (each a list of `CameraSeg`: `tick`, `length`, `start`, `end`, `node_type`). `Realize`, `SpecialN`, `Morphing2`, `LaneY` and the rest are left raw.

## `#SPCONTROLER` rows

```
C0=timing  C1=control-type  C2=2  C3=length(cells)  C4=start  C5=end  C6=node-type(Tilt only)  C7=0
```

`Tilt` node types: 0 mid-series (9267), 1 single (657), 2 series start (1050), 3 series end (1049).

## Corpus facts (8103 charts)

* Formats: 5660 v10, 2443 v12.
* 82% carry `CAM_RotX`/`CAM_Radi`. Only 9% carry manual `Tilt` (36% of a 148-chart v13 sample). The rest of a chart's tilt is the engine's auto-tilt.
* 81% have at least one roll/swing.
* `Tilt` is in [-1, 1]. `CAM_RotX` reaches 3.9; `CAM_Radi` spans -1.5 to 3.0.
* `roll_type` 7 exists (67 rows, v12+) and `vox_format.md` lists only 0 to 6. Counts over 8251 charts: type 1 8483, 3 4642, 2 3262, 5 2129, 6 264, 7 67, 4 27.
* `roll_type=6` has 64 reference samples in 27 songs. Type 7 has none, so it comes from the DLL.

## Reference charts are hand-made

* `zoom_top` slopes cluster around 135 to 160 (140.00 recurs in 5 songs, R² >= 0.999). `zoom_bottom` clusters around -117 to -136.
* `Realize` payloads are identical across the matched v10/v12 charts, but 5 of 148 v13 charts differ. Not tested as a zoom-scale cause.
* Tilt style varies by song: 5 songs use no manual tilt, others up to 7.37 events per laser run (`furiko_doll/mxm`).

## Zoom

* `CAM_RotX` correlates positively with `zoom_top`. `CAM_Radi` correlates negatively with `zoom_bottom`, so it is negated.
* `ROTX_TO_ZOOM_TOP = 140.0`, `RADI_TO_ZOOM_BOTTOM = -125.0`, as central values.
* Both endpoints of every segment are emitted, deduplicated where consecutive segments hand off the same value, and spaced apart where a same-tick snap needs two values.

## Tilt

`compute_tilt_events` emits `tilt=normal` as the baseline and passes manual `Tilt` segments through as floats at each segment's start and end. The auto-tilt formula (`#TILT MODE INFO`) is not modelled; ksh's own auto-tilt stands in.

Sign: the formats measure tilt in opposite directions. Vox `+1.0` is ksh `-1`. Of 4252 non-trivial matched samples, 98.9% have opposite signs, and pooled regression gives `ksh = -1.5681 * vox` (R² 0.911, n=6520).

Magnitude: the unit reading is 1.0, but per-song modal `ksh/vox` ratios cluster at -1.5 (56 songs), -2.0 (16), -2.4 to -2.5 (9), beyond (3), -1.0 (1), about 0 (4). `TILT_VOX_TO_KSH = -1.5` in `camera_events.py` (the authority). `#TILT MODE INFO` is ruled out as the cause. Open: whether KSM's tilt unit is about two-thirds of SDVX's or charters exaggerate.

## Pretilt

KSM tilts a lane early toward the first point of a laser section that's still two beats away. From KSM v2's `HighwayTiltAuto.cpp`: per frame and per laser lane, take the laser value under the crit line; if the lane has no active section, take the first point of any section starting within `kResolution4 / 2` = 480 pulses = 2 quarter notes. Then add `v` (left lane) or `-(1 - v)` (right).

* Magnitude depends on how far the first point is from the lane's home edge: left laser opening at the left edge gives 0.0, centre 0.5, right edge 1.0. Mirrored for the right lane.
* The trigger is per lane. An idle lane pretilts even while the other lane has a laser.
* The lead is in beats but the tilt moves in real time, so a slow song completes the pretilt and a fast one barely starts. Return to flat is 5x slower than the swing away.
* `tilt=zero` fades the auto path out over about 250 ms. `tilt=0` is a manual graph that takes over in 40 ms with no smoothing.

It's worst when a section opens with a slam after an idle lane, the opening is off the home edge, and the BPM is low.

This corrects an earlier claim that pretilt fires on any laser and so can't be cancelled from chart data. The trigger is exactly computable.

### What the reference charters do

Over 1238 reference conversions, throwaway analysis with no script in the repo:

* They flatten the run-up, then restore tilt exactly on the laser's first point. 87.9% of 8067 `zero`/`0` to auto restorations land on a laser section start, against 13.6% for the same events shifted one beat (6.5x enrichment).
* The flat region has a median of 3 beats (modes 3.0, 2.0, 1.0, 4.0). The flattening end sits on a previous laser's edge: 15.2% on a laser start, 42.3% within a quarter beat of a laser end.
* `tilt=zero` is used in 807 charts, `tilt=0` in 486, manual floats in 407, `keep_*` in 38. 5 charts drive tilt entirely from manual floats, which suppresses auto-tilt.
* Of 64577 section starts after an idle lane, 25.6% are flattened. Centre-opening slams get it 49.5% of the time, home-edge openings with no slam 12.8%. Run-up note density raises it from 12.4% to 30.0%.
* Example: `yukibare_parade/mxm.ksh` measures 15 to 16.

### What the converter emits (`pretilt_fix`, off by default)

`_pretilt_brackets` emits a `tilt=zero` ... `tilt=normal` pair for each laser section that:

* has its lane idle for `PRETILT_WINDOW_BEATS = 2.0`;
* opens at least `PRETILT_MIN_FACTOR = 0.25` from the home edge;
* has the window clear of lasers on both lanes. ksh's tilt is global and KSM's look-ahead is per lane, so cancelling while the other lane holds a laser would flatten tilt the arcade really had. This is why it fires far less than the charters do.

The bracket closes on the section's first point and opens `PRETILT_WINDOW_BEATS + PRETILT_LEAD_BEATS` earlier. The half-beat lead lets the 250 ms fade finish before the window opens. The opening tick is snapped to a 1/16 note (`PRETILT_SNAP_BEATS`), and clamped so it never opens inside the preceding laser. Brackets overlapping a manual `Tilt` segment are skipped. Lengths are in quarter notes times the chart's `tl.res`; the first version used 192nds and made fifth-of-a-beat brackets on a 480-tick chart.

On 400 random charts, 47.8% get at least one bracket (mean 2.7, max 24) with no invariant violations. With the flag off, output is byte-identical to before.

### Unproven

* Source is KSM v2; the charters used v1.6x. Tilt relaxation and keep semantics changed across 1.20/1.20b/1.21.
* "Cancel KSM pretilt" and "reproduce an untilted SDVX passage" are the same edit.
* USC computes roll reactively with no look-ahead, so brackets just read as untilted there.
* ksh option lines don't take a grid slot. Assigning ticks by line index drops the onset-alignment result from 87.9% to 2.4%.
* The brackets haven't been played in KSM.

## Spin

**Kind:** vox rolls (`roll_type` 1, 2, 3, 4, 6, 7) map to the full spin `@(`/`@)`, and swing (5) to the half spin `@<`/`@>`. Matches 1353/1354. `S<`/`S>` is never used by charters, so it isn't emitted.

**Direction:** the tag sits on the laser point just before a same-tick slam. Direction is the sign of the next position change (`_outgoing_dirsign`). Right-to-left is clockwise (`@(` or `@<`), left-to-right is counterclockwise. 1347/1354 (99.5%).

### From the DLL

The system is `Game::AngleUpdater` (vftables `0x1808c92b0`/`0x1808c92c8`), driven by gameplay event kind 8.

**Type remap.** `FUN_1803b1180` rewrites `roll_type` at `0x1803b1a0c` into an internal kind. Types 2 and 3 swap:

| vox | 1 | 2 | 3 | 4 | 5 | 6 | 7 |
|---|---|---|---|---|---|---|---|
| internal | 1 | 3 | 2 | 4 | 5 | 6 | 7 |

Ghidra shows the case bodies as denormal floats because it types the destination as `float`. They are ints. All DLL constants use the internal number; this document uses vox numbering.

**Duration.** `FUN_18011f320(kind, bpm, length)` returns seconds. Purely musical, no wall-clock term:

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

| vox type | default (length 0) | unit | previously |
|---|---|---|---|
| 1 | 7 beats | 1 beat | 6 |
| 2 | 2 beats | 1 beat | same |
| 3 | 3 beats | 1 beat | same |
| 4 | 12 beats | 1 beat | same |
| 5 | 3 beats | 1 beat | same |
| 6 | 7 (unreachable) | 1/10 beat | 1/8 beat |
| 7 | 3 (unreachable) | 1/10 beat | 1/8 beat |

**Motion.** `CurrentRotationEffect` is built at the event, capturing start, duration and direction `d = +/-1`, and dispatches at `0x1803a4a1e` to one of three lambdas. With progress `u`:

| lambda | types | angle (degrees) |
|---|---|---|
| `FUN_1803a6190` | 1, 2, 3, 6 | `d*840*u` while `u < 3/7`, then `d*52.5*sin(7.6969*(u-3/7))*(4/7-(u-3/7))` |
| `FUN_1803a64d0` | 4 | `d*1440*u` while `u < 3/4`, then `d*120*sin(17.5929*(u-3/4))*(1/4-(u-3/4))` |
| `FUN_1803a6350` | 5, 7 | `d*80*sin(2.1*pi*u)*(1-u)` |

* A normal roll turns once (360 degrees) in the first 3/7, then a damped sine settles over 0.7 of a period.
* Type 4 turns three times, each a quarter of the duration, then settles. The peak coefficient is the same 30 degrees.
* A swing never completes a turn. It peaks near 61 degrees at `u = 0.238`. Type 7 runs this curve, not the roll curve; "type 7 is like type 6" is only half right.

The path was found by scanning for the laser record's field offsets (`+0x1c` tick, `+0x2c` node type, `+0x30` roll type, `+0x38` width, `+0x40` curve type, `+0x48` roll length) and following `roll_type` forward.

### Type 4 in ksh

A spin token only fires when a laser slam is judged on its line (`CamPatternMain::onLaserSlamJudged`). A type-4 row has one slam, so three spin tokens would leave two inert. This looks right in the file and does nothing in game.

Instead the converter emits one spin token plus a manual `tilt=` ramp. KSM applies manual tilt to the highway rotation directly, unclamped (`HighwayTiltManual.cpp`):

```
tick          tilt=0          plus the spin token, on the slam
tick + D      tilt=+/-72      linear ramp across the declared duration
tick + D      tilt=0          same tick: back to level
tick + D + 1  tilt=normal     one cell later: back to auto tilt
```

`D` is the declared duration in quarter notes (C8, or 12 if 0) at the chart's resolution. `+72` is clockwise (`@(`), `-72` anticlockwise (`@)`).

Chosen, not derived:

* `72` comes from testing in the target KSM build; `kTiltRadians` isn't in the files consulted.
* The ramp spans all of `D`, not the `3D/4` the turns occupy.

The type-4 token is the one length not halved: `48 * D` instead of `24 * D`, so it ends where the ramp ends. All 27 type-4 rows in the corpus (including the update folder) match.

The ramp owns its span. `compute_tilt_events` drops any other tilt point strictly inside it (manual passthrough, series-end revert, pretilt bracket) and reports the count on stderr. 1 of 27 hits it: `2392_dementafterlegend_cosmograph_5m` (v13), a `0.0 -> 0.0` manual block. `data/music` has no format-13 charts, so checks need both roots.

| chart | C8 | D | token |
|---|---|---|---|
| `2216_tetoris_hiiragimagnetite_5m` | 3 | 3 beats | `@)144` |
| `0271_vallis_djyoshitaka_4i` | 7 | 7 beats | `@)336` |
| `1751_april2021_grace_5m` | 8 | 8 beats | `@)384` |
| `0704_flower_djyoshitaka_4i` | 0 | 12 beats | `@)576` |
| `2392_dementafterlegend_cosmograph_5m` | 3 | 3 beats | `@(144` |

The lone reference type-4 sample, `tetoris/mxm` with C8=3, is a single `@)120` where the old law predicted 72. That's a charter writing one long spin for three turns.

Type 7 emits a half spin. Its length stays on `3 * C8` rather than the DLL's 1/10-beat unit, for the reason below. Over 8107 charts: 8045 unchanged, 25 change spin and tilt (type 4), 35 change spin token only (type 7).

### The scale question

KSM's spin differs in shape from SDVX's:

* SDVX completes its turn at 3/7 = 0.4286 of the declared duration.
* KSM v2 (`CamPatternSpin.cpp`) completes it at 360/675 = 0.5333 of the ksh length, overshoots to 440/675 and recovers by 1.0. So KSM's length also includes recovery, contradicting the `vox_format.md` C3 note that overshoot comes after.

Three scales disagree: 24 (1354 hand samples), 20.6 (SDVX rotation time) and 38.6 (rotation-rate match against ksm-v2; the charters used v1.6x). Nothing changes: `BEAT_TO_KSH192 = 24` and `TYPE67_UNIT_TO_KSH192 = 3` stay, and `DEFAULT_BEATS` keeps type 1 at 6 rather than 7. The reference scale is a half and the DLL's share is 3/7, so 6 halved and 7 times 3/7 both give 3 beats; changing one would make type 1 wrong. Choosing needs a test chart played in KSM.

### Length law

A ksh spin lasts half the vox-declared duration, in 192nds, except type 4. One quarter note is 48 192nds, so `24 * quarter notes`. `python correlate_camera.py` prints the derivation.

| roll_type | vox length | ksh length |
|---|---|---|
| 1 to 5 | length column in quarter notes, or the default (`DEFAULT_BEATS` = 6, 2, 3, 12, 3) when 0 | `24 * beats` |
| 6, 7 | length column in 1/32 notes | `3 * units` |

Why half: `vox_format.md` says vox lengths include the overshoot, unlike KSM's. The overshoot takes as long as the rotation.

Each charter picks one scale per song, so pooling hides the law. The modal `ksh_len / C8` is exactly 24 in 282 of 390 songs, then 32 (24 songs), 36 (21), 48 (19). Across 1354 samples, 24 matches 64.1% exactly and 32 only 16.5%. An earlier version said 32, fit to a minority-charter subset.

Checks:

* Large lengths land exactly: C8 of 10, 11, 22, 30, 32, 46 give 240, 264, 528, 720, 768, 1104.
* Type 6 matches 61/64, and C8 of 13, 17, 23, 33, 37 give 39, 51, 69, 99, 111, which no charter picks by feel.
* BPM has R² of about 0 against ksh length. In 3/4, 33/54 match 24 exactly and a per-measure 192 matches none. Laser-run length doesn't explain the residual.

Defaults match the names after all: `{1:6, 2:2, 3:3, 4:12, 5:3}` quarter notes. `vox_format.md` was wrong about types 2 and 5. Medians over songs with exact 24-scale rows: 6.00 (rt1, 19 songs), 2.00 (rt2, 6), 3.00 (rt3, 17), 3.00 (rt5, 93). Scale-free ratios within a song: rt3/rt5 = 1.000, rt1/rt5 = 2.000, rt1/rt3 = 2.000.

### Which column holds the length

The length is `C8` up to format 12 and `C9` from 13, for every roll type. An earlier version said this was true only for types 6 and 7, so converted v13 charts dropped every explicit length and used the default (`2393_alive_dadadaizu_5m` measure 115: `C9=15` should be `@)360`, was `@)144`).

The shift is in the row parser, which reads all ten columns before looking at the roll type. Details are in `vox_format.md`.

* The chart reader (`FUN_18023baa0`, laser loop at `0x18023d470`) has three branches (`< 12`, `== 12`, `>= 13`). They differ in whether position is an int or float, and in whether the 8th column goes to a v13-only field (`+0x34`) and pushes length and cells-per-chain one slot along.
* The length field (`+0x38`) is fed from `C8` in v10/v12 and `C9` in v13.
* The never-nonzero-on-non-roll column is `C8` in v10/v12 (0 of 2,861,916 rows) and `C9` in v13 (0 of 93,086). `survey_camera.py --lasercols` prints it.
* v13's `C9` per type matches v12's `C8`, e.g. type 1 `[1,1,2,4,46]` mean 3.6 against `[1,2,3,5,21]` mean 4.1.

The 23 v13 rows with both columns are unambiguous: `C8` is the v13-only flag (0, 1 or 2 across 93,574 rows). `shared/vox_parser.py` resolves this per chart, so `camera_events.py` has no version test.

Inherited rather than measured: the v13 length unit. None of the 148 v13 charts (a 2026 update) has hand-chart coverage. `C9=32` on `2393_alive_dadadaizu_5m` track8 measure 79 gives `@(96`, matching the "around 2 beats" the original source described.

## Bugs found and fixed

1. A zero-length vox segment (`tick == end_tick`, `start != end`) is a real instant jump, like a slam. `compute_zoom_events` and `compute_tilt_events` wrote `events[tick] = value`, so a neighbour sharing the tick overwrote it and the peak became a shallow ramp (`2226_gryphone_etia_5m`: 7 such segments each in `cam_rotx`/`cam_radi`, 2 in `tilt`). Now `_place_track` puts distinct same-tick values one cell apart.
2. Dedup kept only the first point of a same-value run, so the hold before a ramp collapsed into a long diagonal (`2226_gryphone_etia_5m` measures 90 to 93: hold at 1.0 for about 335 cells, then ramp to -1.0). Now both the first and last point of each run survive. Output there: `(17088,'0') (17089,'1') (17424,'1') (17472,'-1') (17760,'-1') (17856,'0') (17857,'normal')`.

`scripts/camera/2226_gryphone_etia_5m.ksh` is not a reference. An earlier version of this document called it hand-charted and cited a 100% match, but its header is placeholder output from a similar converter, so it shared the same bug. The only valid check was against the vox segments directly.

## Status

`convert_camera.py` produces notes plus camera. Smoke-tested on `1734_777_roughsketch_3e` (+2.2% lines), a manual-`Tilt` chart (`0418_werewolf_howls_camellia_4i`, vox `-0.500` gives `tilt=0.5`), type 7 (`0642_sayonara_planet_wars_kuroma_4i`), type 4 (`2216_tetoris_hiiragimagnetite_5m`, `2392_dementafterlegend_cosmograph_5m`) and `2226_gryphone_etia_5m`. With `camera=False` (the default) the output is unchanged, as `notes-refcheck` confirms byte for byte. With `pretilt_fix` off, behaviour is unchanged by that flag.

No authoritative hand-charted reference with heavy camera work exists, so the output is validated against the vox data's own structure only.

Known gap: spin tokens sit on the roll point's exact tick, but `laser_curves.py` decimation may drop that point, leaving the token on a `:` continuation instead of a position character. How often, and whether KSM renders it, is unchecked.

## Open items

1. Auto-tilt formula isn't modelled.
2. The ksh scale for every spin type (24, 20.6 or 38.6) needs a test chart in KSM. v13 length units have no reference coverage.
3. Whether decimation can drop a roll point's grid line.
4. DLL leads: the gameplay-event kinds in `FUN_180407200`; the producer of event kind 8 (to confirm the field order `[4]` BPM, `[5]` direction, `[6]` kind, `[7]` length); and the consumer of the v13-only `+0x34` field, which `FUN_1802409f0` uses to group laser points into runs, with track-dependent values 1 and 2 (`0x180240c15`). `FUN_1803b1180` also turns it into a 0.0/1.0/2.0 scale per laser point.
5. Type-4 ramp: `72` is tested, not derived. A manual `tilt=` suppresses auto laser-tilt for the whole duration, and the linear ramp turns the lane during the settle, where the DLL's rotation is linear only for the first 3/4. Playing it would settle these.
6. Pretilt while the other lane is busy needs the auto-tilt formula reproduced as manual floats.
7. Tilt magnitude: -1.5 follows the charters. Deciding whether KSM's unit is 2/3 of SDVX's needs the DLL's tilt render path or playback.
8. Whether the v2 constants (two-beat window, 4.0 scale fade, 40 ms takeover) match v1.6x.
