"""Closeness score between a render and the cabinet capture: 46 log-spaced bands per 46 ms frame, level-normalised, mean dB difference. Lower is closer. Calibration only, wired to the kamui capture in scripts/audio/reference/kamui_goal.ogg. Never delete that file: it can't be regenerated and every calibration number depends on it. The three WAVs this needs in output/work/ are described in game_paths.py. For any other song use the audio-refcheck skill.

Score .wav renders, not .ogg, which adds codec noise. The metric fits one global level offset, so a level change can make idle frames look worse.
"""
import os, sys, wave, numpy as np

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)
sys.path.insert(0, os.path.join(_HERE, os.pardir, "shared"))
from game_paths import WORK as SP, MUSIC

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
    offs = np.array([int(round(0.3463 * (k * HOP / SR) - 8.37)) for k in range(nframes)])
    return spectrogram(ref, nframes, offs), nframes


def score(path, refspec, nframes, tag):
    x = rd(path)
    S = spectrogram(x, nframes)
    a = np.log10(np.maximum(refspec, 1e-3))
    b = np.log10(np.maximum(S, 1e-3))
    act = (refspec.mean(axis=1) > 20) & (S.mean(axis=1) > 20)
    a, b = a[act], b[act]
    off = np.median(a - b)
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
