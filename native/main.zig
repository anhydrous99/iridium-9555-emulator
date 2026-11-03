//! Process-isolated original-firmware execution. One JSON request and reply per line.
const std = @import("std");
const common = @import("common");
const xap = @import("xap2");
const avr = @import("emu_avr");
const bc5 = @import("bc5");
const avr_soc = @import("avr_soc");
const trx = @import("trx");
const mmu = @import("mmu.zig");
const m = trx.machine;
const Value = std.json.Value;
const Image = enum { bc5, avr, trx, ptt };
const Handset = enum { @"9555", @"9575" };
var handset: Handset = .@"9555";
const max_steps = 10_000_000;
const max_probe_steps = 100_000_000;
const max_memory = 4096;

const BcMem = struct {
    pub var data: [0x10000]u16 = @splat(0);
    pub var bus: bc5.Bus = undefined;
};
const Bc = bc5.Soc(BcMem);
var bc5_fallback: common.bus.Device = undefined;
var bc5_mmu: mmu.Model = undefined;
const ModelError = struct { address: u32, operation: []const u8, reason: []const u8 };
var model_error: ?ModelError = null;
var avr_data: avr.cpu.Data = @splat(0);
var avr_prog: avr.cpu.Prog = undefined;
var avr_bus: avr.cpu.Bus = undefined;
var avr_cpu: avr.Cpu = undefined;
var avr_dev: avr_soc.devices.Devices = .{};
var avr_backing = [_]common.bus.Backing(u8){.{ .base = 0, .mem = &avr_data }};
const avr_map = [_]common.bus.Range{
    .{ .lo = 0, .hi = 0x1F, .kind = .cpu_alias },
    .{ .lo = 0x20, .hi = 0x5C, .kind = .mmio },
    .{ .lo = 0x5D, .hi = 0x5F, .kind = .cpu_alias },
    .{ .lo = 0x60, .hi = 0xFF, .kind = .mmio },
    .{ .lo = 0x100, .hi = 0x4FF, .kind = .ram },
};
const avr_extreme_map = [_]common.bus.Range{
    .{ .lo = 0, .hi = 0x1F, .kind = .cpu_alias },
    .{ .lo = 0x20, .hi = 0x5C, .kind = .mmio },
    .{ .lo = 0x5D, .hi = 0x5F, .kind = .cpu_alias },
    .{ .lo = 0x60, .hi = 0x1FF, .kind = .mmio },
    .{ .lo = 0x200, .hi = 0x21FF, .kind = .ram },
};
var trx_model: trx.devices.Model = undefined;
var trx_flash: trx.devices.Flash = undefined;
var current_image: Image = .bc5;
var firmware: []const u8 = &.{};
var ready = false;
var total_steps: u64 = 0;
var unclassified: u64 = 0;
var halt_buffer: [256]u8 = undefined;
var halt_reason: ?[]const u8 = null;
var lcd_buffer: [65536]u8 = undefined;
var lcd_len: usize = 0;
var lcd_dropped: u64 = 0;
const Milestones = struct { main: bool = false, scheduler: bool = false, idle: bool = false, panic: ?u16 = null };
var milestones: Milestones = .{};
const CallStop = struct {
    registers: [8]u16,
    stack_address: u16,
    stack_count: u8,
    stack_words: [64]u16,
};
const CallResult = struct {
    returned: bool,
    al: u16,
    ah: u16,
    steps: u64,
    pc: u32,
    program_pc: u32,
    stopped: ?CallStop,
};
var last_call: ?CallResult = null;

pub fn main(init: std.process.Init) !u8 {
    var outbuf: [8192]u8 = undefined;
    var output = std.Io.File.stdout().writerStreaming(init.io, &outbuf);
    const out = &output.interface;
    defer out.flush() catch {};
    return serve(init, out) catch |err| {
        try json(out, .{ .@"error" = @errorName(err), .fatal = true });
        return 2;
    };
}

fn serve(init: std.process.Init, out: *std.Io.Writer) !u8 {
    const args = try init.minimal.args.toSlice(init.arena.allocator());
    var name: ?[]const u8 = null;
    var path: ?[]const u8 = null;
    var i: usize = 1;
    while (i < args.len) : (i += 2) {
        if (i + 1 == args.len) return error.ExpectedImageAndFirmware;
        if (std.mem.eql(u8, args[i], "--image")) {
            name = args[i + 1];
        } else if (std.mem.eql(u8, args[i], "--firmware")) {
            path = args[i + 1];
        } else if (std.mem.eql(u8, args[i], "--model")) {
            handset = std.meta.stringToEnum(Handset, args[i + 1]) orelse return error.UnknownHandset;
        } else return error.UnknownArgument;
    }
    current_image = std.meta.stringToEnum(Image, name orelse return error.ExpectedImageAndFirmware) orelse return error.UnknownImage;
    const input = path orelse return error.ExpectedImageAndFirmware;
    firmware = try std.Io.Dir.cwd().readFileAlloc(init.io, input, init.gpa, .limited(8 << 20));
    defer init.gpa.free(firmware);
    try initialize(init, input);
    defer deinitialize(init.gpa);
    try state(out);
    try out.flush();
    var inbuf: [65536]u8 = undefined;
    var input_stream = std.Io.File.stdin().readerStreaming(init.io, &inbuf);
    while (try input_stream.interface.takeDelimiter('\n')) |line| {
        var arena = std.heap.ArenaAllocator.init(init.gpa);
        defer arena.deinit();
        request(init, arena.allocator(), out, line) catch |err| {
            try json(out, .{ .@"error" = @errorName(err), .fatal = false });
        };
        try out.flush();
    }
    return 0;
}

fn initialize(init: std.process.Init, path: []const u8) !void {
    switch (current_image) {
        .bc5 => {
            const size: usize = if (handset == .@"9575") 0x36BB22 else 0x310FBA;
            if (firmware.len != size and firmware.len != size + 4) return error.BadBc5ImageSize;
            var profile = bc5.main_image;
            profile.file = path;
            // The optional final two raw-image words are a container CRC, not firmware.
            profile.window_end = if (handset == .@"9575") 0x3E6C else 0x3C7E;
            if (handset == .@"9575") {
                profile.window_base = 0x363E4A / 2;
                profile.code_words = 0xFEF96 / 2;
            }
            try Bc.init(init.gpa, init.io, std.Io.Dir.cwd(), profile);
            attachBc5Devices();
        },
        .avr => {
            const size: usize = if (handset == .@"9575") 14296 else avr_soc.loader.image_len;
            if (firmware.len != size) return error.BadAvrImageSize;
            @memset(&avr_prog, 0xFF);
            @memcpy(avr_prog[0..firmware.len], firmware);
            avr_backing[0].mem = avr_data[0..if (handset == .@"9575") @as(usize, 0x2200) else 0x500];
            avr_bus = try avr.cpu.Bus.init(init.gpa, if (handset == .@"9575") &avr_extreme_map else &avr_map, &avr_backing);
            avr_cpu = .{ .data = &avr_data, .prog = &avr_prog, .bus = &avr_bus };
            avr_cpu.program_mask = if (handset == .@"9575") 0xFFFF else avr.cpu.pc_mask;
            avr_dev = .{ .bus = &avr_bus, .open_bus = true, .mega = handset == .@"9575" };
            avr_dev.reset();
            avr_bus.dev = avr_dev.device();
            avr_cpu.sys = avr_dev.sys();
            avr_soc.loader.coldReset(&avr_cpu);
            if (handset == .@"9575") avr_cpu.st.sp = 0x21FF;
        },
        .trx, .ptt => {
            const expected: usize = if (current_image == .trx) 0x260760 else 0xA7BF8;
            if (firmware.len != expected) return error.BadTrxImageSize;
            @memset(&m.flash, 0xFF);
            const offset: usize = if (current_image == .trx) 0 else 0x400000 - m.flash_base;
            @memcpy(m.flash[offset..][0..firmware.len], firmware);
            try m.reset(init.gpa, if (current_image == .trx) .p1 else .p2, 8);
            trx_model = .{ .gpa = init.gpa, .nwin = 8 };
            m.bus.dev = trx_model.device();
            trx_flash = .{ .mem = &m.flash, .base = m.flash_base, .bus = &m.bus };
            m.cpu.asi1 = trx_flash.device();
        },
    }
    ready = true;
    resetCounters();
}

fn deinitialize(gpa: std.mem.Allocator) void {
    if (!ready) return;
    switch (current_image) {
        .bc5 => Bc.deinit(gpa),
        .avr => avr_bus.deinit(),
        .trx, .ptt => {
            trx_model.deinit();
            m.deinit();
        },
    }
    ready = false;
}

fn resetCounters() void {
    total_steps = 0;
    unclassified = 0;
    halt_reason = null;
    milestones = .{};
    lcd_len = 0;
    lcd_dropped = 0;
    last_call = null;
    model_error = null;
}

fn attachBc5Devices() void {
    Bc.systemMode(true);
    bc5_fallback = BcMem.bus.dev.?;
    bc5_mmu = .{ .data = &BcMem.data, .system_control = &Bc.dev.io[0x97] };
    BcMem.bus.dev = .{ .ctx = &bc5_mmu, .read = bc5Read, .write = bc5Write };
}

fn modelFault(address: u32, operation: []const u8, err: anyerror) void {
    model_error = .{ .address = address, .operation = operation, .reason = @errorName(err) };
    halt_reason = std.fmt.bufPrint(&halt_buffer, "mmu:{s}@0x{x}", .{ @errorName(err), address }) catch "mmu-fault";
    BcMem.bus.halt(.{ .fault = address });
}

fn bc5Read(_: *anyopaque, address: u32, bits: u8) u64 {
    const value = bc5_mmu.read(@intCast(address)) catch |err| {
        modelFault(address, "read", err);
        return 0;
    };
    return value orelse bc5_fallback.read(bc5_fallback.ctx, address, bits);
}

fn bc5Write(_: *anyopaque, address: u32, bits: u8, value: u64) void {
    const handled = bc5_mmu.write(@intCast(address), @truncate(value)) catch |err| {
        modelFault(address, "write", err);
        return;
    };
    if (!handled) bc5_fallback.write(bc5_fallback.ctx, address, bits, value);
}

fn reset(init: std.process.Init) !void {
    switch (current_image) {
        .bc5 => {
            Bc.reset();
            attachBc5Devices();
        },
        .avr => {
            @memset(&avr_data, 0);
            avr_bus.resetRun(std.math.maxInt(u64));
            avr_dev = .{ .bus = &avr_bus, .open_bus = true, .mega = handset == .@"9575" };
            avr_dev.reset();
            avr_soc.loader.coldReset(&avr_cpu);
            if (handset == .@"9575") avr_cpu.st.sp = 0x21FF;
        },
        .trx, .ptt => {
            trx_model.deinit();
            m.deinit();
            @memset(&m.flash, 0xFF);
            const offset: usize = if (current_image == .trx) 0 else 0x400000 - m.flash_base;
            @memcpy(m.flash[offset..][0..firmware.len], firmware);
            try m.reset(init.gpa, if (current_image == .trx) .p1 else .p2, 8);
            trx_model = .{ .gpa = init.gpa, .nwin = 8 };
            m.bus.dev = trx_model.device();
            trx_flash = .{ .mem = &m.flash, .base = m.flash_base, .bus = &m.bus };
            m.cpu.asi1 = trx_flash.device();
        },
    }
    resetCounters();
}

fn json(out: *std.Io.Writer, value: anytype) !void {
    try std.json.Stringify.value(value, .{}, out);
    try out.writeByte('\n');
}

fn state(out: *std.Io.Writer) !void {
    var registers: [32]u32 = @splat(0);
    var uart_dropped: [4]u64 = @splat(0);
    if (current_image == .avr) for (&uart_dropped, avr_dev.st.usart) |*lost, uart| {
        lost.* = uart.out_dropped;
    };
    var lcd_numbers: [lcd_buffer.len]u16 = undefined;
    for (lcd_buffer[0..lcd_len], 0..) |byte, index| lcd_numbers[index] = byte;
    const pc: u32 = switch (current_image) {
        .bc5 => xap.cpu.byteAddr(Bc.core.cpu.pc),
        .avr => @as(u32, avr_cpu.st.pc) * 2,
        .trx, .ptt => m.regs.pc,
    };
    const program_pc: u32 = switch (current_image) {
        .bc5 => Bc.core.cpu.pc,
        .avr => avr_cpu.st.pc,
        .trx, .ptt => m.regs.pc,
    };
    switch (current_image) {
        .bc5 => {
            const r = Bc.core.cpu;
            registers[0..8].* = .{ r.ah, r.al, r.x, r.y, r.xh, r.ux, r.uy, r.flags };
        },
        .avr => for (avr_data[0..32], &registers) |r, *dest| {
            dest.* = r;
        },
        .trx, .ptt => for (0..32) |index| {
            registers[index] = m.cpu.get(@intCast(index));
        },
    }
    try json(out, .{
        .image = @tagName(current_image),
        .handset = @tagName(handset),
        .pc = pc,
        .program_pc = program_pc,
        .steps = total_steps,
        .at_idle = current_image == .bc5 and Bc.core.cpu.pc == xap.cpu.progAddr(0xB774),
        .halt = halt_reason,
        .registers = registers[0..if (current_image == .bc5) @as(usize, 8) else 32],
        .register_names = if (current_image == .bc5) "AH,AL,X,Y,XH,UX,UY,FLAGS" else if (current_image == .avr) "r0..r31" else "g0..g7,o0..o7,l0..l7,i0..i7",
        .flags = switch (current_image) {
            .bc5 => @as(u32, Bc.core.cpu.flags),
            .avr => avr_cpu.sregByte(),
            .trx, .ptt => m.regs.psr,
        },
        .sp = switch (current_image) {
            .bc5 => @as(u32, Bc.core.cpu.y),
            .avr => avr_cpu.st.sp,
            .trx, .ptt => m.cpu.get(14),
        },
        .cycles = if (current_image == .avr) avr_cpu.st.cycles else @as(u64, 0),
        .milestones = milestones,
        .unclassified_accesses = unclassified,
        .lcd_bytes = lcd_numbers[0..lcd_len],
        .lcd_dropped = lcd_dropped,
        .uart_tx_dropped = if (current_image == .avr) uart_dropped[0..avr_dev.uartCount()] else null,
        .last_call = last_call,
        .model = "partial-peripherals",
        .mmu_assumption = if (current_image == .bc5) mmu.assumption else null,
        .flash_assumption = if (current_image == .bc5) bc5.flash_mod.assumption else null,
        .avr_assumption = if (current_image == .avr and handset == .@"9575") "inferred-atmega640-1280-family; unsupported peripherals remain open bus" else null,
        .model_error = model_error,
    });
    lcd_len = 0;
}

fn setHalt(value: anytype) void {
    if (halt_reason == null) halt_reason = std.fmt.bufPrint(&halt_buffer, "{any}", .{value}) catch "halt";
}

fn collectLog(bus: anytype) void {
    for (bus.log.items) |access| if (bus.kindOf(access.addr) == .unclassified) {
        unclassified += 1;
    };
    bus.log.clearRetainingCapacity();
}

fn flushLog() void {
    switch (current_image) {
        .bc5 => collectLog(&BcMem.bus),
        .avr => collectLog(&avr_bus),
        .trx, .ptt => collectLog(&m.bus),
    }
}

fn refillFuel(steps: u64) void {
    // Block-copy instructions can perform many accesses. Fuel bounds these independently of steps.
    const fuel = steps * 32 + (1 << 22);
    switch (current_image) {
        .bc5 => BcMem.bus.resetRun(fuel),
        .avr => avr_bus.resetRun(fuel),
        .trx, .ptt => m.bus.resetRun(fuel),
    }
}

fn observeBc5() void {
    const pc = xap.cpu.byteAddr(Bc.core.cpu.pc);
    if (pc == 0x5748) milestones.main = true;
    if (pc == 0xB5E0) milestones.scheduler = true;
    if (pc == 0xB774) milestones.idle = true;
    if (pc == 0x70A0) milestones.panic = Bc.core.cpu.al;
    // Original reset has armed and kicked the watchdog, then reached its final wait.
    // Stop at that boundary; the host chooses a warm reset without inventing its timing.
    if (pc == 0x184F0 and Bc.dev.low[0x76] == 1 and Bc.dev.io[0x91] & 1 != 0)
        halt_reason = "firmware-reset-requested";
    if (pc == 0x68E48) {
        // Observe the firmware's serial sender; every instruction still executes normally.
        const count = Bc.core.cpu.ah;
        for (0..count) |n| {
            const address = Bc.core.cpu.al +% @as(u16, @intCast(n));
            if (lcd_len < lcd_buffer.len) {
                // MMU reads here are observational: an unsupported buffer loses telemetry,
                // while the CPU's subsequent access determines whether guest execution faults.
                const word = bc5_mmu.read(address) catch {
                    lcd_dropped += count - n;
                    break;
                };
                lcd_buffer[lcd_len] = @truncate(word orelse BcMem.data[address]);
                lcd_len += 1;
            } else lcd_dropped += 1;
        }
    }
}

fn step(comptime image: Image) void {
    switch (image) {
        .bc5 => {
            observeBc5();
            if (milestones.panic != null) {
                halt_reason = "firmware-panic";
                return;
            }
            if (halt_reason != null) return;
            const before = Bc.core.steps;
            Bc.core.step();
            total_steps += Bc.core.steps - before;
            if (Bc.core.halted) |h| setHalt(h);
            if (BcMem.bus.stop) |h| setHalt(h);
        },
        .avr => {
            const pc = @as(u32, avr_cpu.st.pc) * 2;
            if (pc == (if (handset == .@"9575") @as(u32, 0x105C) else avr_soc.loader.main_addr)) milestones.main = true;
            if (pc == (if (handset == .@"9575") @as(u32, 0xB1E) else avr_soc.loader.idle_addr)) milestones.idle = true;
            avr_cpu.step();
            total_steps += 1;
            if (avr_cpu.stop) |h| setHalt(h);
            if (avr_bus.stop) |h| setHalt(h);
            if (halt_reason == null and avr_dev.st.reset_request != 0)
                halt_reason = "firmware-reset-requested";
        },
        .trx, .ptt => {
            if (trx_model.latch.count() >= 65536) {
                halt_reason = "device-register-limit";
                return;
            }
            const layout = m.layout(m.config);
            if (m.regs.pc == layout.post_init) milestones.main = true;
            if (m.regs.pc == layout.rtos_start[0] or m.regs.pc == layout.rtos_start[1]) milestones.scheduler = true;
            if (m.cpu.step()) |h| setHalt(h);
            total_steps += 1;
        },
    }
}

fn run(steps: u64) void {
    if (halt_reason != null) return;
    refillFuel(steps);
    // Each worker owns one image; select its instruction loop once per request.
    switch (current_image) {
        inline else => |image| runSteps(image, steps),
    }
    flushLog();
}

fn runSteps(comptime image: Image, steps: u64) void {
    for (0..steps) |n| {
        step(image);
        if (n % 1024 == 0) flushLog();
        if (halt_reason != null) break;
    }
}

fn runToIdle(steps: u64) void {
    if (halt_reason != null) return;
    refillFuel(steps);
    for (0..steps) |n| {
        step(.bc5);
        if (n % 1024 == 0) flushLog();
        if (halt_reason != null) break;
        if (Bc.core.cpu.pc == xap.cpu.progAddr(0xB774)) {
            milestones.idle = true;
            break;
        }
    }
    flushLog();
}

fn number(comptime T: type, object: std.json.ObjectMap, key: []const u8, default: ?T) !T {
    const value = object.get(key) orelse return default orelse error.MissingField;
    if (value != .integer) return error.ExpectedInteger;
    return std.math.cast(T, value.integer) orelse error.IntegerOutOfRange;
}

fn request(init: std.process.Init, alloc: std.mem.Allocator, out: *std.Io.Writer, line: []const u8) !void {
    const parsed = try std.json.parseFromSlice(Value, alloc, line, .{ .max_value_len = 65536 });
    defer parsed.deinit();
    if (parsed.value != .object) return error.ExpectedObject;
    const obj = parsed.value.object;
    const op = obj.get("op") orelse return error.MissingOperation;
    if (op != .string) return error.ExpectedOperation;
    if (std.mem.eql(u8, op.string, "run")) {
        const steps = try number(u64, obj, "steps", 100_000);
        if (steps > max_steps) return error.StepLimit;
        run(steps);
    } else if (std.mem.eql(u8, op.string, "idle")) {
        if (current_image != .bc5) return error.Bc5Only;
        const steps = try number(u64, obj, "steps", max_steps);
        if (steps == 0 or steps > max_steps) return error.StepLimit;
        runToIdle(steps);
    } else if (std.mem.eql(u8, op.string, "state")) {
        // Observation does not advance time or access device registers.
    } else if (std.mem.eql(u8, op.string, "reset")) {
        try reset(init);
    } else if (std.mem.eql(u8, op.string, "warm_reset")) {
        if (current_image != .bc5) return error.Bc5Only;
        Bc.warmReset();
        attachBc5Devices();
        resetCounters();
    } else if (std.mem.eql(u8, op.string, "read")) {
        return readMemory(out, try number(u32, obj, "address", null), try number(u32, obj, "count", 1));
    } else if (std.mem.eql(u8, op.string, "write")) {
        const address = try number(u32, obj, "address", null);
        const values = obj.get("values") orelse return error.MissingField;
        if (values != .array or values.array.items.len > max_memory) return error.BadMemoryValues;
        try writeMemory(address, values.array.items);
    } else if (std.mem.eql(u8, op.string, "call")) {
        try call(obj);
    } else if (std.mem.eql(u8, op.string, "pins")) {
        if (current_image != .avr) return error.AvrOnly;
        const port = try number(u4, obj, "port", null);
        if (port >= avr_dev.portCount()) return error.BadPort;
        avr_dev.setPinsIn(port, try number(u8, obj, "value", null));
    } else if (std.mem.eql(u8, op.string, "uart_rx")) {
        if (current_image != .avr) return error.AvrOnly;
        const port = try number(u2, obj, "port", null);
        if (port >= avr_dev.uartCount()) return error.BadPort;
        if (!avr_dev.uartPush(port, try number(u8, obj, "value", null))) return error.UartFull;
    } else if (std.mem.eql(u8, op.string, "uart_tx")) {
        if (current_image != .avr) return error.AvrOnly;
        const port = try number(u2, obj, "port", null);
        if (port >= avr_dev.uartCount()) return error.BadPort;
        return json(out, .{ .value = avr_dev.uartPop(port), .dropped = avr_dev.st.usart[port].out_dropped });
    } else if (std.mem.eql(u8, op.string, "spi")) {
        if (current_image != .avr) return error.AvrOnly;
        return json(out, .{ .value = avr_dev.spiTransfer(try number(u8, obj, "value", null)) });
    } else return error.UnknownOperation;
    try state(out);
}

fn validRange(address: u32, count: usize) bool {
    if (count > max_memory or count > std.math.maxInt(u32) - address) return false;
    const end = address + @as(u32, @intCast(count));
    return switch (current_image) {
        .bc5 => end <= 0x10000,
        .avr => end <= (if (handset == .@"9575") @as(u32, 0x2200) else 0x500),
        .trx, .ptt => m.bytes(address, @intCast(count)) != null,
    };
}

fn readMemory(out: *std.Io.Writer, address: u32, count: u32) !void {
    if (!validRange(address, count)) return error.BadMemoryRange;
    var values: [max_memory]u32 = undefined;
    for (0..count) |n| values[n] = switch (current_image) {
        .bc5 => BcMem.data[address + n],
        .avr => avr_data[address + n],
        .trx, .ptt => m.bytes(address, count).?[n],
    };
    try json(out, .{ .address = address, .unit_bits = if (current_image == .bc5) @as(u8, 16) else 8, .values = values[0..count] });
}

fn writeMemory(address: u32, values: []const Value) !void {
    if (!validRange(address, values.len)) return error.BadMemoryRange;
    // Validate the entire write before mutation, including ROM/MMIO classification.
    for (values, 0..) |v, n| {
        const at = address + @as(u32, @intCast(n));
        const kind = switch (current_image) {
            .bc5 => BcMem.bus.kindOf(at),
            .avr => avr_bus.kindOf(at),
            .trx, .ptt => m.bus.kindOf(at),
        };
        if (kind != .ram and kind != .scratch) return error.RamWriteRequired;
        if (v != .integer or v.integer < 0 or v.integer > (if (current_image == .bc5) @as(i64, 65535) else 255)) return error.BadMemoryValue;
    }
    for (values, 0..) |v, n| switch (current_image) {
        .bc5 => BcMem.data[address + n] = @intCast(v.integer),
        .avr => avr_data[address + n] = @intCast(v.integer),
        .trx, .ptt => m.bytes(address, @intCast(values.len)).?[n] = @intCast(v.integer),
    };
}

fn call(obj: std.json.ObjectMap) !void {
    if (current_image != .bc5) return error.Bc5Only;
    if (halt_reason != null) return error.MachineHalted;
    const entry = try number(u32, obj, "entry", null);
    if (entry % 2 != 0 or entry >= Bc.image.code_words * 2) return error.BadEntry;
    const al = try number(u16, obj, "al", 0);
    const ah = try number(u16, obj, "ah", 0);
    const steps = try number(u64, obj, "steps", 100_000);
    if (steps == 0 or steps > max_probe_steps) return error.StepLimit;
    const stack: []const Value = if (obj.get("stack")) |value| blk: {
        if (value != .array) return error.BadStack;
        break :blk value.array.items;
    } else &.{};
    if (stack.len > 32) return error.BadStack;
    for (stack) |v| if (v != .integer or v.integer < 0 or v.integer > 65535) return error.BadStack;
    const saved = Bc.core;
    // Probes retain guest memory effects; preserve the paused CPU's stack and registers.
    var stack_before: [0x380]u16 = undefined;
    const stack_base = 0xF960;
    @memcpy(&stack_before, BcMem.data[stack_base..][0..stack_before.len]);
    defer @memcpy(BcMem.data[stack_base..][0..stack_before.len], &stack_before);
    Bc.core.cpu.y = 0xFCC0;
    for (stack, 0..) |v, n| BcMem.data[0xFCC0 + n] = @intCast(v.integer);
    Bc.core.cpu.al = al;
    Bc.core.cpu.ah = ah;
    Bc.core.cpu.pc = xap.cpu.progAddr(entry);
    Bc.core.cpu.x = @truncate(xap.cpu.sentinel);
    Bc.core.cpu.xh = @truncate(xap.cpu.sentinel >> 16);
    Bc.core.depth = 0;
    const before = total_steps;
    run(steps);
    const returned = if (Bc.core.halted) |h| h == .returned else false;
    const stack_guard_changed = BcMem.data[stack_base] != stack_before[0];
    const r = Bc.core.cpu;
    var stopped: ?CallStop = null;
    if (!returned or stack_guard_changed) {
        const count = @min(64, BcMem.data.len - @as(usize, r.y));
        var words: [64]u16 = @splat(0);
        @memcpy(words[0..count], BcMem.data[r.y..][0..count]);
        stopped = .{
            .registers = .{ r.ah, r.al, r.x, r.y, r.xh, r.ux, r.uy, r.flags },
            .stack_address = r.y,
            .stack_count = @intCast(count),
            .stack_words = words,
        };
    }
    last_call = .{
        .returned = returned and !stack_guard_changed,
        .al = Bc.core.cpu.al,
        .ah = Bc.core.cpu.ah,
        .steps = total_steps - before,
        .pc = xap.cpu.byteAddr(Bc.core.cpu.pc),
        .program_pc = Bc.core.cpu.pc,
        .stopped = stopped,
    };
    const elapsed = Bc.core.steps - saved.steps;
    const unknown = Bc.core.unknown_flag_uses;
    Bc.core = saved;
    Bc.core.steps += elapsed;
    Bc.core.unknown_flag_uses = unknown;
    if (stack_guard_changed) {
        halt_reason = "probe-stack-guard-changed";
    } else if (returned) {
        halt_reason = null;
        BcMem.bus.stop = null;
    } else if (halt_reason == null) halt_reason = "probe-did-not-return";
}

test "protocol integer validation rejects missing, negative and noninteger arguments" {
    const p = try std.json.parseFromSlice(Value, std.testing.allocator, "{\"negative\":-1,\"float\":1.5,\"valid\":255}", .{});
    defer p.deinit();
    try std.testing.expectError(error.IntegerOutOfRange, number(u8, p.value.object, "negative", null));
    try std.testing.expectError(error.ExpectedInteger, number(u8, p.value.object, "float", null));
    try std.testing.expectError(error.MissingField, number(u8, p.value.object, "absent", null));
    try std.testing.expectEqual(@as(u8, 255), try number(u8, p.value.object, "valid", null));
}

test "memory bounds reject overflow and overlong reads" {
    current_image = .bc5;
    try std.testing.expect(!validRange(0xFFFFFFFF, 1));
    try std.testing.expect(!validRange(0, max_memory + 1));
    try std.testing.expect(!validRange(65535, 2));
    try std.testing.expect(validRange(65535, 1));
}

test {
    _ = @import("mmu.zig");
}
