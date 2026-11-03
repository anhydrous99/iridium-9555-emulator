//! SPARC V8 / LEON integer unit (ARCHITECTURE §6.2): register windows (NWINDOWS configurable;
//! window modes `real` and `virtual`, see `Virtual`),
//! PSR/WIM/TBR/Y, PC/nPC with delay slots and annulment, precise traps through TBR into the
//! firmware's own handlers, `rett`, `ticc`, `mulscc`, mul/div, `ldd`/`std`, and ASI accesses.
//! Every data access goes through the common `Bus` (big-endian bytes, strict log, tape/device, fuel);
//! each instruction costs one bus fuel unit, like the toy emulator. Instruction fetch reads the
//! backing arrays directly (not logged).
//!
//! No FPU or coprocessor is fitted to this profile (fp_disabled / cp_disabled traps, EF=EC=0).
//! Integer operations and external interrupt levels follow the SPARC V8 manual, revision
//! SAV080SI9308, sections 7.4, B.7-B.8 and B.14-B.16 (https://research.swtch.com/sparcv8.pdf).
//! shortcut: no predecode cache; decoding is a table lookup per instruction. Add one if a profile shows it.
const std = @import("std");
const common = @import("common");
const bus_mod = common.bus;
const decode = @import("decode.zig");
const Insn = decode.Insn;

pub const Bus = bus_mod.Bus(bus_mod.sparc);

pub const max_windows = 32;

/// Trap types (SPARC V8 manual table 7-1) used here.
pub const tt = struct {
    pub const instruction_access_exception: u8 = 0x01;
    pub const illegal_instruction: u8 = 0x02;
    pub const privileged_instruction: u8 = 0x03;
    pub const fp_disabled: u8 = 0x04;
    pub const window_overflow: u8 = 0x05;
    pub const window_underflow: u8 = 0x06;
    pub const mem_address_not_aligned: u8 = 0x07;
    pub const data_access_exception: u8 = 0x09;
    pub const tag_overflow: u8 = 0x0A;
    pub const cp_disabled: u8 = 0x24;
    pub const division_by_zero: u8 = 0x2A;
    pub const trap_instruction: u8 = 0x80;
};

pub const psr_bits = struct {
    pub const cwp: u32 = 0x1F;
    pub const et: u32 = 0x20;
    pub const ps: u32 = 0x40;
    pub const s: u32 = 0x80;
    pub const pil: u32 = 0xF00;
    pub const c: u32 = 1 << 20;
    pub const v: u32 = 1 << 21;
    pub const z: u32 = 1 << 22;
    pub const n: u32 = 1 << 23;
    pub const icc: u32 = 0xF << 20;
    /// What `wr %psr` can change: icc, PIL, S, PS, ET, CWP (EF/EC stay 0: no FPU, no coprocessor).
    pub const writable: u32 = icc | pil | s | ps | et | cwp;
};

/// The whole architectural state; plain data, so it is a snapshot part.
pub const Regs = extern struct {
    g: [8]u32 = @splat(0),
    /// Window w: outs at [16w, 16w+8), locals at [16w+8, 16w+16). The ins of w are the outs of w+1.
    win: [max_windows * 16]u32 = @splat(0),
    pc: u32 = 0,
    npc: u32 = 4,
    /// impl/ver (bits 31:24) are fixed per CPU model; LEON2 = 0 (the default: the Trx reset code takes
    /// its LEON2 path, trx-arch §2), LEON3 = 0xF3 (QEMU leon3_generic; `sparc boot --cpu leon3`).
    /// Which one the part is is [A9 mod H]: the images' .data holds the LEON3 marker 3 at 0x7000200C.
    psr: u32 = psr_bits.s,
    wim: u32 = 0,
    tbr: u32 = 0,
    y: u32 = 0,
    /// NWINDOWS, 2..32. Default 8 [unk: NOTES O5].
    nwin: u32 = 8,
    /// LEON cache control register (ASI 2, address 0).
    ccr: u32 = 0,
};

/// Why `step` stopped the run.
pub const Exit = union(enum) {
    /// A trap with ET=0 put the processor into error mode (trap type).
    error_mode: u8,
    /// The bus stopped the run (fault, fuel, tape).
    stop: bus_mod.Stop,
};

/// Window mode `virtual` (ARCHITECTURE §6.2): unbounded windows instead of NWINDOWS × 16. `save` and
/// traps never overflow; `restore` and `rett` never underflow: a window that is not held is filled
/// from its save area (16 words at its %sp), as the firmware's underflow handler does. `ta 3` stores
/// every held caller window to its save area instead of entering the firmware's flush handler. WIM
/// is a plain register, and PSR.CWP reads as the window index mod NWINDOWS (what `real` mode shows).
/// Its state lives outside `Regs`, so it is for system runs (boot), not snapshotted function tests.
pub const Virtual = struct {
    /// Ring of (outs, locals) blocks like `Regs.win`; window k's ins are block k+1's outs. When the
    /// held windows fill it, the oldest one is stored to its save area, so the depth is unbounded.
    pub const ring = 1024;
    win: [ring * 16]u32 = @splat(0),
    /// Current window index (save counts down) and the highest window held in `win` (>= cur).
    cur: i64 = 0,
    top: i64 = 0,
};

pub const Cpu = struct {
    r: *Regs,
    bus: *Bus,
    /// Called when execution arrives at the target of a `call`/`jmpl …,%o7` (after the delay slot),
    /// with the call depth before the callee is entered. It may redirect pc/npc (intercept, HLE).
    on_call: ?*const fn (c: *Cpu, target: u32, depth: u32) void = null,
    pending_call: ?u32 = null,
    /// Shadow call stack for `on_call`'s depth, kept only while a hook is set (a multitasking
    /// system run never pops the frames of switched-out tasks). Allocated from the bus's gpa.
    frames: std.ArrayList(Frame) = .empty,
    /// Window mode `virtual` when set (see `virtualWindows`); null = `real`.
    virt: ?*Virtual = null,
    /// ASI 1 (forced cache miss) accesses go here when set (the Trx flash command interface);
    /// otherwise they are plain memory accesses on the bus.
    asi1: ?bus_mod.Device = null,
    /// Externally asserted interrupt request level; 0 deasserts it. The source owns acknowledgement.
    irl: u4 = 0,
    /// LEON ASR19 idle; external clocks still run while the instruction pipeline waits for an IRQ.
    sleeping: bool = false,

    /// An active call: where it returns to (%o7+8 at arrival) and the caller's %sp then. A frame
    /// ends when the pc reaches `ret` (or `ret+4`) with that %sp again, i.e. back in the caller's
    /// window: a branch to `ret` inside a deeper frame of the same function is not a return.
    pub const Frame = struct { ret: u32, sp: u32 };

    pub fn depth(c: *const Cpu) u32 {
        return @intCast(c.frames.items.len);
    }

    pub fn deinit(c: *Cpu) void {
        c.frames.deinit(c.bus.gpa);
    }

    pub fn get(c: *const Cpu, n: u5) u32 {
        if (n < 8) return c.r.g[n];
        return c.cell(n).*;
    }

    pub fn set(c: *Cpu, n: u5, v: u32) void {
        if (n == 0) return;
        if (n < 8) c.r.g[n] = v else c.cell(n).* = v;
    }

    /// Storage of windowed register n (8..31) of the current window.
    fn cell(c: *const Cpu, n: u5) *u32 {
        const up: u32 = if (n < 24) 0 else 1; // the ins are the next window's outs
        const off = if (n < 24) n - 8 else n - 24;
        if (c.virt) |v| return &v.win[@as(usize, @intCast(@mod(v.cur + up, Virtual.ring))) * 16 + off];
        const w: u32 = c.r.psr & psr_bits.cwp;
        return &c.r.win[((w + up) % c.r.nwin) * 16 + off];
    }

    /// Switches to window mode `virtual`, keeping the current window's registers (callers' windows
    /// are not carried over: use it at reset, before any `save`).
    pub fn virtualWindows(c: *Cpu, v: *Virtual) void {
        var cur: [24]u32 = undefined;
        for (&cur, 8..) |*x, n| x.* = c.get(@intCast(n));
        v.* = .{ .cur = c.cwp(), .top = c.cwp() };
        c.virt = v;
        for (cur, 8..) |x, n| c.set(@intCast(n), x);
    }

    /// The window next to the current one: d = -1 (save, trap) or +1 (restore, rett), mod NWINDOWS.
    fn neighbour(c: *const Cpu, d: i2) u32 {
        return if (d < 0) (c.cwp() + c.r.nwin - 1) % c.r.nwin else (c.cwp() + 1) % c.r.nwin;
    }

    /// Moves the current window by d. `real`: CWP only (WIM was checked by the caller). `virtual`:
    /// may store the oldest held window (ring full) or fill the new one from its save area.
    fn window(c: *Cpu, d: i2) ?Exit {
        const v = c.virt orelse {
            c.setCwp(c.neighbour(d));
            return null;
        };
        v.cur += d;
        while (v.top - v.cur > Virtual.ring - 2) {
            c.saveArea(v, v.top, true);
            v.top -= 1;
        }
        c.setCwp(@intCast(@mod(v.cur, c.r.nwin)));
        if (v.cur > v.top) {
            c.saveArea(v, v.cur, false);
            v.top = v.cur;
        }
        if (c.bus.stop) |s| return .{ .stop = s };
        return null;
    }

    /// Stores (or loads) window k's locals and ins to (from) its save area [%sp of k, +64).
    fn saveArea(c: *Cpu, v: *Virtual, k: i64, store: bool) void {
        const b: usize = @intCast(@mod(k, Virtual.ring));
        const nb: usize = @intCast(@mod(k + 1, Virtual.ring));
        const sp = v.win[b * 16 + 6];
        for (0..16) |j| {
            const r = if (j < 8) &v.win[b * 16 + 8 + j] else &v.win[nb * 16 + j - 8];
            const a = sp +% 4 * @as(u32, @intCast(j));
            if (store) c.bus.write(a, 32, r.*) else r.* = @truncate(c.bus.read(a, 32));
        }
    }

    pub fn cwp(c: *const Cpu) u32 {
        return c.r.psr & psr_bits.cwp;
    }

    fn setCwp(c: *Cpu, w: u32) void {
        c.r.psr = (c.r.psr & ~psr_bits.cwp) | w;
    }

    fn icc(c: *Cpu, n: bool, z: bool, v: bool, carry: bool) void {
        c.r.psr = (c.r.psr & ~psr_bits.icc) |
            (if (n) psr_bits.n else 0) | (if (z) psr_bits.z else 0) |
            (if (v) psr_bits.v else 0) | (if (carry) psr_bits.c else 0);
    }

    fn logicIcc(c: *Cpu, r: u32) void {
        c.icc(r >> 31 != 0, r == 0, false, false);
    }

    fn carryIn(c: *const Cpu) u32 {
        return @intFromBool(c.r.psr & psr_bits.c != 0);
    }

    /// Takes trap `t` (V8 §7.4), or enters error mode if traps are disabled.
    pub fn trap(c: *Cpu, t: u8) ?Exit {
        c.r.tbr = (c.r.tbr & 0xFFFF_F000) | (@as(u32, t) << 4);
        if (c.r.psr & psr_bits.et == 0) return .{ .error_mode = t };
        const s = c.r.psr & psr_bits.s != 0;
        c.r.psr = (c.r.psr & ~(psr_bits.et | psr_bits.ps)) | psr_bits.s | (if (s) psr_bits.ps else 0);
        if (c.window(-1)) |e| return e;
        c.set(17, c.r.pc); // %l1
        c.set(18, c.r.npc); // %l2
        c.r.pc = c.r.tbr;
        c.r.npc = c.r.tbr +% 4;
        return null;
    }

    fn halt(c: *Cpu, s: bus_mod.Stop) Exit {
        c.bus.halt(s);
        return .{ .stop = c.bus.stop.? };
    }

    /// Executes one instruction. Returns why the run must stop, or null.
    pub fn step(c: *Cpu) ?Exit {
        const b = c.bus;
        if (b.stop) |s| return .{ .stop = s };
        c.popReturns();
        if (c.pending_call) |t| if (c.r.pc == t) {
            c.pending_call = null;
            if (c.on_call) |f| {
                const d = c.depth();
                c.frames.append(b.gpa, .{ .ret = c.get(15) +% 8, .sp = c.get(14) }) catch @panic("sparc: shadow call stack: out of memory");
                f(c, t, d);
                if (b.stop) |s| return .{ .stop = s };
                c.popReturns(); // an intercept returns at once: pc is the return address now
            }
        };
        if (b.fuel == 0) return c.halt(.fuel_exhausted);
        b.fuel -= 1;
        if (c.irl != 0 and c.r.psr & psr_bits.et != 0 and
            (c.irl == 15 or c.irl > (c.r.psr & psr_bits.pil) >> 8))
        {
            c.sleeping = false;
            return c.trap(0x10 + @as(u8, c.irl));
        }
        if (c.sleeping) return null;
        const pc = c.r.pc;
        if (pc & 3 != 0) return c.trap(tt.mem_address_not_aligned);
        const raw = c.fetch(pc) orelse return c.halt(.{ .fault = pc });
        const e = c.exec(decode.decode(raw));
        if (e) |x| return x;
        if (b.stop) |s| return .{ .stop = s };
        return null;
    }

    /// Ends the frames the pc has returned from. More than one at once only for tail calls (`call g;
    /// restore` or the leaf `mov %o7,%g1; call g; mov %g1,%o7`): g's frame has the caller's ret and %sp.
    fn popReturns(c: *Cpu) void {
        while (c.frames.getLastOrNull()) |top| {
            // +4: struct-return callers are resumed at call+12 (`jmp %i7+12`)
            if ((c.r.pc != top.ret and c.r.pc != top.ret +% 4) or c.get(14) != top.sp) break;
            _ = c.frames.pop();
        }
    }

    fn fetch(c: *Cpu, pc: u32) ?u32 {
        var w: u32 = 0;
        for (0..4) |k| {
            const p = c.bus.unitPtr(pc +% @as(u32, @intCast(k))) orelse return null;
            w = w << 8 | p.*;
        }
        return w;
    }

    /// Runs until pc == `until` (not executed), a stop, or error mode.
    pub fn run(c: *Cpu, until: u32) ?Exit {
        while (c.r.pc != until) if (c.step()) |e| return e;
        return null;
    }

    fn advance(c: *Cpu) void {
        c.r.pc = c.r.npc;
        c.r.npc +%= 4;
    }

    fn exec(c: *Cpu, i: Insn) ?Exit {
        const a = c.get(i.rs1());
        const bv: u32 = if (i.imm()) @bitCast(i.simm13()) else c.get(i.rs2());
        const P = psr_bits;
        const priv = c.r.psr & P.s != 0;
        switch (i.op) {
            .call => {
                const target = c.r.pc +% i.disp30();
                c.set(15, c.r.pc);
                c.r.pc = c.r.npc;
                c.r.npc = target;
                c.pending_call = target;
                return null;
            },
            .bicc => {
                const taken = condTrue(c.r.psr, i.cond());
                const target = c.r.pc +% @as(u32, @bitCast(i.disp22()));
                if (taken and i.annul() and i.cond() == 8) {
                    c.r.pc = target;
                    c.r.npc = target +% 4;
                } else if (taken) {
                    c.r.pc = c.r.npc;
                    c.r.npc = target;
                } else if (i.annul()) {
                    c.r.pc = c.r.npc +% 4;
                    c.r.npc +%= 8;
                } else c.advance();
                return null;
            },
            .sethi => c.set(i.rd(), @as(u32, i.imm22()) << 10),
            .unimp, .illegal => return c.trap(tt.illegal_instruction),
            .fbfcc, .fpop1, .fpop2, .ldf, .ldfsr, .lddf, .stf, .stfsr, .stdfq, .stdf => return c.trap(tt.fp_disabled),
            .cbccc, .cpop1, .cpop2, .ldc, .ldcsr, .lddc, .stc, .stcsr, .stdcq, .stdc => return c.trap(tt.cp_disabled),

            .add => c.set(i.rd(), a +% bv),
            .addcc => {
                const r = a +% bv;
                c.icc(r >> 31 != 0, r == 0, ((a ^ ~bv) & (a ^ r)) >> 31 != 0, ((a & bv) | ((a | bv) & ~r)) >> 31 != 0);
                c.set(i.rd(), r);
            },
            .addx, .addxcc => {
                const s = @as(u64, a) + bv + c.carryIn();
                const r: u32 = @truncate(s);
                if (i.op == .addxcc) c.icc(r >> 31 != 0, r == 0, ((a ^ ~bv) & (a ^ r)) >> 31 != 0, s >> 32 != 0);
                c.set(i.rd(), r);
            },
            .sub => c.set(i.rd(), a -% bv),
            .subcc => {
                const r = a -% bv;
                c.icc(r >> 31 != 0, r == 0, ((a ^ bv) & (a ^ r)) >> 31 != 0, a < bv);
                c.set(i.rd(), r);
            },
            .subx, .subxcc => {
                const cin = c.carryIn();
                const r = a -% bv -% cin;
                if (i.op == .subxcc) c.icc(r >> 31 != 0, r == 0, ((a ^ bv) & (a ^ r)) >> 31 != 0, @as(u64, a) < @as(u64, bv) + cin);
                c.set(i.rd(), r);
            },
            .taddcc, .taddcctv, .tsubcc, .tsubcctv => {
                const sub = i.op == .tsubcc or i.op == .tsubcctv;
                const r = if (sub) a -% bv else a +% bv;
                const overflow = (if (sub) ((a ^ bv) & (a ^ r)) else ((a ^ ~bv) & (a ^ r))) >> 31 != 0 or
                    (a | bv) & 3 != 0;
                if (overflow and (i.op == .taddcctv or i.op == .tsubcctv)) return c.trap(tt.tag_overflow);
                const carry = if (sub) a < bv else ((a & bv) | ((a | bv) & ~r)) >> 31 != 0;
                c.icc(r >> 31 != 0, r == 0, overflow, carry);
                c.set(i.rd(), r);
            },
            .@"and", .andcc, .@"or", .orcc, .xor, .xorcc, .andn, .andncc, .orn, .orncc, .xnor, .xnorcc => {
                const r = switch (i.op) {
                    .@"and", .andcc => a & bv,
                    .@"or", .orcc => a | bv,
                    .xor, .xorcc => a ^ bv,
                    .andn, .andncc => a & ~bv,
                    .orn, .orncc => a | ~bv,
                    else => ~(a ^ bv),
                };
                if (i.op3() & 0x10 != 0) c.logicIcc(r);
                c.set(i.rd(), r);
            },
            .umul, .umulcc, .smul, .smulcc => {
                const p: u64 = if (i.op == .umul or i.op == .umulcc)
                    @as(u64, a) * bv
                else
                    @bitCast(@as(i64, @as(i32, @bitCast(a))) * @as(i32, @bitCast(bv)));
                const r: u32 = @truncate(p);
                c.r.y = @truncate(p >> 32);
                if (i.op == .umulcc or i.op == .smulcc) c.logicIcc(r);
                c.set(i.rd(), r);
            },
            .udiv, .udivcc, .sdiv, .sdivcc => {
                if (bv == 0) return c.trap(tt.division_by_zero);
                const dividend = @as(u64, c.r.y) << 32 | a;
                var v = false;
                var r: u32 = undefined;
                if (i.op == .udiv or i.op == .udivcc) {
                    const q = dividend / bv;
                    v = q > 0xFFFF_FFFF;
                    r = if (v) 0xFFFF_FFFF else @truncate(q);
                } else {
                    const x: i64 = @bitCast(dividend);
                    const d: i64 = @as(i32, @bitCast(bv));
                    const q: i64 = if (x == std.math.minInt(i64) and d == -1) std.math.maxInt(i64) else @divTrunc(x, d);
                    v = q > std.math.maxInt(i32) or q < std.math.minInt(i32);
                    r = if (!v) @bitCast(@as(i32, @intCast(q))) else if (q > 0) 0x7FFF_FFFF else 0x8000_0000;
                }
                if (i.op == .udivcc or i.op == .sdivcc) c.icc(r >> 31 != 0, r == 0, v, false);
                c.set(i.rd(), r);
            },
            .mulscc => {
                const nv: u32 = @intFromBool((c.r.psr & P.n != 0) != (c.r.psr & P.v != 0));
                const op1 = nv << 31 | a >> 1;
                const op2: u32 = if (c.r.y & 1 != 0) bv else 0;
                const r = op1 +% op2;
                c.icc(r >> 31 != 0, r == 0, ((op1 ^ ~op2) & (op1 ^ r)) >> 31 != 0, ((op1 & op2) | ((op1 | op2) & ~r)) >> 31 != 0);
                c.r.y = (a & 1) << 31 | c.r.y >> 1;
                c.set(i.rd(), r);
            },
            .sll => c.set(i.rd(), a << @truncate(bv)),
            .srl => c.set(i.rd(), a >> @truncate(bv)),
            .sra => c.set(i.rd(), @bitCast(@as(i32, @bitCast(a)) >> @truncate(bv))),

            .rdasr => switch (i.rs1()) {
                0 => c.set(i.rd(), c.r.y),
                15 => {}, // stbar
                // LEON3 %asr17: processor index 0, bit 8 = V8 mul/div present, NWINDOWS-1 (QEMU: 0x107)
                17 => c.set(i.rd(), 0x100 | (c.r.nwin - 1)),
                else => return c.trap(tt.illegal_instruction),
            },
            .rdpsr, .rdwim, .rdtbr => {
                if (!priv) return c.trap(tt.privileged_instruction);
                c.set(i.rd(), switch (i.op) {
                    .rdpsr => c.r.psr,
                    .rdwim => c.r.wim,
                    else => c.r.tbr,
                });
            },
            .wrasr => switch (i.rd()) {
                0 => c.r.y = a ^ bv,
                19 => {
                    if (!priv) return c.trap(tt.privileged_instruction);
                    // Firmware's idle routine writes ASR19; LEON power-down resumes on an unmasked IRQ.
                    c.sleeping = true;
                },
                else => return c.trap(tt.illegal_instruction),
            },
            .wrpsr, .wrwim, .wrtbr => {
                if (!priv) return c.trap(tt.privileged_instruction);
                const v = a ^ bv;
                switch (i.op) {
                    .wrpsr => {
                        if (v & P.cwp >= c.r.nwin) return c.trap(tt.illegal_instruction);
                        if (c.virt) |vw| {
                            // shortcut: a CWP change moves the window index by the nearest distance and
                            // holds the windows passed over; the boot's writes keep CWP.
                            const n: i64 = c.r.nwin;
                            const d = @mod(@as(i64, v & P.cwp) - @as(i64, c.cwp()) + @divFloor(n, 2), n) - @divFloor(n, 2);
                            vw.cur += d;
                            vw.top = @max(vw.top, vw.cur);
                        }
                        c.r.psr = (c.r.psr & ~P.writable) | (v & P.writable);
                    },
                    .wrwim => {
                        c.r.wim = v & winMask(c.r.nwin);
                        // `virtual`: the windows `real` mode treats as valid above CWP end below the first
                        // invalid one; drop the rest (the reset code's clearing loop leaves 8 behind).
                        if (c.virt) |vw| {
                            var k: u32 = 1;
                            while (k < c.r.nwin and c.r.wim >> @intCast((c.cwp() + k) % c.r.nwin) & 1 == 0) k += 1;
                            if (k < c.r.nwin) vw.top = @min(vw.top, vw.cur + k - 1);
                        }
                    },
                    else => c.r.tbr = (v & 0xFFFF_F000) | (c.r.tbr & 0xFF0),
                }
            },

            .jmpl => {
                const target = a +% bv;
                if (target & 3 != 0) return c.trap(tt.mem_address_not_aligned);
                c.set(i.rd(), c.r.pc);
                c.r.pc = c.r.npc;
                c.r.npc = target;
                if (i.rd() == 15) c.pending_call = target;
                return null;
            },
            .rett => {
                const target = a +% bv;
                if (c.r.psr & P.et != 0) return c.trap(if (priv) tt.illegal_instruction else tt.privileged_instruction);
                if (!priv) return c.trap(tt.privileged_instruction);
                if (c.virt == null and c.r.wim >> @intCast(c.neighbour(1)) & 1 != 0) return c.trap(tt.window_underflow);
                if (target & 3 != 0) return c.trap(tt.mem_address_not_aligned);
                if (c.window(1)) |e| return e;
                const s = c.r.psr & P.ps != 0;
                c.r.psr = (c.r.psr & ~P.s) | P.et | (if (s) P.s else 0);
                c.r.pc = c.r.npc;
                c.r.npc = target;
                return null;
            },
            .ticc => if (condTrue(c.r.psr, i.cond())) {
                const n: u8 = @truncate((a +% bv) & 0x7F);
                if (n != 3 or c.virt == null) return c.trap(tt.trap_instruction + n);
                const v = c.virt.?; // `virtual`: ta 3 (flush windows) is done here
                var k = v.cur + 1;
                while (k <= v.top) : (k += 1) c.saveArea(v, k, true);
                v.top = v.cur;
                if (c.bus.stop) |s| return .{ .stop = s };
            },
            .flush => {},
            .save, .restore => {
                const d: i2 = if (i.op == .save) -1 else 1;
                if (c.virt == null and c.r.wim >> @intCast(c.neighbour(d)) & 1 != 0)
                    return c.trap(if (d < 0) tt.window_overflow else tt.window_underflow);
                if (c.window(d)) |e| return e;
                c.set(i.rd(), a +% bv);
            },

            .ld, .ldub, .lduh, .ldsb, .ldsh, .ldd, .st, .stb, .sth, .std, .ldstub, .swap => return c.mem(i, a +% bv, null),
            .lda, .lduba, .lduha, .ldsba, .ldsha, .ldda, .sta, .stba, .stha, .stda, .ldstuba, .swapa => {
                if (i.imm()) return c.trap(tt.illegal_instruction);
                if (!priv) return c.trap(tt.privileged_instruction);
                return c.mem(i, a +% bv, i.asi());
            },
        }
        c.advance();
        return null;
    }

    /// Loads and stores. `asi` null = the default data space (supervisor/user data).
    fn mem(c: *Cpu, i: Insn, addr: u32, asi: ?u8) ?Exit {
        const kind: struct { bits: u8, load: bool, signed: bool = false, double: bool = false, atomic: bool = false } = switch (i.op) {
            .ld, .lda => .{ .bits = 32, .load = true },
            .ldub, .lduba => .{ .bits = 8, .load = true },
            .lduh, .lduha => .{ .bits = 16, .load = true },
            .ldsb, .ldsba => .{ .bits = 8, .load = true, .signed = true },
            .ldsh, .ldsha => .{ .bits = 16, .load = true, .signed = true },
            .ldd, .ldda => .{ .bits = 64, .load = true, .double = true },
            .ldstub, .ldstuba => .{ .bits = 8, .load = true, .atomic = true },
            .swap, .swapa => .{ .bits = 32, .load = true, .atomic = true },
            .st, .sta => .{ .bits = 32, .load = false },
            .stb, .stba => .{ .bits = 8, .load = false },
            .sth, .stha => .{ .bits = 16, .load = false },
            else => .{ .bits = 64, .load = false, .double = true },
        };
        if (kind.double and i.rd() & 1 != 0) return c.trap(tt.illegal_instruction);
        if (addr & (kind.bits / 8 - 1) != 0) return c.trap(tt.mem_address_not_aligned);
        const space: Space = if (asi) |x| spaceOf(x) orelse return c.trap(tt.data_access_exception) else .memory;
        // Reserve both bus accesses before a side-effecting atomic read; fuel is a host limit.
        if (kind.atomic and (space == .memory or (space == .miss and c.asi1 == null)) and c.bus.fuel < 2)
            return c.halt(.fuel_exhausted);
        if (kind.load) {
            const v: u64 = switch (space) {
                .memory => c.bus.read(addr, kind.bits),
                .miss => if (c.asi1) |d| d.read(d.ctx, addr, kind.bits) & mask(kind.bits) else c.bus.read(addr, kind.bits),
                .ccr => if (addr == 0) c.r.ccr else 0,
                .cache, .flush => 0,
            };
            if (c.bus.stop != null) return null;
            if (kind.atomic) {
                const replacement: u32 = if (kind.bits == 8) 0xFF else c.get(i.rd());
                switch (space) {
                    .memory => c.bus.write(addr, kind.bits, replacement),
                    .miss => if (c.asi1) |d| d.write(d.ctx, addr, kind.bits, replacement) else c.bus.write(addr, kind.bits, replacement),
                    .ccr => if (addr == 0) {
                        c.r.ccr = replacement;
                    },
                    .cache, .flush => {},
                }
                if (c.bus.stop != null) return null;
            }
            if (kind.double) {
                c.set(i.rd(), @truncate(v >> 32));
                c.set(i.rd() + 1, @truncate(v));
            } else {
                const x: u32 = @truncate(v);
                c.set(i.rd(), if (!kind.signed) x else if (kind.bits == 8) sext(u8, x) else sext(u16, x));
            }
        } else {
            const v: u64 = if (kind.double) @as(u64, c.get(i.rd())) << 32 | c.get(i.rd() + 1) else c.get(i.rd());
            switch (space) {
                .memory => c.bus.write(addr, kind.bits, v & mask(kind.bits)),
                .miss => if (c.asi1) |d| d.write(d.ctx, addr, kind.bits, v & mask(kind.bits)) else c.bus.write(addr, kind.bits, v & mask(kind.bits)),
                .ccr => if (addr == 0) {
                    c.r.ccr = @truncate(v);
                },
                .cache, .flush => {},
            }
            if (c.bus.stop != null) return null;
        }
        c.advance();
        return null;
    }
};

/// Alternate spaces of the LEON (trx-coverage §5.4): 0x1C bypass reaches memory like 8-0xB
/// (user/supervisor instruction/data); 1 forced cache miss too, unless `Cpu.asi1` takes it; 2 is
/// cache control; 5/6/0x10/0x11 flush; 0xC-0xF cache tags/data (reads 0, writes ignored).
/// Anything else: data_access_exception, not a strict-logged access (ARCHITECTURE §3.3): no reached
/// instruction uses one, and an E4 record has no ASI field, so it would pass for a plain access.
const Space = enum { memory, miss, ccr, cache, flush };

fn spaceOf(asi: u8) ?Space {
    return switch (asi) {
        1 => .miss,
        8, 9, 0xA, 0xB, 0x1C => .memory,
        2 => .ccr,
        5, 6, 0x10, 0x11 => .flush,
        0xC, 0xD, 0xE, 0xF => .cache,
        else => null,
    };
}

fn sext(comptime T: type, x: u32) u32 {
    const S = @Int(.signed, @bitSizeOf(T));
    return @bitCast(@as(i32, @as(S, @bitCast(@as(T, @truncate(x))))));
}

fn mask(bits: u8) u64 {
    return if (bits >= 64) std.math.maxInt(u64) else (@as(u64, 1) << @intCast(bits)) - 1;
}

pub fn winMask(nwin: u32) u32 {
    return if (nwin >= 32) 0xFFFF_FFFF else (@as(u32, 1) << @intCast(nwin)) - 1;
}

pub fn condTrue(psr: u32, cnd: u4) bool {
    const n = psr & psr_bits.n != 0;
    const z = psr & psr_bits.z != 0;
    const v = psr & psr_bits.v != 0;
    const cy = psr & psr_bits.c != 0;
    const t = switch (cnd & 7) {
        0 => false,
        1 => z,
        2 => z or (n != v),
        3 => n != v,
        4 => cy or z,
        5 => cy,
        6 => n,
        else => v,
    };
    return if (cnd & 8 != 0) !t else t;
}

// ---------------------------------------------------------------------------------------------
const testing = std.testing;

const TS = struct {
    var ram: [0x1000]u8 align(4096) = @splat(0);
    var regs: Regs = .{};
    var backing = [_]bus_mod.Backing(u8){.{ .base = 0x4000_0000, .mem = &ram }};
    const map = [_]bus_mod.Range{.{ .lo = 0x4000_0000, .hi = 0x4000_0FFF, .kind = .ram }};
};

/// Puts `words` at 0x40000000 and returns a CPU ready to run them (S=1, ET=1, TBR=0x40000000).
fn setup(b: *Bus, words: []const u32) !struct { cpu: Cpu, bus: *Bus } {
    b.* = try Bus.init(testing.allocator, &TS.map, &TS.backing);
    @memset(&TS.ram, 0);
    for (words, 0..) |w, k| std.mem.writeInt(u32, TS.ram[k * 4 ..][0..4], w, .big);
    TS.regs = .{ .pc = 0x4000_0000, .npc = 0x4000_0004, .psr = psr_bits.s | psr_bits.et, .tbr = 0x4000_0000 };
    return .{ .cpu = .{ .r = &TS.regs, .bus = b }, .bus = b };
}

fn runN(c: *Cpu, n: usize) !void {
    for (0..n) |_| if (c.step()) |e| {
        std.debug.print("unexpected exit {any} at pc 0x{x}\n", .{ e, c.r.pc });
        return error.TestUnexpectedResult;
    };
}

fn testFormat3(op: u2, op3: u6, rd: u5, rs1: u5, operand: u13, immediate: bool) u32 {
    return @as(u32, op) << 30 | @as(u32, rd) << 25 | @as(u32, op3) << 19 |
        @as(u32, rs1) << 14 | @as(u32, @intFromBool(immediate)) << 13 | operand;
}

test "tagged arithmetic: tags, carry, signed overflow and precise trap-on-overflow" {
    const P = psr_bits;
    const Case = struct { op3: u6, a: u32, b: u32, result: u32, cc: u32, traps: bool = false };
    const cases = [_]Case{
        .{ .op3 = 0x20, .a = 4, .b = 8, .result = 12, .cc = 0 },
        .{ .op3 = 0x20, .a = 4, .b = 1, .result = 5, .cc = P.v },
        .{ .op3 = 0x20, .a = 0xFFFF_FFFC, .b = 4, .result = 0, .cc = P.z | P.c },
        .{ .op3 = 0x20, .a = 0x7FFF_FFFC, .b = 4, .result = 0x8000_0000, .cc = P.n | P.v },
        .{ .op3 = 0x21, .a = 4, .b = 8, .result = 0xFFFF_FFFC, .cc = P.n | P.c },
        .{ .op3 = 0x21, .a = 4, .b = 1, .result = 3, .cc = P.v },
        .{ .op3 = 0x21, .a = 0x8000_0000, .b = 4, .result = 0x7FFF_FFFC, .cc = P.v },
        .{ .op3 = 0x22, .a = 4, .b = 8, .result = 12, .cc = 0 },
        .{ .op3 = 0x23, .a = 8, .b = 8, .result = 0, .cc = P.z },
        .{ .op3 = 0x22, .a = 4, .b = 1, .result = 0xCAFE, .cc = P.z | P.c, .traps = true },
        .{ .op3 = 0x22, .a = 0x7FFF_FFFC, .b = 4, .result = 0xCAFE, .cc = P.z | P.c, .traps = true },
        .{ .op3 = 0x23, .a = 0x8000_0000, .b = 4, .result = 0xCAFE, .cc = P.z | P.c, .traps = true },
    };
    for (cases) |tc| {
        var b: Bus = undefined;
        var s = try setup(&b, &.{testFormat3(2, tc.op3, 3, 1, 2, false)});
        defer b.deinit();
        s.cpu.set(1, tc.a);
        s.cpu.set(2, tc.b);
        s.cpu.set(3, 0xCAFE);
        TS.regs.psr |= P.z | P.c;
        try runN(&s.cpu, 1);
        try testing.expectEqual(tc.result, s.cpu.get(3));
        try testing.expectEqual(tc.cc, TS.regs.psr & P.icc);
        try testing.expectEqual(@as(u32, if (tc.traps) 0x4000_00A0 else 0x4000_0004), TS.regs.pc);
        if (tc.traps) {
            try testing.expectEqual(@as(u32, 0x4000_0000), s.cpu.get(17));
            try testing.expectEqual(@as(u32, 0x4000_0004), s.cpu.get(18));
        }
    }
}

test "atomic byte and word operations use original operands and preserve adjacent big-endian lanes" {
    for ([_]u6{ 0x0D, 0x0F, 0x1D, 0x1F }) |op3| {
        const byte = op3 & 2 == 0;
        const alternate = op3 & 0x10 != 0;
        const operand: u13 = if (alternate) 0xB << 5 else 1;
        var b: Bus = undefined;
        var s = try setup(&b, &.{testFormat3(3, op3, 2, 1, operand, !alternate)});
        defer b.deinit();
        const address: u32 = if (byte) 0x4000_0801 else 0x4000_0800;
        s.cpu.set(1, address - @intFromBool(!alternate));
        s.cpu.set(2, 0x5566_7788);
        std.mem.writeInt(u32, TS.ram[0x800..0x804], 0x1122_3344, .big);
        try runN(&s.cpu, 1);
        try testing.expectEqual(@as(u32, if (byte) 0x22 else 0x1122_3344), s.cpu.get(2));
        try testing.expectEqual(@as(u32, if (byte) 0x11FF_3344 else 0x5566_7788), std.mem.readInt(u32, TS.ram[0x800..0x804], .big));
        try testing.expectEqual(@as(u32, 0x4000_0004), TS.regs.pc);
    }
    // rd may alias the effective-address register: the write uses its pre-load value.
    var b: Bus = undefined;
    var s = try setup(&b, &.{testFormat3(3, 0x0F, 1, 1, 0, true)});
    defer b.deinit();
    s.cpu.set(1, 0x4000_0800);
    std.mem.writeInt(u32, TS.ram[0x800..0x804], 42, .big);
    try runN(&s.cpu, 1);
    try testing.expectEqual(@as(u32, 42), s.cpu.get(1));
    try testing.expectEqual(@as(u32, 0x4000_0800), std.mem.readInt(u32, TS.ram[0x800..0x804], .big));
}

test "atomic access rejects misalignment, user ASI, immediate ASI and unknown ASI before mutation" {
    const Case = struct { op3: u6, operand: u13, immediate: bool, address: u32 = 0x4000_0800, supervisor: bool = true, trap: u8 };
    const cases = [_]Case{
        .{ .op3 = 0x0F, .operand = 0, .immediate = true, .address = 0x4000_0801, .trap = tt.mem_address_not_aligned },
        .{ .op3 = 0x1F, .operand = 0xB << 5, .immediate = false, .supervisor = false, .trap = tt.privileged_instruction },
        .{ .op3 = 0x1D, .operand = 0, .immediate = true, .trap = tt.illegal_instruction },
        .{ .op3 = 0x1F, .operand = 0x13 << 5, .immediate = false, .trap = tt.data_access_exception },
    };
    for (cases) |tc| {
        var b: Bus = undefined;
        var s = try setup(&b, &.{testFormat3(3, tc.op3, 2, 1, tc.operand, tc.immediate)});
        defer b.deinit();
        if (!tc.supervisor) TS.regs.psr &= ~psr_bits.s;
        s.cpu.set(1, tc.address);
        s.cpu.set(2, 99);
        std.mem.writeInt(u32, TS.ram[0x800..0x804], 42, .big);
        try runN(&s.cpu, 1);
        try testing.expectEqual(@as(u32, 0x4000_0000) + @as(u32, tc.trap) * 16, TS.regs.pc);
        try testing.expectEqual(@as(u32, 99), s.cpu.get(2));
        try testing.expectEqual(@as(u32, 42), std.mem.readInt(u32, TS.ram[0x800..0x804], .big));
        try testing.expectEqual(@as(usize, 0), b.log.items.len);
    }
}

test "atomic fuel exhaustion and failed stores preserve the faulting pc and destination" {
    var b: Bus = undefined;
    var s = try setup(&b, &.{ testFormat3(3, 0x0F, 2, 1, 0, true), testFormat3(3, 0x04, 2, 1, 0, true) });
    defer b.deinit();
    s.cpu.set(1, 0x4000_0800);
    s.cpu.set(2, 99);
    std.mem.writeInt(u32, TS.ram[0x800..0x804], 42, .big);
    b.fuel = 2; // one instruction plus two bus accesses cannot fit
    try testing.expectEqual(Exit{ .stop = .fuel_exhausted }, s.cpu.step().?);
    try testing.expectEqual(@as(u32, 0x4000_0000), TS.regs.pc);
    try testing.expectEqual(@as(u32, 99), s.cpu.get(2));
    try testing.expectEqual(@as(u32, 42), std.mem.readInt(u32, TS.ram[0x800..0x804], .big));
    b.resetRun(100);
    TS.regs.pc = 0x4000_0004;
    TS.regs.npc = 0x4000_0008;
    const rom_map = [_]bus_mod.Range{.{ .lo = 0x4000_0000, .hi = 0x4000_0FFF, .kind = .rom }};
    b.map = &rom_map;
    try testing.expectEqual(Exit{ .stop = .{ .fault = 0x4000_0800 } }, s.cpu.step().?);
    try testing.expectEqual(@as(u32, 0x4000_0004), TS.regs.pc);
}

test "external interrupts respect ET and PIL; level 15 bypasses PIL and preserves delayed pc" {
    const Case = struct { irl: u4, pil: u4, et: bool = true, taken: bool };
    const cases = [_]Case{
        .{ .irl = 0, .pil = 0, .taken = false },
        .{ .irl = 5, .pil = 5, .taken = false },
        .{ .irl = 4, .pil = 5, .taken = false },
        .{ .irl = 6, .pil = 5, .taken = true },
        .{ .irl = 15, .pil = 15, .taken = true },
        .{ .irl = 15, .pil = 0, .et = false, .taken = false },
    };
    for (cases) |tc| {
        var b: Bus = undefined;
        var s = try setup(&b, &.{0x8210202A}); // mov 42,%g1
        defer b.deinit();
        TS.regs.psr |= @as(u32, tc.pil) << 8;
        if (!tc.et) TS.regs.psr &= ~psr_bits.et;
        TS.regs.npc = 0x4000_0300; // current instruction may be a branch delay slot
        s.cpu.irl = tc.irl;
        try runN(&s.cpu, 1);
        try testing.expectEqual(@as(u32, if (tc.taken) 0 else 42), s.cpu.get(1));
        if (tc.taken) {
            try testing.expectEqual(@as(u32, 0x4000_0100) + @as(u32, tc.irl) * 16, TS.regs.pc);
            try testing.expectEqual(@as(u32, 0x4000_0000), s.cpu.get(17));
            try testing.expectEqual(@as(u32, 0x4000_0300), s.cpu.get(18));
            try testing.expectEqual(@as(u32, tc.pil) << 8, TS.regs.psr & psr_bits.pil);
            try testing.expect(TS.regs.psr & psr_bits.et == 0);
            try testing.expectEqual(tc.irl, s.cpu.irl); // the source must acknowledge/deassert
        } else try testing.expectEqual(@as(u32, 0x4000_0300), TS.regs.pc);
    }
}

test "LEON power-down holds the next instruction until an unmasked interrupt and is privileged" {
    var b: Bus = undefined;
    var s = try setup(&b, &.{ testFormat3(2, 0x30, 19, 0, 0, false), 0x8210202A });
    defer b.deinit();
    try runN(&s.cpu, 1);
    try testing.expect(s.cpu.sleeping);
    try testing.expectEqual(@as(u32, 0x4000_0004), TS.regs.pc);
    TS.regs.psr |= 4 << 8;
    s.cpu.irl = 4;
    try runN(&s.cpu, 3);
    try testing.expect(s.cpu.sleeping);
    try testing.expectEqual(@as(u32, 0), s.cpu.get(1));
    try testing.expectEqual(@as(u32, 0x4000_0004), TS.regs.pc);
    s.cpu.irl = 5;
    try runN(&s.cpu, 1);
    try testing.expect(!s.cpu.sleeping);
    try testing.expectEqual(@as(u32, 0x4000_0150), TS.regs.pc);
    try testing.expectEqual(@as(u32, 0x4000_0004), s.cpu.get(17));
    try testing.expectEqual(@as(u32, 0x4000_0008), s.cpu.get(18));

    s.cpu.irl = 0;
    TS.regs = .{ .pc = 0x4000_0000, .npc = 0x4000_0004, .psr = psr_bits.et, .tbr = 0x4000_0000 };
    try runN(&s.cpu, 1);
    try testing.expect(!s.cpu.sleeping);
    try testing.expectEqual(@as(u32, 0x4000_0030), TS.regs.pc);
}

test "add/sub flags, addx/subx carry chains, conditions" {
    var b_s: Bus = undefined;
    var s = try setup(&b_s, &.{
        0x82102001, // mov 1, %g1
        0x84103fff, // mov -1, %g2
        0x86804002, // addcc %g1, %g2, %g3   -> 0, Z C
        0x88c04001, // addxcc %g1, %g1, %g4  -> 3 (carry in)
        0x8aa04002, // subcc %g1, %g2, %g5   -> 2, borrow C
        0x8ce00001, // subxcc %g0, %g1, %g6 -> -2 (borrow in) N C
    });
    defer s.bus.deinit();
    try runN(&s.cpu, 3);
    try testing.expectEqual(@as(u32, 0), s.cpu.get(3));
    try testing.expectEqual(psr_bits.z | psr_bits.c, TS.regs.psr & psr_bits.icc);
    try runN(&s.cpu, 1);
    try testing.expectEqual(@as(u32, 3), s.cpu.get(4));
    try runN(&s.cpu, 1);
    try testing.expectEqual(@as(u32, 2), s.cpu.get(5));
    try testing.expect(condTrue(TS.regs.psr, 5)); // bcs
    try runN(&s.cpu, 1);
    try testing.expectEqual(@as(u32, 0xFFFF_FFFE), s.cpu.get(6));
    try testing.expectEqual(psr_bits.n | psr_bits.c, TS.regs.psr & psr_bits.icc);
}

test "delay slots: taken, annulled not-taken, ba,a skips its slot" {
    var b_s: Bus = undefined;
    var s = try setup(&b_s, &.{
        0x80a00000, // cmp %g0, %g0          (Z)
        0x02800003, // be +12 -> 0x10
        0x82102001, // mov 1, %g1            (delay slot, executed)
        0x82102002, // mov 2, %g1            (skipped)
        0x22800002, // 0x10: be,a +8 -> 0x18 (taken: slot runs)
        0x84102003, // mov 3, %g2
        0x32800002, // 0x18: bne,a +8 (not taken: slot annulled)
        0x86102004, // mov 4, %g3            (annulled)
        0x30800002, // 0x20: ba,a +8 -> 0x28 (slot annulled)
        0x88102005, // mov 5, %g4            (annulled)
        0x8a102006, // 0x28: mov 6, %g5
    });
    defer s.bus.deinit();
    try runN(&s.cpu, 8);
    try testing.expectEqual(@as(u32, 1), s.cpu.get(1));
    try testing.expectEqual(@as(u32, 3), s.cpu.get(2));
    try testing.expectEqual(@as(u32, 0), s.cpu.get(3));
    try testing.expectEqual(@as(u32, 0), s.cpu.get(4));
    try testing.expectEqual(@as(u32, 6), s.cpu.get(5));
    try testing.expectEqual(@as(u32, 0x4000_002C), TS.regs.pc);
}

test "windows: save/restore move outs to ins; overflow traps through TBR with l1/l2" {
    var b_s: Bus = undefined;
    var s = try setup(&b_s, &.{
        0x9010202a, // mov 42, %o0
        0x9de3bfa0, // save %sp, -0x60, %sp
        0xb0062001, // add %i0, 1, %i0
        0x81e80000, // restore
        0x9de3bfa0, // 0x10: save (overflows: WIM set below)
    });
    defer s.bus.deinit();
    TS.regs.wim = 1 << 6; // window 7 ok, window 6 invalid after two saves
    TS.regs.g[0] = 0;
    s.cpu.set(14, 0x4000_0F00);
    try runN(&s.cpu, 3);
    try testing.expectEqual(@as(u32, 7), s.cpu.cwp());
    try testing.expectEqual(@as(u32, 0x4000_0EA0), s.cpu.get(14));
    try runN(&s.cpu, 1);
    try testing.expectEqual(@as(u32, 0), s.cpu.cwp());
    try testing.expectEqual(@as(u32, 43), s.cpu.get(8));
    TS.regs.psr |= 7; // pretend CWP=7 so the next save hits window 6
    try runN(&s.cpu, 1);
    try testing.expectEqual(@as(u32, 0x4000_0050), TS.regs.pc); // TBR + 5*16
    try testing.expectEqual(@as(u32, 6), s.cpu.cwp());
    try testing.expectEqual(@as(u32, 0x4000_0010), s.cpu.get(17));
    try testing.expectEqual(@as(u32, 0x4000_0014), s.cpu.get(18));
    try testing.expect(TS.regs.psr & psr_bits.et == 0);
    TS.regs.psr &= ~psr_bits.et;
    try testing.expectEqual(Exit{ .error_mode = tt.illegal_instruction }, s.cpu.trap(tt.illegal_instruction).?);
}

test "mul/div edges, mulscc product, y register" {
    var b_s: Bus = undefined;
    var s = try setup(&b_s, &.{
        0x82103fff, // mov -1, %g1
        0x84504001, // umul %g1, %g1, %g2   -> 1, y = 0xFFFFFFFE
        0x86584001, // smul %g1, %g1, %g3   -> 1, y = 0
        0x81806001, // wr %g1, 1, %y       -> y = 0xFFFFFFFE
        0x88f06002, // udivcc %g1, 2, %g4 -> overflow 0xFFFFFFFF, V
        0x81800000, // wr %g0, %g0, %y
        0x8a786000, // sdiv %g1, 0, %g5   -> division_by_zero
    });
    defer s.bus.deinit();
    try runN(&s.cpu, 2);
    try testing.expectEqual(@as(u32, 1), s.cpu.get(2));
    try testing.expectEqual(@as(u32, 0xFFFF_FFFE), TS.regs.y);
    try runN(&s.cpu, 3);
    try testing.expectEqual(@as(u32, 0), s.cpu.get(1) +% 1);
    try testing.expectEqual(@as(u32, 0xFFFF_FFFF), s.cpu.get(4));
    try testing.expectEqual(psr_bits.n | psr_bits.v, TS.regs.psr & psr_bits.icc);
    try runN(&s.cpu, 2);
    try testing.expectEqual(@as(u32, 0x4000_0000 + 0x2A * 16), TS.regs.pc);

    // 32 mulscc steps + final shift compute a 32x32 -> 64 signed product (V8 manual appendix E)
    var prog: [40]u32 = undefined;
    prog[0] = 0x81800008; // wr %g0, %o0, %y  (multiplier)
    prog[1] = 0x82804000; // addcc %g1?? replaced below
    prog[1] = 0x80a00000; // cmp %g0,%g0 clears N V
    for (2..34) |k| prog[k] = 0x83204009; // mulscc %g1, %o1, %g1
    prog[34] = 0x83204000; // mulscc %g1, %g0, %g1
    prog[35] = 0x91400000; // rd %y, %o0
    var b_s2: Bus = undefined;
    var s2 = try setup(&b_s2, &prog);
    defer s2.bus.deinit();
    s2.cpu.set(8, 1234567);
    s2.cpu.set(9, 89);
    TS.regs.g[1] = 0;
    try runN(&s2.cpu, 36);
    // %g1:%y hold the product; positive multiplier, so no correction step
    try testing.expectEqual(@as(u32, 1234567 * 89), s2.cpu.get(8));
}

test "loads/stores: sign extension, ldd/std pairs, alignment trap, call/ret depth" {
    var b_s: Bus = undefined;
    var s = try setup(&b_s, &.{
        0x03100002, // sethi %hi(0x40000800), %g1
        0x82106100, // or %g1, 0x100, %g1  -> 0x40000900
        0x84103f80, // mov -128, %g2
        0xc4284000, // stb %g2, [%g1]
        0xc6484000, // ldsb [%g1], %g3
        0xc8084000, // ldub [%g1], %g4
        0xd0384000, // std %o0, [%g1]
        0xd4184000, // ldd [%g1], %o2
        0xca006002, // ld [%g1+2], %g5  -> unaligned trap
    });
    defer s.bus.deinit();
    s.cpu.set(8, 0x11223344);
    s.cpu.set(9, 0x55667788);
    try runN(&s.cpu, 8);
    try testing.expectEqual(@as(u32, 0xFFFF_FF80), s.cpu.get(3));
    try testing.expectEqual(@as(u32, 0x80), s.cpu.get(4));
    try testing.expectEqualSlices(u8, &.{ 0x11, 0x22, 0x33, 0x44, 0x55, 0x66, 0x77, 0x88 }, TS.ram[0x900..0x908]);
    try testing.expectEqual(@as(u32, 0x11223344), s.cpu.get(10));
    try testing.expectEqual(@as(u32, 0x55667788), s.cpu.get(11));
    try runN(&s.cpu, 1);
    try testing.expectEqual(@as(u32, 0x4000_0070), TS.regs.pc);

    var b_s2: Bus = undefined;
    var s2 = try setup(&b_s2, &.{
        0x40000004, // call +16
        0x90102001, // mov 1, %o0 (delay slot sets the argument)
        0x01000000, // nop (return lands here)
        0x01000000,
        0x81c3e008, // 0x10: retl
        0x90022001, // add %o0, 1, %o0
    });
    defer s2.bus.deinit();
    const H = struct {
        var seen: u32 = 0;
        fn f(c: *Cpu, target: u32, depth: u32) void {
            seen = target ^ c.get(8) ^ depth << 8;
        }
    };
    s2.cpu.on_call = H.f;
    defer s2.cpu.deinit();
    try runN(&s2.cpu, 3);
    try testing.expectEqual(@as(u32, 0x4000_0010 ^ 1), H.seen);
    try testing.expectEqual(@as(u32, 1), s2.cpu.depth());
    try runN(&s2.cpu, 1);
    try testing.expectEqual(@as(u32, 0x4000_0008), TS.regs.pc);
    try runN(&s2.cpu, 1);
    try testing.expectEqual(@as(u32, 0), s2.cpu.depth());
    try testing.expectEqual(@as(u32, 2), s2.cpu.get(8));
}

test "an intercepted call that returns onto `ba,a` leaves the call depth balanced" {
    var b_s: Bus = undefined;
    var s = try setup(&b_s, &.{
        0x40000004, // call +16 -> 0x10 (intercepted)
        0x01000000, // nop
        0x30800003, // 0x08: ba,a 0x14 (the return address)
        0x01000000,
        0x81c3e008, // 0x10: retl (never runs)
        0x01000000, // 0x14
    });
    defer s.bus.deinit();
    const H = struct {
        fn f(c: *Cpu, _: u32, _: u32) void {
            c.r.pc = c.get(15) +% 8;
            c.r.npc = c.r.pc +% 4;
        }
    };
    s.cpu.on_call = H.f;
    defer s.cpu.deinit();
    try runN(&s.cpu, 3);
    try testing.expectEqual(@as(u32, 0x4000_0014), TS.regs.pc);
    try testing.expectEqual(@as(u32, 0), s.cpu.depth());
}

test "call depth of a recursion whose return address is also a branch target in the callee" {
    var b_s: Bus = undefined;
    var s = try setup(&b_s, &.{
        0x90102003, // mov 3, %o0
        0x40000004, // call f (0x14)
        0x01000000, // nop
        0x01000000, // 0x0C: back in F
        0x01000000,
        0x9DE3BFA0, // f = 0x14: save %sp, -0x60, %sp
        0x90A62001, //    subcc %i0, 1, %o0
        0x02800004, //    be r (0x2C): the base case jumps to the recursive call's return address
        0x01000000,
        0x7FFFFFFC, //    call f
        0x01000000,
        0x40000004, // r = 0x2C: call g (0x3C)
        0x01000000,
        0x81C7E008, //    ret
        0x81E80000, //    restore
        0x81C3E008, // g = 0x3C: retl
        0x01000000,
    });
    defer s.bus.deinit();
    defer s.cpu.deinit();
    s.cpu.set(14, 0x4000_0F00);
    const H = struct {
        var g_depths: [4]u32 = undefined;
        var n: usize = 0;
        fn f(c: *Cpu, target: u32, d: u32) void {
            _ = c;
            if (target != 0x4000_003C) return;
            g_depths[n] = d;
            n += 1;
        }
    };
    H.n = 0;
    s.cpu.on_call = H.f;
    try runN(&s.cpu, 3 + 6 + 6 + 4 + 3 * 6); // F, f(3) and f(2) to their calls, f(1) to r, 3 × (call g … restore)
    try testing.expectEqual(@as(u32, 0x4000_000C), TS.regs.pc);
    // F (depth 0) calls f(3) at depth 1, f(2) at 2, f(1) at 3; each frame calls g after its recursion
    try testing.expectEqualSlices(u32, &.{ 3, 2, 1 }, H.g_depths[0..H.n]);
    try runN(&s.cpu, 1); // frames end at the start of the step at the return address
    try testing.expectEqual(@as(u32, 0), s.cpu.depth());
}

test "ASI 1 goes to the asi1 device when one is set" {
    var b_s: Bus = undefined;
    var s = try setup(&b_s, &.{
        0xC2B08020, // stha %g1, [%g2] 1
        0xC6908020, // lduha [%g2] 1, %g3
    });
    defer s.bus.deinit();
    const D = struct {
        var last: [3]u64 = .{ 0, 0, 0 };
        fn read(_: *anyopaque, _: u32, _: u8) u64 {
            return 0x1_BEEF; // wider than the access: the core masks it
        }
        fn write(_: *anyopaque, addr: u32, bits: u8, v: u64) void {
            last = .{ addr, bits, v };
        }
    };
    var ctx: u8 = 0;
    s.cpu.asi1 = .{ .ctx = &ctx, .read = D.read, .write = D.write };
    TS.regs.g[1] = 0x1234_00AA;
    TS.regs.g[2] = 0xAAA;
    try runN(&s.cpu, 2);
    try testing.expectEqual([3]u64{ 0xAAA, 16, 0xAA }, D.last);
    try testing.expectEqual(@as(u32, 0xBEEF), TS.regs.g[3]);
}

test "an unassigned ASI traps (data_access_exception) and touches nothing; with ET=0 it is error mode" {
    var b_s: Bus = undefined;
    var s = try setup(&b_s, &.{
        0xC6808260, // lda [%g2] 0x13, %g3
        0xC2A08260, // sta %g1, [%g2] 0x13
    });
    defer s.bus.deinit();
    TS.regs.g[1] = 0x1234_5678;
    TS.regs.g[2] = 0x4000_0800;
    TS.regs.g[3] = 7;
    try runN(&s.cpu, 1);
    try testing.expectEqual(@as(u32, 0x4000_0000 + @as(u32, tt.data_access_exception) * 16), TS.regs.pc);
    try testing.expectEqual(@as(u32, 7), TS.regs.g[3]);
    TS.regs = .{ .pc = 0x4000_0004, .npc = 0x4000_0008, .psr = psr_bits.s | psr_bits.et, .tbr = 0x4000_0000 };
    TS.regs.g[1] = 0x1234_5678;
    TS.regs.g[2] = 0x4000_0800;
    try runN(&s.cpu, 1);
    try testing.expectEqual(@as(u32, 0x4000_0090), TS.regs.pc);
    try testing.expectEqualSlices(u8, &.{ 0, 0, 0, 0 }, TS.ram[0x800..0x804]);
    TS.regs = .{ .pc = 0x4000_0000, .npc = 0x4000_0004, .psr = psr_bits.s, .tbr = 0x4000_0000 };
    try testing.expectEqual(Exit{ .error_mode = tt.data_access_exception }, s.cpu.step().?);
}

test "virtual windows: 12 saves without traps, ta 3 flushes the callers, restores refill from memory" {
    var words: [64]u32 = undefined;
    var n: usize = 0;
    for ([_]u32{ 0xA010202A, 0x90102000 }) |w| { // mov 42, %l0; mov 0, %o0
        words[n] = w;
        n += 1;
    }
    for (0..12) |_| { // save %sp, -0x40, %sp; add %i0, 1, %o0; mov %o0, %l0
        words[n..][0..3].* = .{ 0x9DE3BFC0, 0x90062001, 0xA0100008 };
        n += 3;
    }
    words[n] = 0x91D02003; // ta 3
    n += 1;
    for (0..12) |_| {
        words[n] = 0x81E80000; // restore
        n += 1;
    }
    var b_s: Bus = undefined;
    var s = try setup(&b_s, words[0..n]);
    defer s.bus.deinit();
    TS.regs.wim = 0xFF; // real mode would take window_overflow on the first save
    s.cpu.set(14, 0x4000_0F00);
    var v: Virtual = undefined;
    s.cpu.virtualWindows(&v);
    try runN(&s.cpu, 2 + 36 + 1);
    try testing.expectEqual(@as(u32, 4), s.cpu.cwp()); // -12 mod 8
    for (0..12) |k| { // the caller at depth k has %sp 0xF00 - 0x40k, and l0 = k (42 at depth 0)
        const want: u32 = if (k == 0) 42 else @intCast(k);
        try testing.expectEqual(want, std.mem.readInt(u32, TS.ram[0xF00 - 0x40 * k ..][0..4], .big));
    }
    std.mem.writeInt(u32, TS.ram[0xF00..][0..4], 77, .big); // the refill must read the save area
    try runN(&s.cpu, 12);
    try testing.expectEqual(@as(u32, 0), s.cpu.cwp());
    try testing.expectEqual(@as(u32, 77), s.cpu.get(16));
    try testing.expectEqual(@as(u32, 0x4000_0F00), s.cpu.get(14));
    try testing.expectEqual(@as(u32, 0), s.cpu.get(8));
    try testing.expectEqual(@as(u32, 0x4000_0000 + 4 * @as(u32, @intCast(n))), TS.regs.pc);
}

test "virtual windows: a chain deeper than the ring spills its oldest windows and comes back" {
    const Big = struct {
        var ram: [0x2_0000]u8 align(4096) = @splat(0);
        var backing = [_]bus_mod.Backing(u8){.{ .base = 0x4000_0000, .mem = &ram }};
        const map = [_]bus_mod.Range{.{ .lo = 0x4000_0000, .hi = 0x4001_FFFF, .kind = .ram }};
    };
    const prog = [_]u32{
        0xA010202A, // mov 42, %l0
        0x8210244C, // mov 1100, %g1
        0x9DE3BFC0, // 1: save %sp, -0x40, %sp
        0x82A06001, //    subcc %g1, 1, %g1
        0x12BFFFFE, //    bne 1b
        0x01000000,
        0x8210244C, // mov 1100, %g1
        0x81E80000, // 2: restore
        0x82A06001, //    subcc %g1, 1, %g1
        0x12BFFFFE, //    bne 2b
        0x01000000,
    };
    for (prog, 0..) |w, k| std.mem.writeInt(u32, Big.ram[4 * k ..][0..4], w, .big);
    var b = try Bus.init(testing.allocator, &Big.map, &Big.backing);
    defer b.deinit();
    var regs: Regs = .{ .pc = 0x4000_0000, .npc = 0x4000_0004, .psr = psr_bits.s | psr_bits.et };
    var c: Cpu = .{ .r = &regs, .bus = &b };
    c.set(14, 0x4001_FF00);
    var v: Virtual = undefined;
    c.virtualWindows(&v);
    try runN(&c, 2 + 1100 * 4);
    try testing.expect(v.top - v.cur <= Virtual.ring - 2);
    try testing.expectEqual(@as(u32, 42), std.mem.readInt(u32, Big.ram[0x1FF00..][0..4], .big)); // spilled
    try runN(&c, 1 + 1100 * 4);
    try testing.expectEqual(@as(u32, 0), c.cwp());
    try testing.expectEqual(@as(u32, 42), c.get(16));
    try testing.expectEqual(@as(u32, 0x4001_FF00), c.get(14));
}

test "rett with ET=0: returns into a valid window; invalid window or misaligned target is error mode (V8 B.25)" {
    var b_s: Bus = undefined;
    var s = try setup(&b_s, &.{0x81C86000}); // rett %g1
    defer s.bus.deinit();
    const P = psr_bits;
    TS.regs.psr = P.s | P.ps; // ET=0, CWP 0
    TS.regs.wim = 1 << 1;
    TS.regs.g[1] = 0x4000_0100;
    try testing.expectEqual(Exit{ .error_mode = tt.window_underflow }, s.cpu.step().?);
    TS.regs = .{ .pc = 0x4000_0000, .npc = 0x4000_0004, .psr = P.s | P.ps, .wim = 1 << 2, .tbr = 0x4000_0000 };
    TS.regs.g[1] = 0x4000_0102;
    try testing.expectEqual(Exit{ .error_mode = tt.mem_address_not_aligned }, s.cpu.step().?);
    TS.regs = .{ .pc = 0x4000_0000, .npc = 0x4000_0004, .psr = P.s, .wim = 1 << 2, .tbr = 0x4000_0000 };
    TS.regs.g[1] = 0x4000_0100;
    try runN(&s.cpu, 1);
    try testing.expectEqual(P.et | 1, TS.regs.psr); // S = PS (0), CWP + 1
    try testing.expectEqual(@as(u32, 0x4000_0004), TS.regs.pc);
    try testing.expectEqual(@as(u32, 0x4000_0100), TS.regs.npc);
}
