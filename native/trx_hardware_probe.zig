//! Optional original-image driver regressions. No original bytes, hooks or translated routines.
const std = @import("std");
const trx = @import("trx");
const sparc = @import("sparc");
const m = trx.machine;

const Profile = struct {
    config: m.Config,
    flush: u32,
    cached_byte: u32,
    timer_init: u32,
    timer_isr: u32,
    timer_ticks: u32,
    clock_hz: u32,
    reset: u32,
};

const profiles = [_]Profile{
    .{ .config = .p1, .flush = 0x34418, .cached_byte = 0x400A_6020, .timer_init = 0x13988, .timer_isr = 0x12DA4, .timer_ticks = 0x400B_33D4, .clock_hz = 700000, .reset = 0x37950 },
    .{ .config = .p2, .flush = 0x7002_F1AC, .cached_byte = 0x7006_0588, .timer_init = 0x4027B4, .timer_isr = 0x401CC4, .timer_ticks = 0x7003_A278, .clock_hz = 2800000, .reset = 0x423D2C },
};

var aggregate_dispatches: u2 = 0;

fn enter(entry: u32, args: []const u32, p: Profile) void {
    m.regs = .{ .pc = entry, .npc = entry + 4, .psr = sparc.cpu.psr_bits.s | sparc.cpu.psr_bits.et | sparc.cpu.psr_bits.pil, .tbr = 0x7000_1000 };
    m.cpu.pending_call = null;
    m.cpu.set(14, if (p.config == .p1) 0x400C_0000 else 0x400B_0000);
    m.cpu.set(15, 0x3FFF_FFF8);
    for (args, 8..) |arg, reg| m.cpu.set(@intCast(reg), arg);
    m.bus.resetRun(4_000_000);
}

fn execute(devices: *trx.devices.Model) !enum { returned, reset } {
    for (0..1_000_000) |_| {
        if (m.regs.pc == 0x4000_0000) return .returned;
        if (m.regs.pc == 0x347E8) aggregate_dispatches |= 1;
        if (m.regs.pc == 0x348F4) aggregate_dispatches |= 2;
        devices.tick(1);
        m.cpu.irl = devices.irqLevel();
        if (devices.reset_requested) return .reset;
        if (m.cpu.step()) |e| {
            std.debug.print("original driver stopped {any}, PC=0x{x}\n", .{ e, m.regs.pc });
            return error.GuestStopped;
        }
    }
    return error.InstructionBudgetExceeded;
}

fn readWord(address: u32) u32 {
    return std.mem.readInt(u32, m.bytes(address, 4).?[0..4], .big);
}

fn check(init: std.process.Init, p: Profile) !void {
    try m.reset(init.gpa, p.config, 8);
    defer m.deinit();
    m.materialize(p.config);
    var devices: trx.devices.Model = .{ .gpa = init.gpa, .nwin = 8, .ptt = p.config == .p2 };
    defer devices.deinit();
    m.bus.dev = devices.device();

    for ("ABC") |byte| try std.testing.expect(devices.uartPush(1, byte));
    enter(p.flush, &.{1}, p);
    try std.testing.expectEqual(.returned, try execute(&devices));
    try std.testing.expectEqual(devices.uarts[1].rx.head, devices.uarts[1].rx.tail);
    try std.testing.expectEqual(@as(u32, 0xFFFF_FFFF), readWord(p.cached_byte));

    if (p.config == .p1) {
        @memcpy(m.bytes(0x4000_0100, 3).?, "XYZ");
        std.mem.writeInt(u32, m.bytes(0x4000_024C, 4).?[0..4], 2, .big);
        enter(0x34CD0, &.{ 0x4000_0100, 1, 3, 0x4000_0200 }, p);
        try std.testing.expectEqual(.returned, try execute(&devices));
        try std.testing.expectEqual(@as(u32, 3), m.cpu.get(8));
        for ("XYZ") |byte| try std.testing.expectEqual(@as(?u8, byte), devices.uartPop(2));
        try std.testing.expectEqual(@as(?u8, null), devices.uartPop(2));

        const d = devices.device();
        // Original initialization uses 0x52 for an absent deferred callback; no host handler runs.
        for (0..12) |index|
            std.mem.writeInt(u32, m.bytes(0x400A_5FEC + @as(u32, @intCast(index)) * 4, 4).?[0..4], 0x52, .big);
        d.write(d.ctx, 0x8000_0128, 32, 0x68);
        d.write(d.ctx, 0x8000_1704, 32, 0xC00);
        d.write(d.ctx, 0x8000_1604, 32, 0xC00);
        try std.testing.expectEqual(@as(u4, 8), devices.irqLevel());
        aggregate_dispatches = 0;
        enter(0xDCE64, &.{}, p);
        try std.testing.expectEqual(.returned, try execute(&devices));
        try std.testing.expectEqual(@as(u2, 3), aggregate_dispatches);
        try std.testing.expectEqual(@as(u4, 0), devices.irqLevel());
        try std.testing.expectEqual(@as(u64, 0x0C0C), d.read(d.ctx, 0x8000_1310, 32));
        for ([_]u32{ 2, 3 }) |port| {
            enter(0x33D68, &.{port}, p); // original TX-interrupt mask routine
            try std.testing.expectEqual(.returned, try execute(&devices));
        }
        try std.testing.expectEqual(@as(u64, 0), d.read(d.ctx, 0x8000_1318, 32));
        d.write(d.ctx, 0x8000_1704, 32, 0x7000);
        d.write(d.ctx, 0x8000_1604, 32, 0x7000);
        try std.testing.expect(devices.uartPush(2, 'R'));
        try std.testing.expect(devices.uartPush(3, 'S'));
        aggregate_dispatches = 0;
        enter(0xDCE64, &.{}, p);
        try std.testing.expectEqual(.returned, try execute(&devices));
        try std.testing.expectEqual(@as(u2, 3), aggregate_dispatches);
        try std.testing.expectEqual(@as(u4, 0), devices.irqLevel());
        try std.testing.expectEqual(@as(u64, 0x8080), d.read(d.ctx, 0x8000_1310, 32));
        for ([_]u32{ 2, 3 }) |port| {
            enter(p.flush, &.{port}, p);
            try std.testing.expectEqual(.returned, try execute(&devices));
        }
        try std.testing.expectEqual(@as(u64, 0), d.read(d.ctx, 0x8000_1318, 32));
        std.debug.print("p1: original aggregate UART2/3 IRQ dispatch, masking and FIFO drain passed\n", .{});
    }

    enter(p.timer_init, &.{100}, p);
    try std.testing.expectEqual(.returned, try execute(&devices));
    try std.testing.expectEqual(p.clock_hz / 100, devices.timers[0].reload);
    try std.testing.expectEqual(@as(u32, 0x44), devices.irq_config[12]);
    // The original tick handler, with OS globals left in their unstarted state, must acknowledge
    // the actual timer event and increment the actual OS tick count through original instructions.
    devices.tick((@as(u64, devices.timers[0].reload) + 1) * (@as(u64, devices.scaler_reload) + 1));
    try std.testing.expectEqual(@as(u4, 4), devices.irqLevel());
    const before = readWord(p.timer_ticks);
    enter(p.timer_isr, &.{}, p);
    try std.testing.expectEqual(.returned, try execute(&devices));
    try std.testing.expectEqual(before + 1, readWord(p.timer_ticks));
    try std.testing.expectEqual(@as(u4, 0), devices.irqLevel());

    enter(p.reset, &.{}, p);
    try std.testing.expectEqual(.reset, try execute(&devices));
    try std.testing.expect(devices.reset_requested);
    std.debug.print("{s}: original UART drain, timer initialization/ISR and watchdog reset passed\n", .{@tagName(p.config)});
}

fn boot(init: std.process.Init, p: Profile) !void {
    try m.reset(init.gpa, p.config, 8);
    defer m.deinit();
    var devices: trx.devices.Model = .{ .gpa = init.gpa, .nwin = 8, .ptt = p.config == .p2 };
    defer devices.deinit();
    m.bus.dev = devices.device();
    var flash: trx.devices.Flash = .{ .mem = &m.flash, .base = m.flash_base, .bus = &m.bus };
    m.cpu.asi1 = flash.device();
    const layout = m.layout(p.config);
    var main_reached = false;
    var scheduler_reached = false;
    var frame_ticks: usize = 0;
    // A missing TDMA interrupt formerly made original supervision request reset at 47.6M steps.
    const limit: usize = if (p.config == .p1) 60_000_000 else 7_000_000;
    for (0..limit) |step| {
        if (m.regs.pc == layout.post_init) main_reached = true;
        if (m.regs.pc == layout.rtos_start[0] or m.regs.pc == layout.rtos_start[1]) scheduler_reached = true;
        if (p.config == .p1 and m.regs.pc == 0x7005_B7C8) frame_ticks += 1;
        devices.tick(1);
        m.cpu.irl = devices.irqLevel();
        if (devices.reset_requested) return error.UnexpectedBootReset;
        if (m.cpu.step()) |e| {
            std.debug.print("original boot stopped {any}, PC=0x{x}\n", .{ e, m.regs.pc });
            return error.GuestStopped;
        }
        if (step % 1024 == 0) m.bus.log.clearRetainingCapacity();
    }
    try std.testing.expect(main_reached);
    try std.testing.expect(scheduler_reached);
    try std.testing.expect(readWord(p.timer_ticks) > 0);
    if (p.config == .p1) {
        try std.testing.expect(frame_ticks > 20);
        try std.testing.expectEqual(@as(u32, 1), readWord(0x400A_7348)); // supervision remains armed
        try std.testing.expect(readWord(0x400A_7344) < 10); // original frame ISR services it
    }
    std.debug.print("{s}: natural startup reached RTOS and delivered {d} original OS ticks\n", .{ @tagName(p.config), readWord(p.timer_ticks) });
}

pub fn main(init: std.process.Init) !void {
    const args = try init.minimal.args.toSlice(init.arena.allocator());
    if (args.len != 2) return error.ExpectedFirmwareDirectory;
    try m.loadFirmware(init.io, args[1]);
    for (profiles) |profile| {
        try check(init, profile);
        try boot(init, profile);
    }
}
