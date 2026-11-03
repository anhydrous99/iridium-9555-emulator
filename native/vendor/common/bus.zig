//! Guest data bus (ARCHITECTURE §3.2). The emulator does every guest data access through it; Zig
//! code only through `reg.zig` handles (ram/rom globals are plain overlays and bypass it).
//! It classifies each address, logs strict accesses in order (E4), serves MMIO reads from a
//! device (system runs) or a tape (tests), faults on ROM writes and counts fuel.
const std = @import("std");
const Tape = @import("tape.zig").Tape;

pub const Kind = enum(u8) { ram, rom, mmio, shared, cpu_alias, scratch, unclassified };

/// Inclusive guest address range. A map is sorted and non-overlapping; gaps are `unclassified`.
pub const Range = struct { lo: u32, hi: u32, kind: Kind };

/// Host array that backs guest units `[base, base + mem.len)`.
pub fn Backing(comptime Unit: type) type {
    return struct { base: u32, mem: []Unit };
}

/// One logged access (E4). `value` is zero-extended to 64 bits.
pub const Access = struct { addr: u32, bits: u8, write: bool, value: u64 };

/// Why a run stopped (E1 kinds that the bus can raise).
pub const Stop = union(enum) { fault: u32, fuel_exhausted, tape_exhausted };

/// System-mode peripheral model, or the CPU for `cpu_alias` addresses.
pub const Device = struct {
    ctx: *anyopaque,
    read: *const fn (ctx: *anyopaque, addr: u32, bits: u8) u64,
    write: *const fn (ctx: *anyopaque, addr: u32, bits: u8, value: u64) void,
};

pub const Config = struct {
    /// Addressing unit: u16 for the BC5 data space, u8 for byte buses.
    Unit: type,
    /// Order of units inside a multi-unit value. BC5 u32 is high word first, so `.big`.
    endian: std.lang.Endian,
    /// Widest single bus access (BC5 16, AVR 8, SPARC/x86 32). Wider handle accesses are split
    /// into ascending-address accesses of this width, each logged on its own.
    max_access_bits: u8,
};

pub const bc5 = Config{ .Unit = u16, .endian = .big, .max_access_bits = 16 };
pub const avr = Config{ .Unit = u8, .endian = .little, .max_access_bits = 8 };
pub const sparc = Config{ .Unit = u8, .endian = .big, .max_access_bits = 32 };
pub const x86 = Config{ .Unit = u8, .endian = .little, .max_access_bits = 32 };

pub fn Bus(comptime cfg: Config) type {
    return struct {
        const Self = @This();
        pub const Unit = cfg.Unit;
        pub const config = cfg;
        const unit_bits = @bitSizeOf(Unit);
        comptime {
            if (cfg.max_access_bits % unit_bits != 0 or cfg.max_access_bits > 64) @compileError("bad max_access_bits");
        }

        gpa: std.mem.Allocator,
        map: []const Range,
        // The BC5's complete 16-bit data map fits in 64 KiB; byte buses keep range lookup.
        kinds: [if (Unit == u16) 65536 else 0]Kind = @splat(.unclassified),
        backing: []const Backing(Unit),
        tape: ?*Tape = null,
        dev: ?Device = null,
        cpu: ?Device = null,
        log: std.ArrayList(Access) = .empty,
        fuel: u64 = std.math.maxInt(u64),
        stop: ?Stop = null,
        /// Host-side runs (fork-server child) set this to write the result and `_exit`.
        on_stop: ?*const fn (Stop) noreturn = null,

        pub fn init(gpa: std.mem.Allocator, map: []const Range, backing: []const Backing(Unit)) error{BadMap}!Self {
            for (map, 0..) |r, i| {
                if (r.lo > r.hi) return error.BadMap;
                if (i > 0 and map[i - 1].hi >= r.lo) return error.BadMap;
            }
            for (backing, 0..) |b, i| {
                if (b.mem.len == 0 or b.base + (b.mem.len - 1) < b.base) return error.BadMap;
                if (i > 0 and backing[i - 1].base + backing[i - 1].mem.len > b.base) return error.BadMap;
            }
            var self = Self{ .gpa = gpa, .map = map, .backing = backing };
            for (map) |r| {
                if (r.lo < self.kinds.len) {
                    const end = @min(@as(u64, r.hi) + 1, self.kinds.len);
                    @memset(self.kinds[r.lo..@intCast(end)], r.kind);
                }
            }
            return self;
        }

        pub fn deinit(self: *Self) void {
            self.log.deinit(self.gpa);
        }

        /// Clears the log, the stop reason and refills fuel; keeps map, backing, tape, devices.
        pub fn resetRun(self: *Self, fuel: u64) void {
            self.log.clearRetainingCapacity();
            self.stop = null;
            self.fuel = fuel;
        }

        pub fn kindOf(self: *const Self, addr: u32) Kind {
            if (addr < self.kinds.len) return self.kinds[addr];
            var lo: usize = 0;
            var hi: usize = self.map.len;
            while (lo < hi) {
                const mid = (lo + hi) / 2;
                const r = self.map[mid];
                if (addr < r.lo) hi = mid else if (addr > r.hi) lo = mid + 1 else return r.kind;
            }
            return .unclassified;
        }

        /// Host cell of a guest unit, or null if no array backs it.
        pub fn unitPtr(self: *const Self, addr: u32) ?*Unit {
            for (self.backing) |b| {
                if (addr >= b.base and addr - b.base < b.mem.len) return &b.mem[addr - b.base];
            }
            return null;
        }

        pub fn read(self: *Self, addr: u32, bits: u8) u64 {
            return self.access(addr, bits, false, 0);
        }

        pub fn write(self: *Self, addr: u32, bits: u8, value: u64) void {
            _ = self.access(addr, bits, true, value);
        }

        fn access(self: *Self, addr: u32, bits: u8, is_write: bool, value: u64) u64 {
            std.debug.assert(bits % unit_bits == 0 and bits <= 64 and bits > 0);
            if (bits <= cfg.max_access_bits) return self.one(addr, bits, is_write, value);
            const step = cfg.max_access_bits;
            const n = bits / step;
            var out: u64 = 0;
            for (0..n) |i| {
                const sh: u6 = @intCast(switch (cfg.endian) {
                    .big => (n - 1 - i) * step,
                    .little => i * step,
                });
                const a = addr + @as(u32, @intCast(i * (step / unit_bits)));
                out |= self.one(a, step, is_write, (value >> sh) & mask(step)) << sh;
            }
            return out;
        }

        fn one(self: *Self, addr: u32, bits: u8, is_write: bool, value: u64) u64 {
            if (self.stop != null) return 0;
            if (self.fuel == 0) {
                self.halt(.fuel_exhausted);
                return 0;
            }
            self.fuel -= 1;
            const kind = self.kindOf(addr);
            switch (kind) {
                .ram, .scratch => return self.mem(addr, bits, is_write, value),
                .rom => {
                    if (is_write) {
                        self.halt(.{ .fault = addr });
                        return 0;
                    }
                    return self.mem(addr, bits, false, 0);
                },
                .cpu_alias => {
                    if (self.cpu) |d| return devAccess(d, addr, bits, is_write, value);
                    return self.mem(addr, bits, is_write, value);
                },
                .shared, .unclassified, .mmio => {
                    // shared is memory (unbacked faults); backed unclassified behaves like RAM;
                    // mmio and unbacked unclassified addresses go to the device or the tape.
                    const v = if (kind == .shared or (kind == .unclassified and self.unitPtr(addr) != null))
                        self.mem(addr, bits, is_write, value)
                    else if (self.dev) |d|
                        devAccess(d, addr, bits, is_write, value)
                    else if (is_write)
                        0
                    else
                        self.tapeRead(addr) & mask(bits);
                    if (self.stop != null) return 0;
                    self.log.append(self.gpa, .{
                        .addr = addr,
                        .bits = bits,
                        .write = is_write,
                        .value = if (is_write) value & mask(bits) else v,
                    }) catch @panic("bus log: out of memory");
                    return v;
                },
            }
        }

        fn mem(self: *Self, addr: u32, bits: u8, is_write: bool, value: u64) u64 {
            const n = bits / unit_bits;
            var out: u64 = 0;
            for (0..n) |i| {
                const p = self.unitPtr(addr + @as(u32, @intCast(i))) orelse {
                    self.halt(.{ .fault = addr });
                    return 0;
                };
                const sh: u6 = @intCast(switch (cfg.endian) {
                    .big => (n - 1 - i) * unit_bits,
                    .little => i * unit_bits,
                });
                if (is_write) p.* = @truncate(value >> sh) else out |= @as(u64, p.*) << sh;
            }
            return out;
        }

        fn tapeRead(self: *Self, addr: u32) u64 {
            if (self.tape) |t| if (t.pop(addr)) |v| return v;
            self.halt(.tape_exhausted);
            return 0;
        }

        pub fn halt(self: *Self, s: Stop) void {
            if (self.stop == null) self.stop = s;
            if (self.on_stop) |f| f(s);
        }
    };
}

fn devAccess(d: Device, addr: u32, bits: u8, is_write: bool, value: u64) u64 {
    if (is_write) {
        d.write(d.ctx, addr, bits, value & mask(bits));
        return 0;
    }
    return d.read(d.ctx, addr, bits) & mask(bits);
}

fn mask(bits: u8) u64 {
    return if (bits >= 64) std.math.maxInt(u64) else (@as(u64, 1) << @intCast(bits)) - 1;
}

/// Index of the first differing entry of two strict logs, or null if equal.
pub fn firstLogDiff(a: []const Access, b: []const Access) ?usize {
    const n = @min(a.len, b.len);
    for (a[0..n], b[0..n], 0..) |x, y, i| if (!std.meta.eql(x, y)) return i;
    return if (a.len == b.len) null else n;
}

/// Raw bits of an integer, bool, enum or packed struct, zero-extended.
pub fn toRaw(v: anytype) u64 {
    const T = @TypeOf(v);
    return switch (@typeInfo(T)) {
        .bool => @intFromBool(v),
        .int => @as(@Int(.unsigned, @bitSizeOf(T)), @bitCast(v)),
        .@"enum" => toRaw(@backingInt(v)),
        .@"struct" => |s| if (s.backing_integer) |I| toRaw(@as(I, @bitCast(v))) else @compileError(@typeName(T) ++ ": not a packed struct"),
        else => @compileError(@typeName(T) ++ ": no raw bit representation"),
    };
}

/// Inverse of `toRaw`. Extra high bits are dropped. An invalid exhaustive-enum value is a safety panic.
pub fn fromRaw(comptime T: type, raw: u64) T {
    const U = @Int(.unsigned, @bitSizeOf(T));
    return switch (@typeInfo(T)) {
        .bool => raw & 1 != 0,
        .int => @bitCast(@as(U, @truncate(raw))),
        .@"enum" => |e| @fromBackingInt(@intCast(fromRaw(e.tag_type, raw))),
        .@"struct" => @bitCast(@as(U, @truncate(raw))),
        else => @compileError(@typeName(T) ++ ": no raw bit representation"),
    };
}

// ---------------------------------------------------------------------------------------------
const testing = std.testing;

fn testBus16(data: []u16, map: []const Range) !Bus(bc5) {
    const S = struct {
        var backing: [1]Backing(u16) = undefined;
    };
    S.backing = .{.{ .base = 0, .mem = data }};
    return Bus(bc5).init(testing.allocator, map, &S.backing);
}

test "classification by sorted map, gaps unclassified" {
    var data: [0x10000]u16 = @splat(0);
    const map = [_]Range{
        .{ .lo = 0x0100, .hi = 0x3C7F, .kind = .rom },
        .{ .lo = 0xA000, .hi = 0xFCFF, .kind = .ram },
        .{ .lo = 0xFF00, .hi = 0xFFDF, .kind = .mmio },
        .{ .lo = 0xFFE0, .hi = 0xFFE1, .kind = .cpu_alias },
        .{ .lo = 0xFFF0, .hi = 0xFFFF, .kind = .scratch },
    };
    var b = try testBus16(&data, &map);
    defer b.deinit();
    try testing.expectEqual(Kind.rom, b.kindOf(0x0100));
    try testing.expectEqual(Kind.rom, b.kindOf(0x3C7F));
    try testing.expectEqual(Kind.unclassified, b.kindOf(0x3C80));
    try testing.expectEqual(Kind.unclassified, b.kindOf(0x00FF));
    try testing.expectEqual(Kind.ram, b.kindOf(0xA000));
    try testing.expectEqual(Kind.mmio, b.kindOf(0xFFDF));
    try testing.expectEqual(Kind.cpu_alias, b.kindOf(0xFFE1));
    try testing.expectEqual(Kind.unclassified, b.kindOf(0xFFE2));
    try testing.expectEqual(Kind.scratch, b.kindOf(0xFFFF));
}

test "bad maps are rejected" {
    var data: [16]u16 = @splat(0);
    const overlap = [_]Range{ .{ .lo = 0, .hi = 5, .kind = .ram }, .{ .lo = 5, .hi = 9, .kind = .rom } };
    try testing.expectError(error.BadMap, testBus16(&data, &overlap));
    const unsorted = [_]Range{ .{ .lo = 8, .hi = 9, .kind = .ram }, .{ .lo = 0, .hi = 1, .kind = .rom } };
    try testing.expectError(error.BadMap, testBus16(&data, &unsorted));
}

test "16-bit classification agrees with ranges including gaps and wider addresses" {
    var data: [16]u16 = @splat(0);
    const map = [_]Range{
        .{ .lo = 1, .hi = 3, .kind = .mmio },
        .{ .lo = 0x100, .hi = 0x3FFF, .kind = .rom },
        .{ .lo = 0xA000, .hi = 0xFD04, .kind = .ram },
        .{ .lo = 0xFD05, .hi = 0xFD05, .kind = .mmio },
        .{ .lo = 0xFFF0, .hi = 0xFFFFFFFF, .kind = .scratch },
    };
    var b = try testBus16(&data, &map);
    defer b.deinit();
    for (0..65536) |addr| {
        var expected: Kind = .unclassified;
        for (map) |r| {
            if (addr >= r.lo and addr <= r.hi) {
                expected = r.kind;
                break;
            }
        }
        try testing.expectEqual(expected, b.kindOf(@intCast(addr)));
    }
    try testing.expectEqual(Kind.scratch, b.kindOf(0x10000));
    try testing.expectEqual(Kind.scratch, b.kindOf(0xFFFFFFFF));
}

test "strict log keeps order; ram and scratch are not logged; mmio reads come from the tape" {
    var data: [0x10000]u16 = @splat(0);
    const map = [_]Range{
        .{ .lo = 0x00A0, .hi = 0x00A0, .kind = .shared },
        .{ .lo = 0xA000, .hi = 0xFCFF, .kind = .ram },
        .{ .lo = 0xFF00, .hi = 0xFFDF, .kind = .mmio },
        .{ .lo = 0xFFF0, .hi = 0xFFFF, .kind = .scratch },
    };
    var b = try testBus16(&data, &map);
    defer b.deinit();
    var t = try Tape.init(testing.allocator, &.{
        .{ .addr = 0xFF18, .value = 0x8000 },
        .{ .addr = 0xFF20, .value = 7 },
        .{ .addr = 0xFF18, .value = 0 },
    });
    defer t.deinit(testing.allocator);
    b.tape = &t;

    b.write(0xA000, 16, 0x1234);
    b.write(0xFFF2, 16, 9);
    try testing.expectEqual(@as(u64, 0x8000), b.read(0xFF18, 16));
    b.write(0x00A0, 16, 5);
    try testing.expectEqual(@as(u64, 7), b.read(0xFF20, 16)); // per-address streams
    try testing.expectEqual(@as(u64, 0), b.read(0xFF18, 16));
    try testing.expectEqual(@as(u64, 5), b.read(0x0050, 16) + b.read(0x00A0, 16)); // 0x50: unclassified, backed
    b.write(0xFF30, 16, 0xBEEF);

    try testing.expectEqual(@as(u16, 0x1234), data[0xA000]);
    try testing.expectEqual(@as(u16, 9), data[0xFFF2]);
    try testing.expectEqual(@as(u16, 0), data[0xFF30]); // mmio writes do not land in memory
    const want = [_]Access{
        .{ .addr = 0xFF18, .bits = 16, .write = false, .value = 0x8000 },
        .{ .addr = 0x00A0, .bits = 16, .write = true, .value = 5 },
        .{ .addr = 0xFF20, .bits = 16, .write = false, .value = 7 },
        .{ .addr = 0xFF18, .bits = 16, .write = false, .value = 0 },
        .{ .addr = 0x0050, .bits = 16, .write = false, .value = 0 },
        .{ .addr = 0x00A0, .bits = 16, .write = false, .value = 5 },
        .{ .addr = 0xFF30, .bits = 16, .write = true, .value = 0xBEEF },
    };
    try testing.expectEqualSlices(Access, &want, b.log.items);
    try testing.expectEqual(@as(?usize, null), firstLogDiff(&want, b.log.items));
    try testing.expectEqual(@as(?usize, 6), firstLogDiff(&want, b.log.items[0..6]));
    try testing.expectEqual(@as(?Stop, null), b.stop);

    _ = b.read(0xFF18, 16); // stream for 0xFF18 is used up
    try testing.expectEqual(Stop.tape_exhausted, b.stop.?);
    const n = b.log.items.len;
    _ = b.read(0xFF20, 16); // after a stop nothing is performed or logged
    try testing.expectEqual(n, b.log.items.len);
}

test "rom write faults, fuel runs out" {
    var data: [0x10000]u16 = @splat(0);
    data[0x0100] = 0xCAFE;
    const map = [_]Range{.{ .lo = 0x0100, .hi = 0x3C7F, .kind = .rom }};
    var b = try testBus16(&data, &map);
    defer b.deinit();
    try testing.expectEqual(@as(u64, 0xCAFE), b.read(0x0100, 16));
    b.write(0x0101, 16, 1);
    try testing.expectEqual(Stop{ .fault = 0x0101 }, b.stop.?);
    try testing.expectEqual(@as(u16, 0), data[0x0101]);

    b.resetRun(2);
    _ = b.read(0x0100, 16);
    _ = b.read(0x0100, 16);
    try testing.expectEqual(@as(?Stop, null), b.stop);
    _ = b.read(0x0100, 16);
    try testing.expectEqual(Stop.fuel_exhausted, b.stop.?);
}

test "wide accesses: BC5 u32 is two word accesses, high word first; SPARC is one BE access" {
    var data: [0x10000]u16 = @splat(0);
    const map = [_]Range{.{ .lo = 0xA000, .hi = 0xA0FF, .kind = .shared }};
    var b = try testBus16(&data, &map);
    defer b.deinit();
    b.write(0xA010, 32, 0x11223344);
    try testing.expectEqual(@as(u16, 0x1122), data[0xA010]);
    try testing.expectEqual(@as(u16, 0x3344), data[0xA011]);
    try testing.expectEqual(@as(u64, 0x11223344), b.read(0xA010, 32));
    try testing.expectEqual(@as(usize, 4), b.log.items.len);
    try testing.expectEqual(@as(u32, 0xA011), b.log.items[1].addr);
    try testing.expectEqual(@as(u64, 0x3344), b.log.items[1].value);

    var ram: [0x100]u8 = @splat(0);
    const backing = [_]Backing(u8){.{ .base = 0x40000000, .mem = &ram }};
    const smap = [_]Range{
        .{ .lo = 0x40000000, .hi = 0x400001FF, .kind = .ram }, // only 0x100 bytes backed
        .{ .lo = 0x80000100, .hi = 0x800017FF, .kind = .mmio },
    };
    var s = try Bus(sparc).init(testing.allocator, &smap, &backing);
    defer s.deinit();
    s.write(0x40000004, 32, 0xA1B2C3D4);
    try testing.expectEqualSlices(u8, &.{ 0xA1, 0xB2, 0xC3, 0xD4 }, ram[4..8]);
    try testing.expectEqual(@as(u64, 0xB2C3), s.read(0x40000005, 16));
    s.write(0x80000904, 32, 0xFFFF_FFFF);
    try testing.expectEqual(@as(usize, 1), s.log.items.len);
    try testing.expectEqual(@as(u8, 32), s.log.items[0].bits);
    _ = s.read(0x40000100, 8); // ram class but no backing: fault
    try testing.expectEqual(Stop{ .fault = 0x40000100 }, s.stop.?);
}

test "devices serve mmio and cpu_alias" {
    const Dev = struct {
        last: u64 = 0,
        fn rd(ctx: *anyopaque, addr: u32, bits: u8) u64 {
            _ = bits;
            const d: *@This() = @ptrCast(@alignCast(ctx));
            return d.last + addr;
        }
        fn wr(ctx: *anyopaque, addr: u32, bits: u8, value: u64) void {
            _ = .{ addr, bits };
            const d: *@This() = @ptrCast(@alignCast(ctx));
            d.last = value;
        }
    };
    var data: [0x10000]u16 = @splat(0);
    const map = [_]Range{
        .{ .lo = 0xFF00, .hi = 0xFFDF, .kind = .mmio },
        .{ .lo = 0xFFE0, .hi = 0xFFE4, .kind = .cpu_alias },
    };
    var b = try testBus16(&data, &map);
    defer b.deinit();
    var mm: Dev = .{};
    var cpu: Dev = .{};
    b.dev = .{ .ctx = &mm, .read = Dev.rd, .write = Dev.wr };
    b.cpu = .{ .ctx = &cpu, .read = Dev.rd, .write = Dev.wr };
    b.write(0xFF95, 16, 2);
    try testing.expectEqual(@as(u64, 2 + 0xFF00), b.read(0xFF00, 16));
    b.write(0xFFE1, 16, 0x10);
    try testing.expectEqual(@as(u64, 0x10 + 0xFFE4), b.read(0xFFE4, 16));
    try testing.expectEqual(@as(usize, 2), b.log.items.len); // cpu_alias is not logged
}

test "toRaw/fromRaw" {
    const P = packed struct(u16) { lo: u4, mid: bool, hi: u11 };
    const E = enum(u8) { a = 1, b = 0xF0, _ };
    try testing.expectEqual(@as(u64, 0xFFFB), toRaw(@as(i16, -5)));
    try testing.expectEqual(@as(i16, -5), fromRaw(i16, 0x1_FFFB));
    try testing.expectEqual(@as(u64, 0xF0), toRaw(E.b));
    try testing.expectEqual(E.a, fromRaw(E, 0x101));
    const p = P{ .lo = 3, .mid = true, .hi = 0x7FF };
    try testing.expectEqual(@as(u64, 0xFFF3), toRaw(p));
    try testing.expectEqual(p, fromRaw(P, 0xFFF3));
    try testing.expectEqual(true, fromRaw(bool, 1));
}
