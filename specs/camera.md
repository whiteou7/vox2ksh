# The camera element

**Status: converter exists (`scripts/camera/convert.py`); spin is solved (kind, direction and length), zoom is on reasonably solid ground.** Scope, tools, and findings below. Nothing here has been checked against the DLL, per direction: settle what the manual reference conversions and direct domain knowledge can tell us first, fall back to the DLL only once that's exhausted.

**Pretilt is out of scope, by direction.** "Pretilt" is KSM anticipating an upcoming laser and starting to tilt before the arcade would - a behaviour embedded in KSM's own engine, triggered by any laser at all, not something specific to a subset of charts or a condition the chart data expresses. It's a game-engine problem, not a `.vox` -> `.ksh` mapping problem, so this converter does not attempt to cancel or otherwise reproduce/undo it - see "Tilt: automatic baseline and manual passthrough" below.

Scope: lane tilt, spin/swing and top/bottom zoom - the `.vox` tracks that move the playfield rather than the notes on it. Explicitly out of scope for this pass (KSMv2-only, or not expressible pre-v2): `zoom_side`, `center_split`, `rotation_deg`, `scroll_speed`, and the `*_curve` interpolation options. `zoom_side` usage was checked directly: zero occurrences across every file in `scripts/shared/reference/ksh`.

## What makes this element different

Audio and notes were both *transcription* problems: the game does something exact, and the job was to read it out of the binary. Camera turned out to be a mapping problem in a stronger sense than expected - see [Reference charts are hand-made, not derived](#reference-charts-are-hand-made-not-derived). Document the lossy/uncertain parts explicitly; a converter that silently discards or fabricates camera data is worse than one that says what it doesn't know. Per direction, exact accuracy on the zoom scale factor and the spin length formula isn't the bar here - a reasonable, documented approximation is fine; the goal is a converter that does something sensible everywhere and is honest about where it's guessing. (Spin length turned out to be recoverable exactly anyway, once the per-charter scale was controlled for - see "Length" below. Zoom is still an approximation.)

## Tools

| file | what it does |
|---|---|
| [`../scripts/camera/survey.py`](../scripts/camera/survey.py) | Walks all 8103 `.vox` charts, tabulates `#SPCONTROLER` control-type inventory, `Tilt`/`CAM_RotX`/`CAM_Radi` value ranges/lengths, and laser roll/swing (C3) x length (C8) distributions. `--locate <types>` pinpoints exact chart/measure occurrences of specific `roll_type` values. |
| [`../scripts/camera/correlate.py`](../scripts/camera/correlate.py) | Matches every `scripts/shared/reference/ksh` pair to its `.vox` source and correlates vox camera data against the hand-charted ksh camera lines by tick: regression for zoom, laser-position regression for tilt, and a full tabulation for spin (kind, direction, length). |
| [`../scripts/camera/camera.py`](../scripts/camera/camera.py) | The actual conversion logic: `compute_tilt_events`, `compute_zoom_events`, `compute_spin_tokens`, each taking a loaded `VoxChart` and returning tick-tagged events. Pure compute, no file I/O - documented inline, this file is the executable form of this writeup. |
| [`../scripts/camera/convert.py`](../scripts/camera/convert.py) | CLI: `python convert.py <chart.vox> [-o out.ksh]`. Thin wrapper - calls `../notes/convert.py`'s `convert(vox_path, out_path, camera=True)`, which places `camera.py`'s events into the same grid it builds for notes. `camera=False` (the default, used by `notes/xcheck.py`) is unaffected - verified byte-for-byte via `notes/xcheck.py` before/after this change. |

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
- **A `roll_type` value 7 exists** on `#TRACK1`/`#TRACK8`, v12 only, 49 rows corpus-wide - not documented in `vox_format.md`, which lists only 0-6. **Correction to inherited notes**, in the spirit of `audio_engine.md` §3's effect-id fixes. Its `C8` length range (5-28) overlaps type 6's (5-25).
- `roll_type` corpus counts: type 1 (6-beat) 8146, type 3 (3-beat) 4641, type 2 (2-beat) 3259, type 5 (swing) 2064, type 6 (v12 8x-roll) 202, type 7 (undocumented) 49, type 4 (12-beat triple) 25.

### Locating `roll_type` 6 and 7

**`roll_type=6` is now covered by the reference set** - 64 matched samples across 27 songs, once the corpus grew past the 30 charts this document was originally written against (644 matched pairs now). It is, in fact, the *best*-fit type of all, see "Spin/swing: length" below. **`roll_type=7` still has zero reference coverage**, so its length handling is inherited from type 6 by the (documented, and structurally confirmed) claim that the two behave identically. Regenerate the full 251-row list with `python survey.py --locate 6,7`. A sample (chart, side, position `measure,beat,cell` 1-indexed, `C8` length):

```
roll_type=7  0642_sayonara_planet_wars_kuroma_4i.vox   side=R  pos=035,03,00  len(C8)=17
roll_type=7  0675_beat_new_world_beatmario_4i.vox      side=R  pos=071,03,00  len(C8)=12
roll_type=7  2004_daiuchurmx_meto_5m.vox               side=L  pos=097,01,00  len(C8)=12
roll_type=7  2101_jamawoshinaide_symholic_5m.vox       side=L  pos=093,04,24  len(C8)=28
roll_type=7  2101_jamawoshinaide_symholic_5m.vox       side=R  pos=012,04,24  len(C8)=28
roll_type=6  0044_sekaiha_neko_nem_4i.vox              side=L  pos=025,03,00  len(C8)=6
roll_type=6  0271_vallis_djyoshitaka_4i.vox            side=R  pos=032,04,24  len(C8)=50
roll_type=6  1972_guinevere_penoreri_2a.vox            side=L  pos=014,01,00  len(C8)=25
roll_type=6  2213_kyoufuuallback_yukopi_3e.vox         side=L  pos=010,01,00  len(C8)=5
roll_type=6  2244_kakugoseyo_makishiukyou_5m.vox       side=L  pos=038,04,24  len(C8)=14
```

## Reference charts are hand-made, not derived

`scripts/shared/README.md` already states the `scripts/shared/reference/ksh` conversions are **manual** - done by a human watching the game, not generated from `.vox`. For notes and lasers this didn't matter much: the underlying event data is exact, so a competent transcription converges almost exactly (`notes.md`'s near-exact BT/FX/laser-run counts). For camera it matters a lot, because camera values are a continuous, subjective "does this look right" quantity:

- **Per-song zoom regression is not one constant.** `zoom_top` slopes cluster loosely around 90-200 (most 135-160, with `140.00` recurring exactly in 5 different songs' regressions - `foolish_again/exh.ksh`, `memory_flow/mxm.ksh`, `resonant_gear/mxm.ksh`, `rip_gossip_no_umi/exh.ksh`, `the_king_of_red/adv.ksh`, all R² ≥ 0.999, which is a real signal at that repetition rate). `zoom_bottom` slopes cluster around -90 to -152, mostly -117 to -136.
- `#SPCONTROLER`'s `Realize` rows were checked as a candidate per-song calibration factor and ruled out for the reference set specifically - every one of the 30 matched (v10/v12) charts has byte-identical `Realize` payloads. **Correction**: it's not universally fixed - a broader v13 survey (`vox_format.md`'s "Format version 13") found 5/148 charts with a different payload (varying `CAM_Radi`'s overshoot/end values). Rare, and not revisited as a zoom-scale explanation yet, but no longer "always identical" as originally stated.
- **Tilt intervention style varies wildly by song.** Counting `tilt=` events per laser run across the 30 reference charts: 5 songs use **zero** manual tilt lines at all (pure `tilt=normal` throughout - `aim_higher`, `aqua_luna_rium`, `chakra`, `komorebi_ni_saku`, `shiawase_usagi_peko_miko_marin`), while others range from light touch-ups (~0.1-0.6 events/run) to dense hand-animation (up to 7.37 events/run in `furiko_doll/mxm.ksh` - a near-continuous manual reproduction of the tilt curve, not a simple bracket idiom). Per direction, this is a low-priority piece.
- Per direction (zoom accuracy isn't the bar), `camera.py` uses ~140 / ~-125 as central-tendency constants, clearly flagged as approximate.

## Zoom: sign, direction, and the constants used

- `CAM_RotX` correlates **positively** with `zoom_top` (matches vox's "higher = lane top higher on screen" against ksh's rotation description directly, no sign flip).
- `CAM_Radi` correlates **negatively** with `zoom_bottom` - vox's "higher `CAM_Radi`" means more zoomed out, ksh's "higher `zoom_bottom`" means more zoomed in, so a converter must negate.
- `camera.py`'s `ROTX_TO_ZOOM_TOP = 140.0`, `RADI_TO_ZOOM_BOTTOM = -125.0`. Both endpoints of every segment are emitted (not just each segment's start plus a final end - see "Bugs found and fixed" below for why that was wrong), deduplicated where consecutive segments hand off the same value, and spaced apart where they don't - i.e. a same-tick vox snap.

## Tilt: automatic baseline and manual passthrough

**Confirmed by direction**: only 9% of charts carry a manual `Tilt` track (v10/v12 corpus-wide), yet every reference chart is full of `tilt=` lines - so most tilt output is SDVX's own automatic laser-driven tilt (governed by `#TILT MODE INFO`'s 0/1/2 normal/bigger/stay-max mode), computed independently by the arcade engine, not read out of the vox file. **The auto-tilt formula itself is not modelled** - `camera.py` leaves this to ksh's own built-in auto-tilt (`tilt=normal` as the baseline), which is not necessarily identical to the arcade's, but is the closest available approximation without the DLL. Confirmed low priority per direction. Note: manual `Tilt` is far more common in chart-format-13 charts specifically - 36% of a 148-chart v13 sample vs 9% in the v10/v12 corpus, see `vox_format.md`'s "Format version 13" - which shifts how much of a v13 chart's tilt behaviour this passthrough actually covers, without changing the mechanism itself.

`compute_tilt_events` therefore does two things only: emit `tilt=normal` as the baseline, and pass through any manual `Tilt` vox segment as literal floats at each segment's start/end tick (charter-authored camera work, not auto-tilt, so it overrides the baseline outright).

**Pretilt is explicitly not handled, by direction.** KSM's own auto-tilt engine anticipates an upcoming laser and starts tilting before the arcade would - but per direction this is triggered by *any* laser, not some chart-detectable subset of them, which makes it a property of KSM's engine rather than something the `.vox` -> `.ksh` mapping could ever selectively cancel. Earlier work in this project tried to find a triggering condition (a silence-before-laser heuristic, fit from one clean example) and built a test chart to investigate further (`gen_pretilt_test.py` / `pretilt_test.ksh` / `PRETILT_TEST.md`, currently `git stash`ed) - that whole line of investigation is closed: there is no chart-side condition to fix, so the converter doesn't try.

## Spin/swing: kind, direction and length

**Kind mapping - confirmed by direction, and 1353/1354 against the reference set.** Vox's "roll" variants (`roll_type` 1, 2, 3, 4, 6, 7) map to ksh's full spin (`@(`/`@)`); vox's "swing" (`roll_type` 5) maps to ksh's half spin (`@<`/`@>`). `S<`/`S>` (ksh's own dedicated swing token) is never emitted - confirmed unused in every reference chart, including for genuine vox `roll_type=5` swings (charters used half-spin instead), so per direction this converter omits it too.

**Direction - confirmed by direction, 1347/1354 (99.5%) match.** The roll/swing tag sits on the laser point immediately *before* a same-tick slam in every raw example inspected (not after - the direction that matters is the outgoing movement, computed by `_outgoing_dirsign` as the sign of the first position change at or after the tagged point, looking a few points ahead for curve cases). Hypothesis tested: a slam moving right-to-left (`dirsign < 0`) is clockwise -> `@(` (full) or `@<` (half); left-to-right (`dirsign > 0`) is counterclockwise -> `@)` or `@>`. Reported by `correlate.py`'s dedicated hypothesis-match-rate section.

### Length: solved - a ksh spin lasts exactly half the duration vox declares

**One law covers every roll type**: a ksh spin token's length is **half the vox-declared duration**, expressed in ksh 192nds. Since one quarter note is 48 ksh-192nds, that is `24 * (vox length in quarter notes)`. Reproduce the whole derivation with `python correlate.py`, whose "spin length" section prints every step below.

| roll_type | where the vox length comes from | ksh length |
|---|---|---|
| 1, 2, 3, 4, 5 | `C8` quarter notes, or the type's default (`DEFAULT_BEATS` = 6, 2, 3, 12, 3) when `C8=0` | `24 * beats` |
| 6, 7 ("8x speed") | `C8` counts 1/32 notes (= 1/8 quarter note); on format-13 charts the same value lives in `C9` instead | `3 * units` |

**Why half.** `vox_format.md`'s C3 note already says it: vox's lengths "refer to the time the roll takes to *completely* finish, including overshoots — unlike KSM roll lengths, where the overshoot occurs after the specified length". The measurement adds the missing number - the overshoot takes exactly as long as the rotation it follows, so ksh gets half of what vox declares.

**The thing that makes this measurable is controlling for the charter.** The reference conversions are hand-made, and each song's charter picks one scale and holds it across that song - but *different* charters picked different ones. Per song, the modal `ksh_len / C8` is exactly 24 in 282 of 390 songs; the rest sit at 32 (24 songs), 36 (21), 48 (19) and a thin tail. Pooling raw lengths mixes those together and hides the law - which is how an earlier version of this section, working from three `roll_type=1` samples that happened to come from 32-scale songs, concluded `ksh_length = 32 * C8`. **Correction: that constant was fit to a minority-charter subset.** Across all 1354 samples, `24` matches exactly 64.1% of the time and `32` only 16.5%, and the residual is one-sided charter rounding (`x1.333` 16.5%, `x1.5` 5.7%, `x2.0` 4.5%) rather than scatter.

Three independent things confirm 24 rather than a fitted average:

- **Large `C8` values land dead on it.** `C8` of 10, 11, 22, 30, 32, 46 produce ksh lengths of exactly 240, 264, 528, 720, 768, 1104. Nothing is being rounded to a comfortable musical value at that size.
- **`roll_type=6` is transcribed machine-exactly, 61/64.** Its 1/32-note unit puts the factor at `24/8 = 3`, and `C8` of 13, 17, 23, 33, 37 produce ksh `39`, `51`, `69`, `99`, `111` - numbers no charter picks by feel. Type 6 is the cleanest evidence in the whole section, and it is the same law.
- **BPM and time signature are both ruled out.** Regressing ksh length on BPM within a fixed `(roll_type, C8)` gives R² ≈ 0 in every group (the spin is musical time, not wall-clock). Non-4/4 measures fit the same 24 (33/54 exact in 3/4) while a "192 is per *current* measure" alternative fits none of them - so ksh's 192 is a fixed 4/4-measure unit, as `ksh_format.md` implies. Laser-run length doesn't explain the residual either (exact-match rate is flat at 60-74% across every run-length bucket).

**The `C8=0` defaults match `vox_format.md`'s names after all** - `{1:6, 2:2, 3:3, 4:12, 5:3}` quarter notes. **Correction to `vox_format.md`**, which recorded types 2 and 5 as contradicting their names: they don't, and neither do 1 and 3. Restricting to songs whose explicit-`C8` rows measure exactly 24, the implied default is 6.00 (rt1, median of 19), 2.00 (rt2, of 6), 3.00 (rt3, of 17) and 3.00 (rt5, of 93) - each the median *and* the mode. Pooling without that restriction is what made rt1 look like 8 beats and rt3 like 4: songs that only ever use default-length rolls have no explicit rows to measure their scale from, and skew 32-ward.

A **scale-free cross-check** settles it without needing any scale at all, since the charter's factor cancels in a ratio between two types in the same song: rt3/rt5 = 1.000 (median over 14 songs, 9 exact), rt1/rt5 = 2.000 (23 songs, 13 exact), rt1/rt3 = 2.000 (19 songs, 12 exact) - exactly the 6:3:3 the names predict. You can read it straight off the per-song table: `air/exh` defaults to `{rt1:144, rt3:72, rt5:72}` and `air/mxm` to `{rt1:192, rt3:96}` - same song, two difficulties, two different charter scales, identical ratios.

**Type 4 is the one gap.** `12` is its name, not a measurement: the reference set contains a single type-4 sample (`tetoris/mxm`, `C8=3` -> `@)120`, where the law predicts 72), and the corpus holds only 25 type-4 rows in total, 24 of them `C8=0`. KSM has no triple-spin token to transcribe faithfully in the first place, so this may not be recoverable from hand charts at all.

### `roll_type` 6/7 on format 13: `C9` is `C8`, moved

**Correction, twice over.** The earlier reading - `C9` in 1/16-note units, `TYPE6_FALLBACK_UNIT_TO_KSH192=12` - was 4x too long, and the "prefer `C8` whenever present" tie-break was backwards. The v13 length column is the same quantity in the same unit as v12's `C8`; only its position changed. Corpus quantiles `[min, q25, median, q75, max]`, type 6: v12 `C8` = `[5, 12, 15, 25, 135]` (mean 17.7) against v13 `C9` = `[3, 12, 15, 25, 35]` (mean 18.2); type 7: `[5, 7, 15, 25, 32]` (mean 15.7) against `[10, 12, 18, 28, 45]` (mean 20.4, n=16). For contrast, `C9` on types 1-5 in v13 - the genuine "cells per chain" - is `[1, 2, 3, 5, 21]`, a different quantity entirely, which is why `camera.py` reads `C9` as a length only for 6/7.

So `TYPE67_UNIT_TO_KSH192 = 3` applies to both columns, and **the 4 ambiguous v13 rows resolve**: every one carries a `C8` of 1 or 2 (a 3-to-6-tick spin, i.e. nothing) alongside a `C9` of 10-30, squarely in the normal length range - `C8` is vestigial there, so `_spin_length` prefers `C9` outright on v13 rather than "`C8` if present". The version test is what keeps that preference off v12, whose only rows carrying both are one charter's (`littleredridinghood`) real `C8` length of 7-15 next to a genuine cells-per-chain `C9=3`. No corpus row in any version reaches the no-length-anywhere fallback.

**This also closes the loose end** flagged when `C9` was first read as 1/16 notes - that the source described the same roll as lasting "around 2 beats" while the formula produced 8. Under the corrected unit `C9=32` is 32 thirty-second notes = 4 quarter notes declared, halved to 2 beats of visible ksh spin. The original worked example, `track8` measure 79 of `2393_alive_dadadaizu_5m.vox`, now converts to `@(96` - two beats, as described - instead of `@(384`; and the v13 type-7 example `0152_earthquake_super_shock_soundholic_4i.vox` gives `@(60` for `C9=20` instead of `@(240`.

## Bugs found and fixed

1. **Same-tick snap overwrite (both zoom and tilt), analogous to `notes.md` bug #3** ("a same-tick slam landing on a run boundary lost its true endpoint entirely, drawing a diagonal instead of a vertical drop"). A vox camera/tilt segment can be zero-length (`tick == end_tick`) with `start != end` - a genuine instant jump, the same idea as a laser slam. `compute_zoom_events` and `compute_tilt_events` originally wrote `events[tick] = value` per segment into a plain dict; when a zero-length segment shared its tick with the next (or the previous) segment, the later write silently clobbered the earlier one, and the arrival/departure value pair collapsed into whichever value got written last - erasing the peak or trough the snap was there to represent, and drawing a shallow ramp straight through it instead. Confirmed on `2226_gryphone_etia_5m.vox` (flagged by direction as a heavy camera/tilt chart worth checking): `cam_rotx`/`cam_radi` each have 7 zero-length segments sharing a tick with their neighbour, `tilt` has 2. Fixed by routing every track through `_place_track` (`camera.py`), which spaces genuinely distinct same-tick values one grid cell apart instead of overwriting - the same fix shape as the laser one, and for the same reason (ksh has no way to hold two different values on one grid line, so an instant vox transition needs two adjacent ksh ones). Example, `zoom_top`/`zoom_bottom` at the very start of `2226_gryphone_etia_5m.vox` (an initial-framing snap before anything else happens): before the fix, only `zoom_top=-105 zoom_bottom=94` would have survived (jumping straight to the second segment's target, no line for the resting `0, 0` before it, or the diagonal-instead-of-vertical version of it depending on which segment ordered last); after the fix, `zoom_bottom=0`/`zoom_top=0` and `zoom_bottom=94`/`zoom_top=-105` are both emitted, one cell apart.

2. **Dedup dropped the hold-anchor point right before a ramp, collapsing holds into long diagonals.** `_dedupe_consecutive`'s original form kept only the *first* point of a run of consecutive-equal-value ticks and dropped the rest - including the *last* one, which is what stops ksh's linear interpolation from blending a flat hold straight into whatever ramp comes after it. Found by direction on `2226_gryphone_etia_5m.vox` measures 90-93: vox snaps tilt to 1.0, **holds it there for ~335 cells (~7 beats)**, then ramps down to -1.0 over the next 48 cells, holds again for ~288 cells, then ramps to 0 over 96. With only the run's first point kept, the output jumped straight from the snap to a single line at the *ramp's end* value, turning "hold at 100%, then a quick flip to -100%" into one long diagonal spanning the entire hold-plus-ramp duration - exactly what was reported. Fixed by keeping a point whenever it differs from *either* neighbour (i.e. both the first and last point of every same-value run survive; only strictly-interior repeats get dropped) - verified against the raw vox segments directly post-fix: `camera.py` now emits `(17088,'0') (17089,'1') (17424,'1') (17472,'-1') (17760,'-1') (17856,'0') (17857,'normal')` for that span, correctly holding through 17424 and 17760 before each ramp.

**On `scripts/camera/2226_gryphone_etia_5m.ksh`, corrected**: an earlier version of this document called this file "an actual hand-charted reference" and reported a suspicious 100%-exact match against it (tilt 59/59, zoom 54/54, spin 4/4) as validation. That was wrong on inspection - its header is machine-placeholder output (`artist=`, `effect=`, `jacket=`, `illustrator=` all blank; `difficulty=infinite`/`level=1`/`bg=desert`/`layer=arrow` all matching `notes/convert.py`'s own hardcoded defaults exactly; `title=2226_gryphone_etia_5m` matching its `"title=%s" % base_filename` placeholder convention verbatim), i.e. it's prior machine-generated output from some earlier version of a similar converter, not independent ground truth - which is exactly why it agreed with this session's *also-buggy* output on the hold-collapse bug above: both pieces of code made the same mistake. The file is left in place (not this project's to delete) but is no longer treated as a reference anywhere in this document. The only trustworthy validation done was against the vox segment data directly, by hand, per bug 2's writeup.

## Converter status

`scripts/camera/convert.py` produces a complete chart (notes + camera together, via `notes/convert.py`'s `camera=True` path). Smoke-tested on: a plain chart (`1734_777_roughsketch_3e`, output grows from 24585 to 25135 lines, +2.2%, from the extra grid resolution camera anchors require - not a blowup), a manual-`Tilt` chart (`0418_werewolf_howls_camellia_4i`, floats pass through correctly), a `roll_type=7` chart (`0642_sayonara_planet_wars_kuroma_4i`, produces a syntactically valid but unvalidated-length spin token), and a heavy camera/tilt chart (`2226_gryphone_etia_5m`, where both bugs above were found and their fixes verified directly against the raw vox segments - see "Bugs found and fixed"). `notes/xcheck.py` confirmed byte-for-byte unaffected when `camera=False` (the default), so this is additive, not a risk to the existing notes/laser work.

No independent hand-charted reference with heavy camera work has been found yet (the one candidate turned out to be prior machine output - see above), so beyond the raw-vox-segment checks in "Bugs found and fixed," this converter's camera output hasn't been validated against an authoritative outside source. Treat it as "matches the vox data's own structure, by direct inspection," not "verified correct" until one exists.

Known integration gap: spin tokens are placed at the vox roll point's exact tick, but if `laser.py`'s curve decimation (see `specs/notes.md`) drops that exact point when building the ksh laser run, the spin suffix can end up hanging off a `:` continuation character rather than a real laser position character. Not yet checked how often this happens or whether it renders acceptably in KSM.

## Open items

1. **Tilt auto-mode formula** - not modelled; `camera.py` relies on ksh's own built-in auto-tilt as an approximation. Low priority per direction.
2. **Spin length for `roll_type` 4 and 7** - the length law and the type defaults are settled for 1, 2, 3, 5 and 6 (see "Length" above); type 4 has one reference sample that the law misses, and type 7 has none at all and rides on type 6. Both are rare enough (25 and 49 corpus rows) that hand charts may never supply the evidence.
3. **Spin/laser-decimation interaction** - whether a roll point can lose its exact grid line to curve decimation, and what that looks like in the output.
4. Per direction, DLL work (chart reader `FUN_180239810`, the unexamined gameplay-event kinds in `FUN_180407200`) stays the fallback once the above are worth revisiting, not the starting point.

Pretilt is deliberately not on this list - see "Tilt: automatic baseline and manual passthrough" above for why it's considered closed rather than open.
