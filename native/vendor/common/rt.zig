//! Call wrappers, guest frames and loop sync points (ARCHITECTURE §4.6, §5.1, §5.4).
//! Generated `fw.zig` wrappers call `rt.call(addr, R, impl_or_null, .{args})`; it decides in one
//! place whether the Zig body, the emulated original or a test hook runs.
const std = @import("std");
const root = @import("root");
const bus = @import("bus.zig");
const hooks = @import("hooks.zig");

pub const Arg = hooks.Arg;

/// Verify build (default): wrappers record, intercept and can force the original. A product root
/// file declares `pub const rt_verify = false;` and wrappers inline to direct calls.
pub const verify: bool = if (@hasDecl(root, "rt_verify")) root.rt_verify else true;

pub const max_args = 64;

/// Runs original code: marshals `args` per the measured ISA signature, runs the emulator to a
/// sentinel return address and returns the raw result (`ret_bits` wide, 0 for void/noreturn).
pub const OriginalFn = *const fn (target: u32, args: []const Arg, ret_bits: u16) u64;
/// Bound by the image's emulator at worker start.
pub var original: ?OriginalFn = null;

/// `impl` is the Zig body, or `null` for a bridge (always the original). `R` may be `noreturn`.
/// Order in verify builds: record E5 → noreturn hook / intercept → original if bridge or forced
/// → Zig body.
pub inline fn call(comptime addr: u32, comptime R: type, comptime impl: anytype, args: anytype) R {
    const bridge = @TypeOf(impl) == @TypeOf(null);
    if (comptime !verify) {
        if (comptime bridge) {
            var buf: [max_args]Arg = undefined;
            return runOriginal(R, addr, toArgs(&buf, args));
        }
        return @call(.auto, impl, args);
    }
    var buf: [max_args]Arg = undefined;
    const a = toArgs(&buf, args);
    if (hooks.recording and hooks.depth == hooks.record_depth) hooks.recordCall(addr, a);
    if (R == noreturn) {
        if (hooks.on_noreturn) |f| f(addr, a);
    } else if (hooks.intercept) |f| {
        if (f(addr, a)) |r| return fromAbi(R, r);
    }
    hooks.depth += 1;
    defer hooks.depth -= 1;
    if (comptime bridge) return runOriginal(R, addr, a);
    if (hooks.force.isForced(addr)) return runOriginal(R, addr, a);
    return @call(.auto, impl, args);
}

/// Bound by the image's emulator: the original's indirect call (`icall`, a code pointer) of `target`,
/// any code address: the arguments in their registers, then the emulator's call protocol (E5 with the
/// target's own signature, noreturn, intercept, a translated target's Zig body unless forced) or the
/// original code at `target`, a function start or not.
pub var indirect: ?OriginalFn = null;

/// Code-pointer call (ARCHITECTURE §5.2): calls the code at runtime address `addr` as the original's
/// indirect call does. `W` is the image's wrapper namespace (fw.zig: `W.<unit>.<name>`), `entries` its
/// fn_table entries (`addr`, `unit`, `name`, `kind`). A kind=fn entry at `addr` whose wrapper has the
/// call site's type (`R` and the types of `args`) is called through that wrapper (rt.call: E5, force,
/// Zig body). Any other address (past a handler table, a function of another type or kind, not a
/// function start) goes to `indirect`, so it runs the original code there or faults as it does.
/// shortcut: registers other than the arguments hold what the emulated machine last left in them,
/// not the Zig caller's locals, and the stack holds the emulator's sentinel return address above
/// the Zig side's guest frames, not the original caller's return address and saved registers; code
/// at a stray address that reads them (or returns through them) sees other values. Upgrade by
/// running the caller as original code (force it) when such a stray target is reached.
pub inline fn callCode(comptime W: type, comptime entries: anytype, comptime R: type, addr: u32, args: anytype) R {
    inline for (entries) |e| {
        if (comptime std.mem.eql(u8, @tagName(e.kind), "fn")) {
            const w = @field(@field(W, e.unit), e.name);
            if (comptime callType(@TypeOf(w), R, @TypeOf(args))) if (addr == e.addr) return @call(.auto, w, args);
        }
    }
    var buf: [max_args]Arg = undefined;
    const f = indirect orelse std.debug.panic("rt: code pointer 0x{x} is not a function of the call site's type and no emulator is bound", .{addr});
    return fromAbi(R, f(addr, toArgs(&buf, args), retBits(R)));
}

fn callType(comptime F: type, comptime R: type, comptime Args: type) bool {
    const info = @typeInfo(F).@"fn";
    const fields = @typeInfo(Args).@"struct".field_types;
    if (info.return_type.? != R or info.param_types.len != fields.len) return false;
    for (info.param_types, fields) |p, a| if (p.? != a) return false;
    return true;
}

fn runOriginal(comptime R: type, addr: u32, a: []const Arg) R {
    const f = original orelse std.debug.panic("rt: original 0x{x} called but no emulator is bound", .{addr});
    const r = f(addr, a, retBits(R));
    if (R == noreturn) std.debug.panic("rt: noreturn original 0x{x} returned", .{addr}) else return fromAbi(R, r);
}

/// Loop head `index` of a `kind=loop` function (state is compared there).
pub inline fn sync(comptime index: u32) void {
    if (verify) if (hooks.on_sync) |f| f(index);
}

/// Flattens wrapper arguments to ABI words: ints, bools, enums (incl. `Ptr`), packed structs,
/// types with `toAbi()` (U32, CodePtr, BePtr), and slices/arrays of those (varargs).
pub fn toArgs(buf: *[max_args]Arg, args: anytype) []const Arg {
    var n: usize = 0;
    inline for (args) |v| pushArg(buf, &n, v);
    return buf[0..n];
}

fn pushArg(buf: *[max_args]Arg, n: *usize, v: anytype) void {
    const T = @TypeOf(v);
    switch (@typeInfo(T)) {
        .array => {
            for (v) |e| pushArg(buf, n, e);
            return;
        },
        .pointer => |p| {
            if (p.size != .slice) @compileError(@typeName(T) ++ ": guest pointers must be Ptr(T), not host pointers");
            for (v) |e| pushArg(buf, n, e);
            return;
        },
        else => {},
    }
    if (n.* == max_args) @panic("rt: too many call arguments");
    buf[n.*] = abiArg(v);
    n.* += 1;
}

pub fn abiArg(v: anytype) Arg {
    const T = @TypeOf(v);
    const value = if (@typeInfo(T) == .@"struct" and @hasDecl(T, "toAbi")) v.toAbi() else bus.toRaw(v);
    return .{ .value = value, .bits = abiBits(T) };
}

pub fn fromAbi(comptime R: type, raw: u64) R {
    if (R == void) return {};
    if (comptime abiBits(R) > 64) @compileError(@typeName(R) ++ ": return values wider than 64 bits need abi=reg");
    if (@typeInfo(R) == .@"struct" and @hasDecl(R, "fromAbi")) return R.fromAbi(raw);
    return bus.fromRaw(R, raw);
}

// extern structs (U32, CodePtr, BePtr) have no @bitSizeOf in 0.17; use their byte size.
fn abiBits(comptime T: type) u16 {
    return if (@typeInfo(T) == .@"struct" and @typeInfo(T).@"struct".layout == .@"extern") @sizeOf(T) * 8 else @bitSizeOf(T);
}

fn retBits(comptime R: type) u16 {
    return if (R == void or R == noreturn) 0 else abiBits(R);
}

/// Guest frame mirroring (§4.6). `M` binds the image's stack pointer and memory:
///   `fn sp() u32`, `fn setSp(u32) void`, `fn at(comptime T: type, addr: u32) *T` (any pointer).
/// Offsets and sizes are in guest address units (BC5 words, bytes elsewhere).
pub fn Frames(comptime M: type) type {
    return struct {
        pub const Frame = struct {
            base: u32,
            size: u32,
            pub fn leave(f: Frame) void {
                if (M.sp() != f.base) @panic("rt.Frame.leave: guest stack pointer not balanced");
                M.setSp(f.base +% f.size);
            }
            /// The original's escaping local at `@(off, SP)`: same guest address.
            pub fn local(f: Frame, comptime T: type, off: u32) @TypeOf(M.at(T, 0)) {
                return M.at(T, f.base +% off);
            }
            pub fn addr(f: Frame, off: u32) u32 {
                return f.base +% off;
            }
        };
        /// SP -= size, as the original prologue (`enter -n`, `save %sp,-n,%sp`, AVR prologue).
        pub fn enter(size: u32) Frame {
            const base = M.sp() -% size;
            M.setSp(base);
            return .{ .base = base, .size = size };
        }
    };
}

// ---------------------------------------------------------------------------------------------
const testing = std.testing;
const mem16 = @import("mem16.zig");

const TR = struct {
    var data: mem16.Bc5Data = @splat(0);
    var y: u32 = 0xFCE0;
    var orig_calls: u32 = 0;
    var last_args: [8]Arg = undefined;
    var last_n: usize = 0;
    var synced: u32 = 0;
};
const S = mem16.Flat(&TR.data, .big);
const P = S.Ptr(u16);

fn fakeOriginal(target: u32, args: []const Arg, ret_bits: u16) u64 {
    TR.orig_calls += 1;
    @memcpy(TR.last_args[0..args.len], args);
    TR.last_n = args.len;
    return switch (target) {
        0x1234 => blk: {
            std.debug.assert(ret_bits == 16);
            break :blk args[0].value *% 3;
        },
        0x2000 => 0xAAAA, // the "original" step
        else => 0,
    };
}

const fw = struct {
    pub inline fn scale(x: u16) u16 {
        return call(0x1234, u16, null, .{x});
    }
    pub inline fn step(x: u16, p: P) u16 {
        return call(0x2000, u16, zimpl.step, .{ x, p });
    }
    pub inline fn put(c: mem16.CodePtr, v: mem16.U32, flag: bool, va: []const u16) void {
        return call(0x3000, void, null, .{ c, v, flag, va });
    }
    pub inline fn fatal(code: u16) noreturn {
        call(0x4000, noreturn, zimpl.fatal, .{code});
    }
};
const zimpl = struct {
    fn step(x: u16, p: P) u16 {
        const a = fw.scale(x);
        sync(0);
        return a +% fw.scale(p.get().?.*);
    }
    fn fatal(code: u16) noreturn {
        std.debug.panic("fatal {d}", .{code});
    }
};
fn callsFatal() noreturn {
    fw.fatal(7);
}

fn setup() void {
    hooks.gpa = testing.allocator;
    hooks.reset();
    original = fakeOriginal;
    TR.orig_calls = 0;
}

test "bridge runs the original; translated body runs Zig; E5 recorded at the chosen depth" {
    setup();
    defer hooks.deinit();
    TR.data[0xA000] = 5;
    const p = P.fromAddr(0xA000);

    try testing.expectEqual(@as(u16, 21), fw.scale(7));
    try testing.expectEqual(@as(usize, 1), TR.last_n);
    try testing.expectEqual(Arg{ .value = 7, .bits = 16 }, TR.last_args[0]);

    // harness calls the Zig body directly: its callees are depth-0 calls
    hooks.recording = true;
    try testing.expectEqual(@as(u16, 21 + 15), zimpl.step(7, p));
    try testing.expectEqual(@as(usize, 2), hooks.calls.items.len);
    try testing.expectEqual(@as(u32, 0x1234), hooks.calls.items[0].target);
    try testing.expectEqual(@as(u64, 5), hooks.argsOf(hooks.calls.items[1])[0].value);
    try testing.expectEqual(@as(u32, 0), hooks.depth);

    // through the wrapper at depth 0 only the wrapper call itself is recorded
    hooks.calls.clearRetainingCapacity();
    _ = fw.step(1, p);
    try testing.expectEqual(@as(usize, 1), hooks.calls.items.len);
    try testing.expectEqual(@as(u32, 0x2000), hooks.calls.items[0].target);
    try testing.expectEqualSlices(Arg, &.{ .{ .value = 1, .bits = 16 }, .{ .value = 0xA000, .bits = 16 } }, hooks.argsOf(hooks.calls.items[0]));
}

test "force set selects the original; intercept stubs a callee" {
    setup();
    defer hooks.deinit();
    TR.data[0xA000] = 5;
    const p = P.fromAddr(0xA000);

    try hooks.forceAllExcept(&.{});
    try testing.expectEqual(@as(u16, 0xAAAA), fw.step(1, p)); // forced to the original
    try hooks.forceAllExcept(&.{0x2000});
    try testing.expectEqual(@as(u16, 3 + 15), fw.step(1, p)); // F in Zig, callees original
    try hooks.forceOnly(&.{0x2000});
    try testing.expectEqual(@as(u16, 0xAAAA), fw.step(1, p));
    try hooks.forceOnly(&.{});

    const Stub = struct {
        fn f(target: u32, args: []const Arg) ?u64 {
            _ = args;
            return if (target == 0x1234) 100 else null;
        }
    };
    hooks.intercept = Stub.f;
    TR.orig_calls = 0;
    try testing.expectEqual(@as(u16, 200), fw.step(1, p));
    try testing.expectEqual(@as(u32, 0), TR.orig_calls);
}

test "argument flattening: toAbi types, bool, slices" {
    setup();
    defer hooks.deinit();
    fw.put(mem16.CodePtr.fromAddr(0x0A0F8E), mem16.U32.init(0x11223344), true, &.{ 0xA, 0xB });
    try testing.expectEqualSlices(Arg, &.{
        .{ .value = 0x0A0F8E / 2 + 0x800C, .bits = 32 },
        .{ .value = 0x11223344, .bits = 32 },
        .{ .value = 1, .bits = 1 },
        .{ .value = 0xA, .bits = 16 },
        .{ .value = 0xB, .bits = 16 },
    }, TR.last_args[0..TR.last_n]);
    try testing.expectEqual(mem16.CodePtr.fromRaw(0x587D3), fromAbi(mem16.CodePtr, 0x587D3));
    try testing.expectEqual(@as(i16, -1), fromAbi(i16, 0xFFFF));
    fromAbi(void, 0);
    _ = &callsFatal; // noreturn wrapper path compiles (it exits the process, so it is not run here)
}

test "callCode: a kind=fn function of the call site's type runs through its wrapper, any other address through indirect" {
    setup();
    defer hooks.deinit();
    const Ind = struct {
        var target: u32 = 0;
        var args: [4]Arg = undefined;
        var n: usize = 0;
        var bits: u16 = 0;
        fn f(t: u32, a: []const Arg, ret_bits: u16) u64 {
            target = t;
            @memcpy(args[0..a.len], a);
            n = a.len;
            bits = ret_bits;
            return 0x1_0077; // wider than R: fromAbi keeps 16 bits
        }
    };
    const W = struct {
        pub const u = struct {
            pub const scale = fw.scale;
            pub const step = fw.step;
            pub const isr = fw.scale;
        };
    };
    const entries = .{
        .{ .addr = 0x1234, .unit = "u", .name = "scale", .kind = .@"fn" },
        .{ .addr = 0x2000, .unit = "u", .name = "step", .kind = .@"fn" },
        .{ .addr = 0x3000, .unit = "u", .name = "isr", .kind = .isr },
    };
    indirect = Ind.f;
    defer indirect = null;
    hooks.recording = true;
    const x: u16 = 7;
    // the function at the address, same type: its wrapper (a bridge here: E5, then the original)
    try testing.expectEqual(@as(u16, 21), callCode(W, entries, u16, 0x1234, .{x}));
    try testing.expectEqual(@as(usize, 1), hooks.calls.items.len);
    try testing.expectEqual(@as(u32, 0), Ind.n);
    // not a function start, a function of another type, another kind: the original's indirect call
    for ([_]u32{ 0x1236, 0x2000, 0x3000 }) |a| {
        Ind.n = 0;
        try testing.expectEqual(@as(u16, 0x77), callCode(W, entries, u16, a, .{x}));
        try testing.expectEqual(a, Ind.target);
        try testing.expectEqualSlices(Arg, &.{.{ .value = 7, .bits = 16 }}, Ind.args[0..Ind.n]);
        try testing.expectEqual(@as(u16, 16), Ind.bits);
    }
    try testing.expectEqual(@as(usize, 1), hooks.calls.items.len); // E5 of those is the emulator's
    callCode(W, entries, void, 0x40, .{ x, P.fromAddr(0xA000) });
    try testing.expectEqual(@as(u16, 0), Ind.bits);
    try testing.expectEqual(@as(u64, 0xA000), Ind.args[1].value);
}

test "sync hook" {
    setup();
    defer hooks.deinit();
    const H = struct {
        fn f(i: u32) void {
            TR.synced = i + 1;
        }
    };
    hooks.on_sync = H.f;
    TR.data[0xA000] = 0;
    _ = zimpl.step(0, P.fromAddr(0xA000));
    try testing.expectEqual(@as(u32, 1), TR.synced);
}

test "frames mirror the guest stack" {
    const M = struct {
        pub fn sp() u32 {
            return TR.y;
        }
        pub fn setSp(v: u32) void {
            TR.y = v & 0xFFFF;
        }
        pub const at = S.at;
    };
    const F = Frames(M);
    TR.y = 0xFCE0;
    const outer = F.enter(6);
    try testing.expectEqual(@as(u32, 0xFCDA), TR.y);
    const buf = outer.local([3]u16, 1);
    buf.* = .{ 1, 2, 3 };
    try testing.expectEqual(@as(u16, 1), TR.data[0xFCDB]);
    try testing.expectEqual(@as(u16, 0xFCDB), S.addrOf(buf));
    try testing.expectEqual(@as(u32, 0xFCDB), outer.addr(1));
    const inner = F.enter(2);
    inner.leave();
    outer.leave();
    try testing.expectEqual(@as(u32, 0xFCE0), TR.y);
}
