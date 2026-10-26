"""Assemble asm/gc_hook.s for every supported menu version and build its data block.

  python tools/build.py [--release] [-v]                        every version in MENUS
  python tools/build.py --menu 514 [code_addr] [data_addr]      one version (default: its caves)

Writes build/v<version>/gc_hook.bin (code), gc_data.bin (data), gc_hook.json (symbols).
"""
import json
import re
import struct
import sys
from pathlib import Path

from capstone import CS_ARCH_PPC, CS_MODE_32, CS_MODE_BIG_ENDIAN, Cs
from keystone import KS_ARCH_PPC, KS_MODE_BIG_ENDIAN, KS_MODE_PPC32, Ks

ROOT = Path(__file__).resolve().parent.parent

# per menu version:
#   SDK    functions the hook calls
#   SITES  call sites (addr, original bl); site "x" (or "x2", "x3", ...) calls gc_x
#   DATA   data addresses (addr, an instruction that references it, for tools/port.py)
#   CAVES  dead code used for the hook (found by tools/caves.py): (start, size). code and
#          data are patched; btns and panes are runtime-only (never patched); code2 is a
#          second, separate code cave. The data block must be 8-aligned (lfd).
# 0x80001800 is NOT usable: Dolphin's Gecko cheat handler lives there.
# v1.1's data caves (v513 0x814AE13C, v514 0x814AE238) are NOT dead: that function starts
# 3 instructions earlier, before its stwu (see docs/TECHNICAL.md, Code caves).
# v514 and v512 were mapped from v513 with tools/port.py.
MENUS = {
    513: dict(name="4.3U",
              SDK=dict(WPADProbe=0x8157AA24, KPADRead=0x81587984, PADRead=0x81576930,
                       PADReset=0x815765C0, memset=0x81330334, GetPaneRect=0x8151EE64,
                       SCGetAspect=0x81569FB4, WWWQueue=0x8136D8A8),
              SITES=dict(probe=(0x81337584, 0x482434A1), kpad=(0x813375BC, 0x482503C9),
                         rect=(0x81369844, 0x481B5621),     # GUI PaneComponent::contain
                         rect2=(0x81378CA4, 0x481A61C1)),   # its twin (HOME Menu, ...)
              DATA=dict(WMGR=(0x8169897C, 0x813F1C08),      # -> browser manager (+0x28: event queue)
                        PANEVT=(0x81671704, 0x8151E980)),   # nw4r::lyt::Pane vtable (null panes)
              CAVES=dict(code=(0x81359A70, 0x930), data=(0x8135A3A0, 0x120), btns=(0x814B4568, 0x100),
                         panes=(0x814B3A28, 0x140), code2=(0x81576484, 0x13C))),
    514: dict(name="4.3E",
              SDK=dict(WPADProbe=0x8157AB20, KPADRead=0x81587A80, PADRead=0x81576A2C,
                       PADReset=0x815766BC, memset=0x81330334, GetPaneRect=0x8151EF60,
                       SCGetAspect=0x8156A0B0, WWWQueue=0x8136D950),
              SITES=dict(probe=(0x813375F4, 0x4824352D), kpad=(0x8133762C, 0x48250455),
                         rect=(0x813698EC, 0x481B5675), rect2=(0x81378D4C, 0x481A6215)),
              DATA=dict(WMGR=(0x8169A81C, 0x813F1D04), PANEVT=(0x816719C4, 0x8151EA7C)),
              CAVES=dict(code=(0x81359B18, 0x930), data=(0x8135A448, 0x120), btns=(0x814B4664, 0x100),
                         panes=(0x814B3B24, 0x140), code2=(0x81576580, 0x13C))),
    512: dict(name="4.3J",
              SDK=dict(WPADProbe=0x815A3964, KPADRead=0x815B08C4, PADRead=0x8159F870,
                       PADReset=0x8159F500, memset=0x81330334, GetPaneRect=0x81547DA4,
                       SCGetAspect=0x81592EF4, WWWQueue=0x8136CD5C),
              SITES=dict(probe=(0x81336A64, 0x4826CF01), kpad=(0x81336A9C, 0x48279E29),
                         rect=(0x81368CF8, 0x481DF0AD), rect2=(0x81378158, 0x481CFC4D)),
              DATA=dict(WMGR=(0x816C807C, 0x813F0F58), PANEVT=(0x816A170C, 0x815478C0)),
              CAVES=dict(code=(0x81358F30, 0x930), data=(0x81359860, 0x120), btns=(0x814DD4A8, 0x100),
                         panes=(0x814DC968, 0x140), code2=(0x8159F3C4, 0x13C))),
}

# tuning
DEADZONE = 12
SPEED = 4.5e-6          # per frame, times (|stick| - deadzone)^2  (~0.035 at full tilt)
LIMX, LIMY = 1.12, 1.0  # 1.12 * K = 306: the cursor can reach the right edge
HOLD = 10               # frames to keep the last GC status when PADRead has no new data
K, KWIDE = 273.6, 273.6 * 1.15  # layout units per KPAD pos unit (4:3, 16:9): KPADGetProjectionPos
XLIM, YLIM = 290.0, 230.0       # centers outside this aren't on screen (4:3 layout); also drops
                                # the edge panes of buttons that run off screen (Mail's right half)
MINSZ = 24.0                    # panes smaller than this on a side are decorations
MAXW, MAXH = 400.0, 300.0       # panes this big (local units) are backdrops, not buttons
STRIP = 4.0                     # panes thinner than 1:STRIP are edge hit areas, not buttons
DEDUP = 40.0                    # centers closer than this are the same button (several panes)
MINFWD = 20.0                   # D-pad: ignore buttons less than this far ahead (layout units)
LATW = 3.0                      # D-pad: sideways distance counts this much more than forward
NEAR = 48.0                     # D-pad: within this of a button = on it (else any direction
                                # with nothing that way jumps to the nearest button)
CONE = 1.8                      # D-pad: only buttons with sideways <= CONE * forward (~60 degrees)
START = (-192.0, 145.0)         # cursor at boot, layout units: the top-left channel tile
DRPT1, DRPT2 = 24, 8            # D-pad repeat: first after 24 frames, then every 8
FLAGS = {"LED", "DEBUG"}  # debug build: disc slot LED + call counters + TEST input; --release drops them

# data block layout
OFF = dict(CX=0x00, CY=0x04, PREV=0x08, RPT=0x0C, OVR=0x10, PCNT=0x14, MAGIC=0x18, TMP=0x20, ZERO=0x28,
           HALF=0x2C, THREEHALF=0x30, SPEED=0x34, LIMX=0x38, LIMY=0x3C, PADBUF=0x40, BTNTAB=0x70, TEST=0x8A, KCNT=0x8C, LAST=0x90, MISS=0x9C, GOOD=0xA0,
           NBTN=0xA4, DPREV=0xA8, DRPT=0xAC, K=0xB0, KWIDE=0xB4, XLIM=0xB8, YLIM=0xBC, MINFWD=0xC0,
           LATW=0xC4, BIG=0xC8, CONE=0xCC, DIRTAB=0xD0, MAXW=0xF0, MAXH=0xF4, DEDUP=0xF8, STRIP=0xFC,
           HTMLM=0x100, SAVEX=0x104, SAVEY=0x108, WWWTAB=0x10C, NULLW=0x110, NULLH=0x114, MINSZ=0x118, NEAR2=0x11C)
DATA_SIZE = 0x120

# GC PAD bit i -> Wii Remote bits
BTNTAB = [
    0x0000,  # 0  D-left   -> (button selection, gc_dpad)
    0x0000,  # 1  D-right
    0x0000,  # 2  D-down
    0x0000,  # 3  D-up
    0x0010,  # 4  Z        -> +
    0x0010,  # 5  R        -> +
    0x1000,  # 6  L        -> -
    0x0000,  # 7  (unused)
    0x0800,  # 8  A        -> A
    0x0400,  # 9  B        -> B
    0x0200,  # 10 X        -> 1
    0x0100,  # 11 Y        -> 2
    0x8000,  # 12 Start    -> HOME
]


def data_block():
    d = bytearray(DATA_SIZE)
    struct.pack_into(">Q", d, OFF["MAGIC"], 0x4330000080000000)
    struct.pack_into(">2f", d, OFF["CX"], START[0] / K, -START[1] / K)
    for k, v in (("HALF", 0.5), ("THREEHALF", 1.5), ("SPEED", SPEED), ("LIMX", LIMX), ("LIMY", LIMY),
                 ("K", K), ("KWIDE", KWIDE), ("XLIM", XLIM), ("YLIM", YLIM), ("MINFWD", MINFWD),
                 ("LATW", LATW), ("BIG", 1e30), ("MAXW", MAXW), ("MAXH", MAXH), ("DEDUP", DEDUP),
                 ("STRIP", STRIP), ("CONE", CONE), ("NULLW", 30.0), ("NULLH", 40.0),
                 ("MINSZ", MINSZ), ("NEAR2", NEAR ** 2)):
        struct.pack_into(">f", d, OFF[k], v)
    # GC D-pad bit i -> direction in layout space (y up): left, right, down, up
    struct.pack_into(">8f", d, OFF["DIRTAB"], -1, 0, 1, 0, 0, -1, 0, 1)
    # GC D-pad bit i -> WPAD bit the menu maps to that browser arrow key (it assumes a
    # sideways remote): left -> WPAD up, right -> down, down -> left, up -> right
    struct.pack_into(">4B", d, OFF["WWWTAB"], 0x08, 0x04, 0x01, 0x02)
    struct.pack_into(">13H", d, OFF["BTNTAB"], *BTNTAB)
    return bytes(d)


def read_sections():
    """asm source -> {section: [lines]}, applying @if/@endif and stripping comments."""
    secs, cur, keep = {"code": []}, "code", [True]
    for line in (ROOT / "asm" / "gc_hook.s").read_text().splitlines():
        if line.startswith("@section "):
            cur = line.split()[1]
            secs.setdefault(cur, [])
            continue
        if line.startswith("@if "):
            keep.append(keep[-1] and line[4:].strip() in FLAGS)
            continue
        if line.startswith("@endif"):
            keep.pop()
            continue
        line = line.split("#")[0].rstrip()
        if keep[-1] and line.strip():
            secs[cur].append(line)
    return secs


def is_label(line):
    return line.endswith(":") and not line.startswith(" ")


def hook(site):
    """call site name -> the hook it calls: probe -> gc_probe, rect2 -> gc_rect"""
    return "gc_" + site.rstrip("0123456789")


def maxbtn(menu):
    caves = MENUS[menu]["CAVES"]
    return min(caves["btns"][1] // 8, caves["panes"][1] // 4)   # (x, y) f32 pairs / Pane *


def assemble(menu, code_addr, data_addr):
    """-> ({section: bytes}, {label: addr}). code2 goes in its own cave."""
    SDK, caves = MENUS[menu]["SDK"], MENUS[menu]["CAVES"]
    bases = dict(code=code_addr, code2=caves["code2"][0])
    secs = read_sections()
    # label addresses: every non-label line is exactly one instruction
    syms = {}
    for name, lines in secs.items():
        n = 0
        for line in lines:
            if is_label(line):
                syms[line[:-1]] = bases[name] + 4 * n
            else:
                n += 1
    subs = {k: hex(v) for k, v in {**SDK, **OFF, **syms}.items()}
    data = {k: v[0] for k, v in MENUS[menu]["DATA"].items()}
    for name, addr in (("DATA", data_addr), ("BTNS", caves["btns"][0]), ("PANES", caves["panes"][0]),
                       *data.items()):
        lo = addr & 0xFFFF
        lo = lo - 0x10000 if lo & 0x8000 else lo
        subs.update({name + "_HA": hex(((addr - lo) >> 16) & 0xFFFF), name + "_LO": str(lo)})
    subs.update(DEADZONE=str(DEADZONE), HOLD=str(HOLD), MAXBTN=str(maxbtn(menu)), DRPT1=str(DRPT1),
                DRPT2=str(DRPT2))
    ks = Ks(KS_ARCH_PPC, KS_MODE_PPC32 | KS_MODE_BIG_ENDIAN)
    md = Cs(CS_ARCH_PPC, CS_MODE_32 | CS_MODE_BIG_ENDIAN)
    out = {}
    for name, lines in secs.items():
        src = [re.sub(r"\b[rf](\d+)\b", r"\1", re.sub(r"\{(\w+)\}", lambda m: subs[m.group(1)], l))
               for l in lines]
        code = bytearray(ks.asm("\n".join(src), bases[name])[0]) if src else bytearray()
        insns = [l for l in src if not is_label(l)]
        assert len(code) == 4 * len(insns), f"{name}: instruction count mismatch"
        # keystone mis-encodes some branches to absolute addresses, so encode b/bl to a number
        # ourselves and verify every branch target against the source
        for i, line in enumerate(insns):
            m = BRANCH.match(line)
            if not m:
                continue
            pc, op, tgt = bases[name] + 4 * i, m.group(1), m.group(2)
            want = syms[tgt] if tgt in syms else int(tgt, 0)
            if op in ("b", "bl"):
                struct.pack_into(">I", code, 4 * i, branch(pc, want, link=op == "bl"))
            ins = next(md.disasm(bytes(code[4 * i:4 * i + 4]), pc))
            got = int(ins.op_str.split()[-1].rstrip(","), 0)
            assert got == want, f"{name} {pc:#x} '{line.strip()}': encodes {got:#x}, want {want:#x}"
        out[name] = bytes(code)
    return out, syms


BRANCH = re.compile(r"^\s*(b|bl|beq|bne|blt|bgt|ble|bge|bdnz)\s+(?:\d+,\s*)?(\w+)\s*$")


def branch(frm, to, link=True):
    off = to - frm
    assert -0x2000000 <= off < 0x2000000 and not off & 3
    return 0x48000000 | (off & 0x03FFFFFC) | int(link)


def bl(frm, to):
    return branch(frm, to)


def build(menu, code_addr=None, data_addr=None, verbose=False):
    caves = MENUS[menu]["CAVES"]
    code_addr = caves["code"][0] if code_addr is None else code_addr
    data_addr = caves["data"][0] if data_addr is None else data_addr
    assert data_addr % 8 == 0, f"data block {data_addr:#x} must be 8-aligned (lfd)"
    secs, syms = assemble(menu, code_addr, data_addr)
    code, code2 = secs["code"], secs.get("code2", b"")
    data = data_block()
    assert code_addr + len(code) <= data_addr or data_addr + len(data) <= code_addr, "code overlaps data"
    for name, size in (("code", len(code)), ("data", len(data))):
        start, room = caves[name]
        addr = code_addr if name == "code" else data_addr
        if addr == start:
            assert size <= room, f"{name} ({size:#x}) does not fit its cave ({room:#x})"
    assert len(code2) <= caves["code2"][1], f"code2 ({len(code2):#x}) does not fit its cave"
    out = ROOT / "build" / f"v{menu}"
    out.mkdir(parents=True, exist_ok=True)
    (out / "gc_hook.bin").write_bytes(code)
    (out / "gc_data.bin").write_bytes(data)
    (out / "gc_code2.bin").write_bytes(code2)
    info = dict(menu=menu, name=MENUS[menu]["name"], code_addr=code_addr, data_addr=data_addr,
                code_size=len(code), data_size=len(data), flags=sorted(FLAGS), syms=syms,
                extra=dict(code2=dict(addr=caves["code2"][0], size=len(code2))), caves=caves,
                sites={k: dict(addr=a, orig=o, new=bl(a, syms[hook(k)]), hook=hook(k))
                       for k, (a, o) in MENUS[menu]["SITES"].items()})
    (out / "gc_hook.json").write_text(json.dumps(info, indent=1))
    print(f"v{menu}: code {code_addr:#x} size {len(code):#x}, data {data_addr:#x} size {len(data):#x},"
          f" code2 {caves['code2'][0]:#x} size {len(code2):#x}, flags {sorted(FLAGS)}")
    print({k: hex(v) for k, v in syms.items()})
    if verbose:
        md = Cs(CS_ARCH_PPC, CS_MODE_32 | CS_MODE_BIG_ENDIAN)
        for base, blob in ((code_addr, code), (caves["code2"][0], code2)):
            for i in md.disasm(blob, base):
                print(f"{i.address:08x}: {i.mnemonic:9} {i.op_str}")


if __name__ == "__main__":
    argv = sys.argv[1:]
    menus = list(MENUS)
    if "--menu" in argv:
        i = argv.index("--menu")
        menus = [int(argv[i + 1])]
        del argv[i:i + 2]
    args = [int(a, 0) for a in argv if not a.startswith(("-", "+"))]
    assert not args or len(menus) == 1, "custom addresses need --menu"
    if "--release" in argv:
        FLAGS.clear()
    FLAGS.update(a[1:] for a in argv if a.startswith("+"))   # +NAME turns on @if NAME
    for menu in menus:
        build(menu, *args, verbose="-v" in argv)
