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
pub fn map(window_end: u16) [21]Range {
    return .{
        .{ .lo = 0x0001, .hi = 0x0035, .kind = .mmio }, // radio config block
        .{ .lo = 0x003F, .hi = 0x004C, .kind = .mmio }, // HW timers
        .{ .lo = 0x0061, .hi = 0x0062, .kind = .mmio }, // PIO direction/output
        .{ .lo = 0x0064, .hi = 0x0069, .kind = .mmio }, // IRQ control
        .{ .lo = 0x006E, .hi = 0x0071, .kind = .mmio }, // MMU page-list selectors
        .{ .lo = 0x0073, .hi = 0x0074, .kind = .mmio }, // flash page / bank
        .{ .lo = 0x0076, .hi = 0x0078, .kind = .mmio }, // watchdog / reset
        .{ .lo = 0x00A7, .hi = 0x00A8, .kind = .mmio }, // GPIO edge masks
        .{ .lo = mem16.window_lo, .hi = window_end - 1, .kind = .rom }, // flash constant window
        .{ .lo = 0x4000, .hi = 0x7FFF, .kind = .mmio }, // MMU buffer windows
        .{ .lo = 0x8000, .hi = 0x8FFF, .kind = .mmio }, // flash page window (page = reg 0x0073)
        .{ .lo = 0xA000, .hi = 0xFD04, .kind = .ram }, // RAM, pool, globals + stack, crash record
        .{ .lo = 0xFD05, .hi = 0xFD05, .kind = .mmio }, // MMU indirect physical-page access
        .{ .lo = 0xFD06, .hi = 0xFDBD, .kind = .ram },
        .{ .lo = 0xFDBE, .hi = 0xFDC5, .kind = .mmio }, // serial control/count registers (58B54..58DE0)
        .{ .lo = 0xFDC6, .hi = 0xFDFF, .kind = .ram },
        // Inferred register page: original driver accesses span FE6C..FEDB (bc5-arch §8).
        .{ .lo = 0xFE00, .hi = 0xFEFF, .kind = .mmio },
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
    serial: [8]u16 = @splat(0),
    ext: [0x100]u16 = @splat(0),
    io: [0x100]u16 = @splat(0),
    pending: u16 = 0,
    interrupt_level: u16 = 0,
    interrupt_depth: u16 = 0,
    interrupt_registers: [4][2]u16 = @splat(@splat(0)),
    timer_armed: u16 = 0,
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

/// Implemented fallback device accesses, excluding the separate buffer-MMU model.
/// Latches and boot-poll defaults are hypotheses and remain unsupported in strict runs.
pub fn modeledAccess(address: u16, write: bool) bool {
    if (address >= 0x8000 and address < 0x9000) return true;
    if (address == 0x73) return true;
    return !write and (address == 0xFF7D or address == 0xFFB4 or address == 0xFFB5);
}

pub const peripheral_assumption = "inferred-bc5-timer-irq";

pub fn timerIrqAccess(address: u16, write: bool) bool {
    return switch (address) {
        0x41...0x44, 0x48...0x4C, 0x64...0x69, 0xFF94, 0xFF95 => true,
        0xFFC3, 0xFFC4 => !write,
        else => false,
    };
}

pub fn analogAccess(address: u16, write: bool) bool {
    return switch (address) {
        0xFF79, 0xFF7B, 0xFF80, 0xFF8C, 0xFF8D => true,
        0xFF7C, 0xFF8E => !write,
        else => false,
    };
}

pub fn Soc(comptime M: type) type {
    return struct {
        pub var core: cpu_mod.Core = undefined;
        pub var dev: Devices = .{};
        pub var image: Image = main_image;
        /// Timer/IRQ register meanings follow original 657E..6820 and 0E8C..1172.
        /// IRQ entry uses the interpreter's explicitly inferred XAP2 hardware frame.
        pub var hardware_enabled = false;
        /// External stimuli survive CPU/device reset. AIO0..3 are routed through channel5 by 107DC.
        pub var analog_inputs: [4]u16 = @splat(0);
        pub var adc_inputs: [2][64]u16 = @splat(@splat(0));
        pub var words: []u16 = &.{};
        /// Physical flash behind the page window (system runs); the image sits at the
        /// XA-flash-bank offset. Not a snapshot part: function tests tape the window.
        pub var flash: flash_mod.Flash = .{};
        /// Offset the image was laid at in `flash` (re-laid when the selection changes).
        pub var laid_at: u32 = 0;
        var segs: [2]cpu_mod.Segment = undefined;
        var ranges: [21]Range = undefined;
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
            core = .{ .bus = &M.bus, .code = &segs, .alias_regs = image.alias_regs, .sel = sel, .banked_interrupts = hardware_enabled };
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

        pub fn setAnalog(channel: u4, value: u10) error{BadAnalogChannel}!void {
            if (channel >= analog_inputs.len) return error.BadAnalogChannel;
            analog_inputs[channel] = value;
        }

        pub fn setAdcSample(bank: u1, channel: u6, value: u10) void {
            adc_inputs[bank][channel] = value;
        }

        pub fn raiseInterrupt(source: u4) void {
            dev.pending |= @as(u16, 1) << source;
        }

        /// 1B182 drives conversion-start bit13 and polls bit4 in FF8E/FF7C, then reads bits15..6.
        /// Busy follows the start level; analogue settling time is not calibrated.
        fn adcStatus(bank: u1) ?u16 {
            const enable: u16 = if (bank == 0) 0x400 else 0x1000;
            if (!hardware_enabled or dev.io[0x80] & enable == 0) return null;
            const command = dev.io[if (bank == 0) 0x8D else 0x7B];
            const channel: u6 = @truncate(command);
            var sample = adc_inputs[bank][channel];
            if (bank == 0 and channel == 5) {
                // Original 107DC selects an AIO by writing 5 into one of these four mux bytes.
                const mux = [_]u16{ dev.io[0x8C] & 0xFF, dev.io[0x8C] >> 8, dev.io[0x79] & 0xFF, dev.io[0x79] >> 8 };
                for (mux, 0..) |selection, pin| if (selection == 5) {
                    sample = analog_inputs[pin];
                    break;
                };
            }
            const status = dev.io[if (bank == 0) 0x8E else 0x7C] & 0x2F;
            return (sample << 6) | status | (if (command & 0x2000 != 0) @as(u16, 0x10) else 0);
        }

        /// Advance peripheral events before the next guest instruction. No guest callback is injected.
        pub fn tick() void {
            core.banked_interrupts = hardware_enabled;
            if (!hardware_enabled) return;
            const now: u32 = @truncate(core.steps >> clock_shift);
            const enabled = dev.io[0x94];
            for ([_]u4{ 1, 2, 3 }, [_]u4{ 2, 0, 13 }) |bit, irq| {
                const mask = @as(u16, 1) << bit;
                if (dev.timer_armed & enabled & mask == 0) continue;
                const due = switch (bit) {
                    1 => @as(i32, @bitCast(now -% (@as(u32, dev.low[0x41]) << 16 | dev.low[0x42]))) >= 0,
                    2 => @as(i32, @bitCast(now -% (@as(u32, dev.low[0x43]) << 16 | dev.low[0x44]))) >= 0,
                    else => @as(i16, @bitCast(@as(u16, @truncate(now)) -% dev.low[0x4C])) >= 0,
                };
                if (!due) continue;
                dev.pending |= @as(u16, 1) << irq;
                dev.timer_armed &= ~mask;
                if (bit == 1 and dev.low[0x4B] != 0) {
                    const period = @as(u32, dev.low[0x48]) << 16 | dev.low[0x49];
                    if (period != 0) {
                        const next = (@as(u32, dev.low[0x41]) << 16 | dev.low[0x42]) +% period;
                        dev.low[0x41] = @truncate(next >> 16);
                        dev.low[0x42] = @truncate(next);
                        dev.timer_armed |= mask;
                    }
                }
            }
            if (dev.io[0x95] & 2 == 0 or core.cpu.flags & 0x10 == 0) return;
            const pending = dev.pending & dev.low[0x64];
            const priorities: u32 = @as(u32, dev.low[0x65]) << 16 | dev.low[0x66];
            var source: ?u4 = null;
            var level = dev.interrupt_level;
            for (0..16) |n| {
                if (pending & (@as(u16, 1) << @as(u4, @intCast(n))) == 0) continue;
                const priority: u16 = @intCast((priorities >> @as(u5, @intCast(n * 2))) & 3);
                if ((source == null and dev.interrupt_depth == 0) or priority > level) {
                    source = @intCast(n);
                    level = priority;
                }
            }
            if (source) |irq| {
                if (core.interrupt(cpu_mod.image_base)) {
                    // A higher level can preempt before the wrapper reads FFC3/FFC4.
                    dev.interrupt_registers[dev.interrupt_depth] = .{ dev.io[0xC3], dev.io[0xC4] };
                    dev.io[0xC3] = irq;
                    dev.io[0xC4] = dev.interrupt_level;
                    dev.pending &= ~(@as(u16, 1) << irq);
                    dev.interrupt_level = level;
                    dev.interrupt_depth += 1;
                }
            }
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
            if (a >= 0xFDBE and a <= 0xFDC5) return dev.serial[a - 0xFDBE];
            if (a >= 0xFE00 and a < 0xFF00) return dev.ext[a - 0xFE00];
            if (a == 0xFF8E) if (adcStatus(0)) |v| return v;
            if (a == 0xFF7C) if (adcStatus(1)) |v| return v;
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
            const v: u16 = @truncate(value);
            if (a >= 0x8000 and a < 0x9000) return flash.write(physical(a), @truncate(value));
            if (a >= 0xFDBE and a <= 0xFDC5) {
                dev.serial[a - 0xFDBE] = v;
                return;
            }
            if (hardware_enabled) switch (a) {
                // 6820 enables source11+event; 6834 pulses the unshifted event bit through 69.
                0x69 => dev.pending |= (v & ~dev.low[0x69] & 0x1F) << 11,
                0x67 => {
                    dev.interrupt_level = v & 3;
                    if (dev.interrupt_depth != 0) {
                        dev.interrupt_depth -= 1;
                        const previous = dev.interrupt_registers[dev.interrupt_depth];
                        dev.io[0xC3] = previous[0];
                        dev.io[0xC4] = previous[1];
                    }
                },
                0xFF94 => dev.timer_armed = (dev.timer_armed & v) | (v & ~dev.io[0x94] & 0xE),
                0x41, 0x42 => dev.timer_armed |= dev.io[0x94] & 2,
                0x43, 0x44 => dev.timer_armed |= dev.io[0x94] & 4,
                0x4C => dev.timer_armed |= dev.io[0x94] & 8,
                else => {},
            };
            if (a < 0x100) dev.low[a] = @truncate(value) else if (a >= 0xFE00 and a < 0xFF00) dev.ext[a - 0xFE00] = @truncate(value) else if (a >= 0xFF00) dev.io[a - 0xFF00] = @truncate(value);
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

test "strict BC5 access classification excludes register latches and boot defaults" {
    for ([_]u16{ 0x8000, 0x8FFF, 0x73 }) |address| {
        try std.testing.expect(modeledAccess(address, false));
        try std.testing.expect(modeledAccess(address, true));
    }
    for ([_]u16{ 0xFF7D, 0xFFB4, 0xFFB5 }) |address| {
        try std.testing.expect(modeledAccess(address, false));
        try std.testing.expect(!modeledAccess(address, true));
    }
    for ([_]u16{ 0x64, 0x74, 0x76, 0xFE95, 0xFF95, 0xFFB9, 0xFFFF }) |address| {
        try std.testing.expect(!modeledAccess(address, false));
        try std.testing.expect(!modeledAccess(address, true));
    }
}

const TimerFixture = struct {
    pub var data: [0x10000]u16 = undefined;
    pub var bus: Bus = undefined;
    const S = Soc(@This());
    var ranges: [21]Range = undefined;
    var backing: [1]bus_mod.Backing(u16) = undefined;

    fn setup() !void {
        @memset(&data, 0);
        ranges = map(main_image.window_end);
        backing = .{.{ .base = 0, .mem = &data }};
        bus = try Bus.init(std.testing.allocator, &ranges, &backing);
        S.dev = .{};
        S.analog_inputs = @splat(0);
        S.adc_inputs = @splat(@splat(0));
        S.core = .{ .bus = &bus, .code = &.{} };
        S.core.cpu.y = 0xB000;
        S.core.cpu.uy = 0xAF00;
        S.core.cpu.pc = cpu_mod.image_base + 0x500;
        S.core.cpu.flags = 0x10;
        S.hardware_enabled = true;
        S.systemMode(true);
        bus.write(0xFF95, 16, 7);
    }

    fn deinit() void {
        S.hardware_enabled = false;
        bus.deinit();
    }
};

test "compare B queues one masked IRQ and saves the interrupted frame when enabled" {
    const F = TimerFixture;
    try F.setup();
    defer F.deinit();
    F.bus.write(0x43, 16, 0);
    F.bus.write(0x44, 16, 10);
    F.bus.write(0x66, 16, 2);
    F.bus.write(0xFF94, 16, 5);
    F.S.core.steps = 9 << clock_shift;
    F.S.tick();
    try std.testing.expectEqual(@as(u16, 0), F.S.dev.pending);
    F.S.core.steps = 10 << clock_shift;
    F.S.tick();
    try std.testing.expectEqual(@as(u16, 1), F.S.dev.pending);
    try std.testing.expectEqual(cpu_mod.image_base + 0x500, F.S.core.cpu.pc);
    F.bus.write(0x64, 16, 1);
    F.S.tick();
    try std.testing.expectEqual(cpu_mod.image_base + 2, F.S.core.cpu.pc);
    try std.testing.expectEqual(@as(u16, 0), F.S.dev.pending);
    try std.testing.expectEqual(@as(u16, 0x10), F.data[0xAF00 - 33]);
    try std.testing.expectEqual(@as(u16, 0), F.data[0xAF00 - 32]);
    try std.testing.expectEqual(@as(u16, 0x850C), F.data[0xAF00 - 31]);
    try std.testing.expectEqual(@as(u16, 2), F.S.dev.interrupt_level);
    F.bus.write(0x67, 16, 0x800);
    F.S.core.cpu.flags = 0x10;
    F.S.tick();
    try std.testing.expectEqual(@as(u16, 0), F.S.dev.pending);
    try std.testing.expectEqual(@as(u16, 0), F.S.dev.interrupt_level);
}

test "pending IRQs respect global enable and choose the highest enabled priority" {
    const F = TimerFixture;
    try F.setup();
    defer F.deinit();
    F.bus.write(0x64, 16, 5);
    F.bus.write(0x66, 16, 0x32);
    F.bus.write(0xFF95, 16, 5);
    F.S.raiseInterrupt(0);
    F.S.raiseInterrupt(2);
    F.S.tick();
    try std.testing.expectEqual(@as(u16, 5), F.S.dev.pending);
    F.bus.write(0xFF95, 16, 7);
    F.S.tick();
    try std.testing.expectEqual(@as(u16, 2), F.S.dev.io[0xC3]);
    try std.testing.expectEqual(@as(u16, 3), F.S.dev.interrupt_level);
    try std.testing.expectEqual(@as(u16, 1), F.S.dev.pending);
    // Re-enabling CPU interrupts inside a level-3 ISR cannot admit a level-2 request.
    F.S.core.cpu.flags = 0x10;
    F.S.tick();
    try std.testing.expectEqual(@as(u16, 1), F.S.dev.pending);
    F.bus.write(0x67, 16, 0x800);
    F.S.tick();
    try std.testing.expectEqual(@as(u16, 0), F.S.dev.io[0xC3]);
    try std.testing.expectEqual(@as(u16, 0), F.S.dev.pending);
}

test "nested interrupt completion restores the outer source and previous-level registers" {
    const F = TimerFixture;
    try F.setup();
    defer F.deinit();
    F.bus.write(0x64, 16, 3);
    F.bus.write(0x66, 16, 0xD); // IRQ0 level1, IRQ1 level3.
    F.S.dev.io[0xC3] = 9;
    F.S.dev.io[0xC4] = 2;
    F.S.raiseInterrupt(0);
    F.S.tick();
    F.S.core.cpu.flags = 0x10;
    F.S.raiseInterrupt(1);
    F.S.tick();
    try std.testing.expectEqual(@as(u16, 2), F.S.dev.interrupt_depth);
    try std.testing.expectEqual(@as(u16, 1), F.S.dev.io[0xC3]);
    try std.testing.expectEqual(@as(u16, 1), F.S.dev.io[0xC4]);
    F.bus.write(0x67, 16, 0x801);
    try std.testing.expectEqual(@as(u16, 1), F.S.dev.interrupt_level);
    try std.testing.expectEqual(@as(u16, 0), F.S.dev.io[0xC3]);
    try std.testing.expectEqual(@as(u16, 0), F.S.dev.io[0xC4]);
    F.bus.write(0x67, 16, 0x800);
    try std.testing.expectEqual(@as(u16, 0), F.S.dev.interrupt_depth);
    try std.testing.expectEqual(@as(u16, 9), F.S.dev.io[0xC3]);
    try std.testing.expectEqual(@as(u16, 2), F.S.dev.io[0xC4]);
}

test "software event bits map to interrupt sources eleven through fifteen" {
    const F = TimerFixture;
    try F.setup();
    defer F.deinit();
    F.bus.write(0x69, 16, 0x1F);
    try std.testing.expectEqual(@as(u16, 0xF800), F.S.dev.pending);
    F.bus.write(0x69, 16, 0);
    try std.testing.expectEqual(@as(u16, 0xF800), F.S.dev.pending);
    F.S.dev.pending = 0;
    F.bus.write(0x69, 16, 4);
    try std.testing.expectEqual(@as(u16, 0x2000), F.S.dev.pending);
    F.S.dev.pending = 0;
    F.bus.write(0x69, 16, 4);
    try std.testing.expectEqual(@as(u16, 0), F.S.dev.pending);
}

test "compare A reloads its programmed period and compare C matches across low-word wrap" {
    const F = TimerFixture;
    try F.setup();
    defer F.deinit();
    F.bus.write(0x41, 16, 0);
    F.bus.write(0x42, 16, 0xFFFE);
    F.bus.write(0x48, 16, 0);
    F.bus.write(0x49, 16, 4);
    F.bus.write(0x4B, 16, 1);
    F.bus.write(0x4C, 16, 2);
    F.bus.write(0xFF94, 16, 0xB);
    F.S.core.steps = 0xFFFE << clock_shift;
    F.S.tick();
    try std.testing.expectEqual(@as(u16, 4), F.S.dev.pending);
    try std.testing.expectEqual(@as(u16, 1), F.S.dev.low[0x41]);
    try std.testing.expectEqual(@as(u16, 2), F.S.dev.low[0x42]);
    F.S.core.steps = 0x10002 << clock_shift;
    F.S.tick();
    try std.testing.expectEqual(@as(u16, 0x2004), F.S.dev.pending);
    try std.testing.expectEqual(@as(u16, 6), F.S.dev.low[0x42]);
}

test "priority-zero guest ISR executes device delivery and returns through the original frame contract" {
    const F = TimerFixture;
    try F.setup();
    defer F.deinit();
    // Vector word2: ld AL,#77; st AL,@A100; ld AL,#800; st AL,@67; rti @(-33,Y).
    const code = [_]u16{ 0, 0, 0x7714, 0xA100, 0x0025, 0x0800, 0x0014, 0x6725, 0xDF0D };
    const segments = [_]cpu_mod.Segment{.{ .base = cpu_mod.image_base, .words = &code }};
    F.S.core.code = &segments;
    const interrupted = F.S.core.cpu.pc;
    F.bus.write(0x64, 16, 1);
    F.S.raiseInterrupt(0);
    F.S.tick();
    try std.testing.expectEqual(cpu_mod.image_base + 2, F.S.core.cpu.pc);
    for (0..5) |_| {
        F.S.tick();
        F.S.core.step();
    }
    try std.testing.expectEqual(@as(u16, 0x77), F.data[0xA100]);
    try std.testing.expectEqual(interrupted, F.S.core.cpu.pc);
    try std.testing.expectEqual(@as(u16, 0x10), F.S.core.cpu.flags);
    try std.testing.expectEqual(@as(u16, 0), F.S.dev.interrupt_depth);
    try std.testing.expectEqual(@as(?cpu_mod.Halt, null), F.S.core.halted);
}

test "banked IRQ stack keeps a guest wrapper separate from its interrupted return PC" {
    const F = TimerFixture;
    try F.setup();
    defer F.deinit();
    // Independent wrapper using the same saved-frame/alternate-stack ABI, including newY-3 scratch.
    const code = [_]u16{ 0, 0, 0xDE2B, 0xDD03, 0xDD1B, 0x1058, 0xDC2E, 0xDB22, 0xDA26, 0xD92A, 0xD91E, 0xFD2F, 0x0800, 0x0014, 0x6725, 0xDA17, 0xDB13, 0xDC1F, 0xDD07, 0xDE1B, 0xDF0D };
    const segments = [_]cpu_mod.Segment{.{ .base = cpu_mod.image_base, .words = &code }};
    F.S.core.code = &segments;
    F.S.core.cpu.y = 0xFCCA;
    F.S.core.cpu.uy = 0xFCBD;
    F.S.core.cpu.ah = 12;
    F.S.core.cpu.al = 0x7393;
    F.S.core.cpu.x = 0xDBC8;
    const interrupted = F.S.core.cpu;
    F.bus.write(0x64, 16, 1);
    F.S.raiseInterrupt(0);
    F.S.tick();
    try std.testing.expectEqual(interrupted.uy, F.S.core.cpu.y);
    try std.testing.expectEqual(interrupted.y, F.S.core.cpu.uy);
    var steps: usize = 0;
    while (F.S.core.cpu.pc != interrupted.pc and steps < 32) : (steps += 1) {
        F.S.tick();
        F.S.core.step();
    }
    try std.testing.expectEqualDeep(interrupted, F.S.core.cpu);
    try std.testing.expectEqual(@as(u16, 0), F.S.dev.interrupt_depth);
    try std.testing.expectEqual(@as(u16, 0), F.data[0xFCC8]);
}

test "ADC start/status handshake and both result widths follow externally supplied samples" {
    const F = TimerFixture;
    try F.setup();
    defer F.deinit();
    F.S.setAdcSample(0, 0x17, 0x2AB);
    F.S.setAdcSample(1, 3, 0x155);
    F.bus.write(0xFF80, 16, 0x1400);
    F.bus.write(0xFF8D, 16, 0x8017);
    try std.testing.expectEqual(@as(u64, 0xAAC0), F.bus.read(0xFF8E, 16));
    F.bus.write(0xFF8D, 16, 0xA017);
    try std.testing.expectEqual(@as(u64, 0xAAD0), F.bus.read(0xFF8E, 16));
    F.bus.write(0xFF8D, 16, 0x8017);
    try std.testing.expectEqual(@as(u64, 0xAA), F.bus.read(0xFF8E, 16) >> 8);
    F.bus.write(0xFF7B, 16, 0xB003);
    try std.testing.expectEqual(@as(u64, 0x5550), F.bus.read(0xFF7C, 16));
    F.bus.write(0xFF7B, 16, 0x9003);
    try std.testing.expectEqual(@as(u64, 0x155), F.bus.read(0xFF7C, 16) >> 6);
    F.bus.write(0xFF80, 16, 0);
    try std.testing.expectEqual(@as(u64, 0), F.bus.read(0xFF8E, 16));
}

test "original AIO mux selects four independent physical inputs and rejects invalid stimuli" {
    const F = TimerFixture;
    try F.setup();
    defer F.deinit();
    for (0..4) |pin| try F.S.setAnalog(@intCast(pin), @intCast(0x100 + pin));
    try std.testing.expectError(error.BadAnalogChannel, F.S.setAnalog(4, 0));
    F.bus.write(0xFF80, 16, 0x400);
    F.bus.write(0xFF8D, 16, 0x8005);
    for (0..4) |pin| {
        F.bus.write(0xFF8C, 16, if (pin == 0) 5 else if (pin == 1) 0x500 else 0);
        F.bus.write(0xFF79, 16, if (pin == 2) 5 else if (pin == 3) 0x500 else 0);
        try std.testing.expectEqual(@as(u64, 0x100 + pin), F.bus.read(0xFF8E, 16) >> 6);
    }
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
    Mem.data[0xFEA0] = 0xCAFE;
    try std.testing.expectEqual(bus_mod.Kind.mmio, Mem.bus.kindOf(0xFEA0));
    Mem.bus.write(0xFEA0, 16, 0x1234);
    try std.testing.expectEqual(@as(u16, 0xCAFE), Mem.data[0xFEA0]);
    try std.testing.expectEqual(@as(u16, 0x1234), S.dev.ext[0xA0]);
    try std.testing.expectEqual(@as(u64, 0x1234), Mem.bus.read(0xFEA0, 16));
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
    try std.testing.expectEqual(@as(u16, 0), S.dev.ext[0xA0]);
    try std.testing.expectEqual(@as(u64, 0), Mem.bus.read(0xFEA0, 16));
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
