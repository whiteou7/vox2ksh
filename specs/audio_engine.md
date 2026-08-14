# SOUND VOLTEX — audio effect engine, reverse engineered

Target: `modules/soundvoltex.dll` (PE32+ x64, ImageBase `0x180000000`, build `SoundVoltex6_x64Release`, 2025-06-19). All addresses are virtual addresses in that DLL.

Derived from the binary (MSVC RTTI + Ghidra 12.1.2 + capstone), cross-checked against the 8107 `.vox` charts in `data/music/` and against cabinet recordings in `scripts/shared/reference/ksh/`. Numbers introduced as *measured* come from the calibration metric of §7; three values in this document are **fitted, not transcribed**, and each is called out where it appears (Tape Stop Ex's envelope floor §4.6b, the SE trim §7.2, and the peak-EQ damping default §7.1).

---

## 1. Where the effects live

MSVC RTTI gives the engine away immediately:

```
.?AVCSvoEffectedAudioGenerator@BMSoundLibSvo@@
.?AVCSvoEffectedAudioGeneratorImpl@BMSoundLibSvo@@      vftable @ 0x180919ca8
```

`BMSoundLibSvo::CSvoEffectedAudioGeneratorImpl` is the whole FX chain, occupying roughly `0x180628000 – 0x180650000`. Layers:

| layer | address | role |
|---|---|---|
| generator ctor | `0x180628b50` | builds the effect parameter vectors |
| chart → generator | `0x18022db60` | `switch` on the `.vox` effect id, fills the vectors |
| per-block dispatcher | `0x18062e3d0` | `switch` on the internal *kind*, calls a wrapper |
| dispatcher (animated params) | `0x180633360` | same kinds, parameters interpolated over time |
| wrappers | `0x180630110 … 0x180632c10` | chart params → DSP args (BPM, knob position, grid snap) |
| DSP leaves | `0x18063df40 … 0x1806429b0` | the actual sample crunching |

Shared helpers:

| address | function |
|---|---|
| `0x18063d9e0` | **prepare**: int16 source → float L/R work buffers |
| `0x18063dc40` | **writeback**: float → clamped int16, interleaved |
| `0x18062e310` | musical grid snap, `samplesPerBeat = trunc(2646000 / BPM)` (2646000 = 44100·60) |
| `0x180796b80` | `sincosf` (sin in low dword, cos in high dword) |
| `0x18076f5d0` | `sinf` |
| `0x18076b420` | `powf` |

---

## 2. Signal path

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

What matters for bit-comparable output:

* **Sample rate is hard-coded 44100.** The constant `0.00014247585` = 2π/44100 appears in every filter; `44100.0f` in every time-based effect.
* **Everything is single precision `float`**, coefficients included.
* **Dry/wet is uniform**: `out = (1-mix)·dry + mix·wet`, `mix = clamp(param, 0, 100) / 100`. A few effects fold an extra makeup gain into the wet term (noted per effect).
* **Processing is blocked.** Block length is `gen+0x1a0` (the audio callback's frame count). Coefficients and LFO values are recomputed **once per block**, not per sample, so output is block-size dependent. Laser filters start 64 samples early (`iVar1 = *param_3 - 0x40`). **Retrigger alone** additionally has its phase snapped backwards onto the musical grid (§5.2).
* **Quirk** (`FUN_18063d9e0`): if the *left* int16 sample of a frame is exactly `0`, both channels of that frame are forced to `0` in the work buffer. A real branch in the shipped binary, not a decompiler artefact.

---

## 3. Effect inventory

The `.vox` chart id (`#FXBUTTON EFFECT INFO`, first column) maps to an internal *kind* enum which the dispatcher at `0x18062e3d0` switches on. The mapping is set in `FUN_18022db60`:

| `.vox` id | kind | param vec (this+) | fields | wrapper | DSP leaf | effect |
|---|---|---|---|---|---|---|
| 1  | 3  | 0xb0  | 6  | `0x180630fa0` | `0x18063ffb0` | **Retrigger** |
| 2  | 5  | 0xe0  | 35 | `0x1806317a0` | `0x180641d20` | **Gate** |
| 3  | 6  | 0xf8  | 5  | `0x180631cf0` | `0x18063f420` | **Flanger** |
| 4  | 7  | 0x110 | 3  | inline        | `0x180640700` | **Tape Stop** |
| 5  | 9  | 0x140 | 5  | `0x1806324b0` | `0x180641770` | **Side Chain** |
| 6  | 10 | 0x158 | 7  | `0x180632820` | `0x1806414f0` | **Wobble** (LFO-swept filter) |
| 7  | 2  | 0x98  | 2  | `0x180630d10` | `0x18063fc60` | **Bit Crusher** |
| 8  | 4  | 0xd0  | 7  | `0x180631390` | `0x18063ffb0` | **Retrigger Ex / Echo** |
| 9  | 11 | 0x178 | 2  | inline        | `0x1806429b0` | **Pitch Shift** |
| 10 | 8  | 0x130 | 5  | `0x1806320d0` | `0x180640c20` | **Tape Stop Ex** |
| 11 | 12 | 0x70  | 4  | `0x180630110` | `0x18063df40` | **Low Pass Filter** |
| 12 | 13 | 0x88  | 4  | `0x180630760` | `0x18063e500` | **High Pass Filter** |
| 13 | 14 | 0x190 | 3  | `0x180632c10` | (composite) | parameter-animated effect |

Names above are what the DSP actually *does*. Four ids are labelled differently in the inherited community notes; this trace is where the correction comes from:

| id | inherited name | traced here | evidence |
|---|---|---|---|
| 3 | Phaser | **Flanger** — modulated fractional delay + feedback taps | `0x18063f420` |
| 10 | Highpass | **Tape Stop Ex** — 5 float params, tape-stop-shaped clamps, not a filter | `0x180640c20` |
| 11 | Lowpass | **Lowpass** ✓ | setup case `0xb` → vec `+0x70` → kind 12 → `0x18063df40` |
| 12 | Flanger | **Highpass** | setup case `0xc` → vec `+0x88` → kind 13 → `0x18063e500` |

Chart data supports this independently: ids 11 and 12 both carry 4 params (`mix, f, f, Q`) like a filter, while id 3 carries 5.

Lasers (`#TAB EFFECT INFO`) reuse **the same parameter vectors and DSP leaves**, registered into a *second* map (`gen+0x58`, versus `gen+0x38` for FX buttons) with its own enum, by `FUN_180639290/360/430`:

| `#TAB EFFECT INFO` id | laser kind | param vec (this+) | wrapper | DSP leaf | effect |
|---|---|---|---|---|---|
| 1 | 1 | 0x70 (shared with FX kind 12) | `0x180630110` | `0x18063df40` | **Low Pass Filter** (knob-swept) |
| 2 | 2 | 0x88 (shared with FX kind 13) | `0x1806303f0` | `0x18063e500` | **High Pass Filter** (knob-swept) |
| 3 | 3 | 0xa0 (shared with FX kind 2)  | `0x180630a20` | `0x18063fc60` | **Bit Crusher** (knob-swept) |

Which one a laser node uses comes from `#TRACK1`/`#TRACK8` column **C4**: `0` = peak filter (the default sound, below), `1..5` = index into `#TAB EFFECT INFO` (1-indexed), `6` = no filter of its own but the control source for the `#TAB PARAM ASSIGN INFO` sweep (§6.3). This matches `FUN_18062ea60`, which keys its map on `noteField[4] - 1`.

**The peak filter is the default and it is not in this engine.** With C4 = 0 the key is `-1`, landing on the sentinel `FUN_18063a070` installs (`laserMap[-1] = kind 0`, nothing). The band-pass biquad at `0x18063eb10` is reachable only through Wobble's filter-type selector, so it is not the default laser sound either. The real path is a DirectSound parametric-EQ DMO in the **sound device**, driven from the gameplay event dispatcher — transcribed in §7.1. It dominates in practice: on `2229_kamui` MXM, 870 of 894 VOL-L nodes are C4 = 0.

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

`N` = block length in frames, `x` = dry, `y` = wet, `m` = mix (0..1). Transcribed from the decompiled float math, clamps included.

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

Output stages differ:

```
LPF / HPF:  out = ((1-m)*x + m*y) * (1 - Q*0.04)      # resonance make-down
BPF:        G = (Q <= 1) ? max(Q + 0.9, 0.1)
                         : (Q*0.2 + 2.0 > 4.0 ? 3.0 : Q*0.2 + 2.0)
            out = (1-m)*x + m*y*G
```

The LPF/HPF trim `(1 - Q·0.04)` is applied to the **already mixed** signal, so it attenuates the dry path too — that is what makes SDVX laser sweeps duck slightly.

### 4.2 Laser / knob sweep (wrappers `0x180630110` LPF, `0x1806303f0`+`0x180630760` HPF)

Chart params `{mix, freqLo, freqHi, Q}`. Per block:

```
lo    = max(freqLo, 1.0)
ratio = freqHi / lo
v     = knob position, linearly interpolated 0..127 across the laser segment
LPF:  cutoff = lo * ratio ** (1 - v/127)      # v=0 -> freqHi (open), v=127 -> freqLo
HPF:  cutoff = lo * ratio ** (    v/127)      # v=0 -> freqLo (open), v=127 -> freqHi
```

`1/127 = 0.007874016f`. `v` is the laser position itself, linearly interpolated across the segment — nothing else transforms it, and `#TAB PARAM ASSIGN INFO` is not involved (that belongs to `#TRACK AUTO TAB`, §6.3).

Laser Bit Crusher (`0x180630a20`) ignores the chart's rate field once the knob is moving:

```
vnorm = clamp(v/127, 0, 1)
rate  = int(vnorm * 29.0 + 1.0)     # 1..30
```

### 4.3 Bit Crusher — `0x18063fc60`

Pure sample-and-hold decimator, no bit-depth reduction despite the name:

```
m    = clamp(mix,0,100)/100
rate = clamp(rate, 1, 30)
for i in 0 .. blockLen-1:                  # i is the index *within the block*
    k = i % rate
    s = (k == 0) ? x[i] : x[i-k]           # hold the last sample aligned to `rate`
    out[i] = (1-m)*x[i] + m*s
```

The right channel is held together with the left, using the same `k`. The counter is a function local, so **the hold grid realigns at every block boundary** — this effect's output genuinely depends on the audio callback size. Measured: a continuous grid across the whole segment scores 0.582 dB worse on 16/16 charts, so the block realignment is real.

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

The leading integer on a Retrigger/Echo chart row is the repeat `count`, passed verbatim (`0x180631285`, loaded at `0x1806311aa`). `.vox` id 8 (Echo) feeds the same routine with a 7th field the wrapper reads for grid alignment / update period — its meaning is unresolved, and it is `0.00` on every row of every chart examined.

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

The pattern table is 16 int32 values at `struct+0x10`. The default installed by `FUN_18022db60` is the 8-byte pattern `{32, 4}` replicated 8×:

```
[32, 4, 32, 4, 32, 4, 32, 4, 32, 4, 32, 4, 32, 4, 32, 4]
-> gains  [1.0304, 0.1288, ...]
```

So the stock gate alternates full level (with ~0.26 dB of makeup) and −17.8 dB — **not** silence. Measured: a hard binary `1.0 / 0.0` gate scores 1.452 dB worse on 16/16 charts.

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

Playback advances one recorded sample only when `frac` drops below 1, and each advance adds `idx·step·speed + 1` to `frac` — an effective playback rate of ≈ `1/(1 + idx·step·speed)`, a hyperbolic slow-down, while `env` fades linearly to silence over `dur`.

### 4.6b Tape Stop Ex — `0x180640c20`

`.vox` id 10 is a different envelope shape from Tape Stop, not the same effect with two bolted-on params: Tape Stop fades *out* to silence, Tape Stop Ex fades *in* from a floor. Five chart params `mix, speed, duration, preroll, window`.

**The three time fields are in BEATS**, the opposite of plain Tape Stop. Wrapper `0x1806320d0` looks up the BPM at the current block and multiplies all three by `60/BPM` (`0x180632170`–`0x18063218a`) before calling the DSP; the BPM is re-read per block, so a mid-note tempo change rescales all three. Read them as seconds and on any chart above ~120 BPM the preroll outruns the note, the effect never reaches its active branch, and it renders nothing at all — no error, just a dead effect.

After the wrapper's conversion, the DSP clamps in seconds:

```
m       = clamp(mix, 0, 100) / 100
speed   = clamp(speed, 1.0, 10.0)
dur     = clamp(duration, 0.1, 2.0) * 44100          # samples
window  = clamp(window,   0.1, 2.0) * 44100          # samples - the spin-up window
preroll = max(preroll, 0.0) * 44100                  # samples - NO upper clamp, unlike the others
```

State is a **running absolute sample position** at `this+0x214`, incremented by the block length every call — the note-relative playhead, not reset per block the way plain Tape Stop's `written` is. Two phases, gated on that position `pos`:

* **`pos < min(preroll, dur)`**: the effect has not started; dry passes through (an implicit dry pass, consistent with the shared `prepare` step priming the wet buffer from the dry one).
* **`min(preroll, dur) <= pos <= preroll + window`**: the active phase. On first entry the raw dry samples are copied once into a record buffer (`this+0x40`/`this+0x41`, one-shot flag at `this+0x45`). Then per sample, with `phase` counting from 0 across `window`:
  ```
  env  = clamp( (phase/window)·(1 - floor) + floor ,  <= 1.0 )       # floor = this+0x46
  if frac < 1.0:
      phase  += 1
      frac   += (window - phase)·speed/window + 1.0                  # rate -> 0 as phase -> window
      frac    = max(frac, 1.0)
  frac -= 1.0
  idx  = (window - recordLen) + phase
  out  = m · env · record[idx] + (1-m) · dry
  ```
  The envelope **ramps up** from `floor` toward `1.0` while the rate term advances the read head more often as `phase` grows: `window` is a **spin-up**, the sound easing in quiet and slow and arriving at full level and speed as the window ends.
* **`pos > preroll + window`**: plain `(1-m)·dry`.

Two things not obvious from the formula:

* **The record buffer is filled from the track, not the note.** The snapshot is up to `window` long and routinely runs past the note's end, so a renderer holding only the note's slice clamps on its last sample and emits a DC buzz. `fx_tapestop_ex` takes `lookahead=(fullL, fullR, offset)` for this; without it three charts scored −6 to −24 dB.
* **It fires far less often than it appears.** A note shorter than its own preroll produces nothing. Only 27 reference-matched charts contain a note reaching the active branch, with firing spans of 0.14–2.7 s. `1954_treajourney_chubay` has ten id-10 notes and fires on none of them. Score on note spans and the effect looks inert; score on firing spans and it is worth several dB.

Measured over the 13 capture-matched charts that fire (499 frames, firing spans only): implementing it at all buys **+2.2 dB**, 12 of 13 charts improve and none gets worse.

**The envelope floor is fitted, not transcribed.** Nothing was traced to whatever writes `this+0x46`. A sweep establishes only that it sits well above silence — 0.0 costs 1.3 dB against anything else — but between 0.4 and 0.75 the spread is 0.08 dB with per-chart curves pointing in opposite directions, and even `floor = 1.0` (no volume envelope at all, only the rate ramp) is 0.19 dB behind. 0.5 ships as the middle of a flat region. `--tapestop-ex-floor` isolates it; the metric cannot constrain it further. A secondary phase-tracking field at `this+0x224` is also untraced.

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

Multi-pass modulated delay over the dry ring buffer, with a quadrature LFO on the right channel:

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

An LFO sweeping one of the three biquads. Params `mix, filterType, waveType, freqA, freqB, rate, Q`.

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

**C6 is a rate in cycles per beat, not a period** — the one place a period field is inverted. The wrapper takes its **reciprocal** before scaling by the beat (`fVar19 = 1.0 / field[5]` at `0x180632aa0`, then `fVar19 * (60.0 / BPM)` at `0x180632ab6`):

```
periodSec = (60 / BPM) / C6
```

So `6, 0, 3, 80.00, 500.00, 18000.00, 4.00, 1.40` = LPF, log-triangle, 80 % wet, 500↔18000 Hz, **4 wobbles per beat**, Q = 1.4 — not a 4-beat sweep. Reading it as a period runs that ubiquitous row 16× too slow: measured, the correct reading improves 13/13 capture-matched charts, mean exclusive gain +0.077 → +0.955 dB over 3247 frames. `--wobble-legacy-period` restores the old reading.

The effect's LFO counter is an object member that runs continuously across notes. `apply_chart.py` threads it (`this+0x238`, written back every block); `--no-persist` restores per-note restarts. BitCrusher's sample-and-hold position and Gate's step counter are almost certainly members too, but were not traced and are not threaded — both score well (+2.3 / +3.2) so there is no measured pressure to change them.

### 4.10 Pitch Shift — `0x1806429b0`

**SOLA splice + sinc resample, not a grain-respacing shifter.** The 631-line decompilation is heavily auto-vectorized, which hides an ordinary three-stage algorithm. The real signature takes **five** arguments — `(this, blockLen, blockOffsetFrames, mix, amount)` — with `amount` arriving on the stack at `[rsp+0x160]`; Ghidra types the function as four params and drops it, which is why an earlier reading of this section could not see where the shift ratio came from.

**Parameter conditioning** (`0x180642a2a`–`0x180642a9c`), none of which the chart's column range advertises:

```
mix    = (mix >= 0 ? min(mix, 100) : 0) * 0.01
amount: if (amount >= -12) { a = min(amount, 12); if (a < 0) a = min(a, -1); }
        else                 a = -12
        if (0 < a && a < 1)  a = 1
ratio  = pow(2.0, a/12)                         # double pow @ 0x180769d80
```

So the shift is clamped to **±12 semitones**, and any *nonzero* magnitude below one semitone is pushed **out** to ±1 rather than rounded toward zero. Exactly 0 survives and takes a unison passthrough branch. Both clamps are live in shipped charts: `amount = 12` occurs (sitting exactly on the limit), alongside 0, 2, 4 and 5.

**Object layout**, from the constructor `FUN_18063d5d0` @ `0x18063d5d0`. All three buffer pairs are `PS_BUFLEN` floats:

| byte offset | meaning |
|---|---|
| `0x00` | int16 interleaved source |
| `0x38` / `0x40` | dry input float L/R, filled by `FUN_18063d9e0` at the top of each call |
| `0x58` / `0x60` | output float L/R |
| `0x244` | **441** — autocorrelation window (10 ms @ 44100) |
| `0x248` | output-accumulator cursor; the only state persisting across calls |
| `0x24c` | **17640** — input buffer length (400 ms) |
| `0x250` / `0x258` | grain buffer L/R |
| `0x260` | 17640 — input load count |
| `0x268` / `0x270` | input window float L/R |
| `0x278` | 17640 — accumulator capacity |
| `0x280` / `0x288` | output accumulator L/R |

**Stage 1 — pitch period by autocorrelation.** Each pass reloads the whole 17640-frame input window from the running source cursor, then correlates **441 samples of the left channel only** against itself at every lag from **132 to 882 samples** (`0x84 .. 0x372`, i.e. 50–334 Hz), keeping a running max in a `double`. The winning lag is applied to both channels. Ties keep the **earlier** lag — the update is on a strict increase (`if (dVar53 <= dVar55) keep old`), so a flat or silent window resolves to 132, not to the last lag tried.

The int16 loader has a quirk worth reproducing: wherever the **left** sample is exactly 0 it writes 0 to *both* channels and never reads the right one (`0x180642b43`). `FUN_18063d9e0` does the same, so it is a loader convention rather than something specific to this effect.

**Stage 2 — assemble one grain (SOLA splice).** A triangular crossfade over `lag` samples between the window and itself one `lag` later, then a plain copy tail:

```
grain[j]     = ((lag-j)/lag)·in[c+j] + (j/lag)·in[c+lag+j]      j in [0, lag)
grain[lag..] = in[c+lag..]                                       bounded by the 17640 limit
hop = int(lag / (1/ratio - 1) + 0.5)   if ratio < 1     # == lag·ratio/(1-ratio)
    = int(lag / (ratio - 1) + 0.5)     if ratio > 1
```

This is the step that changes **duration** without a discontinuity. It is *not* what shifts the pitch.

**Stage 3 — resample the grain through a 25-tap windowed sinc**, accumulating into `0x280`/`0x288`:

```
for i in [0, count):                       # count = hop+lag (down) / hop (up)
    c = int(i·ratio)                       # truncation, cvttss2si
    for k in [c-12, c+12]:
        if k < 0: skip
        x = (i·ratio − k) · π
        w = (x == 0) ? 1.0 : sinf(x) / x
        acc[cursor + i] += w · grain[k]
```

**This runs on both shift directions** — `0x180643337` on the up branch, `0x180643a73` on the down branch, byte-identical loops. It is what actually moves the pitch; the direction-specific code before it only assembles the grain and picks the hop. (An earlier reading of this section had the up branch doing "no resample, a straight sample copy", with pitch rising because grains were spaced closer together. That mistook the stage-2 grain copy for the output stage; both are present, and only stage 3 touches pitch.)

**Stage 4 — mix.** Once the accumulator holds a full block: `out = (1-mix)·dry + mix·acc`, a **plain dry/wet mix** against the `0x38`/`0x40` buffers that `FUN_18063d9e0` filled at the top of *this same call*. No history and no crossfade against previous output are involved. The accumulator is then consumed, `memmove`d down by the block length and zero-filled behind.

**Implemented** in `sdvx_fx.fx_pitchshift` (`.vox` id 9, `--no-pitchshift` restores the old do-nothing behaviour). Measured over the 8 capture-matched charts that carry scorable Pitch Shift regions: **+0.983 → +1.929 dB exclusive mean, delta +0.946 (+1.057 frame-weighted), 7 charts improved / 0 regressed**, with every other effect flat to within 0.002 dB. Earlier claims that "no chart in the reference corpus isolates Pitch Shift long enough to score it" were an artifact of the small corpus of the time — the current reference set carries 61 FX-button Pitch Shift notes across 12 capture-matched charts, the longest 2.82 s.

**One reading was settled by measurement rather than by disassembly.** The pass tail at `0x180643472` (`lea esi, [rsi + r12*2]`) advances the source cursor, and `r12` at that point holds a running *total* of hops rather than the current pass's hop — read literally, the input read position accelerates through a held note. That is what the register dataflow appears to say, but it renders badly (`-0.815` dB against the per-pass hop over the same 8 charts, and a +12 semitone shift collapses to near-silence because the cursor outruns the note). The per-pass hop is therefore the default; `--pitchshift-legacy-cursor` reproduces the accelerating reading. The likeliest explanation is a misattribution of which spilled stack slot `r12` is reloaded from across the vectorized tail, not an engine bug — but that has not been proven instruction-by-instruction, so it stays flagged here.

The independent reimplementation of §9 also renders this effect, but not by reimplementing the engine's algorithm — it shells out to a generic pitch-shift library (`librosa` by default, optionally `pyrubberband`/Rubber Band). That is a different kind of approximation, not a second trace of the same DSP, so it neither corroborates nor contradicts anything above and does not appear in §9's agreement/disagreement tables.

---

## 5. Chart → DSP parameter conversion

Wrappers convert chart values using the BPM at the effect's start (`60/BPM` from the constant `0x18092e700`). Verified per effect by disassembling each call site:

| effect | chart field | conversion | proven at |
|---|---|---|---|
| Retrigger / Echo | `length` | **beats** → `sec = beats · 60/BPM` | `0x180631198`, args at `0x180631271` |
| Gate | `period` | **beats** → `sec = beats · 60/BPM` | `0x180631bb2`–`0x180631bbb` |
| Side Chain | `period` | **beats** → `sec = beats · 60/BPM` | `0x180632552` + tail |
| Wobble | `rate` | **cycles per beat** → `sec = (60/BPM) / rate` — **reciprocal** | `0x180632aa0`, `0x180632ab6` |
| Flanger | `period` | **measures** → `rate = measures / secPerMeasure` | `0x180631f6b`–`0x180631f8d` |
| Tape Stop (id 4) | `duration` | already **seconds**, passed through | inline case 7 |
| Tape Stop **Ex** (id 10) | `duration`, `preroll`, `window` | **beats** → `sec = beats · 60/BPM`, all three | `0x180632170`–`0x18063218a` |
| Bit Crusher | `rate` | raw sample count, passed through | `0x180630d10` |
| LPF / HPF | `freqLo/Hi` | Hz, plus the knob exponent of §4.2 | `0x180630110` |

`FUN_18062e2e0` is the time-signature lookup (returns the beat numerator active at a position); the flanger uses it to build `secPerMeasure`.

Laser note → effect index is `noteField[4] - 1` (`FUN_18062ea60` at `0x18062ea7c`), where `-1`/absent means no laser effect. FX-button note → definition index is `noteField[4] - 2` (`FUN_18062e3d0` at `0x18062e3f0`).

### 5.1 Laser event grouping, and what a slam actually is

A laser event is one 20-byte struct per *adjacent point pair*: `{startSample, endSample, startKnob, endKnob, effectIndex}`. `FUN_18062ef70` groups events into **runs** contiguous in time **and sharing the same effect index**; a run is what the wrapper receives as `param_3`. The wrapper bails out unless the run is at least one audio block long:

```
FUN_18062ea60 @ 18062ea7c :  if (gen->blockSize <= (lastEnd - firstStart)) { ...dispatch... }
```

A **laser slam** (two chart points on the same tick) is therefore *not* an effect of its own — it is a zero-duration event contributing a **step discontinuity in the knob curve** of the run it sits inside. The audible slam is the filter cutoff jumping, in one block, across the whole `freqLo … freqHi` range: measured on `2229_kamui` at 50.571 s, where the knob slams 127 → 0 on an HPF (40–2000 Hz, Q 3), the 60–400 Hz band jumps by 28× within 100 ms.

Two consequences for any reimplementation:

* build the knob curve from the events and **leave it stepped** at slams — do not smooth or resample it, and do not treat a laser section as having one constant filter;
* **split a run wherever the per-point effect index changes**, because charts routinely change filter mid-section. Collapsing a section to a single filter applies the wrong filter *and* misplaces the slam — on `2229_kamui` alone that error covered 18 s of audio.

Isolated slams (a run shorter than one block) genuinely produce nothing in this engine.

### 5.2 Retrigger's phase is locked to the musical grid, not to the note

Retrigger's repeat cycle runs on the song's grid, so a note beginning mid-cycle **joins it partway through** — the effect can open by replaying audio from *before* the note. No other effect does this.

**Scope, established by xref.** `FUN_18062e310` has exactly three call sites in the DLL: `0x18056e30d` (an unrelated subsystem), `0x1806344ed`, and `0x1806310e5` — only the last is inside an FX wrapper, namely Retrigger's `0x180630fa0`. The Echo/RetriggerEx wrapper at `0x180631390` reaches the shared DSP at `0x1806316a7` with no snap call, and neither does any other wrapper. **Echo is note-locked; Retrigger is grid-locked**, despite sharing DSP `0x18063ffb0`.

Arguments are `(gen, notePos, lengthBeats /*xmm2*/, secPerBeat /*xmm3*/)`. It walks the BPM list at `gen+0x28` and the time-signature list at `gen+0x30`, taking the last entry of each at or before `notePos`:

```
samplesPerBeat    = trunc(2646000 / BPM)              # 0x18092e970 = 2646000.0 = 44100*60
samplesPerMeasure = samplesPerBeat * timeSigNumerator # imul ecx, r11d - the raw numerator
period            = trunc(samplesPerBeat * lengthBeats)
anchor            = max(lastBpmChangePos, lastTimeSigChangePos)   # cmovle at 0x18062e387
offset            = ((notePos - anchor) % samplesPerMeasure) % period
if offset > period - 512:  offset = 0                 # 0x18092e884 = 512.0
return offset
```

Two details worth keeping: the grid is anchored at the **later of the last BPM and time-signature change**, not the start of the song, so a mid-song tempo change re-bases it; and the 512-sample tolerance snaps *forward* to the next boundary when a note is nearly on one, so a note missing by a hair is not pushed back a whole period.

The wrapper then does `snappedStart = notePos - offset` (`0x1806310ea`), so `offset` is how far into its own cycle the effect already is when the note begins. Worked example: a 2-beat Retrigger at 210 BPM has `samplesPerBeat` = 12600 and `period` = 25200; a note starting one beat in gets `offset` = 12600, so with `count` = 16 (slices of 1575 samples) it opens at slice 8, replaying audio from a beat before the note.

`apply_chart.py` computes this in `grid_snap_offset`, feeds the DSP the region starting `offset` samples before the note, and discards that pre-roll from the result. `--no-grid-snap` restores note-locked behaviour. **Measured**: over the 14 best-aligned capture-matched charts with off-grid Retrigger notes, snapping wins on 14/14, mean +0.882 dB on Retrigger's exclusive frames, smallest margin +0.210.

One caveat this exposed: the engine tracks positions in **integer samples** with a truncating `samplesPerBeat`, while `Timeline.samples()` converts through float seconds. On charts whose BPM does not divide 2646000 evenly the two drift, and `grid_snap_offset` returns a few tens of samples where it should return zero. Inaudible, but wrong wherever position arithmetic is compared; the fix is an integer-sample clock in `Timeline`.

### 5.3 `#BEAT RESOLUTION` — cells per beat is per-chart

A `.vox` position is `measure,beat,cell`, and **how many cells make a beat is a property of the chart**, declared by the optional `#BEAT RESOLUTION` tag:

```
#BEAT RESOLUTION   charts (of 8107)
48 (tag absent)    8088
144                   1
240                  10
480                   8
```

Only 19 charts, but on those a renderer assuming 48 gets **every time in the chart wrong by the ratio** — 10× on a 480 chart. Note starts, lengths, BPM boundaries and laser times all scale together, so every effect starts at the wrong moment and runs an order of magnitude too long.

Through the metric this does not look like a timing bug: it looks like *every DSP failing at once on a few charts*. `1972_guinevere_penoreri` scored −6 to −10 dB on Echo, Flanger, Gate, SideChain and HPF alike, with its capture aligning fine (corr 0.607). A chart that is uniformly bad while its alignment is good points at a chart-global input, not at the DSPs — listen to it rather than excluding it as an outlier.

`scripts/shared/vox.py` has always read the tag correctly; `Timeline` now takes the resolution from the chart, with `res=` as an override.

---

## 6. Reference implementation

`sdvx_fx.py` implements §4.1–4.9 against 16-bit WAV files, in the same ±32768 float domain and with the same clamps and block structure as the DLL. Requires `numpy` (optionally `scipy` for faster IIR) and `ffmpeg` for `.s3v` decoding.

```bash
python scripts/audio/sdvx_fx.py in.wav out.wav --effect retrigger --params 95,2.0,1.0,4,0.85,0.15
python scripts/audio/sdvx_fx.py in.wav out.wav --effect laser_lpf --params 90,400,18000,0.7 --knob 0:0,4:127
python scripts/audio/sdvx_fx.py in.wav out.wav --effect wobble --params 80,0,3,500,18000,4.0,1.4 --range 8:16
python scripts/audio/sdvx_fx.py --list
```

`apply_chart.py` drives it from a real chart: it parses the `.vox`, decodes the `.s3v` (plain ASF/WMA — ffmpeg handles it), and applies every FX-button hold and laser segment at the chart's times, plus the parts of the chain outside the effect generator — the device ParamEq and its music duck (§7.1) and the layered SE (§6.1).

```bash
python scripts/audio/apply_chart.py data/music/2229_kamui_tjhangneil -d 5m -o kamui_fx.ogg
```

Output defaults to Vorbis `.ogg` and the `-o` extension picks the container. The engine's own int16 writeback (§2) always happens first, so a lossy container is applied *on top of* the game's output stage — but pass a `.wav` name for the metric of §7, whose numbers were all measured on PCM.

Diagnostic flags, each isolating one modelling decision:

```
the device ParamEq (7.1)
  --no-peak        skip it entirely
  --peak-delay S   knob lag before it reaches the EQ (default 0.08, the engine's value)
  --peak-always    run it during every laser, not only C4 = 0 ones
  --peak-post-se   put it after the SE mix instead of before
  --no-duck        skip the music-voice duck; --duck-rate sets its ramp (default 0.33/s)
  --duck-hold      freeze the duck target between lasers (rejected, see 6.1.4)
  --peak-gain-scale  multiplies the EQ's resonant gain (default 0.8 - NOT the engine's
                     1.0; see the deviation note at the end of 7.1)
  --peak-max-gain    hard ceiling in dB on that gain, applied after the scale above
                     (default 8 - NOT the engine's unclamped up-to-+15 dB)

the layered SE (6.1)
  --no-se          skip them
  --slam-index N   which virtical_shot sample a slam plays (0 or 1)
  --se-polyphonic  let overlapping slams sum instead of restarting one voice
  --se-trim X      multiplier on the header-derived SE gains (default 1.2; the
                   unexplained ~2 dB of 6.1.4 lives here)
  --slam-gain X    override the slam level outright, bypassing header and trim
  --se-gain X      the same for FX chip samples

effect behaviour
  --laser-mode M   chain | dry | add - how a laser combines with an FX hold (8.1)
  --no-grid-snap   start Retrigger at the note instead of the grid boundary (5.2)
  --no-persist     restart each effect's counter per note instead of resuming (4.9)
  --no-auto-tab    skip #TRACK AUTO TAB spans (6.3)
  --no-param-assign-sweep   run borrowed effects at authored parameters (6.3)
  --no-tapestop-ex leave Tape Stop Ex notes dry (4.6b)
  --tapestop-ex-floor X     Tape Stop Ex envelope floor, the one fitted value (4.6b)
  --tapestop-ex-3phase      the alternative phase model (9.5)
  --wobble-legacy-period    read Wobble's C6 as a period, not a rate (4.9)
  --mix-scale X    scale every effect's wet/dry mix parameter
  --no-stage-clip  keep float precision between stages instead of int16 (8.1)

output
  -b, --block N    per-block coefficient/LFO update size (default 512)
  --master-gain X  gain before the hard clip (6.2)
  --dry PATH       also write the untouched decode
```

Track layout in `.vox`: `#TRACK1` = VOL-L, `#TRACK2` = **FX-L**, `#TRACK3..6` = BT-A..D, `#TRACK7` = **FX-R**, `#TRACK8` = VOL-R.

```
FX    C0 timing   C1 length(cells, 0=chip)   C2 chip:sample / hold:effect+2   C3 cells-per-chain
laser C0 timing   C1 position (v10 0..127, v12 0.0..1.0)   C2 node type (0 mid/1 start/2 end)
      C3 roll type   C4 LASER EFFECT   C5 range (1/2 wide)   C6 unused
      C7 curve type  C8 roll length    C9 cells-per-chain
```

**C4 is the laser effect, not C7** — C7 is the curve type, and both range 0..5 in practice. Using C7 puts the wrong filters at the wrong times across a whole chart. Cell resolution is 48 per 1/4 note **unless the chart says otherwise** (§5.3); do not hardcode it.

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

All modified regions line up with the chart's own note times. FX **chip** notes produce no *track effect* — they have zero length and every wrapper requires at least one full block — but they do trigger a layered sample (§6.1).

### 6.1 The layered SE bank — laser slams and FX chip notes

Not everything you hear is the effect engine. Two gameplay events mix a **sample** on top of the track, from `data/sound/ver5/general_sampler.s3p` (bank id **9**, registered by the loader at `0x1805c5960`; `sys_sd_shotfx.2dx` is bank 4 with the same 15 names).

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

Index 0 is the only entry with a slow attack, consistent with it being a swell rather than a click.

**Which chip sample plays** comes from the FX note's C2 — the same column that means "effect definition + 2" on a *hold*. On a chip it is a `general_sampler` index directly, with `0` and `255` both meaning silence (the common case: 110 of 111 FX-L chips on `2229_kamui` carry C2 = 0, and only 3 of 228 chips on that chart are sampled at all). The 15 names are listed in [`vox_format.md`](vox_format.md) under `#TRACK2`/`#TRACK7`. There is no "default sample" concept.

### 6.1.1 The trigger code

The sound-manager voice API is `Play = FUN_1805c6ec0(this, bankId, sampleIdx, flag)` (invoking the voice's `vtable+0x10`) and `SetVolume = FUN_1805c6e40(this, bankId, sampleIdx, vol)` (`vtable+0x40`, `vol * 1/127`).

Both gameplay triggers live in the event dispatcher `FUN_180407200`. Ghidra types its switch selector as `float`, so the case labels render as tiny denormals — they are int bit patterns (`2.8026e-45` = 2, `4.2039e-45` = 3, …).

**FX chip note** — case 4:

```c
if ((0 < (int)idx) && (idx != 255)) {
    snd = FUN_1800967c0();
    FUN_1805c6ec0(snd, 9, idx);        // bank 9 = ver5/general_sampler
}
```

Same function, case 3, also carries the laser mirroring (`if (field == 2) v = 1.0f - v;`), independently confirming §7.1.

**Laser slam** — a two-stage path. Event **kind 6** (`0x18040773a`, variant tag 5) is a *scheduled play* request; the dispatcher converts it to a queue entry at `gameAudio+0x80`:

```c
entry.index = event.a;                                     // event+0x08, verbatim
entry.due   = now - (long long)((event.time - audioPos) * 1000.0f);   // ms clock
```

and drains that queue later in the same call, once `entry.due < now`:

```c
FUN_1805c6ec0(snd, 0xd, entry.index, 0);   // bank 0xd = ver5/virtical_shot
```

So the slam is **not** played out of `general_sampler`. Bank `0xd` is `/data/sound/ver5/virtical_shot.s3p`, a two-entry bank whose payloads are the same size as `general_sampler`'s first two (58804 / 148132 bytes) — same audio, separate bank.

**The sample index is carried by the event, not computed at play time**: `event+0x08` goes straight into the queue and into `Play`. The `fs00` / `fs01` choice is therefore made by whatever builds the kind-6 events, upstream of `Game::GameAudio`, and **that producer was never found** — the event vector arrives as `Update`'s second argument, and neither field-store scans nor vtable xref-chasing reached its builder. `FUN_18041c220` constructs the object at `world+0xb8`, if that helps. Every measured chart uses index 0. (`apply_chart.py` uses `general_sampler[0]`, byte-identical to `virtical_shot[0]`; `--slam-index 1` selects the other.)

The full bank table, from `FUN_1805c5960`:

```
0 sys_sd_credit.2dx   1 sys_sd_sram.2dx    2 <the song's own .s3v, loaded per song>
3 sys_sd.2dx          4 sys_sd_shotfx.2dx  6 00_title_bgm_06   7 sys_sd_virtical.2dx
8 ver6/bgm_00         9 ver5/general_sampler   0xd ver5/virtical_shot
0xe voice_mitsuru_00  0xf voice_tama_00     0x10 hexa    0xa..0xc,0x11..0x18 ver6/se_*
```

### 6.1.2 No level travels through the play path

Every `Play` for a sampled SE passes a flag of zero, never a level:

```
FX chip   0x18040752a:  xor r9d, r9d ; mov r8d, [rdi-4] ; lea edx, [r9+9]  ; call Play
slam      0x1804080e4:  xor r9d, r9d ; mov r8d, [rcx]   ; lea edx, [r9+0xd]; call Play
```

`Play` forwards to the voice's `vtable+0x10` (`0x1806a1cc0`), which only prepares and starts — it takes no gain. The voice was initialised at unity (`VoiceImpl` ctor `0x1806a183a`: `volume = 1.0f`, `pan = 0.0f`, ramp target `1.0f`), and none of the DLL's 19 `SetVolume` call sites names bank 9 or `0xd`. The level arrives by a different route entirely, once per sample at bank-load time (§6.1.4); `voice+0x70` stays at unity for the whole track.

For completeness, `voice+0x70`'s neighbourhood: `FUN_1806a3640(voice, bit, value)` writes one of **8 independent gain factors** and rebuilds a 256-entry lookup table at `voice+0x6c`, indexed by an active-factor bitmask.

```
bit 0 -> [+0x70]   bit 1 -> [+0x74]   bit 2 -> [+0x7c]   bit 3 -> [+0x8c]
bit 4 -> [+0xac]   bit 5 -> [+0xec]   bit 6 -> [+0x16c]  bit 7 -> [+0x26c]
entry[mask] = product of the factors whose bits are set   (entry[0] = 1.0)
```

The remaining seven factors are set through virtual dispatch and were not traced. None of them is where the SE level lives.

The loudness differences between hit sounds are partly baked into the samples themselves:

| idx | name | dur | peak | peak dBFS | loudest 300 ms RMS |
|---|---|---|---|---|---|
| 0 | `fs00_virtical_se01` (slam) | 1.78 s | 17446 | −5.5 | 5341 |
| 1 | `fs01_virtical_se02` | 3.03 s | 10386 | −10.0 | 4002 |
| 2 | `fs02_shot01` | 1.73 s | 28765 | −1.1 | 9256 |
| 3 | `fs03_shot02` | 0.78 s | 32767 | −0.0 | 8179 |
| 9 | `fs09_shot08` | 2.90 s | 32768 | 0.0 | **11057** |
| 10 | `fs10_shot09` | 1.31 s | 32768 | 0.0 | 9682 |
| 14 | `fs14_shot13` | 6.10 s | 23029 | −3.1 | 4307 |

The chips are mastered hot — several at digital full scale — while the slam sits 5.5 dB lower with a 228 ms swell. That spread is authentic; do not flatten it. On top of it, each sample carries an authored gain in its own header (§6.1.4).

### 6.1.3 One voice per sample — SE do not layer

`Play` resolves the bank and index to a **single, persistent voice object**:

```c
voices = FUN_1805c5830(bank);                  // vector<shared_ptr<Voice>>, 16 bytes/entry
voice  = voices[index];
voice->vtable[0x10](flag);                     // Start on THAT voice
```

One voice per `(bank, sampleIndex)` pair, allocated at bank load. Re-triggering a sample that is still sounding **restarts that voice**; it does not allocate a second one and let the two sum.

This matters because the slam sample runs 1.78 s while slams come far faster — on `2229_kamui` MXM the median gap between slams is 0.429 s, and at some onsets ten copies would still be sounding if they accumulated:

```
138 slam points -> 124 distinct onsets   (14 are VOL-L and VOL-R slamming on the same tick,
                                          which is still one Play into one voice)
inter-slam gap   min 0.000 s   median 0.429 s   max 13.286 s
overlapping copies alive at an onset, if layered:  1..10
```

So coincident slams are one sound, not two, and close slams truncate the previous one — letting tails sum makes the SE layer's level track slam *density*. Measured: layering scores 1.889, one-voice restart **1.858**. `apply_chart.py` restarts by default and truncates each slam at the next onset; `--se-polyphonic` restores additive behaviour.

### 6.1.4 The per-sample gain is in the `S3V0` header, not in the DLL

Each entry of an `.s3p` bank (and each standalone `.s3v`) begins with a 32-byte header:

```
+0x00  'S3V0'
+0x04  u32   header size (always 0x20; the WMA/ASF payload starts here)
+0x08  u32   payload size
+0x0c  u32   checksum
+0x10  u32   (0 for every gameplay sample)
+0x14  i16   gain,  8.8 fixed-point decibels        <-- the level
+0x16  i16   gain trim, same units (0 for every gameplay sample)
+0x18  u32   (0)
+0x1c  i16   pan, /32768                            (0 for every gameplay sample)
```

The bank loader (`0x1805ce7b0`, `'S3V0'` check at `0x1805ce834`) does, per sample:

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

that is,

```
gain = 10 ^ ( ( (i16)hdr[0x14] + (i16)hdr[0x16] ) / 256 / 20 )
```

`0.00390625` is 1/256 (the 8.8 fixed point) and `0.05` is 1/20 — a decibel-to-amplitude conversion. Values in the files are dominated by multiples of `0x80`, i.e. authored in 0.5 dB steps, which settles the fixed-point reading.

The target is **not** `voice+0x70`. `VoiceImpl::vtable+0xd0` (`0x1806a2fc0`) is `return this->connections[i]`, and `MixerConnectionImpl::vtable+0x20` (`0x1802fbf40`) is one instruction, `movss [conn+0x20], xmm1`. The connection is created with a gain of `1.0` and the header value overwrites it immediately — one connection per voice, set once, never touched again, which is why xref hunts through `Play` and `SetVolume` found nothing. The standalone `.s3v` loader (`0x1805cf8c8`) does the same arithmetic, so the song's own track goes through it too.

Measured out of the shipped files:

| bank | sample | `hdr+0x14` | dB | linear |
|---|---|---|---|---|
| `0xd` `virtical_shot` | 0 `fs00_virtical_se01` (**the slam**) | −1324 | −5.172 | **0.5513** |
| `0xd` `virtical_shot` | 1 `fs01_virtical_se02` | −2072 | −8.094 | 0.3938 |
| `9` `general_sampler` | 0, 1 | −1324 | −5.172 | 0.5513 |
| `9` `general_sampler` | 2..13 `fs02_shot01`..`fs13_shot12` (**FX chips**) | −3328 | −13.000 | **0.2239** |
| `9` `general_sampler` | 14 `fs14_shot13` | 0 | 0.000 | 1.0000 |
| `2` | `2229_kamui_tjhangneil.s3v` (**the music**) | 0 | 0.000 | 1.0000 |

The chips are **7.83 dB below the slam** — the engine does distinguish them, in the data rather than the code — and the music is at unity, so these numbers are directly the SE-to-music ratio. `virtical_shot[1]` and `general_sampler[1]` are byte-identical audio with *different* header gains, which rules out the field being derived from the payload: it is authored per bank instance.

**It does not fully agree with the capture.** Sweeping the slam gain with the chips pinned at 0.2239:

```
slam gain   0.40   0.45   0.50   0.5513   0.60   0.65   0.70   0.78
score       1.943  1.897  1.858  1.826    1.807  1.797  1.797  1.816
```

The optimum is ~0.69, **about 2 dB above** the header, and it is not a metric artefact: restricting scoring to the 1187 frames a slam is sounding in, with the level offset taken from frames far from any slam, gives the same answer. Chips remain unmeasurable on this chart, so 0.2239 is neither confirmed nor contradicted.

Ruled out for the missing 2 dB: a per-bank level (`FUN_1805c63b0` takes no gain, and the registration table passes only ids and paths); the duck resting below unity (`0x1805c7b3d` really does load `1.0` when the knob is under 4); freezing the duck between lasers (`--duck-hold` costs 0.34 overall); additive layering (`--se-polyphonic`, worse at any gain); another module owning the mixer (`S3P0`/`S3V0`/`2DX9` appear in `soundvoltex.dll` and no other DLL in `modules/`).

Since the metric only sees the SE:music *ratio*, a constant ×0.8 on the music path would explain it exactly. **Where to look:** the music voice is bank 2, loaded through the standalone `.s3v` loader at `0x1805cf8c8`, which has a second `powf` result at `[rsp+0x60]` whose consumer was never traced; the `.s3p` loader has the same loose end, appending the gain into a `std::vector<float>` (`0x1805ced2c`) that is never seen read.

`load_s3p` returns each sample's header gain and every SE is mixed at `header_gain * --se-trim`. The trim carries the unexplained 2 dB and nothing else — `--se-trim 1.0` plays what the files literally say — while `--slam-gain`/`--se-gain` bypass both. Keeping the derived *ratio* untouched and the one fitted number behind one flag is deliberate.

### 6.2 Output stage — `CGainWithHardLimiter`

`BMSoundLib2017::CGainWithHardLimiter::Process` (`0x18069f090`, vftable `0x180925df8`) is, in full:

```
gain  = this->0x18 (float)          set by 0x1802f8120
limit = this->0x1c (float)          set by 0x1802fbf30   (both at once: 0x1802ffe90)
for each sample (SSE, 4 at a time):
    x = x * gain
    x = min(max(x, -limit), +limit)
```

Despite the name there is no knee, no lookahead and no release — a gain followed by a hard clip. The shipped game clips its own output, so mixing SE hot enough to occasionally clip is authentic; picking a level low enough never to clip makes slams inaudible. `--master-gain` exposes the same stage.

### 6.3 `#TRACK AUTO TAB` and `#TAB PARAM ASSIGN INFO`

`#TRACK AUTO TAB` lets a laser span run an effect pair borrowed from `#FXBUTTON EFFECT INFO`; `#TAB PARAM ASSIGN INFO` optionally attaches "laser position drives this pair's Nth parameter between these bounds" to that same pair. Both are applied by `apply_chart.py` by default (`--no-auto-tab`, `--no-param-assign-sweep`), worth **+1.07 dB** and **+0.698 dB** respectively.

Corpus-wide usage across all 8107 charts:

```
#TRACK AUTO TAB          non-empty in 2738 charts (33.8 %)
#TAB PARAM ASSIGN INFO   present (24 rows) in every chart, but only 431 charts (5.3 %) have any
                         row whose param-index/bounds columns (C1-C3) are actually nonzero
#TRACK ORIGINAL L/R      non-empty in 2488 charts (30.7 %)
```

Layout, from `voxread.c`'s section table:

```
#TAB PARAM ASSIGN INFO, one row per #FXBUTTON EFFECT INFO slot (24 rows = 12 pairs x 2, always present):
  C0  effect-pair index, 0-indexed (0..11) - a positional counter, never anything but
      0,0,1,1,2,2,...,11,11 in any shipped chart
  C1  index of the pair's own parameter to modulate (0 = none configured)
  C2/C3  the bounds that parameter is swept between

#TRACK AUTO TAB rows (tabsep, same shape as an FX-button hold):
  C0 timing   C1 length (cells)   C2 effect index, **2-INDEXED** - pair = C2 - 2
```

**The two sections use different index bases**, which is the easy mistake here. Two corpus checks settle AUTO TAB's: across the 2128 AUTO TAB rows in charts that also carry modulation, C2 spans **2..13** — twelve consecutive values for twelve pairs, where a 0-indexed reading cannot place 12 or 13 — and read as 2-indexed a span lands on a modulated pair **40.7 %** of the time versus **13.1 %** (about chance) read as 0-indexed.

The sweep itself is `value = C2 + (C3 - C2) · clamp(laserValue, 0, 1)`, refreshed every 512 samples, with `param1`/`param2` selected by chain position, and the control source is a **C4 = 6 laser** — which is why C4 = 6 is not inert. That formula came from an independent reimplementation (§9) and was then confirmed by measurement here.

Worked example: `0002_broken_iroha`'s single AUTO TAB row `021,03,00  96  8` selects pair `8-2` = **6**, which is exactly the pair its one nonzero assign row modulates (`6, 3, 3.00, 0.50` — param 3 of a Flanger, its period, swept 3.00 → 0.50 measures). The laser borrows a Flanger and sweeps its rate as the knob moves. About 59 % of AUTO TAB spans land on an unmodulated pair, which is the "run it at its authored parameters" case.

**`#TRACK ORIGINAL L`/`#TRACK ORIGINAL R` do not matter for audio.** They carry only the un-interpolated control points of a curved laser, where `#TRACK1`/`#TRACK8` already carry the fully-interpolated sequence the game plays. Recommend closing this without implementation work unless a counter-example turns up.

---

## 7. Calibration against a cabinet capture

`scripts/audio/reference/kamui_goal.ogg` is a recording of the actual cabinet playing `2229_kamui_tjhangneil`. It is **not** a clean render — polarity-inverted, Ogg-coded, and its clock drifts against the game's audio by +0.346 samples/second (7.9 ppm), i.e. +45 samples over the track. Sample-exact diffing is therefore impossible: coherent averaging over 124 slams gave correlations ≤ 0.06.

What works is a **phase-insensitive spectral metric**: 46 log-spaced bands per 46 ms frame, level-normalised, mean |dB| difference (`metric.py`). The floor is codec noise — on frames where the chart does nothing, an untouched track already scores 1.22. `xcheck.py` generalises this to any chart/capture pair with automatic alignment, and `masscheck.py` aggregates it across the reference corpus.

| render | all | FX | peak-laser | tab-laser | idle |
|---|---|---|---|---|---|
| untouched track | 3.169 | 4.808 | 4.247 | 5.557 | 1.221 |
| effects only, no SE | 2.934 | | | | |
| + layered SE | 2.380 | | | | |
| + peak filter, *fitted* (old) | 2.310 | 3.123 | 3.011 | 2.788 | 1.137 |
| effects + peak, no SE | 2.500 | | | | |
| + peak filter, transcribed (§7.1) | 1.924 | 2.583 | 2.127 | 2.698 | 1.362 |
| **+ one voice per SE sample (§6.1.3)** | **1.799** | 2.520 | 1.929 | 2.320 | 1.327 |

The bottom row is the state at which the SE model closed; everything adopted since (the Wobble rate fix §4.9, Tape Stop Ex §4.6b, the param-assign sweep §6.3) leaves kamui at **1.808**, which is the current standing against an untouched 3.169 and a codec floor of 1.14.

The idle column worsens between the last two rows purely as a normalisation artefact: the metric matches one global level offset across the track, and the music duck lowers 62 % of it, so untouched frames sit off that common offset. Every region the chart actually touches improves.

### 7.1 The default laser filter — transcribed

Read out of the binary, not fitted. This path does not go through the SVO effect generator at all — it goes through the gameplay event dispatcher and the sound device.

`FUN_180407200` (`Game::GameAudio::Update`, vtable slot 1 @ `0x1808cb848`) walks a vector of 28-byte gameplay events:

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

`acc` is pushed with a timestamp onto a queue at `gameAudio+0x58` and popped only once the head entry is **older than 80 ms** (`comiss xmm0, 0.08` @ `0x180407f61`), so the filter lags the knob. If `disableEq`, the queue is flushed and the knob forced to 0. The popped value ×127 goes to `FUN_1805c7a00`:

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

`TABLE` is 128 floats at **`DAT_18090c050`**: a hand-drawn, piecewise-linear ramp `0, 6, 12 … 54, 100, 106 … 202, 232 … 3672, 3852 … 6912, 7400, 7700, 8000, 8400 … 10800`. Values under 80 Hz are clamped away, so the first ten entries all read as 80 Hz.

The struct is `{fCenter, fBandwidth, fGain}` — `FUN_180626b30` writes its 3rd/4th/5th float args to `[rsp+0x20/0x24/0x28]`. `fGain` is the field forced to 0 in the dead zone, which settles the ordering: a bandwidth of 0 would be out of range, a gain of 0 is exactly "EQ off".

The DMO itself is not in this binary. `CDmoSoundFxAudioProcessor<_DSFXParamEq>` (`0x180919970`) and `CDmoSoundFxDriver<IDirectSoundFXParamEq,_DSFXParamEq>` (`0x180919998`) are thin forwarders to a COM object at `this+0x10`; the sample math is Microsoft's `GUID_DSFX_STANDARD_PARAMEQ`. `sdvx_fx.peaking_coeffs_bw` models it as the RBJ peaking filter with `BW(octaves) = fBandwidth / 12` — a documented-behaviour assumption rather than a transcription, since corroborated by an independent reimplementation (§9.1).

**The same call ducks the music.** Bank 2 is the song's own `.s3v` (registered per song by `FUN_1805c63b0(this, 2, path)`, up to 6 stems); every bank-2 voice gets a target gain

```c
if (v <  4)  g = 1.0f;
if (v < 95)  g = 0.8f - (v - 4) * 0.0025274728f;  // 0.800 .. 0.570
if (v < 100) g = 0.57f;
if (v < 120) g = 0.57f + (v - 100) * 0.011500001f;
else         g = 0.8f;
```

through voice `vtable+0x60` (`0x1806a21f0`), which writes a **target**; the mixer chases it at **0.33 gain units per second** (`0x1806a25b1`). A slow, shallow duck, not a gate.

Where the EQ sits was settled by measurement: **before** the layered SE are mixed in scores 1.924, after scores 2.029. Slot 0 of the device's 7 ParamEq slots is on the music path, upstream of where the SE voices join. Three further predictions of the code are confirmed independently by the capture:

| prediction from the code | test | result |
|---|---|---|
| 80 ms queue delay | sweep `--peak-delay` | minimum at exactly 0.08 s (0.06 → 2.088, 0.08 → **1.924**, 0.10 → 2.155) |
| `event+0x10 != 0` mutes the EQ | `--peak-always` | tab-laser regions 2.787 → **3.820**; peak-laser unchanged. So that field is the C4 effect index |
| the music duck exists | `--no-duck` | 1.924 → **2.195** |

**Deliberate deviation: the CLI's default gain is tamed, not authentic.** Every number above was scored against the plain transcription, and `paramq_from_knob`'s own defaults are still `gain_scale=1.0, max_gain_db=None`. But `apply_chart.py`'s CLI defaults `--peak-gain-scale` to `0.8` and `--peak-max-gain` to `8`, so a plain run renders a *dampened* EQ. This is a product choice, not a modelling correction: the boost is authentic (an ablation against the kamui capture makes the render measurably worse without it) but unpleasant enough for chart-conversion listening that comfort won by default, with the untamed model one flag away.

**Consequence for re-measuring:** `xcheck.py`/`masscheck.py` invoke `apply_chart.py` without those flags, so a fresh corpus run scores the dampened default. Pass `--extra="--peak-gain-scale 1.0 --peak-max-gain 15"` to reproduce this section's numbers.

### 7.2 SE levels

Sweeping the layered-sample gains against the corrected baseline:

```
slam gain   0.40   0.55   0.60   0.65   0.70   0.80   1.00
score       1.943  1.827  1.807  1.797  1.798  1.825  1.940
```

**0.65** is the optimum, flat to 0.70 — and only meaningful together with the one-voice rule of §6.1.3, since while overlapping copies were allowed to sum the fit came out at 0.5 (the stacking was supplying the missing level). Sweeping the trim instead, which is the same experiment in the units the discrepancy actually lives in:

```
--se-trim   0.80   0.90   1.00   1.10   1.25   1.40
score       1.905  1.861  1.826  1.805  1.796  1.813
```

1.00 is what the files say; the minimum is 1.25, i.e. **+1.9 dB**. Whatever explains that (§6.1.4) should collapse this flag back to 1.0.

Which slam sample plays is settled for this chart: `virtical_shot[0]` scores 1.924 against `virtical_shot[1]`'s 2.366 and 2.500 for no SE at all.

---

## 8. Known gaps

* **The SE-versus-music level is derived (§6.1.4) but ~2 dB under the fit.** A constant ×0.8 on the music path would reconcile the two exactly; nothing found so far puts one there.
* **What selects `fs00_virtical_se01` vs `fs01_virtical_se02`** is authored into the kind-6 event stream, and the producer of that vector was not found (§6.1.1). Worth revisiting during the notes element: note and laser gameplay events very likely live in the same vector.
* **Pitch Shift (id 9)** — algorithm identified (PSOLA, §4.10) but not implemented.
* **Composite kind 14 (id 13)** — partly transcribed. Setup case `0xd` in `FUN_18022db60` appends one 12-byte `{i32 tick, float value}` **keyframe** per definition into a vector at `this+400`, separate from §3's parameter-vector table. At playback it is dispatched through the ordinary per-block switch (`case 0xe`), so it behaves like a normal in-place effect. Wrapper `FUN_180632c10` binary-searches that vector for the current note and builds a `std::function<float(float)>` over the two neighbouring keyframes — constant if their values match within `FLT_EPSILON`, linear otherwise. **What the interpolated value drives was never reached.** Chart ranges for further probing: `p1 ∈ [0,100]` (mix), `p2 ∈ [-24,24]`, `p3 ∈ {0, 0.5, 1, 2}`, 316 occurrences. An independent reimplementation types it `PITCH_SHIFT_EX` with fields `(mix, semitones, ex_param)`, which matches `p2`-as-semitones and makes an animated pitch bend the leading guess.
* **Tape Stop Ex's envelope floor** (`this+0x46`) and its phase-tracking field (`this+0x224`) are untraced; the metric cannot pin the floor (§4.6b).
* **Effect state continuity** is threaded for Wobble only; BitCrusher's hold position and Gate's step counter are almost certainly object members too (§4.9).
* **Block size** in the game is the audio device's callback size (`gen+0x1a0`). Since coefficients and LFOs update per block, output is block-size dependent — match `--block` when diffing against a capture.
* **`Timeline` uses a float-seconds clock; the engine uses integer samples** with a truncating `samplesPerBeat` (§5.2). Inaudible, but wrong wherever position arithmetic is compared.

### 8.1 Effect combination — what stacks, what overwrites

Charts routinely have two effects live at once. Three possible models, with `x` the track, `A` the FX-button effect and `B` the laser effect:

| model | meaning | result |
|---|---|---|
| `chain` | series — `B` processes `A`'s output, like two pedals in a row | `B(A(x))` |
| `dry` | overwrite — `B` reads the original track and replaces `A` where they overlap | `B(x)` |
| `add` | parallel — both read the original, their changes sum | `x + (A(x) − x) + (B(x) − x)` |

Order matters in `chain` and not in `add`: a bit crusher into a lowpass filters already-aliased audio, a lowpass into a bit crusher aliases already-smooth audio.

**FX-L + FX-R, both held — genuinely chained.** The FX dispatcher `FUN_18062e3d0` loops its sub-index and swaps the generator's source pointer to the partial result, so the second button reads the first's output.

**The default peak filter + anything — a separate stage.** The C4 = 0 laser sound is a device `_DSFXParamEq` (§7.1), downstream of the whole generator and upstream of the SE mix, so it always stacks on top in that fixed order.

**Tab-laser effect (C4 = 1..5) + FX button — the one place the disassembly and the capture disagree.** The disassembly points at `dry`: `FUN_18062e3d0` restores the generator's source to the original track on the way out (`if (1 < lVar19) { puVar5 = *param_1; *puVar5 = param_2; ... }`), and the laser dispatcher `FUN_18062ea60` then runs against that restored source and `memcpy`s its result over the destination.

Measurement says `chain`, decisively. Rendering the 20 charts with the most FX-hold/tab-laser overlap in all three modes and scoring the overlap frames themselves against each chart's own capture (low-confidence alignments dropped):

```
16 charts, 4656 overlap frames:
  chain  mean +2.706   frame-weighted +2.696   wins 13/16
  dry    mean +2.096   frame-weighted +2.098   wins  3/16
  add    mean +0.895   frame-weighted +0.978   wins  0/16
```

The three charts preferring `dry` do so by 0.1–0.5 dB, inside the spread; `add` is ruled out outright. An independent reimplementation reads the same path as `chain` (§9.1). So `chain` ships, and **the binary reading is what needs re-examining** — specifically whether `FUN_18062e3d0`'s source-pointer restore applies only to the FX sub-chain, or whether `param_2` already points at the FX result by the time it is restored.

**Two consequences wherever effects stack.** *Mix compounds rather than averages*: every effect computes `out = (1-mix)·dry + mix·wet` against **its own input**, so two effects at 50 % leave the original at 25 %, not 50 %. And *there is an int16 requantisation between stages* (`FUN_18063dc40` → `FUN_18063d9e0`, §2), so a chain can clip **mid-chain** — a resonant filter feeding a boosting effect hard-clips at the boundary in a way an all-float implementation would not reproduce. `--no-stage-clip` disables it; the engine does clip, so the default keeps it.

---

## 9. Cross-check against `Rosemoe/sdvx-sfx-renderer`

An independent reimplementation of the same engine (`https://github.com/Rosemoe/sdvx-sfx-renderer`, IDA-based, ~4000 lines of Python). Scope differs — it renders effects and optional click/knob/shot sounds over the song, and does not model the SE bank levels, the music duck, or the peak filter's queue delay. Two independent traces of the same binary agreeing is much stronger evidence than either alone, and where they disagree at least one is wrong.

### 9.1 Independent agreement

* **The device ParamEq (§7.1)** — identical 128-entry centre-frequency table, identical `[80, 16000]` clamp, identical piecewise bandwidth/gain curves, identical `knob < 4` dead zone, and the same `bandwidth / 12` semitones→octaves reading that §7.1 flagged as an assumption.
* **The effect-id table (§3)** — agrees on 11 of 13 ids, including both corrections to the inherited notes (id 3 Flanger, id 12 High Pass Filter).
* **Wobble's five waveform cases, its `(1 − Q·0.04)` trim, and its column layout** `filterType, waveType, mix, freqA, freqB, rate, Q` (§4.9).
* **Laser value handling** — VOL-R mirrored as `1 − pos`, VOL-L raw, `max()` across both lasers into one accumulator (§7.1).
* **`#TRACK AUTO TAB`'s effect column is 2-indexed** (§6.3).
* **A tab-laser effect reads the FX-button result**, not the dry track — the `chain` model of §8.1, which the disassembly appeared to contradict.
* **Tape Stop (id 4) duration in seconds**, and `#BEAT RESOLUTION` honoured per chart (§5.3).

### 9.2 What it supplied

* **Wobble's rate field** (§4.9) — their code names C6 `frequency` and divides by it. Confirmed in our own disassembly before adopting; 13/13 charts improved, +0.878 dB. This alone justified the comparison.
* **A concrete model for the `#TAB PARAM ASSIGN INFO` sweep** (§6.3), whose direction was unresolved here: `min + (max − min) · laserValue` with `laserValue` clamped 0‥1, `param1`/`param2` by chain position, refreshed every 512 samples. Adopted and confirmed by measurement.
* **`C4 = 6` is the param-assign control source**, not an inert laser.
* **Composite id 13 typed as `PITCH_SHIFT_EX`** — an independent trace landing on the same reading upgrades §8's guess from speculation to probable. Still not transcribed at the sample level by either side.

### 9.3 Where the two disagreed

Every disagreement was A/B'd against the reference corpus on the frames the change could plausibly affect, not the whole track. Each remains behind a flag:

```
                        mean(base)  mean(alt)   delta      frame-wtd   result (16 charts each)
Gate hard-binary          +3.427     +1.975    -1.452       -1.474    ours, 16/16
BitCrusher continuous     +2.476     +1.894    -0.582       -0.513    ours, 16/16
Tape Stop Ex 3-phase      +2.908     +2.800    -0.108       -0.082    ours (mixed: 8 up / 6 down / 2 tied)
Laser C7 easing           +1.744     +1.743    -0.001       -0.001    no measurable difference
Sample domain (float)     +0.956     +0.955    -0.000       -0.000    no measurable difference
Param-assign sweep        +0.454     +1.152    +0.698       +0.445    ADOPTED, 5 up / 3 down / 8 unaffected
```

* **Gate's step table and BitCrusher's block-realigned hold grid win decisively.** Both are direct transcriptions of specific struct fields and constants here, and untraced simplifications there (`1.0/0.0` gating; one continuous grid per segment). The corpus agreed with the transcription in both cases.
* **Tape Stop Ex's three-phase model** (attack → hold → release, versus this project's preroll → spin-up) is genuinely inconclusive, not rejected with a clear margin: 8 of 16 charts prefer it, 6 prefer ours, individual swings up to ±3–5 dB. It was the leading hypothesis for the envelope-floor mystery of §4.6b and **did not resolve it** — if it were the missing piece, adopting it should have moved the aggregate. `--tapestop-ex-3phase` is kept for anyone digging further; the struct-offset evidence that both sides read the same routine still stands.
* **The param-assign sweep is the one real adoption beyond Wobble.** Scored on the charts where an AUTO TAB span overlaps an active C4 = 6 laser, it beats static authored parameters on 5 of the 8 charts where it changes anything (8 of 16 saw no assignment active on the measured span). The wins are large when they land (+5.165, +3.517, +2.617) and the losses smaller (−1.600, −1.053, −0.459), which is what drives the positive mean despite the even-looking split.
* **Laser easing and sample domain make no measurable difference**, each scored on exactly the frames where its sub-condition holds (C7 ∈ {4,5} segments; frames where two effects chain and one clips). The float-domain flag provably changes output — up to 61295 magnitude difference in raw samples on `2229_kamui` — it just does not move the spectral metric. Both stay as they were: int16 stage-clipping on (§8.1), laser knob linear.

### 9.4 Head-to-head score

Same charts, source audio, recording, alignment and metric. `gain = dry − render`, higher is closer to the cabinet. Theirs run with `--no-knob --no-shot` so neither side adds sounds the other cannot; ours run twice, `--no-se` for a like-for-like effect-engine comparison and default for the full mix.

```
12 charts, whole-track ALL frames

              mean     median
theirs       +0.122   +0.217
ours --no-se +0.351   +0.435     effects-only: ours ahead on  9/12 charts
ours full    +0.837   +0.889     full mix    : ours ahead on 11/12 charts
```

Two caveats for reading these. Charts were picked by alignment correlation, which unintentionally favours charts whose render differs *little* from dry — one (`1849_sasoribi_virkato`) scores +0.003 for all three renderers because it has almost no effects — compressing every number toward zero, though not in either side's favour. And the full-mix row is not a comparison of effect engines: it includes the SE bank, header gains and the music duck, which their renderer does not attempt. The honest summary is the middle row: **on effect rendering alone, ours is ahead by roughly 0.23 dB mean and wins 9 of 12**, widening to 11 of 12 once the non-generator parts of the mix are included.
