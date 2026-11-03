//! XAP2 reference executor (ARCHITECTURE §6.3; semantics from bc5-isa.md §2–§4 and the §8 pseudo-code).
//! Every data access goes through the common bus (`Bus(bc5)`: u16 words, fuel, strict log, tapes).
//! Code is read-only words in `Segment`s addressed by the 24-bit program counter.
//!
//! Program space: both BC5 images run at program word 0x800C (bc5-arch §0: far code pointer =
//! image word + 0x800C; the IRQ vectors 0x8752… dispatched register-direct land on their handlers).
//! Relative branches do not depend on the base; bsr return addresses, function pointers and the
//! panic walker do.
//!
//! Open semantics are `variants.zig` readings; `touched` collects the assumptions an executed
//! instruction depended on. Flags the spec leaves unknown (`?`, bc5-isa §2) keep their old value and
//! are marked in `cpu.fq`; a branch that consumes one counts `unknown_flag_uses`.
const std = @import("std");
const common = @import("common");
const hooks = common.hooks;
const dec = @import("decode.zig");
const variants = @import("variants.zig");

pub const Bus = common.bus.Bus(common.bus.bc5);
pub const Insn = dec.Insn;
const Id = variants.Id;

/// Program word of image word 0 (bc5-arch §0).
pub const image_base: u32 = 0x800C;
/// Return address the ABI binding gives a called original; reaching it at call depth 0 ends the run
/// (unless code is mapped there: snippets may put code anywhere).
pub const sentinel: u32 = 0xFFFFFE;

// Internal flag layout (= the chosen XA-flags-layout).
pub const Z: u16 = 1;
pub const N: u16 = 2;
pub const C: u16 = 4;
pub const V: u16 = 8;
pub const IE: u16 = 0x10;
const ZNCV = Z | N | C | V;

/// Register file: plain data, a snapshot part, and the vector `regs` layout (`std.mem.asBytes`).
pub const Cpu = extern struct {
    ah: u16 = 0,
    al: u16 = 0,
    x: u16 = 0,
    y: u16 = 0,
    xh: u16 = 0,
    ux: u16 = 0,
    uy: u16 = 0,
    /// Internal layout Z=0 N=1 C=2 V=3, bit 4 = interrupt enable; other bits as last loaded.
    flags: u16 = 0,
    /// Flags whose value is unknown since the instruction that last set them (same bit positions).
    fq: u16 = 0,
    /// Last value the CPU wrote to I/O 0xFF52 (only the XA-alias-mode alternative reads it).
    ff52: u16 = 0,
    pc: u32 = 0,
};

/// `gate`: the segment exists only under the chosen reading of that assumption (a SoC mapping).
pub const Segment = struct { base: u32, words: []const u16, gate: ?Id = null };

/// `call_depth`: more nested calls than `Core.frames` holds (the 0x380-word stack fits fewer frames).
pub const Trap = enum(u32) { brk = 1, illegal = 2, call_depth = 3 };

/// Why `run` returned. Bus stops (fault, fuel, tape) arrive through `bus.stop`.
pub const Halt = union(enum) {
    returned,
    trap: Trap,
    /// Code fetch outside every segment (`addr` = PC) or a data fault from the bus.
    fault: u32,
    fuel_exhausted,
    tape_exhausted,
    /// `max_steps` executed.
    steps,
    /// A `sleep` with `stop_on_sleep` set; PC is after the sleep.
    sleep,
};

const Frame = struct { ra: u32, y: u16 };

pub const Core = struct {
    cpu: Cpu = .{},
    bus: *Bus,
    code: []const Segment,
    /// Register aliases 0xFFE0/E1/E3/E4 (main image on, loader off; XA-alias-mode).
    alias_regs: bool = true,
    sel: variants.Set = .{},
    touched: variants.Set = .{},
    /// Branches that consumed a flag marked unknown.
    unknown_flag_uses: u64 = 0,
    steps: u64 = 0,
    sleeps: u64 = 0,
    stop_on_sleep: bool = false,
    /// ABI words recorded for a call the original makes (E5): AL, AH, then @(0,Y)…
    // shortcut: a fixed count per target from the binding (default AL, AH); use measured signatures (§5.3) once the registry has them.
    argWords: *const fn (target: u32) u8 = twoWords,
    /// Calls in flight below F (bsr pushes, the matching return pops). Depth 0 = F itself.
    frames: [1024]Frame = undefined,
    depth: u16 = 0,
    halted: ?Halt = null,

    // -----------------------------------------------------------------------------------------
    // Registers, memory

    fn reg(c: *const Core, r: u2) u16 {
        return switch (r) {
            0 => c.cpu.ah,
            1 => c.cpu.al,
            2 => c.cpu.x,
            3 => c.cpu.y,
        };
    }
    fn setReg(c: *Core, r: u2, v: u16) void {
        switch (r) {
            0 => c.cpu.ah = v,
            1 => c.cpu.al = v,
            2 => c.cpu.x = v,
            3 => c.cpu.y = v,
        }
    }

    pub fn read(c: *Core, addr: u16) u16 {
        return @truncate(c.bus.read(addr, 16));
    }
    pub fn write(c: *Core, addr: u16, v: u16) void {
        if (addr == 0xFF52) c.cpu.ff52 = v;
        c.bus.write(addr, 16, v);
    }

    fn ea(c: *const Core, i: Insn) u16 {
        return switch (i.mode) {
            0, 1 => i.full16(),
            2 => c.cpu.x +% i.full16(),
            3 => c.cpu.y +% i.full16(),
        };
    }
    fn src(c: *Core, i: Insn) u16 {
        return if (i.mode == 0) i.full16() else c.read(c.ea(i));
    }
    fn yOff(c: *const Core, i: Insn) u16 {
        return c.cpu.y +% i.full16();
    }

    /// Whether data 0xFFE0–0xFFE4 currently alias the registers (the bus `cpu` device asks).
    pub fn aliasOn(c: *Core) bool {
        const dynamic = c.cpu.ff52 & 2 != 0;
        if (dynamic != c.alias_regs) c.touched.set(.alias_mode);
        return if (c.sel.has(.alias_mode)) dynamic else c.alias_regs;
    }

    /// Bus `cpu` device for the alias range (map class `cpu_alias`): registers, or the RAM cell.
    pub fn aliasDevice(c: *Core) common.bus.Device {
        return .{ .ctx = c, .read = aliasRead, .write = aliasWrite };
    }
    fn aliasReg(c: *Core, addr: u32) ?*u16 {
        if (!c.aliasOn()) return null;
        return switch (addr) {
            0xFFE0 => &c.cpu.ah,
            0xFFE1 => &c.cpu.al,
            0xFFE3 => &c.cpu.x,
            0xFFE4 => &c.cpu.y,
            else => null,
        };
    }
    fn aliasRead(ctx: *anyopaque, addr: u32, bits: u8) u64 {
        _ = bits;
        const c: *Core = @ptrCast(@alignCast(ctx));
        const p = c.aliasReg(addr) orelse c.bus.unitPtr(addr) orelse return 0;
        return p.*;
    }
    fn aliasWrite(ctx: *anyopaque, addr: u32, bits: u8, value: u64) void {
        _ = bits;
        const c: *Core = @ptrCast(@alignCast(ctx));
        const p = c.aliasReg(addr) orelse c.bus.unitPtr(addr) orelse return;
        p.* = @truncate(value);
    }

    // -----------------------------------------------------------------------------------------
    // Flags

    fn flag(c: *Core, f: u16) bool {
        if (c.cpu.fq & f != 0) c.unknown_flag_uses += 1;
        return c.cpu.flags & f != 0;
    }
    fn put(c: *Core, f: u16, on: bool) void {
        c.cpu.flags = if (on) c.cpu.flags | f else c.cpu.flags & ~f;
        c.cpu.fq &= ~f;
    }
    fn nz(c: *Core, v: u16) void {
        c.put(Z, v == 0);
        c.put(N, v & 0x8000 != 0);
    }
    /// A "preserve | clear" assumption on flags `mask`.
    fn keepOrClear(c: *Core, id: Id, mask: u16) void {
        // A flag already 0 but marked '?' still changes under "clear" (written 0 = known).
        if ((c.cpu.flags | c.cpu.fq) & mask == 0) return;
        c.touched.set(id);
        if (c.sel.has(id)) {
            c.cpu.flags &= ~mask;
            c.cpu.fq &= ~mask;
        }
    }
    fn unknown(c: *Core, mask: u16) void {
        c.cpu.fq |= mask;
    }

    /// FLAGS as stored to memory (XA-flags-layout).
    pub fn packFlags(c: *Core) u16 {
        c.touched.set(.flags_layout);
        const f = c.cpu.flags;
        if (!c.sel.has(.flags_layout)) return f;
        return (f & ~ZNCV) | perm(f, Z, 4) | perm(f, N, 8) | perm(f, C, 2) | perm(f, V, 1);
    }
    pub fn unpackFlags(c: *Core, w: u16) void {
        c.touched.set(.flags_layout);
        c.cpu.fq = 0;
        if (!c.sel.has(.flags_layout)) {
            c.cpu.flags = w;
            return;
        }
        c.cpu.flags = (w & ~ZNCV) | perm(w, 4, Z) | perm(w, 8, N) | perm(w, 2, C) | perm(w, 1, V);
    }
    fn perm(w: u16, from: u16, to: u16) u16 {
        return if (w & from != 0) to else 0;
    }

    // -----------------------------------------------------------------------------------------
    // Fetch and run

    /// Code word at program address `pc`, or null if no segment holds it.
    fn word(c: *Core, pc: usize) ?u16 {
        for (c.code) |s| {
            if (pc < s.base or pc - s.base >= s.words.len) continue;
            if (s.gate) |g| {
                c.touched.set(g);
                if (c.sel.has(g)) continue;
            }
            return s.words[pc - s.base];
        }
        return null;
    }

    /// Decodes the instruction at `pc` over the whole 24-bit code space (bc5-isa §8 `fetch`: a prefix
    /// chain continues into the next segment), or null if one of its words is unmapped.
    pub fn fetch(c: *Core, pc: u32) ?Insn {
        return dec.decodeAt(c, word, 1 << 24, pc);
    }

    /// Runs until a halt, or `max_steps` instructions.
    pub fn run(c: *Core, max_steps: u64) Halt {
        c.halted = null;
        var n: u64 = 0;
        while (true) : (n += 1) {
            if (c.halted) |h| return h;
            if (c.bus.stop) |s| return fromStop(s);
            if (n == max_steps) return .steps;
            c.step();
        }
    }

    pub fn fromStop(s: common.bus.Stop) Halt {
        return switch (s) {
            .fault => |a| .{ .fault = a },
            .fuel_exhausted => .fuel_exhausted,
            .tape_exhausted => .tape_exhausted,
        };
    }

    fn halt(c: *Core, h: Halt) void {
        if (c.halted == null) c.halted = h;
    }

    /// One instruction (or one sentinel check).
    pub fn step(c: *Core) void {
        const cpu = &c.cpu;
        // The ABI return address, not an ISA rule: mapped code there runs.
        if (cpu.pc == sentinel and c.depth == 0 and c.word(sentinel) == null) return c.halt(.returned);
        // Instruction fuel, charged to the bus like every data access (harness/isolate.zig).
        if (c.bus.fuel == 0) return c.bus.halt(.fuel_exhausted);
        c.bus.fuel -= 1;
        const pc = cpu.pc;
        const i = c.fetch(pc) orelse return c.halt(.{ .fault = pc });
        const cw = pc + i.n - 1;
        const nxt = (pc + i.n) & 0xFFFFFF;
        c.steps += 1;
        cpu.pc = nxt;
        switch (i.m) {
            .ld => {
                const v = c.src(i);
                c.setReg(i.reg, v);
                c.nz(v);
                c.keepOrClear(.ldst_v, V);
            },
            .st => {
                const v = c.reg(i.reg);
                c.write(c.ea(i), v);
                c.nz(v);
                c.keepOrClear(.ldst_v, V);
            },
            .add, .addc => {
                const a = c.reg(i.reg);
                const b = c.src(i);
                const cin: u32 = if (i.m == .addc and c.flag(C)) 1 else 0;
                const wide = @as(u32, a) + b + cin;
                const r: u16 = @truncate(wide);
                c.setReg(i.reg, r);
                c.arith(i.m == .addc, r, wide > 0xFFFF, (a ^ r) & (b ^ r) & 0x8000 != 0);
            },
            .sub, .subc, .cmp => {
                const a = c.reg(i.reg);
                const b = c.src(i);
                const bin: u32 = if (i.m == .subc and c.flag(C)) 1 else 0;
                const r: u16 = @truncate(@as(u32, a) -% b -% bin);
                if (i.m != .cmp) c.setReg(i.reg, r);
                c.arith(i.m == .subc, r, @as(u32, a) < @as(u32, b) + bin, (a ^ b) & (a ^ r) & 0x8000 != 0);
            },
            .nadd => {
                const a = c.reg(i.reg);
                const b = c.src(i);
                const r = b -% a;
                c.setReg(i.reg, r);
                c.touched.set(.nadd_c); // the two readings always disagree
                const carry = b >= a;
                c.arith(false, r, if (c.sel.has(.nadd_c)) !carry else carry, (b ^ a) & (b ^ r) & 0x8000 != 0);
            },
            .@"or", .@"and", .xor => {
                const a = c.reg(i.reg);
                const b = c.src(i);
                const r = switch (i.m) {
                    .@"or" => a | b,
                    .@"and" => a & b,
                    else => a ^ b,
                };
                c.setReg(i.reg, r);
                c.nz(r);
                if (i.m == .xor) c.keepOrClear(.xor_c, C) else c.keepOrClear(.tst_and_or_cv, C | V);
            },
            .tst => {
                c.nz(c.src(i));
                c.keepOrClear(.tst_and_or_cv, C | V);
            },
            .smult, .umult => {
                const b = c.src(i);
                const p: u32 = if (i.m == .umult)
                    @as(u32, cpu.al) * b
                else
                    @bitCast(@as(i32, @as(i16, @bitCast(cpu.al))) * @as(i16, @bitCast(b)));
                cpu.ah = @truncate(p >> 16);
                cpu.al = @truncate(p);
                c.unknown(ZNCV);
            },
            .sdiv, .udiv => c.divide(i.m == .sdiv, c.src(i)),
            .asl, .asr, .lsr => c.shift(i.m, c.src(i)),
            .bsr => {
                const t = c.target(i, cw);
                cpu.x = @truncate(nxt);
                cpu.xh = @truncate(nxt >> 16);
                c.call(t, nxt);
            },
            .bra, .blt, .bpl, .bmi, .bne, .beq, .bcc, .bcs, .bgt, .bge, .ble, .bcz => {
                // shortcut: a not-taken indirect conditional branch reads no memory (none occur in clean code, bc5-isa 2.2).
                if (c.taken(i.m)) c.jump(c.target(i, cw));
            },
            .rts => c.jump(@as(u32, cpu.xh) << 16 | cpu.x),
            .brxl => c.jump((cw + 1 + cpu.x) & 0xFFFFFF),
            .bc => c.blockCopy(false, pc),
            .enter => {
                // Live Y and X after each store (§8 order): a store through the Y/X alias moves them.
                c.write(cpu.y -% 1, cpu.xh);
                c.write(cpu.y -% 2, cpu.x);
                cpu.y +%= i.full16();
            },
            .leave => {
                cpu.y -%= i.full16();
                cpu.xh = c.read(cpu.y -% 1);
                const lo = c.read(cpu.y -% 2);
                if (lo != cpu.x) c.touched.set(.leave_x);
                if (!c.sel.has(.leave_x)) cpu.x = lo;
                c.jump(@as(u32, cpu.xh) << 16 | lo);
            },
            .st_flags, .st_FLAGS => c.write(c.yOff(i), c.packFlags()),
            .st_ux, .st_UX => c.write(c.yOff(i), cpu.ux),
            .st_uy, .st_UY => c.write(c.yOff(i), cpu.uy),
            .st_xh, .st_XH => c.write(c.yOff(i), cpu.xh),
            .ld_flags, .ld_FLAGS => c.unpackFlags(c.read(c.yOff(i))),
            .ld_ux, .ld_UX => cpu.ux = c.read(c.yOff(i)),
            .ld_uy, .ld_UY => cpu.uy = c.read(c.yOff(i)),
            .ld_xh, .ld_XH => cpu.xh = c.read(c.yOff(i)),
            .rti => c.rti(c.yOff(i)),
            .nop => {},
            .brk => c.halt(.{ .trap = .brk }),
            .sleep => {
                // Function tests never raise an IRQ: sleep returns at once (bc5-isa 6).
                c.sleeps += 1;
                if (c.stop_on_sleep) c.halt(.sleep);
            },
            .op0u => switch (i.w) {
                0xFD09 => c.blockCopy(true, pc),
                else => if (i.reg == 3 and i.mode == 1) c.rti(c.yOff(i)) else c.illegal(pc),
            },
            // 0 uses in either image (bc5-isa 2.1, 2.3): executing one is a fault, not a guess.
            .sif, .rol, .ror => c.illegal(pc),
        }
        if (c.depth > 0) {
            const f = c.frames[c.depth - 1];
            if (cpu.pc == f.ra and cpu.y == f.y) c.depth -= 1;
        }
    }

    fn illegal(c: *Core, pc: u32) void {
        c.cpu.pc = pc;
        c.halt(.{ .trap = .illegal });
    }

    fn arith(c: *Core, with_carry: bool, r: u16, carry: bool, ovf: bool) void {
        const z_old = c.cpu.flags & Z != 0;
        c.nz(r);
        if (with_carry and !z_old and r == 0) {
            c.touched.set(.carry_z);
            if (c.sel.has(.carry_z)) c.put(Z, false);
        }
        c.put(C, carry);
        c.put(V, ovf);
    }

    fn taken(c: *Core, m: dec.Mnem) bool {
        return switch (m) {
            .bra => true,
            .blt => c.flag(N) != c.flag(V),
            .bpl => !c.flag(N),
            .bmi => c.flag(N),
            .bne => !c.flag(Z),
            .beq => c.flag(Z),
            .bcc => !c.flag(C),
            .bcs => c.flag(C),
            .bgt => !c.flag(Z) and c.flag(N) == c.flag(V),
            .bge => c.flag(N) == c.flag(V),
            .ble => c.flag(Z) or c.flag(N) != c.flag(V),
            .bcz => c.flag(C) or c.flag(Z),
            else => unreachable,
        };
    }

    /// Branch/call target (bc5-isa §1): relative to the consuming word, or `XH:SRC` memory-indirect
    /// (modes 1, 3), mode 2 per XA-mode2-ind. Evaluated before bsr overwrites X/XH.
    fn target(c: *Core, i: Insn, cw: u32) u32 {
        const hi = @as(u32, c.cpu.xh) << 16;
        return switch (i.mode) {
            0 => @as(u32, @bitCast(@as(i32, @bitCast(cw)) +% i.full)) & 0xFFFFFF,
            1, 3 => hi | c.read(c.ea(i)),
            2 => blk: {
                c.touched.set(.mode2_ind);
                break :blk hi | if (c.sel.has(.mode2_ind)) c.read(c.ea(i)) else c.ea(i);
            },
        };
    }

    fn jump(c: *Core, t: u32) void {
        c.cpu.pc = t & 0xFFFFFF;
    }

    /// bsr after X/XH hold the return address: E5 record, replay intercept, call tracking.
    fn call(c: *Core, t: u32, ra: u32) void {
        const at_f = hooks.depth + c.depth == hooks.record_depth;
        if (at_f and (hooks.recording or hooks.intercept != null)) {
            var buf: [16]hooks.Arg = undefined;
            const n = @min(c.argWords(t), buf.len);
            for (buf[0..n], 0..) |*a, k| a.* = .{ .bits = 16, .value = switch (k) {
                0 => c.cpu.al,
                1 => c.cpu.ah,
                else => c.read(c.cpu.y +% @as(u16, @intCast(k - 2))),
            } };
            const target_addr = byteAddr(t);
            if (hooks.recording) hooks.recordCall(target_addr, buf[0..n]);
            if (hooks.intercept) |f| if (f(target_addr, buf[0..n])) |r| {
                c.cpu.al = @truncate(r);
                c.cpu.ah = @truncate(r >> 16);
                c.cpu.pc = ra; // replayed: as if the callee returned at once
                return;
            };
        }
        // shortcut: no HLE thunks (§5.6): a translated callee still runs as original code here; add the fn_table dispatch (unless hooks.force.isForced) with the first integrated-mode BC5 unit.
        if (c.depth == c.frames.len) return c.halt(.{ .trap = .call_depth });
        c.frames[c.depth] = .{ .ra = ra, .y = c.cpu.y };
        c.depth += 1;
        c.jump(t);
    }

    fn divide(c: *Core, signed: bool, d: u16) void {
        const cpu = &c.cpu;
        const a: u32 = @as(u32, cpu.ah) << 16 | cpu.al;
        const chosen = divTrunc(signed, a, d, cpu.al);
        const alt = divFloorSat(signed, a, d);
        if (chosen[0] != alt[0] or chosen[1] != alt[1]) c.touched.set(.div_edge);
        const qr = if (c.sel.has(.div_edge)) alt else chosen;
        cpu.al = qr[0];
        cpu.ah = qr[1];
        c.unknown(ZNCV);
    }

    fn shift(c: *Core, m: dec.Mnem, count: u16) void {
        const cpu = &c.cpu;
        const a: u32 = @as(u32, cpu.ah) << 16 | cpu.al;
        if (count >= 32) c.touched.set(.shift_count);
        const n: u32 = if (c.sel.has(.shift_count)) count & 31 else count;
        var r = a;
        if (n != 0) {
            const last: bool = switch (m) {
                .asl => if (n <= 32) (a >> @intCast(32 - n)) & 1 != 0 else false,
                .asr => if (n <= 32) (a >> @intCast(n - 1)) & 1 != 0 else a & 0x8000_0000 != 0,
                else => if (n <= 32) (a >> @intCast(n - 1)) & 1 != 0 else false,
            };
            r = switch (m) {
                .asl => if (n >= 32) 0 else a << @intCast(n),
                .asr => @bitCast(@as(i32, @bitCast(a)) >> @intCast(@min(n, 31))),
                else => if (n >= 32) 0 else a >> @intCast(n),
            };
            c.put(C, last);
        }
        cpu.ah = @truncate(r >> 16);
        cpu.al = @truncate(r);
        const z32 = r == 0;
        const n32 = r & 0x8000_0000 != 0;
        const z16 = cpu.al == 0;
        const n16 = cpu.al & 0x8000 != 0;
        if (z32 != z16 or n32 != n16) c.touched.set(.shift_nz);
        const al = c.sel.has(.shift_nz);
        c.put(Z, if (al) z16 else z32);
        c.put(N, if (al) n16 else n32);
        // bc5-isa §2.1: asl N/Z are '?' (asr/lsr give nz); V is '?' for all three.
        c.unknown(if (m == .asl) Z | N | V else V);
    }

    /// Words after which a block copy is abandoned as `illegal` (xap_ref.py's bound). A copy only runs
    /// past 0xFFFF words when it rewrites AL/X/Y/AH through the register aliases.
    pub const copy_limit: u32 = 1 << 20;

    /// `bc` (to M[Y], Y advances) or FD09 (to M[AH], AH advances): count AL, source X (bc5-isa §2.3).
    /// NZCV are unknown afterwards (§4, §10). A copy that hits `copy_limit` traps `illegal` with the
    /// registers restored; its memory writes stay (the bus has no undo; the snippet runner restores RAM).
    fn blockCopy(c: *Core, fd09: bool, pc: u32) void {
        const cpu = &c.cpu;
        const saved = cpu.*;
        if (cpu.al == 0) {
            if (!fd09) {
                c.touched.set(.bc_zero);
                if (c.sel.has(.bc_zero)) {
                    c.write(cpu.y, c.read(cpu.x));
                    cpu.x +%= 1;
                    cpu.y +%= 1;
                }
            }
            return c.unknown(ZNCV);
        }
        var n: u32 = 0;
        while (cpu.al != 0 and c.bus.stop == null) : (n += 1) {
            if (n == copy_limit) {
                cpu.* = saved;
                return c.illegal(pc);
            }
            const v = c.read(cpu.x);
            if (fd09) {
                c.write(cpu.ah, v);
                cpu.ah +%= 1;
            } else {
                c.write(cpu.y, v);
                cpu.y +%= 1;
            }
            cpu.x +%= 1;
            cpu.al -%= 1;
        }
        if (fd09) {
            c.touched.set(.fd09_final);
            if (c.sel.has(.fd09_final)) {
                cpu.x = saved.x;
                cpu.ah = saved.ah;
            }
        }
        c.unknown(ZNCV);
    }

    /// `rti @(o,Y)`: FLAGS = M[Y+o], PC from the next two words (XA-irq-entry).
    fn rti(c: *Core, a: u16) void {
        c.touched.set(.irq_entry);
        c.unpackFlags(c.read(a));
        const w1 = c.read(a +% 1);
        const w2 = c.read(a +% 2);
        const pc = if (c.sel.has(.irq_entry)) @as(u32, w2) << 16 | w1 else @as(u32, w1) << 16 | w2;
        c.jump(pc);
    }

    /// Hardware interrupt entry (hypothesis H, XA-irq-entry): only when FLAGS bit 4 is set. The
    /// interrupted FLAGS go to M[Y-33] and the PC to M[Y-32..-31]; IE is cleared; PC = word 2.
    pub fn interrupt(c: *Core, base: u32) bool {
        const cpu = &c.cpu;
        if (cpu.flags & IE == 0) return false;
        c.touched.set(.irq_entry);
        const y = cpu.y;
        const hi: u16 = @truncate(cpu.pc >> 16);
        const lo: u16 = @truncate(cpu.pc);
        c.write(y -% 33, c.packFlags());
        c.write(y -% 32, if (c.sel.has(.irq_entry)) lo else hi);
        c.write(y -% 31, if (c.sel.has(.irq_entry)) hi else lo);
        cpu.flags &= ~IE;
        cpu.pc = base + 2;
        return true;
    }
};

fn twoWords(target: u32) u8 {
    _ = target;
    return 2;
}

/// Registry/rt.call address (image byte address) of a program address in the main code range.
pub fn byteAddr(pc: u32) u32 {
    return (pc -% image_base) *% 2;
}
/// Program address of a registry byte address.
pub fn progAddr(byte_addr: u32) u32 {
    return byte_addr / 2 + image_base;
}

/// XA-div-edge chosen reading: C-style truncating division, quotient cut to 16 bits;
/// divide by zero leaves AL = 0xFFFF and AH = the old AL (low dividend word).
fn divTrunc(signed: bool, a: u32, d: u16, al: u16) [2]u16 {
    if (d == 0) return .{ 0xFFFF, al };
    if (!signed) return .{ @truncate(a / d), @truncate(a % d) };
    const sa: i64 = @as(i32, @bitCast(a));
    const sd: i64 = @as(i16, @bitCast(d));
    return .{ @truncate(@as(u64, @bitCast(@divTrunc(sa, sd)))), @truncate(@as(u64, @bitCast(@rem(sa, sd)))) };
}

/// XA-div-edge alternative: floored division, quotient saturated to 16 bits, /0 gives 0, 0.
fn divFloorSat(signed: bool, a: u32, d: u16) [2]u16 {
    if (d == 0) return .{ 0, 0 };
    if (!signed) return .{ @truncate(@min(a / d, 0xFFFF)), @truncate(a % d) };
    const sa: i64 = @as(i32, @bitCast(a));
    const sd: i64 = @as(i16, @bitCast(d));
    const q = std.math.clamp(@divFloor(sa, sd), -0x8000, 0x7FFF);
    return .{ @truncate(@as(u64, @bitCast(q))), @truncate(@as(u64, @bitCast(@mod(sa, sd)))) };
}
