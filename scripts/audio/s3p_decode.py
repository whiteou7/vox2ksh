"""Extract an S3P0 container and decode each S3V0 (ASF/WMA) entry to WAV."""
import struct, sys, os, subprocess, wave, numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir, "shared"))
from _paths import find_ffmpeg

FF = find_ffmpeg()
if FF is None:
    raise SystemExit("ffmpeg not found - set the FFMPEG env var or put it on PATH")

path, outdir = sys.argv[1], sys.argv[2]
names = []
defp = os.path.splitext(path)[0] + ".def"
if os.path.exists(defp):
    for line in open(defp):
        p = line.split()
        if len(p) >= 3 and p[0] == "#define":
            names.append(p[1])

data = open(path, "rb").read()
magic, count = struct.unpack_from("<4sI", data, 0)
assert magic == b"S3P0", magic
os.makedirs(outdir, exist_ok=True)

print("%-3s %-24s %8s %7s %7s %9s %9s" %
      ("#", "name", "bytes", "dur_s", "peak", "centroid", "attack_ms"))
for i in range(count):
    off, size = struct.unpack_from("<II", data, 8 + i * 8)
    blob = data[off:off + size]
    hdr = struct.unpack_from("<4sI", blob, 0)
    assert hdr[0] == b"S3V0", hdr
    payload = blob[hdr[1]:]
    nm = names[i] if i < len(names) else "idx%02d" % i
    raw = os.path.join(outdir, "%02d_%s.wma" % (i, nm))
    wav = os.path.join(outdir, "%02d_%s.wav" % (i, nm))
    open(raw, "wb").write(payload)
    subprocess.run([FF, "-hide_banner", "-loglevel", "error", "-i", raw,
                    "-ar", "44100", "-ac", "2", "-c:a", "pcm_s16le", "-y", wav],
                   check=True)
    os.remove(raw)
    w = wave.open(wav, "rb"); n = w.getnframes()
    d = np.frombuffer(w.readframes(n), dtype="<i2").astype(np.float32).reshape(-1, 2)
    w.close()
    m = d.mean(axis=1)
    dur = n / 44100.0
    peak = np.abs(m).max()
    # spectral centroid
    X = np.abs(np.fft.rfft(m * np.hanning(len(m))))
    fr = np.fft.rfftfreq(len(m), 1 / 44100.0)
    cen = float((X * fr).sum() / max(X.sum(), 1e-9))
    # time to reach 90% of peak = attack
    env = np.abs(m)
    idx = np.argmax(env >= 0.9 * peak) if peak > 0 else 0
    print("%-3d %-24s %8d %7.3f %7.0f %9.0f %9.1f"
          % (i, nm, size, dur, peak, cen, idx / 44.1))
