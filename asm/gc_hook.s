# GameCube controller -> Wii Menu pointer hook, System Menu 4.3U (v513).
#
# Two call sites in the controller manager update (0x81337500) are redirected:
#   0x81337584  bl WPADProbe  ->  bl gc_probe
#   0x813375BC  bl KPADRead   ->  bl gc_kpad
#
# gc_probe: on channel 0, if no real remote is found (-1) and a GC pad is
#   plugged into any port, report "Wii Remote (core) connected" and set OVR.
#   PADRead says err -3 when the pad wasn't polled since the last read, so the
#   last good status (LAST) is reused for up to HOLD frames.
# gc_kpad: on channel 0 with OVR set, replace the KPADStatus with one built
#   from LAST: stick -> pointer, buttons -> Wii Remote buttons.
#
# D-pad button selection: the menu's gui PaneComponent::contain (0x8136979C, and
# its twin 0x81378BFC) asks GetPaneRect for every clickable button each frame:
#   0x81369844  bl GetPaneRect  ->  bl gc_rect
#   0x81378CA4  bl GetPaneRect  ->  bl gc_rect
# gc_rect: records the button's center in layout space (pane global matrix at
#   pane+0x84) into BTNS, and its pane into PANES, while OVR is set.
# gc_dpad: on a D-pad press, picks the closest recorded button in that direction
#   and moves the cursor onto its center. Layout x = K*CX, y = -K*CY.
#   With no buttons recorded (an HTML screen, drawn by the browser), it switches to
#   keyboard mode instead: arrow keys move the browser's focus, A activates it.
#
# {NAME} placeholders are filled in by tools/build.py. r31 = data block.
# "@section code" goes in the big cave, "code2" in its own (CAVES in tools/build.py).
# Labels used across sections are written as {label}.
# Lines between "@if NAME" and "@endif" are kept only when build flag NAME is on.
# Careful: addi/addis with rA = r0 means "li"/"lis", so r0 is never a base here.

@section code
gc_probe:
    stwu r1, -0x20(r1)
    mflr r0
    stw r0, 0x24(r1)
    stw r31, 0x1c(r1)
    stw r30, 0x18(r1)
    stw r29, 0x14(r1)
    stw r28, 0x10(r1)
    mr r30, r3                  # chan
    mr r29, r4                  # u32 *type
    bl {WPADProbe}
    mr r28, r3                  # real result
    cmpwi r30, 0
    bne probe_out
    lis r31, {DATA_HA}
    addi r31, r31, {DATA_LO}
    li r0, 0
    stw r0, {OVR}(r31)
    cmpwi r28, -1               # WPAD_ERR_NO_CONTROLLER
    bne probe_led               # a real remote is there (or busy): leave it alone
    addi r3, r31, {PADBUF}
    bl {PADRead}
    li r4, 0                    # PADReset every port that says "no controller",
    lis r5, 0x8000              # so pads plugged in later get detected (the SDK
    li r7, 4                    # expects the caller to do this every frame)
    mtctr r7
    addi r6, r31, {PADBUF}
rst_loop:
    lbz r7, 0xa(r6)
    extsb r7, r7
    cmpwi r7, -1                # PAD_ERR_NO_CONTROLLER
    bne rst_next
    or r4, r4, r5
rst_next:
    srwi r5, r5, 1
    addi r6, r6, 12
    bdnz rst_loop
    cmpwi r4, 0
    beq rst_done
    mr r3, r4
    bl {PADReset}
rst_done:
    li r5, 4                    # first port with err == 0
    mtctr r5
    addi r6, r31, {PADBUF}
port_loop:
    lbz r0, 0xa(r6)
    extsb. r0, r0
    beq port_ok
    addi r6, r6, 12
    bdnz port_loop
    lwz r7, {MISS}(r31)         # no fresh status this frame
    addi r7, r7, 1
    stw r7, {MISS}(r31)
    cmpwi r7, {HOLD}
    bgt probe_led               # gone for too long: unplugged
    lwz r7, {GOOD}(r31)
    cmpwi r7, 0
    beq probe_led               # never seen a pad yet
    b spoof
port_ok:
    li r7, 0
    stw r7, {MISS}(r31)
    li r7, 1
    stw r7, {GOOD}(r31)
    lwz r7, 0(r6)               # LAST = this port's 12-byte PADStatus
    stw r7, {LAST}(r31)
    lwz r7, 4(r6)
    stw r7, {LAST}+4(r31)
    lwz r7, 8(r6)
    stw r7, {LAST}+8(r31)
spoof:
@if DEBUG
    lhz r7, {LAST}(r31)         # debug: OR in buttons written to TEST (testing without a pad)
    lhz r0, {TEST}(r31)
    or r7, r7, r0
    sth r7, {LAST}(r31)
@endif
    li r0, 1
    stw r0, {OVR}(r31)
    li r0, 0
    stw r0, 0(r29)              # *type = WPAD_DEV_CORE
    li r28, 0                   # WPAD_ERR_NONE
probe_led:
@if DEBUG
    bl {gc_led}
@endif
probe_out:
    mr r3, r28
    lwz r28, 0x10(r1)
    lwz r29, 0x14(r1)
    lwz r30, 0x18(r1)
    lwz r31, 0x1c(r1)
    lwz r0, 0x24(r1)
    mtlr r0
    addi r1, r1, 0x20
    blr

@section code
gc_kpad:
    stwu r1, -0x20(r1)
    mflr r0
    stw r0, 0x24(r1)
    stw r31, 0x1c(r1)
    stw r30, 0x18(r1)
    stw r29, 0x14(r1)
    stw r28, 0x10(r1)
    mr r30, r3                  # chan
    mr r29, r4                  # KPADStatus *buf
    bl {KPADRead}
    mr r28, r3                  # real sample count
    cmpwi r30, 0
    bne kpad_out
    lis r31, {DATA_HA}
    addi r31, r31, {DATA_LO}
    lwz r0, {OVR}(r31)
    cmpwi r0, 0
    beq kpad_out

@if DEBUG
    lwz r3, {KCNT}(r31)         # debug: frames overridden
    addi r3, r3, 1
    stw r3, {KCNT}(r31)
@endif
    mr r3, r29                  # memset(buf, 0, 0x84)
    li r4, 0
    li r5, 0x84
    bl {memset}

# ---- buttons: GC bit i -> BTNTAB[i] ----
    lhz r3, {LAST}(r31)
    li r4, 0
    addi r5, r31, {BTNTAB}-2
    li r6, 13
    mtctr r6
btn_loop:
    lhzu r7, 2(r5)
    andi. r0, r3, 1
    beq btn_skip
    or r4, r4, r7
btn_skip:
    srwi r3, r3, 1
    bdnz btn_loop
    lwz r5, {PREV}(r31)         # r4 = now, r5 = prev
    andc r6, r4, r5             # trig
    andc r7, r5, r4             # release
    stw r4, {PREV}(r31)
    stw r6, 4(r29)
    stw r7, 8(r29)
# KPAD repeat bit (0x80000000): on press, after 30 frames, then every 6
    lwz r8, {RPT}(r31)
    li r9, 0
    cmpw r4, r5
    beq rpt_same
    li r8, 30
    cmpwi r6, 0
    beq rpt_done
    li r9, 1
    b rpt_done
rpt_same:
    cmpwi r4, 0
    beq rpt_done
    addic. r8, r8, -1
    bne rpt_done
    li r9, 1
    li r8, 6
rpt_done:
    stw r8, {RPT}(r31)
    cmpwi r9, 0
    beq no_rpt
    oris r4, r4, 0x8000
no_rpt:
    stw r4, 0(r29)
# keyboard mode (HTML screens, see gc_dpad): A activates the browser's focused element
# instead of clicking under the (hidden) pointer
    lwz r0, {HTMLM}(r31)
    cmpwi r0, 0
    beq no_html
    lwz r3, 4(r29)
    andi. r0, r3, 0x800
    beq html_noa
    li r3, 0x200                # WPAD 1: the browser's "activate"
    bl {www_key}
html_noa:
    lwz r3, 0(r29)              # drop A (0x800) from hold/trig/release
    rlwinm r3, r3, 0, 21, 19
    stw r3, 0(r29)
    lwz r3, 4(r29)
    rlwinm r3, r3, 0, 21, 19
    stw r3, 4(r29)
    lwz r3, 8(r29)
    rlwinm r3, r3, 0, 21, 19
    stw r3, 8(r29)
no_html:
# D-pad: directions that fire this frame (press, then repeat) -> gc_dpad
    lhz r3, {LAST}(r31)         # GC D-pad: left 1, right 2, down 4, up 8
    andi. r3, r3, 0xf
    lwz r4, {DPREV}(r31)
    stw r3, {DPREV}(r31)
    lwz r5, {DRPT}(r31)
    li r6, 0
    cmpw r3, r4
    beq dp_same
    li r5, {DRPT1}              # changed: newly pressed directions fire
    andc r6, r3, r4
    b dp_rpt
dp_same:
    cmpwi r3, 0
    beq dp_rpt
    addic. r5, r5, -1           # held: repeat
    bne dp_rpt
    mr r6, r3
    li r5, {DRPT2}
dp_rpt:
    stw r5, {DRPT}(r31)
    mr r3, r6
    bl {gc_dpad}                # jumps the cursor to the next button (updates CX/CY)

# ---- stick -> cursor ----
    lfs f1, {CX}(r31)
    lfs f2, {CY}(r31)
    fmr f3, f1
    fmr f4, f2
    lbz r3, {LAST}+2(r31)       # stick X
    extsb r3, r3
    bl {stick_delta}
    fadds f1, f1, f5
    lbz r3, {LAST}+3(r31)       # stick Y (up = +), pointer Y (up = -)
    extsb r3, r3
    neg r3, r3
    bl {stick_delta}
    fadds f2, f2, f5
    lfs f6, {LIMX}(r31)         # clamp x to [-LIMX, LIMX]
    fneg f8, f6
    fsubs f7, f1, f6
    fsel f1, f7, f6, f1
    fadds f7, f1, f6
    fsel f1, f7, f1, f8
    lfs f6, {LIMY}(r31)         # clamp y to [-LIMY, LIMY]
    fneg f8, f6
    fsubs f7, f2, f6
    fsel f2, f7, f6, f2
    fadds f7, f2, f6
    fsel f2, f7, f2, f8
    stfs f1, {CX}(r31)
    stfs f2, {CY}(r31)
    stfs f1, 0x20(r29)          # pos
    stfs f2, 0x24(r29)
    fsubs f3, f1, f3
    fsubs f4, f2, f4
    stfs f3, 0x28(r29)          # vec
    stfs f4, 0x2c(r29)
    fmuls f5, f3, f3
    fmadds f5, f4, f4, f5
    lfs f6, {ZERO}(r31)
    fcmpu cr0, f5, f6
    beq no_speed
    frsqrte f7, f5              # speed = s2 * rsqrt(s2), one Newton step
    lfs f8, {HALF}(r31)
    lfs f9, {THREEHALF}(r31)
    fmul f10, f7, f7
    fmul f10, f10, f5
    fnmsub f10, f10, f8, f9
    fmul f7, f7, f10
    fmul f7, f7, f5
    frsp f7, f7
    stfs f7, 0x30(r29)          # speed
no_speed:

# ---- fixed fields (values copied from a real remote at rest) ----
    lis r0, 0xbf80
    stw r0, 0x10(r29)           # acc.y = -1.0
    lis r0, 0x3f80
    stw r0, 0x18(r29)           # acc_value = 1.0
    stw r0, 0x34(r29)           # horizon.x = 1.0
    stw r0, 0x54(r29)           # acc_vertical.x = 1.0
    lis r0, 0x3ff9
    ori r0, r0, 0x3ae6
    stw r0, 0x48(r29)           # dist = 1.95
    li r0, 0x0202
    stw r0, 0x5c(r29)           # dev_type 0, wpad_err 0, dpd_valid 2, data_format 2
    li r28, 1                   # 1 sample
kpad_out:
    mr r3, r28
    lwz r28, 0x10(r1)
    lwz r29, 0x14(r1)
    lwz r30, 0x18(r1)
    lwz r31, 0x1c(r1)
    lwz r0, 0x24(r1)
    mtlr r0
    addi r1, r1, 0x20
    blr

@section code
# r3 = signed stick value -> f5 = cursor delta (quadratic past the deadzone).
# Leaf; keeps f1-f4. Needs r31 = data block.
stick_delta:
    srawi r4, r3, 31
    xor r5, r3, r4
    subf r5, r4, r5             # |s|  (not r0: addi with rA=r0 means "li")
    cmpwi r5, {DEADZONE}
    bge sd_go
    lfs f5, {ZERO}(r31)
    blr
sd_go:
    addi r5, r5, -{DEADZONE}
    mullw r5, r5, r5
    cmpwi r3, 0
    bge sd_pos
    neg r5, r5
sd_pos:
    xoris r5, r5, 0x8000        # int -> double via 0x43300000_80000000 trick
    stw r5, {TMP}+4(r31)
    lis r4, 0x4330
    stw r4, {TMP}(r31)
    lfd f5, {TMP}(r31)
    lfd f13, {MAGIC}(r31)
    fsub f5, f5, f13
    lfs f12, {SPEED}(r31)
    fmul f5, f5, f12
    frsp f5, f5
    blr

@section code
# Replaces "bl GetPaneRect" inside PaneComponent::contain(x, y): same args
# (r3 = Rect *out, r4 = Pane *, r5 = DrawInfo *), and records the button's center.
# Rect = left, top, right, bottom (local). Pane global matrix (3x4) at pane+0x84.
gc_rect:
    stwu r1, -0x20(r1)
    mflr r0
    stw r0, 0x24(r1)
    stw r31, 0x1c(r1)
    stw r30, 0x18(r1)
    stw r29, 0x14(r1)
    mr r30, r3                  # Rect *
    mr r29, r4                  # Pane *
    bl {GetPaneRect}
    lis r31, {DATA_HA}
    addi r31, r31, {DATA_LO}
    lwz r0, {OVR}(r31)
    cmpwi r0, 0
    beq rect_out                # Wii Remote in use: don't bother
    lwz r5, {NBTN}(r31)
    cmplwi r5, {MAXBTN}
    bge rect_out
    lfs f0, {HALF}(r31)
    lfs f1, 0(r30)              # local center
    lfs f2, 8(r30)
    fadds f1, f1, f2
    fmuls f1, f1, f0
    lfs f2, 4(r30)
    lfs f3, 0xc(r30)
    fadds f2, f2, f3
    fmuls f2, f2, f0
    lfs f3, 0x84(r29)           # X = m00*cx + m01*cy + m03
    lfs f4, 0x88(r29)
    lfs f5, 0x90(r29)
    fmadds f5, f3, f1, f5
    fmadds f5, f4, f2, f5
    lfs f3, 0x94(r29)           # Y = m10*cx + m11*cy + m13
    lfs f4, 0x98(r29)
    lfs f6, 0xa0(r29)
    fmadds f6, f3, f1, f6
    fmadds f6, f4, f2, f6
    fabs f3, f5                 # on screen only (skips the other channel pages);
    lfs f4, {XLIM}(r31)         # bge, not bgt, so NaN is rejected too
    fcmpu cr0, f3, f4
    bge rect_out
    fabs f3, f6
    lfs f4, {YLIM}(r31)
    fcmpu cr0, f3, f4
    bge rect_out
    lbz r0, 0xce(r29)           # skip invisible panes (global alpha 0)
    cmpwi r0, 0
    beq rect_out
    lwz r0, 0xb4(r29)           # skip trigger targets that do nothing: the "Wii" title
    lis r6, 0x4261              # bar (BarWii_00) and the channel preview's frame (Fre_*)
    ori r6, r6, 0x7257          # "BarW"
    cmpw r0, r6
    beq rect_out
    lis r6, 0x4672
    ori r6, r6, 0x655f          # "Fre_"
    cmpw r0, r6
    beq rect_out
    lfs f3, 8(r30)              # w, h: local size
    lfs f4, 0(r30)
    fsubs f3, f3, f4
    fabs f3, f3
    lfs f4, 4(r30)
    lfs f7, 0xc(r30)
    fsubs f4, f4, f7
    fabs f4, f4
    lwz r0, 0(r29)              # skip unsized groups: a plain Pane (null) left at the
    lis r6, {PANEVT_HA}         # default 30x40 (dialog roots, the clock, HOME's groups);
    addi r6, r6, {PANEVT_LO}    # their buttons are children
    cmpw r0, r6
    bne rect_sized
    lfs f7, {NULLW}(r31)
    fcmpu cr0, f3, f7
    bne rect_sized
    lfs f7, {NULLH}(r31)
    fcmpu cr0, f4, f7
    beq rect_out
rect_sized:
    lfs f7, {MINSZ}(r31)        # skip decorations smaller than a button (frame corners)
    fcmpu cr0, f3, f7
    blt rect_out
    fcmpu cr0, f4, f7
    blt rect_out
    lfs f7, {MAXW}(r31)         # skip backdrops: bigger than a button
    fcmpu cr0, f3, f7
    bge rect_out
    lfs f7, {MAXH}(r31)
    fcmpu cr0, f4, f7
    bge rect_out
    lfs f7, {STRIP}(r31)        # skip thin strips (edge hit areas of a bigger button)
    fmuls f8, f3, f7
    fcmpu cr0, f4, f8
    bge rect_out
    fmuls f8, f4, f7
    fcmpu cr0, f3, f8
    bge rect_out
    lis r6, {BTNS_HA}
    addi r6, r6, {BTNS_LO}
    cmpwi r5, 0
    beq rect_add
    lwz r8, 0xc(r29)            # skip panes inside a button already recorded:
anc_loop:                       # is any ancestor (Pane::mpParent, +0xc) in PANES?
    cmpwi r8, 0
    beq anc_done
    mtctr r5
    lis r9, {PANES_HA}
    addi r9, r9, {PANES_LO}-4
anc_cmp:
    lwzu r10, 4(r9)
    cmpw r10, r8
    beq rect_out
    bdnz anc_cmp
    lwz r8, 0xc(r8)
    b anc_loop
anc_done:                       # a button is several panes with the same center:
                                # skip centers within DEDUP of one already recorded
    lfs f4, {DEDUP}(r31)
    mtctr r5
    mr r7, r6
rect_dup:
    lfs f1, 0(r7)
    fsubs f1, f1, f5
    fabs f1, f1
    fcmpu cr0, f1, f4
    bge rect_next
    lfs f1, 4(r7)
    fsubs f1, f1, f6
    fabs f1, f1
    fcmpu cr0, f1, f4
    blt rect_out
rect_next:
    addi r7, r7, 8
    bdnz rect_dup
rect_add:
    slwi r7, r5, 2              # PANES[n] = pane
    lis r8, {PANES_HA}
    addi r8, r8, {PANES_LO}
    stwx r29, r8, r7
    slwi r7, r5, 3
    add r6, r6, r7
    stfs f5, 0(r6)
    stfs f6, 4(r6)
    addi r5, r5, 1
    stw r5, {NBTN}(r31)
rect_out:
    lwz r29, 0x14(r1)
    lwz r30, 0x18(r1)
    lwz r31, 0x1c(r1)
    lwz r0, 0x24(r1)
    mtlr r0
    addi r1, r1, 0x20
    blr

@section code
# Called from gc_kpad with r31 = data block, r3 = GC D-pad bits that fire. Moves
# CX/CY onto the center of the best button recorded since the last call, then
# clears the list. Score = forward distance + LATW * sideways distance, among buttons
# at least MINFWD ahead (not the one we're on) and inside a cone of side <= CONE * fwd.
gc_dpad:
    stwu r1, -0x20(r1)
    mflr r0
    stw r0, 0x24(r1)
    stw r30, 0x18(r1)
    mr r6, r3                   # D-pad directions that fire
    lwz r30, {NBTN}(r31)
    li r0, 0
    stw r0, {NBTN}(r31)
    lwz r0, {HTMLM}(r31)        # keyboard mode ends when native buttons show up, the
    cmpwi r0, 0                 # browser goes away, or the stick moves: the pointer
    beq dp_mode                 # comes back
    cmpwi r30, 0
    bne dp_leave
    lis r3, {WMGR_HA}
    lwz r3, {WMGR_LO}(r3)
    cmpwi r3, 0
    beq dp_leave
    lbz r3, {LAST}+2(r31)
    extsb r3, r3
    srawi r4, r3, 31
    xor r5, r3, r4
    subf r5, r4, r5
    cmpwi r5, {DEADZONE}
    bge dp_leave
    lbz r3, {LAST}+3(r31)
    extsb r3, r3
    srawi r4, r3, 31
    xor r5, r3, r4
    subf r5, r4, r5
    cmpwi r5, {DEADZONE}
    bge dp_leave
    lwz r3, {HTMLM}(r31)        # HTMLM low byte 4..2: pointer on the blank spot,
    clrlwi r4, r3, 24           # 1: parked below. Bits 8+: the first key, held back
    cmpwi r4, 1                 # until then (the page ignores the mouse once keys start)
    ble dp_mode
    addi r3, r3, -1             # (not r0: addi with rA = r0 means li)
    cmpwi r4, 2
    beq dp_park
    stw r3, {HTMLM}(r31)
    b dp_mode
dp_park:
    li r0, 1
    stw r0, {HTMLM}(r31)
    lis r0, 0x3f80              # CY = 1.0: below the screen, where the pointer is hidden
    stw r0, {CY}(r31)
    srwi r3, r3, 8
    bl {www_key}
    b dp_mode
dp_leave:
    lwz r0, {SAVEX}(r31)
    stw r0, {CX}(r31)
    lwz r0, {SAVEY}(r31)
    stw r0, {CY}(r31)
    li r0, 0
    stw r0, {HTMLM}(r31)
dp_mode:
    cmpwi r6, 0
    beq dp_out
    cmpwi r30, 0
    beq dp_www
    stw r6, 0x10(r1)
    bl {SCGetAspect}            # 1 = 16:9: the menu scales the pointer by 1.15
    clrlwi r3, r3, 24
    lfs f10, {K}(r31)
    cmplwi r3, 1
    bne dp_k
    lfs f10, {KWIDE}(r31)
dp_k:
    lwz r6, 0x10(r1)
    neg r7, r6                  # lowest pressed direction -> DIRTAB index
    and r7, r6, r7
    cntlzw r7, r7
    subfic r7, r7, 31
    slwi r7, r7, 3
    addi r7, r7, {DIRTAB}
    lfsx f1, r31, r7            # direction (ux, uy), layout space (y up)
    addi r7, r7, 4
    lfsx f2, r31, r7
    lfs f3, {CX}(r31)           # current pointer in layout space
    fmuls f3, f3, f10
    lfs f4, {CY}(r31)
    fmuls f4, f4, f10
    fneg f4, f4
    lfs f11, {LATW}(r31)
    lfs f12, {BIG}(r31)         # best score so far
    lfs f13, {MINFWD}(r31)
    lfs f0, {CONE}(r31)
    li r8, 0                    # best entry
    lis r9, {BTNS_HA}
    addi r9, r9, {BTNS_LO}
    mtctr r30
dp_loop:
    lfs f5, 0(r9)
    lfs f6, 4(r9)
    fsubs f5, f5, f3            # dx
    fsubs f6, f6, f4            # dy
    fmuls f7, f5, f1            # fwd = dx*ux + dy*uy
    fmadds f7, f6, f2, f7
    fcmpu cr0, f7, f13
    ble dp_next
    fmuls f8, f5, f2            # side = |dx*uy - dy*ux|
    fnmsubs f8, f6, f1, f8
    fabs f8, f8
    fmuls f9, f7, f0            # outside the cone (side > CONE * fwd): not in that direction
    fcmpu cr0, f8, f9
    bgt dp_next
    fmadds f9, f8, f11, f7
    fcmpu cr0, f9, f12
    bge dp_next
    fmr f12, f9
    mr r8, r9
dp_next:
    addi r9, r9, 8
    bdnz dp_loop
    cmpwi r8, 0
    bne dp_move
    lfs f12, {BIG}(r31)         # nothing that way: unless the cursor is on a button already,
    lis r9, {BTNS_HA}           # take the nearest one (a new screen, or it was moved off)
    addi r9, r9, {BTNS_LO}
    mtctr r30
dn_loop:
    lfs f5, 0(r9)
    lfs f6, 4(r9)
    fsubs f5, f5, f3
    fsubs f6, f6, f4
    fmuls f7, f5, f5
    fmadds f7, f6, f6, f7
    fcmpu cr0, f7, f12
    bge dn_next
    fmr f12, f7
    mr r8, r9
dn_next:
    addi r9, r9, 8
    bdnz dn_loop
    lfs f7, {NEAR2}(r31)
    fcmpu cr0, f12, f7
    blt dp_out
dp_move:
    lfs f5, 0(r8)               # CX = X/K, CY = -Y/K
    fdivs f5, f5, f10
    stfs f5, {CX}(r31)
    lfs f6, 4(r8)
    fdivs f6, f6, f10
    fneg f6, f6
    stfs f6, {CY}(r31)
    b dp_out
# No native buttons: an HTML screen (the browser). Switch to keyboard mode (pointer
# moved off the page's links, then hidden below the screen) and send the arrow key;
# the browser moves its own focus highlight.
dp_www:
    lis r3, {WMGR_HA}           # only while a browser screen is up (its manager exists only
    lwz r3, {WMGR_LO}(r3)       # then): other screens without buttons, like the health
    cmpwi r3, 0                 # screen, keep A as A
    beq dp_out
    lwz r0, {HTMLM}(r31)
    cmpwi r0, 0
    bne dp_key
    lwz r0, {CX}(r31)
    stw r0, {SAVEX}(r31)
    lwz r0, {CY}(r31)
    stw r0, {SAVEY}(r31)
    lis r0, 0xbf8c              # first 3 frames on a blank spot (the page's title tab,
    stw r0, {CX}(r31)           # top left: CX = -1.094, x = -299) so the page gets a
    lis r0, 0xbf4e              # mouse-out, then parked; the key goes out after that
    stw r0, {CY}(r31)           # (CY = -0.805, y = 220)
    bl dp_dir
    slwi r3, r3, 8
    ori r3, r3, 4
    stw r3, {HTMLM}(r31)
    b dp_out
dp_key:
    bl dp_dir
    bl {www_key}
dp_out:
    lwz r30, 0x18(r1)
    lwz r0, 0x24(r1)
    mtlr r0
    addi r1, r1, 0x20
    blr
# r6 = D-pad bits -> r3 = WPAD bit for the browser arrow key of the lowest one. Leaf.
dp_dir:
    neg r7, r6
    and r7, r6, r7
    cntlzw r7, r7
    subfic r7, r7, 31
    addi r7, r7, {WWWTAB}
    lbzx r3, r31, r7
    blr

@section code2
# r3 = WPAD button bits: queue a button-down and a button-up event (type 1) for the
# browser thread, the way the menu queues pointer events (0x813F1A74). The browser
# thread's handler (0x8136D5CC) turns them into browser keys: WPAD right/left/up/down
# -> Up/Down/Left/Right (it assumes a sideways remote), 1 -> activate.
www_key:
    stwu r1, -0x40(r1)
    mflr r0
    stw r0, 0x44(r1)
    stw r30, 0x38(r1)
    stw r29, 0x34(r1)
    mr r30, r3
    lis r3, {WMGR_HA}           # browser manager -> its event queue (+0x28)
    lwz r3, {WMGR_LO}(r3)
    cmpwi r3, 0
    beq wk_out
    lwz r29, 0x28(r3)
    cmpwi r29, 0
    beq wk_out
    li r0, 0                    # event at 0x10(r1): type, x, y, ..., +0x14 trig, +0x18 release
    stw r0, 0x14(r1)
    stw r0, 0x18(r1)
    stw r0, 0x1c(r1)
    stw r0, 0x20(r1)
    stw r0, 0x28(r1)
    stw r30, 0x24(r1)
    li r0, 1
    stw r0, 0x10(r1)
    mr r3, r29
    addi r4, r1, 0x10
    bl {WWWQueue}               # down
    li r0, 0
    stw r0, 0x24(r1)
    stw r30, 0x28(r1)
    mr r3, r29
    addi r4, r1, 0x10
    bl {WWWQueue}               # up
wk_out:
    lwz r29, 0x34(r1)
    lwz r30, 0x38(r1)
    lwz r0, 0x44(r1)
    mtlr r0
    addi r1, r1, 0x40
    blr

@section code2
@if DEBUG
# gc_probe helper (debug build), r31 = data block: chan-0 probe counter and the
# disc slot LED (HW_GPIOB_OUT bit 0x20): solid = override on, blinking = hook
# running without a pad. Leaf.
gc_led:
    lwz r3, {PCNT}(r31)
    addi r3, r3, 1
    stw r3, {PCNT}(r31)
    lis r6, 0xcd00
    lwz r7, 0xc0(r6)
    rlwinm r7, r7, 0, 27, 25
    lwz r0, {OVR}(r31)
    cmpwi r0, 0
    bne led_on
    lwz r0, {PCNT}(r31)
    andi. r0, r0, 16
    beq led_set
led_on:
    ori r7, r7, 0x20
led_set:
    stw r7, 0xc0(r6)
    blr
@endif
