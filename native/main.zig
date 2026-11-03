//! Process-isolated original-firmware execution. One JSON request and reply per line.
const std = @import("std");
const common = @import("common");
const xap = @import("xap2");
const avr = @import("emu_avr");
const bc5 = @import("bc5");
const avr_soc = @import("avr_soc");
const trx = @import("trx");
const mmu = @import("mmu.zig");
const keypad = @import("keypad.zig");
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
var hardware_strict = false;
var trace_enabled = false;
var trace_buffer: [4096]common.bus.Access = undefined;
var trace_len: usize = 0;
var trace_dropped: u64 = 0;
var external_irq: u4 = 0;
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
var trx_fallback: common.bus.Device = undefined;
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
var serial_cursor: u32 = 0;
var serial_unmodeled: u64 = 0;
var serial_waiting = false;
var serial_peer = false;
var serial_rx_cursor: u32 = 0;
var serial_sequence: u32 = 0;
var serial_dma: ?struct { receive: bool, remaining: u16, in_flight: bool = false } = null;
var gpio_inputs: u16 = 0;
var gpio_reset_count: u64 = 0;
var keypad_model: keypad.Model = .{};
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
    pending: bool = false,
    al: u16,
    ah: u16,
    steps: u64,
    pc: u32,
    program_pc: u32,
    stopped: ?CallStop,
};
var last_call: ?CallResult = null;
const probe_stack_base = 0xF960;
const CallContext = struct {
    saved: xap.cpu.Core,
    stack_before: [0x380]u16,
    before_steps: u64,
    remaining: u64,
};
var call_context: ?CallContext = null;

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
            Bc.hardware_enabled = true;
            try Bc.setAnalog(0, 640); // Virtual GRev board-ID fixture: original callback bin154..168.
            try Bc.init(init.gpa, init.io, std.Io.Dir.cwd(), profile);
            attachBc5Devices();
        },
        .avr => {
            const size: usize = if (handset == .@"9575") 14296 else avr_soc.loader.image_len;
            const flash_size: usize = if (handset == .@"9575") 0x20000 else 0x4000;
            if (firmware.len != size and firmware.len != flash_size) return error.BadAvrImageSize;
            @memset(&avr_prog, 0xFF);
            @memcpy(avr_prog[0..firmware.len], firmware);
            avr_backing[0].mem = avr_data[0..if (handset == .@"9575") @as(usize, 0x2200) else 0x500];
            avr_bus = try avr.cpu.Bus.init(init.gpa, if (handset == .@"9575") &avr_extreme_map else &avr_map, &avr_backing);
            avr_cpu = .{ .data = &avr_data, .prog = &avr_prog, .bus = &avr_bus };
            avr_cpu.program_mask = if (handset == .@"9575") 0xFFFF else avr.cpu.pc_mask;
            avr_dev = .{ .bus = &avr_bus, .open_bus = true, .mega = handset == .@"9575" };
            if (handset == .@"9575") avr_dev.configureFuses(0x77, 0x99, 0xFE, 0xFF);
            avr_dev.reset();
            idleAvrInputs();
            avr_bus.dev = .{ .ctx = &avr_dev, .read = avrRead, .write = avrWrite };
            avr_cpu.sys = avr_dev.sys();
            avr_soc.loader.coldReset(&avr_cpu);
            avr_cpu.st.pc = avr_dev.resetVector();
            if (handset == .@"9575") avr_cpu.st.sp = 0x21FF;
        },
        .trx, .ptt => {
            const expected: usize = if (current_image == .trx) 0x260760 else 0xA7BF8;
            if (firmware.len != expected) return error.BadTrxImageSize;
            @memset(&m.flash, 0xFF);
            const offset: usize = if (current_image == .trx) 0 else 0x400000 - m.flash_base;
            @memcpy(m.flash[offset..][0..firmware.len], firmware);
            try m.reset(init.gpa, if (current_image == .trx) .p1 else .p2, 8);
            trx_model = .{ .gpa = init.gpa, .nwin = 8, .ptt = current_image == .ptt };
            attachTrxDevices();
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
    discardPendingCall();
    total_steps = 0;
    unclassified = 0;
    halt_reason = null;
    milestones = .{};
    lcd_len = 0;
    lcd_dropped = 0;
    serial_cursor = 0;
    serial_unmodeled = 0;
    serial_rx_cursor = 0;
    serial_sequence +%= 1;
    serial_dma = null;
    serial_waiting = false;
    last_call = null;
    model_error = null;
    trace_len = 0;
    trace_dropped = 0;
    external_irq = 0;
    setStrictHardware(hardware_strict);
}

fn setStrictHardware(strict: bool) void {
    hardware_strict = strict;
    switch (current_image) {
        .bc5 => BcMem.bus.strict_unclassified = strict,
        .avr => avr_bus.strict_unclassified = strict,
        .trx, .ptt => m.bus.strict_unclassified = strict,
    }
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
    if (value) |v| return v;
    if (address == 0xFFC2) return gpioPins();
    if (address == 0xFE95) return @intFromBool(serial_waiting);
    if (hardware_strict and !bc5.modeledAccess(@intCast(address), false) and
        !serialAccess(address, false) and !gpioAccess(address, false) and
        !(Bc.hardware_enabled and (bc5.timerIrqAccess(@intCast(address), false) or bc5.analogAccess(@intCast(address), false))))
    {
        hardwareFault(&BcMem.bus, address, false);
        return 0;
    }
    return bc5_fallback.read(bc5_fallback.ctx, address, bits);
}

fn bc5Write(_: *anyopaque, address: u32, bits: u8, value: u64) void {
    const handled = bc5_mmu.write(@intCast(address), @truncate(value)) catch |err| {
        modelFault(address, "write", err);
        return;
    };
    if (handled) return;
    if (hardware_strict and !bc5.modeledAccess(@intCast(address), true) and
        !serialAccess(address, true) and !gpioAccess(address, true) and
        !(Bc.hardware_enabled and (bc5.timerIrqAccess(@intCast(address), true) or bc5.analogAccess(@intCast(address), true))))
        return hardwareFault(&BcMem.bus, address, true);
    const was_reset = gpioResetAsserted();
    const previous_pins = gpioPins();
    bc5_fallback.write(bc5_fallback.ctx, address, bits, value);
    if (address == 0x61 or address == 0x62) {
        keypad_model.writeGpio(Bc.dev.low[0x62], Bc.dev.low[0x61]);
        gpioEdges(previous_pins, gpioPins());
    }
    if (!was_reset and gpioResetAsserted()) {
        gpio_reset_count += 1;
        serial_sequence +%= 1;
        if (serial_dma) |*dma| dma.in_flight = false;
    }
    if (address == 0xFDC0 or address == 0xFE94) serial_cursor = 0;
    if (address == 0xFDC0 or address == 0xFE93) serial_rx_cursor = 0;
    if (address == 0xFDC1 and value != 0) serialTransfer(@truncate(value));
}

fn gpioAccess(address: u32, write: bool) bool {
    return address == 0x61 or address == 0x62 or address == 0xA7 or address == 0xA8 or (address == 0xFFC2 and !write);
}

fn gpioPins() u16 {
    return ((gpio_inputs | keypad_model.inputs()) & ~Bc.dev.low[0x61]) | (Bc.dev.low[0x62] & Bc.dev.low[0x61]);
}

fn gpioEdges(before: u16, after: u16) void {
    const rising = ~before & after & Bc.dev.low[0xA7];
    const falling = before & ~after & Bc.dev.low[0xA8];
    if ((rising | falling) & ~Bc.dev.low[0x61] != 0) Bc.raiseInterrupt(15);
}

fn gpioResetAsserted() bool {
    return Bc.dev.low[0x61] & 0x8000 != 0 and Bc.dev.low[0x62] & 0x8000 == 0;
}

fn serialAccess(address: u32, write: bool) bool {
    if (address == 0xFE95) return !write;
    return (address >= 0xFDBE and address <= 0xFDC5) or address == 0xFE93 or address == 0xFE94;
}

fn serialTransfer(count: u16) void {
    const registers = Bc.dev.serial;
    // Original 39370/3954C and 58B54..58DE0 configure these registers; LCD uses
    // mode3 and the clock/data pin indices 0,1,1 encoded in FDBF (table 2EF0).
    if (registers[0] & 1 == 0) return;
    if (registers[1] & 0x7FFF == 0x440 and serial_peer and
        Bc.dev.low[0x61] & 0x10 != 0 and Bc.dev.low[0x62] & 0x10 == 0 and registers[5] <= 1)
    {
        if (serial_waiting) {
            hardwareFault(&BcMem.bus, 0xFDC1, true);
            return;
        }
        serial_dma = .{ .receive = registers[5] == 1, .remaining = count };
        serial_waiting = true;
        serial_sequence +%= 1;
        return;
    }
    if (registers[2] != 3 or registers[1] & 0x7FFF != 0x420 or registers[5] != 0) {
        serial_unmodeled += 1;
        if (hardware_strict) hardwareFault(&BcMem.bus, 0xFDC1, true);
        return;
    }
    const handle = Bc.dev.ext[0x94];
    for (0..count) |_| {
        if (BcMem.bus.fuel == 0) {
            BcMem.bus.halt(.fuel_exhausted);
            return;
        }
        BcMem.bus.fuel -= 1;
        const value = bc5_mmu.readBuffer(handle, serial_cursor) catch |err| {
            modelFault(0xFDC1, "serial-read", err);
            return;
        };
        serial_cursor +%= 1;
        if (lcd_len < lcd_buffer.len) {
            lcd_buffer[lcd_len] = value;
            lcd_len += 1;
        } else lcd_dropped += 1;
    }
}

fn hardwareFault(bus: anytype, address: u32, write: bool) void {
    if (model_error == null) {
        model_error = .{ .address = address, .operation = if (write) "write" else "read", .reason = "UnmodeledRegister" };
        halt_reason = std.fmt.bufPrint(&halt_buffer, "hardware:UnmodeledRegister@0x{x}", .{address}) catch "hardware-fault";
    }
    bus.halt(.{ .fault = address });
}

fn avrRead(_: *anyopaque, address: u32, _: u8) u64 {
    if (hardware_strict and !avr_dev.modeledAccess(@intCast(address), false)) {
        hardwareFault(&avr_bus, address, false);
        return 0;
    }
    return avr_dev.read(@intCast(address));
}

fn avrWrite(_: *anyopaque, address: u32, _: u8, value: u64) void {
    if (hardware_strict and !avr_dev.modeledAccess(@intCast(address), true))
        return hardwareFault(&avr_bus, address, true);
    avr_dev.write(@intCast(address), @truncate(value));
}

fn attachTrxDevices() void {
    trx_fallback = trx_model.device();
    m.bus.dev = .{ .ctx = &trx_model, .read = trxRead, .write = trxWrite };
}

fn trxRead(_: *anyopaque, address: u32, bits: u8) u64 {
    if (hardware_strict and !trx.devices.modeledAccess(address, false)) {
        hardwareFault(&m.bus, address, false);
        return 0;
    }
    return trx_fallback.read(trx_fallback.ctx, address, bits);
}

fn trxWrite(_: *anyopaque, address: u32, bits: u8, value: u64) void {
    if (hardware_strict and !trx.devices.modeledAccess(address, true))
        return hardwareFault(&m.bus, address, true);
    trx_fallback.write(trx_fallback.ctx, address, bits, value);
}

fn reset(init: std.process.Init) !void {
    switch (current_image) {
        .bc5 => {
            keypad_model = .{};
            gpio_inputs = 0;
            Bc.reset();
            attachBc5Devices();
        },
        .avr => {
            @memset(&avr_data, 0);
            @memset(&avr_prog, 0xFF);
            @memcpy(avr_prog[0..firmware.len], firmware);
            avr_bus.resetRun(std.math.maxInt(u64));
            const fuses = avr_dev.fuses();
            avr_dev = .{ .bus = &avr_bus, .open_bus = true, .mega = handset == .@"9575" };
            avr_dev.configureFuses(fuses.low, fuses.high, fuses.extended, fuses.lock);
            avr_dev.reset();
            idleAvrInputs();
            avr_soc.loader.coldReset(&avr_cpu);
            avr_cpu.st.pc = avr_dev.resetVector();
            if (handset == .@"9575") avr_cpu.st.sp = 0x21FF;
        },
        .trx, .ptt => {
            trx_model.deinit();
            m.deinit();
            @memset(&m.flash, 0xFF);
            const offset: usize = if (current_image == .trx) 0 else 0x400000 - m.flash_base;
            @memcpy(m.flash[offset..][0..firmware.len], firmware);
            try m.reset(init.gpa, if (current_image == .trx) .p1 else .p2, 8);
            trx_model = .{ .gpa = init.gpa, .nwin = 8, .ptt = current_image == .ptt };
            attachTrxDevices();
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

fn idleAvrInputs() void {
    // Released active-low power button; auxiliary PC1/PJ4 low and PD4/PJ5 high.
    if (handset == .@"9575") {
        avr_dev.setPinsIn(8, 0x28);
    } else {
        avr_dev.setPinsIn(2, 1);
        avr_dev.setPinsIn(3, 0x10);
    }
}

fn state(out: *std.Io.Writer) !void {
    var registers: [32]u32 = @splat(0);
    var uart_dropped: [4]u64 = @splat(0);
    if (current_image == .avr) {
        for (&uart_dropped, avr_dev.st.usart) |*lost, uart| lost.* = uart.out_dropped;
    } else if (current_image == .trx or current_image == .ptt) {
        for (&uart_dropped, 0..) |*lost, port| lost.* = trx_model.uartDropped(@intCast(port));
    }
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
    const power_pointer = if (current_image == .bc5) BcMem.data[if (handset == .@"9575") @as(usize, 0xF72F) else 0xF71C] else 0;
    const power_state: ?u16 = if (power_pointer >= 0xA000 and power_pointer < 0xFD00) BcMem.data[power_pointer] else null;
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
        .sleeping = switch (current_image) {
            .avr => avr_cpu.st.sleeping != 0,
            .trx, .ptt => m.cpu.sleeping,
            else => false,
        },
        .power_state = power_state,
        .milestones = milestones,
        .unclassified_accesses = unclassified,
        .lcd_bytes = lcd_numbers[0..lcd_len],
        .lcd_dropped = lcd_dropped,
        .lcd_source = if (current_image == .bc5) "inferred-serial-controller" else @as(?[]const u8, null),
        .serial_unmodeled_transfers = serial_unmodeled,
        .uart_tx_dropped = if (current_image == .avr) uart_dropped[0..avr_dev.uartCount()] else if (current_image == .trx or current_image == .ptt) @as([]u64, &uart_dropped) else null,
        .last_call = last_call,
        .model = "firmware-derived-peripherals",
        .mmu_assumption = if (current_image == .bc5) mmu.assumption else null,
        .flash_assumption = if (current_image == .bc5) bc5.flash_mod.assumption else null,
        .avr_assumption = if (current_image == .avr and handset == .@"9575") "inferred-atmega640-1280-family; unsupported peripherals remain open bus" else null,
        .avr_fuses = if (current_image == .avr) avr_dev.fuses() else @as(?avr_soc.devices.Fuses, null),
        .model_error = model_error,
        .hardware_strict = hardware_strict,
        .bc5_hardware = current_image == .bc5 and Bc.hardware_enabled,
        .board_id_fixture = if (current_image == .bc5) .{ .name = "virtual-grev", .aio0 = Bc.analog_inputs[0] } else null,
        .serial_waiting = serial_waiting,
        .serial_peer = serial_peer,
        .gpio = if (current_image == .bc5) .{
            .pins = gpioPins(),
            .inputs = gpio_inputs,
            .output = Bc.dev.low[0x62],
            .direction = Bc.dev.low[0x61],
            .rising_mask = Bc.dev.low[0xA7],
            .falling_mask = Bc.dev.low[0xA8],
            .irq_mask = Bc.dev.low[0x64],
            .irq_pending = Bc.dev.pending,
            .key_rows = keypad_model.rows,
            .key_columns = keypad_model.inputs(),
            .key_contacts = keypad_model.pressed,
        } else null,
        .trace_enabled = trace_enabled,
        .trace_dropped = trace_dropped,
        .irq_level = if (current_image == .trx or current_image == .ptt) @as(?u4, m.cpu.irl) else null,
    });
    lcd_len = 0;
}

fn setHalt(value: anytype) void {
    if (halt_reason == null) halt_reason = std.fmt.bufPrint(&halt_buffer, "{any}", .{value}) catch "halt";
}

fn collectLog(bus: anytype) void {
    for (bus.log.items) |access| {
        if (bus.kindOf(access.addr) == .unclassified) unclassified += 1;
        if (trace_enabled) {
            if (trace_len < trace_buffer.len) {
                trace_buffer[trace_len] = access;
                trace_len += 1;
            } else trace_dropped += 1;
        }
    }
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
            Bc.tick();
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
            trx_model.tick(1);
            if (trx_model.reset_requested) {
                halt_reason = "firmware-reset-requested";
                return;
            }
            m.cpu.irl = @max(external_irq, trx_model.irqLevel());
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

fn boolean(object: std.json.ObjectMap, key: []const u8) !bool {
    const value = object.get(key) orelse return error.MissingField;
    if (value != .bool) return error.ExpectedBoolean;
    return value.bool;
}

fn request(init: std.process.Init, alloc: std.mem.Allocator, out: *std.Io.Writer, line: []const u8) !void {
    const parsed = try std.json.parseFromSlice(Value, alloc, line, .{ .max_value_len = 65536 });
    defer parsed.deinit();
    if (parsed.value != .object) return error.ExpectedObject;
    const obj = parsed.value.object;
    const op = obj.get("op") orelse return error.MissingOperation;
    if (op != .string) return error.ExpectedOperation;
    if (std.mem.eql(u8, op.string, "run")) {
        if (callPending()) return error.CallPending;
        const steps = try number(u64, obj, "steps", 100_000);
        if (steps > max_steps) return error.StepLimit;
        run(steps);
    } else if (std.mem.eql(u8, op.string, "idle")) {
        if (callPending()) return error.CallPending;
        if (current_image != .bc5) return error.Bc5Only;
        const steps = try number(u64, obj, "steps", max_steps);
        if (steps == 0 or steps > max_steps) return error.StepLimit;
        runToIdle(steps);
    } else if (std.mem.eql(u8, op.string, "state")) {
        // Observation does not advance time or access device registers.
    } else if (std.mem.eql(u8, op.string, "hardware")) {
        if (!obj.contains("strict") and !obj.contains("enabled") and !obj.contains("serial_peer")) return error.MissingField;
        const strict = if (obj.contains("strict")) try boolean(obj, "strict") else hardware_strict;
        const enabled = if (obj.contains("enabled")) try boolean(obj, "enabled") else Bc.hardware_enabled;
        const peer = if (obj.contains("serial_peer")) try boolean(obj, "serial_peer") else serial_peer;
        if ((obj.contains("enabled") or obj.contains("serial_peer")) and current_image != .bc5) return error.Bc5Only;
        if (callPending()) return error.CallPending;
        setStrictHardware(strict);
        if (current_image == .bc5) {
            serial_peer = peer;
            if (enabled != Bc.hardware_enabled) {
                Bc.hardware_enabled = enabled;
                Bc.warmReset();
                attachBc5Devices();
                resetCounters();
            }
        }
    } else if (std.mem.eql(u8, op.string, "trace")) {
        const enabled = if (obj.contains("enabled")) try boolean(obj, "enabled") else trace_enabled;
        flushLog();
        trace_enabled = enabled;
        try json(out, .{ .enabled = trace_enabled, .accesses = trace_buffer[0..trace_len], .dropped = trace_dropped });
        trace_len = 0;
        return;
    } else if (std.mem.eql(u8, op.string, "reset")) {
        try reset(init);
    } else if (std.mem.eql(u8, op.string, "warm_reset")) {
        if (current_image == .bc5) {
            Bc.warmReset();
            attachBc5Devices();
        } else if (current_image == .avr) {
            const ee = avr_dev.st.ee;
            const analog = avr_dev.st.analog;
            const pins = avr_dev.st.pins_in;
            avr_dev.reset();
            avr_dev.st.ee = ee;
            avr_dev.st.analog = analog;
            avr_dev.st.pins_in = pins;
            avr_bus.resetRun(std.math.maxInt(u64));
            avr_soc.loader.coldReset(&avr_cpu);
            avr_cpu.st.pc = avr_dev.resetVector();
            if (handset == .@"9575") avr_cpu.st.sp = 0x21FF;
        } else return error.ResetUnavailable;
        resetCounters();
    } else if (std.mem.eql(u8, op.string, "read")) {
        return readMemory(out, try number(u32, obj, "address", null), try number(u32, obj, "count", 1));
    } else if (std.mem.eql(u8, op.string, "program_read")) {
        if (current_image != .avr) return error.AvrOnly;
        const address = try number(u32, obj, "address", null);
        const count = try number(u32, obj, "count", 1);
        const limit: u32 = if (handset == .@"9575") 0x20000 else 0x4000;
        if (count > max_memory or address > limit or count > limit - address) return error.BadMemoryRange;
        var values: [max_memory]u16 = undefined;
        for (0..count) |n| values[n] = avr_prog[address + n];
        return json(out, .{ .address = address, .unit_bits = 8, .values = values[0..count] });
    } else if (std.mem.eql(u8, op.string, "fuses")) {
        if (current_image != .avr) return error.AvrOnly;
        if (obj.contains("low") or obj.contains("high") or obj.contains("extended") or obj.contains("lock")) {
            const low = try number(u8, obj, "low", null);
            const high = try number(u8, obj, "high", null);
            const extended = try number(u8, obj, "extended", null);
            const lock = try number(u8, obj, "lock", null);
            avr_dev.configureFuses(low, high, extended, lock);
        }
        return json(out, .{ .fuses = avr_dev.fuses(), .boot_start = avr_dev.bootStart(), .reset_vector = avr_dev.resetVector() });
    } else if (std.mem.eql(u8, op.string, "write")) {
        if (callPending()) return error.CallPending;
        const address = try number(u32, obj, "address", null);
        const values = obj.get("values") orelse return error.MissingField;
        if (values != .array or values.array.items.len > max_memory) return error.BadMemoryValues;
        try writeMemory(address, values.array.items);
    } else if (std.mem.eql(u8, op.string, "call")) {
        try call(obj);
    } else if (std.mem.eql(u8, op.string, "call_resume")) {
        try callResume(obj);
    } else if (std.mem.eql(u8, op.string, "serial")) {
        if (current_image != .bc5) return error.Bc5Only;
        return serial(out, obj);
    } else if (std.mem.eql(u8, op.string, "pins")) {
        if (current_image == .bc5) {
            const value = try number(u16, obj, "value", null);
            const mask = try number(u16, obj, "mask", 0xFFFF);
            const before = gpioPins();
            gpio_inputs = (gpio_inputs & ~mask) | (value & mask);
            gpioEdges(before, gpioPins());
        } else if (current_image == .avr) {
            const port = try number(u4, obj, "port", null);
            if (port >= avr_dev.portCount()) return error.BadPort;
            avr_dev.setPinsIn(port, try number(u8, obj, "value", null));
        } else return error.PinsUnavailable;
    } else if (std.mem.eql(u8, op.string, "key")) {
        if (current_image != .bc5) return error.Bc5Only;
        const code = try number(u16, obj, "code", null);
        const pressed = try boolean(obj, "pressed");
        const before = gpioPins();
        try keypad_model.setKey(code, pressed);
        gpioEdges(before, gpioPins());
    } else if (std.mem.eql(u8, op.string, "pin_state")) {
        if (current_image != .avr) return error.AvrOnly;
        var pins: [11]u16 = undefined;
        var inputs: [11]u16 = undefined;
        for (pins[0..avr_dev.portCount()], 0..) |*pin, index| pin.* = avr_dev.pin(@intCast(index));
        for (inputs[0..avr_dev.portCount()], 0..) |*pin, index| pin.* = avr_dev.st.pins_in[index];
        return json(out, .{ .pins = pins[0..avr_dev.portCount()], .inputs = inputs[0..avr_dev.portCount()] });
    } else if (std.mem.eql(u8, op.string, "uart_rx")) {
        const port = try uartPort(obj);
        if (!uartPush(port, try number(u8, obj, "value", null))) return error.UartFull;
    } else if (std.mem.eql(u8, op.string, "uart_tx")) {
        const port = try uartPort(obj);
        return json(out, .{ .value = uartPop(port), .dropped = uartDropped(port) });
    } else if (std.mem.eql(u8, op.string, "uart_io")) {
        return uartIo(out, obj);
    } else if (std.mem.eql(u8, op.string, "spi")) {
        if (current_image != .avr) return error.AvrOnly;
        return json(out, .{ .value = avr_dev.spiTransfer(try number(u8, obj, "value", null)) });
    } else if (std.mem.eql(u8, op.string, "adc")) {
        const channel = try number(u4, obj, "channel", null);
        const value = try number(u10, obj, "value", null);
        switch (current_image) {
            .bc5 => try Bc.setAnalog(channel, value),
            .avr => {
                if (channel >= avr_dev.analogCount()) return error.BadChannel;
                avr_dev.setAnalog(channel, value);
            },
            else => return error.AnalogUnavailable,
        }
    } else if (std.mem.eql(u8, op.string, "comparator")) {
        if (current_image != .avr) return error.AvrOnly;
        const positive = try number(u10, obj, "positive", null);
        const negative = try number(u10, obj, "negative", null);
        const bandgap = if (obj.contains("bandgap")) try number(u10, obj, "bandgap", null) else null;
        avr_dev.setComparatorInputs(positive, negative);
        if (bandgap) |value| avr_dev.setBandgap(value);
    } else if (std.mem.eql(u8, op.string, "async_clock")) {
        if (current_image != .avr) return error.AvrOnly;
        const ticks = try number(u32, obj, "ticks", null);
        if (ticks > max_steps) return error.StepLimit;
        avr_dev.asyncTick(ticks);
    } else if (std.mem.eql(u8, op.string, "twi")) {
        if (current_image != .avr) return error.AvrOnly;
        return twi(out, obj);
    } else if (std.mem.eql(u8, op.string, "irq")) {
        if (current_image == .bc5) {
            Bc.raiseInterrupt(try number(u4, obj, "source", null));
        } else if (current_image == .trx or current_image == .ptt) {
            external_irq = try number(u4, obj, "level", null);
            m.cpu.irl = @max(external_irq, trx_model.irqLevel());
        } else return error.InterruptUnavailable;
    } else return error.UnknownOperation;
    try state(out);
}

fn twi(out: *std.Io.Writer, obj: std.json.ObjectMap) !void {
    const action = obj.get("action") orelse return error.MissingField;
    if (action != .string) return error.ExpectedOperation;
    if (std.mem.eql(u8, action.string, "reply")) {
        const reply = obj.get("reply") orelse return error.MissingField;
        if (reply != .string) return error.ExpectedOperation;
        const kind = std.meta.stringToEnum(avr_soc.devices.TwiReply, reply.string) orelse return error.BadTwiReply;
        return json(out, .{ .accepted = avr_dev.twiReply(kind, try number(u8, obj, "value", 0xFF)) });
    } else if (std.mem.eql(u8, action.string, "address")) {
        const address = try number(u7, obj, "address", null);
        const read_mode = try boolean(obj, "read");
        return json(out, .{ .accepted = avr_dev.twiAddress(address, read_mode) });
    } else if (std.mem.eql(u8, action.string, "receive")) {
        return json(out, .{ .accepted = avr_dev.twiReceive(try number(u8, obj, "value", null)) });
    } else if (std.mem.eql(u8, action.string, "transmit")) {
        return json(out, .{ .value = avr_dev.twiTransmit(try boolean(obj, "ack")) });
    } else if (std.mem.eql(u8, action.string, "stop")) {
        return json(out, .{ .accepted = avr_dev.twiStop() });
    } else if (std.mem.eql(u8, action.string, "events")) {
        var events: [255]avr_soc.devices.TwiEvent = undefined;
        var count: usize = 0;
        while (count < events.len) {
            events[count] = avr_dev.twiPop() orelse break;
            count += 1;
        }
        return json(out, .{ .events = events[0..count], .dropped = avr_dev.st.twi.out_dropped });
    }
    return error.BadTwiAction;
}

fn serial(out: *std.Io.Writer, obj: std.json.ObjectMap) !void {
    const received = if (obj.contains("received")) try number(u8, obj, "received", null) else null;
    const sequence = if (received != null) try number(u32, obj, "sequence", null) else null;
    if (received) |value| {
        if (sequence.? == serial_sequence) {
            if (serial_dma) |*dma| {
                if (dma.in_flight) {
                    if (dma.receive) {
                        bc5_mmu.writeBuffer(Bc.dev.ext[0x93], serial_rx_cursor, value) catch |err| {
                            modelFault(0xFDC1, "serial-write", err);
                            if (callPending()) continueCall(0);
                            return state(out);
                        };
                        serial_rx_cursor +%= 1;
                    } else serial_cursor +%= 1;
                    dma.remaining -= 1;
                    dma.in_flight = false;
                    if (dma.remaining == 0) {
                        serial_dma = null;
                        serial_waiting = false;
                    }
                }
            }
        }
    }
    var value: ?u8 = null;
    if (!gpioResetAsserted()) {
        if (serial_dma) |*dma| {
            if (!dma.in_flight) {
                value = if (dma.receive) 0 else bc5_mmu.readBuffer(Bc.dev.ext[0x94], serial_cursor) catch |err| {
                    modelFault(0xFDC1, "serial-read", err);
                    if (callPending()) continueCall(0);
                    return state(out);
                };
                serial_sequence +%= 1;
                dma.in_flight = true;
            }
        }
    }
    try json(out, .{ .value = value, .sequence = serial_sequence, .active = serial_waiting, .remaining = if (serial_dma) |dma| dma.remaining else @as(u16, 0), .gpio = .{ .output = Bc.dev.low[0x62], .direction = Bc.dev.low[0x61], .reset_count = gpio_reset_count } });
}

fn uartPort(obj: std.json.ObjectMap) !u2 {
    if (current_image == .bc5) return error.UartUnavailable;
    const port = try number(u2, obj, "port", null);
    if (current_image == .avr and port >= avr_dev.uartCount()) return error.BadPort;
    return port;
}

fn uartPush(port: u2, value: u8) bool {
    return if (current_image == .avr) avr_dev.uartPush(port, value) else trx_model.uartPush(port, value);
}

fn uartPop(port: u2) ?u8 {
    return if (current_image == .avr) avr_dev.uartPop(port) else trx_model.uartPop(port);
}

fn uartDropped(port: u2) u64 {
    return if (current_image == .avr) avr_dev.st.usart[port].out_dropped else trx_model.uartDropped(port);
}

fn uartIo(out: *std.Io.Writer, obj: std.json.ObjectMap) !void {
    const port = try uartPort(obj);
    const tx_limit = try number(u8, obj, "tx_limit", 255);
    var rx: [255]u8 = undefined;
    var count: usize = 0;
    if (obj.get("rx")) |value| {
        if (value != .array or value.array.items.len > rx.len) return error.BadUartValues;
        for (value.array.items, 0..) |v, index| {
            if (v != .integer) return error.ExpectedInteger;
            rx[index] = std.math.cast(u8, v.integer) orelse return error.IntegerOutOfRange;
        }
        count = value.array.items.len;
    }
    var accepted: usize = 0;
    for (rx[0..count]) |value| {
        if (!uartPush(port, value)) break;
        accepted += 1;
    }
    var tx: [255]u16 = undefined;
    var sent: usize = 0;
    while (sent < tx_limit) {
        tx[sent] = uartPop(port) orelse break;
        sent += 1;
    }
    try json(out, .{ .accepted = accepted, .values = tx[0..sent], .dropped = uartDropped(port) });
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

fn callPending() bool {
    return call_context != null;
}

fn discardPendingCall() void {
    call_context = null;
}

fn call(obj: std.json.ObjectMap) !void {
    if (current_image != .bc5) return error.Bc5Only;
    if (callPending()) return error.CallPending;
    if (halt_reason != null) return error.MachineHalted;
    const entry = try number(u32, obj, "entry", null);
    if (entry % 2 != 0 or entry >= Bc.image.code_words * 2) return error.BadEntry;
    const al = try number(u16, obj, "al", 0);
    const ah = try number(u16, obj, "ah", 0);
    const steps = try number(u64, obj, "steps", 100_000);
    if (steps == 0 or steps > max_probe_steps) return error.StepLimit;
    const quantum = try number(u64, obj, "quantum", steps);
    if (quantum == 0 or quantum > max_probe_steps) return error.StepLimit;
    const stack: []const Value = if (obj.get("stack")) |value| blk: {
        if (value != .array) return error.BadStack;
        break :blk value.array.items;
    } else &.{};
    if (stack.len > 32) return error.BadStack;
    for (stack) |v| if (v != .integer or v.integer < 0 or v.integer > 65535) return error.BadStack;
    var probe_y: u16 = 0xFCC0;
    if (Bc.core.banked_interrupts and Bc.core.cpu.flags & 0x10 != 0) {
        // The original wrapper saves X/UY below the CPU's 33-word interrupt frame.
        const separation: u16 = @intCast(35 + stack.len);
        if (Bc.core.cpu.uy <= probe_stack_base + separation) return error.BadProbeStack;
        probe_y = @min(probe_y, Bc.core.cpu.uy - separation);
    }
    call_context = .{ .saved = Bc.core, .stack_before = undefined, .before_steps = total_steps, .remaining = steps };
    @memcpy(&call_context.?.stack_before, BcMem.data[probe_stack_base..][0..0x380]);
    Bc.core.cpu.y = probe_y;
    for (stack, 0..) |v, n| BcMem.data[probe_y + n] = @intCast(v.integer);
    Bc.core.cpu.al = al;
    Bc.core.cpu.ah = ah;
    Bc.core.cpu.pc = xap.cpu.progAddr(entry);
    Bc.core.cpu.x = @truncate(xap.cpu.sentinel);
    Bc.core.cpu.xh = @truncate(xap.cpu.sentinel >> 16);
    Bc.core.depth = 0;
    refillFuel(steps);
    continueCall(@min(steps, quantum));
}

fn callResume(obj: std.json.ObjectMap) !void {
    if (current_image != .bc5) return error.Bc5Only;
    const context = if (call_context) |*active| active else return error.NoPendingCall;
    if (halt_reason != null) return error.MachineHalted;
    const steps = try number(u64, obj, "steps", context.remaining);
    if (steps == 0 or steps > max_probe_steps) return error.StepLimit;
    continueCall(@min(steps, context.remaining));
}

fn continueCall(steps: u64) void {
    const context = &call_context.?;
    var executed: u64 = 0;
    while (executed < steps and context.remaining > 0 and halt_reason == null and !serial_waiting) : (executed += 1) {
        step(.bc5);
        context.remaining -= 1;
        if (executed % 1024 == 0) flushLog();
    }
    flushLog();
    const returned = if (Bc.core.halted) |h| h == .returned else false;
    const stack_guard_changed = BcMem.data[probe_stack_base] != context.stack_before[0];
    const pending = !returned and !stack_guard_changed and halt_reason == null and context.remaining != 0;
    const r = Bc.core.cpu;
    var stopped: ?CallStop = null;
    if (!pending and (!returned or stack_guard_changed)) {
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
        .pending = pending,
        .al = r.al,
        .ah = r.ah,
        .steps = total_steps - context.before_steps,
        .pc = xap.cpu.byteAddr(r.pc),
        .program_pc = r.pc,
        .stopped = stopped,
    };
    if (pending) return;
    const elapsed = Bc.core.steps - context.saved.steps;
    const unknown = Bc.core.unknown_flag_uses;
    @memcpy(BcMem.data[probe_stack_base..][0..context.stack_before.len], &context.stack_before);
    Bc.core = context.saved;
    Bc.core.steps += elapsed;
    Bc.core.unknown_flag_uses = unknown;
    call_context = null;
    if (stack_guard_changed) {
        halt_reason = "probe-stack-guard-changed";
    } else if (returned) {
        halt_reason = null;
        BcMem.bus.stop = null;
    } else if (halt_reason == null) halt_reason = "probe-did-not-return";
}

const CallTest = struct {
    segments: [1]xap.cpu.Segment = undefined,
    backing: [1]common.bus.Backing(u16) = undefined,
    const ranges = [_]common.bus.Range{
        .{ .lo = 0, .hi = 0xFF90, .kind = .ram },
        .{ .lo = 0xFF91, .hi = 0xFF91, .kind = .mmio },
        .{ .lo = 0xFF92, .hi = 0xFFFF, .kind = .ram },
    };

    fn init(t: *CallTest, code: []const u16) !void {
        @memset(&BcMem.data, 0);
        t.backing = .{.{ .base = 0, .mem = &BcMem.data }};
        BcMem.bus = try bc5.Bus.init(std.testing.allocator, &ranges, &t.backing);
        BcMem.bus.dev = .{ .ctx = &serial_waiting, .read = read, .write = write };
        t.segments = .{.{ .base = xap.cpu.progAddr(0x100), .words = code }};
        Bc.core = .{ .bus = &BcMem.bus, .code = &t.segments };
        Bc.core.cpu.pc = xap.cpu.progAddr(0);
        Bc.core.cpu.y = 0xA200;
        Bc.dev = .{};
        Bc.hardware_enabled = false;
        current_image = .bc5;
        total_steps = 0;
        halt_reason = null;
        serial_waiting = false;
        milestones = .{};
        last_call = null;
        discardPendingCall();
    }

    fn deinit(_: *CallTest) void {
        discardPendingCall();
        serial_waiting = false;
        BcMem.bus.deinit();
    }

    fn read(_: *anyopaque, address: u32, _: u8) u64 {
        return BcMem.data[address];
    }

    fn write(ctx: *anyopaque, address: u32, _: u8, value: u64) void {
        const waiting: *bool = @ptrCast(@alignCast(ctx));
        BcMem.data[address] = @truncate(value);
        waiting.* = true;
    }
};

test "banked probes keep all stack arguments below a pending interrupt frame" {
    for ([_]usize{ 3, 32 }) |count| {
        var rig: CallTest = .{};
        const words = [_]u16{ 0x0014, (@as(u16, @intCast(count - 1)) << 8) | 0x17, 0x00E2, 0x0004, 0xDF0D };
        try rig.init(&words);
        defer rig.deinit();
        Bc.core.banked_interrupts = true;
        Bc.core.cpu.flags = 0x10;
        Bc.core.cpu.uy = 0xFCE0;
        var arguments = std.json.Array.init(std.testing.allocator);
        defer arguments.deinit();
        for (0..count) |n| try arguments.append(.{ .integer = @intCast(0x1100 + n) });
        var probe_input = try std.json.ObjectMap.init(std.testing.allocator, &.{ "entry", "steps", "quantum", "stack" }, &.{ .{ .integer = 0x100 }, .{ .integer = 100 }, .{ .integer = 1 }, .{ .array = arguments } });
        defer probe_input.deinit(std.testing.allocator);
        const saved = Bc.core.cpu;
        try call(probe_input);
        try std.testing.expect(callPending());
        try std.testing.expect(Bc.core.interrupt(xap.cpu.progAddr(0x104)));
        continueCall(100);
        try std.testing.expect(last_call.?.returned);
        try std.testing.expectEqual(@as(u16, @intCast(0x1100 + count - 1)), last_call.?.al);
        try std.testing.expectEqual(saved, Bc.core.cpu);
        Bc.core.cpu.uy = probe_stack_base + @as(u16, @intCast(35 + count));
        try std.testing.expectError(error.BadProbeStack, call(probe_input));
        try std.testing.expect(!callPending());
    }
}

test "BC5 probe yields for serial service and restores paused registers/stack only after return" {
    var rig: CallTest = .{};
    try rig.init(&.{ 0x0714, 0x9125, 0x0914, 0x00E2 }); // ld AL,7; st AL,@FF91; ld AL,9; rts
    defer rig.deinit();
    BcMem.data[0xFCC0] = 0xBEEF;
    const saved = Bc.core.cpu;
    const input = try std.json.parseFromSlice(Value, std.testing.allocator, "{\"entry\":256,\"stack\":[4660],\"steps\":10}", .{});
    defer input.deinit();
    const continuation = try std.json.parseFromSlice(Value, std.testing.allocator, "{}", .{});
    defer continuation.deinit();
    try call(input.value.object);
    try std.testing.expect(callPending());
    try std.testing.expect(last_call.?.pending);
    try std.testing.expect(!last_call.?.returned);
    try std.testing.expectEqual(@as(?[]const u8, null), halt_reason);
    try std.testing.expectEqual(@as(u64, 2), last_call.?.steps);
    try std.testing.expectEqual(@as(u16, 0xFCC0), Bc.core.cpu.y);
    try std.testing.expectEqual(@as(u16, 0x1234), BcMem.data[0xFCC0]);
    try std.testing.expectError(error.CallPending, call(input.value.object));
    try callResume(continuation.value.object); // still waiting: no guest time or budget is consumed
    try std.testing.expectEqual(@as(u64, 2), last_call.?.steps);
    serial_waiting = false;
    try callResume(continuation.value.object);
    try std.testing.expect(!callPending());
    try std.testing.expect(last_call.?.returned);
    try std.testing.expect(!last_call.?.pending);
    try std.testing.expectEqual(@as(u16, 9), last_call.?.al);
    try std.testing.expectEqual(@as(u64, 4), last_call.?.steps);
    try std.testing.expectEqual(saved, Bc.core.cpu);
    try std.testing.expectEqual(@as(u16, 0xBEEF), BcMem.data[0xFCC0]);
    try std.testing.expectEqual(@as(u16, 7), BcMem.data[0xFF91]);
    try std.testing.expectError(error.NoPendingCall, callResume(continuation.value.object));
}

test "resuming a yielded probe cannot extend its original cumulative instruction budget" {
    var rig: CallTest = .{};
    try rig.init(&.{ 0x0714, 0x9125, 0x00E0 }); // ld AL,7; serial write; infinite branch
    defer rig.deinit();
    const saved = Bc.core.cpu;
    const input = try std.json.parseFromSlice(Value, std.testing.allocator, "{\"entry\":256,\"steps\":5}", .{});
    defer input.deinit();
    const continuation = try std.json.parseFromSlice(Value, std.testing.allocator, "{\"steps\":100000000}", .{});
    defer continuation.deinit();
    try call(input.value.object);
    try std.testing.expect(callPending());
    serial_waiting = false;
    try callResume(continuation.value.object);
    try std.testing.expect(!callPending());
    try std.testing.expect(!last_call.?.pending);
    try std.testing.expect(!last_call.?.returned);
    try std.testing.expectEqual(@as(u64, 5), last_call.?.steps);
    try std.testing.expectEqualStrings("probe-did-not-return", halt_reason.?);
    try std.testing.expectEqual(saved, Bc.core.cpu);
}

test "a yielded probe preserves remaining budget across chunks and restores after stack guard failure" {
    var rig: CallTest = .{};
    try rig.init(&.{ 0x0714, 0x9125, 0x0914, 0x00E2 });
    defer rig.deinit();
    const saved = Bc.core.cpu;
    BcMem.data[probe_stack_base] = 0xA55A;
    const input = try std.json.parseFromSlice(Value, std.testing.allocator, "{\"entry\":256,\"steps\":10}", .{});
    defer input.deinit();
    const chunk = try std.json.parseFromSlice(Value, std.testing.allocator, "{\"steps\":1}", .{});
    defer chunk.deinit();
    try call(input.value.object);
    serial_waiting = false;
    try callResume(chunk.value.object);
    try std.testing.expect(callPending());
    try std.testing.expectEqual(@as(u64, 3), last_call.?.steps);
    BcMem.data[probe_stack_base] = 0; // a guest/device effect between chunks invalidates this probe
    try callResume(chunk.value.object);
    try std.testing.expect(!callPending());
    try std.testing.expect(!last_call.?.returned);
    try std.testing.expectEqualStrings("probe-stack-guard-changed", halt_reason.?);
    try std.testing.expectEqual(saved, Bc.core.cpu);
    try std.testing.expectEqual(@as(u16, 0xA55A), BcMem.data[probe_stack_base]);
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
    _ = @import("keypad.zig");
}
