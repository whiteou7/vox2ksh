#!/usr/bin/env python3
"""The effect DSP, transcribed from BMSoundLibSvo::CSvoEffectedAudioGeneratorImpl (specs/audio_engine.md). Runs standalone on a WAV.

    python fx_dsp.py --list
    python fx_dsp.py in.wav out.wav --effect wobble --params 80,0,3,500,18000,4.0,1.4 --range 8:16
"""

import argparse
import math
import sys
import wave

import numpy as np

SR = 44100
TWO_PI_OVER_SR = 0.00014247585
INV_127 = 0.007874016


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
    def q(a):
        a = np.where(a < -32768.0, -32768.0, np.where(a > 32767.0, 32767.0, a))
        return np.trunc(a).astype(np.int16)
    inter = np.empty(L.size * 2, dtype=np.int16)
    inter[0::2] = q(L)
    inter[1::2] = q(R)
    return inter


def write_wav(path, L, R, sr):
    inter = writeback(L, R)
    with wave.open(path, "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(inter.tobytes())


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


def biquad_coeffs(kind, freq, q):
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


def _knob_curve(knob, nblocks, block):
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
    if gain_db == 0.0:
        return (1.0, 0.0, 0.0, 0.0, 0.0)
    A = 10.0 ** (gain_db / 40.0)
    w0 = 2.0 * math.pi * max(float(freq), 20.0) / SR
    sn, cs = math.sin(w0), math.cos(w0)
    bw = max(float(bw_semitones), 1.0) / 12.0
    alpha = sn * math.sinh(0.5 * math.log(2.0) * bw * w0 / sn)
    a0 = 1.0 + alpha / A
    return ((1.0 + alpha * A) / a0, (-2.0 * cs) / a0, (1.0 - alpha * A) / a0,
            (-2.0 * cs) / a0, (1.0 - alpha / A) / a0)


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

PEAK_KNOB_DEADZONE = 4

PEAK_DUCK_MAX = 0.8
PEAK_DUCK_MIN = 0.57
PEAK_DUCK_SLOPE = 0.0025274728
PEAK_DUCK_RAMP = 0.33


def paramq_from_knob(knob, gain_scale=1.0, max_gain_db=None):
    v = int(knob)
    v = 0 if v < 0 else (127 if v > 127 else v)
    fc = PEAK_FC_TABLE[v]
    if fc > PEAK_CENTER_MAX:
        fc = PEAK_CENTER_MAX
    elif fc < PEAK_CENTER_MIN:
        fc = PEAK_CENTER_MIN
    if fc < 200.0:
        bw = gain = fc * 0.075
    elif fc < 1000.0:
        bw = gain = 15.0
    else:
        bw = 15.0 - (fc - 1000.0) * 0.0003
        gain = 15.0 - (fc - 1000.0) * 0.0005
    if v < PEAK_KNOB_DEADZONE:
        gain = 0.0
    gain *= gain_scale
    if max_gain_db is not None and gain > max_gain_db:
        gain = max_gain_db
    return fc, bw, gain


def peak_duck_target(knob):
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


def fx_bitcrush(L, R, mix, rate, block=64, continuous=False):
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
        g = (idx % 2 == 0).astype(np.float32)
    else:
        pat = np.array(pattern or DEFAULT_GATE_PATTERN, dtype=np.float64)
        idx = np.clip(idx, 0, len(pat) - 1)
        g = (pat[idx] * 0.0322).astype(np.float32)

    outL = (1.0 - m) * L + m * L * g
    outR = (1.0 - m) * R + m * R * g
    return outL.astype(np.float32), outR.astype(np.float32)


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


TAPESTOP_EX_FLOOR = 0.5


def fx_tapestop_ex(L, R, mix, speed, dur_sec, preroll_sec, window_sec,
                   floor=None, block=64, lookahead=None):
    m = mixof(mix)
    speed = clampf(float(speed), 1.0, 10.0)
    window = clampf(float(window_sec), 0.1, 2.0) * SR
    preroll = int(max(float(preroll_sec), 0.0) * SR)
    floor = TAPESTOP_EX_FLOOR if floor is None else float(floor)

    n = L.size
    outL, outR = L.copy(), R.copy()
    if window <= 0.0 or n <= 0:
        return outL, outR

    frac, total = 0.0, 0
    i = 0
    while i < window:
        if frac < 1.0:
            total += 1
            frac += (i * speed) / window + 1.0
        frac -= 1.0
        i += 1

    rec_l = rec_r = None
    base = 0
    frac, phase, written = 0.0, 0, 0

    for i0, i1 in blocks(n, block):
        pos = i1
        if pos <= preroll:
            continue
        if pos > preroll + window:
            outL[i0:i1] = (1.0 - m) * L[i0:i1]
            outR[i0:i1] = (1.0 - m) * R[i0:i1]
            continue

        if rec_l is None:
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

    he = min(hold_n, n)
    if he > ae:
        outL[ae:he] = L[ae:he] * dry
        outR[ae:he] = R[ae:he] * dry

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

    if re_ < n:
        outL[re_:] = L[re_:]
        outR[re_:] = R[re_:]

    return outL.astype(np.float32), outR.astype(np.float32)


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


def fx_flanger(L, R, mix, delay_ms, rate, depth_pct, stages, block=64):
    m = mixof(mix)
    d = clampf(float(delay_ms), 0.1, 3.0) * 44.1
    rate = max(float(rate), 0.0) * 0.5
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


def fx_wobble(L, R, mix, filter_type, wave_type, freq_a, freq_b,
              period_sec, q, block=64, state=None):
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


PS_CORRLEN = 441
PS_BUFLEN = 17640
PS_LAG_MIN = 132
PS_LAG_MAX = 882
PS_TAPS = 12


def ps_ratio(amount):
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
    ref = win[:PS_CORRLEN]
    if ref.size < PS_CORRLEN:
        ref = np.pad(ref, (0, PS_CORRLEN - ref.size))
    need = PS_LAG_MAX + PS_CORRLEN
    src = win[:need]
    if src.size < need:
        src = np.pad(src, (0, need - src.size))
    lags = np.arange(PS_LAG_MIN, PS_LAG_MAX + 1)
    idx = lags[:, None] + np.arange(PS_CORRLEN)[None, :]
    corr = (src.astype(np.float64)[idx] * ref.astype(np.float64)[None, :]).sum(1)
    return int(lags[int(np.argmax(corr))])


def _ps_sinc_into(acc, cursor, grain, count, ratio):
    if count <= 0:
        return
    i = np.arange(count, dtype=np.float64)
    pos = i * ratio
    centre = pos.astype(np.int64)
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
    m = mixof(mix)
    ratio = ps_ratio(amount)
    n = L.size
    outL, outR = np.empty(n, np.float32), np.empty(n, np.float32)

    if ratio == 1.0:
        return L.astype(np.float32), R.astype(np.float32)

    accL = np.zeros(PS_BUFLEN, np.float64)
    accR = np.zeros(PS_BUFLEN, np.float64)
    have = 0
    in_cur = 0
    hop_total = 0

    for i0, i1 in blocks(n, block):
        want = i1 - i0
        guard = 0
        while have < want:
            guard += 1
            if guard > 64 or in_cur >= n:
                have = want
                break
            win_l = L[in_cur:in_cur + PS_BUFLEN].astype(np.float64)
            win_r = R[in_cur:in_cur + PS_BUFLEN].astype(np.float64)
            if win_l.size < PS_BUFLEN:
                win_l = np.pad(win_l, (0, PS_BUFLEN - win_l.size))
                win_r = np.pad(win_r, (0, PS_BUFLEN - win_r.size))
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
        if take < want:
            outL[i0 + take:i1] = L[i0 + take:i1]
            outR[i0 + take:i1] = R[i0 + take:i1]

        have = max(have - want, 0)
        accL[:have] = accL[want:want + have]
        accR[:have] = accR[want:want + have]
        accL[have:] = 0.0
        accR[have:] = 0.0

    return outL, outR


PV_FRAME = 2048         # 0x180784910: 1 << (log2(44100) - 4)
PV_HOP = PV_FRAME >> 2  # 0x180784910: frame >> 2, i.e. 4x overlap


def _pv_window():
    return np.hanning(PV_FRAME + 1)[:PV_FRAME].astype(np.float64)


def _pv_render(x, hop_a, n_out):
    if n_out <= 0:
        return np.zeros(0, np.float64)
    win = _pv_window()
    nbins = PV_FRAME // 2 + 1
    omega = 2.0 * np.pi * np.arange(nbins) / PV_FRAME

    pad = PV_FRAME // 2
    src = np.concatenate([np.zeros(pad), np.asarray(x, dtype=np.float64)])
    nframes = int(np.ceil((n_out + pad) / float(PV_HOP))) + 1
    need = max(int(np.ceil(hop_a * nframes)), pad + PV_HOP) + PV_FRAME
    if src.size < need:
        src = np.concatenate([src, np.zeros(need - src.size)])

    def analyse(a):
        spec = np.fft.rfft(src[a:a + PV_FRAME] * win)
        return np.abs(spec), np.angle(spec)

    def deviate(ang, prev, hop):
        d = ang - prev - omega * hop
        d -= 2.0 * np.pi * np.round(d / (2.0 * np.pi))
        return omega + d / hop

    def lock(syn, mag, ang):
        p = np.flatnonzero((mag[1:-1] > mag[:-2]) & (mag[1:-1] >= mag[2:])) + 1
        if p.size == 0:
            return syn
        edges = np.concatenate([[0], (p[:-1] + p[1:] + 1) // 2, [mag.size]])
        owner = np.repeat(p, np.diff(edges))
        return syn[owner] + (ang - ang[owner])

    acc = np.zeros(nframes * PV_HOP + PV_FRAME)
    norm = np.zeros_like(acc)
    frozen = None
    if hop_a <= 0.0:
        mag0, ang0 = analyse(pad)
        frozen = (mag0, deviate(analyse(pad + PV_HOP)[1], ang0, PV_HOP), ang0)

    prev = np.zeros(nbins)
    phase = None
    for i in range(nframes):
        if frozen is not None:
            mag, freq, ang = frozen
            phase = ang.copy() if phase is None else lock(phase + freq * PV_HOP, mag, ang)
        else:
            mag, ang = analyse(int(i * hop_a))
            if phase is None:
                phase = ang.copy()
            else:
                phase = lock(phase + deviate(ang, prev, hop_a) * PV_HOP, mag, ang)
            prev = ang
        o = i * PV_HOP
        acc[o:o + PV_FRAME] += np.fft.irfft(mag * np.exp(1j * phase)) * win
        norm[o:o + PV_FRAME] += win * win

    out = acc[pad:pad + n_out] / np.maximum(norm[pad:pad + n_out], 1e-9)
    if out.size < n_out:
        out = np.concatenate([out, np.zeros(n_out - out.size)])
    return out


def _pv_channel(x, ratio, speed, n_out):
    if ratio == 1.0:
        return _pv_render(x, PV_HOP * speed, n_out)
    m = int(np.ceil(n_out * ratio)) + 2
    mid = _pv_render(x, PV_HOP * speed / ratio, m)
    pos = np.arange(n_out) * ratio
    return np.interp(pos, np.arange(mid.size), mid)


def fx_pitch_speed(L, R, mix, semitones, speed, block=512, lookahead=None):
    n = L.size
    semitones, speed = float(semitones), float(speed)
    if n <= 0 or (semitones == 0.0 and speed == 1.0):
        return L.astype(np.float32), R.astype(np.float32)

    m = mixof(mix)
    ratio = math.pow(2.0, semitones / 12.0)      # 0x18062d92e
    speed = max(speed, 0.0)

    srcL, srcR = L, R
    if lookahead is not None:
        need = int(n * max(speed, 1.0)) + PV_FRAME * 2
        fl, fr, off = lookahead
        srcL, srcR = fl[off:off + need], fr[off:off + need]

    wetL = _pv_channel(srcL, ratio, speed, n)
    wetR = _pv_channel(srcR, ratio, speed, n)
    if speed == 1.0:
        refL, refR = L.astype(np.float64), R.astype(np.float64)
    else:
        refL = _pv_channel(srcL, 1.0, speed, n)
        refR = _pv_channel(srcR, 1.0, speed, n)

    outL = ((1.0 - m) * refL + m * wetL).astype(np.float32)
    outR = ((1.0 - m) * refR + m * wetR).astype(np.float32)
    return outL, outR


EFFECTS = {
    "retrigger":     (fx_retrigger,      "mix,lengthSec,feedback,count,gate,release"),
    "gate":          (fx_gate,           "mix,steps,periodSec"),
    "flanger":       (fx_flanger,        "mix,delayMs,rate,depthPct,stages"),
    "tapestop":      (fx_tapestop,       "mix,speed,durSec"),
    "tapestop_ex":   (fx_tapestop_ex,    "mix,speed,durSec,prerollSec,windowSec"),
    "sidechain":     (fx_sidechain,      "mix,periodSec,attack,hold,release"),
    "wobble":        (fx_wobble,         "mix,filterType,waveType,freqA,freqB,periodSec,Q"),
    "bitcrush":      (fx_bitcrush,       "mix,rate"),
    "pitchshift":    (fx_pitchshift,     "mix,amount"),
    "pitch_speed":   (fx_pitch_speed,    "mix,semitones,speed"),
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
