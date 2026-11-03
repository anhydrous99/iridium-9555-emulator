//! Typed handles for addresses that are not plain overlays (ARCHITECTURE §4.4): `Reg` for MMIO,
//! `Shared` for ISR/task-shared globals, `Unclassified` for unproven addresses. Every access goes
//! through the image's process-global Bus, so it is classified by the map, logged (E4) in order
//! with the emulator's accesses, and served by the tape or device.
//! T is a native integer, enum or packed struct; the bus applies the guest byte/word order.
const std = @import("std");
const bus = @import("bus.zig");

/// Bind once per image: `pub var bus: Bus(cfg) = undefined;  const h = reg.Handles(&bus);`
pub fn Handles(comptime b: anytype) type {
    const B = @typeInfo(@TypeOf(b)).pointer.child;
    const unit_bits = @bitSizeOf(B.Unit);
    return struct {
        fn check(comptime T: type) void {
            if (@bitSizeOf(T) % unit_bits != 0 or @bitSizeOf(T) > 64)
                @compileError(@typeName(T) ++ ": handle width must be a whole number of bus units, at most 64 bits");
        }

        pub fn Reg(comptime T: type, comptime addr: u32) type {
            comptime check(T);
            return struct {
                pub const address = addr;
                pub const Value = T;
                pub inline fn read() T {
                    return bus.fromRaw(T, b.read(addr, @bitSizeOf(T)));
                }
                pub inline fn write(v: T) void {
                    b.write(addr, @bitSizeOf(T), bus.toRaw(v));
                }
                /// Read-modify-write of named fields: `irq_control.modify(.{ .global_enable = true })`.
                pub inline fn modify(fields: anytype) void {
                    var v = read();
                    inline for (@typeInfo(@TypeOf(fields)).@"struct".field_names) |name| @field(v, name) = @field(fields, name);
                    write(v);
                }
            };
        }

        /// Wider than one bus access (e.g. BC5 u32): split into ascending-address accesses.
        /// If the original accesses the halves in another order, use two narrower handles.
        pub fn Shared(comptime T: type, comptime addr: u32) type {
            comptime check(T);
            return struct {
                pub const address = addr;
                pub const Value = T;
                pub inline fn load() T {
                    return bus.fromRaw(T, b.read(addr, @bitSizeOf(T)));
                }
                pub inline fn store(v: T) void {
                    b.write(addr, @bitSizeOf(T), bus.toRaw(v));
                }
            };
        }

        pub const Unclassified = Shared;
    };
}

// ---------------------------------------------------------------------------------------------
const testing = std.testing;
const Tape = @import("tape.zig").Tape;

const TI = struct {
    var data: [0x10000]u16 = @splat(0);
    var backing: [1]bus.Backing(u16) = undefined;
    var b: bus.Bus(bus.bc5) = undefined;
};
const h = Handles(&TI.b);
const IrqControl = packed struct(u16) { _b0: u1, global_enable: bool, _rest: u14 };
const irq_control = h.Reg(IrqControl, 0xFF95);
const clock_hi = h.Reg(u16, 0xFFB4);
const current_task = h.Shared(u16, 0xF0AB);
const tick_count = h.Shared(u32, 0xF0B0);
const unk_3c90 = h.Unclassified(i16, 0x3C90);

test "handles log through the bus in program order, interleaved with emulator accesses" {
    const map = [_]bus.Range{
        .{ .lo = 0xF0AB, .hi = 0xF0AB, .kind = .shared },
        .{ .lo = 0xF0B0, .hi = 0xF0B1, .kind = .shared },
        .{ .lo = 0xFF00, .hi = 0xFFDF, .kind = .mmio },
    };
    TI.backing = .{.{ .base = 0, .mem = &TI.data }};
    TI.b = try bus.Bus(bus.bc5).init(testing.allocator, &map, &TI.backing);
    defer TI.b.deinit();
    var t = try Tape.init(testing.allocator, &.{
        .{ .addr = 0xFF95, .value = 0x8001 },
        .{ .addr = 0xFFB4, .value = 0x0042 },
    });
    defer t.deinit(testing.allocator);
    TI.b.tape = &t;

    irq_control.modify(.{ .global_enable = true });
    current_task.store(3);
    TI.b.write(0xFF20, 16, 0x1); // as the emulator would
    tick_count.store(0x00010002);
    try testing.expectEqual(@as(u16, 0x42), clock_hi.read());
    try testing.expectEqual(@as(u32, 0x00010002), tick_count.load());
    unk_3c90.store(-1);
    try testing.expectEqual(@as(i16, -1), unk_3c90.load());

    try testing.expectEqual(@as(u16, 3), TI.data[0xF0AB]);
    try testing.expectEqual(@as(u16, 0x0001), TI.data[0xF0B0]); // high word first
    try testing.expectEqual(@as(u16, 0x0002), TI.data[0xF0B1]);
    const A = bus.Access;
    const want = [_]A{
        .{ .addr = 0xFF95, .bits = 16, .write = false, .value = 0x8001 },
        .{ .addr = 0xFF95, .bits = 16, .write = true, .value = 0x8003 },
        .{ .addr = 0xF0AB, .bits = 16, .write = true, .value = 3 },
        .{ .addr = 0xFF20, .bits = 16, .write = true, .value = 1 },
        .{ .addr = 0xF0B0, .bits = 16, .write = true, .value = 0x0001 },
        .{ .addr = 0xF0B1, .bits = 16, .write = true, .value = 0x0002 },
        .{ .addr = 0xFFB4, .bits = 16, .write = false, .value = 0x42 },
        .{ .addr = 0xF0B0, .bits = 16, .write = false, .value = 0x0001 },
        .{ .addr = 0xF0B1, .bits = 16, .write = false, .value = 0x0002 },
        .{ .addr = 0x3C90, .bits = 16, .write = true, .value = 0xFFFF },
        .{ .addr = 0x3C90, .bits = 16, .write = false, .value = 0xFFFF },
    };
    try testing.expectEqualSlices(A, &want, TI.b.log.items);
    try testing.expectEqual(@as(u32, 0xFF95), irq_control.address);
}
