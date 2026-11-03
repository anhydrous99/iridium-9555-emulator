//! Big-endian overlays (SPARC) and sparse 32-bit guest spaces (ARCHITECTURE §4.3).
//! Multi-byte SPARC fields are `Be(T)`; guest pointers are `Space(..).Ptr(T)` (BePtr) and code
//! pointers `Space(..).CodePtr` (CodePtr32). Both hold the original guest address bits.
//! Packed-struct fields count from bit 0 of the integer (as the masks in the listings do).
const std = @import("std");
const bus = @import("bus.zig");

/// A `T` stored big-endian. Same size and alignment as `T`.
/// T: integer, enum or packed struct whose bit size fills its bytes.
pub fn Be(comptime T: type) type {
    if (@sizeOf(T) * 8 != @bitSizeOf(T)) @compileError(@typeName(T) ++ ": Be(T) needs a type without padding bits");
    const I = @Int(.unsigned, @bitSizeOf(T));
    return extern struct {
        raw: I align(@alignOf(T)),
        const Self = @This();
        pub const Value = T;

        pub fn init(v: T) Self {
            return .{ .raw = std.mem.nativeToBig(I, @truncate(bus.toRaw(v))) };
        }
        pub fn get(s: Self) T {
            return bus.fromRaw(T, std.mem.bigToNative(I, s.raw));
        }
        pub fn set(s: *Self, v: T) void {
            s.* = init(v);
        }
    };
}

/// Host array backing guest bytes `[base, base + mem.len)`. Same type the Bus uses.
pub const Region = bus.Backing(u8);

/// Typed access to a sparse byte space. `regions` points at the image's process-global region
/// table (set once at worker start; arrays page-aligned so guest and host alignment agree).
pub fn Space(comptime endian: std.lang.Endian, comptime regions: *const []const Region) type {
    return struct {
        fn enc(a: u32) u32 {
            return if (endian == .big) std.mem.nativeToBig(u32, a) else std.mem.nativeToLittle(u32, a);
        }
        fn dec(raw: u32) u32 {
            return if (endian == .big) std.mem.bigToNative(u32, raw) else std.mem.littleToNative(u32, raw);
        }

        /// Host view of `T` at `addr`, or null if no single region holds all of it.
        /// A misaligned address is a safety panic (the guest would trap too).
        pub fn host(comptime T: type, addr: u32) ?*T {
            for (regions.*) |r| {
                if (addr < r.base) continue;
                const off = addr - r.base;
                if (off < r.mem.len and r.mem.len - off >= @sizeOf(T)) return @ptrCast(@alignCast(&r.mem[off]));
            }
            return null;
        }

        pub fn at(comptime T: type, addr: u32) *T {
            return host(T, addr) orelse @panic("be.Space.at: unmapped guest address");
        }

        /// Guest address of a host pointer into one of the regions.
        pub fn guest(p: anytype) u32 {
            const a = @intFromPtr(p);
            for (regions.*) |r| {
                const b = @intFromPtr(r.mem.ptr);
                if (a >= b and a - b < r.mem.len) return r.base + @as(u32, @intCast(a - b));
            }
            @panic("be.Space.guest: pointer is not into guest memory");
        }

        /// 32-bit guest data pointer stored in the space's byte order.
        pub fn Ptr(comptime T: type) type {
            return extern struct {
                raw: u32,
                const P = @This();
                pub const Target = T;
                pub const none: P = .{ .raw = 0 };

                pub fn fromAddr(a: u32) P {
                    return .{ .raw = enc(a) };
                }
                pub fn addr(p: P) u32 {
                    return dec(p.raw);
                }
                /// Host view; null for address 0, panic for an unmapped address.
                pub fn get(p: P) ?*T {
                    const a = p.addr();
                    return if (a == 0) null else at(T, a);
                }
                pub fn of(x: ?*const T) P {
                    return if (x) |q| fromAddr(guest(q)) else none;
                }
                pub fn set(p: *P, x: ?*const T) void {
                    p.* = of(x);
                }
                /// `p + n` in elements, wrapping at 32 bits.
                pub fn add(p: P, n: i32) P {
                    return fromAddr(p.addr() +% @as(u32, @bitCast(n *% @as(i32, @sizeOf(T)))));
                }
                pub fn cast(p: P, comptime U: type) Ptr(U) {
                    return .{ .raw = p.raw };
                }
                pub fn toAbi(p: P) u64 {
                    return p.addr();
                }
                pub fn fromAbi(x: u64) P {
                    return fromAddr(@truncate(x));
                }
            };
        }

        /// 32-bit code pointer holding an original code address (registry address).
        pub const CodePtr = extern struct {
            raw: u32,
            pub const none: CodePtr = .{ .raw = 0 };
            pub fn fromAddr(a: u32) CodePtr {
                return .{ .raw = enc(a) };
            }
            pub fn addr(p: CodePtr) u32 {
                return dec(p.raw);
            }
            pub fn toAbi(p: CodePtr) u64 {
                return p.addr();
            }
            pub fn fromAbi(x: u64) CodePtr {
                return fromAddr(@truncate(x));
            }
        };
    };
}

// ---------------------------------------------------------------------------------------------
const testing = std.testing;

test "Be(T): same size/alignment, big-endian bytes, round-trips" {
    inline for (.{ u16, u32, i32, u64, u8 }) |T| {
        try testing.expectEqual(@sizeOf(T), @sizeOf(Be(T)));
        try testing.expectEqual(@alignOf(T), @alignOf(Be(T)));
    }
    var x = Be(u32).init(0x11223344);
    try testing.expectEqualSlices(u8, &.{ 0x11, 0x22, 0x33, 0x44 }, std.mem.asBytes(&x));
    try testing.expectEqual(@as(u32, 0x11223344), x.get());
    x.set(0xDEADBEEF);
    try testing.expectEqual(@as(u8, 0xDE), std.mem.asBytes(&x)[0]);

    const y = Be(i16).init(-2);
    try testing.expectEqualSlices(u8, &.{ 0xFF, 0xFE }, std.mem.asBytes(&y));
    try testing.expectEqual(@as(i16, -2), y.get());

    const E = enum(u16) { idle = 1, busy = 0x0102 };
    const e = Be(E).init(.busy);
    try testing.expectEqualSlices(u8, &.{ 0x01, 0x02 }, std.mem.asBytes(&e));
    try testing.expectEqual(E.busy, e.get());

    const Ctl = packed struct(u32) { enable: bool, mode: u3, _r: u24, top: u4 };
    const c = Be(Ctl).init(.{ .enable = true, .mode = 5, ._r = 0, .top = 0xA });
    try testing.expectEqualSlices(u8, &.{ 0xA0, 0x00, 0x00, 0x0B }, std.mem.asBytes(&c));
    try testing.expectEqual(@as(u3, 5), c.get().mode);

    // bytes read from a guest image decode directly
    const raw = [_]u8{ 0x70, 0x08, 0x3B, 0xCC };
    const f: *align(1) const Be(u32) = @ptrCast(&raw);
    try testing.expectEqual(@as(u32, 0x70083BCC), f.get());
}

const TS = struct {
    var flash: [0x100]u8 align(4096) = @splat(0xFF);
    var sdram: [0x100]u8 align(4096) = @splat(0);
    var regions: []const Region = &.{};
};
const Trx = Space(.big, &TS.regions);

// Nucleus task table record (trx-coverage §1.1), 0x18 bytes.
const TaskSpec = extern struct {
    entry: Trx.CodePtr,
    stack: Trx.Ptr(u8),
    stack_size: Be(u32),
    prio: Be(u32),
    name: [8]u8,
};

test "SPARC overlay sizes/offsets, decoded on the real first task record" {
    try testing.expectEqual(0x18, @sizeOf(TaskSpec));
    try testing.expectEqual(4, @offsetOf(TaskSpec, "stack"));
    try testing.expectEqual(8, @offsetOf(TaskSpec, "stack_size"));
    try testing.expectEqual(12, @offsetOf(TaskSpec, "prio"));
    try testing.expectEqual(16, @offsetOf(TaskSpec, "name"));
    // firmware/trx_seg1_0x10000.bin at flash 0x26CD70, record 0 (the DPL task)
    var rec align(4) = [_]u8{
        0x00, 0x0e, 0x2b, 0x58, 0x70, 0x03, 0x37, 0xe8, 0x00, 0x00, 0x10, 0x00,
        0x00, 0x00, 0x00, 0x0c, 0x44, 0x50, 0x4c, 0x00, 0x00, 0x00, 0x00, 0x00,
    };
    const t: *const TaskSpec = @ptrCast(&rec);
    try testing.expectEqual(@as(u32, 0x000E2B58), t.entry.addr());
    try testing.expectEqual(@as(u32, 0x700337E8), t.stack.addr());
    try testing.expectEqual(@as(u32, 0x1000), t.stack_size.get());
    try testing.expectEqual(@as(u32, 12), t.prio.get());
    try testing.expectEqualStrings("DPL", std.mem.sliceTo(&t.name, 0));
}

test "Space: host/guest mapping and BePtr round-trips" {
    const regs = [_]Region{ .{ .base = 0x00010000, .mem = &TS.flash }, .{ .base = 0x40000000, .mem = &TS.sdram } };
    TS.regions = &regs;
    defer TS.regions = &.{};
    @memset(&TS.sdram, 0);

    try testing.expectEqual(@as(?*u32, null), Trx.host(u32, 0x40000100)); // past the array
    try testing.expectEqual(@as(?*u32, null), Trx.host(u32, 0x400000FE)); // straddles the end
    try testing.expectEqual(@as(?*u32, null), Trx.host(u32, 0x20000000));
    try testing.expectEqual(@as(u32, 0xFFFFFFFF), Trx.at(u32, 0x00010010).*);

    const v = Trx.at(Be(u32), 0x40000010);
    v.set(0xCAFEBABE);
    try testing.expectEqualSlices(u8, &.{ 0xCA, 0xFE, 0xBA, 0xBE }, TS.sdram[0x10..0x14]);
    const p = Trx.Ptr(Be(u32)).of(v);
    try testing.expectEqual(@as(u32, 0x40000010), p.addr());
    try testing.expectEqual(v, p.get().?);
    try testing.expectEqual(@as(?*Be(u32), null), Trx.Ptr(Be(u32)).none.get());
    try testing.expectEqual(@as(u32, 0x40000018), p.add(2).addr());
    try testing.expectEqual(@as(u32, 0x4000000C), p.add(-1).addr());
    try testing.expectEqual(@as(u32, 0x40000010), p.cast(u8).addr());
    try testing.expectEqual(p, Trx.Ptr(Be(u32)).fromAbi(p.toAbi()));

    // a stored pointer is the big-endian original value
    const slot = Trx.at(Trx.Ptr(Be(u32)), 0x40000020);
    slot.set(v);
    try testing.expectEqualSlices(u8, &.{ 0x40, 0x00, 0x00, 0x10 }, TS.sdram[0x20..0x24]);
    try testing.expectEqual(@as(u32, 0xCAFEBABE), slot.get().?.get());
    slot.set(null);
    try testing.expectEqual(@as(u32, 0), slot.addr());

    const Le = Space(.little, &TS.regions);
    const q = Le.Ptr(u32).fromAddr(0x40000010);
    try testing.expectEqualSlices(u8, &.{ 0x10, 0x00, 0x00, 0x40 }, std.mem.asBytes(&q));
}
