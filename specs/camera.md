# The camera element

**Status: converter exists (`scripts/camera/convert.py`); zoom and spin are on reasonably solid ground.** Scope, tools, and findings below. Nothing here has been checked against the DLL, per direction: settle what the manual reference conversions and direct domain knowledge can tell us first, fall back to the DLL only once that's exhausted.

**Pretilt is out of scope, by direction.** "Pretilt" is KSM anticipating an upcoming laser and starting to tilt before the arcade would - a behaviour embedded in KSM's own engine, triggered by any laser at all, not something specific to a subset of charts or a condition the chart data expresses. It's a game-engine problem, not a `.vox` -> `.ksh` mapping problem, so this converter does not attempt to cancel or otherwise reproduce/undo it - see "Tilt: automatic baseline and manual passthrough" below.

Scope: lane tilt, spin/swing and top/bottom zoom - the `.vox` tracks that move the playfield rather than the notes on it. Explicitly out of scope for this pass (KSMv2-only, or not expressible pre-v2): `zoom_side`, `center_split`, `rotation_deg`, `scroll_speed`, and the `*_curve` interpolation options. `zoom_side` usage was checked directly: zero occurrences across every file in `scripts/shared/reference/ksh`.

## What makes this element different

Audio and notes were both *transcription* problems: the game does something exact, and the job was to read it out of the binary. Camera turned out to be a mapping problem in a stronger sense than expected - see [Reference charts are hand-made, not derived](#reference-charts-are-hand-made-not-derived). Document the lossy/uncertain parts explicitly; a converter that silently discards or fabricates camera data is worse than one that says what it doesn't know. Per direction, exact accuracy on the zoom scale factor and the spin length formula isn't the bar here - a reasonable, documented approximation is fine; the goal is a converter that does something sensible everywhere and is honest about where it's guessing.

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

Neither occurs in any of the 30 matched reference charts, so there's no hand-chart comparison for them - the constants used for them in `camera.py` are extrapolated, not fitted. Regenerate the full 251-row list with `python survey.py --locate 6,7`. A sample (chart, side, position `measure,beat,cell` 1-indexed, `C8` length):

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

## Spin/swing: kind and direction solid, length approximate

**Kind mapping - confirmed by direction, 100% match against the reference set (49/49 + 17/17).** Vox's "roll" variants (`roll_type` 1, 2, 3, 4, 6, 7) map to ksh's full spin (`@(`/`@)`); vox's "swing" (`roll_type` 5) maps to ksh's half spin (`@<`/`@>`). `S<`/`S>` (ksh's own dedicated swing token) is never emitted - confirmed unused in every reference chart, including for genuine vox `roll_type=5` swings (charters used half-spin instead), so per direction this converter omits it too.

**Direction - confirmed by direction, 66/66 (100%) match.** The roll/swing tag sits on the laser point immediately *before* a same-tick slam in every raw example inspected (not after - the direction that matters is the outgoing movement, computed by `_outgoing_dirsign` as the sign of the first position change at or after the tagged point, looking a few points ahead for curve cases). Hypothesis tested: a slam moving right-to-left (`dirsign < 0`) is clockwise -> `@(` (full) or `@<` (half); left-to-right (`dirsign > 0`) is counterclockwise -> `@)` or `@>`. **66/66 matched tokens in the reference set agree with this rule exactly**, via `correlate.py`'s dedicated hypothesis-match-rate report.

**Length - approximate, not fully solved.** Fit against `roll_type=1` samples with an explicit `C8` (vox's roll-length column): `C8` values of 3, 6, and 9 landed on ksh lengths of exactly 96, 192, and 288 - i.e. `ksh_length = 32 * C8` fits those three exactly. That same constant (32 ksh-192nds per vox "beat" unit) reproduces `roll_type=1`'s default (`C8=0`) length of 192 if its named "6-beat" duration is substituted (`6*32=192`, matching the observed default), and `roll_type=3`'s "3-beat" default of 96 (`3*32=96`, also matching observed data) - **but not** `roll_type=2`'s "2-beat" default (72 observed vs 64 predicted) or `roll_type=5`/swing's default (72-96 observed, no clean fit, and checked against song BPM with no correlation found either). `camera.py` uses `BEAT_TO_KSH192=32` uniformly with a `DEFAULT_BEATS` table (`{1:6, 2:2, 3:3, 4:12, 5:3}`) taken from `vox_format.md`'s own naming, which is therefore known to be off for types 2 and 5's defaults specifically. `roll_type=6` uses a different documented unit (1/32 notes, not beats) -> `TYPE6_UNIT_TO_KSH192=6`; `roll_type=7` (undocumented) falls back to the generic beat formula with no reference-set validation at all - see the locations list above if this needs checking against actual footage.

**`roll_type=6`/`7`'s `C9` fallback when `C8=0` - originally found on one chart, since generalized and corrected twice.** `2393_alive_dadadaizu` (the chart this was first found on) turned out to be vox format 13, not 12 - see `vox_format.md`'s "Format version 13" section for the full survey, including a follow-up that checked whether this was really 6/7-specific.

That follow-up found the picture is more precise than first reported: **`C8=0` in v13 is not specific to types 6/7 at all** - it's near-universal for every `roll_type` (96-100% of rows in the 148-chart sample, types 1 through 7 alike), since it already meant "use the type's default length" pre-v13 (see `vox_format.md`) and v13 charts just lean on that default far more. What *does* distinguish 6/7 is `C9`'s magnitude when `C8=0`: small (mean ≈4.3) for types 1-5, consistently and substantially larger (mean ≈17.4) for types 6/7 - confirmed **within the same chart** in 31 of 33 v13 files that have both, ruling out a cross-song artifact. That size gap is the actual evidence for reading `C9` as length specifically for 6/7, not the mere presence of `C8=0` (which happens for every type and means nothing on its own).

`camera.py` uses `C9` in **1/16-note units** (`TYPE6_FALLBACK_UNIT_TO_KSH192=12`, i.e. `192/16`) for `roll_type` 6 or 7 when `C8` is falsy and `C9` is populated; falls back to a length-1 (near-zero) token, same as before, when neither is available. Verified on the original example: `track8` measure 79 of `2393_alive_dadadaizu_5m.vox` (a laser starting at 0.875, same-tick slam to 0.125, tagged `roll_type=6`, `C9=32`) converts to `@(384` (32*12, exactly 2 measures) at the correct tick. One loose end, not yet resolved: the "1/16 note" unit was stated alongside "lasts around 2 beats", but 32 sixteenth-notes is 8 beats (2 measures), not 2 - either "beats" was meant as "measures", or the unit isn't quite 1/16.

**Bug found and fixed in the same pass**: the `C9` fallback was originally written for `roll_type==6` only, since the chart that surfaced it happened to only exercise type 6. Once the follow-up survey confirmed type 7 shows the identical `C8=0`/large-`C9` pattern, type-7 rows with `C8=0` were found silently falling through to a generic 3-beat guess (the same placeholder default other, unrelated roll types use) instead of the `C9` fallback. Fixed - both types now take the same path. Verified against a real v13 type-7 example (`0152_earthquake_super_shock_soundholic_4i.vox`, `C9=20` -> `@(240`, matching `20*12`).

Still unresolved: the 4/80 v13 rows with a small nonzero `C8` (1 or 2) alongside a populated `C9` - not enough signal to tell whether `C8` still matters there or is vestigial, so `camera.py` still prefers `C8` when present at all (`if p.roll_length:`), for both v10/v12's genuine explicit-length case and this ambiguous v13 minority.

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
2. **Spin length for `roll_type` 2, 5, 6, 7** - `roll_type=1`/`3`'s explicit-`C8` and default formulas are solid; the others are extrapolated/unvalidated. `roll_type=5`'s default doesn't correlate with BPM either (checked directly, no pattern found).
3. **Spin/laser-decimation interaction** - whether a roll point can lose its exact grid line to curve decimation, and what that looks like in the output.
4. Per direction, DLL work (chart reader `FUN_180239810`, the unexamined gameplay-event kinds in `FUN_180407200`) stays the fallback once the above are worth revisiting, not the starting point.

Pretilt is deliberately not on this list - see "Tilt: automatic baseline and manual passthrough" above for why it's considered closed rather than open.
