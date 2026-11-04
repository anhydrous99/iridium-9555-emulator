//! avr-gcc calling convention and the harness call protocol (ARCHITECTURE §5.1, §5.3, §5.6).
//!
//! Arguments: each is rounded up to an even number of bytes and allocated downward from r26
//! (u8/u16 -> r25:r24, u32 -> r25..r22, next u16 -> r23:r22, ...), low byte in the lowest register.
//! Return values: 8 bits r24, 16 bits r25:r24, 32 bits r25..r22, 64 bits r25..r18. r1 is zero,
//! r2-r17 and r28-r29 are callee-saved.
//!
//! Harness protocol (harness/record.zig): every call the emulated original makes records E5 with
//! `hooks.recordCall` at `depth == record_depth`, consults `hooks.intercept`, ends the run on a
//! noreturn target, and enters a translated Zig body (HLE) only when the target is not forced.
//!
//! The bridge (`rt.original`, `rt.indirect`: a Zig caller runs emulated code) puts nothing back
//! afterwards (`returnToZig`, bugcompat-avr.md §8.1), and a stop inside it ends the whole run
//! through the bus stop hook (`stopUnderZig`).
const std = @import("std");
const common = @import("common");
const hooks = common.hooks;
const rt = common.rt;
const cpu_mod = @import("cpu.zig");
const Cpu = cpu_mod.Cpu;

pub const Arg = hooks.Arg;

/// Measured or declared signature. `args == null`: unknown (a bridge with the placeholder
/// `(args: []const u16)` signature) — E5 then records the target with no arguments.
pub const Sig = struct {
    args: ?[]const u16,
    ret_bits: u16,
};

pub fn abiBits(comptime T: type) u16 {
    return if (@typeInfo(T) == .@"struct" and @typeInfo(T).@"struct".layout == .@"extern") @sizeOf(T) * 8 else @bitSizeOf(T);
}

fn retBitsOf(comptime R: type) u16 {
    return if (R == void or R == noreturn) 0 else abiBits(R);
}

/// Signature of a Zig function type (call at comptime).
pub fn sigOf(comptime F: type) Sig {
    const info = @typeInfo(F).@"fn";
    const R = info.return_type.?;
    var bits: [info.param_types.len]u16 = undefined;
    for (info.param_types, 0..) |P, k| {
        if (@typeInfo(P.?) == .pointer) return .{ .args = null, .ret_bits = retBitsOf(R) };
        bits[k] = abiBits(P.?);
    }
    const final = bits;
    return .{ .args = &final, .ret_bits = retBitsOf(R) };
}

/// Registers an argument of `bits` occupies (rounded up to even, at least 2).
pub fn regBytes(bits: u16) u8 {
    const b: u8 = @intCast((@max(bits, 1) + 7) / 8);
    return (b + 1) & ~@as(u8, 1);
}

fn mask(bits: u16) u64 {
    return if (bits >= 64) std.math.maxInt(u64) else (@as(u64, 1) << @intCast(bits)) - 1;
}

fn readLe(c: *const Cpu, first: u8, n: u8) u64 {
    var v: u64 = 0;
    for (0..n) |k| v |= @as(u64, c.data[first + k]) << @intCast(8 * k);
    return v;
}

fn writeLe(c: *Cpu, first: u8, n: u8, v: u64) void {
    for (0..n) |k| c.data[first + k] = @truncate(v >> @intCast(8 * k));
}

// shortcut: arguments beyond r8 (more than 18 bytes) would go on the stack; no AVR function has that
// many, so it panics; implement the stack layout if a signature ever needs it.
fn nextReg(next: *u8, bits: u16) u8 {
    const n = regBytes(bits);
    if (n + 8 > next.*) @panic("avr abi: stack-passed arguments are not supported");
    next.* -= n;
    return next.*;
}

/// Caller side: puts `args` into the argument registers, each in its own bytes only (`ownBytes`): an
/// argument narrower than its register pair leaves the pair's upper register as the caller left it,
/// as the original does (`in r24, SPDR; call l0_rx_byte` at 0x1c82 keeps r25; a stray rx state's code
/// in the callee reads it, bugcompat-avr.md 8.1).
pub fn placeArgs(c: *Cpu, args: []const Arg) void {
    var next: u8 = 26;
    for (args) |a| writeLe(c, nextReg(&next, a.bits), ownBytes(a.bits), a.value & mask(a.bits));
}

/// Bytes of an argument's own value: ceil(bits / 8), at least 1 (regBytes rounds that up to the pair).
fn ownBytes(bits: u16) u8 {
    return @intCast((@max(bits, 1) + 7) / 8);
}

/// Callee side: the arguments of signature `bits` as the caller left them.
pub fn readArgs(c: *const Cpu, bits: []const u16, out: []Arg) []const Arg {
    var next: u8 = 26;
    for (bits, 0..) |b, k| out[k] = .{ .value = readLe(c, nextReg(&next, b), regBytes(b)) & mask(b), .bits = b };
    return out[0..bits.len];
}

fn retReg(bits: u16) struct { first: u8, n: u8 } {
    return if (bits <= 8) .{ .first = 24, .n = 1 } else if (bits <= 16) .{ .first = 24, .n = 2 } else if (bits <= 32) .{ .first = 22, .n = 4 } else .{ .first = 18, .n = 8 };
}

pub fn getRet(c: *const Cpu, bits: u16) u64 {
    if (bits == 0) return 0;
    const r = retReg(bits);
    return readLe(c, r.first, r.n) & mask(bits);
}

pub fn setRet(c: *Cpu, bits: u16, v: u64) void {
    if (bits == 0) return;
    const r = retReg(bits);
    writeLe(c, r.first, r.n, v & mask(bits));
}

/// Calls the Zig function `f` with its arguments read from the registers (avr-gcc layout) and
/// returns its raw result (E2). Used by harness candidates and HLE thunks.
pub fn callWithRegs(comptime f: anytype, c: *const Cpu) u64 {
    const F = @TypeOf(f);
    const info = @typeInfo(F).@"fn";
    var args: std.meta.ArgsTuple(F) = undefined;
    var next: u8 = 26;
    inline for (info.param_types, 0..) |P, k| {
        const b = comptime abiBits(P.?);
        args[k] = rt.fromAbi(P.?, readLe(c, nextReg(&next, b), regBytes(b)) & mask(b));
    }
    const R = info.return_type.?;
    if (comptime R == noreturn) {
        @call(.auto, f, args);
    } else if (comptime R == void) {
        @call(.auto, f, args);
        return 0;
    } else return rt.abiArg(@call(.auto, f, args)).value;
}

/// HLE thunk of a translated body: arguments from registers, result into the return registers.
pub fn hleThunk(comptime f: anytype) *const fn (*Cpu) void {
    return struct {
        fn run(c: *Cpu) void {
            const v = callWithRegs(f, c);
            setRet(c, comptime sigOf(@TypeOf(f)).ret_bits, v);
        }
    }.run;
}

// ---------------------------------------------------------------------------------------------
// Harness call protocol. One image per process (ARCHITECTURE §0.3), so the state is global.

pub const Env = struct {
    sigOf: *const fn (target: u32) Sig,
    isNoreturn: *const fn (target: u32) bool,
    /// HLE body of a translated function, or null.
    hle: *const fn (target: u32) ?*const fn (*Cpu) void,
};

/// Return word address pushed by `runFunction`/`original`: erased flash (0xFFFF), never code.
pub const sentinel: u16 = cpu_mod.pc_mask;
/// `Cpu.Stop.hook` code of a noreturn call; its target and arguments are in `last_noreturn`.
pub const stop_noreturn: u32 = 1;
/// E1 fault code of an invalid opcode (byte address in the low bits): outside the data space,
/// so it cannot be confused with a data fault, and the same in reference and candidate runs.
pub const invalid_fault_base: u32 = 0x0100_0000;

pub var env: ?Env = null;
var bound: ?*Cpu = null;
var shadow: [256]u16 = undefined;
var shadow_n: usize = 0;
pub var last_noreturn: struct { target: u32 = 0, n: u8 = 0, args: [rt.max_args]Arg = undefined } = .{};

/// Binds the image's CPU: installs the call/return hooks and `rt.original`.
pub fn bind(c: *Cpu, e: Env) void {
    bound = c;
    env = e;
    c.hooks.on_call = onCall;
    c.hooks.on_ret = onRet;
    rt.original = original;
    rt.indirect = indirect;
}

pub fn unbind() void {
    if (bound) |c| {
        c.hooks.on_call = null;
        c.hooks.on_ret = null;
    }
    bound = null;
    env = null;
    rt.original = null;
    rt.indirect = null;
}

fn onCall(c: *Cpu, target: u32, ret: u16, kind: cpu_mod.CallKind) cpu_mod.CallAction {
    _ = ret;
    if (kind != .irq) {
        const a = protocol(c, target);
        if (a != .enter) return a;
    }
    enterFrame(c);
    return .enter;
}

/// The harness call protocol of a call to `target` with the arguments in their registers: E5, then a
/// noreturn target stops, an intercept or a translated target's Zig body (HLE, not forced) runs in
/// place of the call (.skip), else the caller enters the original (.enter).
fn protocol(c: *Cpu, target: u32) cpu_mod.CallAction {
    const e = env.?;
    var buf: [rt.max_args]Arg = undefined;
    const sig = e.sigOf(target);
    const args = if (sig.args) |b| readArgs(c, b, &buf) else buf[0..0];
    if (hooks.recording and hooks.depth == hooks.record_depth) hooks.recordCall(target, args);
    if (e.isNoreturn(target)) {
        if (hooks.on_noreturn) |f| f(target, args);
        last_noreturn = .{ .target = target, .n = @intCast(args.len) };
        @memcpy(last_noreturn.args[0..args.len], args);
        c.stop = .{ .hook = stop_noreturn };
        return .stop;
    }
    if (hooks.intercept) |f| if (f(target, args)) |r| {
        setRet(c, sig.ret_bits, r);
        return .skip;
    };
    if (!hooks.force.isForced(target)) if (e.hle(target)) |z| {
        hooks.depth += 1;
        defer hooks.depth -= 1;
        z(c);
        return .skip;
    };
    return .enter;
}

fn enterFrame(c: *Cpu) void {
    if (shadow_n == shadow.len) @panic("avr abi: call nesting deeper than 256");
    shadow[shadow_n] = c.st.sp; // SP the matching return restores
    shadow_n += 1;
    hooks.depth += 1;
}

fn onRet(c: *Cpu) void {
    // A return (or a stack unwind past several frames) leaves every frame whose SP it restored.
    while (shadow_n > 0 and c.st.sp >= shadow[shadow_n - 1]) {
        shadow_n -= 1;
        hooks.depth -= 1;
    }
}

pub const End = enum { returned, stopped };

/// Runs the original at byte address `func` from the current CPU state: pushes the sentinel return
/// address and executes until it returns there with the entry SP, or the run stops.
pub fn runFunction(c: *Cpu, func: u32) End {
    const sp0 = c.st.sp;
    const saved_shadow = shadow_n;
    defer shadow_n = saved_shadow;
    c.pushPc(sentinel);
    c.st.pc = @intCast((func / 2) & cpu_mod.pc_mask);
    while (true) {
        if (c.st.pc == sentinel and c.st.sp == sp0) return .returned;
        c.step();
        if (c.stopped()) return .stopped;
    }
}

/// `rt.original`: a Zig caller runs an emulated original (a bridge, or a forced callee) with the
/// arguments in their registers, to its return (`returnToZig`) or a stop (`stopUnderZig`).
fn original(target: u32, args: []const Arg, ret_bits: u16) u64 {
    const c = bound orelse @panic("avr abi: no CPU bound");
    placeArgs(c, args);
    if (runFunction(c, target) == .stopped) stopUnderZig(c, target);
    return returnToZig(c, ret_bits);
}

/// `rt.indirect`: a Zig caller's code-pointer call (§5.2) of any code address, made as the original's
/// `icall` makes it: arguments in their registers, the call protocol (E5 with the target's own
/// signature, noreturn, intercept, a translated target's Zig body unless forced: `Env.hle`, which the
/// AVR binding gives only call-like kinds, fn and loop), else the original code at `target` runs to
/// its return, or stops (fault, invalid opcode, noreturn, fuel) as it would. Afterwards as
/// `original`: the machine as that code left it (`returnToZig`).
/// shortcut: the return address under that code is `runFunction`'s sentinel, not the one the
/// original's `icall` pushes (the word after it); the saved registers above it are the original's
/// (the Zig caller's saved-register frame wrote them, fw/avr vocab.guest.enterSaved). Stray code
/// that pops it as data gets 0x1FFF (0x0202 in txst0_idle: `pop r29; pop r28`, then its `ret`
/// takes the caller's saved registers as the return address, the soft reset of bugcompat-avr.md
/// §2.3). Upgrade: rt.callCode passes the call site's return address (common/rt.zig).
fn indirect(code_addr: u32, args: []const Arg, ret_bits: u16) u64 {
    const c = bound orelse @panic("avr abi: no CPU bound");
    const target = (code_addr / 2 & cpu_mod.pc_mask) * 2; // the PC's width, as `icall` takes Z
    placeArgs(c, args);
    const end: End = switch (protocol(c, target)) {
        .skip => .returned,
        .stop => .stopped,
        .enter => blk: {
            // icall's frame: its return pops it, and so does code that unwinds the stack past it
            const outer = .{ shadow_n, hooks.depth };
            enterFrame(c);
            defer {
                shadow_n = outer[0];
                hooks.depth = outer[1];
            }
            break :blk runFunction(c, target);
        },
    };
    if (end == .stopped) stopUnderZig(c, target);
    return returnToZig(c, ret_bits);
}

/// What the Zig caller gets back from the emulated code: its result, and the machine as that code
/// left it. Nothing is put back (A14, bugcompat-avr.md §8.1), because nothing is in the original:
/// - code that obeys the avr-gcc ABI (a function entry: a bridge, a forced callee, a function at a
///   code pointer) restores r2-r17, r28 and r29 itself, so on this path they are what they were;
/// - code that does not has no epilogue that restores them: stray code at a code pointer into the
///   middle of a function or of an instruction, past a handler table (callStray, a stray timer
///   callback, the SPI handler), or a function entry whose code reaches such code (l1_rx_byte's
///   icall of a stray state, under isr_USART0_RX). The original caller keeps what it changed
///   (`sbc r13, r15` at 0x06e2, `movw r2, r28` at 0x1570) until its own epilogue pops what it
///   pushed, and the Zig caller's saved-register frame does just that (fw/avr
///   vocab.guest.enterSaved and leave, in every translated function);
/// - so do a data-space store into the register file (A14), r1 (`clr r1`, stray code), and the
///   arguments (the original caller loaded them into those registers itself).
fn returnToZig(c: *const Cpu, ret_bits: u16) u64 {
    return getRet(c, ret_bits);
}

/// A stop inside an original called from Zig cannot return to the Zig caller, so the bus stop hook
/// ends the whole run: an invalid opcode is reported as the bus fault `invalid_fault_base | address`,
/// a bus stop (a fault, fuel, the tape) as itself. A fork-server child writes its result and exits; a
/// harness that runs the whole firmware ends it as its all-original run ends at that stop
/// (scenario_avr's `zigStopped`). Without the hook, or for a hook stop (a noreturn call, which only
/// `hooks.on_noreturn` ends), a panic.
fn stopUnderZig(c: *Cpu, target: u32) noreturn {
    if (c.stop) |s| switch (s) {
        .invalid => |a| c.bus.halt(.{ .fault = invalid_fault_base | a }),
        .undefined_spm_buffer => c.bus.halt(.{ .fault = 0x57 }),
        .hook => {},
    };
    if (c.bus.stop) |s| if (c.bus.on_stop) |f| f(s);
    std.debug.panic("avr abi: original 0x{x} stopped under a Zig caller ({any}, bus {any}) and no stop hook is set (Bus.on_stop)", .{ target, c.stop, c.bus.stop });
}

pub fn resetFrames() void {
    shadow_n = 0;
}

/// The SP of the run's function itself at this moment: the current SP at call depth 0, else the SP its own
/// call site had before the active call pushed (the first frame's, as `enterFrame` recorded it). A stack
/// moved above that (a soft reset under a callee resets SP: the frame is gone, its bytes are below SP): the
/// current SP.
pub fn ownSp(c: *const Cpu) u16 {
    return if (shadow_n > 0) @max(shadow[0], c.st.sp) else c.st.sp;
}

// ---------------------------------------------------------------------------------------------
const testing = std.testing;

test "avr-gcc register allocation and return registers" {
    var t: cpu_mod.TestRig = .{};
    try t.init(&.{});
    defer t.deinit();
    const c = &t.cpu;
    placeArgs(c, &.{ .{ .value = 0x1234, .bits = 16 }, .{ .value = 0x56, .bits = 8 }, .{ .value = 0xAABBCCDD, .bits = 32 }, .{ .value = 1, .bits = 1 } });
    try testing.expectEqual(@as(u8, 0x34), c.data[24]);
    try testing.expectEqual(@as(u8, 0x12), c.data[25]);
    try testing.expectEqual(@as(u8, 0x56), c.data[22]);
    try testing.expectEqualSlices(u8, &.{ 0xDD, 0xCC, 0xBB, 0xAA }, c.data[18..22]);
    try testing.expectEqual(@as(u8, 1), c.data[16]);
    // An 8-bit argument writes its own register only: r23 (above r22) and r17 (above r16) keep what was there.
    c.data[23] = 0xA5;
    c.data[17] = 0x5A;
    placeArgs(c, &.{ .{ .value = 0x1234, .bits = 16 }, .{ .value = 0x56, .bits = 8 }, .{ .value = 0xAABBCCDD, .bits = 32 }, .{ .value = 1, .bits = 1 } });
    try testing.expectEqual(@as(u8, 0xA5), c.data[23]);
    try testing.expectEqual(@as(u8, 0x5A), c.data[17]);
    c.data[25] = 0x77;
    placeArgs(c, &.{.{ .value = 0x9C, .bits = 8 }});
    try testing.expectEqual(@as(u8, 0x9C), c.data[24]);
    try testing.expectEqual(@as(u8, 0x77), c.data[25]);
    placeArgs(c, &.{ .{ .value = 0x1234, .bits = 16 }, .{ .value = 0x56, .bits = 8 }, .{ .value = 0xAABBCCDD, .bits = 32 }, .{ .value = 1, .bits = 1 } });
    var buf: [4]Arg = undefined;
    const back = readArgs(c, &.{ 16, 8, 32, 1 }, &buf);
    try testing.expectEqual(@as(u64, 0xAABBCCDD), back[2].value);
    try testing.expectEqual(@as(u64, 0x56), back[1].value);
    setRet(c, 32, 0x01020304);
    try testing.expectEqualSlices(u8, &.{ 4, 3, 2, 1 }, c.data[22..26]);
    try testing.expectEqual(@as(u64, 0x0102), getRet(c, 16)); // r25:r24 hold the high half of a u32
    try testing.expectEqual(@as(u64, 0x02), getRet(c, 8));
    const S = comptime sigOf(fn (u8, u16, bool) u32);
    try testing.expectEqualSlices(u16, &.{ 8, 16, 1 }, S.args.?);
    try testing.expectEqual(@as(u16, 32), S.ret_bits);
    try testing.expectEqual(@as(?[]const u16, null), comptime sigOf(fn ([]const u16) u16).args);
    const Z = struct {
        fn f(a: u8, b: u16) u16 {
            return a +% b;
        }
    };
    placeArgs(c, &.{ .{ .value = 3, .bits = 8 }, .{ .value = 0x100, .bits = 16 } });
    try testing.expectEqual(@as(u64, 0x103), callWithRegs(Z.f, c));
    hleThunk(Z.f)(c);
    try testing.expectEqual(@as(u16, 0x103), c.reg16(24));
}

test "runFunction: call/return through the sentinel, E5 recorded at depth 0 with callee signatures" {
    var t: cpu_mod.TestRig = .{};
    // 0x00: ldi r24,5 ; rcall .+2 (to 0x06) ; ret ; 0x06: subi r24,-1 ; ret
    try t.init(&.{ 0xe085, 0xd001, 0x9508, 0x5f8f, 0x9508 });
    defer t.deinit();
    const E = struct {
        fn sig(target: u32) Sig {
            return if (target == 0x06) .{ .args = &.{8}, .ret_bits = 8 } else .{ .args = null, .ret_bits = 8 };
        }
        fn no(target: u32) bool {
            _ = target;
            return false;
        }
        fn hle(target: u32) ?*const fn (*Cpu) void {
            _ = target;
            return null;
        }
    };
    hooks.gpa = testing.allocator;
    defer hooks.deinit();
    hooks.reset();
    hooks.recording = true;
    bind(&t.cpu, .{ .sigOf = E.sig, .isNoreturn = E.no, .hle = E.hle });
    defer unbind();
    resetFrames();
    try testing.expectEqual(End.returned, runFunction(&t.cpu, 0));
    try testing.expectEqual(@as(u64, 6), getRet(&t.cpu, 8));
    try testing.expectEqual(@as(u16, 0x4FF), t.cpu.st.sp);
    try testing.expectEqual(@as(usize, 1), hooks.calls.items.len);
    try testing.expectEqual(@as(u32, 0x06), hooks.calls.items[0].target);
    try testing.expectEqualSlices(Arg, &.{.{ .value = 5, .bits = 8 }}, hooks.argsOf(hooks.calls.items[0]));
    try testing.expectEqual(@as(u32, 0), hooks.depth);
    // the Zig side reaches the same original through rt.original, callee-saved registers kept
    t.cpu.data[16] = 0x77;
    try testing.expectEqual(@as(u64, 10), rt.original.?(0x06, &.{.{ .value = 9, .bits = 8 }}, 8));
    try testing.expectEqual(@as(u8, 0x77), t.cpu.data[16]);
}

test "indirect: a code pointer reaches any word address as icall does (E5 with the target's sig, HLE, mid-function code)" {
    var t: cpu_mod.TestRig = .{};
    // 0x00: subi r24,-1 ; 0x02: subi r24,-1 ; 0x04: rcall .+0 (to 0x06) ; 0x06: ret
    try t.init(&.{ 0x5f8f, 0x5f8f, 0xd000, 0x9508 });
    defer t.deinit();
    const E = struct {
        fn sig(target: u32) Sig {
            return if (target == 0x00) .{ .args = &.{8}, .ret_bits = 8 } else .{ .args = null, .ret_bits = 16 };
        }
        fn no(target: u32) bool {
            _ = target;
            return false;
        }
        fn hle(target: u32) ?*const fn (*Cpu) void {
            return if (target == 0x00) hleThunk(zig) else null;
        }
        fn zig(x: u8) u8 {
            return x +% 0x40;
        }
    };
    hooks.gpa = testing.allocator;
    defer hooks.deinit();
    hooks.reset();
    hooks.recording = true;
    bind(&t.cpu, .{ .sigOf = E.sig, .isNoreturn = E.no, .hle = E.hle });
    defer unbind();
    resetFrames();
    const call = rt.indirect.?;
    // a translated function start, not forced: its Zig body (HLE), arguments from the registers
    try testing.expectEqual(@as(u64, 0x45), call(0x00, &.{.{ .value = 5, .bits = 8 }}, 8));
    // forced: the original there
    try hooks.forceAllExcept(&.{});
    try testing.expectEqual(@as(u64, 7), call(0x00, &.{.{ .value = 5, .bits = 8 }}, 8));
    // mid-function (past a table, into code): runs from there; its own calls are one level down
    try testing.expectEqual(@as(u64, 6), call(0x02, &.{.{ .value = 5, .bits = 8 }}, 16)); // r25 placed as 0
    // a word address beyond the PC's 13 bits wraps as icall's does: word 0x2001 is word 1
    try testing.expectEqual(@as(u64, 6), call(0x4002, &.{.{ .value = 5, .bits = 8 }}, 16));
    try testing.expectEqual(@as(u16, 0x4FF), t.cpu.st.sp);
    try testing.expectEqual(@as(u32, 0), hooks.depth);
    // E5: each indirect call at depth 0 with the target's own signature; 0x02's rcall is at depth 1
    const want = [_]struct { u32, usize }{ .{ 0x00, 1 }, .{ 0x00, 1 }, .{ 0x02, 0 }, .{ 0x02, 0 } };
    try testing.expectEqual(want.len, hooks.calls.items.len);
    for (want, hooks.calls.items) |w, ev| {
        try testing.expectEqual(w[0], ev.target);
        try testing.expectEqual(w[1], ev.n_args);
    }
    try testing.expectEqual(@as(u64, 5), hooks.argsOf(hooks.calls.items[0])[0].value);
}

test "returnToZig: nothing is put back; an ABI-obeying callee pops its own registers, what stray code changed stays (direct, nested, under HLE)" {
    var t: cpu_mod.TestRig = .{};
    // 0x00: push r16 ; ldi r16,0x77 ; pop r16 ; ret                  a function entry that obeys the ABI
    // 0x08: ldi r30,2 ; ldi r31,0 ; ldi r24,0x55 ; st Z,r24 (r2 through the data space) ;
    //       mov r13,r24 ; ldi r16,0x66 ; clr r1 ; ret                 stray code: no function starts here
    // 0x18: ldi r30,4 ; ldi r31,0 ; icall (word 4 = 0x08) ; ret        an entry whose code icalls it (l1_rx_byte)
    // 0x20: rcall 0x24 ; ret        0x24: ret (translated: its Zig body runs instead, HLE, and calls 0x18)
    try t.init(&.{
        0x930f, 0xe707, 0x910f, 0x9508,
        0xe0e2, 0xe0f0, 0xe585, 0x8380,
        0x2ed8, 0xe606, 0x2411, 0x9508,
        0xe0e4, 0xe0f0, 0x9509, 0x9508,
        0xd001, 0x9508, 0x9508,
    });
    defer t.deinit();
    const E = struct {
        var seen: u32 = 0;
        fn sig(target: u32) Sig {
            _ = target;
            return .{ .args = &.{}, .ret_bits = 0 };
        }
        fn no(target: u32) bool {
            _ = target;
            return false;
        }
        fn hle(target: u32) ?*const fn (*Cpu) void {
            return if (target == 0x24) hleThunk(zig) else null;
        }
        fn zig() void {
            _ = rt.original.?(0x18, &.{}, 0); // the Zig body calls the original whose icall reaches 0x08
        }
        fn count(c: *Cpu, addr: u16, write: bool) void {
            _ = c;
            if (write and addr == 2) seen += 1;
        }
    };
    hooks.gpa = testing.allocator;
    defer hooks.deinit();
    hooks.reset();
    bind(&t.cpu, .{ .sigOf = E.sig, .isNoreturn = E.no, .hle = E.hle });
    defer unbind();
    resetFrames();
    t.cpu.hooks.on_access = E.count; // a harness hook: sees every access, and stays in place
    defer t.cpu.hooks.on_access = null;
    const callers = [_]rt.OriginalFn{ rt.original.?, rt.indirect.? };
    for (callers) |call| {
        // the normal path: the callee restores r16 itself, as before
        t.cpu.data[16] = 0x33;
        _ = call(0x00, &.{}, 0);
        try testing.expectEqual(@as(u8, 0x33), t.cpu.data[16]);
        try testing.expectEqual(@as(u16, 0x4FF), t.cpu.st.sp);
        // stray code at a code pointer (callStray), an entry that icalls it (isr_USART0_RX's
        // l1_rx_byte), an entry whose callee's Zig body calls that entry: the original caller keeps it all
        for ([_]u32{ 0x08, 0x18, 0x20 }) |target| {
            const before = E.seen;
            t.cpu.data[1] = 0x01; // r1 corrupted (A14)
            t.cpu.data[2] = 0xAA;
            t.cpu.data[13] = 0xEE;
            t.cpu.data[16] = 0x33;
            t.cpu.data[17] = 0x44;
            _ = call(target, &.{}, 0);
            try testing.expectEqual(@as(u8, 0x55), t.cpu.data[2]); // stored at data 0x02
            try testing.expectEqual(@as(u8, 0x55), t.cpu.data[13]); // `mov r13, r24`
            try testing.expectEqual(@as(u8, 0x66), t.cpu.data[16]); // `ldi r16, 0x66`
            try testing.expectEqual(@as(u8, 0x44), t.cpu.data[17]);
            try testing.expectEqual(@as(u8, 0x00), t.cpu.data[1]); // `clr r1`
            try testing.expectEqual(before + 1, E.seen);
            try testing.expectEqual(@as(@TypeOf(t.cpu.hooks.on_access), E.count), t.cpu.hooks.on_access);
            try testing.expectEqual(@as(u16, 0x4FF), t.cpu.st.sp);
        }
    }
}

/// Exit status of the forked child `pid`.
fn exitOf(pid: std.c.pid_t) !u8 {
    var status: c_int = 0;
    while (std.c.waitpid(pid, &status, 0) < 0) {}
    const st: u32 = @bitCast(status);
    if (!std.c.W.IFEXITED(st)) return error.ChildDidNotExit;
    return @intCast(std.c.W.EXITSTATUS(st));
}

test "stopUnderZig: a stop under a Zig caller ends the run through the bus stop hook (invalid opcode, fuel), not the caller" {
    var t: cpu_mod.TestRig = .{};
    // 0x00: nop ; 0x02: invalid opcode 0x9008        0x04: rjmp . (stray code that never returns)
    try t.init(&.{ 0x0000, 0x9008, 0xcfff });
    defer t.deinit();
    const E = struct {
        fn sig(target: u32) Sig {
            _ = target;
            return .{ .args = &.{}, .ret_bits = 0 };
        }
        fn no(target: u32) bool {
            _ = target;
            return false;
        }
        fn hle(target: u32) ?*const fn (*Cpu) void {
            _ = target;
            return null;
        }
        /// The harness's end of the run (scenario_avr's `zigStopped`, a fork-server child's report).
        fn stopped(s: common.bus.Stop) noreturn {
            std.c._exit(switch (s) {
                .fault => |a| if (a == invalid_fault_base | 0x02) 10 else 11,
                .fuel_exhausted => 20,
                .tape_exhausted => 30,
            });
        }
    };
    hooks.gpa = testing.allocator;
    defer hooks.deinit();
    hooks.reset();
    bind(&t.cpu, .{ .sigOf = E.sig, .isNoreturn = E.no, .hle = E.hle });
    defer unbind();
    resetFrames();
    const cases = [_]struct { call: rt.OriginalFn, target: u32, want: u8 }{
        .{ .call = rt.original.?, .target = 0x00, .want = 10 }, // a bridge's code reaches the invalid opcode
        .{ .call = rt.indirect.?, .target = 0x02, .want = 10 }, // a code pointer to it
        .{ .call = rt.indirect.?, .target = 0x04, .want = 20 }, // stray code that loops: the fuel ends it
    };
    for (cases) |k| {
        const pid = std.c.fork();
        try testing.expect(pid >= 0);
        if (pid == 0) {
            t.bus.on_stop = E.stopped;
            t.cpu.charge_fuel = true;
            t.bus.fuel = 1000;
            _ = k.call(k.target, &.{}, 0);
            std.c._exit(99); // not reached: a stop does not return to the Zig caller
        }
        try testing.expectEqual(k.want, try exitOf(pid));
    }
}
