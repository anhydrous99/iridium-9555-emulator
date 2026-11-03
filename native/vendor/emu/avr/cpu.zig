//! avr5 CPU core for ATmega164P and the 640/1280 family (ARCHITECTURE §6.1): a switch interpreter over `decode`, exact
//! SREG semantics (AVR Instruction Set Manual flag formulas), AVRe cycle counts for a 16-bit PC,
//! interrupt entry, and hooks for calls/returns/accesses (harness E5, HLE, snippet filters).
//!
//! Data space: r0..r31 live in `data[0..32]` (the register file *is* data 0x00-0x1F, so stray
//! pointer writes into it reproduce), SP and SREG live in `st` (data 0x5D-0x5F), every other data
//! access goes through the bus (classification, E4 log, tape/device, fuel). Program memory is
//! `prog` (up to 128 KiB, little-endian words); the default PC is a 13-bit word address.
const std = @import("std");
const common = @import("common");
const dec = @import("decode.zig");

pub const Bus = common.bus.Bus(common.bus.avr);
pub const Data = [0x2200]u8;
pub const Prog = [0x20000]u8;

pub const pc_mask: u16 = 0x1FFF; // 8 Ki words = 16 KiB flash

/// SREG bit numbers.
pub const C = 0;
pub const Z = 1;
pub const N = 2;
pub const V = 3;
pub const S = 4;
pub const H = 5;
pub const T = 6;
pub const I = 7;

/// Snapshot part "cpu" (plain data). SREG.I is kept apart in `ie` so that the binding can expose
/// it as its own compared byte (ARCHITECTURE §2.2: SREG flags except I are dead on return).
pub const State = extern struct {
    cycles: u64 = 0,
    /// Word address.
    pc: u16 = 0,
    sp: u16 = 0,
    /// SREG bits 0..6 (C Z N V S H T); bit 7 is always 0 here.
    sreg: u8 = 0,
    /// SREG.I: 0 or 0x80.
    ie: u8 = 0,
    /// Set by SEI/RETI: the next instruction runs before any interrupt is taken.
    irq_hold: u8 = 0,
    sleeping: u8 = 0,
};

pub const CallKind = enum { call, rcall, icall, irq };
pub const CallAction = enum { enter, skip, stop };

/// System side (devices): time, interrupt sources, sleep enable, watchdog reset.
pub const Sys = struct {
    ctx: *anyopaque,
    tick: *const fn (ctx: *anyopaque, cycles: u32) void,
    /// Highest-priority (lowest-numbered) pending and enabled vector, if any.
    pending: *const fn (ctx: *anyopaque) ?u8,
    /// The CPU took `vector`: clear the flags hardware clears on vector entry.
    ack: *const fn (ctx: *anyopaque, vector: u8) void,
    sleep_enabled: *const fn (ctx: *anyopaque) bool,
    wdr: *const fn (ctx: *anyopaque) void,
};

pub const Hooks = struct {
    /// Before a call enters `target` (byte address); `ret` is the return word address.
    /// .enter: push and jump; .skip: continue at `ret` without entering (intercept/HLE did it);
    /// .stop: end the run (`Cpu.stop` must be set by the hook).
    on_call: ?*const fn (c: *Cpu, target: u32, ret: u16, kind: CallKind) CallAction = null,
    /// After RET/RETI popped the return address.
    on_ret: ?*const fn (c: *Cpu) void = null,
    /// Every data-space access the instruction makes (registers by number are not accesses).
    on_access: ?*const fn (c: *Cpu, addr: u16, write: bool) void = null,
};

pub const Stop = union(enum) {
    /// Opcode with no avr5 meaning at this byte address.
    invalid: u32,
    /// Set by a hook (e.g. a noreturn call): the code is the hook's.
    hook: u32,
};

pub const Cpu = struct {
    st: State = .{},
    data: *Data,
    prog: *const Prog,
    bus: *Bus,
    hooks: Hooks = .{},
    sys: ?Sys = null,
    stop: ?Stop = null,
    /// ATmega164P by default; the Extreme's 640/1280-family profile uses a 16-bit PC.
    program_mask: u16 = pc_mask,
    /// Charge one bus fuel unit per instruction (harness runs), as the bus charges per access.
    charge_fuel: bool = true,
    /// Executed instructions per op (snippet coverage); null when not counting.
    op_counts: ?*[@typeInfo(dec.Op).@"enum".field_names.len]u64 = null,

    pub fn reg(c: *const Cpu, n: u5) u8 {
        return c.data[n];
    }
    pub fn setReg(c: *Cpu, n: u5, v: u8) void {
        c.data[n] = v;
    }
    pub fn reg16(c: *const Cpu, n: u5) u16 {
        return @as(u16, c.data[n]) | @as(u16, c.data[@as(u8, n) + 1]) << 8;
    }
    pub fn setReg16(c: *Cpu, n: u5, v: u16) void {
        c.data[n] = @truncate(v);
        c.data[@as(u8, n) + 1] = @truncate(v >> 8);
    }
    pub fn sregByte(c: *const Cpu) u8 {
        return c.st.sreg | c.st.ie;
    }
    pub fn setSreg(c: *Cpu, v: u8) void {
        c.st.sreg = v & 0x7F;
        c.st.ie = v & 0x80;
    }
    pub fn flag(c: *const Cpu, comptime b: u3) bool {
        return if (b == I) c.st.ie != 0 else (c.st.sreg >> b) & 1 != 0;
    }
    fn setFlag(c: *Cpu, comptime b: u3, on: bool) void {
        if (b == I) {
            c.st.ie = if (on) 0x80 else 0;
            return;
        }
        const m: u8 = 1 << b;
        c.st.sreg = if (on) c.st.sreg | m else c.st.sreg & ~m;
    }

    pub fn fetch(c: *const Cpu, pc: u16) u16 {
        const a = @as(usize, pc & c.program_mask) * 2;
        return std.mem.readInt(u16, c.prog[a..][0..2], .little);
    }

    /// Data-space read as the CPU does it (registers, SP/SREG internal, everything else via the bus).
    pub fn read(c: *Cpu, a: u16) u8 {
        if (c.hooks.on_access) |f| f(c, a, false);
        if (a < 0x20) return c.data[a];
        return switch (a) {
            0x5D => @truncate(c.st.sp),
            0x5E => @truncate(c.st.sp >> 8),
            0x5F => c.sregByte(),
            else => @truncate(c.bus.read(a, 8)),
        };
    }

    pub fn write(c: *Cpu, a: u16, v: u8) void {
        if (c.hooks.on_access) |f| f(c, a, true);
        if (a < 0x20) {
            c.data[a] = v;
            return;
        }
        switch (a) {
            0x5D => c.st.sp = (c.st.sp & 0xFF00) | v,
            0x5E => c.st.sp = (c.st.sp & 0x00FF) | @as(u16, v) << 8,
            0x5F => c.setSreg(v),
            else => c.bus.write(a, 8, v),
        }
    }

    pub fn push(c: *Cpu, v: u8) void {
        c.write(c.st.sp, v);
        c.st.sp -%= 1;
    }
    pub fn pop(c: *Cpu) u8 {
        c.st.sp +%= 1;
        return c.read(c.st.sp);
    }
    /// CALL order: low byte at SP, high byte at SP-1 (big-endian in memory).
    pub fn pushPc(c: *Cpu, pc: u16) void {
        c.push(@truncate(pc));
        c.push(@truncate(pc >> 8));
    }
    pub fn popPc(c: *Cpu) u16 {
        const hi: u16 = c.pop();
        const lo: u16 = c.pop();
        return (hi << 8 | lo) & c.program_mask;
    }

    /// True when the run must end (bus stop or CPU stop).
    pub fn stopped(c: *const Cpu) bool {
        return c.stop != null or c.bus.stop != null;
    }

    /// Executes one instruction, or takes one pending interrupt, or idles one cycle asleep.
    pub fn step(c: *Cpu) void {
        if (c.charge_fuel) {
            if (c.bus.fuel == 0) return c.bus.halt(.fuel_exhausted);
            c.bus.fuel -= 1;
        }
        const hold = c.st.irq_hold;
        c.st.irq_hold = 0;
        if (c.sys) |s| {
            if (c.st.ie != 0 and hold == 0) if (s.pending(s.ctx)) |vec| return c.interrupt(s, vec);
            if (c.st.sleeping != 0) {
                c.st.cycles += 1;
                s.tick(s.ctx, 1);
                return;
            }
        }
        const cyc = c.exec();
        c.st.cycles += cyc;
        if (c.sys) |s| s.tick(s.ctx, cyc);
    }

    // shortcut: interrupt response is 4 cycles (AVRe, 16-bit PC per the instruction set manual); the
    // ATmega164P datasheet wording (4 vs 5) is unverified offline [unk], hypothesis AV-irq-cycles.
    pub const irq_cycles = 4;

    fn interrupt(c: *Cpu, s: Sys, vec: u8) void {
        const ret = c.st.pc;
        const target: u32 = @as(u32, vec) * 4;
        if (c.hooks.on_call) |f| switch (f(c, target, ret, .irq)) {
            .enter => {},
            .skip => return,
            .stop => return,
        };
        c.pushPc(ret);
        c.st.ie = 0;
        c.st.sleeping = 0;
        c.st.pc = @intCast(target / 2);
        s.ack(s.ctx, vec);
        c.st.cycles += irq_cycles;
        s.tick(s.ctx, irq_cycles);
    }

    fn skipLen(c: *const Cpu, pc_next: u16) u16 {
        return if (dec.isTwoWord(c.fetch(pc_next))) 2 else 1;
    }

    /// Executes the instruction at PC and returns its cycle count.
    fn exec(c: *Cpu) u32 {
        const pc = c.st.pc;
        const i = dec.decode(c.fetch(pc), c.fetch(pc +% 1));
        if (c.op_counts) |oc| oc[@backingInt(i.op)] += 1;
        var next: u16 = pc +% i.len;
        var cyc: u32 = 1;
        const d: u5 = @truncate(i.d);
        const r: u5 = @truncate(i.r);
        const kb: u8 = @truncate(@as(u32, @bitCast(i.k)));
        switch (i.op) {
            .invalid => {
                c.stop = .{ .invalid = @as(u32, pc) * 2 };
                return 0;
            },
            .nop => {},
            // shortcut: BREAK is a NOP (OCDEN unprogrammed and lock bits set, avr-full §2); SPM is a NOP
            // (executed from the application section it has no effect); WDR only notifies the system.
            .@"break", .spm => {},
            .wdr => if (c.sys) |s| s.wdr(s.ctx),
            .sleep => if (c.sys) |s| {
                if (s.sleep_enabled(s.ctx)) c.st.sleeping = 1;
            },
            .movw => c.setReg16(d, c.reg16(r)),
            .mov => c.setReg(d, c.reg(r)),
            .ldi => c.setReg(d, kb),
            .add => c.setReg(d, c.add8(c.reg(d), c.reg(r), 0)),
            .adc => c.setReg(d, c.add8(c.reg(d), c.reg(r), @intFromBool(c.flag(C)))),
            .sub => c.setReg(d, c.sub8(c.reg(d), c.reg(r), 0, false)),
            .subi => c.setReg(d, c.sub8(c.reg(d), kb, 0, false)),
            .sbc => c.setReg(d, c.sub8(c.reg(d), c.reg(r), @intFromBool(c.flag(C)), true)),
            .sbci => c.setReg(d, c.sub8(c.reg(d), kb, @intFromBool(c.flag(C)), true)),
            .cp => _ = c.sub8(c.reg(d), c.reg(r), 0, false),
            .cpi => _ = c.sub8(c.reg(d), kb, 0, false),
            .cpc => _ = c.sub8(c.reg(d), c.reg(r), @intFromBool(c.flag(C)), true),
            .@"and" => c.setReg(d, c.logic(c.reg(d) & c.reg(r))),
            .andi => c.setReg(d, c.logic(c.reg(d) & kb)),
            .@"or" => c.setReg(d, c.logic(c.reg(d) | c.reg(r))),
            .ori => c.setReg(d, c.logic(c.reg(d) | kb)),
            .eor => c.setReg(d, c.logic(c.reg(d) ^ c.reg(r))),
            .com => {
                const v = ~c.reg(d);
                c.setReg(d, c.logic(v));
                c.setFlag(C, true);
            },
            .neg => {
                const a = c.reg(d);
                const v = 0 -% a;
                c.setFlag(H, (v | a) & 0x08 != 0);
                c.setFlag(V, v == 0x80);
                c.setFlag(C, v != 0);
                c.nzs(v);
                c.setReg(d, v);
            },
            .inc => {
                const v = c.reg(d) +% 1;
                c.setFlag(V, v == 0x80);
                c.nzs(v);
                c.setReg(d, v);
            },
            .dec => {
                const v = c.reg(d) -% 1;
                c.setFlag(V, v == 0x7F);
                c.nzs(v);
                c.setReg(d, v);
            },
            .asr, .lsr, .ror => {
                const a = c.reg(d);
                const top: u8 = switch (i.op) {
                    .asr => a & 0x80,
                    .lsr => 0,
                    else => @as(u8, @intFromBool(c.flag(C))) << 7,
                };
                const v = (a >> 1) | top;
                c.setFlag(C, a & 1 != 0);
                c.setFlag(N, v & 0x80 != 0);
                c.setFlag(V, c.flag(N) != c.flag(C));
                c.setFlag(S, c.flag(N) != c.flag(V));
                c.setFlag(Z, v == 0);
                c.setReg(d, v);
            },
            .swap => {
                const a = c.reg(d);
                c.setReg(d, a << 4 | a >> 4);
            },
            .adiw, .sbiw => {
                const a = c.reg16(d);
                const k: u16 = kb;
                const v = if (i.op == .adiw) a +% k else a -% k;
                const ah7 = a & 0x8000 != 0;
                const r15 = v & 0x8000 != 0;
                if (i.op == .adiw) {
                    c.setFlag(V, !ah7 and r15);
                    c.setFlag(C, !r15 and ah7);
                } else {
                    c.setFlag(V, ah7 and !r15);
                    c.setFlag(C, r15 and !ah7);
                }
                c.setFlag(N, r15);
                c.setFlag(S, c.flag(N) != c.flag(V));
                c.setFlag(Z, v == 0);
                c.setReg16(d, v);
                cyc = 2;
            },
            .mul, .muls, .mulsu, .fmul, .fmuls, .fmulsu => {
                const a = c.reg(d);
                const b = c.reg(r);
                const p: u16 = switch (i.op) {
                    .mul, .fmul => @as(u16, a) * b,
                    .muls, .fmuls => @bitCast(@as(i16, @as(i8, @bitCast(a))) * @as(i8, @bitCast(b))),
                    else => @bitCast(@as(i16, @as(i8, @bitCast(a))) * @as(i16, b)),
                };
                const fractional = i.op == .fmul or i.op == .fmuls or i.op == .fmulsu;
                const res = if (fractional) p << 1 else p;
                c.setFlag(C, p & 0x8000 != 0);
                c.setFlag(Z, res == 0);
                c.setReg16(0, res);
                cyc = 2;
            },
            .bset => c.setFlagN(r, true),
            .bclr => c.setFlagN(r, false),
            .bst => c.setFlag(T, (c.reg(d) >> @as(u3, @truncate(r))) & 1 != 0),
            .bld => {
                const m = @as(u8, 1) << @as(u3, @truncate(r));
                c.setReg(d, if (c.flag(T)) c.reg(d) | m else c.reg(d) & ~m);
            },
            .ldd_y, .ldd_z => {
                c.setReg(d, c.read(c.reg16(if (i.op == .ldd_y) 28 else 30) +% kb));
                cyc = 2;
            },
            .std_y, .std_z => {
                c.write(c.reg16(if (i.op == .std_y) 28 else 30) +% kb, c.reg(r));
                cyc = 2;
            },
            .lds => {
                c.setReg(d, c.read(@truncate(@as(u32, @bitCast(i.k)))));
                cyc = 2;
            },
            .sts => {
                c.write(@truncate(@as(u32, @bitCast(i.k))), c.reg(r));
                cyc = 2;
            },
            .ld_x, .ld_x_inc, .ld_x_dec, .ld_y_inc, .ld_y_dec, .ld_z_inc, .ld_z_dec => {
                const p = ptrOf(i.op);
                const a = c.indirect(p, i.op);
                // quirk: `ld r26, X+` and the like are undefined in the manual; the pointer update
                // happens after the load here (and in QEMU), so it wins.
                c.setReg(d, c.read(a.addr));
                if (i.op != .ld_x) c.setReg16(p, a.new);
                cyc = 2;
            },
            .st_x, .st_x_inc, .st_x_dec, .st_y_inc, .st_y_dec, .st_z_inc, .st_z_dec => {
                const p = ptrOf(i.op);
                const a = c.indirect(p, i.op);
                c.write(a.addr, c.reg(r));
                if (i.op != .st_x) c.setReg16(p, a.new);
                cyc = 2;
            },
            .lpm_r0, .lpm, .lpm_inc => {
                const z = c.reg16(30);
                const v = c.prog[@as(u32, z) & (@as(u32, c.program_mask) * 2 + 1)];
                if (i.op == .lpm_r0) c.setReg(0, v) else c.setReg(d, v);
                if (i.op == .lpm_inc) c.setReg16(30, z +% 1);
                cyc = 3;
            },
            .push => {
                c.push(c.reg(r));
                cyc = 2;
            },
            .pop => {
                c.setReg(d, c.pop());
                cyc = 2;
            },
            .in => c.setReg(d, c.read(@as(u16, kb) + 0x20)),
            .out => c.write(@as(u16, kb) + 0x20, c.reg(r)),
            .sbi, .cbi => {
                const a = @as(u16, i.d) + 0x20;
                const m = @as(u8, 1) << @as(u3, @truncate(r));
                // shortcut: devices see the read-modify-write; bit-precise SBI/CBI on W1C flag
                // registers is not modelled (the image never uses SBI/CBI on TIFRn/PCIFR/EIFR).
                const v = c.read(a);
                c.write(a, if (i.op == .sbi) v | m else v & ~m);
                cyc = 2;
            },
            .cpse, .sbrc, .sbrs, .sbic, .sbis => {
                const skip = switch (i.op) {
                    .cpse => c.reg(d) == c.reg(r),
                    .sbrc => (c.reg(d) >> @as(u3, @truncate(r))) & 1 == 0,
                    .sbrs => (c.reg(d) >> @as(u3, @truncate(r))) & 1 != 0,
                    .sbic => (c.read(@as(u16, i.d) + 0x20) >> @as(u3, @truncate(r))) & 1 == 0,
                    else => (c.read(@as(u16, i.d) + 0x20) >> @as(u3, @truncate(r))) & 1 != 0,
                };
                if (skip) {
                    const n = c.skipLen(next);
                    next +%= n;
                    cyc += n;
                }
            },
            .brbs, .brbc => {
                const set = c.flagN(r);
                if (set == (i.op == .brbs)) {
                    next = pc +% 1 +% @as(u16, @bitCast(@as(i16, @intCast(i.k))));
                    cyc = 2;
                }
            },
            .rjmp => {
                next = pc +% 1 +% @as(u16, @bitCast(@as(i16, @intCast(i.k))));
                cyc = 2;
            },
            .jmp => {
                next = @truncate(@as(u32, @bitCast(i.k)));
                cyc = 3;
            },
            .ijmp => {
                next = c.reg16(30);
                cyc = 2;
            },
            .rcall, .call, .icall => {
                const target: u16 = switch (i.op) {
                    .rcall => pc +% 1 +% @as(u16, @bitCast(@as(i16, @intCast(i.k)))),
                    .call => @truncate(@as(u32, @bitCast(i.k))),
                    else => c.reg16(30),
                };
                const kind: CallKind = switch (i.op) {
                    .rcall => .rcall,
                    .call => .call,
                    else => .icall,
                };
                cyc = if (i.op == .call) 4 else 3;
                const action: CallAction = if (c.hooks.on_call) |f| f(c, @as(u32, target & c.program_mask) * 2, next & c.program_mask, kind) else .enter;
                switch (action) {
                    .enter => {
                        c.pushPc(next);
                        next = target;
                    },
                    .skip => {},
                    .stop => return cyc,
                }
            },
            .ret, .reti => {
                next = c.popPc();
                if (i.op == .reti) {
                    c.st.ie = 0x80;
                    c.st.irq_hold = 1;
                }
                cyc = 4;
                if (c.hooks.on_ret) |f| f(c);
            },
        }
        if (i.op == .bset and r == I) c.st.irq_hold = 1; // SEI: the next instruction runs first
        c.st.pc = next & c.program_mask;
        return cyc;
    }

    fn flagN(c: *const Cpu, b: u5) bool {
        return if (b == I) c.st.ie != 0 else (c.st.sreg >> @as(u3, @truncate(b))) & 1 != 0;
    }
    fn setFlagN(c: *Cpu, b: u5, on: bool) void {
        if (b == I) {
            c.st.ie = if (on) 0x80 else 0;
            return;
        }
        const m = @as(u8, 1) << @as(u3, @truncate(b));
        c.st.sreg = if (on) c.st.sreg | m else c.st.sreg & ~m;
    }

    /// N, Z and S = N ^ V (V already set).
    fn nzs(c: *Cpu, v: u8) void {
        c.setFlag(N, v & 0x80 != 0);
        c.setFlag(Z, v == 0);
        c.setFlag(S, c.flag(N) != c.flag(V));
    }

    fn logic(c: *Cpu, v: u8) u8 {
        c.setFlag(V, false);
        c.nzs(v);
        return v;
    }

    fn add8(c: *Cpu, a: u8, b: u8, cin: u1) u8 {
        const v = a +% b +% cin;
        const cy = (a & b) | (b & ~v) | (~v & a);
        c.setFlag(H, cy & 0x08 != 0);
        c.setFlag(C, cy & 0x80 != 0);
        c.setFlag(V, ((a & b & ~v) | (~a & ~b & v)) & 0x80 != 0);
        c.nzs(v);
        return v;
    }

    /// SUB/SUBI/CP/CPI and, with `keep_z`, SBC/SBCI/CPC (Z only stays set if the result is 0).
    fn sub8(c: *Cpu, a: u8, b: u8, cin: u1, keep_z: bool) u8 {
        const v = a -% b -% cin;
        const bw = (~a & b) | (b & v) | (v & ~a);
        const z_prev = c.flag(Z);
        c.setFlag(H, bw & 0x08 != 0);
        c.setFlag(C, bw & 0x80 != 0);
        c.setFlag(V, ((a & ~b & ~v) | (~a & b & v)) & 0x80 != 0);
        c.nzs(v);
        if (keep_z) c.setFlag(Z, v == 0 and z_prev);
        return v;
    }

    const Indirect = struct { addr: u16, new: u16 };

    fn indirect(c: *const Cpu, p: u5, op: dec.Op) Indirect {
        const v = c.reg16(p);
        return switch (op) {
            .ld_x_inc, .ld_y_inc, .ld_z_inc, .st_x_inc, .st_y_inc, .st_z_inc => .{ .addr = v, .new = v +% 1 },
            .ld_x_dec, .ld_y_dec, .ld_z_dec, .st_x_dec, .st_y_dec, .st_z_dec => .{ .addr = v -% 1, .new = v -% 1 },
            else => .{ .addr = v, .new = v },
        };
    }

    fn ptrOf(op: dec.Op) u5 {
        return switch (op) {
            .ld_x, .ld_x_inc, .ld_x_dec, .st_x, .st_x_inc, .st_x_dec => 26,
            .ld_y_inc, .ld_y_dec, .st_y_inc, .st_y_dec => 28,
            else => 30,
        };
    }

    /// Runs until a stop, `max` steps, or PC == `until_pc` (word) with SP == `until_sp`.
    pub fn runUntil(c: *Cpu, until_pc: ?u16, until_sp: u16, max: u64) RunEnd {
        var n: u64 = 0;
        while (n < max) : (n += 1) {
            if (until_pc) |p| if (c.st.pc == p and c.st.sp == until_sp) return .reached;
            c.step();
            if (c.stopped()) return .stopped;
        }
        if (until_pc) |p| if (c.st.pc == p and c.st.sp == until_sp) return .reached;
        return .max_steps;
    }
};

pub const RunEnd = enum { reached, stopped, max_steps };

/// Cycle count of the instruction at `pc` when it does not branch or skip (for tests and tools).
pub fn baseCycles(op: dec.Op) u32 {
    return switch (op) {
        .adiw, .sbiw, .mul, .muls, .mulsu, .fmul, .fmuls, .fmulsu, .ldd_y, .ldd_z, .std_y, .std_z, .lds, .sts => 2,
        .ld_x, .ld_x_inc, .ld_x_dec, .ld_y_inc, .ld_y_dec, .ld_z_inc, .ld_z_dec => 2,
        .st_x, .st_x_inc, .st_x_dec, .st_y_inc, .st_y_dec, .st_z_inc, .st_z_dec => 2,
        .push, .pop, .sbi, .cbi, .rjmp, .ijmp => 2,
        .lpm_r0, .lpm, .lpm_inc, .jmp, .rcall, .icall => 3,
        .call, .ret, .reti => 4,
        else => 1,
    };
}

// ---------------------------------------------------------------------------------------------
const testing = std.testing;

pub const TestRig = struct {
    data: Data = @splat(0),
    prog: Prog = @splat(0xFF),
    backing: [1]common.bus.Backing(u8) = undefined,
    bus: Bus = undefined,
    cpu: Cpu = undefined,

    const map = [_]common.bus.Range{
        .{ .lo = 0x00, .hi = 0x1F, .kind = .cpu_alias },
        .{ .lo = 0x20, .hi = 0xFF, .kind = .mmio },
        .{ .lo = 0x100, .hi = 0x4FF, .kind = .ram },
    };

    pub fn init(t: *TestRig, words: []const u16) !void {
        t.backing = .{.{ .base = 0, .mem = &t.data }};
        t.bus = try Bus.init(testing.allocator, &map, &t.backing);
        for (words, 0..) |w, k| std.mem.writeInt(u16, t.prog[2 * k ..][0..2], w, .little);
        t.cpu = .{ .data = &t.data, .prog = &t.prog, .bus = &t.bus, .charge_fuel = false };
        t.cpu.st.sp = 0x4FF;
    }
    pub fn deinit(t: *TestRig) void {
        t.bus.deinit();
    }
    pub fn steps(t: *TestRig, n: usize) !void {
        for (0..n) |_| {
            t.cpu.step();
            if (t.cpu.stopped()) return error.Stopped;
        }
    }
};

test "larger AVR profile preserves high program addresses and LPM byte addresses" {
    var t: TestRig = .{};
    try t.init(&.{0x0000});
    defer t.deinit();
    std.mem.writeInt(u16, t.prog[0x4000..][0..2], 0xE007, .little); // LDI r16,7
    std.mem.writeInt(u16, t.prog[0x4002..][0..2], 0x95C8, .little); // LPM r0,Z
    t.prog[0x4004] = 0xA5;
    try testing.expectEqual(@as(u16, 0), t.cpu.fetch(0x2000)); // 164P wraps at 16 KiB.
    t.cpu.program_mask = 0xFFFF;
    t.cpu.st.pc = 0x2000;
    t.cpu.setReg16(30, 0x4004);
    try t.steps(2);
    try testing.expectEqual(@as(u8, 7), t.cpu.reg(16));
    try testing.expectEqual(@as(u8, 0xA5), t.cpu.reg(0));
    try testing.expectEqual(@as(u16, 0x2002), t.cpu.st.pc);
    t.cpu.pushPc(0x4321);
    try testing.expectEqual(@as(u16, 0x4321), t.cpu.popPc());
}

test "ADD/ADC/SUB/SBC/CP flags (instruction set manual formulas)" {
    var t: TestRig = .{};
    try t.init(&.{ 0x0f01, 0x1f01, 0x1b01, 0x0b01, 0x0701 }); // add r16,r17; adc r16,r17; sub r16,r17; sbc r16,r17; cpc r16,r17
    defer t.deinit();
    t.cpu.setReg(16, 0x7F);
    t.cpu.setReg(17, 0x01);
    try t.steps(1);
    try testing.expectEqual(@as(u8, 0x80), t.cpu.reg(16));
    // 0x7F + 0x01: H=1 V=1 N=1 S=0 Z=0 C=0
    try testing.expectEqual(@as(u8, (1 << H) | (1 << V) | (1 << N)), t.cpu.st.sreg);
    t.cpu.setReg(16, 0xFF);
    t.cpu.setSreg(1 << C);
    try t.steps(1); // adc: 0xFF + 0x01 + 1 = 0x01, C=1 H=1
    try testing.expectEqual(@as(u8, 0x01), t.cpu.reg(16));
    try testing.expectEqual(@as(u8, (1 << H) | (1 << C)), t.cpu.st.sreg);
    t.cpu.setReg(16, 0x80);
    try t.steps(1); // sub: 0x80 - 0x01 = 0x7F, V=1 H=1, S=V^N=1
    try testing.expectEqual(@as(u8, 0x7F), t.cpu.reg(16));
    try testing.expectEqual(@as(u8, (1 << H) | (1 << V) | (1 << S)), t.cpu.st.sreg);
    t.cpu.setReg(16, 0x01);
    t.cpu.setSreg(1 << Z);
    try t.steps(1); // sbc: 1 - 1 - 0 = 0, Z stays set
    try testing.expectEqual(@as(u8, 1 << Z), t.cpu.st.sreg);
    t.cpu.setReg(16, 0x00);
    try t.steps(1); // cpc: 0 - 1 - 0 = 0xFF: C=1 H=1 N=1 S=1, Z cleared
    try testing.expectEqual(@as(u8, (1 << C) | (1 << H) | (1 << N) | (1 << S)), t.cpu.st.sreg);
}

test "ADIW/SBIW, NEG, ASR/ROR, MULS/FMULS, cycles" {
    var t: TestRig = .{};
    // adiw r24,1; sbiw r24,2; neg r16; asr r17; ror r18; muls r16,r17; fmuls r16,r17
    try t.init(&.{ 0x9601, 0x9702, 0x9501, 0x9515, 0x9527, 0x0201, 0x0381 });
    defer t.deinit();
    t.cpu.setReg16(24, 0x7FFF);
    try t.steps(1);
    try testing.expectEqual(@as(u16, 0x8000), t.cpu.reg16(24));
    try testing.expectEqual(@as(u8, (1 << V) | (1 << N)), t.cpu.st.sreg);
    try testing.expectEqual(@as(u64, 2), t.cpu.st.cycles);
    t.cpu.setReg16(24, 0x0001);
    try t.steps(1); // 1 - 2 = 0xFFFF: C=1 N=1 S=1
    try testing.expectEqual(@as(u8, (1 << C) | (1 << N) | (1 << S)), t.cpu.st.sreg);
    t.cpu.setReg(16, 0x80);
    try t.steps(1); // neg 0x80 = 0x80: V=1 N=1 C=1 H=0
    try testing.expectEqual(@as(u8, (1 << V) | (1 << N) | (1 << C)), t.cpu.st.sreg);
    t.cpu.setReg(17, 0x81);
    try t.steps(1); // asr 0x81 = 0xC0, C=1 N=1 V=N^C=0 S=1
    try testing.expectEqual(@as(u8, 0xC0), t.cpu.reg(17));
    try testing.expectEqual(@as(u8, (1 << C) | (1 << N) | (1 << S)), t.cpu.st.sreg);
    t.cpu.setReg(18, 0x02);
    try t.steps(1); // ror with C=1: 0x81, C=0 N=1 V=1 S=0
    try testing.expectEqual(@as(u8, 0x81), t.cpu.reg(18));
    try testing.expectEqual(@as(u8, (1 << N) | (1 << V)), t.cpu.st.sreg);
    t.cpu.setReg(16, 0x80);
    t.cpu.setReg(17, 0x80);
    try t.steps(1); // muls -128*-128 = 0x4000
    try testing.expectEqual(@as(u16, 0x4000), t.cpu.reg16(0));
    try t.steps(1); // fmuls: 0x4000 << 1 = 0x8000, C = bit 15 before shift = 0
    try testing.expectEqual(@as(u16, 0x8000), t.cpu.reg16(0));
    try testing.expectEqual(false, t.cpu.flag(C));
    try testing.expectEqual(@as(u64, 2 + 2 + 1 + 1 + 1 + 2 + 2), t.cpu.st.cycles);
}

test "skips over two-word instructions, branches, call/ret order on the stack" {
    var t: TestRig = .{};
    // 0: cpse r0,r0 ; 1-2: jmp 0 ; 3: rcall +1 ; 4: nop ; 5: ret
    try t.init(&.{ 0x1000, 0x940c, 0x0000, 0xd001, 0x0000, 0x9508 });
    defer t.deinit();
    try t.steps(1);
    try testing.expectEqual(@as(u16, 3), t.cpu.st.pc);
    try testing.expectEqual(@as(u64, 3), t.cpu.st.cycles); // 1 + 2 skipped words
    try t.steps(1); // rcall .+2 -> 5, return address 4
    try testing.expectEqual(@as(u16, 5), t.cpu.st.pc);
    try testing.expectEqual(@as(u16, 0x4FD), t.cpu.st.sp);
    try testing.expectEqual(@as(u8, 0x00), t.data[0x4FE]); // high byte at SP+1
    try testing.expectEqual(@as(u8, 0x04), t.data[0x4FF]); // low byte at the old SP
    try t.steps(1);
    try testing.expectEqual(@as(u16, 4), t.cpu.st.pc);
    try testing.expectEqual(@as(u16, 0x4FF), t.cpu.st.sp);
    try testing.expectEqual(@as(u64, 3 + 3 + 4), t.cpu.st.cycles);
}

test "registers are data 0x00-0x1F; SP/SREG are data 0x5D-0x5F" {
    var t: TestRig = .{};
    // ldi r26,5 ; ldi r27,0 ; ldi r16,0x5a ; st X,r16 ; lds r17,0x5f ; sts 0x5d, r16
    try t.init(&.{ 0xe0a5, 0xe0b0, 0xe50a, 0x930c, 0x9110, 0x005f, 0x9300, 0x005d });
    defer t.deinit();
    t.cpu.setSreg(0x83);
    try t.steps(6);
    try testing.expectEqual(@as(u8, 0x5a), t.cpu.reg(5));
    try testing.expectEqual(@as(u8, 0x83), t.cpu.reg(17));
    try testing.expectEqual(@as(u16, 0x45a), t.cpu.st.sp);
    try testing.expectEqual(@as(usize, 0), t.bus.log.items.len); // nothing reached the bus log
}

test "invalid opcode stops at its byte address" {
    var t: TestRig = .{};
    try t.init(&.{ 0x0000, 0x9008 });
    defer t.deinit();
    t.cpu.step();
    t.cpu.step();
    try testing.expectEqual(Stop{ .invalid = 2 }, t.cpu.stop.?);
}

test "baseCycles agrees with exec on straight-line instructions" {
    var t: TestRig = .{};
    const words = [_]u16{ 0x0f01, 0x9601, 0x9005, 0x930f, 0x910f, 0x8100, 0x9488, 0xe50a, 0x0201 };
    try t.init(&words);
    defer t.deinit();
    t.cpu.setReg16(30, 0x100);
    for (words) |w| {
        const before = t.cpu.st.cycles;
        try t.steps(1);
        try testing.expectEqual(baseCycles(dec.decode(w, 0).op), @as(u32, @intCast(t.cpu.st.cycles - before)));
    }
}
