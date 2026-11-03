//! Device stubs of the Trx ASIC for system runs (ARCHITECTURE §7.4 tier `model`; register map from
//! trx-arch §2). Function tests do not use them: there the bus serves `mmio` reads from the vector's
//! tape. Every register is a 32-bit latch (writes stored, reads return the last value, big-endian
//! byte lanes), except the ones whose behaviour is evidenced:
//!   0x80000024  LEON2 configuration: NWINDOWS-1 in bits 24:20 (reset code 0x10080-0x1008C)
//!   0x80000920  timer unit free-running count, counting DOWN: -1 per read. The busy-wait 0x7004A744
//!               (P2 0x70010AF4) spins while `now > start - (7us+5)/10`, and the scheduler's task
//!               accounting adds the count at switch-in (0x12050) and subtracts it at switch-out (0x12018)
//!   0x80000A10  TDMA counter, modulo 63000 (0x2A01C): +1 per read
//!   0x80000524, 0x80000624  serial controllers' status: bit 9 (ready) always set [A9 mod H]
//!   0xA/0xB/0xC/0xD0000000 DSP windows: memory (the DSP loader verifies by read-back)
//! Everything else in the custom APB (IRQ config 0x100, UARTs 0x200/0x300/0x1600/0x1700, clock
//! 0x700, wake 0x800, watchdog 0x900, 0xB00, HPI 0xC00/0xD00, L1 sequencer 0x1000, status 0x1300,
//! 0x1400, 0x1500) and the PTT DSU 0x90000000 is a latch that reads 0 until written.
//! `Flash` is the flash command interface the RAM routines reach through ASI 1.
// shortcut: latches only; status/polled registers get evidenced models (or learned tape defaults) when a scenario needs them.
const std = @import("std");
const common = @import("common");
const sparc = @import("sparc");

pub const Model = struct {
    gpa: std.mem.Allocator,
    nwin: u32,
    latch: std.AutoHashMapUnmanaged(u32, u32) = .empty,
    ticks: u32 = 0,
    tdma: u32 = 0,
    reads: u64 = 0,
    writes: u64 = 0,

    pub fn deinit(m: *Model) void {
        m.latch.deinit(m.gpa);
    }

    pub fn device(m: *Model) common.bus.Device {
        return .{ .ctx = m, .read = read, .write = write };
    }

    fn word(m: *Model, a: u32) u32 {
        return switch (a) {
            0x8000_0024 => (m.nwin - 1) << 20,
            0x8000_0920 => blk: {
                m.ticks -%= 1;
                break :blk m.ticks;
            },
            0x8000_0A10 => blk: {
                m.tdma = (m.tdma + 1) % 63000;
                break :blk m.tdma;
            },
            // [A9 mod H] serial controllers (pointer table 0x1088A8): 0x297B8.. write +0x30, spin on
            // +0x24 bit 9, read +0x34. Ready is always set, so the transfer completes at once.
            0x8000_0524, 0x8000_0624 => (m.latch.get(a) orelse 0) | 0x200,
            else => m.latch.get(a) orelse 0,
        };
    }

    fn read(ctx: *anyopaque, addr: u32, bits: u8) u64 {
        const m: *Model = @ptrCast(@alignCast(ctx));
        m.reads += 1;
        const sh = lane(addr, bits);
        return (m.word(addr & ~@as(u32, 3)) >> sh) & mask(bits);
    }

    fn write(ctx: *anyopaque, addr: u32, bits: u8, value: u64) void {
        const m: *Model = @ptrCast(@alignCast(ctx));
        m.writes += 1;
        const a = addr & ~@as(u32, 3);
        const sh = lane(addr, bits);
        const old = m.latch.get(a) orelse 0;
        const v = (old & ~(mask(bits) << sh)) | (@as(u32, @truncate(value)) & mask(bits)) << sh;
        m.latch.put(m.gpa, a, v) catch @panic("devices: out of memory");
    }
};

/// AMD-command-set 16-bit flash as the RAM routines drive it through ASI 1 (trx-arch §2; P1 CFI query
/// 0x700870BC, program 0x70087240, sector erase/resume 0x700872EC, autoselect 0x70087464; PTT
/// 0x7001457C-0x70014AEC). Unlock AA@0xAAA, 55@0x554; F0 = read array; 98@0xAA = CFI query;
/// unlock+A0 = program (bits only clear); unlock+80, unlock+30@sector = sector erase (10@0xAAA =
/// chip erase); unlock+90 = autoselect. Program and erase finish at once: status reads return the
/// array, so the DQ7 polls end on their first read. Bytes 0-0xFFFF (boot block, not shipped) read
/// 0xFF and ignore programming. Accesses at or above 8 MB go to the bus.
/// [A9 mod H]: the CFI timing/voltage bytes and the ids (an Am29LV640-like 8 MB top-boot part). The
/// sector map is evidenced: upgrade tool sector_size_8MB 0x4072D0 = 127 × 64 KB, then 8 × 8 KB.
pub const Flash = struct {
    /// Flash bytes from `base` (machine.flash).
    mem: []u8,
    base: u32,
    bus: *sparc.cpu.Bus,
    mode: enum { array, cfi, ids } = .array,
    /// Unlock cycles seen (0-2), and what the next cycle completes.
    cycle: u2 = 0,
    erase_armed: bool = false,
    program_next: bool = false,

    pub const size: u32 = 0x80_0000;
    const top_boot: u32 = 0x7F_0000;
    /// CFI words 0x10-0x34.
    const cfi = [_]u8{
        'Q', 'R', 'Y', 0x02, 0x00, 0x40, 0x00, 0x00, 0x00, 0x00, 0x00, 0x27, 0x36, 0x00, 0x00, 0x04, // 0x10
        0x00, 0x0A, 0x00, 0x05, 0x00, 0x04, 0x00, 0x17, 0x02, 0x00, 0x00, 0x00, 0x02, // 0x20: 8 MB, 2 regions
        0x7E, 0x00, 0x00, 0x01, // 127 × 64 KB
        0x07, 0x00, 0x20, 0x00, // 8 × 8 KB
    };

    pub fn device(f: *Flash) common.bus.Device {
        return .{ .ctx = f, .read = read, .write = write };
    }

    fn byteAt(f: *const Flash, a: u32) u8 {
        const w = a >> 1; // x16 data word; its high byte is 0 in the query modes
        return switch (f.mode) {
            .array => if (a >= f.base) f.mem[a - f.base] else 0xFF,
            .cfi => if (a & 1 == 0 or w < 0x10 or w - 0x10 >= cfi.len) 0 else cfi[w - 0x10],
            .ids => if (a & 1 == 0) (if (w == 1) 0x22 else 0) else switch (w) {
                0 => 0x01, // AMD
                1 => 0x7E,
                else => 0,
            },
        };
    }

    fn read(ctx: *anyopaque, addr: u32, bits: u8) u64 {
        const f: *Flash = @ptrCast(@alignCast(ctx));
        if (addr >= size) return f.bus.read(addr, bits);
        var v: u64 = 0;
        for (0..bits / 8) |k| v = v << 8 | f.byteAt(addr + @as(u32, @intCast(k)));
        return v;
    }

    fn write(ctx: *anyopaque, addr: u32, bits: u8, value: u64) void {
        const f: *Flash = @ptrCast(@alignCast(ctx));
        if (addr >= size) return f.bus.write(addr, bits, value);
        const d: u8 = @truncate(value);
        const at = addr & 0xFFF;
        if (f.program_next) {
            f.program_next = false;
            for (0..bits / 8) |k| {
                const a = addr + @as(u32, @intCast(k));
                if (a >= f.base) f.mem[a - f.base] &= @truncate(value >> @intCast(8 * (bits / 8 - 1 - k)));
            }
            return;
        }
        if (d == 0xF0) {
            f.* = .{ .mem = f.mem, .base = f.base, .bus = f.bus };
            return;
        }
        if (d == 0x98 and at == 0xAA) {
            f.mode = .cfi;
            return;
        }
        switch (f.cycle) {
            0 => f.cycle = if (d == 0xAA and at == 0xAAA) 1 else 0, // anything else (30 resume, B0 suspend) is a no-op
            1 => f.cycle = if (d == 0x55 and at == 0x554) 2 else 0,
            else => {
                f.cycle = 0;
                if (f.erase_armed) {
                    f.erase_armed = false;
                    if (d == 0x30) f.erase(addr & ~(sector(addr) - 1), sector(addr));
                    if (d == 0x10 and at == 0xAAA) f.erase(0, size);
                } else if (at == 0xAAA) switch (d) {
                    0xA0 => f.program_next = true,
                    0x80 => f.erase_armed = true,
                    0x90 => f.mode = .ids,
                    else => {},
                };
            },
        }
    }

    fn sector(addr: u32) u32 {
        return if (addr >= top_boot) 0x2000 else 0x1_0000;
    }

    fn erase(f: *Flash, lo: u32, len: u32) void {
        const a = @max(lo, f.base);
        if (lo + len > a) @memset(f.mem[a - f.base ..][0 .. lo + len - a], 0xFF);
    }
};

test "flash: CFI query, program clears bits, sector erase, autoselect, reset" {
    const S = struct {
        var mem: [Flash.size - 0x1_0000]u8 = undefined;
    };
    const mem = &S.mem;
    @memset(mem, 0xFF);
    var f: Flash = .{ .mem = mem, .base = 0x1_0000, .bus = undefined };
    const d = f.device();
    const t = std.testing;
    d.write(d.ctx, 0, 16, 0xF0);
    d.write(d.ctx, 0xAA, 16, 0x98);
    try t.expectEqual(@as(u64, 'Q'), d.read(d.ctx, 0x20, 16));
    try t.expectEqual(@as(u64, 'Y'), d.read(d.ctx, 0x24, 16));
    try t.expectEqual(@as(u64, 0x17), d.read(d.ctx, 0x4E, 16)); // word 0x27: 2^23 bytes
    try t.expectEqual(@as(u64, 0x7E), d.read(d.ctx, 0x5A, 16)); // region 1: 127 sectors
    d.write(d.ctx, 0, 16, 0xF0);
    try t.expectEqual(@as(u64, 0xFFFF), d.read(d.ctx, 0x2_0000, 16));
    for ([_]u32{ 0xAA, 0x55, 0xA0 }, [_]u32{ 0xAAA, 0x554, 0xAAA }) |v, a| d.write(d.ctx, a, 16, v);
    d.write(d.ctx, 0x2_0002, 16, 0x12F0);
    try t.expectEqual(@as(u64, 0x12F0), d.read(d.ctx, 0x2_0002, 16));
    for ([_]u32{ 0xAA, 0x55, 0xA0 }, [_]u32{ 0xAAA, 0x554, 0xAAA }) |v, a| d.write(d.ctx, a, 16, v);
    d.write(d.ctx, 0x2_0002, 16, 0xFF0F); // programming only clears bits
    try t.expectEqual(@as(u64, 0x1200), d.read(d.ctx, 0x2_0002, 16));
    for ([_]u32{ 0xAA, 0x55, 0x80, 0xAA, 0x55 }, [_]u32{ 0xAAA, 0x554, 0xAAA, 0xAAA, 0x554 }) |v, a| d.write(d.ctx, a, 16, v);
    d.write(d.ctx, 0x2_8000, 16, 0x30); // anywhere in the 64 KB sector 0x20000
    try t.expectEqual(@as(u64, 0xFFFF), d.read(d.ctx, 0x2_0002, 16));
    mem[0x7F_2000 - 0x1_0000] = 0;
    mem[0x7F_4000 - 0x1_0000] = 0;
    for ([_]u32{ 0xAA, 0x55, 0x80, 0xAA, 0x55 }, [_]u32{ 0xAAA, 0x554, 0xAAA, 0xAAA, 0x554 }) |v, a| d.write(d.ctx, a, 16, v);
    d.write(d.ctx, 0x7F_2000, 16, 0x30); // 8 KB boot sector: the next one is untouched
    try t.expectEqual(@as(u8, 0xFF), mem[0x7F_2000 - 0x1_0000]);
    try t.expectEqual(@as(u8, 0), mem[0x7F_4000 - 0x1_0000]);
    for ([_]u32{ 0xAA, 0x55, 0x90 }, [_]u32{ 0xAAA, 0x554, 0xAAA }) |v, a| d.write(d.ctx, a, 16, v);
    try t.expectEqual(@as(u64, 0x0001), d.read(d.ctx, 0, 16));
    d.write(d.ctx, 0, 16, 0xF0);
    try t.expectEqual(@as(u64, 0xFFFF), d.read(d.ctx, 0, 16)); // boot block: not shipped
}

/// Shift of a `bits`-wide access at `addr` inside its big-endian 32-bit word.
fn lane(addr: u32, bits: u8) u5 {
    return @intCast((4 - bits / 8 - (addr & 3)) * 8);
}

fn mask(bits: u8) u32 {
    return if (bits >= 32) 0xFFFF_FFFF else (@as(u32, 1) << @intCast(bits)) - 1;
}

test "latches keep big-endian byte lanes; config reports NWINDOWS" {
    var m: Model = .{ .gpa = std.testing.allocator, .nwin = 8 };
    defer m.deinit();
    const d = m.device();
    d.write(d.ctx, 0x8000_0704, 32, 0x1122_3344);
    d.write(d.ctx, 0x8000_0705, 8, 0xAA);
    try std.testing.expectEqual(@as(u64, 0x11AA_3344), d.read(d.ctx, 0x8000_0704, 32));
    try std.testing.expectEqual(@as(u64, 0x3344), d.read(d.ctx, 0x8000_0706, 16));
    try std.testing.expectEqual(@as(u64, 7 << 20), d.read(d.ctx, 0x8000_0024, 32));
    try std.testing.expect(d.read(d.ctx, 0x8000_0920, 32) != d.read(d.ctx, 0x8000_0920, 32));
}
