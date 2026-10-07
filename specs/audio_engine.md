# SOUND VOLTEX audio engine

Target: `modules/soundvoltex.dll` (PE32+ x64, ImageBase `0x180000000`, `SoundVoltex6_x64Release`, 2025-06-19). All addresses are virtual addresses in it.

Read from MSVC RTTI, Ghidra 12.1.2 and capstone, and checked against the charts in `data/music/` and the cabinet recordings in `scripts/shared/reference/ksh/`. Two values are fitted rather than transcribed: Tape Stop Ex's envelope floor (§4.6b) and the SE trim (§7.2). Two renderer defaults soften the transcription for listening: the resonance cap (§4.1b) and the peak-EQ gain (§7.1). For a plain-language intro, see [`audio_engine_primer.md`](audio_engine_primer.md). Measurements are in [`evidence/audio_engine.md`](evidence/audio_engine.md).

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
* Processing is blocked. The block length is `gen+0x1a0`, the audio callback's frame count. Coefficients and LFOs update once per block, so the output depends on block size; match `--block` when comparing against a capture. Laser filters start 64 samples early. Only Retrigger is snapped to the musical grid (§5.2).
* `FUN_18063d9e0` zeroes both channels of any frame whose left sample is exactly 0.

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

Lasers (`#TAB EFFECT INFO`) reuse the same vectors and leaves, registered into a second map (`gen+0x58`, against `gen+0x38`) by `FUN_180639290/360/430`:

| id | kind | vec | wrapper | leaf | effect |
|---|---|---|---|---|---|
| 1 | 1 | 0x70 | `0x180630110` | `0x18063df40` | Low Pass (knob-swept) |
| 2 | 2 | 0x88 | `0x1806303f0` | `0x18063e500` | High Pass (knob-swept) |
| 3 | 3 | 0xa0 | `0x180630a20` | `0x18063fc60` | Bit Crusher (knob-swept) |

A laser node's effect comes from `#TRACK1`/`#TRACK8` column C4: `0` is the peak filter (default), `1..5` index `#TAB EFFECT INFO` (1-indexed), and `6` has no filter but is the control source for `#TAB PARAM ASSIGN INFO` (§6.3). `FUN_18062ea60` keys its map on `noteField[4] - 1`.

The peak filter, used by most laser nodes, isn't in this engine. C4=0 gives key `-1`, the no-op sentinel `FUN_18063a070` installs (`laserMap[-1] = kind 0`). It's a DirectSound ParamEq driven from the gameplay event dispatcher (§7.1). The band-pass at `0x18063eb10` is reachable only through Wobble.

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

The `(1 - Q*0.04)` trim applies to the mixed signal, so it attenuates the dry path too and laser sweeps duck slightly.

The filter history is float. `FUN_18063e500` keeps raw filter outputs in float buffers at `gen+0x48` (L) and `gen+0x50` (R) and reads them back on the next sample. The mixed, trimmed result goes to separate wet buffers (`gen+0x58`/`0x60`). The only int16 clamp is `FUN_18063dc40`, once per stage (§8.1).

### 4.1b Resonance cap

The engine uses the authored Q unscaled: wrapper `FUN_180630760` passes mix, cutoff and Q straight to `FUN_18063e500`. Tab LPF/HPF definitions are mostly Q=0.7 (no peak), Q=3.0 (+9.5 dB) or Q=5.0 (+14.0 dB). Wobble is almost always Q=1.4 and has its own makeup gain.

`render_chart.py` caps the resonant peak of every LPF/HPF that takes a chart Q (laser and FX-button, not Wobble) at 6 dB by default (`--filter-max-resonance`) for listening comfort. `--filter-max-resonance 99` renders the transcription, and `fx_dsp.damp_resonance`'s own defaults are inert. To reproduce numbers measured before the cap, including §4.1 and §9, pass `--extra="--filter-max-resonance 99"` along with the §7.1 flags.

### 4.2 Laser / knob sweep (wrappers `0x180630110` LPF, `0x1806303f0` + `0x180630760` HPF)

Params `{mix, freqLo, freqHi, Q}`. Per block:

```
lo    = max(freqLo, 1.0)
ratio = freqHi / lo
v     = knob position 0..127, linearly interpolated across the segment
LPF:  cutoff = lo * ratio ** (1 - v/127)      # v=0 -> freqHi, v=127 -> freqLo
HPF:  cutoff = lo * ratio ** (    v/127)      # v=0 -> freqLo, v=127 -> freqHi
```

`1/127 = 0.007874016f`.

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

The right channel uses the same `k`. The counter is function-local, so the hold grid restarts every block.

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

The leading integer is the repeat `count`, passed through unchanged (`0x180631285`). Id 8 (Echo) feeds the same routine with a 7th field that the wrapper reads. It's `0.00` in every chart, and its purpose is unknown.

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

The 16-entry int32 table at `struct+0x10` defaults (from `FUN_18022db60`) to `{32, 4}` repeated 8 times, giving gains of 1.0304 (+0.26 dB) and 0.1288 (-17.8 dB).

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

Id 10 fades in from a floor, where Tape Stop fades out. Params: `mix, speed, duration, preroll, window`. The three time fields are in beats: wrapper `0x1806320d0` multiplies them by `60/BPM` (`0x180632170` to `0x18063218a`) and re-reads BPM every block. After conversion, in seconds:

```
m       = clamp(mix, 0, 100) / 100
speed   = clamp(speed, 1.0, 10.0)
dur     = clamp(duration, 0.1, 2.0) * 44100
window  = clamp(window,   0.1, 2.0) * 44100    # spin-up window
preroll = max(preroll, 0.0) * 44100            # no upper clamp
```

State is a running absolute sample position `pos` at `this+0x214`, incremented by block length per call. Three phases:

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
  The envelope ramps up from `floor` to 1.0 while the read head speeds up: a spin-up.
* `pos > preroll + window`: `(1-m)*dry`.

The record buffer comes from the track, not the note. It's up to `window` long and often runs past the note's end, so `fx_tapestop_ex` takes `lookahead=(fullL, fullR, offset)`. A note shorter than its preroll produces nothing, so many id-10 notes are silent.

The floor is fitted, because nothing traced writes `this+0x46`. 0.5 ships, and `--tapestop-ex-floor` overrides it. The field at `this+0x224` is also untraced.

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

C6 is a rate in cycles per beat. The wrapper takes `1.0 / field[5]` (`0x180632aa0`) and scales it by `60.0 / BPM` (`0x180632ab6`):

```
periodSec = (60 / BPM) / C6
```

So `6, 0, 3, 80.00, 500.00, 18000.00, 4.00, 1.40` is an LPF with a log-triangle wave, 80% wet, sweeping 500 to 18000 Hz at 4 wobbles per beat, Q=1.4.

The LFO counter restarts at every note. It's a member at `this+0x238`, but `FUN_180632820` zeroes it before each note's block loop (`mov dword ptr [rax + 0x238], 0` at `0x1806329eb`), so it carries across blocks only within a note. BitCrusher's hold position and Gate's step counter don't carry across notes either.

### 4.10 Pitch Shift (`0x1806429b0`)

SOLA splice plus sinc resample. The routine takes five arguments `(this, blockLen, blockOffsetFrames, mix, amount)`, with `amount` on the stack at `[rsp+0x160]`, which Ghidra's decompile drops.

Conditioning (`0x180642a2a` to `0x180642a9c`):

```
mix    = (mix >= 0 ? min(mix, 100) : 0) * 0.01
amount: if (amount >= -12) { a = min(amount, 12); if (a < 0) a = min(a, -1); }
        else                 a = -12
        if (0 < a && a < 1)  a = 1
ratio  = pow(2.0, a/12)                       # double pow @ 0x180769d80
```

Shift is clamped to +-12 semitones, and any nonzero magnitude under one semitone becomes +-1. Exactly 0 is a unison passthrough.

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

Stage 1, pitch period: each pass reloads the 17640-frame window from the source cursor, then autocorrelates 441 left-channel samples at every lag from 132 to 882 (`0x84` to `0x372`, 50 to 334 Hz), keeping a running max in a double. The winning lag applies to both channels. Ties keep the earlier lag, so a silent window gives 132. The loader zeroes both channels where the left sample is 0 (`0x180642b43`), like `FUN_18063d9e0`.

Stage 2, grain (SOLA splice): a triangular crossfade over `lag` samples, then a copy tail:

```
grain[j]     = ((lag-j)/lag)*in[c+j] + (j/lag)*in[c+lag+j]      j in [0, lag)
grain[lag..] = in[c+lag..]                                       bounded by 17640
hop = int(lag / (1/ratio - 1) + 0.5)   if ratio < 1
    = int(lag / (ratio - 1) + 0.5)     if ratio > 1
```

This changes duration without a discontinuity, not pitch.

Stage 3, 25-tap windowed sinc resample into `0x280`/`0x288`, which moves the pitch:

```
for i in [0, count):                       # count = hop+lag (down) / hop (up)
    c = int(i*ratio)
    for k in [c-12, c+12]:
        if k < 0: skip
        x = (i*ratio - k) * pi
        w = (x == 0) ? 1.0 : sinf(x) / x
        acc[cursor + i] += w * grain[k]
```

Both directions run the same code (`0x180643337` up, `0x180643a73` down).

Stage 4, mix: once the accumulator holds a block, `out = (1-mix)*dry + mix*acc` against this call's dry buffers. The accumulator is `memmove`d down by the block length and zero-filled. The pass tail at `0x180643472` advances the source cursor by that pass's hop.

Implemented as `fx_dsp.fx_pitchshift`.

### 4.11 Pitch & Speed (id 13, kind 14, wrapper `0x180632c10`)

The wrapper does no DSP. Case `0xd` in `FUN_18022db60` pushes three floats per definition (`+0x16c`, `+0x170`, `+0x174`) into the vector at `+0x190`. The wrapper reads them, wraps them in `std::function<float(float)>` objects and calls one routine:

```
std::shared_ptr<BMSoundLib2017::WaveBuffer> ApplyPitchAndSpeed(
    short const*, unsigned __int64, int, int,
    std::function<float(float)>,   // 1: PITCH, semitones
    std::function<float(float)>,   // 2: SPEED, playback-rate multiplier
    std::function<float(float)>,   // 3: MIX, percent
    std::function<float(float)>)   // 4: TIME, progress remap
```

So `13, p1, p2, p3` is `mix%, semitones, speed`.

Each parameter is used only when it differs from neutral by more than `FLT_EPSILON` (`|p2| > e` at `0x180632cf6`, `|p3 - 1| > e` at `0x180632db8`, `|p1 - 100| > e` at `0x180632e5b`). Otherwise the wrapper passes an empty `std::function`, meaning "leave alone". So `13, 100.00, 0.00, 1.00`, the most common id-13 row, does nothing. At mix 100 there's no mixing stage.

Speed is a playback rate. `FUN_180784e10` advances a 16.16 position accumulator by `(int)(65536.0/speed + 0.5)` per input frame consumed: speed 2 eats two input frames per output frame, 0.5 eats half a frame, and `speed <= 0` freezes. Charts use 0, 0.5, 1 and 2. Pitch is `powf(2, semitones/12)` at `0x18062d92e`, unclamped (charts range over [-24, 24]).

When speed isn't 1, the dry side of the mix isn't the dry track. `FUN_18062ca80` renders twice, once with both parameters and once with the same speed and a constant-0 pitch lambda (`0x1802be750`, at `0x18062cf79`), and mixes against the second render. At speed 1 the second pass is skipped (`0x18062ce2b`).

The input runs from the note's first frame to the end of the buffer, not the note's end (`0x18062cd2f`), so speed > 1 pulls audio from after the note. The output is `end - start + 1` frames, `memcpy`d back (`0x180633227`).

The engine is PhaseGear, a third-party FFT phase vocoder (`BMSoundLib2017::PhaseGearDriverImpl`, ctor `0x180620010`, per-block driver `0x180620860`, plus `PhaseGearCore`, `PhaseGearSignalProc` and `PhaseGearLib::FFTHandler`). From `PhaseGearCore::Initialize` (`0x180784910`): frame size `1 << (log2(sampleRate) - 4)` = 2048, synthesis hop `frame >> 2` (4x overlap), and a ring buffer primed with `frame/2` zeros. Pitch and speed reach it via `0x180784600` (`core+0x38`) and `0x180784620` (`core+0x34`), gated by `core+0x30`. A formant section (`core+0x44..0x4c`) and a four-band section (`core+0x60`, stride `0x18`) exist, but this caller leaves them off.

Implemented as `fx_dsp.fx_pitch_speed`, with a textbook phase vocoder at PhaseGear's frame and hop (identity phase locking, resample for pitch). Time and pitch mapping follow the contract, but the timbre differs because PhaseGear's internals aren't transcribed (§8).

## 5. Chart to DSP conversion

Wrappers convert chart values using the BPM at the effect's start (`60/BPM`, constant `0x18092e700`):

| effect | field | conversion | at |
|---|---|---|---|
| Retrigger / Echo | length | beats: `sec = beats * 60/BPM` | `0x180631198`, `0x180631271` |
| Gate | period | beats | `0x180631bb2` to `0x180631bbb` |
| Side Chain | period | beats | `0x180632552` |
| Wobble | rate | cycles per beat: `sec = (60/BPM) / rate` | `0x180632aa0`, `0x180632ab6` |
| Flanger | period | measures: `rate = measures / secPerMeasure` | `0x180631f6b` to `0x180631f8d` |
| Tape Stop (id 4) | duration | seconds, passed through | inline case 7 |
| Tape Stop Ex (id 10) | duration, preroll, window | beats | `0x180632170` to `0x18063218a` |
| Bit Crusher | rate | raw sample count | `0x180630d10` |
| LPF / HPF | freqLo/Hi | Hz, plus the §4.2 exponent | `0x180630110` |

`FUN_18062e2e0` returns the beat numerator active at a position; the flanger uses it for `secPerMeasure`. A laser note's effect index is `noteField[4] - 1` (`FUN_18062ea60` at `0x18062ea7c`); an FX note's definition index is `noteField[4] - 2` (`FUN_18062e3d0` at `0x18062e3f0`).

### 5.1 Laser event grouping and slams

A laser event is a 20-byte struct per adjacent point pair: `{startSample, endSample, startKnob, endKnob, effectIndex}`. `FUN_18062ef70` groups events into runs that are contiguous in time and share an effect index. The wrapper skips runs shorter than one block (`FUN_18062ea60` at `18062ea7c`: `if (gen->blockSize <= (lastEnd - firstStart))`).

A slam (two points on one tick) is a zero-duration step in the knob curve of the run it sits in, so the cutoff jumps across the whole `freqLo..freqHi` range within one block. A run splits wherever the per-point effect index changes, and a slam isolated in a run shorter than one block produces nothing.

A point pair has to sit inside one section. C2 is the node type (1 starts, 0 continues, 2 ends), and a chart can end one laser and start another on the same tick (`2` then `1`). That's a handoff, not a slam: the game draws two sections, schedules no kind-6 event (no slam SE, §6.1.1), and no knob event crosses the boundary. The note converter applies the same rule (`scripts/notes/laser_curves.py`).

### 5.2 Retrigger is locked to the musical grid

Retrigger's repeat cycle runs on the song's grid. A note that starts mid-cycle joins it partway through and can open by replaying audio from before the note. Echo/RetriggerEx is note-locked: its wrapper (`0x180631390`) reaches the shared DSP at `0x1806316a7` with no snap. Retrigger's wrapper `0x180630fa0` calls `FUN_18062e310` at `0x1806310e5`.

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

The wrapper then does `snappedStart = notePos - offset` (`0x1806310ea`). Example: a 2-beat Retrigger at 210 BPM has `samplesPerBeat` 12600 and `period` 25200. A note one beat in gets offset 12600, so with `count` 16 (1575-sample slices) it opens at slice 8.

`render_chart.py` computes this in `grid_snap_offset`, renders from `offset` samples before the note and discards the pre-roll.

### 5.3 `#BEAT RESOLUTION`

Cells per beat is set per chart by the optional `#BEAT RESOLUTION` tag: 48 when absent, which is nearly every chart, otherwise 144, 240 or 480. `Timeline` reads it from the chart, with `res=` as an override.

### 5.3b The beat column is in denominator units

The beat in `measure,beat,cell` is one denominator unit, `res * 4 / den` cells: 48 in 4/4 and 12 in 15/16. `Timeline.abs_tick` computes it that way.

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

The `-o` extension picks the container (default Vorbis). Use `.wav` for the §7 metric.

Flags:

```
device ParamEq (7.1)
  --no-peak          skip it
  --peak-delay S     knob lag (default 0.08, the engine's value)
  --peak-always      run it during every laser, not only C4 = 0
  --peak-post-se     put it after the SE mix
  --no-duck          skip the music duck
  --duck-rate R      chase the duck at R gain/s (default: instant)
  --duck-hold        freeze the duck target between lasers
  --peak-gain-scale  multiplies the resonant gain (default 0.8, engine 1.0)
  --peak-max-gain    ceiling in dB (default 8, engine unclamped up to +15)

layered SE (6.1)
  --no-se            skip them
  --slam-index N     which virtical_shot sample a slam plays (0 or 1)
  --se-polyphonic    let overlapping slams sum instead of restarting one voice
  --se-trim X        multiplier on header-derived SE gains (default 1.2, 7.2)
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
  --no-pitchshift      leave Pitch Shift dry (4.10)
  --no-pitch-speed     leave id 13 dry (4.11)
  --tapestop-ex-floor X  the fitted floor (4.6b)
  --tapestop-ex-3phase   the other renderer's phase model (9.3)
  --wobble-legacy-period read Wobble's C6 as a period (4.9)
  --filter-max-resonance DB  resonance cap on LPF/HPF (4.1b)
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

FX chips apply no track effect (zero length, and the wrappers need a full block) but trigger a sample (§6.1). A worked example (`2229_kamui_tjhangneil` MXM) is in the evidence file.

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

On a chip, the FX note's C2 is a `general_sampler` index (on a hold the same column is effect + 2). 0 and 255 are silent, and nearly all chips are 0. The names are in `vox_format.md` under `#TRACK2`/`#TRACK7`.

### 6.1.1 Trigger code

Voice API: `Play = FUN_1805c6ec0(this, bankId, sampleIdx, flag)` (voice `vtable+0x10`), `SetVolume = FUN_1805c6e40(this, bankId, sampleIdx, vol)` (`vtable+0x40`, `vol/127`). Both triggers are in the event dispatcher `FUN_180407200`. Ghidra types its selector as `float`, so case labels show as denormals (`2.8026e-45` = 2, `4.2039e-45` = 3, and so on).

FX chip, case 4:

```c
if ((0 < (int)idx) && (idx != 255)) {
    snd = FUN_1800967c0();
    FUN_1805c6ec0(snd, 9, idx);        // bank 9 = ver5/general_sampler
}
```

Case 3 mirrors VOL-R (`if (field == 2) v = 1.0f - v;`, §7.1).

A laser slam plays in two stages. Event kind 6 (`0x18040773a`, tag 5) is a scheduled play request, queued at `gameAudio+0x80`:

```c
entry.index = event.a;                                     // event+0x08, verbatim
entry.due   = now - (long long)((event.time - audioPos) * 1000.0f);
```

Drained later in the same call once `entry.due < now`:

```c
FUN_1805c6ec0(snd, 0xd, entry.index, 0);   // bank 0xd = ver5/virtical_shot
```

Bank `0xd` is `/data/sound/ver5/virtical_shot.s3p`, whose two entries hold the same audio as `general_sampler`'s first two. The sample index comes from `event+0x08`, set by whatever builds kind-6 events upstream of `Game::GameAudio`; that producer is untraced (§8). Every measured chart uses index 0. `render_chart.py` plays `general_sampler[0]`, and `--slam-index 1` selects the other.

Bank table, from `FUN_1805c5960`:

```
0 sys_sd_credit.2dx   1 sys_sd_sram.2dx    2 <the song's own .s3v, loaded per song>
3 sys_sd.2dx          4 sys_sd_shotfx.2dx  6 00_title_bgm_06   7 sys_sd_virtical.2dx
8 ver6/bgm_00         9 ver5/general_sampler   0xd ver5/virtical_shot
0xe voice_mitsuru_00  0xf voice_tama_00     0x10 hexa    0xa..0xc,0x11..0x18 ver6/se_*
```

### 6.1.2 No level goes through Play

Both SE `Play` calls pass flag 0 (`0x18040752a` chip, `0x1804080e4` slam), voice `vtable+0x10` (`0x1806a1cc0`) takes no gain, and none of the 19 `SetVolume` call sites names bank 9 or `0xd`. Voices start at unity (`VoiceImpl` ctor `0x1806a183a`). An SE's level comes from its header gain (6.1.4) and from the sample itself: the chips are mastered hot, several at full scale, and the slam peaks lower with a 228 ms swell.

### 6.1.3 One voice per sample

`Play` resolves to a single persistent voice per `(bank, sampleIndex)`, allocated at bank load:

```c
voices = FUN_1805c5830(bank);                  // vector<shared_ptr<Voice>>, 16 bytes/entry
voice  = voices[index];
voice->vtable[0x10](flag);
```

Playing a sample that's still sounding restarts its voice. VOL-L and VOL-R slamming together is one Play. `render_chart.py` truncates each slam at the next onset, and `--se-polyphonic` sums them instead.

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

File values are mostly multiples of `0x80` (0.5 dB steps). The gain lands on the voice's mixer connection: `VoiceImpl::vtable+0xd0` (`0x1806a2fc0`) returns `this->connections[i]`, and `MixerConnectionImpl::vtable+0x20` (`0x1802fbf40`) is `movss [conn+0x20], xmm1`. Nothing changes it afterwards. The standalone `.s3v` loader (`0x1805cf8c8`) does the same for the song.

| bank | sample | `hdr+0x14` | dB | linear |
|---|---|---|---|---|
| `0xd` virtical_shot | 0 `fs00_virtical_se01` (slam) | -1324 | -5.172 | 0.5513 |
| `0xd` virtical_shot | 1 `fs01_virtical_se02` | -2072 | -8.094 | 0.3938 |
| 9 general_sampler | 0, 1 | -1324 | -5.172 | 0.5513 |
| 9 general_sampler | 2..13 (FX chips) | -3328 | -13.000 | 0.2239 |
| 9 general_sampler | 14 `fs14_shot13` | 0 | 0.000 | 1.0000 |
| 2 | `2229_kamui_tjhangneil.s3v` (music) | 0 | 0.000 | 1.0000 |

Chips sit 7.83 dB below the slam, and the music is at unity. `virtical_shot[1]` and `general_sampler[1]` hold identical audio with different header gains, so the gain is per bank entry.

Against the capture, the best-fit slam gain is about 2 dB above the header's (§7.2). Two loader results are untraced: the standalone `.s3v` loader keeps a second `powf` result at `[rsp+0x60]`, and the `.s3p` loader appends the gain to a `std::vector<float>` (`0x1805ced2c`).

`load_s3p` returns each sample's header gain, and every SE mixes at `header_gain * --se-trim`. `--se-trim 1.0` plays what the files say, and `--slam-gain` and `--se-gain` bypass both.

### 6.2 Output stage: `CGainWithHardLimiter`

`BMSoundLib2017::CGainWithHardLimiter::Process` (`0x18069f090`, vftable `0x180925df8`):

```
gain  = this->0x18 (float)     set by 0x1802f8120
limit = this->0x1c (float)     set by 0x1802fbf30 (both at once: 0x1802ffe90)
for each sample (SSE, 4 at a time):
    x = x * gain
    x = min(max(x, -limit), +limit)
```

A gain and a hard clip, with no knee, lookahead or release. `--master-gain` sets the gain.

### 6.3 `#TRACK AUTO TAB` and `#TAB PARAM ASSIGN INFO`

`#TRACK AUTO TAB` lets a laser span run an effect pair borrowed from `#FXBUTTON EFFECT INFO`. `#TAB PARAM ASSIGN INFO` can attach a rule that the laser position drives one of the pair's parameters between two bounds. `render_chart.py` applies both (`--no-auto-tab` and `--no-param-assign-sweep` turn them off).

AUTO TAB is used in about a third of charts. PARAM ASSIGN has 24 rows in every chart, but only about 5% have nonzero C1 to C3.

```
#TAB PARAM ASSIGN INFO, one row per #FXBUTTON EFFECT INFO slot (24 rows = 12 pairs x 2):
  C0  effect-pair index, 0-indexed (always 0,0,1,1,...,11,11)
  C1  index of the pair's own parameter to modulate (0 = none)
  C2/C3  bounds the parameter is swept between

#TRACK AUTO TAB rows (same shape as an FX hold):
  C0 timing   C1 length (cells)   C2 effect index, 2-INDEXED: pair = C2 - 2
```

The sweep is `value = C2 + (C3 - C2) * clamp(laserValue, 0, 1)`, refreshed every 512 samples, with `param1` and `param2` chosen by chain position. The control source is a C4=6 laser.

Example: the AUTO TAB row `021,03,00  96  8` selects pair 8-2=6. If that pair's assign row is `6, 3, 3.00, 0.50`, the sweep drives param 3 of a Flanger, its period, from 3.00 to 0.50 measures. Most AUTO TAB spans land on an unmodulated pair and run at their authored parameters.

`#TRACK ORIGINAL L/R` has no effect on audio. It holds only the un-interpolated control points, and `#TRACK1`/`#TRACK8` already carry the sequence that plays.

## 7. Calibration against a cabinet capture

`scripts/audio/reference/kamui_goal.ogg` is a recording of the cabinet playing `2229_kamui_tjhangneil`. It's polarity-inverted, Ogg-coded and drifts +0.346 samples/s (7.9 ppm), so the metric is phase-insensitive: `spectral_metric.py` splits each 46 ms frame into 46 log-spaced bands, normalises the level and scores the mean |dB| difference. Codec noise keeps even an untouched track above zero. `check_one_chart.py` runs the metric with automatic alignment on any chart/capture pair, and `check_all_charts.py` aggregates it over the corpus.

### 7.1 The default laser filter

This runs through the gameplay event dispatcher and the sound device, not the effect generator.

`FUN_180407200` (`Game::GameAudio::Update`, vtable slot 1 at `0x1808cb848`) walks 28-byte events:

```
+0x00  ?                 +0x04  int  kind (2..7, the switch selector)
+0x08  int   a           +0x0c  float pos / time
+0x10  int   b           +0x18  byte variant tag (= kind - 1)
```

Kind 3 is a laser (`0x1804074aa`, asserts tag 2). Per tick one accumulator covers every laser event:

```c
disableEq = (event.b != 0);                       // event+0x10, the C4 effect index
v = (event.a == 2) ? 1.0f - event.pos             // event+0x08: 1 = VOL-L, 2 = VOL-R
                   : event.pos;
acc = max(acc, v);                                // both knobs share one filter
```

`acc` is queued with a timestamp at `gameAudio+0x58` and popped once the head is older than 80 ms (`comiss xmm0, 0.08` at `0x180407f61`), so the filter lags the knob. If `disableEq` is set, the queue is flushed and the knob is forced to 0. The popped value times 127 goes to `FUN_1805c7a00`:

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

`TABLE` is 128 floats at `DAT_18090c050`, a hand-drawn piecewise-linear ramp: `0, 6, 12 ... 54, 100, 106 ... 202, 232 ... 3672, 3852 ... 6912, 7400, 7700, 8000, 8400 ... 10800`. The first ten entries clamp to 80 Hz.

The struct is `{fCenter, fBandwidth, fGain}` (`FUN_180626b30` writes args 3 to 5 to `[rsp+0x20/0x24/0x28]`). In the dead zone `fGain` is 0, which turns the EQ off.

The DMO isn't in this binary. `CDmoSoundFxAudioProcessor<_DSFXParamEq>` (`0x180919970`) and `CDmoSoundFxDriver<IDirectSoundFXParamEq,_DSFXParamEq>` (`0x180919998`) forward to a COM object at `this+0x10`, and the math is Microsoft's `GUID_DSFX_STANDARD_PARAMEQ`. `fx_dsp.peaking_coeffs_bw` models it as the RBJ peaking filter with `BW(octaves) = fBandwidth / 12`, the same reading as the independent reimplementation (§9.1).

The same call ducks the music. Bank 2 is the song's `.s3v` (registered per song by `FUN_1805c63b0(this, 2, path)`, up to 6 stems). Every bank-2 voice gets a target gain:

```c
if (v <  4)  g = 1.0f;
if (v < 95)  g = 0.8f - (v - 4) * 0.0025274728f;  // 0.800 .. 0.570
if (v < 100) g = 0.57f;
if (v < 120) g = 0.57f + (v - 100) * 0.011500001f;
else         g = 0.8f;
```

Voice `vtable+0x60` (`0x1806a21f0`) writes a target, and the mixer chases it at 0.33 gain/s (`0x1806a25b1`).

ParamEq slot 0 sits on the music path, before the SE voices are mixed in (placed by measurement).

`render_chart.py` defaults `--peak-gain-scale` to 0.8 and `--peak-max-gain` to 8 dB, a dampened EQ chosen for listening comfort; `paramq_from_knob`'s own defaults (`gain_scale=1.0, max_gain_db=None`) are the transcription. To reproduce this section's measurements, `check_one_chart.py`/`check_all_charts.py` need `--extra="--peak-gain-scale 1.0 --peak-max-gain 15"`.

### 7.2 SE levels

With the one-voice rule (6.1.3), the best SE trim against the capture is 1.25 (+1.9 dB) over the header gains, where the files imply 1.00. `render_chart.py` defaults `--se-trim` to 1.2. `virtical_shot[0]` is the right slam sample for kamui.

## 8. Known gaps

* The SE level fits the capture about 2 dB above the header gain (6.1.4, 7.2).
* The producer of kind-6 events, which picks the slam sample, is untraced (6.1.1). Note and laser events probably share that vector.
* Kind 14 (id 13): the PhaseGear internals. Transcribing `PhaseGearSignalProc` (`0x180787e20` init, `0x1807894b0` synthesis, `PhaseGearLib::FFTHandlerF`) would close this. Its fourth function remaps the note's 0..1 progress; in this build it's the identity lambda at `0x1802be750`.
* Tape Stop Ex's floor (`this+0x46`) and phase field (`this+0x224`) are untraced (4.6b).
* The order of the FX-note list at `gen+0x20` is untraced (8.1).
* `Timeline` uses float seconds and the engine uses integer samples, so for BPMs that don't divide 2646000 evenly `grid_snap_offset` (5.2) returns tens of samples where it should return zero.

### 8.1 Effect combination

With `x` the track, `A` the FX-button effect and `B` the laser effect:

| model | meaning | result |
|---|---|---|
| chain | series | `B(A(x))` |
| dry | `B` reads the original and replaces `A` where they overlap | `B(x)` |
| add | parallel, changes sum | `x + (A(x) - x) + (B(x) - x)` |

**FX-L plus FX-R: the later note overwrites.** `FUN_18062e3d0` handles one note, and its `lVar19 < 2` loop walks the pair's two effects (the map at `gen+0x38` stores each pair as two `{kind, index}` entries at stride 8). Those two chain:

```
if (lVar19 == 1 && iVar6 != -1) {            // second member of the pair
    memcpy(param_5, param_4, param_6 * 2);   // scratch <- destination
    puVar5 = *param_1; *puVar5 = param_5;    // generator source := scratch
}
```

On exit the source is restored to the original track (`if (1 < lVar19) { puVar5 = *param_1; *puVar5 = param_2; ... }`). The caller `FUN_18062ef70` calls the dispatcher once per FX note from the list at `gen+0x20`. Each call reads the restored `param_2` and writes the same `param_4` (seeded with a copy of dry), so where two FX notes overlap, the later one replaces the earlier. The order follows the `gen+0x20` list. The renderer does FX-L then FX-R, and `--fx-order-rl` swaps them.

**Peak filter plus anything: a separate stage.** The C4=0 filter is a device ParamEq (7.1), downstream of the generator and upstream of the SE mix, so it always stacks on top.

**Tab laser (C4 1..5) plus FX button: chain.** Just before the laser run loop, `FUN_18062ef70` points the generator source at a copy of the FX result:

```
memcpy(scratch, param_4, len);      // scratch <- the DESTINATION, i.e. the FX result
puVar23 = *param_1;
*puVar23 = scratch;                 // generator source := that snapshot
...
for (run = first; run != last; run += 0x18)
    FUN_18062ea60(param_1, param_4, run);
```

**Laser plus laser: the later run overwrites.** The snapshot is taken once, and each `FUN_18062ea60` call `memcpy`s its result over the destination. VOL-L and VOL-R both read the post-FX audio, and the later run wins the overlap.

**Where effects stack,** the mix compounds, because each effect mixes against its own input (two effects at 50% leave 25% of the original). There's also an int16 requantisation between stages (`FUN_18063dc40` then `FUN_18063d9e0`, §2), so a chain can clip partway through. `--no-stage-clip` keeps float between stages.

### 8.2 High-Q laser passages run about 1 dB hot

A fast laser wiggle through a Q 5.0 tab LPF renders about 0.9 dB louder than the capture, with a fraction of a percent of samples clipping. The cause is unknown. Candidates: the Q 5 peak against its `(1 - Q*0.04)` trim, the device ParamEq stacking on top (7.1), and chaining compounding both.

## 9. Cross-check against `Rosemoe/sdvx-sfx-renderer`

[sdvx-sfx-renderer](https://github.com/Rosemoe/sdvx-sfx-renderer) is an independent reimplementation of the same engine, built from IDA in about 4000 lines of Python. It doesn't model SE bank levels, the music duck or the peak filter's queue delay.

### 9.1 Agreement

* The ParamEq (7.1): the 128-entry table, `[80, 16000]` clamp, bandwidth/gain curves, `knob < 4` dead zone and `bandwidth / 12` octave reading.
* The effect-id table (§3), 11 of 13 ids.
* Wobble's five waves, its `(1 - Q*0.04)` trim and column layout.
* Laser handling: VOL-R as `1 - pos`, VOL-L raw, `max()` into one accumulator.
* `#TRACK AUTO TAB`'s effect column is 2-indexed.
* A tab laser reads the FX-button result (chain, 8.1).
* Tape Stop (id 4) duration in seconds, and `#BEAT RESOLUTION` per chart.

### 9.2 Taken from it

* Wobble's C6 as a rate (4.9), later confirmed in the disassembly.
* The `#TAB PARAM ASSIGN INFO` sweep formula and its 512-sample refresh (6.3), and C4=6 as its control source.

### 9.3 Disagreements

Each was A/B tested on the frames it affects, and the other renderer's reading stays behind a flag. Ours scores better for Gate's step table (4.5) and BitCrusher's block-realigned grid (4.3). Its three-phase Tape Stop Ex model is inconclusive (`--tapestop-ex-3phase`). Laser easing and float-only stages make no measurable difference.
