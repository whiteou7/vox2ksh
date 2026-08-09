import os, sys, struct
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pe import Bin
from xref import scan_rip_refs, decode_at

b = Bin()
start = int(sys.argv[1], 16)
end = int(sys.argv[2], 16)
o = b.va2off(start)
data = b.data[o:o + (end - start)]
for i in range(0, len(data) - 7, 4):
    va = start + i
    f = struct.unpack('<f', data[i:i+4])[0]
    d = struct.unpack('<d', data[i:i+8])[0] if i + 8 <= len(data) else 0.0
    u = struct.unpack('<I', data[i:i+4])[0]
    fs = ("%.9g" % f) if (abs(f) > 1e-30 and abs(f) < 1e30) or f == 0 else ''
    ds = ("%.12g" % d) if (abs(d) > 1e-30 and abs(d) < 1e30) or d == 0 else ''
    print("%x  %08x  f=%-16s d=%s" % (va, u, fs, ds))
