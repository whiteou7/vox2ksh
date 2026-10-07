# SOUND VOLTEX audio engine

Target: `modules/soundvoltex.dll` (PE32+ x64, ImageBase `0x180000000`, `SoundVoltex6_x64Release`, 2025-06-19). All addresses are virtual addresses in it.

From MSVC RTTI, Ghidra 12.1.2 and capstone, cross-checked against the 8107 charts in `data/music/` and cabinet recordings in `scripts/shared/reference/ksh/`. Three values are fitted, not transcribed: Tape Stop Ex's envelope floor (§4.6b), the SE trim (§7.2) and the peak-EQ damping default (§7.1). Plain-language intro: [`audio_engine_primer.md`](audio_engine_primer.md).

## 1. Where the effects live

`BMSoundLibSvo::CSvoEffectedAudioGeneratorImpl` (vftable `0x180919ca8`, roughly `0x180628000` to `0x180650000`) is the whole FX chain.

| layer | address | role |
|---|---|---|
| generator ctor | `0x180628b50` | builds parameter vectors |
| chart to generator | `0x18022db60` | `switch` on `.vox` effect id, fills the vectors |
| per-block dispatcher | `0x18062e3d0` | `switch` on internal kind, calls a wrapper |
| dispatcher (animated params) | `0x180633360` | same kinds, parameters interpolated over time |
| wrappers | `0x180630110` to `0x180632c10` | chart params to DSP args (BPM, knob, grid snap) |
| DSP leaves | `0x18063df40` to `0x1806429b0` | the sample math |

| address | function |
|---|---|
| `0x18063d9e0` | prepare: int16 to float L/R work buffers |
| `0x18063dc40` | writeback: float to clamped int16, interleaved |
| `0x18062e310` | grid snap, `samplesPerBeat = trunc(2646000 / BPM)` (2646000 = 44100*60) |
| `0x180796b80` / `0x18076f5d0` / `0x18076b420` | `sincosf` / `sinf` / `powf` |

## 2. Signal path

```
.s3v (16-bit PCM, 44100 Hz stereo)
  -> FUN_18063d9e0   float L[], R[] holding raw int16 magnitudes (+-32768, no /32768 anywhere)
  -> one effect      dry at gen+0x38/0x40, wet at gen+0x58/0x60
  -> FUN_18063dc40   clamp to [-32768, 32767], truncate toward zero, write interleaved int16
```

* Sample rate is fixed at 44100. `0.00014247585` = 2pi/44100 is in every filter.
* All math is single-precision float, coefficients included.
* Dry/wet: `out = (1-mix)*dry + mix*wet`, `mix = clamp(param, 0, 100) / 100`. A few effects add makeup gain to the wet term.
* Blocked: block length is `gen+0x1a0` (the audio callback's frame count). Coefficients and LFOs update once per block, so output depends on block size. Laser filters start 64 samples early. Retrigger alone is snapped back onto the musical grid (§5.2).
* Quirk in `FUN_18063d9e0`: if the left sample is exactly 0, both channels of that frame are zeroed. A real branch in the binary.

## 3. Effect inventory

The `.vox` id (`#FXBUTTON EFFECT INFO` column 1) maps to an internal kind in `FUN_18022db60`:

| id | kind | vec (this+) | fields | wrapper | DSP leaf | effect |
|---|---|---|---|---|---|---|
| 1 | 3 | 0xb0 | 6 | `0x180630fa0` | `0x18063ffb0` | Retrigger |
| 2 | 5 | 0xe0 | 35 | `0x1806317a0` | `0x180641d20` | Gate |
| 3 | 6 | 0xf8 | 5 | `0x180631cf0` | `0x18063f420` | Flanger |
| 4 | 7 | 0x110 | 3 | inline | `0x180640700` | Tape Stop |
| 5 | 9 | 0x140 | 5 | `0x1806324b0` | `0x180641770` | Side Chain |
| 6 | 10 | 0x158 | 7 | `0x180632820` | `0x1806414f0` | Wobble |
| 7 | 2 | 0x98 | 2 | `0x180630d10` | `0x18063fc60` | Bit Crusher |
| 8 | 4 | 0xd0 | 7 | `0x180631390` | `0x18063ffb0` | Retrigger Ex / Echo |
| 9 | 11 | 0x178 | 2 | inline | `0x1806429b0` | Pitch Shift |
| 10 | 8 | 0x130 | 5 | `0x1806320d0` | `0x180640c20` | Tape Stop Ex |
| 11 | 12 | 0x70 | 4 | `0x180630110` | `0x18063df40` | Low Pass |
| 12 | 13 | 0x88 | 4 | `0x180630760` | `0x18063e500` | High Pass |
| 13 | 14 | 0x190 | 3 | `0x180632c10` | `ApplyPitchAndSpeed` | Pitch & Speed (§4.11) |

Four ids are mislabelled in the inherited community notes:

| id | inherited | actual | evidence |
|---|---|---|---|
| 3 | Phaser | Flanger | modulated fractional delay with feedback taps, `0x18063f420` |
| 10 | Highpass | Tape Stop Ex | 5 float params with tape-stop-shaped clamps, `0x180640c20` |
| 11 | Lowpass | Lowpass | confirmed: case `0xb`, vec `+0x70`, kind 12, `0x18063df40` |
| 12 | Flanger | Highpass | case `0xc`, vec `+0x88`, kind 13, `0x18063e500` |

Ids 11 and 12 carry 4 params (`mix, f, f, Q`) like a filter; id 3 carries 5.

Lasers (`#TAB EFFECT INFO`) reuse the same vectors and leaves, registered into a second map (`gen+0x58`, against `gen+0x38`) by `FUN_180639290/360/430`:

| id | kind | vec | wrapper | leaf | effect |
|---|---|---|---|---|---|
| 1 | 1 | 0x70 | `0x180630110` | `0x18063df40` | Low Pass (knob-swept) |
| 2 | 2 | 0x88 | `0x1806303f0` | `0x18063e500` | High Pass (knob-swept) |
| 3 | 3 | 0xa0 | `0x180630a20` | `0x18063fc60` | Bit Crusher (knob-swept) |

A laser node's effect comes from `#TRACK1`/`#TRACK8` column C4: `0` is the peak filter (default), `1..5` index `#TAB EFFECT INFO` (1-indexed), `6` has no filter but is the control source for `#TAB PARAM ASSIGN INFO` (§6.3). `FUN_18062ea60` keys its map on `noteField[4] - 1`.

The peak filter is not in this engine. C4=0 gives key `-1`, the sentinel `FUN_18063a070` installs (`laserMap[-1] = kind 0`, nothing). The band-pass at `0x18063eb10` is reachable only through Wobble. The real path is a DirectSound ParamEq DMO driven from the gameplay event dispatcher (§7.1). On `2229_kamui` MXM, 870 of 894 VOL-L nodes are C4=0.

Column order per type, from reader `FUN_180239810` / writer `FUN_1800d40c0`:

```
1  -> %d, %d,  %f, %f, %f, %f, %f      2  -> %d, %f, %d, %f
3  -> %d, %f,  %f, %f, %d, %f          4  -> %d, %f, %f, %f
5  -> %d, %f,  %f, %d, %d, %d          6  -> %d, %d, %d, %f, %f, %f, %f, %f
7  -> %d, %f,  %d                      8  -> %d, %d, %f, %f, %f, %f, %f, %f
9  -> %d, %f,  %f                      10 -> %d, %f, %f, %f, %f, %f
11 -> %d, %f,  %f, %f, %f              12 -> %d, %f, %f, %f, %f
TAB 1/2 -> %d, %f, %f, %f, %f          TAB 3 -> %d, %f, %d
```

## 4. Algorithms

`N` is the block length, `x` dry, `y` wet, `m` mix (0..1).

### 4.1 Biquads (LPF `0x18063df40`, HPF `0x18063e500`, BPF `0x18063eb10`)

RBJ cookbook, Direct Form I, coefficients per block:

```
f  = max(freq, 1.0)                 # LPF: <=1 -> 1; HPF/BPF: <1 -> 1
Q  = max(q, 0.1)
w0 = f * 2*pi/44100
sn, cs = sincosf(w0)
alpha  = sn * (0.5 / Q)
a0i    = 1 / (1 + alpha)

LPF:  b0 = b2 = (1-cs)*0.5*a0i ,  b1 = (1-cs)*a0i
HPF:  b0 = b2 = (1+cs)*0.5*a0i ,  b1 = -(1+cs)*a0i
BPF:  b0 = alpha*a0i , b1 = 0 , b2 = -alpha*a0i
a1 = -2*cs*a0i        a2 = (1-alpha)*a0i

y[n] = b0*x[n] + b1*x[n-1] + b2*x[n-2] - a1*y[n-1] - a2*y[n-2]
```

Output stage:

```
LPF / HPF:  out = ((1-m)*x + m*y) * (1 - Q*0.04)
BPF:        G = (Q <= 1) ? max(Q + 0.9, 0.1) : (Q*0.2 + 2.0 > 4.0 ? 3.0 : Q*0.2 + 2.0)
            out = (1-m)*x + m*y*G
```

The `(1 - Q*0.04)` trim applies to the mixed signal, so it also attenuates dry. That's why laser sweeps duck slightly.

**The feedback path is pure float and must not be requantised.** `FUN_18063e500` writes raw filter outputs to float history buffers at `gen+0x48` (L) / `gen+0x50` (R) and reads them back next sample. The mixed, trimmed result goes to separate wet buffers (`gen+0x58`/`0x60`). The only int16 clamp in the chain is `FUN_18063dc40`, once per stage (§8.1), downstream of the recursion.

An earlier `fx_dsp.py` truncated the feedback to int16 each sample. That injects +-1 LSB into poles within 1e-3 of the unit circle at low cutoffs (9.5e-4 at 40 Hz), causing a limit cycle: a 40 Hz HPF produced +8.3 dB at 250 to 700 Hz and 57 clipped samples on `0381_hyena_hommarju` 4i (tab HPF 40 to 2000 Hz, Q 3, at m10 beat 2 and m12 beat 2). The capture is flat there. It's gone by 200 Hz, which is why it only showed up as two bad laser runs. The device ParamEq shares the recursion (centre clamped to [80, 16000]), so it was affected less.

Measured over 40 (chart, capture) pairs, `-b 512`: the two hyena windows improve +1.23 dB each (3.712 to 2.478, 3.924 to 2.702) and clipped samples fall 110 to 6. Corpus-wide it's small: laser region +0.008 (10 up, 2 down), FX HighPassFilter +0.119 (carried by `aimai_chocolate` 5m), ALL +0.004, other effects unchanged within 0.004. `check_all_charts.py` can't see the laser row (§ audio-refcheck skill).

### 4.1b Resonance damping (a deliberate deviation)

The engine uses the authored Q with no clamp or scale. Wrapper `FUN_180630760` passes mix, cutoff and Q straight to `FUN_18063e500`, and `CGainWithHardLimiter` (§6.2) is a plain gain and clip. The loud whoosh is real.

It's common: of 32430 LPF/HPF definitions in `#TAB EFFECT INFO`, 52.2% have Q > 2, nearly all on two presets, Q=3.0 (25.9%, +9.5 dB peak) and Q=5.0 (25.8%, +14.0 dB). Q=0.7 (47.6%) has no peak. FX-button filters (2474 definitions) are 38% above Q 2. Wobble is 94.8% Q=1.4 (+2.9 dB) with its own makeup gain, so it's left alone.

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

Damping is monotonically worse against recordings, which proves the resonance authentic. The cap targets the two loud presets and leaves Q <= 2 alone.

`render_chart.py` defaults `--filter-max-resonance` to 6 dB. That is a listening-comfort choice costing 0.157 dB on the frames it touches (ALL +0.918 to +0.901). `--filter-max-resonance 99` restores the transcription; `fx_dsp.damp_resonance`'s own defaults are inert. A uniform small decline across every FX row is the signature of a laser-path change, not a per-effect regression.

For re-measuring, pass `--extra="--filter-max-resonance 99"` (with the §7.1 flags) to reproduce numbers from before the cap, including §4.1 and §9.

### 4.2 Laser / knob sweep (wrappers `0x180630110` LPF, `0x1806303f0` + `0x180630760` HPF)

Params `{mix, freqLo, freqHi, Q}`. Per block:

```
lo    = max(freqLo, 1.0)
ratio = freqHi / lo
v     = knob position 0..127, linearly interpolated across the segment
LPF:  cutoff = lo * ratio ** (1 - v/127)      # v=0 -> freqHi, v=127 -> freqLo
HPF:  cutoff = lo * ratio ** (    v/127)      # v=0 -> freqLo, v=127 -> freqHi
```

`1/127 = 0.007874016f`. Nothing else transforms `v`; `#TAB PARAM ASSIGN INFO` belongs to `#TRACK AUTO TAB` (§6.3).

Laser Bit Crusher (`0x180630a20`) ignores the chart rate once the knob moves: `rate = int(clamp(v/127, 0, 1) * 29.0 + 1.0)`, 1 to 30.

### 4.3 Bit Crusher (`0x18063fc60`)

Sample-and-hold, no bit-depth reduction:

```
m    = clamp(mix,0,100)/100
rate = clamp(rate, 1, 30)
for i in 0 .. blockLen-1:          # i is the index within the block
    k = i % rate
    s = (k == 0) ? x[i] : x[i-k]
    out[i] = (1-m)*x[i] + m*s
```

Right channel uses the same `k`. The counter is function-local, so the hold grid realigns every block and output depends on callback size. A continuous grid scores 0.582 dB worse on 16/16 charts.

### 4.4 Retrigger / Echo (`0x18063ffb0`)

Params `mix, lengthSec, feedback, count, gate, release`:

```
m    = clamp(mix,0,100)/100
len  = clamp(lengthSec, 0.1, 8.0)
fb   = clamp(feedback,  0.1, 1.0)
cnt  = clamp(count,     1,   32)
gt   = clamp(gate,      0.1, 1.0)
rel  = clamp(release,   0.0, 1.0)

seg     = int(len*44100) // cnt
gateLen = int(seg * gt)
fadeLen = int(gateLen * rel)
g[k]    = fb ** k   for k = 0..31       # table at this+0x154

t   = phase counter (samples since effect start)
rep = t // seg ;  if rep >= cnt: rep = 0, t -= seg*cnt
rem = t %  seg
if rem > gateLen:             wet = 0
elif rem > gateLen - fadeLen: wet = delayed * g[rep] * (1 - (rem-gateLen+fadeLen)/fadeLen)
else:                         wet = delayed * g[rep]
delayed = dry[i - rep*seg]
out = (1-m)*dry + m*wet
```

The leading integer is the repeat `count`, passed verbatim (`0x180631285`). Id 8 (Echo) feeds the same routine with a 7th field the wrapper reads for alignment or update period. It's `0.00` in every chart examined and its meaning is unresolved.

### 4.5 Gate (`0x180641d20`)

```
m       = clamp(mix,0,100)/100
steps   = clamp(steps, 1, 32)
period  = clamp(periodSec, 0.1, 4.0) * 44100
stepLen = int(period) // steps
t   = phase counter, wrapped at period
idx = t // stepLen ; if idx > 15: idx -= 16
g   = float(patternTable[idx] * 0.0322)        # int32 table, double multiply
out = (1-m)*x + m*x*g
```

The 16-entry int32 table at `struct+0x10` defaults (from `FUN_18022db60`) to `{32, 4}` repeated 8x, giving gains 1.0304 and 0.1288: full level (+0.26 dB) and -17.8 dB, not silence. A hard `1.0/0.0` gate scores 1.452 dB worse on 16/16 charts.

### 4.6 Tape Stop (`0x180640700`)

```
m     = clamp(mix,0,100)/100
speed = clamp(speed, 1.0, 10.0)
dur   = clamp(durSec, 0.1, 2.0)
total = dur * 44100
step  = 1 / total

if written + N >= total:   out = (1-m)*dry
else:
    append dry block to the record buffer
    for each sample:
        if frac < 1.0:
            idx  += 1
            frac += idx_before * step * speed + 1.0
        env  = 1 - written * step
        wet  = record[idx] * env
        out  = (1-m)*dry + m*wet
        written += 1
        frac    -= 1.0
```

Playback rate is about `1/(1 + idx*step*speed)`, a hyperbolic slow-down, while `env` fades linearly to silence over `dur`. Duration is in seconds.

### 4.6b Tape Stop Ex (`0x180640c20`)

Id 10 fades in from a floor where Tape Stop fades out. Params `mix, speed, duration, preroll, window`.

**All three time fields are in beats**, unlike Tape Stop. Wrapper `0x1806320d0` multiplies them by `60/BPM` (`0x180632170` to `0x18063218a`), re-reading BPM every block. Read as seconds, above about 120 BPM the preroll outruns the note and the effect renders nothing with no error.

After conversion, in seconds:

```
m       = clamp(mix, 0, 100) / 100
speed   = clamp(speed, 1.0, 10.0)
dur     = clamp(duration, 0.1, 2.0) * 44100
window  = clamp(window,   0.1, 2.0) * 44100    # spin-up window
preroll = max(preroll, 0.0) * 44100            # no upper clamp
```

State is a running absolute sample position `pos` at `this+0x214`, incremented by block length per call (not reset per block). Three phases:

* `pos < min(preroll, dur)`: dry passes through.
* `min(preroll, dur) <= pos <= preroll + window`: active. On first entry the dry samples are copied once into a record buffer (`this+0x40`/`0x41`, one-shot flag `this+0x45`). Per sample, `phase` counting from 0:
  ```
  env  = clamp( (phase/window)*(1 - floor) + floor, <= 1.0 )     # floor = this+0x46
  if frac < 1.0:
      phase += 1
      frac  += (window - phase)*speed/window + 1.0
      frac   = max(frac, 1.0)
  frac -= 1.0
  idx  = (window - recordLen) + phase
  out  = m * env * record[idx] + (1-m) * dry
  ```
  The envelope ramps up from `floor` to 1.0 while the read head advances more often. It's a spin-up.
* `pos > preroll + window`: `(1-m)*dry`.

Notes:

* The record buffer comes from the track, not the note. It's up to `window` long and often runs past the note's end, so a renderer holding only the note's slice clamps on its last sample and buzzes. `fx_tapestop_ex` takes `lookahead=(fullL, fullR, offset)`; without it three charts scored -6 to -24 dB.
* It fires rarely. A note shorter than its preroll produces nothing. Only 27 reference-matched charts have a note that reaches the active branch (spans 0.14 to 2.7 s). `1954_treajourney_chubay` has ten id-10 notes and fires on none. Score on firing spans.
* Measured on 13 capture-matched charts that fire (499 frames): implementing it gives +2.2 dB, 12 of 13 improve, none worse.

**The floor is fitted.** Nothing was traced to whatever writes `this+0x46`. 0.0 costs 1.3 dB, but between 0.4 and 0.75 the spread is 0.08 dB with per-chart curves in opposite directions, and `floor = 1.0` is only 0.19 dB behind. 0.5 ships. `--tapestop-ex-floor` isolates it. The field at `this+0x224` is also untraced.

### 4.7 Side Chain (`0x180641770`)

A volume envelope, no detector:

```
m      = clamp(mix,0,100)/100
period = max(periodSec, 0.1)
A%,H%,R% = clamp(each, 0, 100)
N = int(period*44100)
A = int(A% * 0.002 * N)
H = int(H% * 0.003 * N)
R = int(R% * 0.005 * N)

t = counter, wrapped at N
if   t < A:        g = 1 - t/A
elif t < A+H:      g = 0
elif t < A+H+R:    g = (t - H - A)/R
else:              g = 1.0
out = (1-m)*x + m*x*g
```

Example `5, 90.00, 1.00, 45, 50, 60`: 1 s cycle, 90 ms duck, 150 ms silence, 300 ms recovery.

### 4.8 Flanger (`0x18063f420`)

Multi-pass modulated delay, with a quadrature LFO on the right channel:

```
m     = clamp(mix,0,100)/100
d     = clamp(delayMs, 0.1, 3.0) * 44.1        # samples
rate  = max(rateParam, 0.0) * 0.5              # Hz
depth = clamp(feedbackPct, 0, 100)/100 * d
st    = clamp(stages, 0.0, 4.0)                # ceil() -> pass count

for pass in ceil(st) .. 0:
    for i in block:
        sL   = sinf(counter * rate * 2*pi/44100)
        posL = i - (sL*depth + d)
        L'   = lerp(buf[floor(posL)], buf[floor(posL)+1], frac(posL))
        c2   = counter + 11025/rate (wrapped)             # 90 degrees
        sR   = sinf(c2 * rate * 2*pi/44100)
        posR = i - (sR*depth + d)
        R'   = lerp(...)
        if pass == topPass:                               # partial last pass
            a = m - (1-m)*(topPass - st) ; b = (topPass - st)*m + (1-m)
            out = a*L' + b*x
        else:
            out = m*L' + (1-m)*x
        if st >= 1 and pass == 0: out *= 1.5              # make-up
        counter += 1 ; wrap at 22050/rate
```

### 4.9 Wobble (`0x1806414f0`)

An LFO sweeping one biquad. Params `mix, filterType, waveType, freqA, freqB, rate, Q`:

```
mix    = clamp(mix, 0, 100)
lo, hi = min(freqA,freqB), max(freqA,freqB)
period = max(periodSec, 0.1) * 44100
Q      = max(Q, 0.1)
ph     = counter / period
ratio  = hi / lo

waveType 0: f = lo + ph*(hi-lo)                            # saw up
waveType 1: f = hi - ph*(hi-lo)                            # saw down
waveType 2: f = lo * ratio ** ((sinf(ph*2*pi) + 1) * 0.5)  # log-sine
waveType 3: f = lo * ratio ** (ph < 0.5 ? 2*ph : 2-2*ph)   # log-triangle
waveType 4: f = (counter >= period/2) ? hi : lo            # square

counter += N ; if counter >= period: counter -= period
filterType 0 -> LPF, 1 -> HPF, 2 -> BPF
```

**C6 is a rate in cycles per beat.** The wrapper takes the reciprocal before scaling by the beat (`1.0 / field[5]` at `0x180632aa0`, then `* (60.0 / BPM)` at `0x180632ab6`):

```
periodSec = (60 / BPM) / C6
```

So `6, 0, 3, 80.00, 500.00, 18000.00, 4.00, 1.40` is an LPF, log-triangle, 80% wet, 500 to 18000 Hz, 4 wobbles per beat, Q=1.4. Reading C6 as a period runs that common row 16x slow. The correct reading improves 13/13 capture-matched charts, +0.077 to +0.955 dB mean exclusive over 3247 frames. `--wobble-legacy-period` restores the old reading.

**The LFO counter restarts at every note.** It's a member at `this+0x238`, but `FUN_180632820` zeroes it before every note's block loop (`mov dword ptr [rax + 0x238], 0` at `0x1806329eb`). The write-back only carries it across blocks within a note. On `2337_recipinoriddle_oster` 5m at m114 b4 a persisted phase scores 3.671 against the capture and a per-note restart 1.877 (dry 4.456), and reproduces the capture's 3 to 15 kHz modulation profile. `--wobble-persist` restores the old model. BitCrusher's hold position and Gate's step counter aren't threaded either. Both score well (+2.3, +3.2), so don't thread them without finding a reset.

The same capture confirms the `max(periodSec, 0.1)` clamp: the chart asks for 61 ms, the clamp gives 100 ms, and modulation peaks at 10.0 Hz, not 16.3.

### 4.10 Pitch Shift (`0x1806429b0`)

SOLA splice plus sinc resample. The routine takes five arguments `(this, blockLen, blockOffsetFrames, mix, amount)`, with `amount` on the stack at `[rsp+0x160]`; Ghidra drops it.

Conditioning (`0x180642a2a` to `0x180642a9c`):

```
mix    = (mix >= 0 ? min(mix, 100) : 0) * 0.01
amount: if (amount >= -12) { a = min(amount, 12); if (a < 0) a = min(a, -1); }
        else                 a = -12
        if (0 < a && a < 1)  a = 1
ratio  = pow(2.0, a/12)                       # double pow @ 0x180769d80
```

Shift is clamped to +-12 semitones, and any nonzero magnitude under one semitone is pushed out to +-1. Exactly 0 takes a unison passthrough. `amount = 12` occurs in charts alongside 0, 2, 4, 5.

Object layout (ctor `FUN_18063d5d0`; all three buffer pairs are `PS_BUFLEN` floats):

| offset | meaning |
|---|---|
| `0x00` | int16 interleaved source |
| `0x38`/`0x40` | dry float L/R, filled by `FUN_18063d9e0` |
| `0x58`/`0x60` | output float L/R |
| `0x244` | 441, autocorrelation window (10 ms) |
| `0x248` | output cursor; the only state kept across calls |
| `0x24c` | 17640, input buffer length (400 ms) |
| `0x250`/`0x258` | grain buffer L/R |
| `0x260` | 17640, input load count |
| `0x268`/`0x270` | input window float L/R |
| `0x278` | 17640, accumulator capacity |
| `0x280`/`0x288` | output accumulator L/R |

Stage 1, pitch period: each pass reloads the 17640-frame window from the source cursor, then autocorrelates 441 left-channel samples at every lag from 132 to 882 (`0x84` to `0x372`, 50 to 334 Hz), keeping a running max in a double. The winning lag applies to both channels. Ties keep the earlier lag (strict increase), so a silent window gives 132. The loader zeroes both channels where the left sample is 0 (`0x180642b43`), the same convention as `FUN_18063d9e0`.

Stage 2, grain (SOLA splice): a triangular crossfade over `lag` samples, then a copy tail:

```
grain[j]     = ((lag-j)/lag)*in[c+j] + (j/lag)*in[c+lag+j]      j in [0, lag)
grain[lag..] = in[c+lag..]                                       bounded by 17640
hop = int(lag / (1/ratio - 1) + 0.5)   if ratio < 1
    = int(lag / (ratio - 1) + 0.5)     if ratio > 1
```

This changes duration without a discontinuity, not pitch.

Stage 3, 25-tap windowed sinc resample into `0x280`/`0x288`:

```
for i in [0, count):                       # count = hop+lag (down) / hop (up)
    c = int(i*ratio)
    for k in [c-12, c+12]:
        if k < 0: skip
        x = (i*ratio - k) * pi
        w = (x == 0) ? 1.0 : sinf(x) / x
        acc[cursor + i] += w * grain[k]
```

Both directions run this (`0x180643337` up, `0x180643a73` down, byte-identical). It's what moves the pitch; an earlier reading wrongly had the up branch as a plain copy.

Stage 4, mix: once the accumulator holds a block, `out = (1-mix)*dry + mix*acc` against this call's dry buffers, with no history or crossfade. The accumulator is `memmove`d down by the block length and zero-filled.

Implemented as `fx_dsp.fx_pitchshift` (`--no-pitchshift` disables). Over 8 capture-matched charts with scorable regions: +0.983 to +1.929 dB exclusive, delta +0.946 (+1.057 frame-weighted), 7 up, 0 down, other effects flat within 0.002. The reference set has 61 FX-button Pitch Shift notes in 12 capture-matched charts, longest 2.82 s.

One reading was settled by measurement. The pass tail at `0x180643472` (`lea esi, [rsi + r12*2]`) advances the source cursor, and `r12` looks like a running total of hops, which would accelerate the cursor through a held note. That renders badly (-0.815 dB against per-pass hop on the same 8 charts, and +12 semitones collapses to near-silence). The per-pass hop is the default; `--pitchshift-legacy-cursor` gives the accelerating reading. Probably a misattribution of which spilled stack slot `r12` reloads from across the vectorized tail; unproven.

The independent reimplementation (§9) renders this with `librosa` or `pyrubberband`, a different approximation that neither confirms nor contradicts the above.

### 4.11 Pitch & Speed (id 13, kind 14, wrapper `0x180632c10`)

Not composite or keyframed. The wrapper does no DSP: it reads three columns from the vector at `+0x190` (`+0x188` from the wrapper's base), builds `std::function<float(float)>` objects and calls one routine:

```
std::shared_ptr<BMSoundLib2017::WaveBuffer> ApplyPitchAndSpeed(
    short const*, unsigned __int64, int, int,
    std::function<float(float)>,   // 1: PITCH, semitones
    std::function<float(float)>,   // 2: SPEED, playback-rate multiplier
    std::function<float(float)>,   // 3: MIX, percent
    std::function<float(float)>)   // 4: TIME, progress remap
```

So `13, p1, p2, p3` is `mix%, semitones, speed`. The earlier `{i32 tick, float value}` keyframe reading misparsed a 12-byte record; case `0xd` in `FUN_18022db60` pushes three floats (`+0x16c`, `+0x170`, `+0x174`), one record per definition, none a tick.

Each parameter is honoured only if it differs from neutral, guarded by `FLT_EPSILON` (`|p2| > e` at `0x180632cf6`, `|p3 - 1| > e` at `0x180632db8`, `|p1 - 100| > e` at `0x180632e5b`). Otherwise an empty `std::function` is passed, read as "leave alone". So `13, 100.00, 0.00, 1.00` is a complete no-op, and it's the most common id-13 row. At mix 100 there's no mixing stage.

Speed is a playback rate, not a duration. `FUN_180784e10` advances a 16.16 position accumulator by `(int)(65536.0/speed + 0.5)` per input frame consumed. Speed 2 eats two input frames per output frame (pulling audio from after the note), 0.5 eats half, and `speed <= 0` freezes without consuming input. The corpus range is `p3` in {0, 0.5, 1, 2}. Pitch is `powf(2, semitones/12)` at `0x18062d92e`, unclamped (`p2` in [-24, 24]).

The dry reference isn't the dry track when speed is not 1. `FUN_18062ca80` renders twice: once with both parameters, and once more with the same speed and a constant-0 pitch lambda (`0x1802be750`, at `0x18062cf79`). The mix crossfades against that second render. At speed 1 the second pass is skipped (`0x18062ce2b`).

Buffer geometry: input runs from the note's first frame to the end of the buffer, not the note's end (`0x18062cd2f`), so speed > 1 can pull audio from after the note. Output is `end - start + 1` frames, `memcpy`d back (`0x180633227`).

The engine is a third-party FFT phase vocoder, PhaseGear (`BMSoundLib2017::PhaseGearDriverImpl`, ctor `0x180620010`, per-block driver `0x180620860`, `PhaseGearCore` / `PhaseGearSignalProc` / `PhaseGearLib::FFTHandler`). From `PhaseGearCore::Initialize` (`0x180784910`): frame `1 << (log2(sampleRate) - 4)` = 2048, synthesis hop `frame >> 2` (4x overlap), ring buffer primed with `frame/2` zeros. Pitch and speed reach it via `0x180784600` (`core+0x38`) and `0x180784620` (`core+0x34`), gated by `core+0x30`. A formant section (`core+0x44..0x4c`) and a four-band section (`core+0x60`, stride `0x18`) exist but this caller leaves them off.

Implemented as `fx_dsp.fx_pitch_speed` (`--no-pitch-speed` disables). The parameter contract is transcribed; the vocoder is not. It uses a textbook phase vocoder at PhaseGear's frame and hop with identity phase locking, plus a resample for pitch. Time and pitch mapping is exact (output frequency within 0.4% of `f(t * speed) * 2^(semitones/12)` for speed in {0.5, 1, 2} and semitones in {0, +-7, +-12}), but timbre is a stand-in. Treat score changes as evidence about the contract, not the vocoder. An id-13 note counts as applied even when all three columns are neutral.

## 5. Chart to DSP conversion

Wrappers convert chart values using the BPM at the effect's start (`60/BPM`, constant `0x18092e700`):

| effect | field | conversion | proven at |
|---|---|---|---|
| Retrigger / Echo | length | beats: `sec = beats * 60/BPM` | `0x180631198`, `0x180631271` |
| Gate | period | beats | `0x180631bb2` to `0x180631bbb` |
| Side Chain | period | beats | `0x180632552` |
| Wobble | rate | cycles per beat: `sec = (60/BPM) / rate` (reciprocal) | `0x180632aa0`, `0x180632ab6` |
| Flanger | period | measures: `rate = measures / secPerMeasure` | `0x180631f6b` to `0x180631f8d` |
| Tape Stop (id 4) | duration | seconds, passed through | inline case 7 |
| Tape Stop Ex (id 10) | duration, preroll, window | beats | `0x180632170` to `0x18063218a` |
| Bit Crusher | rate | raw sample count | `0x180630d10` |
| LPF / HPF | freqLo/Hi | Hz, plus the §4.2 exponent | `0x180630110` |

`FUN_18062e2e0` returns the beat numerator active at a position; the flanger uses it for `secPerMeasure`. A laser note's effect index is `noteField[4] - 1` (`FUN_18062ea60` at `0x18062ea7c`); an FX note's definition index is `noteField[4] - 2` (`FUN_18062e3d0` at `0x18062e3f0`).

### 5.1 Laser event grouping and slams

A laser event is a 20-byte struct per adjacent point pair: `{startSample, endSample, startKnob, endKnob, effectIndex}`. `FUN_18062ef70` groups events into runs that are contiguous in time and share an effect index. The wrapper bails unless the run is at least one block long (`FUN_18062ea60` at `18062ea7c`: `if (gen->blockSize <= (lastEnd - firstStart))`).

A slam (two points on one tick) is not an effect. It's a zero-duration step in the knob curve of the run it sits in, and the filter cutoff jumps across the whole `freqLo..freqHi` range in one block. On `2229_kamui` at 50.571 s the knob slams 127 to 0 on an HPF (40 to 2000 Hz, Q 3) and the 60 to 400 Hz band jumps 28x within 100 ms. So:

* Keep the knob curve stepped at slams. Don't smooth it or assume one filter per section.
* Split a run wherever the per-point effect index changes. Collapsing a section to one filter applies the wrong filter and misplaces the slam (18 s of audio on `2229_kamui`).
* An isolated slam (run shorter than one block) produces nothing.

**The pair has to be inside one section.** A laser point's node type (C2: 1 starts, 0 continues, 2 ends) matters: a chart can end one laser and start another on the same tick (`2` then `1`). That's a handoff, not a slam. The game draws two sections, plays nothing, and schedules no kind-6 event. Reading only ticks turns every handoff into a phantom slam: an event spanning both sections and a layered slam SE (§6.1). The knob does step there either way, but the event must not cross the boundary or the run picks up the wrong effect index. `render_chart.py` guarded the event builder (`if a[2] == 2: continue`) but not the SE trigger, so only the SE was audible.

Rare: 18 pairs against 584760 genuine ones across 8254 charts, in `2397_ultracharge_yutaimai_5m` (12), `2385_cyanotype_synthion_5m` (4), `0697_syousitsu_cosmo_4i` (1), `2088_xinca_tonarinoniwa_5m` (1), plus 2 in `2406_saihate_namv_5m` (not in this install; user-reported, measures 9 and 10). Each is a loud noise on a downbeat. On `2088_xinca_tonarinoniwa` MXM at 35.74 s, the render's error over 0.4 s falls from 5.584 to 3.158 dB with the guard (gain over dry +1.723 to +4.149; over 0.8 s, 4.245 to 2.858). Control windows move 0.000. The cabinet plays no slam sound at a `2`/`1` handoff. The note converter needs the same guard (see `scripts/notes/laser_curves.py`).

### 5.2 Retrigger is locked to the musical grid

Retrigger's repeat cycle runs on the song's grid, so a note starting mid-cycle joins it partway and can open by replaying audio from before the note. No other effect does this.

`FUN_18062e310` has three call sites: `0x18056e30d` (unrelated), `0x1806344ed`, and `0x1806310e5`, the last being Retrigger's wrapper `0x180630fa0`. The Echo/RetriggerEx wrapper (`0x180631390`) reaches the shared DSP at `0x1806316a7` with no snap. Echo is note-locked; Retrigger is grid-locked.

Args `(gen, notePos, lengthBeats, secPerBeat)`. It takes the last BPM-list (`gen+0x28`) and time-signature-list (`gen+0x30`) entries at or before `notePos`:

```
samplesPerBeat    = trunc(2646000 / BPM)
samplesPerMeasure = samplesPerBeat * timeSigNumerator       # raw numerator
period            = trunc(samplesPerBeat * lengthBeats)
anchor            = max(lastBpmChangePos, lastTimeSigChangePos)   # cmovle at 0x18062e387
offset            = ((notePos - anchor) % samplesPerMeasure) % period
if offset > period - 512:  offset = 0                       # 0x18092e884 = 512.0
return offset
```

The grid anchors at the later of the last BPM and time-signature change, and the 512-sample tolerance snaps forward when a note is nearly on a boundary. The wrapper does `snappedStart = notePos - offset` (`0x1806310ea`). Example: a 2-beat Retrigger at 210 BPM has `samplesPerBeat` 12600, `period` 25200. A note one beat in gets offset 12600, so with `count` 16 (1575-sample slices) it opens at slice 8.

`render_chart.py` computes this in `grid_snap_offset`, renders from `offset` samples before the note and discards the pre-roll. `--no-grid-snap` restores note-locked behaviour. Over the 14 best-aligned charts with off-grid Retrigger notes, snapping wins 14/14, mean +0.882 dB on exclusive frames, smallest margin +0.210.

Caveat: the engine uses integer samples with a truncating `samplesPerBeat`, while `Timeline.samples()` goes through float seconds. For BPMs not dividing 2646000 evenly, `grid_snap_offset` returns tens of samples where it should return zero. An integer-sample clock in `Timeline` would fix it.

### 5.3 `#BEAT RESOLUTION`

Cells per beat is per-chart, from the optional `#BEAT RESOLUTION` tag: 48 (absent) in 8088 charts, 144 in 1, 240 in 10, 480 in 8. On those 19, a renderer assuming 48 gets every time wrong by the ratio (10x on 480). Through the metric this looks like every DSP failing at once: `1972_guinevere_penoreri` scored -6 to -10 dB on Echo, Flanger, Gate, SideChain and HPF with good alignment (corr 0.607). A uniformly bad chart with good alignment means a chart-global input is wrong. `shared/vox_parser.py` always read it correctly; `Timeline` now takes it from the chart, with `res=` as an override.

### 5.3b The beat column is in denominator units

`Timeline.abs_tick` read the beat of `measure,beat,cell` as quarter notes (`measure_tick + beat * res + cell`). A beat is `res * 4 / den` cells: 48 in 4/4, 12 in 15/16. Measure lengths already used the denominator, so only positions inside non-`/4` measures were wrong, by a lot: `2152_nemsysarena_tonarinoniwa_3e` measure 55 (12/16) addresses beat 12 at true offset 132, but the old reading gave 528 in a 144-cell measure.

501 of 8254 charts have a non-`/4` signature, 416 place events where this moves, and 47,156 timing rows were pushed outside their own measure. On the 7751 `/4` charts it's a proven no-op.

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

## 6. Reference implementation

`fx_dsp.py` implements §4.1 to 4.9 on 16-bit WAVs in the same float domain with the same clamps and block structure. It needs `numpy` (optionally `scipy`) and `ffmpeg` for `.s3v`.

```bash
python scripts/audio/fx_dsp.py in.wav out.wav --effect retrigger --params 95,2.0,1.0,4,0.85,0.15
python scripts/audio/fx_dsp.py in.wav out.wav --effect laser_lpf --params 90,400,18000,0.7 --knob 0:0,4:127
python scripts/audio/fx_dsp.py in.wav out.wav --effect wobble --params 80,0,3,500,18000,4.0,1.4 --range 8:16
python scripts/audio/fx_dsp.py --list
```

`render_chart.py` drives it from a chart: parses the `.vox`, decodes the `.s3v`, applies every FX hold and laser segment, and adds the device ParamEq and music duck (§7.1) and the layered SE (§6.1).

```bash
python scripts/audio/render_chart.py data/music/2229_kamui_tjhangneil -d 5m -o kamui_fx.ogg
```

The `-o` extension picks the container (default Vorbis). The engine's int16 writeback happens first, so a lossy container sits on top of the game's output stage. Use `.wav` for the §7 metric.

Diagnostic flags:

```
device ParamEq (7.1)
  --no-peak          skip it
  --peak-delay S     knob lag (default 0.08, the engine's value)
  --peak-always      run it during every laser, not only C4 = 0
  --peak-post-se     put it after the SE mix
  --no-duck          skip the music duck; --duck-rate sets its ramp (default 0.33/s)
  --duck-hold        freeze the duck target between lasers (rejected, 6.1.4)
  --peak-gain-scale  multiplies the resonant gain (default 0.8, engine 1.0)
  --peak-max-gain    ceiling in dB (default 8, engine unclamped up to +15)

layered SE (6.1)
  --no-se            skip them
  --slam-index N     which virtical_shot sample a slam plays (0 or 1)
  --se-polyphonic    let overlapping slams sum instead of restarting one voice
  --se-trim X        multiplier on header-derived SE gains (default 1.2, carries the 6.1.4 gap)
  --slam-gain X      override the slam level, bypassing header and trim
  --se-gain X        the same for FX chip samples

effect behaviour
  --laser-mode M       chain | dry | add: how a laser combines with an FX hold (8.1)
  --no-grid-snap       start Retrigger at the note (5.2)
  --wobble-persist     carry Wobble's LFO across notes (4.9)
  --fx-chain-overlap   a second FX note reads what the first wrote (8.1)
  --fx-order-rl        process FX-R before FX-L (8.1)
  --laser-chain-overlap  let VOL-L and VOL-R stack (8.1)
  --no-auto-tab        skip #TRACK AUTO TAB spans (6.3)
  --no-param-assign-sweep  borrowed effects use authored parameters (6.3)
  --no-tapestop-ex     leave Tape Stop Ex dry (4.6b)
  --no-pitch-speed     leave id 13 dry (4.11)
  --tapestop-ex-floor X  the one fitted value (4.6b)
  --tapestop-ex-3phase   alternative phase model (9.3)
  --wobble-legacy-period read Wobble's C6 as a period (4.9)
  --mix-scale X        scale every effect's mix
  --no-stage-clip      keep float between stages (8.1)

output
  -b, --block N        per-block update size (default 512)
  --master-gain X      gain before the hard clip (6.2)
  --dry PATH           also write the untouched decode
```

`.vox` track layout: `#TRACK1` VOL-L, `#TRACK2` FX-L, `#TRACK3..6` BT-A..D, `#TRACK7` FX-R, `#TRACK8` VOL-R.

```
FX    C0 timing   C1 length(cells, 0=chip)   C2 chip:sample / hold:effect+2   C3 cells-per-chain
laser C0 timing   C1 position (v10 0..127, v12 0.0..1.0)   C2 node type (0 mid/1 start/2 end)
      C3 roll type   C4 LASER EFFECT   C5 range (1/2 wide)   C6 unused
      C7 curve type  C8 roll length    C9 cells-per-chain
```

C4 is the laser effect, not C7. C7 is the curve type; both range 0..5, and using C7 puts the wrong filters at the wrong times. Don't hardcode 48 cells per quarter (§5.3).

Worked example, `2229_kamui_tjhangneil` MXM, 210 BPM: 12 FX defs, 5 laser defs, 153.1 s. FX buttons: Echo x28, Flanger x22, Gate x11, BitCrusher x11, Wobble x10, TapeStop x8, HPF x7, Retrigger x1. Lasers: LPF x6, BitCrusher x4, HPF x2 (C4=1..5), and 57 peak-filter runs (C4=0). Device EQ is active 67.2 s of 153.1 s with the knob reaching 127. Layered SE: 138 laser slams and 3 sampled FX chips. FX chips make no track effect (zero length, and wrappers need a full block) but do trigger a sample.

### 6.1 The layered SE bank

Two gameplay events mix a sample over the track from `data/sound/ver5/general_sampler.s3p` (bank id 9, registered at `0x1805c5960`; `sys_sd_shotfx.2dx` is bank 4 with the same 15 names).

```
'S3P0', u32 count, count * { u32 offset, u32 size }
each entry: 'S3V0', u32 headerSize, ... , then an ASF/WMA stream at +headerSize
```

| idx | name | dur | attack | role |
|---|---|---|---|---|
| 0 | `fs00_virtical_se01` | 1.78 s | 228 ms | laser slam (played from bank `0xd`, 6.1.1) |
| 1 | `fs01_virtical_se02` | 3.03 s | 1.1 ms | also a laser sound; trigger unknown |
| 2 to 14 | `fs02_shot01` to `fs14_shot13` | 0.40 to 6.15 s | 1 to 30 ms | FX chip hits |

Which chip sample plays is the FX note's C2, the same column that means "effect + 2" on a hold. On a chip it's a `general_sampler` index, with 0 and 255 both silence (110 of 111 FX-L chips on `2229_kamui` are 0; 3 of 228 chips are sampled). Names are in `vox_format.md` under `#TRACK2`/`#TRACK7`. There is no default sample.

### 6.1.1 Trigger code

Voice API: `Play = FUN_1805c6ec0(this, bankId, sampleIdx, flag)` (voice `vtable+0x10`), `SetVolume = FUN_1805c6e40(this, bankId, sampleIdx, vol)` (`vtable+0x40`, `vol/127`). Both triggers are in the event dispatcher `FUN_180407200`. Ghidra types its selector as `float`, so case labels render as denormals (`2.8026e-45` = 2, `4.2039e-45` = 3, and so on); they're int bit patterns.

FX chip, case 4:

```c
if ((0 < (int)idx) && (idx != 255)) {
    snd = FUN_1800967c0();
    FUN_1805c6ec0(snd, 9, idx);        // bank 9 = ver5/general_sampler
}
```

Case 3 also mirrors the laser (`if (field == 2) v = 1.0f - v;`), confirming §7.1.

Laser slam is two-stage, and only a genuine same-section slam schedules one (§5.1). Event kind 6 (`0x18040773a`, tag 5) is a scheduled play request, queued at `gameAudio+0x80`:

```c
entry.index = event.a;                                     // event+0x08, verbatim
entry.due   = now - (long long)((event.time - audioPos) * 1000.0f);
```

Drained later in the same call once `entry.due < now`:

```c
FUN_1805c6ec0(snd, 0xd, entry.index, 0);   // bank 0xd = ver5/virtical_shot
```

The slam comes from bank `0xd` (`/data/sound/ver5/virtical_shot.s3p`, two entries with the same sizes as `general_sampler`'s first two, 58804 / 148132 bytes, same audio), not `general_sampler`. The sample index comes from the event (`event+0x08`), chosen by whatever builds kind-6 events upstream of `Game::GameAudio`. That producer was never found (the vector arrives as `Update`'s second argument; field-store scans and vtable xrefs didn't reach it; `FUN_18041c220` constructs the object at `world+0xb8`). Every measured chart uses index 0. `render_chart.py` uses `general_sampler[0]`, byte-identical to `virtical_shot[0]`; `--slam-index 1` selects the other.

Bank table, from `FUN_1805c5960`:

```
0 sys_sd_credit.2dx   1 sys_sd_sram.2dx    2 <the song's own .s3v, loaded per song>
3 sys_sd.2dx          4 sys_sd_shotfx.2dx  6 00_title_bgm_06   7 sys_sd_virtical.2dx
8 ver6/bgm_00         9 ver5/general_sampler   0xd ver5/virtical_shot
0xe voice_mitsuru_00  0xf voice_tama_00     0x10 hexa    0xa..0xc,0x11..0x18 ver6/se_*
```

### 6.1.2 No level goes through Play

Every sampled-SE `Play` passes a flag of zero:

```
FX chip   0x18040752a:  xor r9d, r9d ; mov r8d, [rdi-4] ; lea edx, [r9+9]  ; call Play
slam      0x1804080e4:  xor r9d, r9d ; mov r8d, [rcx]   ; lea edx, [r9+0xd]; call Play
```

`Play` forwards to voice `vtable+0x10` (`0x1806a1cc0`), which takes no gain. The voice starts at unity (`VoiceImpl` ctor `0x1806a183a`: volume 1.0, pan 0.0, ramp target 1.0), and none of the 19 `SetVolume` call sites names bank 9 or `0xd`. `voice+0x70` stays at unity for the track.

`FUN_1806a3640(voice, bit, value)` writes one of 8 gain factors and rebuilds a 256-entry table at `voice+0x6c` indexed by active-factor bitmask:

```
bit 0 -> [+0x70]   bit 1 -> [+0x74]   bit 2 -> [+0x7c]   bit 3 -> [+0x8c]
bit 4 -> [+0xac]   bit 5 -> [+0xec]   bit 6 -> [+0x16c]  bit 7 -> [+0x26c]
entry[mask] = product of factors whose bits are set   (entry[0] = 1.0)
```

The other seven factors are set by virtual dispatch and weren't traced. None holds the SE level.

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

### 6.1.3 One voice per sample

`Play` resolves to a single persistent voice per `(bank, sampleIndex)`, allocated at bank load:

```c
voices = FUN_1805c5830(bank);                  // vector<shared_ptr<Voice>>, 16 bytes/entry
voice  = voices[index];
voice->vtable[0x10](flag);
```

Retriggering a sounding sample restarts that voice; it doesn't sum. Slams run 1.78 s but come far faster: on `2229_kamui` MXM, 138 slam points make 124 distinct onsets (14 are VOL-L and VOL-R slamming together, one Play), the median gap is 0.429 s (min 0.000, max 13.286), and up to 10 copies would overlap if layered. Layering scores 1.889; one-voice restart scores 1.858. `render_chart.py` restarts by default and truncates each slam at the next onset; `--se-polyphonic` sums.

### 6.1.4 Per-sample gain is in the `S3V0` header

Each `.s3p` entry and each standalone `.s3v` starts with a 32-byte header:

```
+0x00  'S3V0'
+0x04  u32   header size (always 0x20)
+0x08  u32   payload size
+0x0c  u32   checksum
+0x10  u32   (0 for every gameplay sample)
+0x14  i16   gain, 8.8 fixed-point dB          <-- the level
+0x16  i16   gain trim, same units (0 for gameplay samples)
+0x18  u32   (0)
+0x1c  i16   pan, /32768 (0 for gameplay samples)
```

The bank loader (`0x1805ce7b0`, `'S3V0'` check at `0x1805ce834`):

```
1805cec47  movsx r13d, word [rbp+4]      ; hdr +0x14
1805cec4c  movsx ecx,  word [rbp+6]      ; hdr +0x16
1805cec50  add   ecx, r13d
           xmm1 = (float)((double)ecx * 0.00390625) * 0.05     ; /256 dB, then /20
           xmm0 = 10.0
1805cec6b  call  powf                                          ; 0x18076b420
1805cec76  call  rbx                     ; voice->GetMixerConnection(0)->SetGain(xmm1)
           ... then pan: (float)((double)(i16)hdr[+0x1c] * (1/32768)) -> voice vtable+0x50
```

```
gain = 10 ^ ( ( (i16)hdr[0x14] + (i16)hdr[0x16] ) / 256 / 20 )
```

`0.00390625` is 1/256 and `0.05` is 1/20. File values are mostly multiples of `0x80` (0.5 dB steps).

The target isn't `voice+0x70`. `VoiceImpl::vtable+0xd0` (`0x1806a2fc0`) returns `this->connections[i]`, and `MixerConnectionImpl::vtable+0x20` (`0x1802fbf40`) is one instruction, `movss [conn+0x20], xmm1`. The connection starts at 1.0, the header value overwrites it, and nothing touches it again, which is why searches through `Play` and `SetVolume` found nothing. The standalone `.s3v` loader (`0x1805cf8c8`) does the same, so the song goes through it too.

| bank | sample | `hdr+0x14` | dB | linear |
|---|---|---|---|---|
| `0xd` virtical_shot | 0 `fs00_virtical_se01` (slam) | -1324 | -5.172 | 0.5513 |
| `0xd` virtical_shot | 1 `fs01_virtical_se02` | -2072 | -8.094 | 0.3938 |
| 9 general_sampler | 0, 1 | -1324 | -5.172 | 0.5513 |
| 9 general_sampler | 2..13 (FX chips) | -3328 | -13.000 | 0.2239 |
| 9 general_sampler | 14 `fs14_shot13` | 0 | 0.000 | 1.0000 |
| 2 | `2229_kamui_tjhangneil.s3v` (music) | 0 | 0.000 | 1.0000 |

Chips are 7.83 dB below the slam, and the music is at unity, so these are the SE-to-music ratio. `virtical_shot[1]` and `general_sampler[1]` are byte-identical audio with different header gains, so the field is authored per bank instance.

**It doesn't fully agree with the capture.** Sweeping the slam gain with chips pinned at 0.2239:

```
slam gain   0.40   0.45   0.50   0.5513   0.60   0.65   0.70   0.78
score       1.943  1.897  1.858  1.826    1.807  1.797  1.797  1.816
```

The optimum is about 0.69, 2 dB above the header. It's not a metric artefact: scoring only the 1187 frames a slam is sounding in, with the level offset taken far from any slam, gives the same answer. Chips are unmeasurable on this chart.

Ruled out: a per-bank level (`FUN_1805c63b0` takes no gain; registration passes only ids and paths); the duck resting below unity (`0x1805c7b3d` loads `1.0` when the knob is under 4); freezing the duck between lasers (`--duck-hold` costs 0.34); additive layering (worse at any gain); another module owning the mixer (`S3P0`/`S3V0`/`2DX9` appear only in `soundvoltex.dll`).

Since the metric only sees the SE:music ratio, a constant x0.8 on the music path would explain it. Lead: the music is bank 2, loaded through the standalone `.s3v` loader (`0x1805cf8c8`), which has a second `powf` result at `[rsp+0x60]` whose consumer was never traced. The `.s3p` loader has the same loose end, appending the gain to a `std::vector<float>` (`0x1805ced2c`) that's never seen read.

`load_s3p` returns each sample's header gain, and every SE mixes at `header_gain * --se-trim`. The trim carries the unexplained 2 dB and nothing else (`--se-trim 1.0` plays what the files say). `--slam-gain`/`--se-gain` bypass both.

### 6.2 Output stage: `CGainWithHardLimiter`

`BMSoundLib2017::CGainWithHardLimiter::Process` (`0x18069f090`, vftable `0x180925df8`):

```
gain  = this->0x18 (float)     set by 0x1802f8120
limit = this->0x1c (float)     set by 0x1802fbf30 (both at once: 0x1802ffe90)
for each sample (SSE, 4 at a time):
    x = x * gain
    x = min(max(x, -limit), +limit)
```

A gain and a hard clip, with no knee, lookahead or release. The game clips its own output, so hot SE is authentic and picking a level that never clips makes slams inaudible. `--master-gain` exposes it.

### 6.3 `#TRACK AUTO TAB` and `#TAB PARAM ASSIGN INFO`

`#TRACK AUTO TAB` lets a laser span run an effect pair borrowed from `#FXBUTTON EFFECT INFO`. `#TAB PARAM ASSIGN INFO` optionally attaches "laser position drives this pair's Nth parameter between these bounds". `render_chart.py` applies both by default (`--no-auto-tab`, `--no-param-assign-sweep`), worth +1.07 dB and +0.698 dB.

Corpus usage over 8107 charts: AUTO TAB non-empty in 2738 (33.8%); PARAM ASSIGN present (24 rows) in every chart but only 431 (5.3%) have nonzero C1 to C3; `#TRACK ORIGINAL L/R` non-empty in 2488 (30.7%).

```
#TAB PARAM ASSIGN INFO, one row per #FXBUTTON EFFECT INFO slot (24 rows = 12 pairs x 2):
  C0  effect-pair index, 0-indexed (always 0,0,1,1,...,11,11)
  C1  index of the pair's own parameter to modulate (0 = none)
  C2/C3  bounds the parameter is swept between

#TRACK AUTO TAB rows (same shape as an FX hold):
  C0 timing   C1 length (cells)   C2 effect index, 2-INDEXED: pair = C2 - 2
```

The two sections use different index bases. Across 2128 AUTO TAB rows in charts with modulation, C2 spans 2..13 (twelve values for twelve pairs, which a 0-indexed reading can't place), and read 2-indexed a span lands on a modulated pair 40.7% of the time against 13.1% (chance) read 0-indexed.

The sweep is `value = C2 + (C3 - C2) * clamp(laserValue, 0, 1)`, refreshed every 512 samples, with `param1`/`param2` chosen by chain position. The control source is a C4=6 laser, which is why C4=6 isn't inert. The formula came from the independent reimplementation (§9) and was confirmed by measurement.

Example: `0002_broken_iroha`'s single AUTO TAB row `021,03,00  96  8` selects pair 8-2=6, the pair its one nonzero assign row modulates (`6, 3, 3.00, 0.50`: param 3 of a Flanger, its period, swept 3.00 to 0.50 measures). About 59% of AUTO TAB spans land on an unmodulated pair and run at authored parameters.

`#TRACK ORIGINAL L/R` don't matter for audio: they hold only the un-interpolated control points, and `#TRACK1`/`#TRACK8` already carry the played sequence.

## 7. Calibration against a cabinet capture

`scripts/audio/reference/kamui_goal.ogg` records the cabinet playing `2229_kamui_tjhangneil`. It's polarity-inverted, Ogg-coded, and drifts +0.346 samples/s (7.9 ppm; +45 samples over the track), so sample-exact diffing is impossible (coherent averaging over 124 slams gave correlation <= 0.06).

The metric is phase-insensitive: 46 log-spaced bands per 46 ms frame, level-normalised, mean |dB| difference (`spectral_metric.py`). The floor is codec noise: an untouched track scores 1.22 on frames where the chart does nothing. `check_one_chart.py` generalises it with automatic alignment, and `check_all_charts.py` aggregates over the corpus.

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

### 7.1 The default laser filter, transcribed

Read from the binary. It goes through the gameplay event dispatcher and the sound device, not the effect generator.

`FUN_180407200` (`Game::GameAudio::Update`, vtable slot 1 at `0x1808cb848`) walks 28-byte events:

```
+0x00  ?                 +0x04  int  kind (2..7, the switch selector)
+0x08  int   a           +0x0c  float pos / time
+0x10  int   b           +0x18  byte variant tag (= kind - 1)
```

Kind 3 is a laser (`0x1804074aa`, asserts tag 2). Per tick one accumulator covers every laser event:

```c
disableEq = (event.b != 0);                       // event+0x10
v = (event.a == 2) ? 1.0f - event.pos             // event+0x08: 1 = VOL-L, 2 = VOL-R
                   : event.pos;
acc = max(acc, v);                                // both knobs share one filter
```

`acc` is queued with a timestamp at `gameAudio+0x58` and popped only once the head is older than 80 ms (`comiss xmm0, 0.08` at `0x180407f61`), so the filter lags the knob. If `disableEq`, the queue is flushed and the knob forced to 0. The popped value times 127 goes to `FUN_1805c7a00`:

```c
v  = clamp((int)knob, 0, 127);
fc = clamp(TABLE[v], 80.0f, 16000.0f);            // DSFXPARAMEQ_CENTER_MIN/MAX
if      (fc <  200)  bw = gain = fc * 0.075f;     // 6.0 .. 15.0
else if (fc < 1000)  bw = gain = 15.0f;
else               { bw   = 15.0f - (fc-1000)*0.0003f;    // 15.0 .. 10.5
                     gain = 15.0f - (fc-1000)*0.0005f; }  // 15.0 ..  7.5
if (v < 4) gain = 0.0f;                           // dead zone

FUN_180626b30(device, 0, fc, bw, gain);           // -> _DSFXParamEq slot 0 of 7
```

`TABLE` is 128 floats at `DAT_18090c050`, a hand-drawn piecewise-linear ramp: `0, 6, 12 ... 54, 100, 106 ... 202, 232 ... 3672, 3852 ... 6912, 7400, 7700, 8000, 8400 ... 10800`. The first ten entries read as 80 Hz after clamping.

The struct is `{fCenter, fBandwidth, fGain}` (`FUN_180626b30` writes args 3 to 5 to `[rsp+0x20/0x24/0x28]`). `fGain` is zeroed in the dead zone: bandwidth 0 would be out of range, gain 0 is "EQ off".

The DMO isn't in this binary. `CDmoSoundFxAudioProcessor<_DSFXParamEq>` (`0x180919970`) and `CDmoSoundFxDriver<IDirectSoundFXParamEq,_DSFXParamEq>` (`0x180919998`) forward to a COM object at `this+0x10`; the math is Microsoft's `GUID_DSFX_STANDARD_PARAMEQ`. `fx_dsp.peaking_coeffs_bw` models it as the RBJ peaking filter with `BW(octaves) = fBandwidth / 12`, an assumption since corroborated by the independent reimplementation (§9.1).

The same call ducks the music. Bank 2 is the song's `.s3v` (registered per song by `FUN_1805c63b0(this, 2, path)`, up to 6 stems). Every bank-2 voice gets a target gain:

```c
if (v <  4)  g = 1.0f;
if (v < 95)  g = 0.8f - (v - 4) * 0.0025274728f;  // 0.800 .. 0.570
if (v < 100) g = 0.57f;
if (v < 120) g = 0.57f + (v - 100) * 0.011500001f;
else         g = 0.8f;
```

Voice `vtable+0x60` (`0x1806a21f0`) writes a target, and the mixer chases it at 0.33 gain/s (`0x1806a25b1`).

Placement was settled by measurement: before the layered SE scores 1.924, after scores 2.029. Slot 0 of the 7 ParamEq slots is on the music path, upstream of the SE voices. Three predictions are confirmed by the capture:

| prediction | test | result |
|---|---|---|
| 80 ms queue delay | sweep `--peak-delay` | minimum at 0.08 s (0.06: 2.088, 0.08: 1.924, 0.10: 2.155) |
| `event+0x10 != 0` mutes the EQ | `--peak-always` | tab-laser 2.787 to 3.820; peak-laser unchanged. That field is the C4 effect index |
| the duck exists | `--no-duck` | 1.924 to 2.195 |

**Deliberate deviation.** Every number above was scored on the plain transcription, and `paramq_from_knob`'s defaults are `gain_scale=1.0, max_gain_db=None`. But `render_chart.py` defaults `--peak-gain-scale` to 0.8 and `--peak-max-gain` to 8, so a plain run renders a dampened EQ. The boost is authentic (an ablation against the capture is worse without it) but unpleasant for conversion listening, so comfort won by default.

To reproduce this section's numbers, `check_one_chart.py`/`check_all_charts.py` need `--extra="--peak-gain-scale 1.0 --peak-max-gain 15"`.

### 7.2 SE levels

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

## 8. Known gaps

* The SE-to-music level is derived (6.1.4) but about 2 dB under the fit.
* What selects `fs00_virtical_se01` or `fs01_virtical_se02` is authored into the kind-6 event stream, and its producer wasn't found (6.1.1). Note and laser events likely share that vector.
* Kind 14 (id 13): the PhaseGear internals. `fx_pitch_speed` uses a textbook vocoder at PhaseGear's frame (2048) and hop (512). Transcribing `PhaseGearSignalProc` (`0x180787e20` init, `0x1807894b0` synthesis, `PhaseGearLib::FFTHandlerF`) would close it.
* Kind 14's fourth function remaps the note's 0..1 progress before the other three are sampled. In this build it's the identity lambda at `0x1802be750` and nothing uses it.
* Tape Stop Ex's floor (`this+0x46`) and phase field (`this+0x224`) are untraced.
* State continuity is threaded for Wobble only; BitCrusher and Gate are probably object members too (4.9).
* Game block size is the audio callback size (`gen+0x1a0`). Match `--block` when diffing against a capture.
* `Timeline` uses float seconds; the engine uses integer samples (5.2).

### 8.1 Effect combination

With `x` the track, `A` the FX-button effect and `B` the laser effect:

| model | meaning | result |
|---|---|---|
| chain | series | `B(A(x))` |
| dry | `B` reads the original and replaces `A` where they overlap | `B(x)` |
| add | parallel, changes sum | `x + (A(x) - x) + (B(x) - x)` |

**FX-L + FX-R both held: not chained, the later note overwrites.** `FUN_18062e3d0` handles one note, and its `lVar19 < 2` loop walks the pair's two effects, not the two buttons (the map at `gen+0x38` stores each pair as two `{kind, index}` entries at stride 8). Those two do chain:

```
if (lVar19 == 1 && iVar6 != -1) {            // second member of the pair
    memcpy(param_5, param_4, param_6 * 2);   // scratch <- destination
    puVar5 = *param_1; *puVar5 = param_5;    // generator source := scratch
}
```

On exit the source is restored to the original track (`if (1 < lVar19) { puVar5 = *param_1; *puVar5 = param_2; ... }`). The caller `FUN_18062ef70` calls the dispatcher once per FX note over a list at `gen+0x20`, all reading the same restored `param_2` and writing the same `param_4` (seeded with a copy of dry). So a second FX note reads dry and overwrites the first where they overlap.

Not an edge case: across 8255 charts, FX-L and FX-R overlap on 18776 same-pair and 9664 different-pair holds. The exposing case is `2337_recipinoriddle_oster` 5m, m114 b4, where both buttons hold the same Wobble + PitchSpeed pair for a bar. Chained, the 4 to 8 kHz band sits 11 dB below the capture with modulation depth 0.083 (capture 0.165). Reading dry per note puts the band within 0.8 dB at depth 0.192, and improves every scored region: Wobble +0.301 to +0.592, PitchSpeed +0.461 to +0.697, Tape Stop Ex +3.204 to +3.552. `--fx-chain-overlap` restores chaining.

Which note is last is open: it's the order of the list at `gen+0x20`, whose producer wasn't traced. The renderer does FX-L then FX-R (FX-R wins ties); `--fx-order-rl` swaps. It doesn't matter for same-pair overlaps, and no capture-matched chart with a long different-pair overlap has been scored both ways.

**Default peak filter + anything:** a separate stage. The C4=0 sound is a device ParamEq (7.1), downstream of the generator and upstream of the SE mix, so it always stacks on top.

**Tab laser (C4 1..5) + FX button: chain.** This was long recorded as the one place disassembly and capture disagreed, because `FUN_18062e3d0` restores the source to the original track on exit. That restore is about FX notes, so the next note reads dry. The laser stage reads what `FUN_18062ef70` sets just before the run loop:

```
memcpy(scratch, param_4, len);      // scratch <- the DESTINATION, i.e. the FX result
puVar23 = *param_1;
*puVar23 = scratch;                 // generator source := that snapshot
...
for (run = first; run != last; run += 0x18)
    FUN_18062ea60(param_1, param_4, run);
```

A laser reads what the FX buttons wrote: no disagreement. Measured over the 20 charts with most overlap, scoring overlap frames:

```
16 charts, 4656 overlap frames:
  chain  mean +2.706  frame-weighted +2.696  wins 13/16
  dry    mean +2.096  frame-weighted +2.098  wins  3/16
  add    mean +0.895  frame-weighted +0.978  wins  0/16
```

The three charts preferring `dry` do so by 0.1 to 0.5 dB, inside the spread; `add` is out. The independent reimplementation also reads `chain` (9.1).

**Laser + laser: snapshot, then overwrite.** The snapshot is taken once before the run loop, and each `FUN_18062ea60` call `memcpy`s its result over the destination. Two live laser runs read the same pre-laser audio and the later wins the overlap, so VOL-L and VOL-R stack onto the FX buttons but not each other. Found from `2335_specterchaser_coyaan` 5m measure 62 beats 3 to 4: VOL-L held at 1.0 and VOL-R sweeping, both on C4=2 (LPF 600 to 15000 Hz, Q 5), no FX live. VOL-L pins the LPF at 600 Hz, so chaining buries the region: mean band deviation 9.78 dB against 2.51 dB for the later run alone. `--laser-chain-overlap` restores stacking.

The same region speaks to §4.1b: the capture shows the authored Q=5 resonance (0.8 to 1.6 kHz at -7.2 dB against -12.8 dry), and uncapped Q takes the deviation from 2.51 to 0.94 dB, essentially onto the capture. On a high-Q laser the cap is not a rounding difference.

**Where effects stack:** mix compounds, since each effect computes against its own input (two effects at 50% leave the original at 25%). And there's an int16 requantisation between stages (`FUN_18063dc40` to `FUN_18063d9e0`, §2), so a chain can clip mid-chain where all-float wouldn't. `--no-stage-clip` disables it; the engine clips, so the default keeps it. That's per stage, not licence to requantise inside a leaf (§4.1).

### 8.2 High-Q laser passages run about 1 dB hot

Unresolved and small. On `2226_gryphone_etia` 5m measures 30 to 33 (fast laser wiggle through the tab LPF at Q 5.0), the render rises +1.9 dB over its whole-track level and the capture +1.0 dB, an overshoot of about 0.9 dB and 0.35% of the window's samples clipping. The metric barely sees it (3.542 rendered against 4.895 dry; the overshoot moves it 0.005), so it needs a level measurement.

The truncating feedback of §4.1 masked about 0.3 dB of this, which is why it was introduced; removing it shows the overshoot rather than causing it. Candidates: the tab LPF's Q 5 against its `(1 - Q*0.04)` trim, the device ParamEq stacking on top (7.1), and `chain` compounding both. `CGainWithHardLimiter` has no knee, so the excess is ours.

## 9. Cross-check against `Rosemoe/sdvx-sfx-renderer`

An independent reimplementation of the same engine (https://github.com/Rosemoe/sdvx-sfx-renderer, IDA-based, about 4000 lines of Python). It doesn't model SE bank levels, the music duck or the peak filter's queue delay. Where two independent traces agree, that's stronger evidence; where they differ, one is wrong.

### 9.1 Agreement

* The ParamEq (7.1): identical 128-entry table, `[80, 16000]` clamp, bandwidth/gain curves, `knob < 4` dead zone, and the same `bandwidth / 12` octave reading.
* The effect-id table (§3): 11 of 13 ids, including both corrections (id 3 Flanger, id 12 High Pass).
* Wobble's five waves, its `(1 - Q*0.04)` trim and column layout `filterType, waveType, mix, freqA, freqB, rate, Q`.
* Laser handling: VOL-R as `1 - pos`, VOL-L raw, `max()` into one accumulator.
* `#TRACK AUTO TAB`'s effect column is 2-indexed.
* A tab laser reads the FX-button result (chain, 8.1).
* Tape Stop (id 4) duration in seconds, and `#BEAT RESOLUTION` per chart.

### 9.2 What it supplied

* Wobble's rate field (4.9): their code names C6 `frequency` and divides by it. Confirmed in our disassembly; 13/13 charts improved, +0.878 dB.
* A model for the `#TAB PARAM ASSIGN INFO` sweep (6.3): `min + (max - min) * laserValue`, clamped 0 to 1, refreshed every 512 samples. Adopted and measured.
* C4=6 is the param-assign control source, not an inert laser.
* Composite id 13 typed as `PITCH_SHIFT_EX` with fields `(mix, semitones, ex_param)`. Half right: 4.11 later showed `p2` is semitones and the third field is a playback-speed multiplier.

### 9.3 Disagreements

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
