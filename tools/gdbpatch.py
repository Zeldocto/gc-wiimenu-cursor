"""Apply a System Menu Gecko INI block to Dolphin through its GDB RSP stub.

Linux replacement for ``mkhack.py apply`` (which uses Windows-only dolmem.py).

Run while Dolphin is stopped at the System Menu's first instruction:

    python tools/gdbpatch.py --menu 518 --dry-run
    python tools/gdbpatch.py --menu 518

The GDB stub sees physical MEM1 addresses before the menu enables the MMU,
so each DOL virtual address is translated with ``addr & 0x3fffffff``.
The helper preflights every patch against the stock DOL before writing any of
it, then reads every write back. It never sends a continue/resume command.
"""
from __future__ import annotations

import argparse
import re
import socket
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))

from hackini import parse  # noqa: E402
from ppc import Dol  # noqa: E402

DEFAULT_INI = ROOT / "build" / "gc_cursor_hack.ini"


class RSPError(RuntimeError):
    pass


class GDBRemote:
    """Small acknowledged-mode GDB Remote Serial Protocol client."""

    def __init__(self, host: str, port: int, timeout: float = 5.0):
        self.sock = socket.create_connection((host, port), timeout=timeout)
        self.sock.settimeout(timeout)
        self.packet_size = 0x400
        self._pending = bytearray()

    def close(self):
        try:
            self.sock.close()
        except OSError:
            pass

    def _read_byte(self) -> bytes:
        b = self.sock.recv(1)
        if not b:
            raise RSPError("Dolphin closed the GDB connection")
        return b

    def _read_packet(self) -> bytes:
        # Ignore acknowledgements and any asynchronous bytes until '$'.
        while True:
            b = self._read_byte()
            if b == b"$":
                break
        payload = bytearray()
        while True:
            b = self._read_byte()
            if b == b"#":
                break
            payload += b
        checksum = self._read_byte() + self._read_byte()
        try:
            received = int(checksum, 16)
        except ValueError as exc:
            self.sock.sendall(b"-")
            raise RSPError("malformed checksum in GDB response") from exc
        if (sum(payload) & 0xFF) != received:
            self.sock.sendall(b"-")
            raise RSPError("bad checksum in GDB response")
        self.sock.sendall(b"+")
        return bytes(payload)

    def request(self, payload: bytes) -> bytes:
        checksum = sum(payload) & 0xFF
        self.sock.sendall(b"$" + payload + f"#{checksum:02x}".encode("ascii"))
        # Standard RSP acknowledged mode: wait for '+' before the reply.
        while True:
            b = self._read_byte()
            if b == b"+":
                break
            if b == b"-":
                self.sock.sendall(b"$" + payload + f"#{checksum:02x}".encode("ascii"))
                continue
            if b == b"$":
                # Some stubs omit the request ACK. Preserve this early reply.
                rest = bytearray()
                while True:
                    c = self._read_byte()
                    if c == b"#":
                        break
                    rest += c
                cs = self._read_byte() + self._read_byte()
                if (sum(rest) & 0xFF) != int(cs, 16):
                    self.sock.sendall(b"-")
                    raise RSPError("bad checksum in GDB response")
                self.sock.sendall(b"+")
                return bytes(rest)
        return self._read_packet()

    def connect_and_stop_check(self):
        supported = self.request(b"qSupported:multiprocess+;qXfer:features:read+")
        match = re.search(rb"(?:^|;)PacketSize=([0-9a-fA-F]+)", supported)
        if match:
            self.packet_size = max(0x100, int(match.group(1), 16))
        stop = self.request(b"?")
        if not stop.startswith((b"T", b"S", b"W", b"X")):
            raise RSPError(f"unexpected stop-status reply: {stop!r}")
        print(f"GDB stub connected; target stop reply: {stop.decode('ascii', 'replace')}")

    @staticmethod
    def _phys(addr: int) -> int:
        return addr & 0x3FFFFFFF

    def read_memory(self, addr: int, size: int) -> bytes:
        out = bytearray()
        # Small chunks avoid depending on a particular Dolphin PacketSize.
        chunk_max = min(0x100, max(1, (self.packet_size - 32) // 2))
        while len(out) < size:
            n = min(chunk_max, size - len(out))
            paddr = self._phys(addr + len(out))
            reply = self.request(f"m{paddr:x},{n:x}".encode("ascii"))
            # Memory data is returned as ASCII hex, so a legitimate read can
            # begin with the character E (for example bytes ED 06 ...).  An
            # RSP error reply is exactly E followed by a two-digit error code.
            if re.fullmatch(rb"E[0-9a-fA-F]{2}", reply):
                raise RSPError(f"memory read failed at physical {paddr:#x}: {reply!r}")
            try:
                data = bytes.fromhex(reply.decode("ascii"))
            except (ValueError, UnicodeDecodeError) as exc:
                raise RSPError(f"invalid memory-read reply at {paddr:#x}: {reply!r}") from exc
            if len(data) != n:
                raise RSPError(f"short memory read at {paddr:#x}: wanted {n:#x}, got {len(data):#x}")
            out += data
        return bytes(out)

    def write_memory(self, addr: int, data: bytes):
        chunk_max = min(0x100, max(1, (self.packet_size - 32) // 2))
        done = 0
        while done < len(data):
            chunk = data[done:done + chunk_max]
            paddr = self._phys(addr + done)
            packet = f"M{paddr:x},{len(chunk):x}:".encode("ascii") + chunk.hex().encode("ascii")
            reply = self.request(packet)
            if reply != b"OK":
                raise RSPError(f"memory write failed at physical {paddr:#x}: {reply!r}")
            done += len(chunk)


def choose_hack(ini: Path, menu: int):
    hacks = parse(ini.read_text(encoding="latin-1"))
    matches = [h for h in hacks if h["min"] <= menu <= h["max"]]
    if len(matches) != 1:
        raise SystemExit(f"expected exactly one INI block for v{menu}; found {len(matches)} in {ini}")
    hack = matches[0]
    if not hack["patches"]:
        raise SystemExit(f"the v{menu} INI block has no patches")
    return hack


def prepare_patches(hack, dol: Dol):
    patches = []
    occupied = []
    for i, patch in enumerate(hack["patches"], 1):
        if "offset" not in patch:
            raise SystemExit(f"patch {i}: hash patches are not supported; this hack should use offset= only")
        addr, data = patch["offset"], patch["patch"]
        if not data:
            raise SystemExit(f"patch {i} at {addr:#x} has no data")
        if addr & 3 or len(data) & 3:
            raise SystemExit(f"patch {i} at {addr:#x} is not word-aligned")
        try:
            stock = dol.read(addr, len(data))
        except ValueError as exc:
            raise SystemExit(f"patch {i} at {addr:#x} is outside the selected DOL sections") from exc
        for start, end in occupied:
            if addr < end and start < addr + len(data):
                raise SystemExit(f"patch {i} at {addr:#x} overlaps another patch")
        occupied.append((addr, addr + len(data)))
        patches.append((addr, data, stock))
    return patches


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--menu", type=int, required=True, help="System Menu version, e.g. 518")
    ap.add_argument("--ini", type=Path, default=DEFAULT_INI, help=f"generated Gecko INI (default: {DEFAULT_INI})")
    ap.add_argument("--host", default="127.0.0.1", help="Dolphin GDB stub host (default: 127.0.0.1)")
    ap.add_argument("--port", type=int, default=55000, help="Dolphin GDBPort (default: 55000)")
    ap.add_argument("--timeout", type=float, default=5.0, help="socket timeout in seconds")
    ap.add_argument("--dry-run", action="store_true", help="verify all original bytes but do not write")
    args = ap.parse_args()

    if not args.ini.is_file():
        raise SystemExit(f"INI not found: {args.ini}\nRun: python tools/build.py --menu {args.menu} && python tools/mkhack.py")
    dol_path = ROOT / "bin" / f"sysmenu_v{args.menu}.dol"
    if not dol_path.is_file():
        raise SystemExit(f"stock DOL not found: {dol_path}; provide your own matching v{args.menu} DOL")

    hack = choose_hack(args.ini, args.menu)
    dol = Dol(dol_path)
    patches = prepare_patches(hack, dol)
    total = sum(len(data) for _, data, _ in patches)
    print(f"Selected [{hack['name']}] for System Menu v{args.menu}: {len(patches)} patches, {total:#x} bytes")
    print("Using physical MEM1 addresses (virtual DOL address & 0x3fffffff).")

    rsp = None
    try:
        rsp = GDBRemote(args.host, args.port, args.timeout)
        rsp.connect_and_stop_check()

        # Preflight every patch before changing RAM. Accept stock or already-patched bytes.
        states = []
        for i, (addr, data, stock) in enumerate(patches, 1):
            current = rsp.read_memory(addr, len(data))
            if current == stock:
                state = "stock"
            elif current == data:
                state = "already patched"
            else:
                mismatch = next(j for j, (a, b) in enumerate(zip(current, stock)) if a != b)
                raise SystemExit(
                    f"REFUSING TO PATCH: patch {i} at {addr:#010x} differs from both stock DOL and hack; "
                    f"first mismatch +{mismatch:#x} (RAM={current[mismatch]:02x}, stock={stock[mismatch]:02x}, "
                    f"patch={data[mismatch]:02x}). Is the menu paused at its first instruction?"
                )
            states.append(state)
            print(f"  {i}/{len(patches)} {addr:#010x} {len(data):#05x} bytes: {state}")

        pending = [(a, d) for (a, d, _), state in zip(patches, states) if state == "stock"]
        if args.dry_run:
            print(f"DRY RUN OK: all {len(patches)} patches match stock or are already applied; nothing written.")
            return
        if not pending:
            print("All patches are already installed; nothing to write.")
            return

        print(f"Writing {len(pending)} patch blocks...")
        for addr, data in pending:
            rsp.write_memory(addr, data)
            if rsp.read_memory(addr, len(data)) != data:
                raise RSPError(f"read-back verification failed at {addr:#010x}")
            print(f"  verified {addr:#010x} ({len(data):#x} bytes)")
        print("PATCH COMPLETE. Dolphin has NOT been resumed; unpause it in Dolphin/GDB when ready.")
    finally:
        if rsp is not None:
            rsp.close()


if __name__ == "__main__":
    try:
        main()
    except (OSError, RSPError) as exc:
        raise SystemExit(f"gdbpatch: {exc}")
