# scripts/audio/

Reference writeup: [`specs/audio_engine.md`](../../specs/audio_engine.md) (technical, with DLL addresses).

## The implementation

| file | what it does |
|---|---|
| `sdvx_fx.py` | The DSP, transcribed from `BMSoundLibSvo::CSvoEffectedAudioGeneratorImpl`. Biquads (LPF/HPF/BPF/peaking), BitCrusher, Retrigger/Echo, Gate, TapeStop, SideChain, Flanger, Wobble, plus the knob-swept laser variants. Runs standalone on a WAV. |
| `apply_chart.py` | Parses a `.vox`, decodes the `.s3v`, and applies every FX-button hold and laser segment at the chart's times. Also reproduces the parts that live *outside* the effect generator: the device ParamEq that is the default laser sound, its 80 ms lag, the music duck, and the layered SE bank. |
| `s3p_decode.py` | Extracts an `S3P0` sample bank and decodes each `S3V0` (ASF/WMA) entry to WAV, reporting duration, peak, centroid and attack time. Also where the per-sample header gain is read from — see §6.1.4. |

```bash
python scripts/audio/sdvx_fx.py --list
```

```bash
python scripts/audio/sdvx_fx.py in.wav out.wav --effect wobble --params 80,0,3,500,18000,4.0,1.4 --range 8:16
```

```bash
python scripts/audio/apply_chart.py ../data/music/2229_kamui_tjhangneil -d 5m -o output/kamui_fx.ogg
```

`apply_chart.py --help` lists the diagnostic flags that isolate each part of the chain (`--no-peak`, `--peak-delay`, `--no-duck`, `--se-trim`, `--se-polyphonic`, …). Each exists because it settled a question; they are documented in `audio_engine.md` §6.

## The calibration harness

Only needed if you change the DSP or the chain. Dormant otherwise.

| file | what it does |
|---|---|
| `metric.py` | The closeness metric: 46 log-spaced bands per 46 ms frame, level-normalised, mean \|dB\| difference. Phase-insensitive, so it survives the capture's polarity inversion, 7.9 ppm clock drift and Ogg coding. Lower is closer. |
| `regions.py` | The same metric broken down by what the chart is doing per frame — FX / peak-laser / tab-laser / idle. |
| `blendfit.py` | Fits `β` in `\|ref\| ≈ (1-β)·\|dry\| + β·\|mine\|` per effect region. `β ≈ 1` means the blend depth is right. Currently the diagnostic for the open effect-state-continuity item: Echo fits at 1.00 while Wobble (0.03) and BitCrusher (0.23) sit at the wrong *phase*. |

Those three are wired to the single kamui capture. The two below work on any song with a recording, and are what to reach for now:

| file | what it does |
|---|---|
| `xcheck.py` | Aligns any recording to any chart — offset **and** clock drift, fitted over several correlation windows — renders, and scores **per effect**. `python xcheck.py <song folder> <recording> [-d 5m]`. Use `--render` to score a file you already have, `--extra=--no-persist` to pass flags to `apply_chart.py`. |
| `masscheck.py` | Runs `xcheck.py` across every recording in `../shared/reference/ksh/` and aggregates the per-effect gains. `python masscheck.py [-n 10] [--csv out.csv]`. 41 of the 86 reference folders currently match a chart in `data/music`. |

### Reading `xcheck` output — the one thing that will mislead you

Each region is scored twice: over its raw mask, and over **exclusive** frames where that effect is the only FX running. Effects overlap constantly, so the raw column measures everything active in that region, not the named effect. **Attribute with the exclusive column.**

Two ways the raw column has already produced wrong conclusions:

* Echo scored −0.457 raw and **+2.046** exclusive — the raw figure was an HPF+Gate sitting on top of it. Echo is fine; it was briefly written off as broken.
* A fix worth **+0.639** on Retrigger exclusive frames showed as **+0.010** on the whole-track `ALL` row, because 65 improved frames dilute across 5157. On `ALL` alone a real fix looks like noise.

So: `ALL` for "is the render better overall", exclusive columns for "which DSP is wrong". Never judge a localized change by `ALL`.

`gain` is `dry − render`: positive means the render is closer to the recording than doing nothing. `moved` is how far the effect shifted the audio away from dry, in the same units — read the two together. A near-zero `gain` with a *large* `moved` does not mean the effect is doing nothing; it means it is doing plenty in the wrong direction, which is a wrong algorithm rather than an inactive one. That pairing is how Wobble was identified: it moves the audio further than any other effect and still ends up no closer to the recording (see `HANDOFF.md` §2.6).

Current standing: untouched track **3.169**, current render **1.799**, floor (codec noise) **1.14**.

**Render to `.wav` when scoring.** `apply_chart.py` defaults to `.ogg`, and the metric reads PCM — going through Vorbis would stack a second layer of codec noise on top of the capture's own and make the result incomparable to every number above. The `-o` extension picks the container, so `-o output/work/best.wav` is all it takes.

**The trap**: the metric matches one global level offset across the whole track, so a change that alters level over most of the track shifts that offset and makes untouched "idle" frames *look* worse. Read the FX / peak-laser / tab-laser columns, not idle.

## `reference/`

`kamui_goal.ogg` — a recording of the real cabinet playing `2229_kamui_tjhangneil` MXM.

**Do not delete this file.** It cannot be regenerated without the hardware, and every calibration number in the writeup is measured against it. It is the only binary in the project that is checked in on purpose (the `.gitignore` excludes all audio except this).

## Regenerating the working files

The metric needs three WAVs in `output/work/`, none checked in because all three are derived. See `HANDOFF.md` §5 for the exact ffmpeg commands, or [`../shared/_paths.py`](../shared/_paths.py), which documents the same thing next to the paths it defines.
