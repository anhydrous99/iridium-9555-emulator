//! The Trx machine (ARCHITECTURE §3.2-3.4): guest arrays, the bus map, the CPU, and the two
//! configurations P1 (telephony, seg1 at 0x10000) and P2 (PTT, seg2 at 0x400000). One image per
//! process, so all of it is process-global. Flash holds both segments in either configuration
//! (both are in the real part's flash); P1 and P2 differ in entry, copies and BSS.
const std = @import("std");
const common = @import("common");
const sparc = @import("sparc");
const bus_mod = common.bus;
const cpu_mod = sparc.cpu;

pub const Bus = cpu_mod.Bus;

pub const Config = enum { p1, p2 };

pub const flash_base: u32 = 0x0001_0000;
pub const sdram_base: u32 = 0x4000_0000;
pub const onchip_base: u32 = 0x7000_0000;

/// Flash 0x10000-0x7FFFFF (the boot block 0x0-0xFFFF is not shipped), 0xFF where nothing is loaded.
pub var flash: [0x80_0000 - 0x1_0000]u8 align(4096) = undefined;
/// SDRAM: the BSS/data plus headroom up to 1 MiB. Above the image's BSS it is `unclassified` (backed,
/// so it behaves like RAM but every access is strict-logged). The real size is [open O4].
pub var sdram: [0x10_0000]u8 align(4096) = undefined;
/// On-chip RAM 0x70000000-0x7009FFFF.
pub var onchip: [0xA_0000]u8 align(4096) = undefined;

pub var regs: cpu_mod.Regs = .{};
pub var bus: Bus = undefined;
pub var cpu: cpu_mod.Cpu = undefined;
pub var config: Config = .p1;

pub var backing = [_]bus_mod.Backing(u8){
    .{ .base = flash_base, .mem = &flash },
    .{ .base = sdram_base, .mem = &sdram },
    .{ .base = onchip_base, .mem = &onchip },
};

/// LEON2 block (+0x04/+0x08 memory config, +0x24 configuration/NWINDOWS) and the custom APB
/// 0x80000100-0x800017FF (trx-arch §2); the PTT DSU at 0x90000000; the DSP windows.
fn map(comptime bss_end: u32) [9]bus_mod.Range {
    return .{
        .{ .lo = flash_base, .hi = 0x007F_FFFF, .kind = .rom },
        .{ .lo = sdram_base, .hi = bss_end - 1, .kind = .ram },
        .{ .lo = onchip_base, .hi = 0x7009_FFFF, .kind = .ram },
        .{ .lo = 0x8000_0000, .hi = 0x8000_17FF, .kind = .mmio },
        .{ .lo = 0x9000_0000, .hi = 0x9000_00FF, .kind = .mmio },
        .{ .lo = 0xA000_0000, .hi = 0xA000_FFFF, .kind = .mmio },
        .{ .lo = 0xB000_0000, .hi = 0xB000_7FFF, .kind = .mmio },
        .{ .lo = 0xC000_0000, .hi = 0xC000_3FFF, .kind = .mmio },
        .{ .lo = 0xD000_0000, .hi = 0xD000_1FFF, .kind = .mmio },
    };
}
const map_p1 = map(0x400C_3E20); // BSS end 0x400C3E20 (trx.lst 0x10358)
const map_p2 = map(0x400B_6D24); // BSS end 0x400B6D24 (crt0 0x400164)

/// A copy or clear done by crt0, as the materialized loader applies it (§3.4).
pub const Copy = struct { dst: u32, src: ?u32, len: u32 };

pub const Layout = struct {
    entry: u32,
    /// The first call after the copies: the cold boot stops here for the loader self-check.
    post_init: u32,
    /// The M2 "RTOS start": the scheduler's hand-off to the first task, i.e. the `ta 3` (flush
    /// windows, then load the task context from %g6) of TCT_Schedule's two context-restore routines
    /// (interrupt frame, solicited frame). ARCHITECTURE's 0x700860BC / 0x7000EDC8 is the
    /// interrupt-disable stub init calls first (NOTES §3.2), 3 instructions after crt0.
    rtos_start: [2]u32,
    copies: []const Copy,
    /// Flash range whose bytes are the RAM image (ledger class `shadow`).
    shadow: Copy,
};

pub fn layout(c: Config) Layout {
    return switch (c) {
        .p1 => .{
            .entry = 0x0001_0000,
            .post_init = 0x0001_186C,
            // TCT_Schedule 0x11F54 -> 0x10140 (0x11FFC) or 0x1039C (0x1200C, crt0's tail)
            .rtos_start = .{ 0x0001_014C, 0x0001_03A8 },
            .copies = &.{
                .{ .dst = 0x4000_0000, .src = null, .len = 0xC_3E20 },
                .{ .dst = 0x7000_0078, .src = 0x001E_921C, .len = 0x8_7544 },
            },
            .shadow = .{ .dst = 0x7000_0078, .src = 0x001E_921C, .len = 0x8_7544 },
        },
        .p2 => .{
            .entry = 0x0040_0000,
            .post_init = 0x0040_1810,
            // init 0x401810 -> INC_Initialize 0x401DB0 -> TCT_Schedule 0x7000F804 -> 0x7000EFCC
            // (0x7000F8F4) or 0x700102D4 (0x7000F904)
            .rtos_start = .{ 0x7000_EFD8, 0x7001_02E0 },
            .copies = &.{
                .{ .dst = 0x7003_9348, .src = null, .len = 0x7007_AF40 - 0x7003_9348 },
                .{ .dst = 0x4000_08E8, .src = null, .len = 0x400B_6D24 - 0x4000_08E8 },
                .{ .dst = 0x7000_0038, .src = 0x0046_E000, .len = 0x3_9310 },
                .{ .dst = 0x4000_0000, .src = 0x004A_7310, .len = 0x8E8 },
            },
            .shadow = .{ .dst = 0x7000_0038, .src = 0x0046_E000, .len = 0x3_9310 },
        },
    };
}

/// Host bytes of guest `[addr, addr+len)` in one array, or null.
pub fn bytes(addr: u32, len: u32) ?[]u8 {
    for (&backing) |b| {
        if (addr >= b.base and addr - b.base <= b.mem.len and b.mem.len - (addr - b.base) >= len)
            return b.mem[addr - b.base ..][0..len];
    }
    return null;
}

/// Loads both segments into flash from `dir` (firmware/ is read-only; nothing is written there).
pub fn loadFirmware(io: std.Io, dir: []const u8) !void {
    @memset(&flash, 0xFF);
    var d = try std.Io.Dir.cwd().openDir(io, dir, .{});
    defer d.close(io);
    const s1 = try d.readFile(io, "trx_seg1_0x10000.bin", flash[0..0x26_0760]);
    const s2 = try d.readFile(io, "trx_seg2.bin", flash[0x40_0000 - flash_base ..][0..0xA_7BF8]);
    if (s1.len != 0x26_0760 or s2.len != 0xA_7BF8) return error.BadFirmwareSize;
}

/// Bus over the arrays for configuration `c`; RAM zeroed, CPU at the reset vector (S=1, ET=0).
pub fn reset(gpa: std.mem.Allocator, c: Config, nwin: u32) !void {
    if (nwin < 2 or nwin > cpu_mod.max_windows) return error.BadNwin; // V8: NWINDOWS 2..32
    config = c;
    @memset(&sdram, 0);
    @memset(&onchip, 0);
    bus = try Bus.init(gpa, if (c == .p1) &map_p1 else &map_p2, &backing);
    const e = layout(c).entry;
    regs = .{ .pc = e, .npc = e + 4, .nwin = nwin };
    cpu = .{ .r = &regs, .bus = &bus };
}

pub fn deinit() void {
    cpu.deinit();
    bus.deinit();
}

/// Applies crt0's copies and clears directly (the materialized start).
pub fn materialize(c: Config) void {
    for (layout(c).copies) |cp| {
        const dst = bytes(cp.dst, cp.len).?;
        if (cp.src) |s| @memcpy(dst, bytes(s, cp.len).?) else @memset(dst, 0);
    }
}

/// Every writable part (E3 compares the memory parts).
pub fn parts() [3]common.snapshot.Part {
    return .{
        .memory("sdram", sdram_base, u8, &sdram),
        .memory("onchip", onchip_base, u8, &onchip),
        .state("cpu", &regs),
    };
}
