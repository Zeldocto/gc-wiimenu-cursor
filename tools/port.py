"""Find the v513 addresses used by the hook in another menu DOL.

  python tools/port.py bin/sysmenu_v514.dol

The results are starting points for a new MENUS entry in tools/build.py: check the call
sites with ppc.py, rerun caves.py on the new DOL, and keep the data cave 8-aligned.
DATA addresses are found through an instruction that references them: an r13-relative
load/store (r13 read from the new DOL's startup code) or the addi of a lis/addi pair.

Each address is located by its surrounding code: a window of instructions with every
address-dependent field masked (branch offsets, lis/addi/load/store immediates that aren't
stack offsets). The window grows until it matches exactly one place in the other DOL.
"""
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build import MENUS
from ppc import Dol

SDK, SITES, CAVES, DATA = (MENUS[513][k] for k in ("SDK", "SITES", "CAVES", "DATA"))


MEMOPS = set(range(32, 56)) | {14, 15, 24, 25}   # loads/stores, addi, addis, ori, oris


def mask(w):
    op = w >> 26
    if op == 18:                                    # b/bl
        return w & 0xFC000003
    if op in MEMOPS and (w >> 16) & 31 != 1:        # keep r1 (stack) offsets
        return w & 0xFFFF0000
    return w


def masked(d):
    a0, o, s = max(d.sections, key=lambda x: x[2])  # the big code+data section
    ws = struct.unpack(f">{s // 4}I", d.raw[o:o + s])
    return a0, b"".join(struct.pack(">I", mask(w)) for w in ws)


def find(src, dst, addr):
    """-> (addr in dst, window) for the unique match, or (None, last hit count)."""
    (sa, sb), (da, db) = src, dst
    i = (addr - sa) // 4 * 4
    for half in (8, 16, 32, 64, 128):
        lo, hi = max(0, i - 4 * half), min(len(sb), i + 4 * half)
        pat = sb[lo:hi]
        hits, p = [], db.find(pat)
        while p != -1 and len(hits) < 2:
            if p % 4 == 0:
                hits.append(p)
            p = db.find(pat, p + 1)
        if len(hits) == 1:
            return da + hits[0] + (i - lo), half
        if not hits:
            return None, 0
    return None, len(hits)


def s16(w):
    return w & 0xFFFF if not w & 0x8000 else (w & 0xFFFF) - 0x10000


def sda_base(d):
    """_SDA_BASE_ (r13), from the startup code's `lis r13, hi` + `ori r13, r13, lo`"""
    prev = None
    for a, w in d.words():
        if prev is not None and w >> 16 == 0x61AD:  # ori r13, r13, lo
            return prev << 16 | (w & 0xFFFF)
        prev = w & 0xFFFF if w >> 16 == 0x3DA0 else None  # lis r13, hi
    raise ValueError("no lis/ori r13")


def ref_value(d, addr, r13):
    """address an instruction refers to: d(r13), or the addi of a lis/addi pair"""
    w = d.word(addr)
    ra = (w >> 16) & 31
    if w >> 26 in MEMOPS - {14, 15, 24, 25} and ra == 13:
        return (r13 + s16(w)) & 0xFFFFFFFF
    assert w >> 26 == 14, f"{addr:#x}: not d(r13) or addi"
    for back in range(4, 0x80, 4):                  # the matching lis (often scheduled earlier)
        v = d.word(addr - back)
        if v >> 26 == 15 and (v >> 21) & 31 == ra and (v >> 16) & 31 == 0:
            return (((v & 0xFFFF) << 16) + s16(w)) & 0xFFFFFFFF
    raise ValueError(f"{addr:#x}: no lis for r{ra}")


def main(other):
    a, b = Dol(), Dol(other)
    src, dst = masked(a), masked(b)
    r13a, r13b = sda_base(a), sda_base(b)
    print(f"{'r13':12} {r13a:#010x} -> {r13b:#010x}")
    for name, (value, ref) in DATA.items():
        new, n = find(src, dst, ref)
        if new is None:
            print(f"{name:12} {value:#010x} -> NOT FOUND (reference {ref:#x}: {n} hits)")
            continue
        assert ref_value(a, ref, r13a) == value, f"{name}: the v513 reference doesn't give {value:#x}"
        print(f"{name:12} {value:#010x} -> {ref_value(b, new, r13b):#010x}  (via {ref:#x} -> {new:#x})")
    want = {**SDK, **{f"site_{k}": v[0] for k, v in SITES.items()},
            **{f"cave_{k}": v[0] for k, v in CAVES.items()}}
    for name, addr in want.items():
        new, n = find(src, dst, addr)
        if new is None:
            print(f"{name:12} {addr:#010x} -> NOT FOUND ({n} hits)")
            continue
        same = a.read(addr, 16) == b.read(new, 16)
        word = f", bl {b.word(new):#010x}" if name.startswith("site_") else ""
        print(f"{name:12} {addr:#010x} -> {new:#010x}  (shift {new - addr:+#x}, window +-{n}"
              f"{', identical bytes' if same else ''}{word})")


if __name__ == "__main__":
    main(sys.argv[1])
