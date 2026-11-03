//! Flat machine for snippets and unit tests: 64 Ki data words of plain RAM, the register-alias words
//! 0xFFE0–0xFFE4 routed to the CPU (device decides per `alias_regs`), and caller-supplied code
//! segments. No ROM, MMIO or tapes: what the independent Python reference models too (README.md).
const std = @import("std");
const common = @import("common");
const cpu_mod = @import("cpu.zig");
const bus_mod = common.bus;

pub const map = [_]bus_mod.Range{
    .{ .lo = 0x0000, .hi = 0xFFDF, .kind = .ram },
    .{ .lo = 0xFFE0, .hi = 0xFFE4, .kind = .cpu_alias },
    .{ .lo = 0xFFE5, .hi = 0xFFFF, .kind = .ram },
};

pub const Flat = struct {
    data: [0x10000]u16 = @splat(0),
    backing: [1]bus_mod.Backing(u16) = undefined,
    bus: cpu_mod.Bus = undefined,
    core: cpu_mod.Core = undefined,

    /// `f` must not move afterwards (the bus and core point into it).
    pub fn init(f: *Flat, gpa: std.mem.Allocator, code: []const cpu_mod.Segment, alias_regs: bool) !void {
        f.data = @splat(0);
        f.backing = .{.{ .base = 0, .mem = &f.data }};
        f.bus = try cpu_mod.Bus.init(gpa, &map, &f.backing);
        f.core = .{ .bus = &f.bus, .code = code, .alias_regs = alias_regs };
        f.bus.cpu = f.core.aliasDevice();
    }

    pub fn deinit(f: *Flat) void {
        f.bus.deinit();
    }
};
