const std = @import("std");

pub fn build(b: *std.Build) void {
    const target = b.standardTargetOptions(.{});
    const requested = b.standardOptimizeOption(.{});
    const optimize = if (requested == .debug) .safe else requested;
    const common = module(b, "native/vendor/common/root.zig", target, optimize, &.{});
    const c: std.Build.Module.Import = .{ .name = "common", .module = common };
    const xap = module(b, "native/vendor/emu/xap2/root.zig", target, optimize, &.{c});
    const avr = module(b, "native/vendor/emu/avr/root.zig", target, optimize, &.{c});
    const sparc = module(b, "native/vendor/emu/sparc/root.zig", target, optimize, &.{c});
    const bc5 = module(b, "native/vendor/soc/bc5/soc.zig", target, optimize, &.{ c, .{ .name = "xap2", .module = xap } });
    const avr_soc = module(b, "native/vendor/soc/avr/root.zig", target, optimize, &.{ c, .{ .name = "emu_avr", .module = avr } });
    const trx = module(b, "native/vendor/soc/trx/root.zig", target, optimize, &.{ c, .{ .name = "sparc", .module = sparc } });
    const app = module(b, "native/main.zig", target, optimize, &.{
        c,
        .{ .name = "xap2", .module = xap },
        .{ .name = "emu_avr", .module = avr },
        .{ .name = "sparc", .module = sparc },
        .{ .name = "bc5", .module = bc5 },
        .{ .name = "avr_soc", .module = avr_soc },
        .{ .name = "trx", .module = trx },
    });
    const exe = b.addExecutable(.{ .name = "iridium-core", .root_module = app });
    b.installArtifact(exe);
    const tests = b.step("test", "CPU, bus, peripheral and protocol unit tests (no original firmware needed)");
    for ([_]*std.Build.Module{ common, xap, avr, sparc, bc5, avr_soc, trx, app }) |m| {
        tests.dependOn(&b.addRunArtifact(b.addTest(.{ .root_module = m })).step);
    }
}

fn module(b: *std.Build, path: []const u8, target: std.Build.ResolvedTarget, optimize: std.builtin.OptimizeMode, imports: []const std.Build.Module.Import) *std.Build.Module {
    return b.createModule(.{ .root_source_file = b.path(path), .target = target, .optimize = optimize, .link_libc = true, .imports = imports });
}
