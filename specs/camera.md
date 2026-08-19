# The camera element

**Status: converter exists (`scripts/camera/convert.py`); spin is solved (kind, direction and length), zoom is on reasonably solid ground.** Scope, tools, and findings below. Nothing here has been checked against the DLL, per direction: settle what the manual reference conversions and direct domain knowledge can tell us first, fall back to the DLL only once that's exhausted.

**Pretilt removal is implemented, off by default** (`camera.py`'s `_pretilt_brackets`, reached by `convert(..., pretilt_fix=True)`, the CLI's `--pretilt-fix` and the GUI's "Remove pretilt" checkbox). "Pretilt" is KSM anticipating an upcoming laser and starting to tilt before the arcade would. This document previously called it out of scope on the grounds that it fires on *any* laser and so expresses no chart-side condition a converter could act on. **Correction: that rationale was wrong.** KSM's anticipation window, trigger and magnitude are all exactly specified and all computable from the chart alone, and the hand-made reference conversions cancel it with a consistent, measurable idiom - which is what the implementation reproduces. See [Pretilt: KSM's two-beat laser anticipation](#pretilt-ksms-two-beat-laser-anticipation).

Scope: lane tilt, spin/swing and top/bottom zoom - the `.vox` tracks that move the playfield rather than the notes on it. Explicitly out of scope for this pass (KSMv2-only, or not expressible pre-v2): `zoom_side`, `center_split`, `rotation_deg`, `scroll_speed`, and the `*_curve` interpolation options. `zoom_side` usage was checked directly: zero occurrences across every file in `scripts/shared/reference/ksh`.

## What makes this element different

Audio and notes were both *transcription* problems: the game does something exact, and the job was to read it out of the binary. Camera turned out to be a mapping problem in a stronger sense than expected - see [Reference charts are hand-made, not derived](#reference-charts-are-hand-made-not-derived). Document the lossy/uncertain parts explicitly; a converter that silently discards or fabricates camera data is worse than one that says what it doesn't know. Per direction, exact accuracy on the zoom scale factor and the spin length formula isn't the bar here - a reasonable, documented approximation is fine; the goal is a converter that does something sensible everywhere and is honest about where it's guessing. (Spin length turned out to be recoverable exactly anyway, once the per-charter scale was controlled for - see "Length" below. Zoom is still an approximation.)

## Tools

| file | what it does |
|---|---|
| [`../scripts/camera/survey.py`](../scripts/camera/survey.py) | Walks every `.vox` chart, tabulates `#SPCONTROLER` control-type inventory, `Tilt`/`CAM_RotX`/`CAM_Radi` value ranges/lengths, and laser roll/swing (C3) x length distributions, keyed on format version because the length column moves in v13. `--locate <types>` pinpoints exact chart/measure occurrences of specific `roll_type` values; `--lasercols` reports the length/cells-per-chain columns per version (see "Which column holds the length"). A base install has no format-13 charts at all, so pass `--root <update folder>/data/music` for any v13 coverage. |
| [`../scripts/camera/correlate.py`](../scripts/camera/correlate.py) | Matches every `scripts/shared/reference/ksh` pair to its `.vox` source and correlates vox camera data against the hand-charted ksh camera lines by tick: regression for zoom, laser-position regression for tilt, and for spin a full tabulation of kind and direction plus a `spin_length_report` that derives the length law from scratch (per-song charter scale, exact-match rates, default lengths, and the scale-free type-ratio cross-check). Every matched pair is v10 or v12, so "the length column" is always `C8` here. |
| [`../scripts/camera/camera.py`](../scripts/camera/camera.py) | The actual conversion logic: `compute_tilt_events`, `compute_zoom_events`, `compute_spin_tokens`, each taking a loaded `VoxChart` and returning tick-tagged events. Pure compute, no file I/O - documented inline, this file is the executable form of this writeup. |
| [`../scripts/camera/convert.py`](../scripts/camera/convert.py) | CLI: `python convert.py <chart.vox> [-o out.ksh] [--pretilt-fix]`. Thin wrapper - calls `../notes/convert.py`'s `convert(vox_path, out_path, camera=True)`, which places `camera.py`'s events into the same grid it builds for notes. `camera=False` (the default, used by `notes/xcheck.py`) is unaffected - verified byte-for-byte via `notes/xcheck.py` before/after this change. |

`shared/vox.py` parses `#SPCONTROLER` (`VoxChart.camera = {"tilt": [...], "cam_rotx": [...], "cam_radi": [...]}`, each a list of `CameraSeg`: `tick`, `length`, `start`, `end`, `node_type`). Only these three control types are parsed; `Realize`, `SpecialN`, `Morphing2`, `LaneY`, etc. are out of scope and left in the raw section dict.

## `#SPCONTROLER` row shape - confirmed

Matches `vox_format.md`'s documented layout exactly, transcribed from raw rows rather than assumed:

```
C0=timing  C1=control-type  C2=2 (const)  C3=length(cells)  C4=start  C5=end  C6=node-type(Tilt only, else 0)  C7=0 (const)
```

`Tilt`'s `C6` node-type: `0` mid-series (9267 corpus-wide), `1` a standalone single tilt (657), `2` begins a series (1050), `3` ends a series (1049).

## Corpus-wide facts (from `survey.py`, all 8103 charts)

- **`#FORMAT VERSION`**: 5660 v10, 2443 v12.
- **6667/8103 charts (82%) carry `CAM_RotX`/`CAM_Radi`** (automatic top/bottom zoom work).
- **Only 758/8103 charts (9%) carry any manual `Tilt` row.** The rest of a chart's `tilt=` output is SDVX's own automatic laser-driven tilt - see below.
- **6549/8103 charts (81%) have at least one laser roll/swing entry.**
- Value ranges: `Tilt` stays exactly within [-1, 1]. `CAM_RotX` reaches up to 3.9, `CAM_Radi` down to -1.5 and up to 3.0 - both exceed a naive ±1 reading.
- **A `roll_type` value 7 exists** on `#TRACK1`/`#TRACK8`, v12 and v13, 67 rows corpus-wide - not documented in `vox_format.md`, which lists only 0-6. **Correction to inherited notes**, in the spirit of `audio_engine.md` §3's effect-id fixes. Its length range (5-32 in v12, 10-45 in v13) overlaps type 6's.
- `roll_type` counts over 8251 charts (the 8103-chart base install plus the 148 format-13 charts of one update folder): type 1 (6-beat) 8483, type 3 (3-beat) 4642, type 2 (2-beat) 3262, type 5 (swing) 2129, type 6 (8x-roll, v12+) 264, type 7 (undocumented, v12+) 67, type 4 (12-beat triple) 27. Format 13 is scarce here - 148 charts, 488 roll rows - and it is scarce *because* v13 only exists in update folders; a base install is entirely v10/v12.

### Locating `roll_type` 6 and 7

**`roll_type=6` is now covered by the reference set** - 64 matched samples across 27 songs, once the corpus grew past the 30 charts this document was originally written against (644 matched pairs now). It is, in fact, the *best*-fit type of all, see "Spin/swing: length" below. **`roll_type=7` still has zero reference coverage**, so its length handling is inherited from type 6 by the (documented, and structurally confirmed) claim that the two behave identically. Regenerate the full 331-row list with `python survey.py --locate 6,7 --root <update folder>/data/music`. A sample (chart, format version, side, position `measure,beat,cell` 1-indexed, length - from `C8` on v12 and `C9` on v13, see "Which column holds the length"):

```
roll_type=7  0642_sayonara_planet_wars_kuroma_4i.vox   v12  side=R  pos=035,03,00  len(C8)=17
roll_type=7  2101_jamawoshinaide_symholic_5m.vox      v12  side=L  pos=093,04,24  len(C8)=28
roll_type=6  0044_sekaiha_neko_nem_4i.vox             v12  side=L  pos=025,03,00  len(C8)=6
roll_type=6  0271_vallis_djyoshitaka_4i.vox           v12  side=R  pos=032,04,24  len(C8)=50
roll_type=6  2244_kakugoseyo_makishiukyou_5m.vox      v12  side=L  pos=038,04,24  len(C8)=14
roll_type=6  0152_earthquake_super_shock_soundholic_4i.vox  v13  side=L  pos=048,04,24  len(C9)=30
roll_type=7  0220_ongaku_leaf_4i.vox                  v13  side=L  pos=088,01,00  len(C9)=18
roll_type=6  2268_littleprana_amamihinami_5m.vox      v13  side=L  pos=020,01,00  len(C9)=13
```

## Reference charts are hand-made, not derived

`scripts/shared/README.md` already states the `scripts/shared/reference/ksh` conversions are **manual** - done by a human watching the game, not generated from `.vox`. For notes and lasers this didn't matter much: the underlying event data is exact, so a competent transcription converges almost exactly (`notes.md`'s near-exact BT/FX/laser-run counts). For camera it matters a lot, because camera values are a continuous, subjective "does this look right" quantity:

- **Per-song zoom regression is not one constant.** `zoom_top` slopes cluster loosely around 90-200 (most 135-160, with `140.00` recurring exactly in 5 different songs' regressions - `foolish_again/exh.ksh`, `memory_flow/mxm.ksh`, `resonant_gear/mxm.ksh`, `rip_gossip_no_umi/exh.ksh`, `the_king_of_red/adv.ksh`, all R² ≥ 0.999, which is a real signal at that repetition rate). `zoom_bottom` slopes cluster around -90 to -152, mostly -117 to -136.
- `#SPCONTROLER`'s `Realize` rows were checked as a candidate per-song calibration factor and ruled out for the reference set specifically - every one of the 30 matched (v10/v12) charts has byte-identical `Realize` payloads. **Correction**: it's not universally fixed - a broader v13 survey (see `vox_format.md`'s `#SPCONTROLER` `Realize` entry) found 5/148 charts with a different payload (varying `CAM_Radi`'s overshoot/end values). Rare, and not revisited as a zoom-scale explanation yet, but no longer "always identical" as originally stated.
- **Tilt intervention style varies wildly by song.** Counting `tilt=` events per laser run across the 30 reference charts: 5 songs use **zero** manual tilt lines at all (pure `tilt=normal` throughout - `aim_higher`, `aqua_luna_rium`, `chakra`, `komorebi_ni_saku`, `shiawase_usagi_peko_miko_marin`), while others range from light touch-ups (~0.1-0.6 events/run) to dense hand-animation (up to 7.37 events/run in `furiko_doll/mxm.ksh` - a near-continuous manual reproduction of the tilt curve, not a simple bracket idiom). Per direction, this is a low-priority piece.
- Per direction (zoom accuracy isn't the bar), `camera.py` uses ~140 / ~-125 as central-tendency constants, clearly flagged as approximate.

## Zoom: sign, direction, and the constants used

- `CAM_RotX` correlates **positively** with `zoom_top` (matches vox's "higher = lane top higher on screen" against ksh's rotation description directly, no sign flip).
- `CAM_Radi` correlates **negatively** with `zoom_bottom` - vox's "higher `CAM_Radi`" means more zoomed out, ksh's "higher `zoom_bottom`" means more zoomed in, so a converter must negate.
- `camera.py`'s `ROTX_TO_ZOOM_TOP = 140.0`, `RADI_TO_ZOOM_BOTTOM = -125.0`. Both endpoints of every segment are emitted (not just each segment's start plus a final end - see "Bugs found and fixed" below for why that was wrong), deduplicated where consecutive segments hand off the same value, and spaced apart where they don't - i.e. a same-tick vox snap.

## Tilt: automatic baseline and manual passthrough

**Confirmed by direction**: only 9% of charts carry a manual `Tilt` track (v10/v12 corpus-wide), yet every reference chart is full of `tilt=` lines - so most tilt output is SDVX's own automatic laser-driven tilt (governed by `#TILT MODE INFO`'s 0/1/2 normal/bigger/stay-max mode), computed independently by the arcade engine, not read out of the vox file. **The auto-tilt formula itself is not modelled** - `camera.py` leaves this to ksh's own built-in auto-tilt (`tilt=normal` as the baseline), which is not necessarily identical to the arcade's, but is the closest available approximation without the DLL. Confirmed low priority per direction. Note: manual `Tilt` is far more common in chart-format-13 charts specifically - 36% of a 148-chart v13 sample vs 9% in the v10/v12 corpus, see `vox_format.md`'s "Format version 13" - which shifts how much of a v13 chart's tilt behaviour this passthrough actually covers, without changing the mechanism itself.

`compute_tilt_events` therefore does two things only: emit `tilt=normal` as the baseline, and pass through any manual `Tilt` vox segment as floats at each segment's start/end tick (charter-authored camera work, not auto-tilt, so it overrides the baseline outright).

### The manual passthrough sign was inverted - corrected

**The two formats measure lane tilt in opposite directions.** A vox `Tilt` of `+1.0` is a ksh `tilt=-1`, and the passthrough was emitting the vox value verbatim - tilting every hand-authored camera move in the chart the wrong way. User-reported, and confirmed against the reference conversions: of 4252 non-trivial matched samples (both values away from zero), **4205 - 98.9% - have the ksh value opposite in sign to the vox one**, and `correlate.py`'s pooled "tilt -> tilt (manual vox Tilt track only)" regression is `ksh = -1.5681 * vox`, R² = 0.911 over n = 6520. `camera.py` now applies `TILT_VOX_TO_KSH` to both endpoints of every segment.

**The magnitude is the open half of that constant, and the corpus does not agree with the unit reading.** 1.0 is what the formats' own definitions imply: vox `Tilt` is bounded to [-1, 1], and ksh's manual tilt is in units of one full normal tilt (`HighwayTiltManual` sets `kTiltRadians * value`, the same `kTiltRadians` a fully-deflected auto tilt reaches). Controlling for per-song charter scale the way the spin-length law had to - pooling hides it, see "Length" below - the modal `ksh/vox` ratio across the 107 reference songs with usable manual-`Tilt` coverage is:

| modal ratio | songs |
|---|---|
| -1.49 to -1.52 | 56 |
| -2.00 to -2.08 | 16 |
| -2.4 to -2.5 | 9 |
| beyond -2.5 | 3 |
| -1.0 | 1 |
| ~0 (charter ignored the track) | 4 |

So the charters cluster hard on **-1.5**, with a second cluster at -2.0 and a tail upward - the same shape as the spin-length scales (24 true, charters at 32/36/48), except that here almost nothing sits at the unit value. Either KSM's manual tilt unit is genuinely about two-thirds of SDVX's, or every charter uniformly exaggerates. `#TILT MODE INFO` is ruled out as the explanation: every chart sampled carries mode 0, so the spread is not a tilt-mode scale. Within-song agreement on the modal ratio is only 0.60 (median), much looser than the spin case, which is expected for a hand-drawn continuous curve.

**`TILT_VOX_TO_KSH` is left at `-1.0`, the unit reading**, so the converter emits roughly two-thirds of the reference charters' amplitude on the median song. Changing that one constant to `-1.5` follows the charters instead. The sign is not in question either way.

With `pretilt_fix=False` (the default) that is all `compute_tilt_events` does, and the baseline `tilt=normal` hands the anticipation question to KSM's auto-tilt engine entirely. With `pretilt_fix=True` it additionally emits the flat brackets described in the next section.

## Pretilt: KSM's two-beat laser anticipation

**Correction to this document.** The earlier reading - that pretilt "is triggered by *any* laser, not some chart-detectable subset of them", making it a KSM-engine property no `.vox` -> `.ksh` mapping could selectively cancel - is wrong on both halves. The trigger is a precise two-condition predicate over the laser data, and the reference conversions cancel it with an idiom that shows up 7088 times. The earlier investigation (a silence-before-laser heuristic fit from one clean example, plus the `gen_pretilt_test.py` / `pretilt_test.ksh` / `PRETILT_TEST.md` test chart, `git stash`ed) was looking for the wrong condition, not chasing a nonexistent one.

`camera.py` implements the fix behind `pretilt_fix` (default off) - see [What the converter emits](#what-the-converter-emits) at the end of this section for the shipped predicate, its deliberate conservatism, and the measured firing rate.

### The mechanism, from KSM's source

KSM v2's [`HighwayTiltAuto.cpp`](https://github.com/kshootmania/ksm-v2/blob/master/kshootmania/src/MusicGame/Camera/HighwayTiltAuto.cpp) computes the auto-tilt factor per frame, per laser lane, as: take `GraphSectionValueAt(lane, currentPulse)` - the laser value under the crit line; **if that lane has no active section, take instead the first point value of `FirstInRange(lane, currentPulse, currentPulse + kson::kResolution4 / 2)`**; then accumulate `tiltFactor += isLeftLaser ? v : -(1.0 - v)`. `kResolution = 240` and `kResolution4 = kResolution * 4 = 960` ([libkson `Common.hpp`](https://github.com/m4saka/libkson/blob/master/include/kson/Common/Common.hpp)), so the look-ahead window is **480 pulses = 2 quarter notes = 96 ksh 192nds = half a 4/4 measure**. That branch is pretilt: an idle lane tilts to the *first point value of a section that is still two beats away* and holds there until the laser actually arrives.

Three properties fall straight out of that expression, and all three are chart-side facts:

- **Magnitude is set by how far the section's first point sits from that lane's home edge.** Left lane contributes `v`, right lane contributes `-(1 - v)`. A left laser opening at the left edge pretilts by **0.0** - nothing at all; opening at centre pretilts by **0.5**; opening at the right edge pretilts by a full **1.0**. Mirrored for the right lane. Home-edge openings are free, centre and crossed openings are not.
- **The predicate is per lane, not per chart.** The look-ahead only runs for a lane with no section under the crit line, so the trigger is "*this* lane has been idle for the last two beats", and a long right laser parked at its home edge does not stop the left lane from pretilting into its next section.
- **The lead is counted in beats but the lane moves in real time.** `Speed()` interpolates the smoothed factor at a base of 4.5/s, floored by `kMinSpeed = 0.5` and tapered within `kSlowDownDiffThreshold = 0.1` of the target, and multiplies by `kZeroTiltSlowDownFactor = 1.0 / 5` when the target is under `kZeroTiltFactorThreshold = 0.001` - i.e. the return to flat is five times slower than the swing away from it. Two beats is 1.2 s at 100 BPM and 0.6 s at 200, so a slow song completes the pretilt and parks there visibly, while a fast one barely gets moving before the laser lands.

The tilt keywords act on the *scale*, not this factor: `radians()` returns `kTiltRadians * smoothedFactor * m_tiltScale`, with `m_tiltScale` chasing `kson::AutoTiltScaleAt(...)` at `kTiltScaleInterpolationSpeed = 4.0` - so `tilt=zero` fades the lane flat over roughly a quarter second rather than killing it outright. Manual float tilt is a different path: [`HighwayTilt.cpp`](https://github.com/kshootmania/ksm-v2/blob/master/kshootmania/src/MusicGame/Camera/HighwayTilt.cpp) returns `std::lerp(m_auto.radians(), m_manual.radians(), m_manual.lerpRate())`, and [`HighwayTiltManual.cpp`](https://github.com/kshootmania/ksm-v2/blob/master/kshootmania/src/MusicGame/Camera/HighwayTiltManual.cpp) drives `m_lerpRate` by `Scene::DeltaTime() / 0.04` in whichever direction - **manual takes over in 40 ms and applies its value directly, with no smoothing at all**. That is the practical difference between the two ways of flattening a lane: `tilt=zero` is a ~250 ms fade of the auto path, `tilt=0` is a hard cut to a manual graph.

### When it is visible

Combining the predicate with the timing constants, pretilt is worst when: the lane has been idle two full beats (dense continuous laser passages are immune outright); the upcoming section's first point is away from its home edge, so centre openings at factor 0.5 and crossed openings at 0.75-1.0; **the section opens with a slam**, which is both the commonest and the ugliest case - an isolated centre-to-edge slam makes the lane tilt halfway toward the slam's *origin* for two beats and then whip the other way when the slam hits, where the arcade lane is flat for the whole run-up; the BPM is low, so the swing completes and holds; there are BT/FX notes in the run-up, which is what turns a cosmetic difference into a readability problem; and lasers spaced under two beats apart, where the 5x slower return plus a fresh anticipation target means the lane never settles between them.

### What the reference charters do about it

Measured over all 1238 conversions in `scripts/shared/reference/ksh` (1234 carry lasers, 1009 carry `tilt=` lines). **Unlike every other measurement in this document, these numbers have no in-repo script behind them yet** - they came from throwaway analysis outside the tree, so they are reproducible only by rebuilding it (parse `tilt=` events and laser sections to ticks, honouring the option-line rule in the caveats below; classify each section start by the idle-lane predicate; compare tilt-transition ticks against section-start ticks, against a shifted control). The idiom is **flatten the run-up, then hand the tilt back exactly on the laser's first point**:

- Of the 8067 `zero`/`0` -> auto-keyword restorations in the corpus, **87.9% land on the exact tick of a laser section start**. Control distribution - the same tilt events shifted one beat later - lands exactly on a laser start 13.6% of the time, so this is a ~6.5x enrichment, not an artefact of lasers being common.
- The flat region ahead of that restore has a **median length of 3 beats**, with modes at exactly 3.0 (1538), 2.0 (677), 1.0 (670) and 4.0 (576) - sized to cover the two-beat window with a musical margin.
- The flattening end of the bracket is placed at the previous laser's edge: 15.2% land on a laser *start* tick exactly (that is, on a slam's origin point, killing the tilt from the slam onward) and 42.3% within a quarter beat of a laser *end*.
- Both tokens are in live use, and the choice is meaningful given the 250 ms-versus-40 ms difference above: `tilt=zero` in 807 charts / 6964 events, `tilt=0` in 486 charts / 7197 events, non-zero manual floats in 407 charts / 10903 events, and `keep_*` in only 38 charts / 74 events - the keep family is essentially unused for this. 892 same-tick tilt pairs exercise the instant-change trick. 5 charts drive tilt entirely from manual floats, which suppresses auto-tilt (and therefore pretilt) outright via the `lerpRate` blend.

How often they bother, over the 64577 section starts that meet the idle-lane predicate (25.6% flattened overall), cut by whether the section opens with a slam and by `|pretilt factor|`:

| opens with slam | \|factor\| | n | run-up flattened |
|---|---|---|---|
| no | 0.00 | 12558 | 12.8% |
| no | 0.25 | 2177 | 33.5% |
| no | 0.50 | 4616 | 30.5% |
| no | 0.75-1.00 | 805 | ~21% |
| yes | 0.00 | 30142 | 20.7% |
| yes | 0.25 | 4203 | 36.6% |
| **yes** | **0.50** | **9224** | **49.5%** |
| yes | 0.75-1.00 | 852 | ~31% |

Half of all centre-opening slams after an idle lane get their run-up flattened by hand, against a 12.8% floor for home-edge openings with no slam. The two secondary cuts move the same way: run-up note density takes it from 12.4% (no BT/FX notes in the two beats before) to 30.0% (5-9 notes), and gap length from 23.7% (8+ beats idle) to 28.0% (2-4 beats idle). Note that the 0.75-1.00 buckets score *lower* than 0.50 despite being the larger visual error - they are rare (n=1657 combined) and tend to sit in passages dramatic enough that the tilt is wanted anyway.

A clean worked example is `yukibare_parade/mxm.ksh`, measures 15-16: `tilt=zero` goes in as the preceding lasers end, three beats of flat follow, then `tilt=normal` sits on the line immediately before `0000|01|o-` - a left laser opening at `o` (= 1.0, the far right edge), the maximum-pretilt case.

### What the converter emits

`camera.py`'s `_pretilt_brackets` walks every laser section (segmented by the same `node_type` 1/2 rule as `notes/laser.py`'s `_split_into_runs`) and emits a `tilt=zero` ... `tilt=normal` pair for each one that qualifies:

- **Its lane has been idle for the look-ahead window** - `PRETILT_WINDOW_BEATS = 2.0`, the engine's own `kResolution4 / 2`.
- **Its first point is far enough from that lane's home edge to matter** - `PRETILT_MIN_FACTOR = 0.25` against `pos` (left lane) or `1 - pos` (right), the engine's own `isLeftLaser ? v : -(1.0 - v)`. Home-edge openings score 0 and are skipped outright, since they pretilt by nothing.
- **The window is clear of laser sections on *both* lanes**, not just this one. This is the deliberate conservatism in the implementation: ksh's `tilt` is global while KSM's look-ahead is per lane, so a lane anticipating its next section *while the other lane holds a real laser* is genuine pretilt that cannot be cancelled without flattening the other lane's arcade-correct tilt at the same time. Those cases are left alone. It is the known gap, and the reason the converter fires on far fewer sections than the reference charters do.

The bracket closes on the section's own first point tick (already a grid anchor, so it costs no extra resolution) and opens `PRETILT_WINDOW_BEATS + PRETILT_LEAD_BEATS` earlier - the half-beat lead exists so `tilt=zero`'s ~250 ms scale fade finishes *before* the anticipation window opens rather than racing it. The opening tick is snapped down to a 1/16-note grain (`PRETILT_SNAP_BEATS`) to keep `measure_resolution` from being forced fine for one option line, and clamped to never open inside the preceding laser. Brackets overlapping a manual `Tilt` vox segment are skipped, since the passthrough owns tilt there.

**All lengths are in quarter notes and multiplied by the chart's own `tl.res` at use.** This module works in vox ticks - `notes/convert.py` never rescales, it derives each measure's line count straight from `tl.measure_length` - and `#BEAT RESOLUTION` is per chart (480 on the charts checked, 48 when the header is absent). The first version of this code was sized in ksh 192nds and silently produced fifth-of-a-beat brackets on a 480-tick chart.

Measured over a random 400-chart sample of the corpus: 47.8% of charts get at least one bracket, mean 2.7 per chart, median 0, p90 9, max 24, with the total `tilt=` event count rising from 1038 to 3192. Every bracket satisfies the invariants by construction and by check - closes on a real section start, never overlaps a laser on either lane, never shorter than the window, never overlapping another bracket: 0 violations across those 400 charts. On `1972_guinevere_penoreri_5m` the output grows by 12 lines out of 57771. With the flag off, `camera=True` output is byte-identical to pre-change `camera.py` across a 40-chart sample.

That firing rate is far below the reference charters' 25.6% of qualifying sections, entirely because of the both-lanes-clear requirement plus the 0.25 factor cut. Loosening either is a `min_factor` argument away, but the conservative default is the right one for a converter: a missed pretilt looks like KSM, a wrong bracket kills tilt the arcade really had.

### What is still unproven

Caveats, recorded rather than resolved:

- **The source read is KSM v2, not the v1.6x binary the reference charters were working against.** m4saka targets v1 compatibility and the corpus behaviour is consistent with the v2 constants, but the two have not been diffed. `ksh_format.md`'s `ver` notes already document that tilt relaxation time and keep semantics changed across 1.20/1.20b/1.21, so version-sensitivity in this area is established.
- **The corpus cannot separate "cancel KSM pretilt" from "reproduce a passage SDVX genuinely left untilted"** - they are the same edit, because the arcade starts tilting *at* the laser. The onset alignment is what makes the intent legible: restoring on the laser's exact first point is the SDVX-faithful timing and the pretilt fix simultaneously.
- **USC is not KSM here.** [`Camera.cpp`](https://github.com/Drewol/unnamed-sdvx-clone/blob/master/Main/src/Camera.cpp) computes roll reactively from current laser positions with no look-ahead branch, so a chart bracketed for KSM pretilt simply reads as un-tilted in those spans under USC. Only USC's `Camera.cpp` was read, not its full scoring-to-roll path.
- **Measurement gotcha, worth recording.** ksh option lines do not consume a grid slot: a measure's resolution is set by its note lines alone, and an option line applies at the position of the note line that follows it. Assigning ticks by raw line index instead smears the onset-alignment result from 87.9% down to 2.4% and moves the apparent restore point a few ticks earlier than the laser, which reads as a deliberate lead and is not one.
- **The emitted brackets have not been played.** They are verified structurally (predicate, invariants, grid placement, no-op when disabled) and against the reference idiom, not by watching a converted chart in KSM. Same standard as the rest of this document's camera work - see "Converter status".

## Spin/swing: kind, direction and length

**Kind mapping - confirmed by direction, and 1353/1354 against the reference set.** Vox's "roll" variants (`roll_type` 1, 2, 3, 4, 6, 7) map to ksh's full spin (`@(`/`@)`); vox's "swing" (`roll_type` 5) maps to ksh's half spin (`@<`/`@>`). `S<`/`S>` (ksh's own dedicated swing token) is never emitted - confirmed unused in every reference chart, including for genuine vox `roll_type=5` swings (charters used half-spin instead), so per direction this converter omits it too.

**Direction - confirmed by direction, 1347/1354 (99.5%) match.** The roll/swing tag sits on the laser point immediately *before* a same-tick slam in every raw example inspected (not after - the direction that matters is the outgoing movement, computed by `_outgoing_dirsign` as the sign of the first position change at or after the tagged point, looking a few points ahead for curve cases). Hypothesis tested: a slam moving right-to-left (`dirsign < 0`) is clockwise -> `@(` (full) or `@<` (half); left-to-right (`dirsign > 0`) is counterclockwise -> `@)` or `@>`. Reported by `correlate.py`'s dedicated hypothesis-match-rate section.

### Length: solved - a ksh spin lasts exactly half the duration vox declares

**One law covers every roll type**: a ksh spin token's length is **half the vox-declared duration**, expressed in ksh 192nds. Since one quarter note is 48 ksh-192nds, that is `24 * (vox length in quarter notes)`. Reproduce the whole derivation with `python correlate.py`, whose "spin length" section prints every step below.

| roll_type | where the vox length comes from | ksh length |
|---|---|---|
| 1, 2, 3, 4, 5 | the length column in quarter notes, or the type's default (`DEFAULT_BEATS` = 6, 2, 3, 12, 3) when it is 0 | `24 * beats` |
| 6, 7 ("8x speed") | the length column counting 1/32 notes (= 1/8 quarter note) | `3 * units` |

The length column is `C8` up to format 12 and `C9` from format 13, for every roll type - see "Which column holds the length" below. `shared/vox.py` resolves that per chart, so `p.roll_length` in `camera.py` is always the right column and nothing downstream carries a version test.

**Why half.** `vox_format.md`'s C3 note already says it: vox's lengths "refer to the time the roll takes to *completely* finish, including overshoots — unlike KSM roll lengths, where the overshoot occurs after the specified length". The measurement adds the missing number - the overshoot takes exactly as long as the rotation it follows, so ksh gets half of what vox declares.

**The thing that makes this measurable is controlling for the charter.** The reference conversions are hand-made, and each song's charter picks one scale and holds it across that song - but *different* charters picked different ones. Per song, the modal `ksh_len / C8` is exactly 24 in 282 of 390 songs; the rest sit at 32 (24 songs), 36 (21), 48 (19) and a thin tail. Pooling raw lengths mixes those together and hides the law - which is how an earlier version of this section, working from three `roll_type=1` samples that happened to come from 32-scale songs, concluded `ksh_length = 32 * C8`. **Correction: that constant was fit to a minority-charter subset.** Across all 1354 samples, `24` matches exactly 64.1% of the time and `32` only 16.5%, and the residual is one-sided charter rounding (`x1.333` 16.5%, `x1.5` 5.7%, `x2.0` 4.5%) rather than scatter.

Three independent things confirm 24 rather than a fitted average:

- **Large `C8` values land dead on it.** `C8` of 10, 11, 22, 30, 32, 46 produce ksh lengths of exactly 240, 264, 528, 720, 768, 1104. Nothing is being rounded to a comfortable musical value at that size.
- **`roll_type=6` is transcribed machine-exactly, 61/64.** Its 1/32-note unit puts the factor at `24/8 = 3`, and `C8` of 13, 17, 23, 33, 37 produce ksh `39`, `51`, `69`, `99`, `111` - numbers no charter picks by feel. Type 6 is the cleanest evidence in the whole section, and it is the same law.
- **BPM and time signature are both ruled out.** Regressing ksh length on BPM within a fixed `(roll_type, C8)` gives R² ≈ 0 in every group (the spin is musical time, not wall-clock). Non-4/4 measures fit the same 24 (33/54 exact in 3/4) while a "192 is per *current* measure" alternative fits none of them - so ksh's 192 is a fixed 4/4-measure unit, as `ksh_format.md` implies. Laser-run length doesn't explain the residual either (exact-match rate is flat at 60-74% across every run-length bucket).

**The length-column-is-0 defaults match `vox_format.md`'s names after all** - `{1:6, 2:2, 3:3, 4:12, 5:3}` quarter notes. **Correction to `vox_format.md`**, which recorded types 2 and 5 as contradicting their names: they don't, and neither do 1 and 3. Restricting to songs whose explicit-length rows measure exactly 24, the implied default is 6.00 (rt1, median of 19), 2.00 (rt2, of 6), 3.00 (rt3, of 17) and 3.00 (rt5, of 93) - each the median *and* the mode. Pooling without that restriction is what made rt1 look like 8 beats and rt3 like 4: songs that only ever use default-length rolls have no explicit rows to measure their scale from, and skew 32-ward.

A **scale-free cross-check** settles it without needing any scale at all, since the charter's factor cancels in a ratio between two types in the same song: rt3/rt5 = 1.000 (median over 14 songs, 9 exact), rt1/rt5 = 2.000 (23 songs, 13 exact), rt1/rt3 = 2.000 (19 songs, 12 exact) - exactly the 6:3:3 the names predict. You can read it straight off the per-song table: `air/exh` defaults to `{rt1:144, rt3:72, rt5:72}` and `air/mxm` to `{rt1:192, rt3:96}` - same song, two difficulties, two different charter scales, identical ratios.

**Type 4 is the one gap.** `12` is its name, not a measurement: the reference set contains a single type-4 sample (`tetoris/mxm`, `C8=3` -> `@)120`, where the law predicts 72), and the corpus holds only 27 type-4 rows in total, 22 of them with no explicit length at all. KSM has no triple-spin token to transcribe faithfully in the first place, so this may not be recoverable from hand charts at all.

### Which column holds the length

**Correction, and a bigger one than it looks.** This section previously said the length column moves from `C8` to `C9` in format 13 *for roll types 6 and 7 only*, and that v13's `C9` on types 1-5 stays the unrelated "cells per chain" and must not be read as a length. That is wrong: the shift applies to every roll type. Charts converted before this fix silently dropped every explicit v13 length and fell back to the type default - e.g. `2393_alive_dadadaizu_5m.vox` measure 115, a type-1 roll with `C9=15`, emitted `@)144` (the 6-beat default) where it should emit `@)360`.

The reason it is not a per-type rule is structural: the shift lives in the game's row *parser*, which reads all ten columns into one record before anything has looked at the roll type. Full derivation, with the record-slot tables and the corpus discriminator, is in [`vox_format.md`](vox_format.md)'s "How the version shift was settled" - in outline:

- The current chart reader (`FUN_18023baa0`, laser-row loop at `0x18023d470`) has three version branches, `< 12` / `== 12` / `>= 13`. They differ in exactly two ways: whether the position column is an int 0-127 or a float 0-1, and whether the 8th data column lands in a v13-only record field (`+0x34`) with the length and cells-per-chain pushed one slot along.
- The record field that holds the length (`+0x38`) is fed from `C8` by the v10/v12 branches and from `C9` by the v13 branch. `C8` as the v10/v12 length is what the 1354 reference samples above validate, so the same field being fed from `C9` in v13 settles v13 without needing any v13 reference chart.
- The corpus says the same thing on its own: a length can only matter on a row that carries a roll, and the column that is *never* nonzero on a `roll_type=0` row is `C8` in v10/v12 (0 of 2,861,916 non-roll rows) and `C9` in v13 (0 of 93,086). The other column of the pair is the roll-independent one in both cases. `python scripts/camera/survey.py --lasercols` prints the table.
- Per type, v13's `C9` reproduces v12's `C8` distribution, type 1 included: `[1,1,2,4,46]` mean 3.6 against `[1,2,3,5,21]` mean 4.1 (quartiles `[min, q25, median, q75, max]`). The earlier reading had that same v13 column pegged as cells-per-chain on the strength of it being "an order smaller" than the type-6 lengths - but it was only ever being compared against 6/7's 1/32-note counts, never against v12's type-1 quarter-note lengths, which sit in exactly the same range.

So `TYPE67_UNIT_TO_KSH192 = 3` and `BEAT_TO_KSH192 = 24` both apply to whichever column the version selects, and `_spin_length` no longer needs a version test or a `C8`-vs-`C9` tie-break at all. The 23 v13 rows carrying both columns are no longer ambiguous either: their `C8` is 1 or 2, which is the v13-only flag's entire value range (`0`, `1`, `2` across all 93,574 v13 laser rows, on rows with and without rolls alike), not a vestigial length.

**What is still inherited rather than measured** is the v13 length's *unit*. No format-13 chart has hand-chart coverage - `correlate.py` matches zero of the 148 against `scripts/shared/reference/ksh`, they are all songs from a 2026 update - so "quarter notes for 1-5, 1/32 notes for 6/7" carries over from v10/v12 on the strength of the shared record field and the matching distributions. The type-6 sanity check still lands where it did: `C9=32` on `2393_alive_dadadaizu_5m.vox` track8 measure 79 is 4 declared quarter notes, halved to `@(96`, the "around 2 beats" the original source described.

## Bugs found and fixed

1. **Same-tick snap overwrite (both zoom and tilt), analogous to `notes.md` bug #3** ("a same-tick slam landing on a run boundary lost its true endpoint entirely, drawing a diagonal instead of a vertical drop"). A vox camera/tilt segment can be zero-length (`tick == end_tick`) with `start != end` - a genuine instant jump, the same idea as a laser slam. `compute_zoom_events` and `compute_tilt_events` originally wrote `events[tick] = value` per segment into a plain dict; when a zero-length segment shared its tick with the next (or the previous) segment, the later write silently clobbered the earlier one, and the arrival/departure value pair collapsed into whichever value got written last - erasing the peak or trough the snap was there to represent, and drawing a shallow ramp straight through it instead. Confirmed on `2226_gryphone_etia_5m.vox` (flagged by direction as a heavy camera/tilt chart worth checking): `cam_rotx`/`cam_radi` each have 7 zero-length segments sharing a tick with their neighbour, `tilt` has 2. Fixed by routing every track through `_place_track` (`camera.py`), which spaces genuinely distinct same-tick values one grid cell apart instead of overwriting - the same fix shape as the laser one, and for the same reason (ksh has no way to hold two different values on one grid line, so an instant vox transition needs two adjacent ksh ones). Example, `zoom_top`/`zoom_bottom` at the very start of `2226_gryphone_etia_5m.vox` (an initial-framing snap before anything else happens): before the fix, only `zoom_top=-105 zoom_bottom=94` would have survived (jumping straight to the second segment's target, no line for the resting `0, 0` before it, or the diagonal-instead-of-vertical version of it depending on which segment ordered last); after the fix, `zoom_bottom=0`/`zoom_top=0` and `zoom_bottom=94`/`zoom_top=-105` are both emitted, one cell apart.

2. **Dedup dropped the hold-anchor point right before a ramp, collapsing holds into long diagonals.** `_dedupe_consecutive`'s original form kept only the *first* point of a run of consecutive-equal-value ticks and dropped the rest - including the *last* one, which is what stops ksh's linear interpolation from blending a flat hold straight into whatever ramp comes after it. Found by direction on `2226_gryphone_etia_5m.vox` measures 90-93: vox snaps tilt to 1.0, **holds it there for ~335 cells (~7 beats)**, then ramps down to -1.0 over the next 48 cells, holds again for ~288 cells, then ramps to 0 over 96. With only the run's first point kept, the output jumped straight from the snap to a single line at the *ramp's end* value, turning "hold at 100%, then a quick flip to -100%" into one long diagonal spanning the entire hold-plus-ramp duration - exactly what was reported. Fixed by keeping a point whenever it differs from *either* neighbour (i.e. both the first and last point of every same-value run survive; only strictly-interior repeats get dropped) - verified against the raw vox segments directly post-fix: `camera.py` now emits `(17088,'0') (17089,'1') (17424,'1') (17472,'-1') (17760,'-1') (17856,'0') (17857,'normal')` for that span, correctly holding through 17424 and 17760 before each ramp.

**On `scripts/camera/2226_gryphone_etia_5m.ksh`, corrected**: an earlier version of this document called this file "an actual hand-charted reference" and reported a suspicious 100%-exact match against it (tilt 59/59, zoom 54/54, spin 4/4) as validation. That was wrong on inspection - its header is machine-placeholder output (`artist=`, `effect=`, `jacket=`, `illustrator=` all blank; `difficulty=infinite`/`level=1`/`bg=desert`/`layer=arrow` all matching `notes/convert.py`'s own hardcoded defaults exactly; `title=2226_gryphone_etia_5m` matching its `"title=%s" % base_filename` placeholder convention verbatim), i.e. it's prior machine-generated output from some earlier version of a similar converter, not independent ground truth - which is exactly why it agreed with this session's *also-buggy* output on the hold-collapse bug above: both pieces of code made the same mistake. The file is left in place (not this project's to delete) but is no longer treated as a reference anywhere in this document. The only trustworthy validation done was against the vox segment data directly, by hand, per bug 2's writeup.

## Converter status

`scripts/camera/convert.py` produces a complete chart (notes + camera together, via `notes/convert.py`'s `camera=True` path). Smoke-tested on: a plain chart (`1734_777_roughsketch_3e`, output grows from 24585 to 25135 lines, +2.2%, from the extra grid resolution camera anchors require - not a blowup), a manual-`Tilt` chart (`0418_werewolf_howls_camellia_4i`, floats pass through with the sign flip applied - vox `-0.500` at tick 768 emits `tilt=0.5`, vox `+0.500` at 1152 emits `tilt=-0.5`), a `roll_type=7` chart (`0642_sayonara_planet_wars_kuroma_4i`, produces a syntactically valid but unvalidated-length spin token), and a heavy camera/tilt chart (`2226_gryphone_etia_5m`, where both bugs above were found and their fixes verified directly against the raw vox segments - see "Bugs found and fixed"). `notes/xcheck.py` confirmed byte-for-byte unaffected when `camera=False` (the default), so this is additive, not a risk to the existing notes/laser work. The same held for `pretilt_fix` when it landed: with the flag off, `camera=True` output was byte-identical to the pre-`_pretilt_brackets` module across a 40-chart sample, checked by rebuilding the old `compute_tilt_events` and diffing whole conversions. That no longer describes the module as a whole - the manual-tilt sign fix above deliberately changes `camera=True` output on every chart carrying a `Tilt` track - but it still describes `pretilt_fix` itself, which touches nothing when off.

No independent hand-charted reference with heavy camera work has been found yet (the one candidate turned out to be prior machine output - see above), so beyond the raw-vox-segment checks in "Bugs found and fixed," this converter's camera output hasn't been validated against an authoritative outside source. Treat it as "matches the vox data's own structure, by direct inspection," not "verified correct" until one exists.

Known integration gap: spin tokens are placed at the vox roll point's exact tick, but if `laser.py`'s curve decimation (see `specs/notes.md`) drops that exact point when building the ksh laser run, the spin suffix can end up hanging off a `:` continuation character rather than a real laser position character. Not yet checked how often this happens or whether it renders acceptably in KSM.

## Open items

1. **Tilt auto-mode formula** - not modelled; `camera.py` relies on ksh's own built-in auto-tilt as an approximation. Low priority per direction.
2. **Spin length for `roll_type` 4 and 7** - the length law and the type defaults are settled for 1, 2, 3, 5 and 6 (see "Length" above); type 4 has one reference sample that the law misses, and type 7 has none at all and rides on type 6. Both are rare enough (27 and 67 corpus rows) that hand charts may never supply the evidence. Separately, **no format-13 chart has reference coverage at all**, so the v13 length column's unit is inherited rather than measured - see "Which column holds the length".
3. **Spin/laser-decimation interaction** - whether a roll point can lose its exact grid line to curve decimation, and what that looks like in the output.
4. Per direction, DLL work stays the fallback once the above are worth revisiting, not the starting point. One exception has already been taken: the chart reader's laser-row parser was read to settle which column holds the roll length, because no hand chart can settle it (see "Which column holds the length"). The current reader is `FUN_18023baa0`, not the `FUN_180239810` this item used to name - that one parses an older format generation. Still unexamined: the gameplay-event kinds in `FUN_180407200`, and whatever consumes the v13-only `+0x34` field.

5. **Pretilt bracketing when the *other* lane is busy** - the shipped fix requires the anticipation window to be clear of lasers on both lanes, because ksh's `tilt` is global and KSM's look-ahead is per lane (see [What the converter emits](#what-the-converter-emits)). Cancelling pretilt during another lane's active laser would need the auto-tilt formula modelled and reproduced as manual floats - i.e. open item 1 - rather than a `zero`/`normal` bracket.
6. **The manual-tilt magnitude** - `TILT_VOX_TO_KSH` is at the unit value `-1.0` while the reference charters cluster at `-1.5` (see "The manual passthrough sign was inverted"). Deciding between "KSM's tilt unit really is ~2/3 of SDVX's" and "the charters exaggerate uniformly" needs either the DLL's own tilt render path or a side-by-side playback comparison; the sign half is settled and shipped.
7. **Whether the v2 constants match v1.6x.** The two-beat window, the 4.0 tilt-scale fade and the 40 ms manual takeover all come from ksm-v2 source; the binary the reference charters worked against is v1.6x, and `ksh_format.md`'s `ver` notes already document that tilt relaxation and keep semantics changed across 1.20/1.20b/1.21. A test chart played in the actual target build would settle it.
