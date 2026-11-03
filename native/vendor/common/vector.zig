//! Test vectors (ARCHITECTURE §7.1) and their file format (`corpus/<image>/<fn>/<hash>.vec`).
//! The entry snapshot is stored separately, content-addressed by `snapshot` (see snapshot.zig).
//!
//! Format v1, all integers little-endian:
//!   "FWVEC\0" u16 version
//!   u8 image, u32 func, [16]u8 snapshot digest
//!   u32 n, n bytes                                  regs (ISA register file, layout per emu/<isa>)
//!   u32 n, n × {u32 addr, u64 value}                tape
//!   u32 n, n × {u32 addr, u64 value}                tape defaults
//!   u32 n, n × callee:                              replay records
//!       u32 target, u64 ret, u32 n × {u64 value, u16 bits} args,
//!       3 × (u32 n, n × {u32 addr, u8 bits, u8 write, u64 value})   readset, delta, events
//!   u32 n, scenario; u64 call_no; u8 has_parent, [16]u8 parent; u32 n, mutation
const std = @import("std");
const bus = @import("bus.zig");
const tape = @import("tape.zig");
const hooks = @import("hooks.zig");
const snapshot = @import("snapshot.zig");

pub const version: u16 = 1;
const magic = "FWVEC\x00";

pub const Image = enum(u8) { bc5, bc5_loader, trx, ptt, avr, tool, dplport };

/// Recorded effect of one callee, for replay mode (§7.2) and the E6 read-set check.
pub const CalleeRec = struct {
    target: u32,
    args: []const hooks.Arg,
    ret: u64,
    /// Memory values the callee read; must equal the candidate's memory at the call (E6).
    readset: []const bus.Access = &.{},
    /// Memory writes the callee made; applied on replay.
    delta: []const bus.Access = &.{},
    /// Strict accesses the callee made (E4).
    events: []const bus.Access = &.{},
};

pub const Origin = struct {
    scenario: []const u8 = "",
    call_no: u64 = 0,
    parent: ?[16]u8 = null,
    mutation: []const u8 = "",
};

pub const Vector = struct {
    image: Image,
    func: u32,
    snapshot: [16]u8,
    regs: []const u8,
    tape: []const tape.Entry = &.{},
    tape_defaults: []const tape.Entry = &.{},
    callees: []const CalleeRec = &.{},
    origin: Origin = .{},

    /// A tape ready for the bus (values and defaults). Caller deinits it.
    pub fn makeTape(v: Vector, gpa: std.mem.Allocator) !tape.Tape {
        var t = try tape.Tape.init(gpa, v.tape);
        errdefer t.deinit(gpa);
        for (v.tape_defaults) |d| try t.setDefault(gpa, d.addr, d.value);
        return t;
    }
};

pub fn encode(gpa: std.mem.Allocator, v: Vector) ![]u8 {
    var o: std.ArrayList(u8) = .empty;
    errdefer o.deinit(gpa);
    const put = snapshot.putInt;
    try o.appendSlice(gpa, magic);
    try put(&o, gpa, u16, version);
    try put(&o, gpa, u8, @backingInt(v.image));
    try put(&o, gpa, u32, v.func);
    try o.appendSlice(gpa, &v.snapshot);
    try putBytes(&o, gpa, v.regs);
    for ([_][]const tape.Entry{ v.tape, v.tape_defaults }) |list| {
        try put(&o, gpa, u32, @intCast(list.len));
        for (list) |e| {
            try put(&o, gpa, u32, e.addr);
            try put(&o, gpa, u64, e.value);
        }
    }
    try put(&o, gpa, u32, @intCast(v.callees.len));
    for (v.callees) |c| {
        try put(&o, gpa, u32, c.target);
        try put(&o, gpa, u64, c.ret);
        try put(&o, gpa, u32, @intCast(c.args.len));
        for (c.args) |a| {
            try put(&o, gpa, u64, a.value);
            try put(&o, gpa, u16, a.bits);
        }
        for ([_][]const bus.Access{ c.readset, c.delta, c.events }) |list| {
            try put(&o, gpa, u32, @intCast(list.len));
            for (list) |x| {
                try put(&o, gpa, u32, x.addr);
                try put(&o, gpa, u8, x.bits);
                try put(&o, gpa, u8, @intFromBool(x.write));
                try put(&o, gpa, u64, x.value);
            }
        }
    }
    try putBytes(&o, gpa, v.origin.scenario);
    try put(&o, gpa, u64, v.origin.call_no);
    try put(&o, gpa, u8, @intFromBool(v.origin.parent != null));
    try o.appendSlice(gpa, &(v.origin.parent orelse @as([16]u8, @splat(0))));
    try putBytes(&o, gpa, v.origin.mutation);
    return o.toOwnedSlice(gpa);
}

fn putBytes(o: *std.ArrayList(u8), gpa: std.mem.Allocator, b: []const u8) !void {
    try snapshot.putInt(o, gpa, u32, @intCast(b.len));
    try o.appendSlice(gpa, b);
}

pub const DecodeError = error{ Corrupt, UnsupportedVersion, OutOfMemory };

/// Parses untrusted bytes. All slices of the result are allocated in `arena` (free the arena).
pub fn decode(arena: std.mem.Allocator, bytes: []const u8) DecodeError!Vector {
    var r: snapshot.Reader = .{ .buf = bytes };
    if (!std.mem.eql(u8, try r.take(magic.len), magic)) return error.Corrupt;
    if (try r.int(u16) != version) return error.UnsupportedVersion;
    var v: Vector = .{
        .image = std.enums.fromInt(Image, try r.int(u8)) orelse return error.Corrupt,
        .func = try r.int(u32),
        .snapshot = (try r.take(16))[0..16].*,
        .regs = try arena.dupe(u8, try r.take(try r.int(u32))),
    };
    v.tape = try entries(arena, &r);
    v.tape_defaults = try entries(arena, &r);
    const callees = try arena.alloc(CalleeRec, try count(&r, 4 + 8 + 3 * 4 + 4));
    for (callees) |*c| {
        c.target = try r.int(u32);
        c.ret = try r.int(u64);
        const args = try arena.alloc(hooks.Arg, try count(&r, 10));
        for (args) |*a| a.* = .{ .value = try r.int(u64), .bits = try r.int(u16) };
        c.args = args;
        c.readset = try accesses(arena, &r);
        c.delta = try accesses(arena, &r);
        c.events = try accesses(arena, &r);
    }
    v.callees = callees;
    v.origin.scenario = try arena.dupe(u8, try r.take(try r.int(u32)));
    v.origin.call_no = try r.int(u64);
    const has_parent = try r.int(u8);
    const parent = (try r.take(16))[0..16].*;
    if (has_parent > 1) return error.Corrupt;
    v.origin.parent = if (has_parent == 1) parent else null;
    v.origin.mutation = try arena.dupe(u8, try r.take(try r.int(u32)));
    if (r.remaining() != 0) return error.Corrupt;
    return v;
}

/// Reads a count and rejects it if `n * min_size` cannot fit in what is left.
fn count(r: *snapshot.Reader, min_size: usize) error{Corrupt}!usize {
    const n = try r.int(u32);
    if (n > r.remaining() / min_size) return error.Corrupt;
    return n;
}

fn entries(arena: std.mem.Allocator, r: *snapshot.Reader) DecodeError![]const tape.Entry {
    const out = try arena.alloc(tape.Entry, try count(r, 12));
    for (out) |*e| e.* = .{ .addr = try r.int(u32), .value = try r.int(u64) };
    return out;
}

fn accesses(arena: std.mem.Allocator, r: *snapshot.Reader) DecodeError![]const bus.Access {
    const out = try arena.alloc(bus.Access, try count(r, 14));
    for (out) |*x| {
        x.addr = try r.int(u32);
        x.bits = try r.int(u8);
        const w = try r.int(u8);
        if (w > 1) return error.Corrupt;
        x.write = w == 1;
        x.value = try r.int(u64);
    }
    return out;
}

// ---------------------------------------------------------------------------------------------
const testing = std.testing;

fn sample() Vector {
    const S = struct {
        const args = [_]hooks.Arg{ .{ .value = 0x0102, .bits = 16 }, .{ .value = 1, .bits = 1 } };
        const rs = [_]bus.Access{.{ .addr = 0xF0AB, .bits = 16, .write = false, .value = 3 }};
        const delta = [_]bus.Access{ .{ .addr = 0xA000, .bits = 16, .write = true, .value = 9 }, .{ .addr = 0xA001, .bits = 16, .write = true, .value = 0xFFFF } };
        const callees = [_]CalleeRec{
            .{ .target = 0x0B5E0, .args = &args, .ret = 0x12345678, .readset = &rs, .delta = &delta },
            .{ .target = 0x063CCC, .args = &.{}, .ret = 0 },
        };
    };
    return .{
        .image = .bc5,
        .func = 0x00B8F2,
        .snapshot = @splat(0xAB),
        .regs = &.{ 1, 2, 3, 4, 5 },
        .tape = &.{ .{ .addr = 0xFFB4, .value = 0x10 }, .{ .addr = 0xFFB5, .value = 0x20 } },
        .tape_defaults = &.{.{ .addr = 0xFF18, .value = 0 }},
        .callees = &S.callees,
        .origin = .{ .scenario = "boot_idle", .call_no = 42, .parent = @splat(7), .mutation = "arg0=+1" },
    };
}

test "vector encode/decode round-trip" {
    var arena_state = std.heap.ArenaAllocator.init(testing.allocator);
    defer arena_state.deinit();
    const v = sample();
    const bytes = try encode(testing.allocator, v);
    defer testing.allocator.free(bytes);
    const w = try decode(arena_state.allocator(), bytes);
    try testing.expectEqualDeep(v, w);

    const plain: Vector = .{ .image = .avr, .func = 0x0AA2, .snapshot = @splat(0), .regs = &.{} };
    const b2 = try encode(testing.allocator, plain);
    defer testing.allocator.free(b2);
    try testing.expectEqualDeep(plain, try decode(arena_state.allocator(), b2));

    var t = try w.makeTape(testing.allocator);
    defer t.deinit(testing.allocator);
    try testing.expectEqual(@as(?u64, 0x10), t.pop(0xFFB4));
    try testing.expectEqual(@as(?u64, 0), t.pop(0xFF18));
}

test "vector decode rejects corrupt input" {
    var arena_state = std.heap.ArenaAllocator.init(testing.allocator);
    defer arena_state.deinit();
    const a = arena_state.allocator();
    const bytes = try encode(testing.allocator, sample());
    defer testing.allocator.free(bytes);

    for (0..bytes.len) |n| try testing.expectError(error.Corrupt, decode(a, bytes[0..n])); // every truncation
    const extra = try std.mem.concat(testing.allocator, u8, &.{ bytes, "x" });
    defer testing.allocator.free(extra);
    try testing.expectError(error.Corrupt, decode(a, extra));

    const bad = try testing.allocator.dupe(u8, bytes);
    defer testing.allocator.free(bad);
    bad[6] = 2; // version
    try testing.expectError(error.UnsupportedVersion, decode(a, bad));
    bad[6] = 1;
    bad[8] = 99; // image tag
    try testing.expectError(error.Corrupt, decode(a, bad));
    bad[8] = 0;
    std.mem.writeInt(u32, bad[29..33], 0xFFFF_FFF0, .little); // regs length
    try testing.expectError(error.Corrupt, decode(a, bad));
}
