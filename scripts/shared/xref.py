"""Brute-force RIP-relative xref finder: scan every 4-byte window in .text (and .rdata)
as a candidate disp32 and check whether va_of_window+4+disp32 lands on a target."""
import os, sys, struct
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pe import Bin
import capstone

def scan_rip_refs(b, targets, secnames=('.text',)):
    """returns dict target -> list of window VAs (the VA of the disp32 field)."""
    tset = set(targets)
    res = {t: [] for t in tset}
    for s in b.secs:
        if s['name'] not in secnames:
            continue
        raw, size, base = s['raw'], s['rsize'], s['va']
        data = b.data[raw:raw+size]
        for i in range(0, len(data) - 3):
            d = int.from_bytes(data[i:i+4], 'little', signed=True)
            t = base + i + 4 + d
            if t in tset:
                res[t].append(base + i)
    return res


def decode_at(b, ref_va, back=16):
    """Try to decode the instruction that contains disp32 at ref_va."""
    out = []
    for k in range(2, back):
        va = ref_va - k
        o = b.va2off(va)
        if o is None: continue
        try:
            insns = list(b.md.disasm(b.data[o:o+16], va, 1))
        except Exception:
            continue
        if not insns: continue
        ins = insns[0]
        # instruction must end exactly at ref_va+4 (disp32 last field) or +4+imm
        if ins.address + ins.size in (ref_va + 4, ref_va + 5, ref_va + 6, ref_va + 8):
            for op in ins.operands:
                if op.type == capstone.x86.X86_OP_MEM and op.mem.base == capstone.x86.X86_REG_RIP:
                    if ins.address + ins.size + op.mem.disp == (ref_va + 4 + int.from_bytes(b.read(ref_va,4),'little',signed=True)) or True:
                        out.append(ins)
    return out


if __name__ == '__main__':
    b = Bin()
    lits = [b"#FXBUTTON EFFECT INFO", b"#TAB EFFECT INFO", b"#TAB PARAM ASSIGN INFO",
            b"#REVERB EFFECT PARAM", b"#POSTEFFECT"]
    targets = {}
    for lit in lits:
        for va in b.find_bytes(lit):
            targets[va] = lit.decode()
    res = scan_rip_refs(b, list(targets))
    for t, refs in sorted(res.items()):
        print("target %x (%s): %d refs" % (t, targets[t], len(refs)))
        for r in refs[:20]:
            ins = decode_at(b, r)
            txt = "; ".join("%x: %s %s" % (i.address, i.mnemonic, i.op_str) for i in ins)
            print("   ref@%x  %s" % (r, txt))
