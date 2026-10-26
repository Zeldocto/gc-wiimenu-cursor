# Technical notes: System Menu 4.3U (v513), 4.3E (v514) and 4.3J (v512)

Everything below is for the v513 menu DOL (SHA-1 `26116613f624061ba99c8d1a299aaa6efa85670d`) unless it says otherwise. Addresses are virtual (`0x8xxxxxxx`). The 4.3E and 4.3J addresses are in [System Menu 4.3E (v514)](#system-menu-43e-v514) and [System Menu 4.3J (v512)](#system-menu-43j-v512).

## Menu DOL layout

- Title `00000001-00000002`, TMD version 513, boot content index 8 (`00000098.app`, or `10000098.app` when Priiloader is installed).
- T0 `0x80003400`, size `0x400`: BAT setup stub (entry `0x00003400`).
- D0 `0x8132FFE0`-`0x816DFFE0` (size `0x3B0000`, file offset `0x500`): all of the menu's code and data.
- `r13` (`_SDA_BASE_`) = `0x8169E040`, `r2` (`_SDA2_BASE_`) = `0x8169C400`, both set at `0x81330124`.
- SDK: `release build: Apr 20 2010 (0x4199_60831)` for PAD, WPAD, KPAD, SI and OS.

## SDK functions

Identified by the version strings each library registers with `OSRegisterVersion` (`0x8152C7D8`) and by call patterns.

| Function | Address | Notes |
|---|---|---|
| `PADInit` | `0x815767D4` | registers `<< RVL_SDK - PAD`, ends with `PADReset(0xF0000000)` |
| `PADReset` | `0x815765C0` | `(u32 chanMask)` |
| `PADRead` | `0x81576930` | `(PADStatus[4])`, returns per-port err at `+0xA` |
| `WPADProbe` | `0x8157AA24` | `(chan, u32 *type)`; -1 = no controller |
| `KPADInit` | `0x815880B0` | |
| `KPADRead` | `0x81587984` | `(chan, KPADStatus *buf, len)`; internal state `chan * 0x528` |
| `KPADSetBtnRepeat` | `0x815856B0` | called every frame with (0.5 s, 0.1 s) |
| `memset` | `0x81330334` | |
| `OSReport` | `0x8152E6A0` | |
| `PSMTXInverse` | `0x81540F5C` | |
| `nw4r::lyt::Pane::GetPaneRect` | `0x8151EE64` | `(Rect *out, Pane *, DrawInfo *)`, local rect: left, top, right, bottom |
| `SCGetAspectRatio` | `0x81569FB4` | 1 = 16:9 |

## How the menu uses the GameCube pad

`PADInit` and `PADRead` are each called **once**, in the boot function `0x81379D38` (`0x8137A7C8` and `0x8137AAA4`). That read is the recovery-mode check: port 4, `err == 0` and `(buttons & 0xF) == 0xF`, i.e. **all four D-pad directions held**. The pad library is initialized, but nothing reads it after boot.

`PADRead` error codes: `-1` no controller, `-2` not ready, `-3` transfer (no new response from `SIGetResponse`, at `0x81576B20`). A pad that wasn't present at boot is only detected after the caller runs `PADReset` on its port, which the menu never does.

`PADStatus` (12 bytes): `+0 u16 buttons, +2 s8 stickX, +3 s8 stickY, +4 s8 substickX/Y, +6 u8 triggerL/R, +8 u8 analogA/B, +A s8 err`.

## Controller manager update: `0x81337500` (runs every frame)

`this` = r24. For each channel 0..3:

1. Sensor-bar setting → `0x815858EC(chan, f1)`.
2. `r = WPADProbe(chan, &type)` at **`0x81337584`**. If `r == -1`, `r < -3` or `r >= 1`: `KPADRead` at `0x8133777C`, then `this[chan] = NULL`, which means no controller object and no pointer.
3. Otherwise `n = KPADRead(chan, this + 0xD8 + chan*0x84, 1)` at **`0x813375BC`**. If `n > 0`, `wpad_err != -4` and `type != 0xFD`, a controller object is created or kept at `this + 0x10 + chan*0x30`, chosen by `type`:
   - `0` (core), `0xFB`, `0xFC`, `0xFF`: Wii Remote object (vtable `0x8163499C`)
   - `1`: Nunchuk object (vtable `0x81634910`)
   - `2`: Classic Controller object
   - `n == 0` for 60 frames: disconnect + NULL. `n < 0`: NULL.
4. `KPADSetBtnRepeat(chan, 0.5, 0.1)`.

Afterwards, each non-NULL object's `vtable[0x88]` runs. It reads the KPAD buffer through small getters (for example "is A held"). The HOME Menu reads the same objects.

## KPADStatus (0x84 bytes), confirmed by RAM dumps

| Offset | Field |
|---|---|
| `+0x00` | hold (u32) |
| `+0x04` | trigger |
| `+0x08` | release |
| `+0x0C..+0x14` | acc x/y/z (at rest: 0, -1, 0) |
| `+0x18` | acc_value (1.0) |
| `+0x20/+0x24` | pos x/y, about -1..1 (overshoots slightly); **+inf when not pointing** |
| `+0x28/+0x2C` | vec (pos delta) |
| `+0x30` | speed (length of vec) |
| `+0x34` | horizon (1.0, ~0) |
| `+0x48` | dist (~1.95) |
| `+0x54` | acc_vertical |
| `+0x5C` | dev_type (u8) |
| `+0x5D` | wpad_err (s8) |
| `+0x5E` | dpd_valid_fg (s8): 2 while pointing |
| `+0x5F` | data_format (u8): 2 = core+acc+dpd, 5 = Nunchuk+acc+dpd |
| `+0x60...` | extension data (Nunchuk stick, acc) |

Buttons use standard WPAD bits: Left `0x1`, Right `0x2`, Down `0x4`, Up `0x8`, + `0x10`, 2 `0x100`, 1 `0x200`, B `0x400`, A `0x800`, − `0x1000`, HOME `0x8000`. **`0x80000000` is KPAD's repeat bit**: it's set on the press frame, then after 0.5 s, then every 0.1 s while held. trigger/release are set for one frame.

## The hook (`asm/gc_hook.s`)

- `0x81337584` `bl WPADProbe` → `bl gc_probe`
- `0x813375BC` `bl KPADRead` → `bl gc_kpad`
- `0x81369844` `bl GetPaneRect` → `bl gc_rect` (in `PaneComponent::contain`, see [D-pad button selection](#d-pad-button-selection))
- `0x81378CA4` `bl GetPaneRect` → `bl gc_rect` (its twin in the second GUI library)

**gc_probe** (channel 0 only): calls the real `WPADProbe`. If the result is `-1`:

1. `PADRead` all ports, and `PADReset` every port that reports `-1` (hot-plug).
2. Take the first port with `err == 0` and copy its status to `LAST`. If no port is fresh this frame, keep using `LAST` for up to `HOLD` (10) frames, which covers `-3` "no new data".
3. If a pad was found, return 0 with `type = 0` (core) and set `OVR`.

**gc_kpad** (channel 0 only): calls the real `KPADRead`. If `OVR` is set, it `memset`s the buffer and fills it from `LAST`:

- buttons through `BTNTAB` (GC bit i → WPAD bits), with trigger = `now & ~prev`, release = `prev & ~now`, and the repeat bit (30 frames, then every 6)
- the stick moves a persistent cursor: quadratic response past the dead zone, clamped to ±`LIMX`/`LIMY`
- vec/speed from the cursor delta (`frsqrte` + one Newton step)
- fixed "remote at rest" values, `dpd_valid = 2`, `data_format = 2`
- it returns 1

A real Wii Remote always wins: the GC pad is only used when `WPADProbe` says no controller.

## D-pad button selection

### How the menu hit-tests buttons

The menu (and the HOME Menu, which runs on a second copy of the same library) uses a small GUI library on top of NW4R layouts. Every frame, `Manager::update` (`0x81368EA4`) calls each component's `update` (`0x81368918`, vtable slot `0x4C`), which calls `isTriggerTarget` (slot `0x5C`) and then `PaneComponent::contain(x, y)` (slot `0x68`, `0x8136979C`; twin `0x81378BFC`). `contain` inverts the bounding pane's global matrix (`Pane + 0x84`), calls `GetPaneRect` and checks the point. The pointer comes from the controller object's vtable `0x58` (`0x81336308`): KPAD pos × 273.6 in layout units (× 1.15 more on 16:9), clamped to the screen ±100, with y negated by the caller (layout y points up).

So every clickable button on screen passes through `GetPaneRect` once per frame. **gc_rect** replaces that call: it calls the real `GetPaneRect`, then (while OVR is set) records the button's center in layout space, `M * ((l+r)/2, (t+b)/2)` with `M` = `Pane + 0x84`, into BTNS and its pane into PANES. It skips:

- centers off screen (|x| ≥ 290, |y| ≥ 230; also drops the far half of Mail)
- panes with global alpha 0 (`Pane + 0xCE`)
- plain null panes (`nw4r::lyt::Pane`'s own vtable, `PANEVT`) left at the default 30×40: group nodes such as dialog roots, the clock and the HOME Menu's groups (their buttons are children)
- panes under 24 or over 400×300 local units, and strips thinner than 1:4 (frame corners, edge hit areas, backdrops)
- panes named `BarW*` (the "Wii" title bar) and `Fre_*` (the channel preview frame): trigger targets that do nothing
- panes whose ancestor (`Pane + 0xC`) is already recorded, and centers within 40 of a recorded one: a button is usually several panes

NW4R pane fields used: `+0x0C` parent, `+0x4C` size, `+0x84` global matrix (3×4), `+0xB4` name, `+0xCC` base position, `+0xCD` alpha, `+0xCE` global alpha, `+0xCF` flags.

**gc_dpad** (called by gc_kpad every frame, before the stick) clears the list for the next frame and, on a D-pad press or repeat (24 frames, then every 8), scores each recorded center relative to the cursor: forward distance + 3 × sideways distance, among buttons at least 20 ahead and within a cone (sideways ≤ 1.8 × forward). The cursor jumps to the best one. If nothing is in that direction and the cursor isn't on a button (none within 48), it jumps to the nearest button instead, which handles newly opened screens. The D-pad no longer sends Wii Remote D-pad bits.

### Browser screens

Wii System Settings (and the first-time setup) are HTML pages (`/html/US2/iplsetting.ash` in content `00000097.app`, LZ77-compressed files in a U8 archive) drawn by an embedded Opera browser module loaded at runtime. The browser's API is reached through a pointer table filled at runtime (name/slot pairs at `0x816435C0`; for example `WWWSurfaceMouseEvt` → `0x816987C0`, `WWWSurfaceKeyboardEvt` → `0x816987C8`). The browser manager (`WMGR`, `0x8169897C`) is only non-NULL while a browser screen is up. The menu queues input events for the browser thread with `0x8136D8A8` (an `OSSendMessage` wrapper; queue = `*(WMGR) + 0x28`). Pointer events (type 0) come from `0x813F1A74`. Button events (type 1) are handled by `0x8136D5CC`, which turns Wii Remote bits into browser keys through `0x8136D2B4`, but nothing in this menu version ever queues them.

On those screens gc_rect records nothing, so gc_dpad switches to **keyboard mode** (only while `WMGR` is set: the health screen has no buttons either). It saves the cursor, holds the pointer on a blank spot (the page's title tab) for 3 frames so the page sees a mouse-out, then parks it just below the screen where it's hidden, and queues type-1 events itself (**www_key**). The browser's `input.ini` (in `/tmp/www.arc`) maps those keys to Opera's spatial navigation. The menu's mapping assumes a sideways remote: WPAD right/left/up/down give keys `0xE03C`/`E03D`/`E03E`/`E03F`, which the browser treats as Up/Down/Left/Right. WPAD 1 gives `0xE044`, which activates the focused element. So the hook sends GC left → WPAD up, right → down, down → left, up → right, and A → WPAD 1 (A itself is removed from the KPAD data, since a click would land under the hidden pointer). Moving the stick, a screen with native buttons, or the browser going away ends keyboard mode and restores the cursor.

### Data block

| Offset | Field |
|---|---|
| `0x00/0x04` | cursor x/y (f32); starts on the top-left channel |
| `0x08` | previous buttons |
| `0x0C` | repeat countdown |
| `0x10` | OVR |
| `0x14` | PCNT (debug) |
| `0x18` | int→float magic `0x4330000080000000` |
| `0x20` | temp double |
| `0x28..0x3C` | 0.0, 0.5, 1.5, speed, LIMX, LIMY |
| `0x40` | PADStatus[4] |
| `0x70` | BTNTAB[13] |
| `0x8A` | TEST (debug): GC buttons ORed into LAST, for testing without a pad |
| `0x8C` | KCNT (debug) |
| `0x90` | LAST (12 bytes) |
| `0x9C` | MISS |
| `0xA0` | GOOD |
| `0xA4` | NBTN: buttons recorded this frame |
| `0xA8/0xAC` | D-pad previous / repeat countdown |
| `0xB0..0xCC` | K, K (16:9), screen limits, MINFWD, LATW, 1e30, CONE |
| `0xD0` | DIRTAB: D-pad direction vectors |
| `0xF0..0xFC` | MAXW, MAXH, DEDUP, STRIP |
| `0x100` | HTMLM: keyboard mode (low byte: frames left on the blank spot; bits 8+: held-back first key) |
| `0x104/0x108` | saved cursor |
| `0x10C` | WWWTAB: D-pad → WPAD bit for each browser arrow |
| `0x110..0x11C` | 30, 40 (null pane default size), MINSZ, NEAR² |

**Debug build** (`tools/build.py` without `--release`): call counters, the TEST input, and the disc slot LED (`HW_GPIOB_OUT` `0xCD0000C0`, bit `0x20`): solid when OVR is set, blinking about 2 Hz when the hook runs without a pad.

## Code caves

`tools/caves.py` collects every reachable address: b/bl/bc targets, raw 32-bit pointers anywhere in the DOL, and lis+addi/ori pairs. It reports dead ranges that run from an unreferenced `stwu r1` prologue to the last `blr` before anything reachable.

The compiler sometimes schedules an instruction or two **before** the `stwu`, so a function can start earlier than its prologue. The finder now also rejects a range if anything branches to the instructions between the previous `blr`/`b` and the `stwu`. Three earlier candidates (v513) are **live** code:

- `0x814AE13C` (v1.0/v1.1's data cave): the function starts at `0x814AE130` and is called from `0x814ADFF0`, `0x814AE000` and `0x814AE0B0` (a checksum-style loop). The hook overwrote it and only worked because that path rarely runs. v514's data cave `0x814AE238` is the same function (starts at `0x814AE22C`, three callers).
- `0x8151E680`: starts at `0x8151E67C` (a math function, called from `0x813445E8` for the cursor rotation and from `0x81374624`).
- `0x815469B8`: starts at `0x815469B4`, called from `0x81525F10`. Overwriting it froze the menu at boot.

Used now (v513; the other versions in their sections):

- `0x81359A70`-`0x8135A4C0` (0xA50): a run of unreferenced functions, ending with the old code cave; nothing outside it branches or points into it. Code (up to 0x930), then the data block at `0x8135A3A0`.
- `0x81576484`-`0x815765C0` (0x13C, an unused PAD library function): `code2` (www_key, debug LED helper).
- `0x814B4564`-`0x814B4668`: BTNS, runtime only (centers, from `0x814B4568`).
- `0x814B3A28`-`0x814B3B68`: PANES, runtime only.

Low memory `0x80001800`-`0x80003000` is **not** usable. Dolphin's Gecko cheat handler lives there (magic `0xD01F1BAD`, reinstalled whenever it goes missing and called every frame), and something else in the boot path writes there too.

## Priiloader notes

Checked against DacoTaco/priiloader `master` and tag `0.9.1`.

- `offset=` patches are passed to the loader, which writes them **after** copying all DOL sections (BSS isn't cleared for the menu), then flushes the data cache and invalidates the instruction cache. The patch list is allocated in MEM2.
- `hash=` patches are searched in the DOL file in order, and the search position is **not reset between patches of one hack**. If one is missing, the rest are silently skipped while earlier ones stay applied. This hack only uses `offset=` patches.
- Each `0x........` value is split into bytes, so always write 8 hex digits. The maximum line length is 0x2000 characters, and a name can be at most 39 characters.
- `hacks_hash.ini` is read from `fat:/apps/priiloader/` (SD/USB), otherwise from NAND `/title/00000001/00000002/data/hackshas.ini`. Saving in the hacks menu copies the SD file to NAND, and the menu boot reads the NAND copy.
- Hack on/off states (`hacksh_s.ini`) are one byte per hack, **by index**. If the number of hacks changes, all states are reset to off.
- Every hack in the file is loaded, but the hacks menu only lists the ones whose `minversion`..`maxversion` contains the running menu, and the others are forced off at boot (`main.cpp`, `hacks.cpp` on `master`). That's why `gc_cursor_hack.ini` can hold a block per version with the same name.

## Testing in Dolphin

Dolphin can run the hook without Priiloader. `tools/dolmem.py` maps Dolphin's emulated RAM (shared memory `dolphin-emu.<pid>`) to read and write it.

1. Import a BootMii NAND backup. If Priiloader is installed on that NAND, booting it in Dolphin may hang. In Dolphin's NAND copy only, copy `10000098.app` over `00000098.app` and `title_or.tmd` over `title.tmd`, so the real menu boots directly.
2. Turn **off** *Enable Cheats*, which uses `0x80001800`. Turn on *Options → Boot to Pause*. Set Wii Remote 1 to *None* and Port 1 to *Standard Controller*.
3. Tools → Load Wii System Menu (it stops paused), then:
   ```
   python tools/mkhack.py apply hack/gc_cursor_hack.ini
   ```
   This parses the .ini the way Priiloader does and writes it into RAM. Then unpause.

Patching while the menu is running doesn't take effect: Dolphin's JIT keeps executing its cached copy, and *JIT → Clear Cache* during the menu froze it in testing. Patch while paused at boot instead. `tools/livepatch.py status` shows the call sites, the counters and the GC state.

On Linux (where `dolmem.py`'s Windows shared memory isn't available), Dolphin's GDB stub works instead: set `GDBPort` under `[General]` in `Dolphin.ini`, start with `-d` (breakpoints only work with debugging enabled) and `-n 0000000100000002`. The menu stops before its first instruction with the DOL already loaded; memory is reachable at physical addresses until the MMU is on, and at virtual addresses after. *Tools → Perform Online System Update* installs a menu into a fresh NAND (USA: v513, Europe: v514, Japan: v512), and adding `IPL.CD`/`IPL.CD2` (bool, 1) to its SYSCONF skips first-time setup. The debug build's TEST halfword lets a script press GC buttons through the debugger.

Pitfalls found along the way:
- In PowerPC, `addi rD, r0, x` means `li rD, x`, so r0 is never used as a base register. (That includes `addi r0, r0, -1`, which is `li r0, -1`.)
- keystone mis-encodes `bl <absolute address>` in some multi-label sources. `build.py` encodes b/bl itself and checks every branch target with capstone.

## System Menu 4.3E (v514)

DOL SHA-1 `2ebea6ed22473857ed64b12daa71ae2d1ed61708`, TMD version 514, boot content index 8 (`0000009b.app`, or `1000009b.app` with Priiloader). Same section layout as v513 (T0 `0x80003400` size `0x400`, D0 `0x8132FFE0` size `0x3B0000`) and the same SDK build: `WPADProbe`, `KPADRead`, `PADRead`, `PADReset` and `memset` are byte-identical to v513, only moved. So the KPADStatus/PADStatus layouts above apply unchanged. Everything else used here moved by `+0x70` to `+0xFC` (the controller manager by `+0x70`, the code cave by `+0xA8`, the data cave and the SDK by `+0xFC`), except `memset`, which stayed put.

| | v513 | v514 |
|---|---|---|
| `WPADProbe` | `0x8157AA24` | `0x8157AB20` |
| `KPADRead` | `0x81587984` | `0x81587A80` |
| `PADRead` | `0x81576930` | `0x81576A2C` |
| `PADReset` | `0x815765C0` | `0x815766BC` |
| `memset` | `0x81330334` | `0x81330334` |
| controller manager update | `0x81337500` | `0x81337570` |
| `bl WPADProbe` site | `0x81337584` | `0x813375F4` |
| `bl KPADRead` site | `0x813375BC` | `0x8133762C` |
| `GetPaneRect` | `0x8151EE64` | `0x8151EF60` |
| `SCGetAspectRatio` | `0x81569FB4` | `0x8156A0B0` |
| browser event queue | `0x8136D8A8` | `0x8136D950` |
| `bl GetPaneRect` sites | `0x81369844`, `0x81378CA4` | `0x813698EC`, `0x81378D4C` |
| `WMGR` (browser manager) | `0x8169897C` | `0x8169A81C` |
| `PANEVT` (Pane vtable) | `0x81671704` | `0x816719C4` |
| code run | `0x81359A70` (0xA50) | `0x81359B18` (0xA50) |
| data block | `0x8135A3A0` | `0x8135A448` |
| code2 | `0x81576484` (0x13C) | `0x81576580` (0x13C) |
| BTNS / PANES | `0x814B4568` / `0x814B3A28` | `0x814B4664` / `0x814B3B24` |

v1.1 put the v514 data block at `0x814AE238`, which is live code (see [Code caves](#code-caves)); v1.2 uses the same verified run as v513. The EU hook is the same code as v513's: every instruction of the built hook is identical except the address fields (branch offsets and `lis`/`addi`/`lwz` immediates). It also doesn't overlap any of the official `hacks_hash.ini` hacks (`tools/hackini.py`).

How it was found: `tools/port.py` locates each v513 address in the v514 DOL by matching the surrounding instructions with address-dependent fields masked. All of them matched uniquely (±8 instructions; ±64 for the `GetPaneRect` sites). The data addresses come from a ported instruction that references them (`port.py` decodes `d(r13)` and `lis`/`addi`). The call sites were then checked with `ppc.py --menu 514 dis` (each original `bl` lands on the ported function), the caves with `caves.py --menu 514`, and the ported `PANEVT` holds the ported v513 Pane methods (18/18 entries).

Tested in Dolphin (v514 installed with *Perform Online System Update*, Europe): health screen, channel grid, Wii Options, Wii System Settings with the D-pad, and the HOME Menu. Not tested on 4.3E hardware yet. One thing to watch: cursor speed and the button-repeat delays count frames, so a menu running at 50 Hz moves the cursor about 17% slower than at 60 Hz.

## System Menu 4.3J (v512)

DOL SHA-1 `c94c8e671854d56fa2abd4c4c886e6c62a2c7f0e`, TMD version 512, boot content index 8 (`00000095.app`, or `10000095.app` with Priiloader). Same SDK build again (`KPADRead`, `PADRead`, `PADReset`, `memset` byte-identical to v513; `WPADProbe` differs only in address fields), but more code moved: the menu code by `-0xB20` to `-0xB4C`, the SDK by `+0x28F40`.

| | v513 | v512 |
|---|---|---|
| `WPADProbe` | `0x8157AA24` | `0x815A3964` |
| `KPADRead` | `0x81587984` | `0x815B08C4` |
| `PADRead` | `0x81576930` | `0x8159F870` |
| `PADReset` | `0x815765C0` | `0x8159F500` |
| `memset` | `0x81330334` | `0x81330334` |
| `GetPaneRect` | `0x8151EE64` | `0x81547DA4` |
| `SCGetAspectRatio` | `0x81569FB4` | `0x81592EF4` |
| browser event queue | `0x8136D8A8` | `0x8136CD5C` |
| `bl WPADProbe` site | `0x81337584` | `0x81336A64` |
| `bl KPADRead` site | `0x813375BC` | `0x81336A9C` |
| `bl GetPaneRect` sites | `0x81369844`, `0x81378CA4` | `0x81368CF8`, `0x81378158` |
| `WMGR` (browser manager) | `0x8169897C` | `0x816C807C` |
| `PANEVT` (Pane vtable) | `0x81671704` | `0x816A170C` |
| code run | `0x81359A70` (0xA50) | `0x81358F30` (0xA50) |
| data block | `0x8135A3A0` | `0x81359860` |
| code2 | `0x81576484` (0x13C) | `0x8159F3C4` (0x13C) |
| BTNS / PANES | `0x814B4568` / `0x814B3A28` | `0x814DD4A8` / `0x814DC968` |

Found and checked the same way as v514 (all matches unique, `PANEVT` 18/18, the built hook identical to v513's apart from address fields, no overlap with the official hacks). `r13` is `0x816CD700` (v513: `0x8169E040`).

Tested in Dolphin (Japan update): the same walkthrough as v514. Not tested on 4.3J hardware.

## Porting to another menu version

If the new menu uses the same SDK build (like 4.3E and 4.3J), start with `python tools/port.py bin/sysmenu_v<N>.dol`. It prints each v513 address's counterpart, including the `DATA` addresses. Check the results the same way as for v514 above, then add a `MENUS` entry in `tools/build.py`. `mkhack.py` writes a block for every built version.

Otherwise, repeat the hunt in the new DOL:

1. Find PAD/WPAD/KPAD via their `<< RVL_SDK - ... >>` version strings → `OSRegisterVersion` callers → the neighbouring functions.
2. Find the controller manager by following `KPADRead`'s callers, and the `WPADProbe` + `KPADRead` call sites in its 4-channel loop.
3. Run `tools/caves.py --menu <N>` to find caves, then add `SDK`, `SITES`, `DATA` and `CAVES` for the version to `MENUS` in `tools/build.py`.
4. For the D-pad: find `PaneComponent::contain` (callers of `PSMTXInverse` that call `GetPaneRect`), the browser manager pointer and event queue function, and check the pane field offsets.
5. Confirm the KPADStatus layout with a RAM dump; it can change between SDK versions.
