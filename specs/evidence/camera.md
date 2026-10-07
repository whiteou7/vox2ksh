# Camera evidence

The numbers behind [`../camera.md`](../camera.md). Read this when you need to check a claim there or judge a change against it.

## Corpus facts (8103 charts)

* Formats: 5660 v10, 2443 v12.
* 82% carry `CAM_RotX`/`CAM_Radi`. Only 9% carry manual `Tilt` (36% of a 148-chart v13 sample).
* 81% have at least one roll/swing.
* `Tilt` is in [-1, 1]. `CAM_RotX` reaches 3.9; `CAM_Radi` spans -1.5 to 3.0.
* `roll_type` 7 has 67 rows (v12+). Counts over 8251 charts: type 1 8483, 3 4642, 2 3262, 5 2129, 6 264, 7 67, 4 27.
* `roll_type=6` has 64 reference samples in 27 songs. Type 7 has none.
* `Tilt` node types: 0 mid-series (9267), 1 single (657), 2 series start (1050), 3 series end (1049).

## Reference charts are hand-made

* `zoom_top` slopes cluster around 135 to 160 (140.00 recurs in 5 songs, R² >= 0.999). `zoom_bottom` clusters around -117 to -136.
* `Realize` payloads are identical across the matched v10/v12 charts, but 5 of 148 v13 charts differ. Not tested as a zoom-scale cause.
* Tilt style varies by song: 5 songs use no manual tilt, others up to 7.37 events per laser run (`furiko_doll/mxm`).

## Tilt sign and magnitude

Of 4252 non-trivial matched samples, 98.9% have opposite signs in vox and ksh. Pooled regression gives `ksh = -1.5681 * vox` (R² 0.911, n=6520).

Per-song modal `ksh/vox` ratios: -1.5 (56 songs), -2.0 (16), -2.4 to -2.5 (9), beyond (3), -1.0 (1), about 0 (4). `#TILT MODE INFO` is ruled out as the cause.

## Pretilt: what the reference charters do

Over 1238 reference conversions. This was throwaway analysis with no script in the repo.

* 87.9% of 8067 `zero`/`0` to auto restorations land on a laser section start, against 13.6% for the same events shifted one beat (6.5x enrichment).
* The flat region before the restore has a median of 3 beats (modes 3.0, 2.0, 1.0, 4.0). The flattening end sits on a previous laser's edge: 15.2% on a laser start, 42.3% within a quarter beat of a laser end.
* `tilt=zero` is used in 807 charts, `tilt=0` in 486, manual floats in 407, `keep_*` in 38. 5 charts drive tilt entirely from manual floats, which suppresses auto-tilt.
* Of 64577 section starts after an idle lane, 25.6% are flattened. Centre-opening slams get it 49.5% of the time, home-edge openings with no slam 12.8%. Run-up note density raises it from 12.4% to 30.0%.
* Example: `yukibare_parade/mxm.ksh` measures 15 to 16.
* ksh option lines don't take a grid slot. Assigning ticks by line index drops the onset-alignment result from 87.9% to 2.4%.

## Pretilt: converter measurements

* The first version sized brackets in 192nds and made fifth-of-a-beat brackets on a 480-tick chart. Lengths are now quarter notes times the chart's `tl.res`.
* On 400 random charts, 47.8% get at least one bracket (mean 2.7, max 24) with no invariant violations. With the flag off, output is byte-identical to before.

## Spin: DLL lambdas

| lambda | types | angle (degrees) |
|---|---|---|
| `FUN_1803a6190` | 1, 2, 3, 6 | `d*840*u` while `u < 3/7`, then `d*52.5*sin(7.6969*(u-3/7))*(4/7-(u-3/7))` |
| `FUN_1803a64d0` | 4 | `d*1440*u` while `u < 3/4`, then `d*120*sin(17.5929*(u-3/4))*(1/4-(u-3/4))` |
| `FUN_1803a6350` | 5, 7 | `d*80*sin(2.1*pi*u)*(1-u)` |

`d` is +-1 and `u` is progress. A swing peaks near 61 degrees at `u = 0.238`. The path was found by scanning for the laser record's field offsets (`+0x1c` tick, `+0x2c` node type, `+0x30` roll type, `+0x38` width, `+0x40` curve type, `+0x48` roll length) and following `roll_type` forward.

| vox type | default (length 0) | unit | previously |
|---|---|---|---|
| 1 | 7 beats | 1 beat | 6 |
| 2 | 2 beats | 1 beat | same |
| 3 | 3 beats | 1 beat | same |
| 4 | 12 beats | 1 beat | same |
| 5 | 3 beats | 1 beat | same |
| 6 | 7 (unreachable) | 1/10 beat | 1/8 beat |
| 7 | 3 (unreachable) | 1/10 beat | 1/8 beat |

## Spin: type 4 rows

| chart | C8 | D | token |
|---|---|---|---|
| `2216_tetoris_hiiragimagnetite_5m` | 3 | 3 beats | `@)144` |
| `0271_vallis_djyoshitaka_4i` | 7 | 7 beats | `@)336` |
| `1751_april2021_grace_5m` | 8 | 8 beats | `@)384` |
| `0704_flower_djyoshitaka_4i` | 0 | 12 beats | `@)576` |
| `2392_dementafterlegend_cosmograph_5m` | 3 | 3 beats | `@(144` |

All 27 type-4 rows in the corpus (including the update folder) have a token ending on the tick their ramp ends. 1 of 27 has a manual `Tilt` point inside the ramp: `2392_dementafterlegend_cosmograph_5m` (v13), a `0.0 -> 0.0` block, which the ramp clears.

The lone reference type-4 sample, `tetoris/mxm` with C8=3, is a single `@)120` where the old law predicted 72.

Over 8107 charts after the type-4 and type-7 changes: 8045 unchanged, 25 change spin and tilt (type 4), 35 change spin token only (type 7). 2 charts fail to parse, unrelated.

## Spin: the length law

Per song, the modal `ksh_len / C8` is exactly 24 in 282 of 390 songs, then 32 (24 songs), 36 (21), 48 (19). Across 1354 samples, 24 matches 64.1% exactly and 32 only 16.5%; the residual is one-sided charter rounding (x1.333 16.5%, x1.5 5.7%, x2.0 4.5%). An earlier version said 32, fit to a minority-charter subset.

* Large lengths land exactly: C8 of 10, 11, 22, 30, 32, 46 give 240, 264, 528, 720, 768, 1104.
* Type 6 matches 61/64, and C8 of 13, 17, 23, 33, 37 give 39, 51, 69, 99, 111.
* BPM has R² of about 0 against ksh length. In 3/4, 33/54 match 24 exactly and a per-measure 192 matches none. Laser-run length doesn't explain the residual (exact-match rate is flat at 60 to 74% across run-length buckets).
* Defaults, from songs with exact 24-scale rows: 6.00 (type 1, 19 songs), 2.00 (type 2, 6), 3.00 (type 3, 17), 3.00 (type 5, 93).
* Scale-free ratios within a song: type3/type5 = 1.000 (14 songs), type1/type5 = 2.000 (23), type1/type3 = 2.000 (19). `air/exh` defaults to `{rt1:144, rt3:72, rt5:72}` and `air/mxm` to `{rt1:192, rt3:96}`: same song, different charter scales, same ratios.

## Spin: three scales that disagree

* 24: 1354 hand samples.
* 20.6: SDVX rotation time at face value (3/7 of the declared duration against KSM's 0.5333).
* 38.6: rotation-rate match against ksm-v2 (`(3/7)/(360/675) * declared = 0.804 * declared`), but the charters used v1.6x.

## Which column holds the length

* The chart reader (`FUN_18023baa0`, laser loop at `0x18023d470`) has three branches (`< 12`, `== 12`, `>= 13`). They differ in whether position is an int or float, and in whether the 8th column goes to a v13-only field (`+0x34`) and pushes length and cells-per-chain one slot along.
* The length field (`+0x38`) is fed from `C8` in v10/v12 and `C9` in v13.
* The column never nonzero on a non-roll row: `C8` in v10/v12 (0 of 2,861,916 rows), `C9` in v13 (0 of 93,086). `survey_camera.py --lasercols` prints it.
* v13's `C9` per type matches v12's `C8`: type 1 `[1,1,2,4,46]` mean 3.6 against `[1,2,3,5,21]` mean 4.1.
* The 23 v13 rows with both columns are unambiguous: `C8` is the v13-only flag (0, 1 or 2 across 93,574 rows).
* Example: `2393_alive_dadadaizu_5m` measure 115, `C9=15`, should be `@)360` and was `@)144`. `C9=32` on its track8 measure 79 gives `@(96`.
* None of the 148 v13 charts (a 2026 update) has hand-chart coverage, so the v13 length unit is inherited.

## `roll_type` 6 and 7 samples

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

`survey_camera.py --locate 6,7 --root <update folder>/data/music` regenerates the full 331-row list.

## Bugs found and fixed

1. Zero-length vox segments (`tick == end_tick`, `start != end`) are instant jumps. `compute_zoom_events` and `compute_tilt_events` wrote `events[tick] = value`, so a neighbour sharing the tick overwrote it. `2226_gryphone_etia_5m` has 7 such segments each in `cam_rotx`/`cam_radi` and 2 in `tilt`. Now `_place_track` puts distinct same-tick values one cell apart.
2. Dedup kept only the first point of a same-value run, so a hold before a ramp collapsed into a long diagonal (`2226_gryphone_etia_5m` measures 90 to 93: hold at 1.0 for about 335 cells, then ramp to -1.0). Now both the first and last point of each run survive. Correct output: `(17088,'0') (17089,'1') (17424,'1') (17472,'-1') (17760,'-1') (17856,'0') (17857,'normal')`.

`scripts/camera/2226_gryphone_etia_5m.ksh` is not a reference. An earlier version called it hand-charted and cited a 100% match, but its header is placeholder output from a similar converter, so it shared the bug.

## Smoke tests

`convert_camera.py` produces notes plus camera. Tested on `1734_777_roughsketch_3e` (+2.2% lines), a manual-`Tilt` chart (`0418_werewolf_howls_camellia_4i`, vox `-0.500` gives `tilt=0.5`), type 7 (`0642_sayonara_planet_wars_kuroma_4i`), type 4 (`2216_tetoris_hiiragimagnetite_5m`, `2392_dementafterlegend_cosmograph_5m`) and `2226_gryphone_etia_5m`. With `camera=False` (the default) the output is unchanged, as `notes-refcheck` confirms byte for byte.

## Moved from the spec

* Spin kind: rolls (`roll_type` 1, 2, 3, 4, 6, 7) to the full spin and swing (5) to the half spin matches 1353 of 1354 reference samples.
* Spin direction: the sign of the next position change matches 99.5% of samples.
* Length scale: 24 matches 64.1% of 1354 samples exactly. An earlier version said 32, fitted to a minority-charter subset.
