"""Helpers for static analysis of soundvoltex.dll (PE32+ x64)."""
import os, pefile, capstone, re, sys, struct

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _paths import DLL

class Bin:
    def __init__(self, path=DLL):
        self.path = path
        self.pe = pefile.PE(path, fast_load=True)
        self.base = self.pe.OPTIONAL_HEADER.ImageBase
        with open(path, 'rb') as f:
            self.data = f.read()
        self.secs = []
        for s in self.pe.sections:
            name = s.Name.rstrip(b'\x00').decode('latin1')
            self.secs.append(dict(
                name=name,
                va=self.base + s.VirtualAddress,
                vsize=s.Misc_VirtualSize,
                raw=s.PointerToRawData,
                rsize=s.SizeOfRawData,
                chars=s.Characteristics))
        self.md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_64)
        self.md.detail = True

    def sec_of_va(self, va):
        for s in self.secs:
            if s['va'] <= va < s['va'] + max(s['vsize'], s['rsize']):
                return s
        return None

    def sec_of_off(self, off):
        for s in self.secs:
            if s['raw'] <= off < s['raw'] + s['rsize']:
                return s
        return None

    def va2off(self, va):
        s = self.sec_of_va(va)
        if not s: return None
        d = va - s['va']
        if d >= s['rsize']: return None
        return s['raw'] + d

    def off2va(self, off):
        s = self.sec_of_off(off)
        if not s: return None
        return s['va'] + (off - s['raw'])

    def read(self, va, n):
        o = self.va2off(va)
        if o is None: return None
        return self.data[o:o+n]

    def cstr(self, va, maxlen=256):
        b = self.read(va, maxlen)
        if b is None: return None
        i = b.find(b'\x00')
        return b[:i if i >= 0 else maxlen].decode('latin1', 'replace')

    def find_bytes(self, pat):
        """yield VAs of all occurrences of literal bytes"""
        start = 0
        while True:
            i = self.data.find(pat, start)
            if i < 0: break
            va = self.off2va(i)
            if va is not None:
                yield va
            start = i + 1

    def text_range(self):
        for s in self.secs:
            if s['name'] == '.text':
                return s['va'], s['va'] + s['vsize'], s['raw'], s['rsize']
        return None

    def disas(self, va, n=64):
        o = self.va2off(va)
        return list(self.md.disasm(self.data[o:o+n*16], va, n))

    def func_disas(self, va, maxinsn=4000):
        """Linear disassemble until a heuristic end (ret followed by int3/align)."""
        o = self.va2off(va)
        out = []
        for ins in self.md.disasm(self.data[o:o+maxinsn*16], va, maxinsn):
            out.append(ins)
            if ins.mnemonic in ('ret',):
                # peek next byte
                no = self.va2off(ins.address + ins.size)
                if no is not None and self.data[no] in (0xCC,):
                    break
        return out


def rip_xrefs(b, targets, verbose=False):
    """Scan .text for lea/mov instructions whose rip-relative target is in `targets`.
    Returns dict target -> list of (insn_va, mnemonic, op_str)."""
    tv = set(targets)
    res = {t: [] for t in tv}
    ts, te, traw, trsize = b.text_range()
    code = b.data[traw:traw+trsize]
    for ins in b.md.disasm(code, ts):
        for op in ins.operands:
            if op.type == capstone.x86.X86_OP_MEM and op.mem.base == capstone.x86.X86_REG_RIP:
                t = ins.address + ins.size + op.mem.disp
                if t in res:
                    res[t].append((ins.address, ins.mnemonic, ins.op_str))
    return res
