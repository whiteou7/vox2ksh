# Audio engine evidence

The measurements behind [`../audio_engine.md`](../audio_engine.md), moved out verbatim. Read this when you need to check a claim there or judge a change against it.

## 4.1 Truncating feedback, measured

Measured over 40 (chart, capture) pairs, `-b 512`: the two hyena windows improve +1.23 dB each (3.712 to 2.478, 3.924 to 2.702) and clipped samples fall 110 to 6. Corpus-wide it's small: laser region +0.008 (10 up, 2 down), FX HighPassFilter +0.119 (carried by `aimai_chocolate` 5m), ALL +0.004, other effects unchanged within 0.004. `check_all_charts.py` can't see the laser row (§ audio-refcheck skill).

## 4.1b Resonance damping, measured

Measured on frames with a live Q >= 3 tab filter (5 pairs, 4842 frames):

| setting | gain vs dry | Q3 becomes | Q5 becomes |
|---|---|---|---|
| scale 1.0 (authentic) | +2.794 | +9.5 dB | +14.0 dB |
| scale 0.5 | +2.654 | +4.8 | +7.0 |
| scale 0.0 | +2.191 | 0 | 0 |
| max-resonance off (authentic) | +2.794 | +9.5 | +14.0 |
| max 12 dB | +2.801 | +9.5 | +12.0 |
| max 9 dB | +2.733 | +9.0 | +9.0 |
| max 6 dB (CLI default) | +2.637 | +6.0 | +6.0 |
| max 3 dB | +2.453 | +3.0 | +3.0 |

## 5.1 Same-section handoffs, measured

Rare: 18 pairs against 584760 genuine ones across 8254 charts, in `2397_ultracharge_yutaimai_5m` (12), `2385_cyanotype_synthion_5m` (4), `0697_syousitsu_cosmo_4i` (1), `2088_xinca_tonarinoniwa_5m` (1), plus 2 in `2406_saihate_namv_5m` (not in this install; user-reported, measures 9 and 10). Each is a loud noise on a downbeat. On `2088_xinca_tonarinoniwa` MXM at 35.74 s, the render's error over 0.4 s falls from 5.584 to 3.158 dB with the guard (gain over dry +1.723 to +4.149; over 0.8 s, 4.245 to 2.858). Control windows move 0.000. The cabinet plays no slam sound at a `2`/`1` handoff.

## 5.3b Beat column fix, measured

Over the 34 (chart, capture) pairs (of 645) with a non-`/4` measure, every effect improves, 84 chart-rows up and 4 down:

| effect | before | after | delta | up/down |
|---|---|---|---|---|
| PitchShift | +2.137 | +2.137 | 0 | 0/0 |
| HighPassFilter | +5.254 | +5.407 | +0.153 | 1/0 |
| SideChain | +2.612 | +3.104 | +0.492 | 6/1 |
| Flanger | +0.901 | +1.401 | +0.500 | 13/0 |
| Wobble | +1.518 | +2.045 | +0.526 | 10/1 |
| Echo | +2.111 | +2.781 | +0.670 | 11/0 |
| Retrigger | +1.917 | +2.595 | +0.678 | 4/1 |
| BitCrusher | +1.439 | +2.119 | +0.680 | 17/0 |
| Gate | +2.099 | +2.993 | +0.895 | 13/0 |
| TapeStop | +3.271 | +4.350 | +1.079 | 7/0 |
| PitchSpeed | +2.388 | +4.056 | +1.668 | 2/0 |

Several effects went from negative to positive, which marks a region in the wrong place rather than wrong coefficients: Gate on `re_call/mxm` -2.198 to +3.536 (367 frames), Tape Stop on `extridia/mxm` -3.478 to +4.881, Wobble on `extridia/mxm` -1.745 to +2.813. All four regressions are on `spear_of_justice/mxm` (SideChain -0.937, Retrigger -0.148), both already negative; one chart against 84 is not a finding.

## 6.1.2 Loudness of the SE samples

The samples differ in loudness themselves:

| idx | name | dur | peak | dBFS | loudest 300 ms RMS |
|---|---|---|---|---|---|
| 0 | `fs00_virtical_se01` (slam) | 1.78 s | 17446 | -5.5 | 5341 |
| 1 | `fs01_virtical_se02` | 3.03 s | 10386 | -10.0 | 4002 |
| 2 | `fs02_shot01` | 1.73 s | 28765 | -1.1 | 9256 |
| 3 | `fs03_shot02` | 0.78 s | 32767 | 0.0 | 8179 |
| 9 | `fs09_shot08` | 2.90 s | 32768 | 0.0 | 11057 |
| 10 | `fs10_shot09` | 1.31 s | 32768 | 0.0 | 9682 |
| 14 | `fs14_shot13` | 6.10 s | 23029 | -3.1 | 4307 |

That spread is authentic. Each sample also has an authored header gain (6.1.4).

## 6.1.4 Slam gain sweep

**It doesn't fully agree with the capture.** Sweeping the slam gain with chips pinned at 0.2239:

```
slam gain   0.40   0.45   0.50   0.5513   0.60   0.65   0.70   0.78
score       1.943  1.897  1.858  1.826    1.807  1.797  1.797  1.816
```

The optimum is about 0.69, 2 dB above the header. It's not a metric artefact: scoring only the 1187 frames a slam is sounding in, with the level offset taken far from any slam, gives the same answer. Chips are unmeasurable on this chart.

## 7 Score by render stage

| render | all | FX | peak-laser | tab-laser | idle |
|---|---|---|---|---|---|
| untouched | 3.169 | 4.808 | 4.247 | 5.557 | 1.221 |
| effects only, no SE | 2.934 | | | | |
| + layered SE | 2.380 | | | | |
| + peak filter, fitted (old) | 2.310 | 3.123 | 3.011 | 2.788 | 1.137 |
| effects + peak, no SE | 2.500 | | | | |
| + peak filter, transcribed (7.1) | 1.924 | 2.583 | 2.127 | 2.698 | 1.362 |
| + one voice per SE sample (6.1.3) | 1.799 | 2.520 | 1.929 | 2.320 | 1.327 |

Everything adopted since (§4.9 Wobble rate, §4.6b Tape Stop Ex, §6.3 sweep) leaves kamui at 1.808, against 3.169 untouched and a 1.14 floor. Idle worsens in the last rows only because the metric matches one global level offset and the duck lowers 62% of the track.

## 7.1 Predictions confirmed by the capture

Three predictions are confirmed by the capture:

| prediction | test | result |
|---|---|---|
| 80 ms queue delay | sweep `--peak-delay` | minimum at 0.08 s (0.06: 2.088, 0.08: 1.924, 0.10: 2.155) |
| `event+0x10 != 0` mutes the EQ | `--peak-always` | tab-laser 2.787 to 3.820; peak-laser unchanged. That field is the C4 effect index |
| the duck exists | `--no-duck` | 1.924 to 2.195 |

## 7.2 SE level sweeps

Sweeping slam gain against the corrected baseline:

```
slam gain   0.40   0.55   0.60   0.65   0.70   0.80   1.00
score       1.943  1.827  1.807  1.797  1.798  1.825  1.940
```

0.65 is optimal, flat to 0.70, and only meaningful with the one-voice rule (6.1.3): while overlapping copies could sum, the fit was 0.5. Sweeping the trim:

```
--se-trim   0.80   0.90   1.00   1.10   1.25   1.40
score       1.905  1.861  1.826  1.805  1.796  1.813
```

1.00 is what the files say; the minimum is 1.25 (+1.9 dB). Whatever explains that (6.1.4) should bring this back to 1.0. `virtical_shot[0]` scores 1.924 against `virtical_shot[1]`'s 2.366 and 2.500 with no SE.

## 8.1 Chain, dry and add

A laser reads what the FX buttons wrote: no disagreement. Measured over the 20 charts with most overlap, scoring overlap frames:

```
16 charts, 4656 overlap frames:
  chain  mean +2.706  frame-weighted +2.696  wins 13/16
  dry    mean +2.096  frame-weighted +2.098  wins  3/16
  add    mean +0.895  frame-weighted +0.978  wins  0/16
```

The three charts preferring `dry` do so by 0.1 to 0.5 dB, inside the spread; `add` is out. The independent reimplementation also reads `chain` (9.1).

## 8.1 FX-L and FX-R overlap

Not an edge case: across 8255 charts, FX-L and FX-R overlap on 18776 same-pair and 9664 different-pair holds. The exposing case is `2337_recipinoriddle_oster` 5m, m114 b4, where both buttons hold the same Wobble + PitchSpeed pair for a bar. Chained, the 4 to 8 kHz band sits 11 dB below the capture with modulation depth 0.083 (capture 0.165). Reading dry per note puts the band within 0.8 dB at depth 0.192, and improves every scored region: Wobble +0.301 to +0.592, PitchSpeed +0.461 to +0.697, Tape Stop Ex +3.204 to +3.552. `--fx-chain-overlap` restores chaining.

## 9.3 and 9.4 Cross-check scores

Each was A/B'd on the frames it could affect, and each stays behind a flag:

| | mean(base) | mean(alt) | delta | frame-wtd | result (16 charts each) |
|---|---|---|---|---|---|
| Gate hard-binary | +3.427 | +1.975 | -1.452 | -1.474 | ours, 16/16 |
| BitCrusher continuous | +2.476 | +1.894 | -0.582 | -0.513 | ours, 16/16 |
| Tape Stop Ex 3-phase | +2.908 | +2.800 | -0.108 | -0.082 | ours (8 up / 6 down / 2 tied) |
| Laser C7 easing | +1.744 | +1.743 | -0.001 | -0.001 | no difference |
| Sample domain (float) | +0.956 | +0.955 | 0 | 0 | no difference |
| Param-assign sweep | +0.454 | +1.152 | +0.698 | +0.445 | adopted, 5 up / 3 down / 8 unaffected |

* Gate's step table and BitCrusher's block-realigned grid win decisively. Both are direct transcriptions here against untraced simplifications there.
* Tape Stop Ex's three-phase model (attack, hold, release against preroll, spin-up) is inconclusive: 8 of 16 prefer it, 6 prefer ours, swings up to 3 to 5 dB. It was the leading idea for the floor mystery (4.6b) and didn't resolve it. `--tapestop-ex-3phase` stays for anyone digging.
* The param-assign sweep is the one real adoption beyond Wobble. On charts where AUTO TAB overlaps an active C4=6 laser it beats static parameters on 5 of 8 charts that change at all. Wins are large (+5.165, +3.517, +2.617), losses smaller (-1.600, -1.053, -0.459).
* Laser easing and sample domain make no measurable difference. The float flag changes output (up to 61295 raw-sample magnitude on `2229_kamui`) but not the spectral metric. Int16 stage-clipping stays on, knob stays linear.

### 9.4 Head-to-head

Same charts, audio, recording, alignment and metric. `gain = dry - render`. Theirs ran with `--no-knob --no-shot`; ours with `--no-se` (like for like) and default.

```
12 charts, whole-track ALL frames
              mean     median
theirs       +0.122   +0.217
ours --no-se +0.351   +0.435     effects-only: ours ahead on  9/12 charts
ours full    +0.837   +0.889     full mix    : ours ahead on 11/12 charts
```

Charts were picked by alignment correlation, which favours charts that differ little from dry (`1849_sasoribi_virkato` scores +0.003 for all three), compressing every number toward zero. The full-mix row includes the SE bank, header gains and duck, which theirs doesn't attempt. On effect rendering alone, ours is ahead by about 0.23 dB mean and wins 9 of 12.

## Moved from the spec

Details that used to sit in `../audio_engine.md` next to the rules they support.

### 3 Peak-filter prevalence

On `2229_kamui` MXM, 870 of 894 VOL-L nodes are C4=0.

### 4.1 Feedback truncation: mechanism

An earlier `fx_dsp.py` truncated the feedback to int16 on every sample. At low cutoffs the poles sit within 1e-3 of the unit circle (9.5e-4 at 40 Hz), so a +-1 LSB error set off a limit cycle. On `0381_hyena_hommarju` 4i (tab HPF 40 to 2000 Hz, Q 3, at m10 beat 2 and m12 beat 2), a 40 Hz HPF produced +8.3 dB at 250 to 700 Hz and 57 clipped samples, where the capture is flat. The problem disappears by 200 Hz, which is why it showed up in only two laser runs. The device ParamEq shares the recursion (centre clamped to [80, 16000]) and was hit less. Removing the truncation improved the two bad hyena laser runs by about 1.2 dB each and cut clipped samples from 110 to 6.

### 4.1b Q prevalence and cap cost

Of 32430 LPF/HPF definitions in `#TAB EFFECT INFO`, 52.2% have Q > 2, nearly all on two presets: Q=3.0 (25.9%, +9.5 dB peak) and Q=5.0 (25.8%, +14.0 dB). Q=0.7 (47.6%) has no peak. FX-button filters (2474 definitions) are 38% above Q 2. Wobble is 94.8% Q=1.4 (+2.9 dB). Both damping controls were scored on frames with a live Q >= 3 tab filter, and every step down from the authored value scored worse. The 6 dB default cap costs 0.157 dB on the frames it touches (ALL +0.918 to +0.901).

### 4.3 and 4.5 Transcription against simplification

A continuous BitCrusher hold grid scores 0.582 dB worse than the block-realigned one on 16 of 16 charts. A hard `1.0/0.0` gate scores 1.452 dB worse than the `{32, 4}` table on 16 of 16 charts.

### 4.6b Tape Stop Ex

* Only 27 reference-matched charts have a note that reaches the active branch (spans 0.14 to 2.7 s). `1954_treajourney_chubay` has ten id-10 notes and fires on none.
* On 13 capture-matched charts that fire (499 frames), implementing it gives +2.2 dB. 12 of 13 improve, none get worse.
* Floor sweep: 0.0 costs 1.3 dB, between 0.4 and 0.75 the spread is 0.08 dB with per-chart curves in opposite directions, and `floor = 1.0` is 0.19 dB behind. 0.5 ships.

### 4.9 Wobble

* Reading C6 as cycles per beat improves 13 of 13 capture-matched charts, +0.077 to +0.955 dB mean exclusive over 3247 frames. The independent reimplementation's version of the same change gave +0.878 dB.
* LFO restart: on `2337_recipinoriddle_oster` 5m at m114 b4, a persisted phase scores 3.671 against the capture and a per-note restart 1.877 (dry 4.456), and the restart reproduces the capture's 3 to 15 kHz modulation profile.
* BitCrusher and Gate state is not threaded across notes. They score +2.3 and +3.2 as they are.
* Clamp: the chart asks for 61 ms, the clamp gives 100 ms, and modulation peaks at 10.0 Hz, not 16.3.

### 4.10 Pitch Shift

Over 8 capture-matched charts with scorable regions: +0.983 to +1.929 dB exclusive, delta +0.946 (+1.057 frame-weighted), 7 up, 0 down, other effects flat within 0.002. The reference set has 61 FX-button Pitch Shift notes in 12 capture-matched charts, longest 2.82 s. The accelerating-cursor reading scores -0.815 dB against the per-pass hop on the same 8 charts.

### 5.1 Slam sections

* On `2229_kamui` at 50.571 s the knob slams 127 to 0 on an HPF (40 to 2000 Hz, Q 3) and the 60 to 400 Hz band jumps 28x within 100 ms.
* Collapsing a section to one filter misplaces the slam over 18 s of audio on `2229_kamui`.
* Handoffs: 18 pairs against 584760 real ones, in 5 charts. On `2088_xinca_tonarinoniwa` MXM the guard takes the error over the 0.4 s the phantom SE covers from 5.584 to 3.158 dB.

### 5.2 Grid snap

Over the 14 best-aligned charts with off-grid Retrigger notes, snapping wins 14/14, mean +0.882 dB on exclusive frames, smallest margin +0.210.

### 5.3 and 5.3b Beat resolution and beat column

* `#BEAT RESOLUTION`: 48 (absent) in 8088 charts, 144 in 1, 240 in 10, 480 in 8. `1972_guinevere_penoreri` scored -6 to -10 dB on Echo, Flanger, Gate, SideChain and HPF with good alignment (corr 0.607) before `Timeline` read the tag.
* Beat column: `2152_nemsysarena_tonarinoniwa_3e` measure 55 (12/16) addresses beat 12 at true offset 132, and the old reading gave 528 in a 144-cell measure. 501 of 8254 charts have a non-`/4` signature, 416 place events where this moves, and 47,156 timing rows were pushed outside their own measure. On the 7751 `/4` charts it's a no-op.

### 6 Worked example

`2229_kamui_tjhangneil` MXM, 210 BPM, 153.1 s, 12 FX definitions and 5 laser definitions. FX buttons: Echo x28, Flanger x22, Gate x11, BitCrusher x11, Wobble x10, TapeStop x8, HPF x7, Retrigger x1. Lasers: LPF x6, BitCrusher x4, HPF x2 (C4=1..5), and 57 peak-filter runs (C4=0). Device EQ is active 67.2 s of 153.1 s with the knob reaching 127. Layered SE: 138 laser slams and 3 sampled FX chips. 110 of 111 FX-L chips are 0, and 3 of 228 chips are sampled.

### 6.1.3 Slam onsets

On `2229_kamui` MXM, 138 slam points make 124 distinct onsets (14 are VOL-L and VOL-R slamming together, one Play). The median gap is 0.429 s (min 0.000, max 13.286). Layering scores 1.889 and one-voice restart scores 1.858.

### 6.1.4 Slam gain

The best-fit slam gain is about 0.69 against the header's 0.5513. Freezing the duck between lasers (`--duck-hold`) costs 0.34. The slam peaks at -5.5 dBFS (table under 6.1.2).

### 4.10 Pitch Shift source cursor

At the pass tail `0x180643472` (`lea esi, [rsi + r12*2]`), `r12` looks like a running total of hops, which would accelerate the cursor through a held note. Rendered that way, +12 semitones collapses to near-silence, so the spec uses the per-pass hop. The likely explanation is a misattribution of which spilled stack slot `r12` reloads from across the vectorized tail, unproven. `--pitchshift-legacy-cursor` renders the accelerating reading.

### 6.1.1 Kind-6 producer search

The kind-6 vector arrives as `Update`'s second argument. Field-store scans and vtable xrefs didn't reach its producer; `FUN_18041c220` constructs the object at `world+0xb8`.

### 6.1.4 SE gap: ruled out

A per-bank level (`FUN_1805c63b0` takes no gain, and registration passes only ids and paths); a duck that rests below unity (`0x1805c7b3d` loads `1.0` when the knob is under 4); freezing the duck between lasers (`--duck-hold`); additive layering (worse at any gain); another module owning the mixer (`S3P0`, `S3V0` and `2DX9` appear only in `soundvoltex.dll`). The metric sees only the SE:music ratio, so a constant x0.8 on the music path would also explain the gap.

### 6.3 AUTO TAB and PARAM ASSIGN

* Gain from applying them: +1.07 dB (AUTO TAB) and +0.698 dB (param-assign sweep).
* Usage over 8107 charts: AUTO TAB non-empty in 2738 (33.8%); PARAM ASSIGN present (24 rows) in every chart but only 431 (5.3%) have nonzero C1 to C3; `#TRACK ORIGINAL L/R` non-empty in 2488 (30.7%).
* Across 2128 AUTO TAB rows in charts with modulation, a span lands on a modulated pair 40.7% of the time read 2-indexed against 13.1% (chance) read 0-indexed.
* `0002_broken_iroha`'s single AUTO TAB row `021,03,00  96  8` selects pair 8-2=6, the pair its one nonzero assign row modulates (`6, 3, 3.00, 0.50`: param 3 of a Flanger, its period, swept 3.00 to 0.50 measures). About 59% of AUTO TAB spans land on an unmodulated pair.

### 7 Calibration

An untouched track scores 1.22 on idle frames, and the codec floor is 1.14. Kamui went from 3.169 untouched to 1.808 now. The per-stage table is under 7 above.

### 7.1 Peak filter placement

Placed before the layered SE the EQ scores 1.924, and after it 2.029.

### 8.1 Overlap behaviour

* Chain against dry and add: 16 charts scored on overlap frames, `chain` beats `dry` on 13 and `add` on all 16 (full numbers under 8.1 above).
* Laser plus laser: on `2335_specterchaser_coyaan` 5m measure 62 beats 3 to 4, VOL-L held at 1.0 and VOL-R sweeping, both on C4=2 (LPF 600 to 15000 Hz, Q 5), no FX live. Chaining gives a mean band deviation of 9.78 dB against 2.51 dB for the later run alone. The capture shows the authored Q=5 resonance (0.8 to 1.6 kHz at -7.2 dB against -12.8 dry), and uncapped Q takes the deviation from 2.51 to 0.94 dB.

### 8.2 High-Q laser passages

On `2226_gryphone_etia` 5m measures 30 to 33 (fast laser wiggle through the tab LPF at Q 5.0), the render rises +1.9 dB over its whole-track level and the capture +1.0 dB, an overshoot of about 0.9 dB, with 0.35% of the window's samples clipping. The metric barely sees it: 3.542 rendered against 4.895 dry, and the overshoot moves it 0.005. The truncating feedback of 4.1 masked about 0.3 dB of it.

### 4.6b, 7.2, 8.1 Further details

* Tape Stop Ex without `lookahead`: three charts scored -6 to -24 dB.
* Slam gain optimum is 0.65 (flat to 0.70) with the one-voice rule; the fit was 0.5 while overlapping copies could sum.
* FX-L and FX-R overlap: 18776 same-pair and 9664 different-pair holds across the corpus. On `2337_recipinoriddle_oster` 5m, chaining put a 4 to 8 kHz band 11 dB under the capture, and reading dry per note matches it within 0.8 dB.
