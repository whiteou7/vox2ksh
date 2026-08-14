#!/usr/bin/env python3
"""
SOUND VOLTEX audio-effect engine — reference reimplementation.

Transcribed from BMSoundLibSvo::CSvoEffectedAudioGeneratorImpl in
modules/soundvoltex.dll (see README.md for addresses and derivations).

Conventions kept identical to the game:
  * fixed 44100 Hz, stereo
  * DSP operates on float values in the raw int16 magnitude domain (+-32768),
    NOT normalised to +-1
  * out = (1-mix)*dry + mix*wet, mix = clamp(param,0,100)/100
  * coefficients / LFO values are recomputed once per block, not per sample
  * final writeback clamps to [-32768, 32767] and truncates toward zero

Requires numpy, and numpy only. The biquad recursion (_iir_run) runs a
pure-Python per-sample loop rather than a vectorised filter because numpy has
no IIR primitive and scipy is not a dependency; the recursion itself is linear
(see _iir_run's docstring for why its feedback must not be requantised).
"""

import argparse
import math
import sys
import wave

import numpy as np

SR = 44100
TWO_PI_OVER_SR = 0.00014247585   # the literal float constant in the DLL
INV_127 = 0.007874016            # 1/127, the knob normaliser


# --------------------------------------------------------------------------
# WAV I/O  (16-bit PCM only, matching the engine's native format)
# --------------------------------------------------------------------------

def read_wav(path):
    with wave.open(path, "rb") as w:
        if w.getsampwidth() != 2:
            raise SystemExit("only 16-bit PCM WAV is supported (the engine's native format)")
        ch, sr, n = w.getnchannels(), w.getframerate(), w.getnframes()
        raw = w.readframes(n)
    data = np.frombuffer(raw, dtype="<i2").astype(np.float32)
    if ch == 1:
        L = R = data
    else:
        data = data.reshape(-1, ch)
        L, R = data[:, 0].copy(), data[:, 1].copy()
    if sr != SR:
        print(f"warning: input is {sr} Hz; the engine is hard-coded to {SR} Hz. "
              f"Times/frequencies will be off unless you resample first.", file=sys.stderr)
    return L.astype(np.float32), R.astype(np.float32), sr


def writeback(L, R):
    """Engine writeback (FUN_18063dc40): clamp to int16 range, truncate toward
    zero, interleave. Returns the raw int16 frames.

    This is the game's actual output format, so it is the right hand-off point
    for anything downstream - a container writer, or a pipe to an encoder.
    """
    def q(a):
        a = np.where(a < -32768.0, -32768.0, np.where(a > 32767.0, 32767.0, a))
        return np.trunc(a).astype(np.int16)
    inter = np.empty(L.size * 2, dtype=np.int16)
    inter[0::2] = q(L)
    inter[1::2] = q(R)
    return inter


def write_wav(path, L, R, sr):
    """Engine writeback, into a 16-bit PCM WAV."""
    inter = writeback(L, R)
    with wave.open(path, "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(inter.tobytes())


# --------------------------------------------------------------------------
# small helpers
# --------------------------------------------------------------------------

def clampf(v, lo, hi):
    return lo if v < lo else (hi if v > hi else v)


def mixof(v):
    return clampf(float(v), 0.0, 100.0) * 0.01


def blocks(n, block):
    i = 0
    while i < n:
        j = min(i + block, n)
        yield i, j
        i = j


# --------------------------------------------------------------------------
# 4.1  biquads
# --------------------------------------------------------------------------

def biquad_coeffs(kind, freq, q):
    """RBJ cookbook, exactly as FUN_18063df40 / e500 / eb10 compute them."""
    f = max(float(freq), 1.0)
    Q = max(float(q), 0.1)
    w0 = np.float32(f * TWO_PI_OVER_SR)
    sn, cs = math.sin(w0), math.cos(w0)
    alpha = sn * (0.5 / Q)
    a0i = 1.0 / (1.0 + alpha)
    if kind == "lpf":
        b0 = b2 = (1.0 - cs) * 0.5 * a0i
        b1 = (1.0 - cs) * a0i
    elif kind == "hpf":
        b0 = b2 = (1.0 + cs) * 0.5 * a0i
        b1 = -((1.0 + cs) * a0i)
    elif kind == "bpf":
        b0 = alpha * a0i
        b1 = 0.0
        b2 = -alpha * a0i
    else:
        raise ValueError(kind)
    a1 = -2.0 * cs * a0i
    a2 = (1.0 - alpha) * a0i
    return (b0, b1, b2, a1, a2)


def _iir_run(x, c, state):
    """y[n] = b0 x[n] + b1 x[n-1] + b2 x[n-2] - a1 y[n-1] - a2 y[n-2]

    The recursion is linear: the feedback memory (y[n-1], y[n-2]) is plain float, neither clamped nor quantised. `FUN_18063e500` writes each filter output into the *float* history buffers at `gen+0x48` (L) and `gen+0x50` (R) and reads them back from there on the next sample, entirely separately from the mixed/trimmed result it writes to the wet buffers at `gen+0x58`/`gen+0x60`. The only int16 clamp-and-truncate in the chain is the writeback helper `FUN_18063dc40`, which runs once per stage, not per sample - so the inter-stage requantisation of audio_engine.md 8.1 is real and stays on, but it is downstream of this loop rather than inside it.

    An earlier version clamped and truncated the feedback to int16 every sample, on the reading that the engine's scratch buffers are raw int16 and that the next *sample* therefore reads a requantised history. The decompiled leaf above rules that out, and the truncation is not harmless: it injects +-1 LSB into a recursion whose poles sit within 1e-3 of the unit circle at low cutoffs (9.5e-4 at 40 Hz), where the feedback is very nearly `2*y[n-1] - y[n-2]`. That drives a limit cycle. Measured on 0381_hyena_hommarju 4i, whose tab HPF (40-2000 Hz, Q 3) sweeps to its 40 Hz endpoint twice: the truncating version added +8.3 dB at 250-700 Hz and +6.9 dB at 700-2500 Hz over dry, which a 40 Hz highpass cannot do, and doubled RMS (6776 -> 14416 versus 8693 for the linear recursion). Audibly a broadband roar; the cabinet capture of that passage is flat across those bands. The artefact is confined to low cutoffs and is gone by ~200 Hz, which is why it surfaced as two bad laser runs rather than as a chart-wide problem.

    What the truncation was introduced to suppress - gryphone_etia 5m measures 30-33, a fast laser wiggle through the tab LPF at Q=5.0 - is a separate, smaller issue that it only partly masked. Our render's level rises +1.9 dB over its own whole-track level in that window against the capture's +1.0 dB; the clamp took about 0.3 dB off that overshoot while manufacturing the much larger artefact above. See audio_engine.md 8.2.

    Still a per-sample Python loop rather than a vectorised filter: numpy has no IIR primitive and scipy is not a dependency (requirements-gui.txt is numpy-only). It only runs while a filter effect is actually active.
    """
    b0, b1, b2, a1, a2 = c
    x1, x2, y1, y2 = state
    y = np.empty_like(x)
    for i in range(x.size):
        xn = float(x[i])
        yn = b0 * xn + b1 * x1 + b2 * x2 - a1 * y1 - a2 * y2
        y[i] = yn
        x2, x1 = x1, xn
        y2, y1 = y1, yn
    state[0], state[1], state[2], state[3] = x1, x2, y1, y2
    return y


def _new_iir_state():
    return [0.0, 0.0, 0.0, 0.0]


def damp_resonance(q, scale=1.0, max_db=None):
    """Tame an LPF/HPF's resonant peak without moving its cutoff.

    NOT part of the transcription - the game always runs the authored Q
    (`FUN_180630760` hands the chart's Q straight to the DSP leaf, no scaling,
    no clamp). This exists for the same reason `paramq_from_knob`'s
    `gain_scale`/`max_gain_db` do, and reads the same way: left at its
    defaults it returns `q` unchanged and every filter is bit-identical to the
    plain transcription.

    An RBJ lowpass/highpass peaks at exactly `20*log10(Q)` dB at its cutoff,
    so scaling that figure in dB is just `Q ** scale` - which makes `scale` a
    straight "fraction of the resonant boost to keep" and `max_db` a ceiling
    in the same dB the peak is measured in. `Q <= 1` has no peak to tame and
    is returned untouched (scaling it would *raise* resonance toward 1.0,
    which is the opposite of the point), and the result is never above the
    authored Q.
    """
    q = float(q)
    if q <= 1.0:
        return q
    boost_db = 20.0 * math.log10(q) * scale
    if max_db is not None and boost_db > max_db:
        boost_db = max_db
    if boost_db < 0.0:
        boost_db = 0.0
    return min(q, 10.0 ** (boost_db / 20.0))


def filter_blocked(L, R, kind, mix, freq_fn, q, block,
                   res_scale=1.0, res_max_db=None):
    """Run a biquad, recomputing coefficients once per block (freq_fn(blockIdx)).

    `res_scale`/`res_max_db` dampen the LPF/HPF resonance (see damp_resonance);
    they do not apply to `bpf`, which is Wobble's filter selector and carries
    its own separate makeup gain. The `(1 - Q*0.04)` trim deliberately keeps
    using the **authored** Q rather than the damped one: the trim is authentic
    and tied to the chart value, so recomputing it from a damped Q would undo
    part of the damping by handing back the attenuation the engine applies.
    """
    m = mixof(mix)
    Q = max(float(q), 0.1)
    if kind == "bpf":
        if Q <= 1.0:
            g = max(Q + 0.9, 0.1)
        else:
            g = Q * 0.2 + 2.0
            if g > 4.0:
                g = 3.0
        trim = 1.0
        Qc = Q
    else:
        g = 1.0
        trim = 1.0 - Q * 0.04
        Qc = damp_resonance(Q, res_scale, res_max_db)

    sl, sr_ = _new_iir_state(), _new_iir_state()
    outL, outR = L.copy(), R.copy()
    for bi, (i, j) in enumerate(blocks(L.size, block)):
        c = biquad_coeffs(kind, freq_fn(bi), Qc)
        yl = _iir_run(L[i:j], c, sl)
        yr = _iir_run(R[i:j], c, sr_)
        if kind == "bpf":
            outL[i:j] = (1.0 - m) * L[i:j] + m * yl * g
            outR[i:j] = (1.0 - m) * R[i:j] + m * yr * g
        else:
            outL[i:j] = ((1.0 - m) * L[i:j] + m * yl) * trim
            outR[i:j] = ((1.0 - m) * R[i:j] + m * yr) * trim
    return outL, outR


def fx_lpf(L, R, mix, freq, q, block=64, res_scale=1.0, res_max_db=None):
    return filter_blocked(L, R, "lpf", mix, lambda b: freq, q, block,
                          res_scale, res_max_db)


def fx_hpf(L, R, mix, freq, q, block=64, res_scale=1.0, res_max_db=None):
    return filter_blocked(L, R, "hpf", mix, lambda b: freq, q, block,
                          res_scale, res_max_db)


def fx_peak(L, R, mix, freq, q, block=64):
    return filter_blocked(L, R, "bpf", mix, lambda b: freq, q, block)


# --------------------------------------------------------------------------
# 4.2  laser / knob sweeps
# --------------------------------------------------------------------------

def _knob_curve(knob, nblocks, block):
    """knob: list of (seconds, value 0..127) breakpoints -> per-block value."""
    if not knob:
        return lambda b: 0.0
    ts = np.array([k[0] for k in knob], dtype=np.float64)
    vs = np.array([k[1] for k in knob], dtype=np.float64)
    bt = (np.arange(nblocks) * block) / float(SR)
    vals = np.interp(bt, ts, vs)
    return lambda b: float(vals[min(b, nblocks - 1)])


def fx_laser_lpf(L, R, mix, f_lo, f_hi, q, knob=None, block=64,
                 res_scale=1.0, res_max_db=None):
    lo = max(float(f_lo), 1.0)
    ratio = float(f_hi) / lo
    nb = (L.size + block - 1) // block
    kv = _knob_curve(knob, nb, block)
    return filter_blocked(L, R, "lpf", mix,
                          lambda b: lo * (ratio ** (1.0 - kv(b) * INV_127)), q, block,
                          res_scale, res_max_db)


def fx_laser_hpf(L, R, mix, f_lo, f_hi, q, knob=None, block=64,
                 res_scale=1.0, res_max_db=None):
    lo = max(float(f_lo), 1.0)
    ratio = float(f_hi) / lo
    nb = (L.size + block - 1) // block
    kv = _knob_curve(knob, nb, block)
    return filter_blocked(L, R, "hpf", mix,
                          lambda b: lo * (ratio ** (kv(b) * INV_127)), q, block,
                          res_scale, res_max_db)


def peaking_coeffs(freq, q, gain_db):
    """RBJ peakingEQ, parameterised by Q."""
    A = 10.0 ** (gain_db / 40.0)
    w0 = 2.0 * math.pi * max(float(freq), 20.0) / SR
    sn, cs = math.sin(w0), math.cos(w0)
    alpha = sn / (2.0 * max(q, 0.05))
    a0 = 1.0 + alpha / A
    b0 = (1.0 + alpha * A) / a0
    b1 = (-2.0 * cs) / a0
    b2 = (1.0 - alpha * A) / a0
    a1 = (-2.0 * cs) / a0
    a2 = (1.0 - alpha / A) / a0
    return (b0, b1, b2, a1, a2)


def peaking_coeffs_bw(freq, bw_semitones, gain_db):
    """RBJ peakingEQ parameterised by bandwidth in semitones.

    _DSFXParamEq.fBandwidth is documented in semitones, so the DirectSound
    ParamEq DMO's shape is the cookbook peaking filter with
    BW(octaves) = semitones / 12.
    """
    if gain_db == 0.0:
        return (1.0, 0.0, 0.0, 0.0, 0.0)
    A = 10.0 ** (gain_db / 40.0)
    w0 = 2.0 * math.pi * max(float(freq), 20.0) / SR
    sn, cs = math.sin(w0), math.cos(w0)
    bw = max(float(bw_semitones), 1.0) / 12.0          # octaves
    alpha = sn * math.sinh(0.5 * math.log(2.0) * bw * w0 / sn)
    a0 = 1.0 + alpha / A
    return ((1.0 + alpha * A) / a0, (-2.0 * cs) / a0, (1.0 - alpha * A) / a0,
            (-2.0 * cs) / a0, (1.0 - alpha / A) / a0)


# --------------------------------------------------------------------------
# The default ("peak filter") laser sound.
#
# This is NOT the SVO effect generator. FUN_1805c7a00 maps the laser knob to a
# _DSFXParamEq and pushes it into slot 0 of the sound device's ParamEq array
# (FUN_180626b30 -> CDmoSoundFxAudioProcessor<_DSFXParamEq>). Everything below
# is transcribed from that function; see README section 7.
#
# 128-entry centre-frequency table at DAT_18090c050, indexed by int(knob).
# --------------------------------------------------------------------------

PEAK_FC_TABLE = (
    0.0, 6.0, 12.0, 18.0, 24.0, 30.0, 36.0, 42.0,
    48.0, 54.0, 100.0, 106.0, 112.0, 118.0, 124.0, 130.0,
    136.0, 142.0, 148.0, 154.0, 160.0, 166.0, 172.0, 178.0,
    184.0, 190.0, 196.0, 202.0, 232.0, 262.0, 292.0, 322.0,
    352.0, 382.0, 412.0, 442.0, 472.0, 522.0, 572.0, 622.0,
    672.0, 722.0, 772.0, 822.0, 872.0, 922.0, 972.0, 1022.0,
    1072.0, 1122.0, 1172.0, 1222.0, 1272.0, 1322.0, 1372.0, 1422.0,
    1472.0, 1522.0, 1572.0, 1622.0, 1672.0, 1722.0, 1772.0, 1822.0,
    1872.0, 1922.0, 1972.0, 2022.0, 2072.0, 2122.0, 2172.0, 2222.0,
    2272.0, 2322.0, 2372.0, 2422.0, 2472.0, 2522.0, 2572.0, 2622.0,
    2672.0, 2722.0, 2772.0, 2822.0, 2872.0, 2922.0, 2972.0, 3022.0,
    3072.0, 3122.0, 3172.0, 3222.0, 3272.0, 3322.0, 3372.0, 3422.0,
    3472.0, 3522.0, 3572.0, 3622.0, 3672.0, 3852.0, 4032.0, 4212.0,
    4392.0, 4572.0, 4752.0, 4932.0, 5112.0, 5292.0, 5472.0, 5652.0,
    5832.0, 6012.0, 6192.0, 6372.0, 6552.0, 6732.0, 6912.0, 7400.0,
    7700.0, 8000.0, 8400.0, 8800.0, 9270.0, 9750.0, 10240.0, 10800.0,
)

# DirectSound ParamEq limits, applied verbatim by FUN_1805c7a00.
PEAK_CENTER_MIN = 80.0
PEAK_CENTER_MAX = 16000.0

# The knob value below which the game leaves the EQ flat and the music at unity.
PEAK_KNOB_DEADZONE = 4

# Music-voice target gain vs knob (voice vtable+0x60 -> ramped gain, bank 2).
PEAK_DUCK_MAX = 0.8
PEAK_DUCK_MIN = 0.57
PEAK_DUCK_SLOPE = 0.0025274728          # per knob step over 4..94
PEAK_DUCK_RAMP = 0.33                   # gain units per second (FUN_1806a2520)


def paramq_from_knob(knob, gain_scale=1.0, max_gain_db=None):
    """int knob 0..127 -> (fCenter, fBandwidth semitones, fGain dB).

    Transcribed from FUN_1805c7a00 @ 0x1805c7a00.

    `gain_scale`/`max_gain_db` are NOT part of the transcription - the game
    always uses gain_scale=1.0, max_gain_db=None. They exist so a converter
    can deliberately tame the default laser sound's resonant boost (reported:
    audibly loud/distracting "whoosh" at some knob positions) without
    touching the authentic model everything else measures against. Left at
    their defaults, this function is bit-identical to the plain transcription.
    """
    v = int(knob)
    v = 0 if v < 0 else (127 if v > 127 else v)
    fc = PEAK_FC_TABLE[v]
    if fc > PEAK_CENTER_MAX:
        fc = PEAK_CENTER_MAX
    elif fc < PEAK_CENTER_MIN:
        fc = PEAK_CENTER_MIN
    if fc < 200.0:
        bw = gain = fc * 0.075                    # 6.0 .. 15.0, continuous at 200
    elif fc < 1000.0:
        bw = gain = 15.0
    else:
        bw = 15.0 - (fc - 1000.0) * 0.0003        # 15.0 .. 10.5
        gain = 15.0 - (fc - 1000.0) * 0.0005      # 15.0 ..  7.5
    if v < PEAK_KNOB_DEADZONE:
        gain = 0.0
    gain *= gain_scale
    if max_gain_db is not None and gain > max_gain_db:
        gain = max_gain_db
    return fc, bw, gain


def peak_duck_target(knob):
    """int knob 0..127 -> music-voice target gain (FUN_1805c7a00 tail)."""
    v = int(knob)
    v = 0 if v < 0 else (127 if v > 127 else v)
    if v < PEAK_KNOB_DEADZONE:
        return 1.0
    if v < 95:
        return PEAK_DUCK_MAX - (v - 4) * PEAK_DUCK_SLOPE
    if v < 100:
        return PEAK_DUCK_MIN
    if v < 120:
        return (v - 100) * 0.011500001 + PEAK_DUCK_MIN
    return PEAK_DUCK_MAX


def fx_laser_peak(L, R, knob=None, block=64, knob_per_block=None,
                   gain_scale=1.0, max_gain_db=None):
    """Run the device ParamEq over L/R with a knob curve.

    `knob` is the usual list of (seconds, value 0..127) breakpoints;
    `knob_per_block` overrides it with a ready-made per-block array.
    `gain_scale`/`max_gain_db` tame the resonant boost - see paramq_from_knob.
    """
    nb = (L.size + block - 1) // block
    if knob_per_block is None:
        kv = _knob_curve(knob, nb, block)
        kvals = [kv(b) for b in range(nb)]
    else:
        kvals = knob_per_block
    sl, sr_ = _new_iir_state(), _new_iir_state()
    outL, outR = L.copy(), R.copy()
    for bi, (i, j) in enumerate(blocks(L.size, block)):
        fc, bw, gain = paramq_from_knob(kvals[bi], gain_scale, max_gain_db)
        c = peaking_coeffs_bw(fc, bw, gain)
        outL[i:j] = _iir_run(L[i:j], c, sl)
        outR[i:j] = _iir_run(R[i:j], c, sr_)
    return outL, outR


def fx_laser_bitcrush(L, R, mix, _rate_unused, knob=None, block=64):
    nb = (L.size + block - 1) // block
    kv = _knob_curve(knob, nb, block)
    outL, outR = L.copy(), R.copy()
    for bi, (i, j) in enumerate(blocks(L.size, block)):
        vn = clampf(kv(bi) * INV_127, 0.0, 1.0)
        rate = int(vn * 29.0 + 1.0)
        outL[i:j], outR[i:j] = fx_bitcrush(L[i:j], R[i:j], mix, rate, block=block)
    return outL, outR


# --------------------------------------------------------------------------
# 4.3  bit crusher
# --------------------------------------------------------------------------

def fx_bitcrush(L, R, mix, rate, block=64, continuous=False):
    """Sample-and-hold decimator.

    Note: in the DLL the phase counter is a *local* that restarts at 0 on every
    call, i.e. the hold grid realigns at each audio block boundary. Reproduced
    here, so output depends on `block` exactly as the game's does.

    `continuous=True` is a diagnostic for audio_engine.md 9.3: an independent
    reimplementation runs the hold grid once across the whole segment instead
    of restarting it every block.
    """
    m = mixof(mix)
    rate = int(clampf(int(rate), 1, 30))
    outL, outR = L.copy(), R.copy()
    if continuous:
        loc = np.arange(L.size)
        src = loc - (loc % rate)
        outL[:] = (1.0 - m) * L + m * L[src]
        outR[:] = (1.0 - m) * R + m * R[src]
        return outL.astype(np.float32), outR.astype(np.float32)
    for i, j in blocks(L.size, block):
        loc = np.arange(j - i)
        src = i + (loc - (loc % rate))
        outL[i:j] = (1.0 - m) * L[i:j] + m * L[src]
        outR[i:j] = (1.0 - m) * R[i:j] + m * R[src]
    return outL.astype(np.float32), outR.astype(np.float32)


# --------------------------------------------------------------------------
# 4.4  retrigger / echo
# --------------------------------------------------------------------------

def fx_retrigger(L, R, mix, length_sec, feedback, count, gate, release, block=64):
    m = mixof(mix)
    ln = clampf(float(length_sec), 0.1, 8.0)
    fb = clampf(float(feedback), 0.1, 1.0)
    cnt = int(clampf(int(count), 1, 32))
    gt = clampf(float(gate), 0.1, 1.0)
    rel = clampf(float(release), 0.0, 1.0)

    seg = max(int(ln * SR) // cnt, 1)
    gate_len = int(seg * gt)
    fade_len = int(gate_len * rel)
    gtab = np.array([fb ** k for k in range(32)], dtype=np.float32)

    n = L.size
    t = np.arange(n) % (seg * cnt)
    rep = t // seg
    rem = t % seg
    src = np.maximum(np.arange(n) - rep * seg, 0)

    env = gtab[rep]
    if fade_len > 0:
        tail = rem > (gate_len - fade_len)
        f = 1.0 - ((rem - gate_len) + fade_len) / float(fade_len)
        env = np.where(tail, env * np.clip(f, 0.0, 1.0), env)
    env = np.where(rem > gate_len, 0.0, env)

    outL = (1.0 - m) * L + m * L[src] * env
    outR = (1.0 - m) * R + m * R[src] * env
    return outL.astype(np.float32), outR.astype(np.float32)


# --------------------------------------------------------------------------
# 4.5  gate
# --------------------------------------------------------------------------

DEFAULT_GATE_PATTERN = [32, 4] * 8          # the constant at 0x180933e50


def fx_gate(L, R, mix, steps, period_sec, pattern=None, block=64, hard_binary=False):
    m = mixof(mix)
    steps = int(clampf(int(steps), 1, 32))
    period = clampf(float(period_sec), 0.1, 4.0) * SR
    step_len = max(int(period) // steps, 1)

    n = L.size
    t = np.arange(n) % int(period)
    idx = t // step_len
    idx = np.where(idx > 15, idx - 16, idx)

    if hard_binary:
        # diagnostic: plain 50% duty cycle, no table, no makeup gain - the
        # simplification an independent reimplementation uses in place of
        # transcribing struct+0x10. See audio_engine.md 4.5 / 9.3.
        g = (idx % 2 == 0).astype(np.float32)
    else:
        pat = np.array(pattern or DEFAULT_GATE_PATTERN, dtype=np.float64)
        idx = np.clip(idx, 0, len(pat) - 1)
        g = (pat[idx] * 0.0322).astype(np.float32)

    outL = (1.0 - m) * L + m * L * g
    outR = (1.0 - m) * R + m * R * g
    return outL.astype(np.float32), outR.astype(np.float32)


# --------------------------------------------------------------------------
# 4.6  tape stop
# --------------------------------------------------------------------------

def fx_tapestop(L, R, mix, speed, dur_sec, block=64):
    m = mixof(mix)
    speed = clampf(float(speed), 1.0, 10.0)
    dur = clampf(float(dur_sec), 0.1, 2.0)
    total = dur * SR
    step = 1.0 / total

    n = L.size
    outL, outR = L.copy(), R.copy()
    idx = 0
    frac = 0.0
    written = 0
    for i in range(n):
        if written + 1 >= total:
            outL[i] = (1.0 - m) * L[i]
            outR[i] = (1.0 - m) * R[i]
            continue
        if frac < 1.0:
            before = idx
            idx += 1
            frac += before * step * speed + 1.0
        env = 1.0 - written * step
        s = min(idx, n - 1)
        outL[i] = (1.0 - m) * L[i] + m * L[s] * env
        outR[i] = (1.0 - m) * R[i] + m * R[s] * env
        written += 1
        frac -= 1.0
    return outL, outR


# --------------------------------------------------------------------------
# 4.6b  tape stop ex
# --------------------------------------------------------------------------

# The envelope floor Tape Stop Ex ramps up FROM. In the engine this is a struct
# field (this+0x46), not a chart column, and what writes it was never traced -
# so this is the one value in this effect that is FITTED rather than transcribed.
#
# Swept against 13 capture-matched charts (audio_engine.md 4.6b). What the data
# actually supports is narrow: running the effect at all beats not running it by
# ~2 dB, and a floor of 0.0 is clearly wrong (+1.92 vs +3.2). It does NOT pick a
# value in between - 0.4/0.5/0.6/0.75 score +3.159/+3.217/+3.234/+3.205, a 0.08
# dB spread that is noise, and individual charts disagree in opposite directions
# (steelneedle wants 0.4, pureruby wants 1.0). 0.5 is the middle of a plateau,
# not a fitted optimum; do not tune it further without new evidence.
TAPESTOP_EX_FLOOR = 0.5


def fx_tapestop_ex(L, R, mix, speed, dur_sec, preroll_sec, window_sec,
                   floor=None, block=64, lookahead=None):
    """4.6b Tape Stop Ex - FUN_180640c20. NOT the same shape as fx_tapestop.

    Plain Tape Stop fades OUT to silence while slowing down. This one runs the
    other way: it ramps UP from `floor` to full level while the playback rate
    ACCELERATES back to normal, i.e. a spin-up into the beat rather than a
    grind to a halt. Three phases, gated per block on the note-relative
    position (the engine keeps it at this+0x214 and adds the block length each
    call, so the decision uses the position at the END of the block):

        pos <= preroll            untouched dry
        preroll < pos <= preroll+window   the spin-up (below)
        pos > preroll + window    (1-m)*dry, wet contribution finished

    `duration` cannot actually gate anything: the engine's lower bound is
    min(preroll, duration), which is never above preroll, and the active branch
    separately requires pos > preroll. So the column is inert here whatever it
    holds - kept in the signature because the chart carries it.

    On first activation the engine snapshots the dry signal into a record
    buffer and plays THAT back, so the wet path is a recording of the audio at
    the effect's start, not the live input.

    That snapshot is taken from the TRACK, not from the note, and it is up to
    `window` long - which routinely runs past the note's own end. Pass
    `lookahead=(fullL, fullR, offset)` (the caller's whole track plus where this
    slice starts in it) so the recording can extend past the slice the way the
    engine's does. Without it the tail of the recording repeats one clamped
    sample, which on a short note is a DC buzz rather than audio.
    """
    m = mixof(mix)
    speed = clampf(float(speed), 1.0, 10.0)
    window = clampf(float(window_sec), 0.1, 2.0) * SR
    preroll = int(max(float(preroll_sec), 0.0) * SR)
    floor = TAPESTOP_EX_FLOOR if floor is None else float(floor)

    n = L.size
    outL, outR = L.copy(), R.copy()
    if window <= 0.0 or n <= 0:
        return outL, outR

    # Pre-pass: how many recorded samples the whole window will consume. The
    # engine runs this once, before the first output sample, purely to get the
    # total (it is what positions the read head below). Note it integrates the
    # rate ramp in the opposite direction from the main loop - the totals match
    # either way, which is why the engine can get away with it.
    frac, total = 0.0, 0
    i = 0
    while i < window:
        if frac < 1.0:
            total += 1
            frac += (i * speed) / window + 1.0
        frac -= 1.0
        i += 1

    rec_l = rec_r = None
    base = 0            # read head: the playback ENDS on the window boundary
    frac, phase, written = 0.0, 0, 0

    for i0, i1 in blocks(n, block):
        pos = i1                        # position at the end of this block
        if pos <= preroll:
            continue                    # dry, untouched
        if pos > preroll + window:
            outL[i0:i1] = (1.0 - m) * L[i0:i1]
            outR[i0:i1] = (1.0 - m) * R[i0:i1]
            continue

        if rec_l is None:               # one-shot snapshot (this+0x45 flag)
            cap = int(window) + 1
            if lookahead is not None:
                fl, fr, off = lookahead
                a = off + i0
                rec_l = fl[a:a + cap].copy()
                rec_r = fr[a:a + cap].copy()
            else:
                rec_l = L[i0:i0 + cap].copy()
                rec_r = R[i0:i0 + cap].copy()
            base = int(window) - total

        for i in range(i0, i1):
            env = (written / window) * (1.0 - floor) + floor
            if env > 1.0:
                env = 1.0
            if frac < 1.0:
                phase += 1
                frac += (window - written) * speed / window + 1.0
                if frac <= 1.0:
                    frac = 1.0
            frac -= 1.0
            s = base + phase
            if s < 0:
                s = 0
            elif s >= rec_l.size:
                s = rec_l.size - 1
            outL[i] = (1.0 - m) * L[i] + m * env * rec_l[s]
            outR[i] = (1.0 - m) * R[i] + m * env * rec_r[s]
            written += 1

    return outL, outR


def fx_tapestop_ex_3phase(L, R, mix, speed, dur_sec, preroll_sec, window_sec,
                          block=1024, lookahead=None):
    """Diagnostic alternative to fx_tapestop_ex: THREE phases instead of two.

    Ported from an independent reimplementation's `TapeScratch` (its name for
    id 10), which reads attack/hold/release where this project reads
    duration/preroll/window - same chart columns, same clamp ranges per
    column (attack<->duration both [0.1,2.0]s, hold<->preroll both
    unclamped-above, release<->window both [0.1,2.0]s), different claimed
    shape. See audio_engine.md 9.3.

        attack:  play a cached copy of the input at an ACCELERATING read rate
                 while fading OUT to silence, over `duration` seconds
        hold:    silence (dry at (1-mix) only)
        release: play a PREFETCHED copy of the original input (from where
                 hold/release starts, not from attack) at a decelerating read
                 rate while fading volume back IN, over `window` seconds
        after:   fully dry, unattenuated - `mix` does not apply once release
                 has finished, unlike this project's own model

    This is a best-effort, not a byte-exact port: one edge case in the
    source (the attack cache buffer is allocated at full `duration` length
    but may only ever be filled up to `min(duration, preroll)` samples if
    preroll cuts the attack phase short - the common case in real chart data,
    since preroll is usually much shorter than duration - so a fast-forwarding
    read head can run past what was actually cached) is simplified here to
    cap the read head at what is actually filled, avoiding reading unwritten
    zeros. Everything else follows the source directly enough to compare
    line-for-line.
    """
    m = mixof(mix)
    dry = 1.0 - m
    speed = clampf(float(speed), 1.0, 10.0)
    attack_n = max(1, int(clampf(float(dur_sec), 0.1, 2.0) * SR))
    hold_n = max(0, int(max(float(preroll_sec), 0.0) * SR))
    release_n = max(1, int(clampf(float(window_sec), 0.1, 2.0) * SR))

    n = L.size
    outL, outR = L.copy(), R.copy()
    if n <= 0:
        return outL, outR

    # ---------------- attack ----------------
    ae = min(min(attack_n, hold_n), n)
    if ae > 0:
        cacheL, cacheR = L[:ae].copy(), R[:ae].copy()
        idxs = np.empty(ae, dtype=np.int64)
        read_index, phase = 0, 0.0
        for i in range(ae):
            if phase < 1.0:
                ri = read_index
                read_index += 1
                phase += 1.0 + ri * speed / attack_n
            idxs[i] = min(read_index - 1, ae - 1)
            phase -= 1.0
        gains = 1.0 - np.arange(ae, dtype=np.float64) / attack_n
        idxs = np.clip(idxs, 0, ae - 1)
        outL[:ae] = cacheL[idxs] * (m * gains) + L[:ae] * dry
        outR[:ae] = cacheR[idxs] * (m * gains) + R[:ae] * dry

    # ---------------- hold ----------------
    he = min(hold_n, n)
    if he > ae:
        outL[ae:he] = L[ae:he] * dry
        outR[ae:he] = R[ae:he] * dry

    # ---------------- release ----------------
    rs = max(hold_n, he)
    re_ = min(hold_n + release_n, n)
    if re_ > rs:
        if lookahead is not None:
            fullL, fullR, off = lookahead
            a = off + rs
            relL, relR = np.zeros(release_n), np.zeros(release_n)
            avail = min(release_n, fullL.size - a)
            if avail > 0:
                relL[:avail], relR[:avail] = fullL[a:a + avail], fullR[a:a + avail]
        else:
            relL, relR = np.zeros(release_n), np.zeros(release_n)
            avail = min(release_n, n - rs)
            if avail > 0:
                relL[:avail], relR[:avail] = L[rs:rs + avail], R[rs:rs + avail]

        # dry-run to find how many read-head advances the full release takes -
        # the source does this once per release, not once per sample
        step_count, ph = 0, 0.0
        for s in range(release_n):
            if ph < 1.0:
                step_count += 1
                ph += 1.0 + s * speed / release_n
            ph -= 1.0

        attack_gain_end = (1.0 - ae / attack_n) if attack_n else 1.0
        m_rel = re_ - rs
        idxs2 = np.empty(m_rel, dtype=np.int64)
        read_index2, phase2 = 0, 0.0
        for i in range(m_rel):
            if phase2 < 1.0:
                read_index2 += 1
                phase2 = max(phase2 + 1.0 + (release_n - i) * speed / release_n, 1.0)
            ridx = read_index2 + release_n - step_count
            idxs2[i] = max(0, min(ridx, release_n - 1))
            phase2 -= 1.0
        elapsed = np.arange(m_rel, dtype=np.float64)
        rel_gain = np.minimum(attack_gain_end + (elapsed / release_n) * (1.0 - attack_gain_end), 1.0)
        outL[rs:re_] = relL[idxs2] * (m * rel_gain) + L[rs:re_] * dry
        outR[rs:re_] = relR[idxs2] * (m * rel_gain) + R[rs:re_] * dry

    # ---------------- after release: fully dry, mix does not apply ----------
    if re_ < n:
        outL[re_:] = L[re_:]
        outR[re_:] = R[re_:]

    return outL.astype(np.float32), outR.astype(np.float32)


# --------------------------------------------------------------------------
# 4.7  side chain
# --------------------------------------------------------------------------

def fx_sidechain(L, R, mix, period_sec, attack, hold, release, block=64):
    m = mixof(mix)
    period = max(float(period_sec), 0.1)
    a_pct = int(clampf(int(attack), 0, 100))
    h_pct = int(clampf(int(hold), 0, 100))
    r_pct = int(clampf(int(release), 0, 100))

    N = int(period * SR)
    A = max(int(a_pct * 0.002 * N), 1)
    H = int(h_pct * 0.003 * N)
    Rl = max(int(r_pct * 0.005 * N), 1)

    t = np.arange(L.size) % N
    g = np.ones(L.size, dtype=np.float32)
    g = np.where(t < A, 1.0 - t / float(A), g)
    g = np.where((t >= A) & (t < A + H), 0.0, g)
    seg3 = (t >= A + H) & (t < A + H + Rl)
    g = np.where(seg3, ((t - H) - A) / float(Rl), g)

    outL = (1.0 - m) * L + m * L * g
    outR = (1.0 - m) * R + m * R * g
    return outL.astype(np.float32), outR.astype(np.float32)


# --------------------------------------------------------------------------
# 4.8  flanger
# --------------------------------------------------------------------------

def fx_flanger(L, R, mix, delay_ms, rate, depth_pct, stages, block=64):
    m = mixof(mix)
    d = clampf(float(delay_ms), 0.1, 3.0) * 44.1     # base delay in samples
    rate = max(float(rate), 0.0) * 0.5               # LFO Hz
    depth_pct = int(clampf(int(depth_pct), 0, 100))
    st = clampf(float(stages), 0.0, 4.0)
    depth = depth_pct * 0.01 * d
    if rate <= 0.0:
        return L.copy(), R.copy()

    top = int(math.ceil(st))
    wrap = 22050.0 / rate
    quarter = 11025.0 / rate

    n = L.size
    curL, curR = L.astype(np.float64), R.astype(np.float64)
    idx = np.arange(n)

    for p in range(top, -1, -1):
        c = (np.arange(n) % wrap)
        sL = np.sin(c * rate * TWO_PI_OVER_SR)
        c2 = (c + quarter) % wrap
        sR = np.sin(c2 * rate * TWO_PI_OVER_SR)

        posL = idx - (sL * depth + d)
        posR = idx - (sR * depth + d)

        def tap(buf, pos):
            i0 = np.floor(pos).astype(np.int64)
            fr = pos - i0
            i0 = np.clip(i0, 0, n - 2)
            return buf[i0] * (1.0 - fr) + buf[i0 + 1] * fr

        wL, wR = tap(curL, posL), tap(curR, posR)

        if p == top:
            a = m - (1.0 - m) * (top - st)
            b = (top - st) * m + (1.0 - m)
            curL = a * wL + b * curL
            curR = a * wR + b * curR
        else:
            curL = m * wL + (1.0 - m) * curL
            curR = m * wR + (1.0 - m) * curR

        if st >= 1.0 and p == 0:
            curL *= 1.5
            curR *= 1.5

    return curL.astype(np.float32), curR.astype(np.float32)


# --------------------------------------------------------------------------
# 4.9  wobble
# --------------------------------------------------------------------------

def fx_wobble(L, R, mix, filter_type, wave_type, freq_a, freq_b,
              period_sec, q, block=64, state=None):
    """LFO-swept biquad.

    The engine's LFO counter is an object member at `this+0x238`, written back
    every block (0x1806416b1 / 0x1806416c2) - so it does NOT restart at each
    note, it resumes where the previous note left it. Pass a dict as `state` to
    reproduce that; omit it and the phase starts at zero, which is what a
    standalone one-shot render wants.
    """
    lo = min(float(freq_a), float(freq_b))
    hi = max(float(freq_a), float(freq_b))
    period = max(float(period_sec), 0.1) * SR
    Q = max(float(q), 0.1)
    ratio = hi / max(lo, 1e-9)
    kind = {0: "lpf", 1: "hpf", 2: "bpf"}[int(filter_type)]
    wt = int(wave_type)
    start = float(state.get("counter", 0.0)) if state is not None else 0.0

    def freq_for(bi):
        counter = (start + bi * block) % period
        ph = counter / period
        if wt == 0:
            return lo + ph * (hi - lo)
        if wt == 1:
            return hi - ph * (hi - lo)
        if wt == 2:
            return lo * (ratio ** ((math.sin(ph * 2.0 * math.pi) + 1.0) * 0.5))
        if wt == 3:
            tri = 2.0 * ph if counter < period * 0.5 else 2.0 - 2.0 * ph
            return lo * (ratio ** tri)
        if wt == 4:
            return hi if counter >= period * 0.5 else lo
        return lo

    out = filter_blocked(L, R, kind, mix, freq_for, Q, block)
    if state is not None:
        nblocks = (L.size + block - 1) // block
        state["counter"] = (start + nblocks * block) % period
    return out


# --------------------------------------------------------------------------
# 4.10  pitch shift
# --------------------------------------------------------------------------

# Constants written by the constructor FUN_18063d5d0 @ 0x18063d5d0. All three
# buffer pairs (input window, grain, output accumulator) are PS_BUFLEN floats.
PS_CORRLEN = 441        # 0x244: autocorrelation window, 10 ms @ 44100
PS_BUFLEN = 17640       # 0x24c / 0x260 / 0x278: 400 ms @ 44100
PS_LAG_MIN = 132        # 0x84   -> 334 Hz
PS_LAG_MAX = 882        # 0x372  -> 50 Hz
PS_TAPS = 12            # sinc kernel half-width; 25 taps total


def ps_ratio(amount):
    """Chart `amount` (semitones) -> resample ratio, exactly as the DLL's
    prologue conditions it (0x180642a2a-0x180642a9c).

    Two clamps the .vox column range does not advertise: the value is limited
    to +-12 semitones, and any NONZERO magnitude below one semitone is pushed
    OUT to +-1 rather than rounded toward zero. Exactly 0 survives as 0 and
    takes the unison passthrough branch.
    """
    a = float(amount)
    if a >= -12.0:
        a = min(a, 12.0)
        if a < 0.0:
            a = min(a, -1.0)
    else:
        a = -12.0
    if 0.0 < a < 1.0:
        a = 1.0
    return math.pow(2.0, a / 12.0)


def _ps_best_lag(win):
    """Pitch period by autocorrelation, over lags PS_LAG_MIN..PS_LAG_MAX.

    Correlates PS_CORRLEN samples of the LEFT channel only (the DLL reads
    buffer 0x268 for both the reference and the delayed copy, then applies the
    winning lag to both channels), keeping a running max. Ties keep the
    EARLIER lag: the DLL updates its best only on a strict increase
    (`if (dVar53 <= dVar55) keep old`), so a flat/silent window resolves to
    PS_LAG_MIN rather than to the last lag tried.
    """
    ref = win[:PS_CORRLEN]
    if ref.size < PS_CORRLEN:
        ref = np.pad(ref, (0, PS_CORRLEN - ref.size))
    need = PS_LAG_MAX + PS_CORRLEN
    src = win[:need]
    if src.size < need:
        src = np.pad(src, (0, need - src.size))
    # corr[k] = sum_i ref[i] * src[i + lag_min + k], accumulated in float64 as
    # the DLL does (its running sum is a double even though the taps are float)
    lags = np.arange(PS_LAG_MIN, PS_LAG_MAX + 1)
    idx = lags[:, None] + np.arange(PS_CORRLEN)[None, :]
    corr = (src.astype(np.float64)[idx] * ref.astype(np.float64)[None, :]).sum(1)
    return int(lags[int(np.argmax(corr))])


def _ps_sinc_into(acc, cursor, grain, count, ratio):
    """The output stage: resample `grain` by `ratio` with a 25-tap windowed
    sinc and ADD it into `acc` at `cursor` (0x180643337 up / 0x180643a73 down).

    out[i] = sum over k in [int(i*r)-12, int(i*r)+12] of sinc(i*r - k)*grain[k]

    This runs on BOTH shift directions - it is what actually moves the pitch.
    The direction-specific code before it only assembles the grain and picks
    the hop, i.e. it fixes the DURATION that this resample would otherwise
    change. Note `int(i*r)` truncates (cvttss2si) and taps at negative source
    indices are skipped, not clamped.
    """
    if count <= 0:
        return
    i = np.arange(count, dtype=np.float64)
    pos = i * ratio
    centre = pos.astype(np.int64)                # truncation toward zero
    k = centre[:, None] + np.arange(-PS_TAPS, PS_TAPS + 1)[None, :]
    x = (pos[:, None] - k) * 3.1415927
    w = np.where(x == 0.0, 1.0, np.sin(x) / np.where(x == 0.0, 1.0, x))
    ok = (k >= 0) & (k < grain.size)
    contrib = np.where(ok, w * grain[np.clip(k, 0, grain.size - 1)], 0.0)
    end = min(cursor + count, acc.size)
    take = end - cursor
    if take > 0:
        acc[cursor:end] += contrib.sum(1)[:take].astype(np.float32)


def fx_pitchshift(L, R, mix, amount, block=512, legacy_cursor=False):
    """PSOLA pitch shift - FUN_1806429b0 @ 0x1806429b0.

    Three stages per pass, all inside one `while accumulated < blockLen` loop:

      1. reload a PS_BUFLEN-frame window of the dry track from the running
         input cursor, and find its pitch period by autocorrelation;
      2. assemble a grain: a triangular crossfade over `lag` samples between
         the window and itself one `lag` later (the SOLA splice that changes
         duration without a discontinuity), then a plain copy tail;
      3. resample that grain by `ratio` through the 25-tap sinc above,
         accumulating into a persistent output buffer.

    Once the accumulator holds a full block it is mixed against the dry input
    - `out = (1-mix)*dry + mix*acc`, a PLAIN dry/wet mix, not a crossfade
    against previous output - consumed, and shifted down.

    `legacy_cursor` selects how the input cursor advances between passes. The
    tail at 0x180643472 (`lea esi, [rsi + r12*2]`) first read as advancing by a
    running TOTAL of hops rather than by this pass's hop, which would make the
    read position accelerate through a held note. Measurement rejected that
    outright (-0.815 dB against the per-pass hop over 8 charts, and a +12
    semitone shift degenerates to near-silence), so the per-pass hop is the
    default and the accelerating reading survives only as a diagnostic.
    See audio_engine.md 4.10.
    """
    m = mixof(mix)
    ratio = ps_ratio(amount)
    n = L.size
    outL, outR = np.empty(n, np.float32), np.empty(n, np.float32)

    if ratio == 1.0:                       # unison: the DLL copies straight
        return L.astype(np.float32), R.astype(np.float32)

    accL = np.zeros(PS_BUFLEN, np.float64)
    accR = np.zeros(PS_BUFLEN, np.float64)
    have = 0                               # 0x248, persists across blocks
    in_cur = 0                             # source frame the window starts at
    hop_total = 0                          # the running sum legacy_cursor uses

    for i0, i1 in blocks(n, block):
        want = i1 - i0
        guard = 0
        while have < want:
            guard += 1
            if guard > 64 or in_cur >= n:  # ran off the note; pad with silence
                have = want
                break
            win_l = L[in_cur:in_cur + PS_BUFLEN].astype(np.float64)
            win_r = R[in_cur:in_cur + PS_BUFLEN].astype(np.float64)
            if win_l.size < PS_BUFLEN:
                win_l = np.pad(win_l, (0, PS_BUFLEN - win_l.size))
                win_r = np.pad(win_r, (0, PS_BUFLEN - win_r.size))
            # the int16 loader zeroes BOTH channels wherever the LEFT sample is
            # exactly 0 and never reads the right one (0x180642b43); shared with
            # FUN_18063d9e0, so it is a loader convention, not a pitch quirk
            zero = win_l == 0.0
            win_r = np.where(zero, 0.0, win_r)

            lag = _ps_best_lag(win_l)
            if ratio > 1.0:
                hop = int(lag / (ratio - 1.0) + 0.5)
                count = hop
            else:
                hop = int(lag / (1.0 / ratio - 1.0) + 0.5)
                count = hop + lag
            hop = max(hop, 1)

            # stage 2: SOLA splice, then the plain copy tail
            span = max(hop, lag)
            gl = np.zeros(span + PS_LAG_MAX, np.float64)
            gr = np.zeros(span + PS_LAG_MAX, np.float64)
            j = np.arange(lag)
            wdn = (lag - j) / float(lag)
            wup = j / float(lag)
            gl[:lag] = wdn * win_l[:lag] + wup * win_l[lag:2 * lag]
            gr[:lag] = wdn * win_r[:lag] + wup * win_r[lag:2 * lag]
            if span > lag:
                tail = min(span - lag, PS_BUFLEN - 2 * lag)
                if tail > 0:
                    gl[lag:lag + tail] = win_l[lag:lag + tail]
                    gr[lag:lag + tail] = win_r[lag:lag + tail]

            _ps_sinc_into(accL, have, gl, count, ratio)
            _ps_sinc_into(accR, have, gr, count, ratio)

            have = min(have + count, PS_BUFLEN)
            hop_total += hop
            in_cur += hop_total if legacy_cursor else hop

        take = min(want, have)
        outL[i0:i0 + take] = (1.0 - m) * L[i0:i0 + take] + m * accL[:take]
        outR[i0:i0 + take] = (1.0 - m) * R[i0:i0 + take] + m * accR[:take]
        if take < want:                    # accumulator underran: pass dry
            outL[i0 + take:i1] = L[i0 + take:i1]
            outR[i0 + take:i1] = R[i0 + take:i1]

        have = max(have - want, 0)
        accL[:have] = accL[want:want + have]
        accR[:have] = accR[want:want + have]
        accL[have:] = 0.0
        accR[have:] = 0.0

    return outL, outR


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------

EFFECTS = {
    # name              (fn,             param names / .vox column order after the type id)
    "retrigger":     (fx_retrigger,      "mix,lengthSec,feedback,count,gate,release"),
    "gate":          (fx_gate,           "mix,steps,periodSec"),
    "flanger":       (fx_flanger,        "mix,delayMs,rate,depthPct,stages"),
    "tapestop":      (fx_tapestop,       "mix,speed,durSec"),
    "tapestop_ex":   (fx_tapestop_ex,    "mix,speed,durSec,prerollSec,windowSec"),
    "sidechain":     (fx_sidechain,      "mix,periodSec,attack,hold,release"),
    "wobble":        (fx_wobble,         "mix,filterType,waveType,freqA,freqB,periodSec,Q"),
    "bitcrush":      (fx_bitcrush,       "mix,rate"),
    "pitchshift":    (fx_pitchshift,     "mix,amount"),
    "lpf":           (fx_lpf,            "mix,freq,Q"),
    "hpf":           (fx_hpf,            "mix,freq,Q"),
    "peak":          (fx_peak,           "mix,freq,Q"),
    "laser_lpf":     (fx_laser_lpf,      "mix,freqLo,freqHi,Q"),
    "laser_hpf":     (fx_laser_hpf,      "mix,freqLo,freqHi,Q"),
    "laser_bitcrush":(fx_laser_bitcrush, "mix,rate"),
}

INT_PARAMS = {
    "retrigger": {3},
    "gate": {1},
    "flanger": {3},
    "sidechain": {2, 3, 4},
    "wobble": {1, 2},
    "bitcrush": {1},
    "laser_bitcrush": {1},
}


def parse_knob(s):
    if not s:
        return None
    out = []
    for part in s.split(","):
        t, v = part.split(":")
        out.append((float(t), float(v)))
    return sorted(out)


def main():
    ap = argparse.ArgumentParser(
        description="Apply SOUND VOLTEX FX/laser effects to a 16-bit WAV file.")
    ap.add_argument("input", nargs="?")
    ap.add_argument("output", nargs="?")
    ap.add_argument("--effect", "-e")
    ap.add_argument("--params", "-p", default="",
                    help="comma-separated, in .vox column order (see --list)")
    ap.add_argument("--range", "-r", default=None,
                    help="apply only to START:END seconds, e.g. 8:16")
    ap.add_argument("--knob", "-k", default=None,
                    help="laser knob automation: 'sec:val,sec:val' with val in 0..127")
    ap.add_argument("--block", "-b", type=int, default=64,
                    help="per-block coefficient update size in frames (default 64)")
    ap.add_argument("--list", action="store_true", help="list effects and parameters")
    args = ap.parse_args()

    if args.list or not args.effect:
        print("effect          parameters (.vox column order)")
        print("-" * 66)
        for k, (_, sig) in EFFECTS.items():
            print(f"{k:<16}{sig}")
        return 0

    if not args.input or not args.output:
        ap.error("input and output are required")

    if args.effect not in EFFECTS:
        ap.error(f"unknown effect {args.effect!r}; try --list")
    fn, sig = EFFECTS[args.effect]

    raw = [p for p in args.params.split(",") if p != ""]
    ints = INT_PARAMS.get(args.effect, set())
    params = [int(float(p)) if i in ints else float(p) for i, p in enumerate(raw)]
    want = len(sig.split(","))
    if len(params) != want:
        ap.error(f"{args.effect} takes {want} params ({sig}), got {len(params)}")

    L, R, sr = read_wav(args.input)

    if args.range:
        a, b = args.range.split(":")
        i0, i1 = int(float(a) * sr), int(float(b) * sr)
        i0, i1 = max(0, i0), min(L.size, i1)
    else:
        i0, i1 = 0, L.size

    kw = {"block": args.block}
    if args.effect.startswith("laser_"):
        kw["knob"] = parse_knob(args.knob)

    wl, wr = fn(L[i0:i1].copy(), R[i0:i1].copy(), *params, **kw)
    outL, outR = L.copy(), R.copy()
    outL[i0:i1], outR[i0:i1] = wl, wr

    write_wav(args.output, outL, outR, sr)
    print(f"wrote {args.output}  [{args.effect} {args.params} over "
          f"{i0/sr:.3f}s..{i1/sr:.3f}s, block={args.block}]")
    return 0


if __name__ == "__main__":
    sys.exit(main())
