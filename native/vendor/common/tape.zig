//! Peripheral input tapes (ARCHITECTURE §7.4). A read of a taped address pops the next value
//! recorded for *that address*; when its stream is used up it returns the stream's default
//! (polled registers) or, without one, the bus stops with `tape_exhausted`.
const std = @import("std");

/// One recorded read value.
pub const Entry = struct { addr: u32, value: u64 };

pub const Tape = struct {
    streams: std.AutoHashMapUnmanaged(u32, Stream) = .empty,

    pub const Stream = struct {
        values: std.ArrayList(u64) = .empty,
        pos: usize = 0,
        default: ?u64 = null,
    };

    pub fn init(gpa: std.mem.Allocator, entries: []const Entry) !Tape {
        var t: Tape = .{};
        errdefer t.deinit(gpa);
        for (entries) |e| try t.append(gpa, e.addr, e.value);
        return t;
    }

    pub fn deinit(t: *Tape, gpa: std.mem.Allocator) void {
        var it = t.streams.valueIterator();
        while (it.next()) |s| s.values.deinit(gpa);
        t.streams.deinit(gpa);
    }

    pub fn append(t: *Tape, gpa: std.mem.Allocator, addr: u32, value: u64) !void {
        const g = try t.streams.getOrPut(gpa, addr);
        if (!g.found_existing) g.value_ptr.* = .{};
        try g.value_ptr.values.append(gpa, value);
    }

    /// Value returned for `addr` once its recorded values are used up.
    pub fn setDefault(t: *Tape, gpa: std.mem.Allocator, addr: u32, value: u64) !void {
        const g = try t.streams.getOrPut(gpa, addr);
        if (!g.found_existing) g.value_ptr.* = .{};
        g.value_ptr.default = value;
    }

    pub fn pop(t: *Tape, addr: u32) ?u64 {
        const s = t.streams.getPtr(addr) orelse return null;
        if (s.pos < s.values.items.len) {
            s.pos += 1;
            return s.values.items[s.pos - 1];
        }
        return s.default;
    }

    /// Back to the start of every stream, so the candidate run sees what the reference run saw.
    pub fn rewind(t: *Tape) void {
        var it = t.streams.valueIterator();
        while (it.next()) |s| s.pos = 0;
    }

    /// Recorded values not yet consumed (all streams).
    pub fn remaining(t: *const Tape) usize {
        var n: usize = 0;
        var it = t.streams.valueIterator();
        while (it.next()) |s| n += s.values.items.len - s.pos;
        return n;
    }
};

test "per-address streams, defaults, rewind" {
    const gpa = std.testing.allocator;
    var t = try Tape.init(gpa, &.{ .{ .addr = 1, .value = 10 }, .{ .addr = 2, .value = 20 }, .{ .addr = 1, .value = 11 } });
    defer t.deinit(gpa);
    try t.setDefault(gpa, 2, 0x99);
    try std.testing.expectEqual(@as(?u64, 20), t.pop(2));
    try std.testing.expectEqual(@as(?u64, 10), t.pop(1));
    try std.testing.expectEqual(@as(usize, 1), t.remaining());
    try std.testing.expectEqual(@as(?u64, 11), t.pop(1));
    try std.testing.expectEqual(@as(?u64, null), t.pop(1));
    try std.testing.expectEqual(@as(?u64, 0x99), t.pop(2));
    try std.testing.expectEqual(@as(?u64, null), t.pop(3));
    t.rewind();
    try std.testing.expectEqual(@as(?u64, 10), t.pop(1));
    try std.testing.expectEqual(@as(usize, 2), t.remaining());
}
