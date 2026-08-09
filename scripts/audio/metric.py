"""Phase-insensitive closeness metric against the reference capture.

Compares log-magnitude spectra in 46 log-spaced bands per 46 ms frame, after
normalising each candidate to the reference's overall level. Robust to the
capture's polarity inversion, 8 ppm drift and Ogg coding.
Returns mean |dB difference| - lower is closer.
"""
import os, sys, wave, numpy as np

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)
sys.path.insert(0, os.path.join(_HERE, os.pardir, "shared"))
from _paths import WORK as SP, MUSIC

SR = 44100
N = 2048
HOP = 1024

_BANDS = None


def bands():
    global _BANDS
    if _BANDS is None:
        fr = np.fft.rfftfreq(N, 1.0 / SR)
        edges = np.geomspace(40.0, 18000.0, 47)
        _BANDS = [np.flatnonzero((fr >= edges[i]) & (fr < edges[i + 1]))
                  for i in range(46)]
    return _BANDS


def rd(p):
    w = wave.open(p, 'rb'); n = w.getnframes()
    d = np.frombuffer(w.readframes(n), dtype='<i2').astype(np.float64).reshape(-1, 2)
    w.close(); return d.mean(axis=1)


def spectrogram(x, nframes, offs=None):
    B = bands()
    out = np.zeros((nframes, len(B)))
    win = np.hanning(N)
    for k in range(nframes):
        i = k * HOP + (offs[k] if offs is not None else 0)
        if i < 0 or i + N > len(x):
            continue
        X = np.abs(np.fft.rfft(x[i:i + N] * win))
        for j, sel in enumerate(B):
            out[k, j] = X[sel].mean() if len(sel) else 0.0
    return out


def build_ref():
    ref = -rd(os.path.join(SP, "goal.wav"))
    nframes = (len(ref) - N) // HOP
    # drift model measured earlier: offset(t) = 0.3463*t(seconds) - 8.37
    offs = np.array([int(round(0.3463 * (k * HOP / SR) - 8.37)) for k in range(nframes)])
    return spectrogram(ref, nframes, offs), nframes


def score(path, refspec, nframes, tag):
    x = rd(path)
    S = spectrogram(x, nframes)
    a = np.log10(np.maximum(refspec, 1e-3))
    b = np.log10(np.maximum(S, 1e-3))
    # active frames only (ignore silence at both ends)
    act = (refspec.mean(axis=1) > 20) & (S.mean(axis=1) > 20)
    a, b = a[act], b[act]
    off = np.median(a - b)                 # global level match, in log10
    d = 20.0 * np.abs((a - b) - off)
    print("  %-34s  mean |dB| = %6.3f   (level offset %+.2f dB, %d frames)"
          % (tag, d.mean(), 20 * off, act.sum()))
    return d.mean()


if __name__ == "__main__":
    refspec, nframes = build_ref()
    print("reference frames: %d" % nframes)
    for path, tag in [(os.path.join(SP, "kamui_dry.wav"), "dry (no processing)")] + \
                     [(p, os.path.basename(p)) for p in sys.argv[1:]]:
        score(path, refspec, nframes, tag)
