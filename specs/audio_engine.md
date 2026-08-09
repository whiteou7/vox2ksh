# SOUND VOLTEX — audio effect engine, reverse engineered

Target: `modules/soundvoltex.dll` (PE32+ x64, ImageBase `0x180000000`, build `C:\work\git\sdvxx\sdvx\build\SoundVoltex6_x64Release\out\SoundVoltex.pdb`, 2025‑06‑19).

All addresses below are virtual addresses in that DLL. Everything here was derived from the binary itself (MSVC RTTI names + Ghidra 12.1.2 decompilation + capstone disassembly), cross‑checked against 8103 `.vox` chart files in `data/music/`.

---

## 1. Where the effects live

MSVC RTTI gives the engine away immediately:

```
.?AVCSvoEffectedAudioGenerator@BMSoundLibSvo@@
.?AVCSvoEffectedAudioGeneratorImpl@BMSoundLibSvo@@      vftable @ 0x180919ca8
```

`BMSoundLibSvo::CSvoEffectedAudioGeneratorImpl` is the whole FX chain. Its code occupies roughly `0x180628000 – 0x180650000`. Layers:

| layer | address | role |
|---|---|---|
| generator ctor | `0x180628b50` | builds the effect parameter vectors |
| chart → generator | `0x18022db60` | `switch` on the `.vox` effect id, fills the vectors |
| per‑block dispatcher | `0x18062e3d0` | `switch` on the internal *kind*, calls a wrapper |
| dispatcher (animated params) | `0x180633360` | same kinds, parameters interpolated over time |
| wrappers | `0x180630110 … 0x180632c10` | chart params → DSP args (BPM, knob position, grid snap) |
| DSP leaves | `0x18063df40 … 0x1806429b0` | the actual sample crunching |

Shared helpers:

| address | function |
|---|---|
| `0x18063d9e0` | **prepare**: int16 source → float L/R work buffers |
| `0x18063dc40` | **writeback**: float → clamped int16, interleaved |
| `0x18062e310` | musical grid snap, `samplesPerBeat = trunc(2646000 / BPM)` (2646000 = 44100·60) |
| `0x180796b80` | `sincosf` (returns sin in low dword, cos in high dword) |
| `0x18076f5d0` | `sinf` |
| `0x18076b420` | `powf` |

---

## 2. Signal path — the part everybody gets wrong

```
.s3v track (16-bit PCM, 44100 Hz, stereo interleaved)
        │
        ▼  FUN_18063d9e0
 float L[], R[]      ← values are the *raw int16 magnitudes*, i.e. ±32768.
        │              There is NO /32768 normalisation anywhere in the chain.
        ▼  one effect  (dry L/R at gen+0x38 / gen+0x40, wet out at gen+0x58 / gen+0x60)
        ▼  FUN_18063dc40
 clamp to [-32768, 32767], truncate toward zero, write interleaved int16
```

Facts that matter if you want bit‑comparable output:

* **Sample rate is hard‑coded 44100.** The constant `0.00014247585` = 2π/44100 appears in every filter; `44100.0f` appears in every time‑based effect.
* **Everything is single precision `float`.** Coefficients too.
* **Dry/wet is uniform**: `out = (1-mix)·dry + mix·wet`, `mix = clamp(param, 0, 100) / 100`. A few effects fold an extra makeup gain into the wet term (noted per effect).
* **Processing is blocked.** Block length is `gen+0x1a0` (the audio callback's frame count). Filter coefficients / LFO values are recomputed **once per block**, not per sample. Effect start positions are snapped *backwards* onto the musical grid by `FUN_18062e310`, and the laser filters additionally start 64 samples early (`iVar1 = *param_3 - 0x40`).
* **Quirk worth knowing** (`FUN_18063d9e0`): if the *left* int16 sample of a frame is exactly `0`, the code forces **both** channels of that frame to `0` in the work buffer. It is a real branch in the shipped binary, not a decompiler artefact.

---

## 3. Effect inventory

The `.vox` chart id (`#FXBUTTON EFFECT INFO`, first column) maps to an internal *kind* enum, which the dispatcher at `0x18062e3d0` switches on. The mapping is set in `FUN_18022db60`:

| `.vox` id | kind | param vec (this+) | fields | wrapper | DSP leaf | effect |
|---|---|---|---|---|---|---|
| 1  | 3  | 0xb0  | 6  | `0x180630fa0` | `0x18063ffb0` | **Retrigger** |
| 2  | 5  | 0xe0  | 35 | `0x1806317a0` | `0x180641d20` | **Gate** |
| 3  | 6  | 0xf8  | 5  | `0x180631cf0` | `0x18063f420` | **Flanger** |
| 4  | 7  | 0x110 | 3  | inline        | `0x180640700` | **Tape Stop** |
| 5  | 9  | 0x140 | 5  | `0x1806324b0` | `0x180641770` | **Side Chain** |
| 6  | 10 | 0x158 | 7  | `0x180632820` | `0x1806414f0` | **Wobble** (LFO‑swept filter) |
| 7  | 2  | 0x98  | 2  | `0x180630d10` | `0x18063fc60` | **Bit Crusher** |
| 8  | 4  | 0xd0  | 7  | `0x180631390` | `0x18063ffb0` | **Retrigger Ex / Echo** |
| 9  | 11 | 0x178 | 2  | inline        | `0x1806429b0` | **Pitch Shift** |
| 10 | 8  | 0x130 | 5  | `0x1806320d0` | `0x180640c20` | **Tape Stop Ex** |
| 11 | 12 | 0x70  | 4  | `0x180630110` | `0x18063df40` | **Low Pass Filter** |
| 12 | 13 | 0x88  | 4  | `0x180630760` | `0x18063e500` | **High Pass Filter** |
| 13 | 14 | 0x190 | 3  | `0x180632c10` | (composite) | parameter‑animated effect |

Effect‑type names above are what the DSP actually *does*. Community notes (`vox_format.md`) label some differently and flag themselves unverified; where they conflict, the binary trace wins:

| id | community notes | traced here | evidence |
|---|---|---|---|
| 3 | Phaser | modulated fractional delay + feedback taps = **flanger** topology | `0x18063f420` |
| 10 | Highpass | 5 float params, tape‑stop‑shaped clamps — **not** a filter | `0x180640c20` |
| 11 | Lowpass | **Lowpass** ✓ | setup case `0xb` → vec `+0x70` → kind 12 → `0x18063df40` |
| 12 | Flanger | **Highpass** | setup case `0xc` → vec `+0x88` → kind 13 → `0x18063e500` |

Chart data supports this: types 11 and 12 both carry 4 params (`mix, f, f, Q`) like a filter, while type 3 carries 5.

Lasers (`#TAB EFFECT INFO`) reuse **the same parameter vectors and the same DSP leaves**, but are registered into a *second* map (`gen+0x58`, versus `gen+0x38` for FX buttons) with its own small enum, by `FUN_180639290/360/430`:

| `#TAB EFFECT INFO` id | laser kind | param vec (this+) | wrapper | DSP leaf | effect |
|---|---|---|---|---|---|
| 1 | 1 | 0x70 (shared with FX kind 12) | `0x180630110` | `0x18063df40` | **Low Pass Filter** (knob‑swept) |
| 2 | 2 | 0x88 (shared with FX kind 13) | `0x1806303f0` | `0x18063e500` | **High Pass Filter** (knob‑swept) |
| 3 | 3 | 0xa0 (shared with FX kind 2)  | `0x180630a20` | `0x18063fc60` | **Bit Crusher** (knob‑swept) |

Which of the five a laser node uses comes from **`#TRACK1`/`#TRACK8` column C4**:

```
C4 = 0     peak filter  (the DEFAULT laser sound - see below)
C4 = 1..5  index into #TAB EFFECT INFO, 1-indexed
C4 = 6     no effect
```

This matches `FUN_18062ea60`, which keys its map on `noteField[4] - 1`, so C4 1..5 becomes map key 0..4 = the five `#TAB EFFECT INFO` slots.

**The peak filter is the default and it is not in this engine.** With C4 = 0 the key is `-1`, which lands on the sentinel `FUN_18063a070` installs (`laserMap[-1] = kind 0`, i.e. nothing). The band‑pass biquad at `0x18063eb10` is reachable only through Wobble's filter‑type selector, so it is *not* what you hear on a default laser either. The real path is a DirectSound parametric‑EQ DMO living in the **sound device**, not in the effect generator, driven straight from the gameplay event dispatcher. It is transcribed in full in §7.1.

On `2229_kamui` MXM, 870 of 894 VOL‑L nodes are C4 = 0 — the default peak filter is the dominant laser sound in practice.

Chart column order per type is fixed by the reader `FUN_180239810` / writer `FUN_1800d40c0`:

```
1  -> %d, %d,  %f, %f, %f, %f, %f      2  -> %d, %f, %d, %f
3  -> %d, %f,  %f, %f, %d, %f          4  -> %d, %f, %f, %f
5  -> %d, %f,  %f, %d, %d, %d          6  -> %d, %d, %d, %f, %f, %f, %f, %f
7  -> %d, %f,  %d                      8  -> %d, %d, %f, %f, %f, %f, %f, %f
9  -> %d, %f,  %f                      10 -> %d, %f, %f, %f, %f, %f
11 -> %d, %f,  %f, %f, %f              12 -> %d, %f, %f, %f, %f
TAB 1/2 -> %d, %f, %f, %f, %f          TAB 3 -> %d, %f, %d
```

---

## 4. The algorithms

`N` = block length in frames, `x` = dry, `y` = filtered/wet, `m` = mix (0..1). Everything below is transcribed from the decompiled float math, clamps included.

### 4.1 Biquads (LPF `0x18063df40`, HPF `0x18063e500`, BPF `0x18063eb10`)

Textbook RBJ cookbook, Direct Form I, coefficients recomputed each block:

```
f  = max(freq, 1.0)                 # LPF uses  <=1 -> 1 ; HPF/BPF use  <1 -> 1
Q  = max(q, 0.1)
w0 = f * 2*pi/44100                 # literal constant 0.00014247585f
sn, cs = sincosf(w0)
alpha  = sn * (0.5 / Q)
a0i    = 1 / (1 + alpha)

LPF:  b0 = b2 = (1-cs)*0.5*a0i ,  b1 = (1-cs)*a0i
HPF:  b0 = b2 = (1+cs)*0.5*a0i ,  b1 = -(1+cs)*a0i
BPF:  b0 = alpha*a0i , b1 = 0 , b2 = -alpha*a0i
a1 = -2*cs*a0i        a2 = (1-alpha)*a0i

y[n] = b0*x[n] + b1*x[n-1] + b2*x[n-2] - a1*y[n-1] - a2*y[n-2]
```

Output stage differs:

```
LPF / HPF:  out = ((1-m)*x + m*y) * (1 - Q*0.04)      # resonance make-down
BPF:        G = (Q <= 1) ? max(Q + 0.9, 0.1)
                         : (Q*0.2 + 2.0 > 4.0 ? 3.0 : Q*0.2 + 2.0)
            out = (1-m)*x + m*y*G
```

Note the LPF/HPF gain trim `(1 - Q·0.04)` is applied to the **already mixed** signal, so it attenuates the dry path too. That is what makes SDVX laser sweeps duck slightly.

### 4.2 Laser / knob sweep (wrappers `0x180630110` LPF, `0x1806303f0`+`0x180630760` HPF)

The four chart params are `{mix, freqLo, freqHi, Q}`. Per block:

```
lo    = max(freqLo, 1.0)
ratio = freqHi / lo
v     = knob position, linearly interpolated 0..127 across the laser segment
LPF:  cutoff = lo * ratio ** (1 - v/127)      # v=0 -> freqHi (open), v=127 -> freqLo
HPF:  cutoff = lo * ratio ** (    v/127)      # v=0 -> freqLo (open), v=127 -> freqHi
```

`1/127 = 0.007874016f`. The knob value is the *effect parameter* value, produced from laser position via `#TAB PARAM ASSIGN INFO` — it is not simply the raw laser x‑position.

Laser Bit Crusher (`0x180630a20`) ignores the chart's rate field once the knob is moving:

```
vnorm = clamp(v/127, 0, 1)
rate  = int(vnorm * 29.0 + 1.0)     # 1..30
```

### 4.3 Bit Crusher — `0x18063fc60`

Pure sample‑and‑hold decimator (no bit‑depth reduction despite the name):

```
m    = clamp(mix,0,100)/100
rate = clamp(rate, 1, 30)
for i in 0 .. blockLen-1:                  # i is the index *within the block*
    k = i % rate
    s = (k == 0) ? x[i] : x[i-k]           # hold the last sample aligned to `rate`
    out[i] = (1-m)*x[i] + m*s
```

The right channel is held together with the left, using the same `k`. The counter is a function local, so **the hold grid realigns at every block boundary** — this effect's output genuinely depends on the audio callback size.

### 4.4 Retrigger / Echo — `0x18063ffb0`

Six params `mix, lengthSec, feedback, count, gate, release`.

```
m    = clamp(mix,0,100)/100
len  = clamp(lengthSec, 0.1, 8.0)
fb   = clamp(feedback,  0.1, 1.0)
cnt  = clamp(count,     1,   32)
gt   = clamp(gate,      0.1, 1.0)
rel  = clamp(release,   0.0, 1.0)

seg     = int(len*44100) // cnt          # samples per repeat
gateLen = int(seg * gt)
fadeLen = int(gateLen * rel)
g[k]    = fb ** k        for k = 0..31   # precomputed table at this+0x154

t   = phase counter (samples since effect start)
rep = t // seg ;  if rep >= cnt: rep = 0, t -= seg*cnt
rem = t %  seg
if rem > gateLen:                     wet = 0
elif rem > gateLen - fadeLen:         wet = delayed * g[rep] * (1 - (rem-gateLen+fadeLen)/fadeLen)
else:                                 wet = delayed * g[rep]
delayed = dry[i - rep*seg]            # ring buffer of the dry signal
out = (1-m)*dry + m*wet
```

`.vox` id 8 (Echo) feeds the same routine with a 7th field used by the wrapper for grid alignment/update period.

### 4.5 Gate — `0x180641d20`

```
m      = clamp(mix,0,100)/100
steps  = clamp(steps, 1, 32)
period = clamp(periodSec, 0.1, 4.0) * 44100
stepLen = int(period) // steps

t   = phase counter, wrapped at `period`
idx = t // stepLen ; if idx > 15: idx -= 16          # 16-entry table, repeats
g   = float(patternTable[idx] * 0.0322)              # int32 table, double-precision multiply
out = (1-m)*x + m*x*g
```

The pattern table is 16 int32 values living at `struct+0x10`. The default installed by `FUN_18022db60` is the 8‑byte pattern `{32, 4}` replicated 8×, i.e.

```
[32, 4, 32, 4, 32, 4, 32, 4, 32, 4, 32, 4, 32, 4, 32, 4]
-> gains  [1.0304, 0.1288, ...]
```

So the stock gate alternates full level (with ~0.26 dB of makeup) and −17.8 dB.

### 4.6 Tape Stop — `0x180640700`

```
m     = clamp(mix,0,100)/100
speed = clamp(speed, 1.0, 10.0)
dur   = clamp(durSec, 0.1, 2.0)
total = dur * 44100
step  = 1 / total

if written + N >= total:        # effect has run its course
    out = (1-m)*dry             # wet contribution is zero from here on
else:
    append dry block to the record buffer
    for each sample:
        if frac < 1.0:
            idx  += 1
            frac += (idx_before) * step * speed + 1.0
        env  = 1 - written * step
        wet  = record[idx] * env
        out  = (1-m)*dry + m*wet
        written += 1
        frac    -= 1.0
```

Playback advances one recorded sample only when `frac` drops below 1, and each advance adds `idx·step·speed + 1` to `frac` — so the effective playback rate is ≈ `1/(1 + idx·step·speed)`, a hyperbolic slow‑down, while `env` fades linearly to silence over `dur`. `.vox` id 10 (`0x180640c20`) is the same idea with two extra params (pre‑roll offset and a separate slow‑down window).

### 4.7 Side Chain — `0x180641770`

A pure amplitude envelope — no detector, no real compression:

```
m      = clamp(mix,0,100)/100
period = max(periodSec, 0.1)
A%,H%,R% = clamp(each, 0, 100)          # ints
N = int(period*44100)
A = int(A% * 0.002 * N)
H = int(H% * 0.003 * N)
R = int(R% * 0.005 * N)

t = counter, wrapped at N
if   t < A:        g = 1 - t/A          # duck
elif t < A+H:      g = 0                # hold
elif t < A+H+R:    g = (t - H - A)/R    # recover
else:              g keeps its last value (1.0)
out = (1-m)*x + m*x*g
```

Example `5, 90.00, 1.00, 45, 50, 60` → 1 s cycle, 90 ms duck, 150 ms silence, 300 ms recovery.

### 4.8 Flanger — `0x18063f420`

Multi‑pass modulated delay run over the dry ring buffer, with a quadrature LFO on the right channel:

```
m     = clamp(mix,0,100)/100
d     = clamp(delayMs, 0.1, 3.0) * 44.1     # base delay, samples
rate  = max(rateParam, 0.0) * 0.5           # Hz
depth = clamp(feedbackPct, 0, 100)/100 * d  # modulation depth, samples
st    = clamp(stages, 0.0, 4.0)             # ceil() -> pass count

for pass in ceil(st) .. 0:
    for i in block:
        sL  = sinf(counter * rate * 2*pi/44100)
        posL = i - (sL*depth + d)
        L' = lerp(buf[floor(posL)], buf[floor(posL)+1], frac(posL))
        c2  = counter + 11025/rate  (wrapped)            # 90° offset
        sR  = sinf(c2 * rate * 2*pi/44100)
        posR = i - (sR*depth + d)
        R' = lerp(...)
        if pass == topPass:                              # partial last pass
            a = m - (1-m)*(topPass - st) ;  b = (topPass - st)*m + (1-m)
            out = a*L' + b*x
        else:
            out = m*L' + (1-m)*x
        if st >= 1 and pass == 0: out *= 1.5             # final make-up
        counter += 1 ; wrap counter at 22050/rate
```

### 4.9 Wobble — `0x1806414f0`

An LFO that sweeps one of the three biquads. Params `mix, filterType, waveType, freqA, freqB, periodSec, Q`.

```
mix    = clamp(mix, 0, 100)
lo, hi = min(freqA,freqB), max(freqA,freqB)
period = max(periodSec, 0.1) * 44100
Q      = max(Q, 0.1)
ph     = counter / period
ratio  = hi / lo

waveType 0: f = lo + ph*(hi-lo)                          # saw up
waveType 1: f = hi - ph*(hi-lo)                          # saw down
waveType 2: f = lo * ratio ** ((sinf(ph*2*pi) + 1) * 0.5) # log-sine
waveType 3: f = lo * ratio ** (ph < 0.5 ? 2*ph : 2-2*ph)  # log-triangle
waveType 4: f = (counter >= period/2) ? hi : lo           # square

counter += N ; if counter >= period: counter -= period
filterType 0 -> LPF(0x18063df40), 1 -> HPF(0x18063e500), 2 -> BPF(0x18063eb10)
```

`6, 0, 3, 80.00, 500.00, 18000.00, 4.00, 1.40` = LPF, log‑triangle, 80 % wet, 500↔18000 Hz, 4 s period, Q = 1.4.

### 4.10 Pitch Shift — `0x1806429b0`

Time‑domain overlap‑add with resampling: `pow(2.0, semitones/12)` (double `pow` at `0x180769d80`), a windowed grain buffer at `this+0x4a…0x51`, cross‑faded segments whose count is `int(len/(ratio-1) + 0.5)` (or `len·ratio/(1-ratio)` when shifting down), and `sinf`‑based window weights. Two chart params: `mix` and `amount`. This one I did **not** finish transcribing coefficient‑for‑coefficient — see §6.

---

## 5. Chart → DSP parameter conversion

The wrappers convert chart values to DSP arguments using the BPM at the effect's start (`60/BPM` is loaded from the constant `0x18092e700` in every one of them). Verified per effect by disassembling each call site:

| effect | chart field | conversion | proven at |
|---|---|---|---|
| Retrigger / Echo | `length` | **beats** → `sec = beats · 60/BPM` | `0x180631198`, args at `0x180631271` |
| Gate | `period` | **beats** → `sec = beats · 60/BPM` | `0x180631bb2`–`0x180631bbb` |
| Side Chain | `period` | **beats** → `sec = beats · 60/BPM` | `0x180632552` + tail |
| Wobble | `period` | **beats** → `sec = beats · 60/BPM` | `0x180632ab2`–`0x180632aba` |
| Flanger | `period` | **measures** → `rate = measures / secPerMeasure` | `0x180631f6b`–`0x180631f8d` |
| Tape Stop | `duration` | already **seconds**, passed through | inline case 7 |
| Bit Crusher | `rate` | raw sample count, passed through | `0x180630d10` |
| LPF / HPF | `freqLo/Hi` | Hz, plus the knob exponent of §4.2 | `0x180630110` |

`FUN_18062e2e0` is the time‑signature lookup (returns the beat numerator active at a position); the flanger uses it to build `secPerMeasure`.

Laser note → effect index is `noteField[4] - 1` (`FUN_18062ea60` at `0x18062ea7c`), where `-1`/absent means no laser effect. FX‑button note → definition index is `noteField[4] - 2` (`FUN_18062e3d0` at `0x18062e3f0`).

### 5.1 Laser event grouping, and what a slam actually is

A laser event is one 20‑byte struct per *adjacent point pair*: `{startSample, endSample, startKnob, endKnob, effectIndex}`. `FUN_18062ef70` groups events into **runs** that are contiguous in time **and share the same effect index**; a run is what gets handed to the wrapper as `param_3`. The wrapper then bails out unless the run is at least one audio block long:

```
FUN_18062ea60 @ 18062ea7c :  if (gen->blockSize <= (lastEnd - firstStart)) { ...dispatch... }
```

A **laser slam** (two chart points on the same tick, e.g. `004,01,39 0.000000` immediately followed by `004,01,39 0.750000`) is therefore *not* an effect of its own — it is a zero‑duration event that contributes a **step discontinuity in the knob curve** of the run it sits inside. The audible "slam" is the filter cutoff jumping, in one block, across the whole `freqLo … freqHi` range. Measured on `2229_kamui` at 50.571 s, where the knob slams 127 → 0 on the HPF (40–2000 Hz, Q 3), the 60–400 Hz band jumps by **28×** within 100 ms.

Two consequences for any reimplementation:

* the knob curve must be built from the events and **left as a step** at slams — do not smooth or resample it, and do not treat a laser section as having one constant filter;
* a run must be split wherever the per‑point effect index changes, because charts routinely change filter mid‑section. Collapsing a section to a single filter both applies the wrong filter and misplaces the slam. On this one chart that error covered **18 s of audio**.

Isolated slams (a run shorter than one block) genuinely produce nothing in this engine.

## 6. Reference implementation

`sdvx_fx.py` implements §4.1–4.9 against 16‑bit WAV files, in the same ±32768 float domain and with the same clamps and block structure as the DLL.

```bash
python scripts/audio/sdvx_fx.py in.wav out.wav --effect retrigger --params 95,2.0,1.0,4,0.85,0.15
python scripts/audio/sdvx_fx.py in.wav out.wav --effect laser_lpf --params 90,400,18000,0.7 --knob 0:0,4:127
python scripts/audio/sdvx_fx.py in.wav out.wav --effect wobble --params 80,0,3,500,18000,4.0,1.4 --range 8:16
python scripts/audio/sdvx_fx.py --list
```

`apply_chart.py` drives it from a real chart: it parses the `.vox`, decodes the `.s3v` (plain ASF/WMA — ffmpeg handles it), and applies every FX‑button hold and laser segment at the times the chart specifies.

```bash
python scripts/audio/apply_chart.py data/music/2229_kamui_tjhangneil -d 5m -o kamui_fx.ogg
```

Output defaults to Vorbis `.ogg`; the `-o` extension picks the container. The engine's own int16 writeback (§2) always happens first, so a lossy container is applied *on top of* the game's output stage, never instead of it — but pass a `.wav` name for the calibration metric of §7, whose numbers were all measured on PCM.

It also reproduces the parts of the chain that live *outside* the effect generator: the device ParamEq that is the default laser sound, its 80 ms lag and its music duck (§7.1), and the layered SE (§6.1). The diagnostics that isolate each of those:

```
--no-peak        skip the device ParamEq entirely
--peak-delay S   knob lag before it reaches the EQ (default 0.08, the engine's value)
--peak-always    run the EQ during every laser, not only C4 = 0 ones
--peak-post-se   put the EQ after the SE are mixed instead of before
--no-duck        skip the music-voice duck; --duck-rate sets its ramp (default 0.33/s)
--duck-hold      freeze the duck target between lasers (rejected, see 6.1.4)
--slam-index N   which virtical_shot sample a slam plays (0 or 1)
--se-polyphonic  let overlapping slam samples sum instead of restarting one voice
--se-trim X      global multiplier on the header-derived SE gains (default 1.25)
--slam-gain X    override the slam level outright, ignoring its header and the trim
--se-gain X      the same for FX chip samples
```

Track layout in `.vox`: `#TRACK1` = VOL‑L, `#TRACK2` = **FX‑L**, `#TRACK3..6` = BT‑A..D, `#TRACK7` = **FX‑R**, `#TRACK8` = VOL‑R. Cell resolution is 48 per 1/4 note.

```
FX    C0 timing   C1 length(cells, 0=chip)   C2 chip:sample / hold:effect+2   C3 cells-per-chain
laser C0 timing   C1 position (v10 0..127, v12 0.0..1.0)   C2 node type (0 mid/1 start/2 end)
      C3 roll type   C4 LASER EFFECT   C5 range (1/2 wide)   C6 unused
      C7 curve type  C8 roll length    C9 cells-per-chain
```

**C4 is the laser effect, not C7.** C7 is the curve type; both range 0..5 in practice, which made the mistake look plausible for a while. Using C7 put filters at the wrong times with the wrong indices over the whole chart.

Not yet handled: `#TRACK AUTO TAB` (applies FX‑hold effects to lasers, with the parameter ramp from `#TAB PARAM ASSIGN INFO`) and `#TRACK ORIGINAL L/R`.

Requires `numpy` (and optionally `scipy` for faster IIR), plus `ffmpeg` for `.s3v` decoding.

### Worked example — `2229_kamui_tjhangneil` (MXM, 210 BPM)

```
12 FX defs, 5 laser defs, 153.1 s track
  FX buttons : Echo x28  Flanger x22  Gate x11  BitCrusher x11  Wobble x10
               TapeStop x8  HPF x7  Retrigger x1
  lasers     : LPF x6  BitCrusher x4  HPF x2      (C4 = 1..5, engine DSP)
               peak filter x57 runs                (C4 = 0, the device ParamEq - 7.1)
  device EQ  : active in 67.2 s of 153.1 s, knob reaches 127
  layered SE : 138 laser slams,  3 sampled FX chips
```

All modified regions line up with the chart's own note times (e.g. the flanger hold at measure 7 → 6.857–7.286 s, changed 100 %). Output in `output/` (git-ignored); `slam_demo_A/B` is the 49.5–63.5 s window, which contains four laser slams on the resonant HPF.

FX **chip** notes produce no *track effect* — they have zero length and every wrapper requires at least one full block. They do, however, trigger a layered sample; see §6.1.

### 6.1 The layered SE bank — laser slams and FX chip notes

Not everything you hear is the effect engine. Two gameplay events mix a **sample** on top of the track, from `data/sound/ver5/general_sampler.s3p` (registered as bank id **9** by the loader at `0x1805c5960`; `sys_sd_shotfx.2dx` is bank 4 and carries the same 15 names).

Container format:

```
'S3P0', u32 count, count * { u32 offset, u32 size }
each entry: 'S3V0', u32 headerSize, ... , then an ASF/WMA stream at +headerSize
```

The 15 entries, decoded (44100 Hz stereo, single transient + decay tail each):

| idx | name | dur | attack | role |
|---|---|---|---|---|
| 0 | `fs00_virtical_se01` | 1.78 s | 228 ms | **laser slam** (played from bank `0xd`, §6.1.1) |
| 1 | `fs01_virtical_se02` | 3.03 s | 1.1 ms | also a laser sound — trigger condition unknown |
| 2–14 | `fs02_shot01` … `fs14_shot13` | 0.40–6.15 s | 1–30 ms | **FX chip note** hit sounds |

Index 0 is the only entry with a slow (228 ms) attack — everything else attacks in under 30 ms — which is consistent with it being a swell rather than a click.

**Which chip sample plays** comes from the FX note's C2 — the same column that means "effect definition + 2" on a *hold*. On a chip it is a `general_sampler` index directly, and **0 means no sample**, which is the common case:

```
#TRACK2/#TRACK7, chip notes (C1 == 0):     C2 = 0 -> silent
                                           C2 = 1..14 -> general_sampler[C2]
1  big snare (quiet)   2  big clap      3  short clap    4  big snare
5  short snare         6  crash         7  kick+crash+downlifter
8  open hi-hat         9  kick+crash    10 snare+click   11 female "oh"
12 male "hey"          13 male "yeah"   14 fireworks
```

On `2229_kamui` MXM that is **3 sampled chips out of 228** — 110 of 111 FX‑L chips carry C2 = 0. There is no "default sample" concept; an earlier revision of this document claimed one and was wrong.

Index 1 (`fs01_virtical_se02`) is accounted for by this table: it is chip sample 1, "big snare (quiet)", noted as possibly unused.

### 6.1.1 The trigger code (found)

The sound-manager voice API is `Play = FUN_1805c6ec0(this, bankId, sampleIdx, flag)` (it invokes the voice's `vtable+0x10`) and `SetVolume = FUN_1805c6e40(this, bankId, sampleIdx, vol)` (`vtable+0x40`, `vol * 1/127`, so volume is an integer 0…127).

Both gameplay triggers live in the event dispatcher `FUN_180407200`. Ghidra types its switch selector as `float`, so the case labels render as tiny denormals — they are int bit patterns (`2.8026e-45` = 2, `4.2039e-45` = 3, `5.60519e-45` = 4, …).

**FX chip note** — case 4:

```c
if ((0 < (int)idx) && (idx != 255)) {
    snd = FUN_1800967c0();
    FUN_1805c6ec0(snd, 9, idx);        // bank 9 = ver5/general_sampler
}
```

Exactly the rule inferred from the chart data: index 0 and 255 are silent, 1…14 select a sample. Same function, case 3, also carries the laser mirroring (`if (field == 2) v = 1.0f - v;`), independently confirming §7.1.

**Laser slam** — a two-stage path. Event **kind 6** (`0x18040773a`, variant tag 5) is a *scheduled play* request; the dispatcher converts it to a queue entry at `gameAudio+0x80`:

```c
entry.index = event.a;                                     // event+0x08, verbatim
entry.due   = now - (long long)((event.time - audioPos) * 1000.0f);   // ms clock
```

and drains that queue later in the same call, once `entry.due < now`:

```c
FUN_1805c6ec0(snd, 0xd, entry.index, 0);   // bank 0xd = ver5/virtical_shot
```

So the slam sound is **not** played out of `general_sampler`. Bank `0xd` is `/data/sound/ver5/virtical_shot.s3p`, a two-entry bank whose payloads are the same size as `general_sampler`'s first two (58804 / 148132 bytes) — the same audio, separate bank.

**The sample index is carried by the event, not computed at play time** — `event+0x08` goes straight into the queue and straight into `Play`. So the `fs00` / `fs01` choice is made by whatever builds the kind-6 events, upstream of `Game::GameAudio`. That producer was not found: the event vector arrives as `Update`'s second argument, the records are built somewhere that neither the `mov [reg+4], imm` / `mov byte [reg+0x18], imm` scans nor xref-chasing from the `Game::GameAudio` vtable reached. Measured on the capture, this chart uses index 0 throughout (§7.2). (`apply_chart.py` uses `general_sampler[0]`, which is byte-identical to `virtical_shot[0]`; `--slam-index 1` selects the other.)

The full bank table, from `FUN_1805c5960` (`lea edx, [r9 + N]` with `r9` zeroed gives the id):

```
0 sys_sd_credit.2dx   1 sys_sd_sram.2dx    2 <the song's own .s3v, loaded per song>
3 sys_sd.2dx          4 sys_sd_shotfx.2dx  6 00_title_bgm_06   7 sys_sd_virtical.2dx
8 ver6/bgm_00         9 ver5/general_sampler   0xd ver5/virtical_shot
0xe voice_mitsuru_00  0xf voice_tama_00     0x10 hexa    0xa..0xc,0x11..0x18 ver6/se_*
```

Caveats:

* **The SE mix level is authored in the sample files, not in the code — see §6.1.4.** That is why the search through `Play` and `SetVolume` came up empty, and the dead end is worth keeping on record: `Play` (`FUN_1805c6ec0`) only calls the voice's `vtable+0x10`, and it carries no level. Volume is the separate `FUN_1805c6e40` (`vtable+0x40` → `0x1806a2100`, clamped to `[0,4]`, stored at `voice+0x70`). Enumerating all **19** call sites of it — via `.pdata`-anchored disassembly, not a linear sweep — turns up no literal bank `9` or `0xd` anywhere; the only literal volumes are `0` and `127`. All of that is true and all of it is beside the point: the level never travels through `voice+0x70` at all, it is set once at bank-load time on the voice's *mixer connection*.

The 8-factor mechanism below is still the right description of `voice+0x70`'s neighbourhood. `FUN_1806a3640(voice, bit, value)` writes one of **8 independent gain factors** and rebuilds a 256‑entry lookup table at `voice+0x6c`, indexed by an active‑factor bitmask:

  ```
  bit 0 -> [+0x70]   bit 1 -> [+0x74]   bit 2 -> [+0x7c]   bit 3 -> [+0x8c]
  bit 4 -> [+0xac]   bit 5 -> [+0xec]   bit 6 -> [+0x16c]  bit 7 -> [+0x26c]
  entry[mask] = product of the factors whose bits are set   (entry[0] = 1.0)
  ```

Powers of two index the factors themselves, so `SetGain` writes `[+0x6c + bit*4]` and the table stays self‑consistent. `+0x70` is the volume `SetVolume` writes and the one the mixer ramps toward `+0x78`. The remaining seven are set through virtual dispatch and were not traced to their sources. They are also not where the SE level lives.

`--slam-gain` is still fitted against the capture (§7.2), but it now has a derived value to be compared against, and the two disagree by about 2 dB — see §6.1.4. It is worth knowing how much the fit moves when the structure around it changes: the §7.1 correction (up to +15 dB of EQ and a duck on the music path but not on the SE) left it at 0.5, but the §6.1.3 one-voice fix moved it to 0.65. A fitted constant absorbs whatever the model is missing. For context on why the slam needs a gain of its own at all: `fs00_virtical_se01` peaks at **17446** of 32767 — about 5.5 dB below the chip samples (28765–32767) — and its 228 ms attack costs it more in perceived loudness. Measured on `2229_kamui`, median level added over music+effects in the 250 ms after each slam:

  | slam level | sample peak | slam vs music | output clipping |
  |---|---|---|---|
  | 0.25 | 4362 | under +1 dB | 0.05 % |
  | **0.689 (what ships: 0.5513 × 1.25)** | ~12000 | ~+2 dB | 0.02 % |
  | 1.0 | 17446 | +3.7 dB | 0.08 % |
  | 1.6 | 27914 | +6.1 dB | 0.54 % |
  | 2.2 | 38381 (self-clips) | +7.4 dB | 1.45 % |

Chip samples do **not** share that number — their headers put them 7.83 dB lower (§6.1.4). This chart cannot tune a chip-specific level anyway: 3 sampled chips in 153 s move the metric by 0.002.

### 6.1.2 SE levels come from the samples, not from the code

Every `Play` for a sampled SE passes a flag of zero, never a level:

```
FX chip   0x18040752a:  xor r9d, r9d ; mov r8d, [rdi-4] ; lea edx, [r9+9]  ; call Play
slam      0x1804080e4:  xor r9d, r9d ; mov r8d, [rcx]   ; lea edx, [r9+0xd]; call Play
```

`Play` forwards to the voice's `vtable+0x10` (`0x1806a1cc0`), which only calls the "prepare and start" routine — it takes no gain. And the voice it starts was initialised at unity:

```
VoiceImpl ctor, 0x1806a183a:
    mov qword [rbx+0x70], 0x3f800000    ; volume = 1.0f , pan = 0.0f
    mov qword [rbx+0x78], 0x3f800000    ; ramp target = 1.0f , ramp state = 0
```

Nothing ever moves `+0x70` for bank 9 or `0xd` — all 19 `SetVolume` call sites in the DLL were enumerated (§8) and none names either bank. So **no level reaches the SE through the `Play` / `SetVolume` path.** The level arrives by a different route entirely, once per sample when the bank is loaded (§6.1.4); `+0x70` really does stay at unity for the whole track.

Which means the loudness differences you hear between hit sounds are baked into the samples:

| idx | name | dur | peak | peak dBFS | loudest 300 ms RMS |
|---|---|---|---|---|---|
| 0 | `fs00_virtical_se01` (slam) | 1.78 s | 17446 | −5.5 | 5341 |
| 1 | `fs01_virtical_se02` | 3.03 s | 10386 | −10.0 | 4002 |
| 2 | `fs02_shot01` | 1.73 s | 28765 | −1.1 | 9256 |
| 3 | `fs03_shot02` | 0.78 s | 32767 | −0.0 | 8179 |
| 9 | `fs09_shot08` | 2.90 s | 32768 | 0.0 | **11057** |
| 10 | `fs10_shot09` | 1.31 s | 32768 | 0.0 | 9682 |
| 14 | `fs14_shot13` | 6.10 s | 23029 | −3.1 | 4307 |

The chip samples are mastered hot — several sit at digital full scale — while the slam sits 5.5 dB lower with a 228 ms swell instead of a transient. `fs09_shot08` is **6.3 dB** above the slam in RMS. That spread is authentic; do not flatten it.

That spread is only half the story, though. On top of the mastering, each sample carries an authored gain in its own file header, and the slam and the chips are given **different** ones — so `--se-gain` and `--slam-gain` are not the same number after all. §6.1.4.

### 6.1.4 The per-sample gain is in the `S3V0` header, not in the DLL

Each entry of an `.s3p` bank (and each standalone `.s3v`) begins with a 32-byte header:

```
+0x00  'S3V0'
+0x04  u32   header size (always 0x20; the WMA/ASF payload starts here)
+0x08  u32   payload size
+0x0c  u32   checksum
+0x10  u32   (0 for every gameplay sample)
+0x14  i16   gain,  8.8 fixed-point decibels        <-- the missing level
+0x16  i16   gain trim, same units (0 for every gameplay sample)
+0x18  u32   (0)
+0x1c  i16   pan, /32768                            (0 for every gameplay sample)
```

The bank loader (`0x1805ce7b0`, the `'S3V0'` check is at `0x1805ce834`) reads the header into locals and does, per sample:

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

so

```
gain = 10 ^ ( ( (i16)hdr[0x14] + (i16)hdr[0x16] ) / 256 / 20 )
```

`0.00390625` is 1/256 (the 8.8 fixed point), `0.05` is 1/20, and `0x18076b420` is `powf` — the whole thing is a decibel-to-amplitude conversion. The values in the files are dominated by multiples of `0x80`, i.e. authored in 0.5 dB steps, which is what settles the fixed-point interpretation.

The target is **not** `voice+0x70`. `VoiceImpl::vtable+0xd0` (`0x1806a2fc0`) is `return this->connections[i]`, and `MixerConnectionImpl::vtable+0x20` (`0x1802fbf40`) is one instruction, `movss [conn+0x20], xmm1`. The connection is created with a gain of `1.0` (`0x180623c41`, from the `0x3f800000` the loader puts in the creation params at `0x1805cea8d`) and the header value overwrites it immediately. One connection per voice, set once, never touched again — which is exactly why every xref hunt through `Play` and `SetVolume` found nothing.

The standalone `.s3v` loader (`0x1805cf8c8`) does the same arithmetic on the same fields, so the song's own track goes through it too.

Measured out of the shipped files:

| bank | sample | `hdr+0x14` | dB | linear |
|---|---|---|---|---|
| `0xd` `virtical_shot` | 0 `fs00_virtical_se01` (**the slam**) | −1324 | −5.172 | **0.5513** |
| `0xd` `virtical_shot` | 1 `fs01_virtical_se02` | −2072 | −8.094 | 0.3938 |
| `9` `general_sampler` | 0, 1 | −1324 | −5.172 | 0.5513 |
| `9` `general_sampler` | 2..13 `fs02_shot01`..`fs13_shot12` (**FX chips**) | −3328 | −13.000 | **0.2239** |
| `9` `general_sampler` | 14 `fs14_shot13` | 0 | 0.000 | 1.0000 |
| `2` | `2229_kamui_tjhangneil.s3v` (**the music**) | 0 | 0.000 | 1.0000 |

Two things fall out immediately. The chips are **7.83 dB below the slam**, not equal to it as §6.1.2 previously argued — the engine does distinguish them, it just does it in the data. And the music is at unity, so these numbers are directly the SE-to-music ratio.

Note also that `virtical_shot[1]` and `general_sampler[1]` are byte-identical audio with *different* header gains (−8.09 vs −5.17 dB), which rules out the field being anything derived from the payload. It is authored per bank instance.

**Where it does not yet agree with the capture.** Rendering with the derived pair scores 1.826 against the fitted 0.65/0.65's 1.799. Sweeping the slam gain with the chips pinned at 0.2239:

```
slam gain   0.40   0.45   0.50   0.5513   0.60   0.65   0.70   0.78
score       1.943  1.897  1.858  1.826    1.807  1.797  1.797  1.816
```

The optimum is ~0.69, i.e. **about 2 dB above** the header. That is not an artefact of the global metric: restricting scoring to the 1187 frames a slam is sounding in, and taking the level offset only from frames far from any slam, gives the same answer (0.70 best, 0.5513 worse by 0.15). Chips remain unmeasurable on this chart (1.795–1.799 across 0.12→0.67), so the derived 0.2239 is neither confirmed nor contradicted — it simply sits in the flat region.

What was ruled out for the missing 2 dB:

* a per-bank level — `FUN_1805c63b0(this, bank, path, flag)` takes no gain, and the registration table at `FUN_1805c5960` passes only ids and paths;
* a music-side attenuation from the duck resting below unity — `0x1805c7b3d` really does load `1.0` and jump straight to the tail when the knob is under 4, so §7.1's transcription stands;
* the duck target being frozen between lasers rather than returning to unity (`--duck-hold`) — it moves the slam optimum to 0.52–0.55, which is suggestive, but it costs 0.34 overall (2.135 vs 1.797) and leaves a +1.65 dB global level offset, so it is the wrong model;
* additive layering supplying the difference (`--se-polyphonic`) — 1.876 at 0.5513, worse than one-voice at any gain;
* another module owning the mixer — `S3P0`/`S3V0`/`2DX9` appear in `soundvoltex.dll` and in no other DLL in `modules/`.

The metric can only see the SE-to-music *ratio*, so a constant 0.8 on the music path would be indistinguishable from a constant 1.25 on the SE path. Nothing found so far puts one there.

**How `apply_chart.py` uses this.** `load_s3p` now returns a 4th field per sample, its header gain (`s3v_gain`), and each SE is mixed at `header_gain * --se-trim`. The trim defaults to **1.25**, which is exactly the unexplained 2 dB and nothing else — set `--se-trim 1.0` to hear what the files literally say. `--slam-gain` / `--se-gain` still exist but are now *overrides* that bypass both. The slam's level is read from `virtical_shot.s3p` rather than from the `general_sampler` copy the audio is loaded from, because the two banks disagree on index 1.

That split is deliberate: the ratio between samples is derived and should not be touched, while the one number that is still a fit sits in one place with its own flag. Scores are unchanged — `0.5513/0.2239 * 1.25` gives 1.796, the same as the old fitted `0.65/0.25`.

### 6.1.3 One voice per sample — SE do not layer

`Play` resolves the bank and index to a **single, persistent voice object**:

```c
voices = FUN_1805c5830(bank);                  // vector<shared_ptr<Voice>>, 16 bytes/entry
voice  = voices[index];
voice->vtable[0x10](flag);                     // Start on THAT voice
```

There is one voice per `(bank, sampleIndex)` pair, allocated when the bank is loaded, and `Play` starts it. So re‑triggering a sample that is still sounding **restarts that voice** — it does not allocate a second one and let the two sum. The voice's own gain (`voice+0x70`, §8) confirms the same thing from the other side: there is one gain per sample, not one per note.

This matters on real charts because the slam sample runs 1.78 s while slams come far faster. On `2229_kamui` MXM the median gap between slams is **0.429 s**, and at some onsets ten copies would still be sounding if they were allowed to accumulate:

```
138 slam points -> 124 distinct onsets   (14 are VOL-L and VOL-R slamming on the same tick,
                                          which is still one Play into one voice)
inter-slam gap   min 0.000 s   median 0.429 s   max 13.286 s
overlapping copies alive at an onset, if layered:  1..10
```

Both halves of that are worth stating separately, because an additive mixer gets both wrong:

* **coincident slams are one sound, not two.** Mixing per track double‑levelled 14 of them;
* **close slams truncate the previous one.** Letting the tails sum makes the SE layer's level track slam *density* rather than staying constant.

Measured: layering scores 1.889, one‑voice restart scores **1.858**. `apply_chart.py` does the restart by default and truncates each slam at the next onset; `--se-polyphonic` restores the old additive behaviour for comparison.

The fitted slam level moves with this, which is a good illustration of what a fitted constant really contains: with layering allowed the optimum was 0.5, because the stacking was quietly supplying level the single gain was missing. With one voice it is **0.65–0.70** (§7.2), and the sample's own header says 0.5513 (§6.1.4) — so even after the fix the fit is still carrying something.

### 6.2 Output stage — `CGainWithHardLimiter`

`BMSoundLib2017::CGainWithHardLimiter::Process` (`0x18069f090`, vftable `0x180925df8`) is, in full:

```
gain  = this->0x18 (float)          set by 0x1802f8120
limit = this->0x1c (float)          set by 0x1802fbf30   (both at once: 0x1802ffe90)
for each sample (SSE, 4 at a time):
    x = x * gain
    x = min(max(x, -limit), +limit)
```

Despite the name there is no knee, no lookahead and no release — it is a **gain followed by a hard clip**. That matters for level decisions: the shipped game clips its own output, so mixing SE hot enough to occasionally clip is authentic, not a rendering artefact. An earlier revision of this document chose an SE level of 0.25 specifically to avoid clipping; that reasoning was wrong and made the slams inaudible. `--master-gain` exposes the same gain-then-clip stage.

---

## 7. Calibration against a capture of the real game

`scripts/audio/reference/kamui_goal.ogg` is a recording of the actual cabinet playing this chart. It is **not** a clean render — it is polarity‑inverted, Ogg‑coded, and its clock drifts against the game's audio by **+0.346 samples/second (7.9 ppm)**, i.e. +45 samples over the track. So no sample‑exact diffing: coherent averaging over 124 slams still gave correlations ≤ 0.06.

What does work is a **phase‑insensitive spectral metric**: 46 log‑spaced bands per 46 ms frame, level‑normalised, mean |dB| difference. The floor is set by codec noise — on frames where the chart does nothing, an untouched track already scores 1.22.

| render | all | FX | peak‑laser | tab‑laser | idle |
|---|---|---|---|---|---|
| untouched track | 3.169 | 4.808 | 4.247 | 5.557 | 1.221 |
| effects only, no SE | 2.934 | | | | |
| + layered SE | 2.380 | | | | |
| + peak filter, *fitted* (old) | 2.310 | 3.123 | 3.011 | 2.788 | 1.137 |
| effects + peak, no SE | 2.500 | | | | |
| + peak filter, transcribed (§7.1) | 1.924 | 2.583 | 2.127 | 2.698 | 1.362 |
| **+ one voice per SE sample (§6.1.3)** | **1.799** | 2.520 | 1.929 | 2.320 | 1.327 |

The idle column gets *worse* between the last two rows purely as a normalisation artefact: the metric matches one global level offset across the whole track, and the music duck (below) lowers 62 % of it, so the untouched frames now sit off that common offset. Every region that the chart actually touches improves.

### 7.1 The default laser filter — transcribed

**This is now read out of the binary, not fitted.** The path the earlier revision could not find does not go through the SVO effect generator at all; it goes through the gameplay event dispatcher and the sound device.

`FUN_180407200` (`Game::GameAudio::Update`, vtable slot 1 @ `0x1808cb848`) walks a vector of 28‑byte gameplay events. The record is

```
+0x00  ?                 +0x04  int  kind (2..7, the switch selector)
+0x08  int   a           +0x0c  float pos / time
+0x10  int   b           +0x18  byte variant tag (= kind - 1)
```

Kind 3 = laser (`0x1804074aa`, asserts tag 2). Per tick it keeps **one** accumulator over every laser event:

```c
disableEq = (event.b != 0);                       // event+0x10
v = (event.a == 2) ? 1.0f - event.pos             // event+0x08: 1 = VOL-L, 2 = VOL-R
                   : event.pos;
acc = max(acc, v);                                // both knobs share one filter
```

`acc` is pushed with a timestamp onto a queue at `gameAudio+0x58`, and popped only once the head entry is **older than 80 ms** (`comiss xmm0, 0.08` @ `0x180407f61`) — so the filter lags the knob. If `disableEq`, the queue is flushed and the knob is forced to 0. The popped value ×127 goes to `FUN_1805c7a00`:

```c
v  = clamp((int)knob, 0, 127);
fc = clamp(TABLE[v], 80.0f, 16000.0f);            // DSFXPARAMEQ_CENTER_MIN/MAX
if      (fc <  200)  bw = gain = fc * 0.075f;     //  6.0 .. 15.0, continuous at 200
else if (fc < 1000)  bw = gain = 15.0f;
else               { bw   = 15.0f - (fc-1000)*0.0003f;    // 15.0 .. 10.5
                     gain = 15.0f - (fc-1000)*0.0005f; }  // 15.0 ..  7.5
if (v < 4) gain = 0.0f;                           // dead zone: EQ flat

FUN_180626b30(device, 0, fc, bw, gain);           // -> _DSFXParamEq slot 0 of 7
```

`TABLE` is 128 floats at **`DAT_18090c050`**: a hand‑drawn, piecewise‑linear ramp `0, 6, 12 … 54, 100, 106 … 202, 232 … 3672, 3852 … 6912, 7400, 7700, 8000, 8400 … 10800`. Values under 80 Hz are clamped away, so the first ten entries all read as 80 Hz.

The struct really is `{fCenter, fBandwidth, fGain}` — `FUN_180626b30` writes its 3rd/4th/5th float args to `[rsp+0x20/0x24/0x28]` and hands that to the driver. `fGain` is the field forced to 0 in the dead zone, which settles the ordering: a bandwidth of 0 would be out of range, a gain of 0 is exactly "EQ off".

The DMO itself is **not** in this binary. `CDmoSoundFxAudioProcessor<_DSFXParamEq>` (`0x180919970`) and `CDmoSoundFxDriver<IDirectSoundFXParamEq,_DSFXParamEq>` (`0x180919998`) are thin forwarders to a COM object at `this+0x10`; the sample math is Microsoft's standard `GUID_DSFX_STANDARD_PARAMEQ`. `sdvx_fx.peaking_coeffs_bw` models it as the RBJ cookbook peaking filter with `BW(octaves) = fBandwidth / 12`, which is what "bandwidth in semitones" means. That one step is a documented‑behaviour assumption, not a transcription.

The same call ducks the music. Bank 2 is the song's own `.s3v` (registered per song by `FUN_1805c63b0(this, 2, path)`, up to 6 stems); every bank‑2 voice gets a target gain

```c
if (v <  4)  g = 1.0f;
if (v < 95)  g = 0.8f - (v - 4) * 0.0025274728f;  // 0.800 .. 0.570
if (v < 100) g = 0.57f;
if (v < 120) g = 0.57f + (v - 100) * 0.011500001f;
else         g = 0.8f;
```

through voice `vtable+0x60` (`0x1806a21f0`), which writes a **target**; the mixer chases it at **0.33 gain units per second** (`0x1806a25b1`, where the multiplier is `frameCount / sampleRate`, i.e. seconds). So it is a slow, shallow duck, not a gate.

Where the EQ sits was settled by measurement: running it **before** the layered SE are mixed in scores 1.924, **after** scores 2.029. Slot 0 of the device's 7 ParamEq slots is on the music path, upstream of where the SE voices join.

Three things the capture confirms independently of the disassembly:

| prediction from the code | test | result |
|---|---|---|
| 80 ms queue delay | sweep `--peak-delay` | minimum at exactly 0.08 s (0.06 → 2.088, 0.08 → **1.924**, 0.10 → 2.155) |
| `event+0x10 != 0` mutes the EQ | `--peak-always` | tab‑laser regions 2.787 → **3.820**; peak‑laser unchanged. So that field is the C4 effect index |
| the music duck exists | `--no-duck` | 1.924 → **2.195** |

The old fitted curve (`fc(x) = 180·(8400/180)^x`, +4 dB, Q ≈ 1.0) was a fair reconstruction of the table's middle: the table's top entry really is 8400 Hz at knob 122, and 15 semitones of bandwidth is Q ≈ 1.12. It underestimated the gain badly (+4 dB vs +15 dB) because the measurement was a median over smoothed bands, and it missed the dead zone, the delay and the duck entirely.

### 7.2 SE levels

Same metric, sweeping the layered‑sample gains against the corrected baseline:

```
slam gain   0.40   0.55   0.60   0.65   0.70   0.80   1.00
score       1.943  1.827  1.807  1.797  1.798  1.825  1.940
```

**0.65** is the optimum, flat between 0.65 and 0.70. Note this number is only meaningful together with the one-voice rule of §6.1.3: while overlapping copies were allowed to sum, the fit came out at 0.5, because the stacking was supplying the missing level.

The derived value from the sample headers (§6.1.4) is **0.5513** for the slam and **0.2239** for the chips — the first about 2 dB under this fit, the second unmeasurable on this chart. So the level is no longer *only* fitted, but the fit and the file still disagree; §6.1.4 lists what has been ruled out for the difference.

What ships now is the derived pair times a single `--se-trim`, which at 1.25 lands on 0.6892 / 0.2798 and scores the same 1.796. Sweeping the trim itself, which is the same experiment expressed in the units the mystery is actually in:

```
--se-trim   0.80   0.90   1.00   1.10   1.25   1.40
score       1.905  1.861  1.826  1.805  1.796  1.813
```

1.00 is what the files say; the minimum is at 1.25, i.e. **+1.9 dB**. Whatever explains that should collapse this flag to 1.0.

Which slam sample plays is settled for this chart: rendering with `virtical_shot[0]` (`fs00_virtical_se01`) scored 1.924 against `virtical_shot[1]`'s 2.366 and 2.500 for no SE at all. Index 0 it is; index 1 never occurs here.

## 8. Known gaps / caveats

The two that matter most, both on the SE side (§6.1.1 has the detail):

* **The SE-versus-music level is derived now (§6.1.4) but ~2 dB under the fit.** The per-sample gain is an 8.8 fixed-point dB field at `+0x14` of every `S3V0` header, converted with `powf(10, dB/20)` at bank-load time and written to the voice's mixer connection: slam −5.17 dB (0.5513), FX chips −13.00 dB (0.2239), music 0 dB. Against the capture the slam still fits best at ~0.69. A constant ×0.8 somewhere on the music path would reconcile the two exactly; nothing found so far puts one there, and §6.1.4 lists the candidates already excluded.
* **What selects `fs00_virtical_se01` vs `fs01_virtical_se02`** is authored into the kind-6 event stream (`event+0x08` goes straight through the schedule queue into `Play`), and the producer of that vector was not found. The capture says this chart is all index 0.

And the rest:

* **Pitch Shift (`.vox` id 9)** and the **composite kind 14 (`.vox` id 13)** are identified but not transcribed to the sample level. Kind 14 re‑enters the dispatcher at `0x180633360`, i.e. it is the "parameters animate over the note" path rather than a distinct DSP. Observed chart ranges across all 8103 charts, if you want to probe it: id 13 uses `p1 ∈ [0,100]` (mix), `p2 ∈ [-24,24]`, `p3 ∈ {0, 0.5, 1, 2}` (316 occurrences); id 9 uses `p1 ∈ [4,100]`, `p2 ∈ [-12,100]` (1283 occurrences).
* **Tape Stop Ex (`.vox` id 10, `0x180640c20`)** is structurally understood (pre‑roll + windowed slow‑down) but the exact envelope constants were not fully transcribed.
* **The knob value feeding laser filters** comes from `#TAB PARAM ASSIGN INFO` and the laser segment interpolation; I documented the 0..127 → cutoff mapping but not the laser‑position → 0..127 assignment table.
* Block size in the game is the audio device's callback size (`gen+0x1a0`). Since coefficients and LFO values update per block, output is *block‑size dependent*. `sdvx_fx.py` defaults to 64 frames (`--block`); pick the same value if you are diffing against a capture.
* The chart's first integer on Retrigger/Echo/Gate rows is consumed by the wrapper for musical grid snapping (`FUN_18062e310`, `samplesPerBeat = trunc(2646000/BPM)`), not by the DSP.

### 8.1 Effect combination — what stacks, what overwrites

Charts routinely have two effects live at once: both FX buttons held, or an FX hold running underneath a laser sweep. How the second one combines with the first is **the one place where the disassembly and the capture disagree**, and the shipped default follows the capture. Everything below is what `--laser-mode` selects.

Three possible models, with `x` the track, `A` the FX-button effect and `B` the laser effect:

| model | meaning | result |
|---|---|---|
| `chain` | series — `B` processes `A`'s output, like two pedals in a row | `B(A(x))` |
| `dry` | overwrite — `B` reads the original track and replaces `A` where they overlap | `B(x)` |
| `add` | parallel — both read the original, their changes sum | `x + (A(x) − x) + (B(x) − x)` |

Order matters in `chain` and does not in `add`. A bit crusher into a lowpass is not the same sound as a lowpass into a bit crusher: the first filters already-aliased audio, the second aliases already-smooth audio.

**Three cases, and only one of them is in doubt.**

**FX-L + FX-R, both held — genuinely chained, not disputed.** The FX dispatcher `FUN_18062e3d0` loops its sub-index and swaps the generator's source pointer to the partial result, so the second button reads the first's output. Straight series inside the generator.

**The default peak filter + anything — a separate stage, so the question does not arise.** The C4 = 0 laser sound is a device `_DSFXParamEq` (§7.1), not a generator effect. It is downstream of the whole generator and upstream of the SE mix, so it always stacks on top of whatever the generator produced, in that fixed order. It cannot overwrite a generator effect and a generator effect cannot overwrite it.

**Tab-laser effect (C4 = 1..5) + FX button — this is the unresolved one.** The disassembly points at `dry`. `FUN_18062e3d0` restores the generator's source to the original track on the way out:

```
if (1 < lVar19) { puVar5 = *param_1; *puVar5 = param_2; ... }
```

and the laser dispatcher `FUN_18062ea60` then runs against that restored source and `memcpy`s its result over the destination — which reads as "lasers process the dry track and overwrite whatever the FX buttons wrote".

Against the capture that model loses. `chain` scores best and is the default; `dry` and `add` were both measurably worse. So `apply_chart.py` ships the model the binary appears to contradict.

**The per-model scores were never written down** — only the verdict. That is a gap in this document, not a missing experiment: re-run `--laser-mode chain|dry|add` through `tools/metric.py` and record the three numbers here. Until then, treat "chain wins" as a measured claim whose margin is unknown.

Possible resolutions, none of them checked: the restore may apply only to the FX sub-chain and not to the laser stage; `param_2` may already point at the FX result rather than the original track by the time it is restored; or the overlap on this one chart may be too small to separate the models cleanly, in which case the measurement is weaker than it looks. Anyone reopening this should start by counting how many frames of `2229_kamui` actually have an FX hold and a C4 = 1..5 laser live simultaneously — `tools/blendfit.py` already reports the FX+laser and FX-L+FX-R overlap cases for exactly this reason.

**Two consequences that apply whenever effects do stack.**

*Mix compounds rather than averages.* Every effect computes `out = (1-mix)·dry + mix·wet` against **its own input**, not against the original track. Two effects at 50 % leave the original at 25 %, not 50 %.

*There is an int16 requantisation between stages.* `FUN_18063dc40` writes each result back as clamped, truncated int16 before the next stage reads it through `FUN_18063d9e0` (§2). So a chain can clip **mid-chain**, not only at the output stage — a resonant filter feeding a boosting effect will hard-clip at the boundary in a way an all-float implementation would not reproduce. `apply_chart.py --no-stage-clip` disables it for comparison; the engine does clip, so the default keeps it.
