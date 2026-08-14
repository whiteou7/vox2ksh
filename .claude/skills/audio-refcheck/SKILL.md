---
name: audio-refcheck
description: Regression-test the SDVX audio engine against the cabinet-recording reference corpus. Use whenever scripts/audio/sdvx_fx.py, apply_chart.py, metric.py or anything else in the audio render path changes — DSP math, unit conversions, the SE bank, the device ParamEq, effect combination, the output stage — and before calling any such change good. Also use when asked to "score", "re-measure", "check the render" or "run masscheck".
---

# Audio reference check

Every audio change is measured against real cabinet recordings, never eyeballed. `scripts/shared/reference/ksh/` holds 713 gameplay folders (`mxm.ogg`, `exh.ogg` … — the difficulty tag names the take; `music.ogg` is bare song audio, **not** a capture), and `masscheck.py` matches them to charts in `data/music`, renders each, and scores per effect.

Python is `%LOCALAPPDATA%\Programs\Python\Python312\python.exe`. Run everything from the `vox2ksh` directory.

## The one rule

**A change is not verified until the same measurement exists before and after it.** A single "after" number means nothing — the corpus, the flags and the chart set all move the score.

## Procedure

### 1. Name what changed, and what it can touch

Write down which effect(s) or stage the change affects. That determines which charts are informative and which aggregate rows must not move. A change to one DSP must leave every other effect's row unchanged; if it doesn't, the change is not what you thought it was.

### 2. Get a baseline

Baselines live in `output/refcheck/` (git-ignored, regenerable). Reuse an existing baseline **only** if it was produced from the pre-change tree with the identical flags and corpus.

Otherwise stash the change and produce one:

```bash
git stash push -m refcheck-baseline && python scripts/audio/masscheck.py -j 8 --csv output/refcheck/before.csv ; git stash pop
```

Confirm the stash popped cleanly before continuing.

### 3. Iterate fast on a few charts

A full run is slow. While developing, use `xcheck.py` on charts that actually contain the effect you touched — it renders and scores one chart/capture pair with automatic alignment:

```bash
python scripts/audio/xcheck.py ../data/music/2229_kamui_tjhangneil scripts/shared/reference/ksh/<song>/mxm.ogg -d 5m
```

To find charts that exercise an effect, run `masscheck.py -n 40` and read the per-chart lines — each prints the effects it scored. `--only <substring>` then narrows to one song.

### 4. Full run, after

Same flags as the baseline, no exceptions:

```bash
python scripts/audio/masscheck.py -j 8 --csv output/refcheck/after.csv
```

Run it in the background; it takes a long time and the corpus is large.

### 5. Compare

```bash
python .claude/skills/audio-refcheck/compare.py output/refcheck/before.csv output/refcheck/after.csv
```

It prints, per effect: mean and frame-weighted exclusive gain before/after, the delta, how many charts improved versus regressed, and the largest per-chart swings.

### 6. Verdict

Report, in this order:

* the effect you changed — mean delta, charts up/down, and whether the win survives frame weighting;
* every other effect — these should be flat (|delta| under ~0.02 dB with no chart moving materially). Any non-flat row is a finding, not a rounding error;
* the `ALL` row, for whole-render direction only.

Adopt the change if the target effect improves and nothing else regresses. If the split is even and the mean is inside noise, say so plainly — "inconclusive" is a real result and gets recorded as such (see `specs/audio_engine.md` §9.3 for how past inconclusive results were written up). Do not ship a change on an even split.

If the change is a modelling *choice* rather than a fix, add a flag for it in `apply_chart.py` and A/B both ways, the way `--laser-mode`, `--no-grid-snap` and `--tapestop-ex-floor` already do.

## Reading the metric

These four rules were each learned by getting them wrong.

1. **Read the `excl` column, not `gain`.** Effects overlap constantly, so a region's raw score measures everything live in it. Echo once scored −0.457 raw and +2.046 exclusive and was wrongly declared broken.
2. **Never judge a localized fix by `ALL`.** A +0.639 win on 65 Retrigger frames shows as +0.010 across 5157. That looks like noise because it is diluted, not because it is small. Score on the frames the change can actually affect.
3. **The metric ranks; it cannot diagnose.** A chart broken by one wrong global constant and a chart with several bad DSPs score identically — uniformly awful. If a chart is bad in *every* region while its alignment is fine, suspect a chart-global input (beat resolution, BPM list, parsing) and **listen to it**. Do not exclude it as an outlier: that reflex hid the `#BEAT RESOLUTION` bug through three separate experiments and reversed one of their conclusions.
4. **`moved` separates "doing nothing" from "doing plenty, wrongly".** A large `moved` with ~zero `gain` is a wrong algorithm, not an idle one — that pairing is what identified Wobble's unit bug.

Also: alignment correlation below ~0.15 means the capture never locked onto the chart; drop those pairs rather than reading their scores.

## Gotchas

* **Score in PCM.** `apply_chart.py` defaults to `.ogg`; a lossy container stacks a second layer of codec noise on the capture's own. Pass a `.wav` name when rendering by hand. `xcheck.py`/`masscheck.py` handle this themselves.
* **`masscheck.py` scores the dampened peak EQ *and* the capped filter resonance**, because it invokes `apply_chart.py` without `--peak-gain-scale`/`--peak-max-gain` (§7.1) or `--filter-max-resonance` (§4.1b), and all three CLI defaults are deliberately tamed. That is fine for before/after comparison as long as both runs match. To reproduce the spec's transcribed-model numbers, pass `--extra="--peak-gain-scale 1.0 --peak-max-gain 15 --filter-max-resonance 99"` to **both** runs.
* **`masscheck.py`'s CSV has no `laser` or `idle` row** — it drops both, because neither has an exclusive column to attribute with. So its aggregate cannot see a change to the tab-laser filters or the device ParamEq at all, no matter how large. Score those by re-rendering both ways and reading `xcheck.py`'s `laser` row directly; a flat masscheck table is not evidence that a laser-path change did nothing.
* **Block size changes output.** Coefficients and LFOs update per block, so `-b` must match between runs.
* **Effects with few firing frames need targeted scoring.** Tape Stop Ex fires on a fraction of its own notes; scored over note spans it looks inert. Score the frames the effect is actually live in.
* **No measured floor exists for the non-kamui recordings**, so a raw "+1.07 dB" elsewhere has no yardstick. Only kamui has one (1.14). Compare deltas, not absolutes, outside kamui.

## Recording the result

A measured result belongs in `specs/audio_engine.md`, in the section that owns the behaviour — the number, the chart count, and what was ruled out. Rejected hypotheses are as valuable as accepted ones; §9.3 exists purely to stop someone re-running a dead end.
