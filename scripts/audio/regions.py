"""Break the closeness metric down by what the chart is doing at each frame."""
import os, sys, wave, numpy as np

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)
sys.path.insert(0, os.path.join(_HERE, os.pardir, "shared"))
from _paths import WORK as SP, MUSIC
from metric import build_ref, spectrogram, rd, HOP, N
from apply_chart import read_sections, Timeline, parse_effects, FX_NAMES
SR = 44100

refspec, nframes = build_ref()

folder = os.path.join(MUSIC, "2229_kamui_tjhangneil")
sec = read_sections(os.path.join(folder, "2229_kamui_tjhangneil_5m.vox"))
tl = Timeline(sec)
fxdefs = parse_effects(sec, "#FXBUTTON EFFECT INFO")

fx_mask = np.zeros(nframes, bool)
peak_mask = np.zeros(nframes, bool)
tab_mask = np.zeros(nframes, bool)


def mark(mask, a, b):
    i0 = max(0, a // HOP); i1 = min(nframes, b // HOP + 1)
    mask[i0:i1] = True


for trk in ("#TRACK2", "#TRACK7"):
    for line in sec.get(trk, []):
        f = line.split()
        if len(f) >= 3 and int(f[1]) > 0 and int(f[2]) >= 2:
            t0 = tl.tick_of(f[0])
            mark(fx_mask, tl.samples(t0), tl.samples(t0 + int(f[1])))
for trk in ("#TRACK1", "#TRACK8"):
    pts = []
    for line in sec.get(trk, []):
        f = line.split()
        if len(f) >= 9:
            pts.append((tl.tick_of(f[0]), int(f[2]), int(f[4])))
    pts.sort(key=lambda x: (x[0],))
    for i in range(len(pts) - 1):
        if pts[i][1] == 2 or pts[i + 1][0] <= pts[i][0]:
            continue
        a, b = tl.samples(pts[i][0]), tl.samples(pts[i + 1][0])
        if pts[i][2] == 0:
            mark(peak_mask, a, b)
        elif 1 <= pts[i][2] <= 5:
            mark(tab_mask, a, b)

idle = ~(fx_mask | peak_mask | tab_mask)
print("frame coverage: FX %.0f%%  peak-laser %.0f%%  tab-laser %.0f%%  idle %.0f%%"
      % (100 * fx_mask.mean(), 100 * peak_mask.mean(),
         100 * tab_mask.mean(), 100 * idle.mean()))


def report(path, tag):
    S = spectrogram(rd(path), nframes)
    a = np.log10(np.maximum(refspec, 1e-3))
    b = np.log10(np.maximum(S, 1e-3))
    act = (refspec.mean(axis=1) > 20) & (S.mean(axis=1) > 20)
    off = np.median((a - b)[act])
    d = 20.0 * np.abs((a - b) - off)
    per = d.mean(axis=1)
    print("  %-26s all %5.3f | FX %5.3f | peak %5.3f | tab %5.3f | idle %5.3f"
          % (tag, per[act].mean(),
             per[act & fx_mask].mean(), per[act & peak_mask].mean(),
             per[act & tab_mask].mean(), per[act & idle].mean()))


report(os.path.join(SP, "kamui_dry.wav"), "dry")
for _p in (sys.argv[1:] or [os.path.join(SP, "best.wav")]):
    report(_p, os.path.basename(_p))
