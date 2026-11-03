//! Machine snapshots (ARCHITECTURE §3.2, §7.1, §7.3). A `Machine` lists every writable part of
//! one image's state: guest memory arrays, CPU state, device state. A snapshot is one buffer with
//! all parts; restore is a @memcpy per part. E3 compares memory parts with `firstDiff`.
//! Parts must be plain data (no host pointers), so bytes alone restore them.
const std = @import("std");

pub const Part = struct {
    name: []const u8,
    bytes: []u8,
    /// Guest address of `bytes[0]` for memory parts; null for CPU/device state.
    base: ?u32 = null,
    /// Bytes per guest address unit (BC5 data words: 2).
    unit: u8 = 1,

    pub fn memory(name: []const u8, base: u32, comptime Unit: type, mem: []Unit) Part {
        return .{ .name = name, .bytes = std.mem.sliceAsBytes(mem), .base = base, .unit = @sizeOf(Unit) };
    }
    pub fn state(name: []const u8, ptr: anytype) Part {
        return .{ .name = name, .bytes = std.mem.asBytes(ptr) };
    }
};

pub const Snapshot = struct {
    bytes: []u8,

    pub fn deinit(s: *Snapshot, gpa: std.mem.Allocator) void {
        gpa.free(s.bytes);
        s.* = undefined;
    }
    /// Content address (`SnapshotRef`): the first 16 bytes of BLAKE3 over the state.
    pub fn digest(s: Snapshot) [16]u8 {
        var out: [16]u8 = undefined;
        std.crypto.hash.Blake3.hash(s.bytes, &out, .{});
        return out;
    }
    pub fn eql(a: Snapshot, b: Snapshot) bool {
        return std.mem.eql(u8, a.bytes, b.bytes);
    }
};

/// Inclusive guest address range.
pub const Range = struct { lo: u32, hi: u32 };

pub const Compare = struct {
    /// Validated exclusions (guest addresses, memory parts only).
    exclude: []const Range = &.{},
    /// E3: compare memory parts only (registers are E2's job).
    memory_only: bool = false,
};

/// First difference: part, byte offset in the part, guest address (memory parts) and the two
/// unit values (bytes for state parts).
pub const Diff = struct { part: []const u8, offset: usize, addr: ?u32, a: u64, b: u64 };

pub const Machine = struct {
    parts: []const Part,

    pub fn size(m: Machine) usize {
        var n: usize = 0;
        for (m.parts) |p| n += p.bytes.len;
        return n;
    }

    pub fn capture(m: Machine, gpa: std.mem.Allocator) !Snapshot {
        const s: Snapshot = .{ .bytes = try gpa.alloc(u8, m.size()) };
        m.captureInto(s);
        return s;
    }

    /// Reuses an existing buffer of the right size.
    pub fn captureInto(m: Machine, s: Snapshot) void {
        std.debug.assert(s.bytes.len == m.size());
        var off: usize = 0;
        for (m.parts) |p| {
            @memcpy(s.bytes[off..][0..p.bytes.len], p.bytes);
            off += p.bytes.len;
        }
    }

    pub fn restore(m: Machine, s: Snapshot) error{LayoutMismatch}!void {
        if (s.bytes.len != m.size()) return error.LayoutMismatch;
        var off: usize = 0;
        for (m.parts) |p| {
            @memcpy(p.bytes, s.bytes[off..][0..p.bytes.len]);
            off += p.bytes.len;
        }
    }

    pub fn firstDiff(m: Machine, a: Snapshot, b: Snapshot, opts: Compare) ?Diff {
        std.debug.assert(a.bytes.len == m.size() and b.bytes.len == m.size());
        var off: usize = 0;
        for (m.parts) |p| {
            defer off += p.bytes.len;
            if (opts.memory_only and p.base == null) continue;
            const x = a.bytes[off..][0..p.bytes.len];
            const y = b.bytes[off..][0..p.bytes.len];
            if (std.mem.eql(u8, x, y)) continue;
            const u: usize = if (p.base == null) 1 else p.unit;
            var i: usize = 0;
            while (i < x.len) : (i += u) {
                if (std.mem.eql(u8, x[i..][0..u], y[i..][0..u])) continue;
                const addr: ?u32 = if (p.base) |base| base + @as(u32, @intCast(i / u)) else null;
                if (addr) |ad| if (excluded(opts.exclude, ad)) continue;
                return .{ .part = p.name, .offset = i, .addr = addr, .a = unitValue(x[i..][0..u]), .b = unitValue(y[i..][0..u]) };
            }
        }
        return null;
    }

    /// Self-describing file form: header (parts) + state bytes. Checked against the layout on load.
    pub fn serialize(m: Machine, gpa: std.mem.Allocator, s: Snapshot) ![]u8 {
        var out: std.ArrayList(u8) = .empty;
        errdefer out.deinit(gpa);
        try out.appendSlice(gpa, magic);
        try putInt(&out, gpa, u32, @intCast(m.parts.len));
        for (m.parts) |p| {
            try putInt(&out, gpa, u16, @intCast(p.name.len));
            try out.appendSlice(gpa, p.name);
            try putInt(&out, gpa, u8, @intFromBool(p.base != null));
            try putInt(&out, gpa, u32, p.base orelse 0);
            try putInt(&out, gpa, u8, p.unit);
            try putInt(&out, gpa, u64, p.bytes.len);
        }
        try out.appendSlice(gpa, s.bytes);
        return out.toOwnedSlice(gpa);
    }

    pub fn deserialize(m: Machine, gpa: std.mem.Allocator, bytes: []const u8) error{ Corrupt, LayoutMismatch, OutOfMemory }!Snapshot {
        var r: Reader = .{ .buf = bytes };
        if (!std.mem.eql(u8, try r.take(magic.len), magic)) return error.Corrupt;
        if (try r.int(u32) != m.parts.len) return error.LayoutMismatch;
        for (m.parts) |p| {
            const name = try r.take(try r.int(u16));
            const has_base = try r.int(u8) != 0;
            const base = try r.int(u32);
            const unit = try r.int(u8);
            const len = try r.int(u64);
            if (!std.mem.eql(u8, name, p.name) or has_base != (p.base != null) or
                base != (p.base orelse 0) or unit != p.unit or len != p.bytes.len) return error.LayoutMismatch;
        }
        const body = try r.take(m.size());
        if (r.pos != bytes.len) return error.Corrupt;
        return .{ .bytes = try gpa.dupe(u8, body) };
    }
};

const magic = "FWSNAP\x00\x01";

fn excluded(ex: []const Range, addr: u32) bool {
    for (ex) |r| if (addr >= r.lo and addr <= r.hi) return true;
    return false;
}

fn unitValue(b: []const u8) u64 {
    var v: u64 = 0;
    for (0..b.len) |i| v |= @as(u64, b[i]) << @intCast(8 * i); // host order (little-endian)
    return v;
}

pub fn putInt(out: *std.ArrayList(u8), gpa: std.mem.Allocator, comptime T: type, v: T) !void {
    var b: [@sizeOf(T)]u8 = undefined;
    std.mem.writeInt(T, &b, v, .little);
    try out.appendSlice(gpa, &b);
}

/// Bounds-checked little-endian reader over untrusted bytes.
pub const Reader = struct {
    buf: []const u8,
    pos: usize = 0,

    pub fn take(r: *Reader, n: usize) error{Corrupt}![]const u8 {
        if (n > r.buf.len - r.pos) return error.Corrupt;
        defer r.pos += n;
        return r.buf[r.pos..][0..n];
    }
    pub fn int(r: *Reader, comptime T: type) error{Corrupt}!T {
        return std.mem.readInt(T, (try r.take(@sizeOf(T)))[0..@sizeOf(T)], .little);
    }
    pub fn remaining(r: *const Reader) usize {
        return r.buf.len - r.pos;
    }
};

// ---------------------------------------------------------------------------------------------
const testing = std.testing;

const Cpu = extern struct { pc: u32, y: u16, al: u16, ah: u16, flags: u16 };
const TS = struct {
    var data: [0x10000]u16 = @splat(0);
    var cpu: Cpu = .{ .pc = 0x5A78, .y = 0xFCE0, .al = 1, .ah = 2, .flags = 0 };
    var dev: [8]u8 = @splat(0);
};

fn machine() Machine {
    const S = struct {
        var parts: [3]Part = undefined;
    };
    S.parts = .{ Part.memory("data", 0, u16, &TS.data), Part.state("cpu", &TS.cpu), Part.state("dev", &TS.dev) };
    return .{ .parts = &S.parts };
}

test "capture, mutate, restore: snapshots equal, first difference located" {
    const gpa = testing.allocator;
    const m = machine();
    try testing.expectEqual(@as(usize, 0x20000 + @sizeOf(Cpu) + 8), m.size());
    TS.data[0xF960] = 0xAAAA;
    var s0 = try m.capture(gpa);
    defer s0.deinit(gpa);

    TS.data[0xA123] = 0x55;
    TS.data[0xFFF4] = 0x99; // scratch: excluded below
    TS.cpu.al = 7;
    var s1 = try m.capture(gpa);
    defer s1.deinit(gpa);
    try testing.expect(!s0.eql(s1));
    try testing.expect(!std.mem.eql(u8, &s0.digest(), &s1.digest()));

    const d = m.firstDiff(s0, s1, .{}).?;
    try testing.expectEqualStrings("data", d.part);
    try testing.expectEqual(@as(?u32, 0xA123), d.addr);
    try testing.expectEqual(@as(usize, 0xA123 * 2), d.offset);
    try testing.expectEqual(@as(u64, 0), d.a);
    try testing.expectEqual(@as(u64, 0x55), d.b);

    const ex = [_]Range{ .{ .lo = 0xA000, .hi = 0xA1FF }, .{ .lo = 0xFFF0, .hi = 0xFFFF } };
    const d2 = m.firstDiff(s0, s1, .{ .exclude = &ex }).?;
    try testing.expectEqualStrings("cpu", d2.part);
    try testing.expectEqual(@as(?u32, null), d2.addr);
    try testing.expectEqual(@as(usize, @offsetOf(Cpu, "al")), d2.offset);
    try testing.expectEqual(@as(?Diff, null), m.firstDiff(s0, s1, .{ .exclude = &ex, .memory_only = true }));

    try m.restore(s0);
    try testing.expectEqual(@as(u16, 0), TS.data[0xA123]);
    try testing.expectEqual(@as(u16, 1), TS.cpu.al);
    try testing.expectEqual(@as(u16, 0xAAAA), TS.data[0xF960]);
    var s2 = try m.capture(gpa);
    defer s2.deinit(gpa);
    try testing.expect(s0.eql(s2));
    try testing.expectEqualSlices(u8, &s0.digest(), &s2.digest());
    try testing.expectEqual(@as(?Diff, null), m.firstDiff(s0, s2, .{}));

    try testing.expectError(error.LayoutMismatch, m.restore(.{ .bytes = s0.bytes[1..] }));
}

test "serialize/deserialize round-trip and validation" {
    const gpa = testing.allocator;
    const m = machine();
    TS.data[0x1234] = 0xBEEF;
    var s = try m.capture(gpa);
    defer s.deinit(gpa);
    const file = try m.serialize(gpa, s);
    defer gpa.free(file);
    var back = try m.deserialize(gpa, file);
    defer back.deinit(gpa);
    try testing.expect(s.eql(back));

    try testing.expectError(error.Corrupt, m.deserialize(gpa, file[0 .. file.len - 1]));
    try testing.expectError(error.Corrupt, m.deserialize(gpa, file[0..5]));
    const other: Machine = .{ .parts = m.parts[0..2] };
    try testing.expectError(error.LayoutMismatch, other.deserialize(gpa, file));
    const bad = try gpa.dupe(u8, file);
    defer gpa.free(bad);
    bad[8 + 4 + 2] = 'X'; // first part's name
    try testing.expectError(error.LayoutMismatch, m.deserialize(gpa, bad));
}
