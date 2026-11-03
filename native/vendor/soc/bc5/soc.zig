//! BC5 SoC binding (ARCHITECTURE §3.3, §3.4, §7.4): data-space map, device stubs, image loading, cold
//! reset, the `rt.original` ABI binding, and run-from-snapshot for the harness.
//! `Soc(M)` binds to the image's guest arrays: `M` declares `pub var data: [0x10000]u16` and
//! `pub var bus: Bus(bc5)` (fw/bc5/mem.zig has exactly these; tests use their own).
//! One image per process (§0.3): everything here is process-global.
const std = @import("std");
const common = @import("common");
const xap2 = @import("xap2");
const bus_mod = common.bus;
const mem16 = common.mem16;
const snapshot = common.snapshot;
const cpu_mod = xap2.cpu;
pub const flash_mod = @import("flash.zig");
const Range = bus_mod.Range;

pub const Bus = cpu_mod.Bus;

/// One firmware image (main or loader) as the SoC loads it.
pub const Image = struct {
    name: []const u8,
    /// Project-relative path (`firmware/` is read-only).
    file: []const u8,
    image: common.vector.Image,
    /// Image word of data address 0 (data a = image word base + a inside the window).
    window_base: u32,
    /// First data address after the flash window (the window starts at 0x0100; 0x0000–0x00FF is the
    /// low register page).
    window_end: u16,
    /// Code range in image words; a fetch outside it is a fault (no execution of non-code bytes).
    code_words: u32,
    /// Register aliases 0xFFE0/E1/E3/E4 (bc5-isa §5, §7).
    alias_regs: bool,
    /// `boot.toIdle` points (registry byte addresses): each arrival at `idle_point` is one pass;
    /// arriving at `panic_entry` ends the run as a panic.
    idle_point: u32,
    panic_entry: ?u32,
    /// Byte ledger (project-relative) for the boot's non-code fetch check.
    ledger: []const u8,
};

/// bc5_main.bin: window at byte 0x3096BE (NOTES §1.4), code 0x000000–0x0DC044 (bc5-coverage §0).
pub const main_image: Image = .{
    .name = "bc5_main",
    .file = "firmware/bc5_main.bin",
    .image = .bc5,
    .window_base = mem16.main_window_base,
    .window_end = mem16.window_end,
    .code_words = 0x0DC044 / 2,
    .alias_regs = true,
    .idle_point = 0xB774, // bsr 0xb18 (sleep) in the scheduler's no-task path
    .panic_entry = 0x70A0,
    .ledger = "zig/manifest/bc5/bytes.tsv",
};

/// Data-space classes (ARCHITECTURE §3.3; the low-page register words are the `mmio` rows of
/// manifest/bc5/io.tsv). Gaps are `unclassified` (strict: logged, compared).
pub fn map(window_end: u16) [16]Range {
    return .{
        .{ .lo = 0x0001, .hi = 0x0035, .kind = .mmio }, // radio config block
        .{ .lo = 0x003F, .hi = 0x004C, .kind = .mmio }, // HW timers
        .{ .lo = 0x0064, .hi = 0x0069, .kind = .mmio }, // IRQ control
        .{ .lo = 0x006E, .hi = 0x0071, .kind = .mmio }, // MMU page-list selectors
        .{ .lo = 0x0073, .hi = 0x0074, .kind = .mmio }, // flash page / bank
        .{ .lo = 0x0076, .hi = 0x0078, .kind = .mmio }, // watchdog / reset
        .{ .lo = mem16.window_lo, .hi = window_end - 1, .kind = .rom }, // flash constant window
        .{ .lo = 0x4000, .hi = 0x7FFF, .kind = .mmio }, // MMU buffer windows
        .{ .lo = 0x8000, .hi = 0x8FFF, .kind = .mmio }, // flash page window (page = reg 0x0073)
        .{ .lo = 0xA000, .hi = 0xFD04, .kind = .ram }, // RAM, pool, globals + stack, crash record
        .{ .lo = 0xFD05, .hi = 0xFD05, .kind = .mmio }, // MMU indirect physical-page access
        .{ .lo = 0xFD06, .hi = 0xFDFF, .kind = .ram },
        .{ .lo = 0xFF00, .hi = 0xFFDF, .kind = .mmio }, // I/O
        .{ .lo = 0xFFE0, .hi = 0xFFE4, .kind = .cpu_alias }, // AH AL - X Y (device decides per image)
        .{ .lo = 0xFFE5, .hi = 0xFFEF, .kind = .unclassified },
        .{ .lo = 0xFFF0, .hi = 0xFFFF, .kind = .scratch }, // compiler scratch
    };
}

/// Device-stub state for system runs: one latch per register word (a read returns the last value
/// written) plus the modelled registers below. Plain data, so it is a snapshot part.
pub const Devices = extern struct {
    low: [0x100]u16 = @splat(0),
    io: [0x100]u16 = @splat(0),
};

/// Program addresses 0x540000 + k execute data RAM word 0xA000 + k (XA-ram-code, a hardware mapping
/// inferred from firmware): 0x64A4 copies code from flash into a RAM block and returns its far pointer
/// as `0x54:(ram - 0xA000)` (0x654A-0x6554), which 0x16C3E then calls (`bsr @(0x21,Y)`); e.g.
/// descriptor 0xA3A = the flash driver fn_01a7da.
pub const ram_code_base: u32 = 0x540000;
pub const ram_code_data: u16 = 0xA000;

/// Stub values for read-only registers that boot polls (system runs only; tests tape them):
/// 0xFFB9 is waited on until non-zero by 0x131C/0x67B2 and then used like the 0xFA0 (4000) that the
/// other branch at 0x130A stores, so the stub answers 4000.
pub const ro_defaults = [_][2]u16{
    .{ 0xFFB9, 0x0FA0 },
};

/// Chip id the init sequence checks (`reg 0xFF7D < 0x5011 → panic 0x48`, bc5-arch §3).
pub const chip_id: u16 = 0x5011;
/// µs clock 0xFFB4:0xFFB5 in system runs: one tick per 8 instructions (deterministic).
pub const clock_shift = 3;

pub fn Soc(comptime M: type) type {
    return struct {
        pub var core: cpu_mod.Core = undefined;
        pub var dev: Devices = .{};
        pub var image: Image = main_image;
        pub var words: []u16 = &.{};
        /// Physical flash behind the page window (system runs); the image sits at the
        /// XA-flash-bank offset. Not a snapshot part: function tests tape the window.
        pub var flash: flash_mod.Flash = .{};
        /// Offset the image was laid at in `flash` (re-laid when the selection changes).
        pub var laid_at: u32 = 0;
        var segs: [2]cpu_mod.Segment = undefined;
        var ranges: [16]Range = undefined;
        var backing: [1]bus_mod.Backing(u16) = undefined;
        /// Return width the harness compares (E2) for `runFunc`; the generated bridges return AH:AL.
        pub var ret_bits: u16 = 32;

        /// Loads `img` from `root` (the project directory), binds bus, CPU, aliases and `rt.original`.
        pub fn init(gpa: std.mem.Allocator, io: std.Io, root: std.Io.Dir, img: Image) !void {
            const bytes = try root.readFileAlloc(io, img.file, gpa, .limited(8 << 20));
            defer gpa.free(bytes);
            if (bytes.len % 2 != 0 or img.code_words > bytes.len / 2 or img.window_base + img.window_end > bytes.len / 2) return error.ImageTooShort;
            words = try gpa.alloc(u16, bytes.len / 2);
            errdefer gpa.free(words);
            flash.words = try gpa.alloc(u16, flash_mod.size_words);
            errdefer gpa.free(flash.words);
            mem16.loadWords(words, bytes[0 .. words.len * 2]);
            image = img;
            segs = .{
                .{ .base = cpu_mod.image_base, .words = words[0..img.code_words] },
                .{ .base = ram_code_base, .words = M.data[ram_code_data..], .gate = .ram_code }, // live view of RAM
            };
            ranges = map(img.window_end);
            backing = .{.{ .base = 0, .mem = &M.data }};
            M.bus = try Bus.init(gpa, &ranges, &backing);
            core = .{ .bus = &M.bus, .code = &segs, .alias_regs = img.alias_regs };
            M.bus.cpu = core.aliasDevice();
            common.rt.original = original;
            reset();
        }

        pub fn deinit(gpa: std.mem.Allocator) void {
            M.bus.deinit();
            gpa.free(words);
            gpa.free(flash.words);
            words = &.{};
            flash = .{};
            common.rt.original = null;
        }

        /// Fresh experiment: restore the input image and erase all subsequent flash changes.
        pub fn reset() void {
            layFlash(flashOffset());
            @memset(&M.data, 0);
            warmReset();
        }

        /// Watchdog-style reboot: CPU/device state resets, RAM and programmed flash survive.
        /// Original reset code validates retained PS records at FCE0..FCEE before clearing RAM.
        /// This is an explicit host action until watchdog timing is established; it does not infer a reset
        /// merely because firmware enables the watchdog or writes its kick register.
        pub fn warmReset() void {
            const source = laid_at + image.window_base + mem16.window_lo;
            @memcpy(M.data[mem16.window_lo..image.window_end], flash.words[source..][0 .. image.window_end - mem16.window_lo]);
            segs[0].words = flash.words[laid_at..][0..image.code_words];
            dev = .{};
            const sel = core.sel;
            flash.state = .read;
            core = .{ .bus = &M.bus, .code = &segs, .alias_regs = image.alias_regs, .sel = sel };
            core.cpu.pc = cpu_mod.image_base;
            M.bus.resetRun(std.math.maxInt(u64));
        }

        /// Erased flash with the image at physical word `at`.
        fn layFlash(at: u32) void {
            @memset(flash.words, 0xFFFF);
            const n = @min(words.len, flash.words.len - at);
            @memcpy(flash.words[at..][0..n], words[0..n]);
            flash.state = .read;
            laid_at = at;
        }

        /// System runs serve MMIO from the device stubs; function tests from a tape (`bus.tape`).
        pub fn systemMode(on: bool) void {
            M.bus.dev = if (on) .{ .ctx = &dev, .read = devRead, .write = devWrite } else null;
        }

        /// Every writable part (E3 compares `data`; the window is in it, §3.2).
        var parts: [3]snapshot.Part = undefined;
        pub fn machine() snapshot.Machine {
            parts = .{ .memory("data", 0, u16, &M.data), .state("cpu", &core.cpu), .state("dev", &dev) };
            return .{ .parts = &parts };
        }

        /// Vector register file (`std.mem.asBytes(&Cpu)`) into the CPU.
        pub fn loadRegs(regs: []const u8) error{BadRegs}!void {
            if (regs.len != @sizeOf(cpu_mod.Cpu)) return error.BadRegs;
            @memcpy(std.mem.asBytes(&core.cpu), regs);
        }

        pub const Result = struct { halt: cpu_mod.Halt, ret: u64 = 0 };

        /// Runs original `func` (registry byte address) from the current CPU state until it returns
        /// to the sentinel or halts. `ret` is AL, or AH:AL for `ret_bits` 32.
        pub fn runFunc(func: u32) Result {
            core.cpu.pc = cpu_mod.progAddr(func);
            core.cpu.x = @truncate(cpu_mod.sentinel);
            core.cpu.xh = @truncate(cpu_mod.sentinel >> 16);
            core.depth = 0;
            const h = core.run(std.math.maxInt(u64));
            return .{ .halt = h, .ret = retValue(ret_bits) };
        }

        fn retValue(bits: u16) u64 {
            const v = @as(u64, core.cpu.ah) << 16 | core.cpu.al;
            return if (bits >= 32) v else v & ((@as(u64, 1) << @intCast(bits)) - 1);
        }

        /// `rt.original`: Zig wrappers reach an emulated original through this (§5.1). ABI words
        /// (ints up to 16 bits = one word, wider = high word first) go to AL, AH, then @(0,Y)… (§5.3).
        // shortcut: a 32-bit first argument also follows that flat order (AL = high word) [unk]; settle it with measured signatures.
        pub fn original(target: u32, args: []const common.hooks.Arg, ret_bits_: u16) u64 {
            var w: [common.rt.max_args * 4]u16 = undefined;
            var n: usize = 0;
            for (args) |a| {
                const k: usize = @max(1, (a.bits + 15) / 16);
                for (0..k) |j| {
                    w[n] = @truncate(a.value >> @intCast(16 * (k - 1 - j)));
                    n += 1;
                }
            }
            if (n > 0) core.cpu.al = w[0];
            if (n > 1) core.cpu.ah = w[1];
            for (w[@min(n, 2)..n], 0..) |v, k| core.write(core.cpu.y +% @as(u16, @intCast(k)), v);
            const r = runFunc(target);
            switch (r.halt) {
                .returned => {},
                // In the fork server these end the run through bus.on_stop (E1).
                // shortcut: a brk/illegal trap inside a callee is reported as fault(pc); bus.Stop has no trap kind.
                .trap, .fault => M.bus.halt(.{ .fault = core.cpu.pc }),
                .fuel_exhausted, .tape_exhausted, .steps, .sleep => {},
            }
            if (M.bus.stop == null and r.halt != .returned) std.debug.panic("bc5: original 0x{x} stopped ({t}) under a Zig caller", .{ target, r.halt });
            return retValue(ret_bits_);
        }

        // -------------------------------------------------------------------------------------
        // Device stubs (system runs).

        fn devRead(ctx: *anyopaque, addr: u32, bits: u8) u64 {
            _ = .{ ctx, bits };
            const a: u16 = @intCast(addr);
            if (a >= 0x8000 and a < 0x9000) return flash.read(physical(a));
            if (a < 0x100) return dev.low[a];
            return switch (a) {
                0xFFB4 => @truncate((core.steps >> clock_shift) >> 16),
                0xFFB5 => @truncate(core.steps >> clock_shift),
                0xFF7D => chip_id,
                // Read-only inputs the init sequence polls (stub values, see `ro_defaults`).
                else => if (roDefault(a)) |v| v else if (a >= 0xFF00) dev.io[a - 0xFF00] else 0,
            };
        }

        fn roDefault(a: u16) ?u16 {
            for (ro_defaults) |d| if (d[0] == a) return d[1];
            return null;
        }

        fn devWrite(ctx: *anyopaque, addr: u32, bits: u8, value: u64) void {
            _ = .{ ctx, bits };
            const a: u16 = @intCast(addr);
            if (a >= 0x8000 and a < 0x9000) return flash.write(physical(a), @truncate(value));
            if (a < 0x100) dev.low[a] = @truncate(value) else if (a >= 0xFF00) dev.io[a - 0xFF00] = @truncate(value);
        }

        /// Data 0x8000–0x8FFF: physical flash word `page * 0x1000 + off` (page = reg 0x0073).
        fn physical(a: u16) u32 {
            core.touched.set(.flash_bank);
            // Variant re-runs (§7.6) and `bc5 boot --variant` set `core.sel` without a reset.
            if (laid_at != flashOffset()) layFlash(flashOffset());
            return @as(u32, dev.low[0x73]) * 0x1000 + (a - 0x8000);
        }

        /// Physical flash word of image word 0 (XA-flash-bank): 0x1800C = program address + 0x10000,
        /// as fs reads (0x6DB86) and the page-base table at window 0x34C (= 0x10 pages) assume.
        pub fn flashOffset() u32 {
            return if (core.sel.has(.flash_bank)) 0x800C else 0x1800C;
        }
    };
}

/// The project directory (holds `firmware/`): `explicit` (e.g. $FW_ROOT) if given, else the cwd or
/// one of its parents (tests and tools run from zig/ or deeper).
pub fn projectRoot(io: std.Io, explicit: ?[]const u8) !std.Io.Dir {
    if (explicit) |p| return std.Io.Dir.cwd().openDir(io, p, .{});
    const ups = [_][]const u8{ ".", "..", "../..", "../../..", "../../../.." };
    for (ups) |up| {
        const d = std.Io.Dir.cwd().openDir(io, up, .{}) catch continue;
        if (d.access(io, main_image.file, .{})) |_| return d else |_| d.close(io);
    }
    return error.ProjectRootNotFound;
}

test "warm reset preserves RAM and programmed flash; fresh reset restores the supplied image" {
    const Mem = struct {
        pub var data: [0x10000]u16 = undefined;
        pub var bus: Bus = undefined;
    };
    const S = Soc(Mem);
    var directory = std.testing.tmpDir(.{});
    defer directory.cleanup();
    var bytes: [0x204]u8 = @splat(0);
    std.mem.writeInt(u16, bytes[0x200..][0..2], 0xABCD, .little);
    try directory.dir.writeFile(std.testing.io, .{ .sub_path = "synthetic.bin", .data = &bytes });
    var profile = main_image;
    profile.file = "synthetic.bin";
    profile.window_base = 0;
    profile.window_end = 0x102;
    profile.code_words = 1;
    try S.init(std.testing.allocator, std.testing.io, directory.dir, profile);
    defer S.deinit(std.testing.allocator);
    S.systemMode(true);
    try std.testing.expectEqual(@as(u16, 0xABCD), Mem.data[0x100]);
    // Drive the same external flash protocol the original persistent-store driver uses.
    for ([_][2]u32{ .{ 0x5555, 0xAA }, .{ 0x2AAA, 0x55 }, .{ 0x5555, 0xA0 }, .{ 0x1000, 0x1234 } }) |cycle|
        S.flash.write(cycle[0], @intCast(cycle[1]));
    S.flash.words[S.laid_at + 0x100] &= 0x0FFF;
    S.flash.words[S.laid_at] = 0x00E2;
    Mem.data[0xA100] = 0xCAFE;
    S.dev.low[0x76] = 1;
    S.dev.io[0x91] = 1;
    S.core.cpu.al = 0xBEEF;
    S.core.steps = 42;
    Mem.bus.halt(.{ .fault = 0x1234 });
    S.flash.state = .autoselect;
    S.warmReset();
    try std.testing.expectEqual(@as(u16, 0x1234), S.flash.read(0x1000));
    try std.testing.expectEqual(@as(u16, 0x0BCD), Mem.data[0x100]);
    try std.testing.expectEqual(@as(u16, 0xCAFE), Mem.data[0xA100]);
    try std.testing.expectEqual(@as(u16, 0), S.dev.low[0x76]);
    try std.testing.expectEqual(@as(u16, 0), S.dev.io[0x91]);
    try std.testing.expectEqual(@as(u16, 0), S.core.cpu.al);
    try std.testing.expectEqual(@as(u64, 0), S.core.steps);
    try std.testing.expectEqual(cpu_mod.image_base, S.core.cpu.pc);
    try std.testing.expectEqual(@as(u16, 0x00E2), S.core.code[0].words[0]);
    try std.testing.expectEqual(flash_mod.State.read, S.flash.state);
    try std.testing.expectEqual(@as(?bus_mod.Stop, null), Mem.bus.stop);
    // The live bus still sees the retained flash after volatile page selectors reset.
    Mem.bus.write(0x73, 16, 1);
    try std.testing.expectEqual(@as(u64, 0x1234), Mem.bus.read(0x8000, 16));
    S.reset();
    try std.testing.expectEqual(@as(u16, 0xFFFF), S.flash.read(0x1000));
    try std.testing.expectEqual(@as(u16, 0), Mem.data[0xA100]);
    try std.testing.expectEqual(@as(u16, 0xABCD), Mem.data[0x100]);
    try std.testing.expectEqual(@as(u16, 0), S.core.code[0].words[0]);
}
