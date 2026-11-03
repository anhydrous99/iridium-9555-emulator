//! Common runtime shared by the emulators, the harness and translated firmware (ARCHITECTURE
//! §3.2, §4, §5.1, §7). See API.md. Test: `zig test common/root.zig` from `zig/`.
const std = @import("std");

pub const bus = @import("bus.zig");
pub const tape = @import("tape.zig");
pub const mem16 = @import("mem16.zig");
pub const be = @import("be.zig");
pub const reg = @import("reg.zig");
pub const hooks = @import("hooks.zig");
pub const rt = @import("rt.zig");
pub const snapshot = @import("snapshot.zig");
pub const vector = @import("vector.zig");

test {
    std.testing.refAllDecls(@This());
}

// ---------------------------------------------------------------------------------------------
// End-to-end: one differential test assembled from the pieces, as harness/diff.zig will do it.
const testing = std.testing;

const img = struct {
    var data: mem16.Bc5Data = @splat(0);
    var cpu: extern struct { y: u16, al: u16 } = .{ .y = 0xFCE0, .al = 0 };
    var backing: [1]bus.Backing(u16) = undefined;
    var b: bus.Bus(bus.bc5) = undefined;
    const map = [_]bus.Range{
        .{ .lo = 0x00A0, .hi = 0x00A0, .kind = .shared },
        .{ .lo = 0xA000, .hi = 0xFCFF, .kind = .ram },
        .{ .lo = 0xFF00, .hi = 0xFFDF, .kind = .mmio },
    };
};
const S = mem16.Flat(&img.data, .big);
const h = reg.Handles(&img.b);
const io_status = h.Reg(u16, 0xFF18);
const g_count = h.Shared(u16, 0x00A0);
const g_total = S.at(mem16.U32, 0xA000);

const fw = struct {
    inline fn scale(x: u16) u16 {
        return rt.call(0x1234, u16, null, .{x});
    }
};

/// Stand-in for the emulator: original code does every access through the bus and records the
/// calls it makes (E5) the way the emulator's onCall hook will.
fn emulated(target: u32, args: []const rt.Arg, ret_bits: u16) u64 {
    _ = ret_bits;
    const x: u16 = @truncate(args[0].value);
    switch (target) {
        0x1234 => return x *% 3,
        0x2000 => {
            while (img.b.read(0xFF18, 16) & 0x8000 != 0) {}
            img.b.write(0x00A0, 16, img.b.read(0x00A0, 16) +% 1);
            hooks.recordCall(0x1234, &.{.{ .value = x, .bits = 16 }});
            const t = (@as(u32, img.data[0xA000]) << 16 | img.data[0xA001]) +% x *% 3;
            img.b.write(0xA000, 32, t);
            return img.b.read(0x00A0, 16);
        },
        else => unreachable,
    }
}

/// The translation under test.
fn step(x: u16) u16 {
    while (io_status.read() & 0x8000 != 0) {}
    g_count.store(g_count.load() +% 1);
    g_total.set(g_total.get() +% fw.scale(x));
    return g_count.load();
}

fn stepForgetsPoll(x: u16) u16 {
    g_count.store(g_count.load() +% 1);
    g_total.set(g_total.get() +% fw.scale(x));
    return g_count.load();
}

const Run = struct { ret: u16, mem: snapshot.Snapshot, log: []bus.Access, calls: []hooks.CallEvent, args: []hooks.Arg };

fn runOnce(m: snapshot.Machine, entry: snapshot.Snapshot, t: *tape.Tape, comptime f: anytype, x: u16) !Run {
    const gpa = testing.allocator;
    try m.restore(entry);
    t.rewind();
    img.b.resetRun(1_000_000);
    hooks.reset();
    hooks.recording = true;
    const ret = f(x);
    return .{
        .ret = ret,
        .mem = try m.capture(gpa),
        .log = try gpa.dupe(bus.Access, img.b.log.items),
        .calls = try gpa.dupe(hooks.CallEvent, hooks.calls.items),
        .args = try gpa.dupe(hooks.Arg, hooks.call_args.items),
    };
}

fn freeRun(r: *Run) void {
    r.mem.deinit(testing.allocator);
    testing.allocator.free(r.log);
    testing.allocator.free(r.calls);
    testing.allocator.free(r.args);
}

test "differential run: original vs translation from one snapshot; a dropped poll is caught" {
    const gpa = testing.allocator;
    hooks.gpa = gpa;
    defer hooks.deinit();
    rt.original = emulated;
    defer rt.original = null;
    img.backing = .{.{ .base = 0, .mem = &img.data }};
    img.b = try bus.Bus(bus.bc5).init(gpa, &img.map, &img.backing);
    defer img.b.deinit();
    var t = try tape.Tape.init(gpa, &.{ .{ .addr = 0xFF18, .value = 0x8000 }, .{ .addr = 0xFF18, .value = 0 } });
    defer t.deinit(gpa);
    img.b.tape = &t;

    var parts = [_]snapshot.Part{ .memory("data", 0, u16, &img.data), .state("cpu", &img.cpu) };
    const m: snapshot.Machine = .{ .parts = &parts };
    img.data[0x00A0] = 4;
    g_total.set(0x0001FFFF);
    var entry = try m.capture(gpa);
    defer entry.deinit(gpa);

    const Orig = struct {
        fn f(x: u16) u16 {
            return @truncate(emulated(0x2000, &.{.{ .value = x, .bits = 16 }}, 16));
        }
    };
    var ref = try runOnce(m, entry, &t, Orig.f, 7);
    defer freeRun(&ref);
    var cand = try runOnce(m, entry, &t, step, 7);
    defer freeRun(&cand);

    try testing.expectEqual(ref.ret, cand.ret); // E2
    try testing.expectEqual(@as(u16, 5), cand.ret);
    try testing.expectEqual(@as(?snapshot.Diff, null), m.firstDiff(ref.mem, cand.mem, .{ .memory_only = true })); // E3
    try testing.expectEqual(@as(?usize, null), bus.firstLogDiff(ref.log, cand.log)); // E4
    try testing.expectEqual(@as(usize, 5), ref.log.len); // 2 polls + shared read/write/read; ram not logged
    try testing.expectEqualSlices(hooks.CallEvent, ref.calls, cand.calls); // E5 targets
    try testing.expectEqualSlices(hooks.Arg, ref.args, cand.args); // E5 arguments
    try testing.expectEqual(@as(usize, 1), cand.calls.len);
    try testing.expectEqual(@as(u32, 0x00020014), g_total.get());

    var bad = try runOnce(m, entry, &t, stepForgetsPoll, 7);
    defer freeRun(&bad);
    try testing.expectEqual(ref.ret, bad.ret);
    try testing.expectEqual(@as(?snapshot.Diff, null), m.firstDiff(ref.mem, bad.mem, .{ .memory_only = true }));
    try testing.expectEqual(@as(?usize, 0), bus.firstLogDiff(ref.log, bad.log));
}
