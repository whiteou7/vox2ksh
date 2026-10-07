---
name: audio-refcheck
description: Regression-test the SDVX audio engine against the cabinet-recording reference corpus. Use whenever scripts/audio/fx_dsp.py, render_chart.py, spectral_metric.py or anything else in the audio render path changes — DSP math, unit conversions, the SE bank, the device ParamEq, effect combination, the output stage — and before calling any such change good. Also use when asked to "score", "re-measure", "check the render" or "run masscheck".
---

# Audio reference check

`scripts/shared/reference/ksh/` holds gameplay recordings (`mxm.ogg`, `exh.ogg`, ...; `music.ogg` is bare song audio, not a capture). `check_all_charts.py` matches them to charts in `data/music`, renders each, and scores per effect.

Python is `%LOCALAPPDATA%\Programs\Python\Python312\python.exe`. Run from the `vox2ksh` directory.

**Rule: a change isn't verified until the same measurement exists before and after.** The corpus, flags and chart set all move the score.

## Procedure

1. Note which effect or stage changed. Every other effect's row must stay flat; if not, the change isn't what you thought.

2. Baseline. Reuse one in `output/refcheck/` only if it came from the pre-change tree with the same flags and corpus.

```bash
git stash push -m refcheck-baseline -- scripts && python .claude/skills/audio-refcheck/check_all_charts.py -j 8 --csv output/refcheck/before.csv ; git stash pop
```

3. Iterate on charts that contain the effect. This renders and scores one chart/capture pair, aligning them automatically.

```bash
python .claude/skills/audio-refcheck/check_one_chart.py ../data/music/2229_kamui_tjhangneil scripts/shared/reference/ksh/<song>/mxm.ogg -d 5m
```

To find charts that use an effect, run `check_all_charts.py -n 40` and read the per-chart lines. `--only <substring>` narrows to one song.

4. Full run after, with the same flags. It is slow; run it in the background.

```bash
python .claude/skills/audio-refcheck/check_all_charts.py -j 8 --csv output/refcheck/after.csv
```

5. Compare.

```bash
python .claude/skills/audio-refcheck/compare_runs.py output/refcheck/before.csv output/refcheck/after.csv
```

## Verdict

Report:

* The changed effect: mean delta, charts up and down, and whether it survives frame weighting.
* Every other effect: should be flat (under about 0.02 dB, no chart moving materially). Anything else is a finding.
* The `ALL` row, for overall direction only.

Adopt if the target improves and nothing else regresses. An even split inside noise is "inconclusive"; record it that way (see `audio_engine.md` §9.3) and don't ship it. If the change is a modelling choice rather than a fix, add a flag in `render_chart.py` and A/B both, like `--laser-mode`, `--no-grid-snap` and `--tapestop-ex-floor`.

## Reading the metric

1. Use the `excl` column, not `gain`. Effects overlap, so the raw score covers everything live in the region. Echo scored -0.457 raw and +2.046 exclusive.
2. Don't judge a local fix by `ALL`. A +0.639 win on 65 frames shows as +0.010 over 5157.
3. The metric ranks; it can't diagnose. If a chart is bad in every region but aligns fine, suspect a chart-wide input (beat resolution, BPM list, parsing) and listen to it. Don't drop it as an outlier; that hid the `#BEAT RESOLUTION` bug.
4. A large `moved` with near-zero `gain` means a wrong algorithm, not an idle one. That is how Wobble's unit bug showed up.
5. Alignment correlation below about 0.15 means the capture never locked on. Drop those pairs.

## Gotchas

* Score PCM. `render_chart.py` defaults to `.ogg`; pass a `.wav` name when rendering by hand. The check scripts handle this.
* `check_all_charts.py` runs without `--peak-gain-scale`, `--peak-max-gain` (§7.1) and `--filter-max-resonance` (§4.1b), so it scores the tamed defaults. Fine for before/after if both runs match. To reproduce the transcribed model, pass `--extra="--peak-gain-scale 1.0 --peak-max-gain 15 --filter-max-resonance 99"` to both runs.
* Its CSV has no `laser` or `idle` row, so it can't see changes to the tab-laser filters or device ParamEq. Re-render both ways and read the `laser` row of `check_one_chart.py`. A flat aggregate proves nothing there.
* Block size (`-b`) changes output. Keep it the same between runs.
* Effects that rarely fire, like Tape Stop Ex, look inert over note spans. Score the frames where they're live.
* Only kamui has a measured floor (1.14). Elsewhere compare deltas, not absolute values.

## Recording the result

State the adopted rule in the owning section of `specs/audio_engine.md`, plainly, as fact: no "X is real" emphasis and no account of readings that turned out wrong. Put the number, chart count and any rejected hypotheses under the matching heading in `specs/evidence/audio_engine.md`.
