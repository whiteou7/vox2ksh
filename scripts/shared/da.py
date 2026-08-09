"""Annotated disassembler: da.py <startVA> [endVA|+len]

Annotates call targets and RIP-relative memory refs with symbol names,
string contents, and float/qword values.
"""
import os, sys, struct, capstone
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pe import Bin
from funcs import Funcs
from _paths import SYMS

_syms = None
def syms():
    global _syms
    if _syms is None:
        _syms = {}
        if not os.path.exists(SYMS):
            return _syms          # no symbol dump: fall back to bare addresses
        for line in open(SYMS, encoding='utf-8', errors='replace'):
            p = line.rstrip('\n').split('\t')
            if len(p) >= 3:
                try:
                    _syms[int(p[0], 16)] = p[2]
                except ValueError:
                    pass
    return _syms


def annotate(b, ins):
    S = syms()
    if ins.mnemonic in ('call', 'jmp') and ins.op_str.startswith('0x'):
        t = int(ins.op_str, 16)
        n = S.get(t, '')
        return '  ; -> %s' % (n if n and not n.startswith('FUN_') else hex(t))
    out = []
    for op in ins.operands:
        if op.type == capstone.x86.X86_OP_MEM and op.mem.base == capstone.x86.X86_REG_RIP:
            t = ins.address + ins.size + op.mem.disp
            sec = b.sec_of_va(t)
            nm = S.get(t, '')
            extra = ''
            if sec and sec['name'] in ('.rdata', '.data'):
                d = b.read(t, 40) or b''
                z = d.split(b'\x00')[0]
                if len(z) > 2 and all(32 <= c < 127 for c in z[:32]):
                    extra = ' str=%r' % z[:48]
                elif len(d) >= 8:
                    f, = struct.unpack('<f', d[:4])
                    q, = struct.unpack('<Q', d[:8])
                    dbl, = struct.unpack('<d', d[:8])
                    extra = ' f32=%g f64=%g q=%x' % (f, dbl, q)
            out.append('  ; [%x] %s%s' % (t, nm, extra))
    return ''.join(out)


def run(lo, hi, b=None):
    b = b or Bin()
    off = b.va2off(lo)
    code = b.data[off:off + (hi - lo)]
    for ins in b.md.disasm(code, lo):
        print('%x  %-9s %-42s%s' % (ins.address, ins.mnemonic, ins.op_str, annotate(b, ins)))


if __name__ == '__main__':
    b = Bin()
    lo = int(sys.argv[1], 16)
    if len(sys.argv) > 2:
        a = sys.argv[2]
        hi = lo + int(a[1:], 0) if a.startswith('+') else int(a, 16)
    else:
        fn = Funcs(b).func_of(lo)
        hi = fn[1] if fn else lo + 0x200
    run(lo, hi, b)
