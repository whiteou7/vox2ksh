"""Enumerate functions from .pdata (RUNTIME_FUNCTION table) and disassemble them."""
import os, sys, struct, bisect
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pe import Bin
import capstone

class Funcs:
    def __init__(self, b):
        self.b = b
        self.entries = []   # (start_va, end_va, unwind_va)
        for s in b.secs:
            if s['name'] == '.pdata':
                raw, size = s['raw'], s['vsize']
                data = b.data[raw:raw+size]
                for i in range(0, len(data) - 11, 12):
                    st, en, uw = struct.unpack('<III', data[i:i+12])
                    if st == 0 and en == 0:
                        continue
                    self.entries.append((b.base + st, b.base + en, b.base + uw))
        self.entries.sort()
        self.starts = [e[0] for e in self.entries]

    def func_of(self, va):
        i = bisect.bisect_right(self.starts, va) - 1
        if i < 0: return None
        st, en, uw = self.entries[i]
        if st <= va < en:
            return (st, en)
        return None

    def disas(self, st, en):
        o = self.b.va2off(st)
        return list(self.b.md.disasm(self.b.data[o:o+(en-st)], st))


def fmt(b, insns, annotate=True):
    out = []
    for ins in insns:
        line = "%016x  %-10s %s" % (ins.address, ins.mnemonic, ins.op_str)
        if annotate:
            notes = []
            for op in ins.operands:
                if op.type == capstone.x86.X86_OP_MEM and op.mem.base == capstone.x86.X86_REG_RIP:
                    t = ins.address + ins.size + op.mem.disp
                    notes.append("[%x]" % t)
                    d = b.read(t, 8)
                    if d:
                        f = struct.unpack('<f', d[:4])[0]
                        dd = struct.unpack('<d', d)[0]
                        s = b.cstr(t, 48)
                        pr = ''.join(c for c in s if 32 <= ord(c) < 127) if s else ''
                        if len(pr) >= 4 and pr == s:
                            notes.append('str="%s"' % pr)
                        else:
                            if abs(f) < 1e18 and (abs(f) > 1e-18 or f == 0):
                                notes.append("f32=%.9g" % f)
                            if abs(dd) < 1e18 and (abs(dd) > 1e-18 or dd == 0):
                                notes.append("f64=%.12g" % dd)
                            notes.append("q=%x" % struct.unpack('<Q', d)[0])
            if notes:
                line += "   ; " + " ".join(notes)
        out.append(line)
    return "\n".join(out)


if __name__ == '__main__':
    b = Bin()
    F = Funcs(b)
    print("functions in .pdata:", len(F.entries), file=sys.stderr)
    for a in sys.argv[1:]:
        va = int(a, 16)
        r = F.func_of(va)
        if not r:
            print("no func for %x" % va); continue
        st, en = r
        print("\n;===== func %x - %x  (size %x), query %x" % (st, en, en-st, va))
        print(fmt(b, F.disas(st, en)))
