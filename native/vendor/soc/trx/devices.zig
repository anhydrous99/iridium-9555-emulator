//! Firmware-inferred Trx ASIC devices (register map from trx-arch §2). Unknown registers retain
//! explicit latch hypotheses. Function tests can instead serve `mmio` reads from a vector's tape.
//! Explicit devices include UART byte FIFOs, interrupt configuration/source selection, and:
//!   0x80000024  LEON2 configuration: NWINDOWS-1 in bits 24:20 (reset code 0x10080-0x1008C)
//!   0x80000900  prescaled timer unit, with the RTOS tick on source 12 and watchdog on source 0
//!   0x80000920  free-running timer 1, initialized by original 0x7004A714 (P2 0x403F98)
//!   0x80000A10  TDMA counter and 32 programmed start/end compare channels (0x2A01C..0x2AAC0)
//!   0x80000524, 0x80000624  serial controllers' status: bit 9 (ready) always set [A9 mod H]
//!   0xA/0xB/0xC/0xD0000000 DSP windows: memory (the DSP loader verifies by read-back)
//! Clock/power, wake, HPI, RF sequencer and PTT DSU registers remain latches.
//! `Flash` is the flash command interface the RAM routines reach through ASI 1.
const std = @import("std");
const common = @import("common");
const sparc = @import("sparc");

/// Only these registers have explicit behavior; other APB and DSP addresses are latch hypotheses.
/// Counter progress is deterministic in explicit clock ticks, not a calibrated physical CPU rate.
pub fn modeledAccess(address: u32, is_write: bool) bool {
    const a = address & ~@as(u32, 3);
    if (a >= 0x8000_0100 and a < 0x8000_0140) return true;
    if (uartAddress(a)) |u| return u.offset <= 0x14;
    if (timerAddress(a) != null) return true;
    if (alarmAddress(a) != null) return true;
    if (a >= 0x8000_1300 and a <= 0x8000_130C) return !is_write or a == 0x8000_1304;
    switch (a) {
        0x8000_0900,
        0x8000_0904,
        0x8000_0908,
        0x8000_0960,
        0x8000_0A10,
        0x8000_0A18,
        0x8000_0A1C,
        => return true,
        else => {},
    }
    if (is_write) return false;
    return switch (a) {
        0x8000_0024, 0x8000_0148, 0x8000_0524, 0x8000_0624, 0x8000_1310, 0x8000_1314, 0x8000_1318 => true,
        else => false,
    };
}

const uart_bases = [4]u32{ 0x8000_0300, 0x8000_0200, 0x8000_1700, 0x8000_1600 };
const UartAddress = struct { port: u2, offset: u8 };

fn uartAddress(a: u32) ?UartAddress {
    for (uart_bases, 0..) |base, physical| {
        if (a >= base and a - base < 0x100) {
            return .{ .port = @intCast(physical), .offset = @intCast(a - base) };
        }
    }
    return null;
}

const Ring = struct {
    bytes: [256]u8 = @splat(0),
    head: u8 = 0,
    tail: u8 = 0,

    fn push(q: *Ring, b: u8) bool {
        const next = q.tail +% 1;
        if (next == q.head) return false;
        q.bytes[q.tail] = b;
        q.tail = next;
        return true;
    }

    fn pop(q: *Ring) ?u8 {
        if (q.head == q.tail) return null;
        defer q.head +%= 1;
        return q.bytes[q.head];
    }
};

const Uart = struct {
    rx: Ring = .{},
    tx: Ring = .{},
    tx_dropped: u64 = 0,
    config: u32 = 0,
    control: u32 = 0,
    divisor: u32 = 0,
    pins: u32 = 0,
    modem: u32 = 0,

    fn status(u: *const Uart) u32 {
        // trx 0x34418 drains data until bit 7 becomes one; 0x35378 waits while bit 1 is one.
        // TX completes immediately, independently of the bounded host capture queue.
        return u.config | 0x0C | (if (u.rx.head == u.rx.tail) @as(u32, 0x80) else 0);
    }

    fn pending(u: *const Uart) u32 {
        const tx = (u.status() & (u.config >> 8)) & 0x0C;
        // Inferred: high receive-enable bits request service while the RX FIFO is nonempty.
        const rx: u32 = if (u.rx.head != u.rx.tail and u.config & 0xF000 != 0) 0x80 else 0;
        return tx | rx;
    }
};

const TimerAddress = struct { index: usize, offset: u4 };

fn timerAddress(a: u32) ?TimerAddress {
    if (a < 0x8000_0910 or a > 0x8000_0958) return null;
    const offset: u4 = @truncate(a);
    if (offset != 0 and offset != 4 and offset != 8) return null;
    return .{ .index = (a - 0x8000_0910) / 16, .offset = offset };
}

const Timer = struct {
    count: u32 = 0,
    reload: u32 = 0,
    control: u32 = 0,
    pending: bool = false,

    fn readControl(t: *const Timer) u32 {
        return t.control | (if (t.pending) @as(u32, 0x20) else 0);
    }

    fn writeControl(t: *Timer, value: u32) void {
        // Both tick ISRs write FFFFFFDF: clear pending bit 5, reload, restart, enable IRQs.
        // These low four bits match GPTIMER EN/RS/LD/IE; bit 5 is this ASIC's observed ack.
        t.control = value & 0x0B;
        if (value & 0x20 == 0) t.pending = false;
        if (value & 4 != 0) {
            t.count = t.reload;
            t.pending = false;
        }
    }

    fn advance(t: *Timer, clocks: u64) void {
        if (t.control & 1 == 0 or clocks == 0) return;
        if (clocks <= t.count) {
            t.count -= @intCast(clocks);
            return;
        }
        if (t.control & 8 != 0) t.pending = true;
        if (t.control & 2 != 0) {
            const remaining = clocks - @as(u64, t.count) - 1;
            t.count = t.reload - @as(u32, @intCast(remaining % (@as(u64, t.reload) + 1)));
        } else {
            t.control &= ~@as(u32, 1);
            t.count = 0;
        }
    }
};

const Alarm = struct {
    control: u32 = 0,
    start: u32 = 0xFFFF,
    end: u32 = 0xFFFF,
};

const AlarmAddress = struct { index: usize, offset: u4 };

fn alarmAddress(a: u32) ?AlarmAddress {
    if (a < 0x8000_1100 or a >= 0x8000_1280) return null;
    const offset = (a - 0x8000_1100) % 12;
    return .{ .index = (a - 0x8000_1100) / 12, .offset = @intCast(offset) };
}

// Identical event wiring in telephony table 0x1088B0 and PTT table 0x4471C0.
const alarm_events = [32]u6{ 0, 2, 4, 6, 8, 14, 12, 10, 30, 28, 26, 24, 22, 20, 18, 16, 46, 44, 42, 40, 38, 36, 34, 32, 62, 60, 58, 56, 54, 52, 50, 48 };

pub const Model = struct {
    gpa: std.mem.Allocator,
    nwin: u32,
    /// PTT's table reverses ports 0/1, then lookup 0x7002EC30 reverses them again.
    /// Host indices follow the logical application ports in both images (DPL port 1 = 0x80000200).
    ptt: bool = false,
    latch: std.AutoHashMapUnmanaged(u32, u32) = .empty,
    uarts: [4]Uart = @splat(.{}),
    external_uart_events: [2]u8 = @splat(0),
    irq_config: [16]u32 = @splat(0),
    timers: [5]Timer = @splat(.{}),
    scaler: u32 = 0,
    scaler_reload: u32 = 0,
    timer_config: u32 = 0,
    watchdog_reset_delay: u32 = 0,
    watchdog_second_stage: bool = false,
    reset_requested: bool = false,
    tdma: u32 = 0,
    tdma_phase: u8 = 0,
    tdma_control: u32 = 0,
    tdma_compare: u32 = 0,
    alarms: [32]Alarm = @splat(.{}),
    alarm_pending: [4]u16 = @splat(0),
    reads: u64 = 0,
    writes: u64 = 0,

    pub fn deinit(m: *Model) void {
        m.latch.deinit(m.gpa);
    }

    pub fn device(m: *Model) common.bus.Device {
        return .{ .ctx = m, .read = read, .write = write };
    }

    /// Queue an external byte; false is backpressure, without consuming or replacing earlier input.
    pub fn uartPush(m: *Model, port: u2, value: u8) bool {
        if (!m.uarts[port].rx.push(value)) return false;
        if (port >= 2) m.external_uart_events[port - 2] |= @truncate(m.uarts[port].pending() & 0x80);
        return true;
    }

    /// Completed output capture, in transmission order. No protocol reply is synthesized.
    pub fn uartPop(m: *Model, port: u2) ?u8 {
        return m.uarts[port].tx.pop();
    }

    pub fn uartDropped(m: *const Model, port: u2) u64 {
        return m.uarts[port].tx_dropped;
    }

    /// Peripheral source clocks. Firmware implies 16.8 MHz: 700000*(23+1), or PTT 2800000*(5+1).
    /// The host supplies deterministic clocks; reads never advance timers.
    pub fn tick(m: *Model, clocks: u64) void {
        if (m.tdma_control & 1 != 0) {
            // PTT 0x70011CE8 relates one TDMA tick to four prescaled 2.8 MHz timer ticks.
            const whole = clocks / 24;
            const fraction = clocks % 24 + m.tdma_phase;
            m.tdma_phase = @intCast(fraction % 24);
            const pulses = whole + fraction / 24;
            const before = m.tdma;
            m.tdma = @intCast((m.tdma + pulses % 63000) % 63000);
            if (pulses != 0) {
                // Original 0x2A01C returns (counter - phase - 1) modulo 63000.
                const phase = (before + 62999 - m.tdma_compare % 63000) % 63000;
                for (m.alarms, alarm_events) |alarm, event| {
                    if (alarm.control & 4 == 0) continue;
                    for ([_]u32{ alarm.start, alarm.end }, 0..) |target, edge| {
                        if (target >= 63000 or alarm.control & (@as(u32, 8) << @intCast(edge)) == 0) continue;
                        const distance = (target + 62999 - phase) % 63000 + 1;
                        if (pulses >= distance) {
                            const bit = @as(u7, event) + @as(u7, @intCast(edge));
                            m.alarm_pending[bit / 16] |= @as(u16, 1) << @as(u4, @truncate(bit));
                        }
                    }
                }
            }
        }
        if (clocks <= m.scaler) {
            m.scaler -= @intCast(clocks);
            return;
        }
        const remaining = clocks - @as(u64, m.scaler) - 1;
        const period = @as(u64, m.scaler_reload) + 1;
        const pulses = 1 + remaining / period;
        m.scaler = m.scaler_reload - @as(u32, @intCast(remaining % period));
        for (m.timers[0..4]) |*timer| timer.advance(pulses);
        m.advanceWatchdog(pulses);
    }

    fn advanceWatchdog(m: *Model, pulses: u64) void {
        const timer = &m.timers[4];
        if (timer.control & 1 == 0 or pulses == 0) return;
        if (pulses <= timer.count) {
            timer.count -= @intCast(pulses);
            return;
        }
        const remaining = pulses - @as(u64, timer.count) - 1;
        if (m.watchdog_second_stage or timer.control & 8 == 0) {
            if (m.timer_config & 0x8000 != 0) m.reset_requested = true;
            timer.control &= ~@as(u32, 1);
            timer.count = 0;
        } else {
            timer.pending = true;
            // Inferred two-stage watchdog: +0x60 supplies the grace period after IRQ source 0.
            m.watchdog_second_stage = true;
            timer.count = m.watchdog_reset_delay;
            m.advanceWatchdog(remaining);
        }
    }

    fn interruptSource(m: *const Model) ?u4 {
        var selected: ?u4 = null;
        var highest: u4 = 0;
        var pending: u16 = 0;
        if (m.timers[0].pending) pending |= 1 << 12;
        if (m.timers[4].pending) pending |= 1;
        if (m.alarmPending() or m.external_uart_events[0] != 0 or m.external_uart_events[1] != 0) pending |= 1 << 10;
        for (0..2) |port| {
            const source: u4 = @intCast(4 + port);
            if (m.uarts[port].pending() != 0) pending |= @as(u16, 1) << source;
        }
        for (0..16) |line| {
            const source: u4 = @intCast(line);
            const cfg = m.irq_config[source];
            const level: u4 = @truncate(cfg);
            if (cfg & 0x40 != 0 and level > highest and pending & (@as(u16, 1) << source) != 0) {
                selected = source;
                highest = level;
            }
        }
        return selected;
    }

    /// Pending device events drive the original interrupt controller's configured source level.
    pub fn irqLevel(m: *const Model) u4 {
        const source = m.interruptSource() orelse return 0;
        return @truncate(m.irq_config[source]);
    }

    fn alarmPending(m: *const Model) bool {
        for (m.alarm_pending) |events| if (events != 0) return true;
        return false;
    }

    fn externalUartSummary(m: *const Model) u32 {
        // DCE64's two dispatchers use callback tables for ports 3 and 2 respectively,
        // not separate RX/TX directions: 347E8 handles 400A5FEC, 348F4 handles 400A6004.
        return (if (m.uarts[2].pending() != 0) @as(u32, 4) else 0) |
            (if (m.uarts[3].pending() != 0) @as(u32, 2) else 0);
    }

    fn word(m: *Model, a: u32) u32 {
        if (a >= 0x8000_0100 and a < 0x8000_0140) return m.irq_config[(a - 0x8000_0100) / 4];
        if (timerAddress(a)) |location| {
            const timer = &m.timers[location.index];
            return switch (location.offset) {
                0 => timer.count,
                4 => timer.reload,
                else => timer.readControl(),
            };
        }
        if (alarmAddress(a)) |location| {
            const alarm = m.alarms[location.index];
            return switch (location.offset) {
                0 => alarm.control,
                4 => alarm.start,
                else => alarm.end,
            };
        }
        if (a >= 0x8000_1300 and a <= 0x8000_130C) return m.alarm_pending[(a - 0x8000_1300) / 4];
        if (uartAddress(a)) |location| {
            const u = &m.uarts[location.port];
            switch (location.offset) {
                0 => {
                    const byte = u.rx.pop() orelse 0;
                    if (location.port >= 2 and u.rx.head == u.rx.tail)
                        m.external_uart_events[location.port - 2] &= ~@as(u8, 0x80);
                    return byte;
                },
                4 => return u.status(),
                8 => return u.control,
                0x0C => return u.divisor,
                0x10 => return u.pins,
                0x14 => return u.modem,
                else => {},
            }
        }
        return switch (a) {
            0x8000_0024 => (m.nwin - 1) << 20,
            // The actual interrupt entry 0x70085CDC..CF0 reads a source index, not a CPU level.
            0x8000_0148 => if (m.interruptSource()) |source| source else 0,
            // External UART2/3 TX and RX events as consumed by 0x347E8 / 0x348F4.
            0x8000_1310 => m.uarts[2].pending() << 8 | m.uarts[3].pending(),
            // No external modem-control line-change event has been supplied.
            0x8000_1314 => 0,
            // Original 0xDCE64 / PTT 0x70013444 dispatch bit 0 to the compare-event ISR.
            0x8000_1318 => @as(u32, @intFromBool(m.alarmPending())) | m.externalUartSummary(),
            0x8000_0900 => m.scaler,
            0x8000_0904 => m.scaler_reload,
            0x8000_0908 => m.timer_config,
            0x8000_0960 => m.watchdog_reset_delay,
            0x8000_0A10 => m.tdma,
            0x8000_0A18 => m.tdma_control,
            0x8000_0A1C => m.tdma_compare,
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
        if (uartAddress(addr & ~@as(u32, 3))) |u| {
            // Data is in the low byte of a big-endian word; other lanes do not consume input.
            if (u.offset == 0 and (addr & 3) + bits / 8 < 4) return 0;
        }
        const a = addr & ~@as(u32, 3);
        const result = (m.word(a) >> sh) & mask(bits);
        if (a >= 0x8000_1300 and a <= 0x8000_130C) {
            // Inferred read-to-ack: 0x2A9EC consumes each event word with no later clear write.
            m.alarm_pending[(a - 0x8000_1300) / 4] &= ~@as(u16, @truncate(mask(bits) << sh));
        }
        return result;
    }

    fn write(ctx: *anyopaque, addr: u32, bits: u8, value: u64) void {
        const m: *Model = @ptrCast(@alignCast(ctx));
        m.writes += 1;
        const a = addr & ~@as(u32, 3);
        const sh = lane(addr, bits);
        if (a >= 0x8000_0100 and a < 0x8000_0140) {
            const cfg = &m.irq_config[(a - 0x8000_0100) / 4];
            cfg.* = (cfg.* & ~(mask(bits) << sh)) | (@as(u32, @truncate(value)) & mask(bits)) << sh;
            return;
        }
        if (alarmAddress(a)) |location| {
            const alarm = &m.alarms[location.index];
            const cell = switch (location.offset) {
                0 => &alarm.control,
                4 => &alarm.start,
                else => &alarm.end,
            };
            cell.* = (cell.* & ~(mask(bits) << sh)) | (@as(u32, @truncate(value)) & mask(bits)) << sh;
            return;
        }
        // Inferred event acknowledgment: the outer ISR strobes this before reading status.
        // UART dispatchers defer service, so a persistent ready level would starve their HISRs.
        // Keep readiness visible in 1310/1318, including when both UARTs need dispatch.
        if (a == 0x8000_1304) {
            m.external_uart_events = @splat(0);
            return;
        }
        if (timerAddress(a)) |location| {
            const timer = &m.timers[location.index];
            const old = switch (location.offset) {
                0 => timer.count,
                4 => timer.reload,
                else => timer.readControl(),
            };
            const v = (old & ~(mask(bits) << sh)) | (@as(u32, @truncate(value)) & mask(bits)) << sh;
            switch (location.offset) {
                0 => timer.count = v,
                4 => timer.reload = v,
                else => {
                    timer.writeControl(v);
                    if (location.index == 4 and v & 4 != 0) m.watchdog_second_stage = false;
                },
            }
            return;
        }
        const timer_cell: ?*u32 = switch (a) {
            0x8000_0900 => &m.scaler,
            0x8000_0904 => &m.scaler_reload,
            0x8000_0908 => &m.timer_config,
            0x8000_0960 => &m.watchdog_reset_delay,
            0x8000_0A10 => &m.tdma,
            0x8000_0A18 => &m.tdma_control,
            0x8000_0A1C => &m.tdma_compare,
            else => null,
        };
        if (timer_cell) |reg| {
            reg.* = (reg.* & ~(mask(bits) << sh)) | (@as(u32, @truncate(value)) & mask(bits)) << sh;
            if (a == 0x8000_0A10) reg.* %= 63000;
            return;
        }
        if (uartAddress(a)) |location| {
            const u = &m.uarts[location.port];
            if (location.offset == 0) {
                if ((addr & 3) + bits / 8 >= 4) {
                    if (!u.tx.push(@truncate(value))) u.tx_dropped +%= 1;
                    if (location.port >= 2)
                        m.external_uart_events[location.port - 2] |= @truncate(u.pending() & 0x0C);
                }
                return;
            }
            const cell: ?*u32 = switch (location.offset) {
                4 => &u.config,
                8 => &u.control,
                0x0C => &u.divisor,
                0x10 => &u.pins,
                0x14 => &u.modem,
                else => null,
            };
            if (cell) |reg| {
                reg.* = (reg.* & ~(mask(bits) << sh)) | (@as(u32, @truncate(value)) & mask(bits)) << sh;
                if (location.offset == 4) {
                    reg.* &= ~@as(u32, 0xFF); // FIFO flags are read-only
                    if (location.port >= 2)
                        m.external_uart_events[location.port - 2] = @truncate(u.pending());
                }
                return;
            }
        }
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
    d.write(d.ctx, 0x8000_0924, 32, 0xFFFF_FFFF);
    d.write(d.ctx, 0x8000_0928, 32, 7);
    const before = d.read(d.ctx, 0x8000_0920, 32);
    try std.testing.expectEqual(before, d.read(d.ctx, 0x8000_0920, 32));
    m.tick(1);
    try std.testing.expectEqual(before - 1, d.read(d.ctx, 0x8000_0920, 32));
}

test "hardware coverage distinguishes explicit reads from register and DSP latches" {
    try std.testing.expect(modeledAccess(0x8000_0024, false));
    try std.testing.expect(modeledAccess(0x8000_0922, false));
    try std.testing.expect(modeledAccess(0x8000_0524, false));
    try std.testing.expect(modeledAccess(0x8000_0920, true));
    try std.testing.expect(!modeledAccess(0x8000_0704, false));
    try std.testing.expect(!modeledAccess(0x8000_0704, true));
    try std.testing.expect(!modeledAccess(0xA000_0000, false));
}

test "four UARTs preserve independent byte streams, FIFO state and big-endian data lanes" {
    var m: Model = .{ .gpa = std.testing.allocator, .nwin = 8 };
    defer m.deinit();
    const d = m.device();
    for (uart_bases, 0..) |base, port| {
        try std.testing.expectEqual(@as(u64, 0x8C), d.read(d.ctx, base + 4, 32));
        try std.testing.expect(m.uartPush(@intCast(port), @intCast(0x40 + port)));
        try std.testing.expectEqual(@as(u64, 0x0C), d.read(d.ctx, base + 4, 32));
        try std.testing.expectEqual(@as(u64, 0), d.read(d.ctx, base, 8));
        try std.testing.expectEqual(@as(u64, 0x40 + port), d.read(d.ctx, base + 3, 8));
        try std.testing.expectEqual(@as(u64, 0x8C), d.read(d.ctx, base + 4, 32));
        d.write(d.ctx, base, 32, 0x100 + 0x50 + port);
        d.write(d.ctx, base, 8, 0xFF); // high byte is not the serial data lane
        d.write(d.ctx, base + 3, 8, 0x60 + port);
        try std.testing.expectEqual(@as(?u8, @intCast(0x50 + port)), m.uartPop(@intCast(port)));
        try std.testing.expectEqual(@as(?u8, @intCast(0x60 + port)), m.uartPop(@intCast(port)));
        try std.testing.expectEqual(@as(?u8, null), m.uartPop(@intCast(port)));
    }
}

test "UART host queues bound input and report capture loss without changing guest TX-ready" {
    var m: Model = .{ .gpa = std.testing.allocator, .nwin = 8 };
    defer m.deinit();
    const d = m.device();
    const base = uart_bases[1];
    for (0..255) |i| {
        try std.testing.expect(m.uartPush(1, @intCast(i)));
        d.write(d.ctx, base, 32, i);
    }
    try std.testing.expect(!m.uartPush(1, 0xEE));
    d.write(d.ctx, base, 32, 0xEE);
    try std.testing.expectEqual(@as(u64, 1), m.uartDropped(1));
    try std.testing.expectEqual(@as(u64, 0x0C), d.read(d.ctx, base + 4, 32));
    for (0..255) |i| {
        try std.testing.expectEqual(@as(u64, i), d.read(d.ctx, base, 32));
        try std.testing.expectEqual(@as(?u8, @intCast(i)), m.uartPop(1));
    }
    try std.testing.expectEqual(@as(u64, 0x8C), d.read(d.ctx, base + 4, 32));
    try std.testing.expectEqual(@as(?u8, null), m.uartPop(1));
    try std.testing.expectEqual(@as(u64, 1), m.uartDropped(1));
    try std.testing.expectEqual(@as(u64, 0), m.uartDropped(0));
    try std.testing.expect(m.uartPush(1, 0xAA));
    try std.testing.expectEqual(@as(u64, 0xAA), d.read(d.ctx, base, 32));
}

test "UART IRQ configuration selects source and level, and drain/mask acknowledge events" {
    var m: Model = .{ .gpa = std.testing.allocator, .nwin = 8 };
    defer m.deinit();
    const d = m.device();
    d.write(d.ctx, 0x8000_0304, 32, 0xF000); // receive enables only
    d.write(d.ctx, 0x8000_0204, 32, 0xF000);
    d.write(d.ctx, 0x8000_0110, 32, 0x01); // source 4, level 1, masked
    d.write(d.ctx, 0x8000_0114, 32, 0x42); // source 5, level 2, enabled
    try std.testing.expect(m.uartPush(0, 'A'));
    try std.testing.expectEqual(@as(u4, 0), m.irqLevel());
    d.write(d.ctx, 0x8000_0113, 8, 0x41); // enable via the low big-endian lane
    try std.testing.expectEqual(@as(u4, 1), m.irqLevel());
    try std.testing.expect(m.uartPush(1, 'B'));
    try std.testing.expectEqual(@as(u4, 2), m.irqLevel());
    try std.testing.expectEqual(@as(u64, 5), d.read(d.ctx, 0x8000_0148, 32));
    try std.testing.expectEqual(@as(u64, 'B'), d.read(d.ctx, 0x8000_0200, 32));
    try std.testing.expectEqual(@as(u4, 1), m.irqLevel());
    try std.testing.expectEqual(@as(u64, 4), d.read(d.ctx, 0x8000_0148, 32));
    try std.testing.expectEqual(@as(u64, 'A'), d.read(d.ctx, 0x8000_0300, 32));
    try std.testing.expectEqual(@as(u4, 0), m.irqLevel());
    d.write(d.ctx, 0x8000_0204, 32, 0x0CFF); // low flags are read-only, upper bits enable TX IRQ
    try std.testing.expectEqual(@as(u64, 0x0C8C), d.read(d.ctx, 0x8000_0204, 32));
    try std.testing.expectEqual(@as(u4, 2), m.irqLevel());
    d.write(d.ctx, 0x8000_0204, 32, 0); // original 0x33BD4 masks TX-ready to acknowledge
    try std.testing.expectEqual(@as(u4, 0), m.irqLevel());
}

test "PTT logical UART mapping and external UART status follow each image's table" {
    var m: Model = .{ .gpa = std.testing.allocator, .nwin = 8, .ptt = true };
    defer m.deinit();
    const d = m.device();
    try std.testing.expect(m.uartPush(1, 0xAB));
    try std.testing.expectEqual(@as(u64, 0xAB), d.read(d.ctx, 0x8000_0200, 32));
    d.write(d.ctx, 0x8000_0300, 32, 0xCD);
    try std.testing.expectEqual(@as(?u8, 0xCD), m.uartPop(0));
    try std.testing.expectEqual(@as(?u8, null), m.uartPop(1));
    d.write(d.ctx, 0x8000_0204, 32, 0xF000);
    d.write(d.ctx, 0x8000_0114, 32, 0x42);
    try std.testing.expect(m.uartPush(1, 0xEF));
    try std.testing.expectEqual(@as(u4, 2), m.irqLevel());
    try std.testing.expectEqual(@as(u64, 5), d.read(d.ctx, 0x8000_0148, 32));
    d.write(d.ctx, 0x8000_1704, 32, 0xFC00);
    d.write(d.ctx, 0x8000_1604, 32, 0xFC00);
    try std.testing.expect(m.uartPush(2, 1));
    try std.testing.expect(m.uartPush(3, 2));
    try std.testing.expectEqual(@as(u64, 0x8C8C), d.read(d.ctx, 0x8000_1310, 32));
    for ([_]u32{ 0x8000_0200, 0x8000_0304, 0x8000_1708, 0x8000_160C, 0x8000_0110 }) |address|
        try std.testing.expect(modeledAccess(address, true));
    try std.testing.expect(!modeledAccess(0x8000_0218, false));
}

test "prescaled RTOS timer IRQs advance only with clocks and acknowledge original ISR writes" {
    var m: Model = .{ .gpa = std.testing.allocator, .nwin = 8 };
    defer m.deinit();
    const d = m.device();
    d.write(d.ctx, 0x8000_0900, 32, 1);
    d.write(d.ctx, 0x8000_0904, 32, 1);
    d.write(d.ctx, 0x8000_0914, 32, 2);
    d.write(d.ctx, 0x8000_0918, 32, 15);
    d.write(d.ctx, 0x8000_0130, 32, 0x44); // source 12 -> CPU priority 4
    try std.testing.expectEqual(@as(u64, 2), d.read(d.ctx, 0x8000_0910, 32));
    try std.testing.expectEqual(@as(u64, 0x0B), d.read(d.ctx, 0x8000_0918, 32)); // load is a strobe
    m.tick(1);
    try std.testing.expectEqual(@as(u64, 2), d.read(d.ctx, 0x8000_0910, 32));
    m.tick(3);
    try std.testing.expectEqual(@as(u64, 0), d.read(d.ctx, 0x8000_0910, 32));
    try std.testing.expectEqual(@as(u4, 0), m.irqLevel());
    m.tick(2);
    try std.testing.expectEqual(@as(u64, 2), d.read(d.ctx, 0x8000_0910, 32));
    try std.testing.expectEqual(@as(u64, 0x2B), d.read(d.ctx, 0x8000_0918, 32));
    try std.testing.expectEqual(@as(u4, 4), m.irqLevel());
    try std.testing.expectEqual(@as(u64, 12), d.read(d.ctx, 0x8000_0148, 32));
    try std.testing.expectEqual(@as(u4, 4), m.irqLevel()); // source lookup does not clear a timer
    d.write(d.ctx, 0x8000_0918, 32, 0xFFFF_FFDF); // original 9555 and PTT tick ISR ack
    try std.testing.expectEqual(@as(u4, 0), m.irqLevel());
    try std.testing.expectEqual(@as(u64, 2), d.read(d.ctx, 0x8000_0910, 32));
    m.tick(6);
    try std.testing.expectEqual(@as(u4, 4), m.irqLevel());
    d.write(d.ctx, 0x8000_0918, 32, 0);
    m.tick(1000);
    try std.testing.expectEqual(@as(u4, 0), m.irqLevel());
}

test "free-running timers wrap, one-shots stop and bulk clocks match individual clocks" {
    var m: Model = .{ .gpa = std.testing.allocator, .nwin = 8 };
    var batched: Model = .{ .gpa = std.testing.allocator, .nwin = 8 };
    defer m.deinit();
    defer batched.deinit();
    for ([_]*Model{ &m, &batched }) |model| {
        const d = model.device();
        d.write(d.ctx, 0x8000_0900, 32, 2);
        d.write(d.ctx, 0x8000_0904, 32, 2);
        d.write(d.ctx, 0x8000_0924, 32, 0xFFFF_FFFF);
        d.write(d.ctx, 0x8000_0928, 32, 7);
        d.write(d.ctx, 0x8000_0914, 32, 2);
        d.write(d.ctx, 0x8000_0918, 32, 13); // load, enable, IRQ; no restart
    }
    for (0..99) |_| m.tick(1);
    batched.tick(99);
    try std.testing.expectEqual(@as(u32, 0xFFFF_FFDE), m.timers[1].count);
    try std.testing.expectEqual(m.timers[1].count, batched.timers[1].count);
    try std.testing.expectEqual(m.scaler, batched.scaler);
    try std.testing.expectEqual(@as(u32, 0), m.timers[0].count);
    try std.testing.expect(m.timers[0].pending);
    try std.testing.expectEqual(@as(u32, 8), m.timers[0].control);
    batched.tick((@as(u64, 1) << 32) * 3);
    try std.testing.expectEqual(m.timers[1].count, batched.timers[1].count);
}

test "watchdog kick postpones expiry, IRQ grace precedes reset, and explicit reset sequence expires" {
    var m: Model = .{ .gpa = std.testing.allocator, .nwin = 8 };
    defer m.deinit();
    const d = m.device();
    d.write(d.ctx, 0x8000_0908, 32, 0x8000);
    d.write(d.ctx, 0x8000_0954, 32, 3);
    d.write(d.ctx, 0x8000_0960, 32, 2);
    d.write(d.ctx, 0x8000_0958, 32, 13); // load, enable, interrupt
    d.write(d.ctx, 0x8000_0100, 32, 0x41); // watchdog -> source 0, level 1
    m.tick(3);
    try std.testing.expectEqual(@as(u4, 0), m.irqLevel());
    d.write(d.ctx, 0x8000_0958, 32, 13); // original servicing ORs the load strobe
    m.tick(3);
    try std.testing.expect(!m.reset_requested);
    m.tick(1);
    try std.testing.expectEqual(@as(u4, 1), m.irqLevel());
    try std.testing.expectEqual(@as(u64, 0), d.read(d.ctx, 0x8000_0148, 32));
    try std.testing.expect(!m.reset_requested);
    m.tick(2);
    try std.testing.expect(!m.reset_requested);
    m.tick(1);
    try std.testing.expect(m.reset_requested);
    m.reset_requested = false;
    // Exact original 0x37950 / PTT 0x423D2C force-reset register sequence.
    d.write(d.ctx, 0x8000_0958, 32, 0);
    d.write(d.ctx, 0x8000_0954, 32, 0);
    d.write(d.ctx, 0x8000_0958, 32, 4);
    d.write(d.ctx, 0x8000_0908, 32, 0x8000);
    d.write(d.ctx, 0x8000_0958, 32, 1);
    m.tick(1);
    try std.testing.expect(m.reset_requested);
}

test "TDMA count is a bounded clocked register with firmware-controlled enable" {
    var m: Model = .{ .gpa = std.testing.allocator, .nwin = 8 };
    defer m.deinit();
    const d = m.device();
    m.tick(240);
    try std.testing.expectEqual(@as(u64, 0), d.read(d.ctx, 0x8000_0A10, 32));
    d.write(d.ctx, 0x8000_0A10, 32, 62998);
    d.write(d.ctx, 0x8000_0A18, 32, 5);
    d.write(d.ctx, 0x8000_0A1C, 32, 123);
    m.tick(48);
    try std.testing.expectEqual(@as(u64, 0), d.read(d.ctx, 0x8000_0A10, 32));
    try std.testing.expectEqual(@as(u64, 0), d.read(d.ctx, 0x8000_0A10, 32));
    m.tick(24);
    try std.testing.expectEqual(@as(u64, 1), d.read(d.ctx, 0x8000_0A10, 32));
    d.write(d.ctx, 0x8000_0A18, 32, 4);
    m.tick(240);
    try std.testing.expectEqual(@as(u64, 1), d.read(d.ctx, 0x8000_0A10, 32));
    try std.testing.expectEqual(@as(u64, 123), d.read(d.ctx, 0x8000_0A1C, 32));
}

test "programmed TDMA start/end events use firmware wiring and acknowledge consumed lanes" {
    var m: Model = .{ .gpa = std.testing.allocator, .nwin = 8 };
    defer m.deinit();
    const d = m.device();
    d.write(d.ctx, 0x8000_0128, 32, 0x68); // original DCE3C: source 10, mode 2, level 8
    d.write(d.ctx, 0x8000_0A1C, 32, 100);
    d.write(d.ctx, 0x8000_1254, 32, 0); // original channel 28 -> event 54, start at frame time 0
    d.write(d.ctx, 0x8000_1258, 32, 2);
    d.write(d.ctx, 0x8000_1250, 32, 0x1C); // channel enabled, both compare interrupts
    d.write(d.ctx, 0x8000_0A18, 32, 5);
    m.tick(100 * 24);
    try std.testing.expectEqual(@as(u4, 0), m.irqLevel());
    m.tick(24);
    try std.testing.expectEqual(@as(u4, 8), m.irqLevel());
    try std.testing.expectEqual(@as(u64, 10), d.read(d.ctx, 0x8000_0148, 32));
    try std.testing.expectEqual(@as(u64, 1), d.read(d.ctx, 0x8000_1318, 32));
    d.write(d.ctx, 0x8000_1304, 32, 0); // original outer ISR's strobe preserves unread snapshot
    try std.testing.expectEqual(@as(u64, 0), d.read(d.ctx, 0x8000_130C, 16));
    try std.testing.expectEqual(@as(u4, 8), m.irqLevel()); // high lane did not consume low status bits
    try std.testing.expectEqual(@as(u64, 0x40), d.read(d.ctx, 0x8000_130E, 16));
    try std.testing.expectEqual(@as(u4, 0), m.irqLevel());
    m.tick(48);
    try std.testing.expectEqual(@as(u64, 0x80), d.read(d.ctx, 0x8000_130C, 32));
    try std.testing.expectEqual(@as(u64, 0), d.read(d.ctx, 0x8000_1318, 32));
    d.write(d.ctx, 0x8000_1250, 32, 0x18); // interrupt enables alone do not arm comparisons
    m.tick(63000 * 24 * 2);
    try std.testing.expectEqual(@as(u4, 0), m.irqLevel());
}

test "TDMA compare events survive a full wrap and bulk clocks match individual clocks" {
    var m: Model = .{ .gpa = std.testing.allocator, .nwin = 8 };
    defer m.deinit();
    var batched: Model = .{ .gpa = std.testing.allocator, .nwin = 8 };
    defer batched.deinit();
    for ([_]*Model{ &m, &batched }) |model| {
        const d = model.device();
        d.write(d.ctx, 0x8000_1104, 32, 17);
        d.write(d.ctx, 0x8000_1108, 32, 29);
        d.write(d.ctx, 0x8000_1100, 32, 0x1C);
        d.write(d.ctx, 0x8000_0A18, 32, 1);
    }
    const clocks = 63001 * 24 + 7;
    for (0..clocks) |_| m.tick(1);
    batched.tick(clocks);
    try std.testing.expectEqual(@as(u16, 3), m.alarm_pending[0]);
    try std.testing.expectEqualSlices(u16, &m.alarm_pending, &batched.alarm_pending);
    try std.testing.expectEqual(m.tdma, batched.tdma);
    try std.testing.expectEqual(m.tdma_phase, batched.tdma_phase);
}

test "external UART groups route exact port status masks through source 10 without starving deferred service" {
    var m: Model = .{ .gpa = std.testing.allocator, .nwin = 8 };
    defer m.deinit();
    const d = m.device();
    d.write(d.ctx, 0x8000_0128, 32, 0x68);
    d.write(d.ctx, 0x8000_1704, 32, 0x0C00);
    try std.testing.expectEqual(@as(u64, 0x0C00), d.read(d.ctx, 0x8000_1310, 32));
    try std.testing.expectEqual(@as(u64, 4), d.read(d.ctx, 0x8000_1318, 32));
    try std.testing.expectEqual(@as(u4, 8), m.irqLevel());
    d.write(d.ctx, 0x8000_1604, 32, 0x0C00);
    try std.testing.expectEqual(@as(u64, 0x0C0C), d.read(d.ctx, 0x8000_1310, 32));
    try std.testing.expectEqual(@as(u64, 6), d.read(d.ctx, 0x8000_1318, 32));
    d.write(d.ctx, 0x8000_1304, 32, 0); // original DCE64 acknowledges before either dispatcher
    try std.testing.expectEqual(@as(u4, 0), m.irqLevel());
    // Both original dispatchers must still see readiness, even after the first status read.
    try std.testing.expectEqual(@as(u64, 0x0C0C), d.read(d.ctx, 0x8000_1310, 32));
    try std.testing.expectEqual(@as(u64, 0x0C0C), d.read(d.ctx, 0x8000_1310, 32));
    m.tick(10000);
    try std.testing.expectEqual(@as(u4, 0), m.irqLevel());
    d.write(d.ctx, 0x8000_1700, 32, 'A'); // another completed transmission generates another event
    try std.testing.expectEqual(@as(u4, 8), m.irqLevel());
    try std.testing.expectEqual(@as(?u8, 'A'), m.uartPop(2));
    d.write(d.ctx, 0x8000_1704, 32, 0);
    d.write(d.ctx, 0x8000_1604, 32, 0);
    try std.testing.expectEqual(@as(u4, 0), m.irqLevel());
    try std.testing.expectEqual(@as(u64, 0), d.read(d.ctx, 0x8000_1318, 32));
}

test "external receive events acknowledge on FIFO drain or mask and coexist with compare interrupts" {
    var m: Model = .{ .gpa = std.testing.allocator, .nwin = 8 };
    defer m.deinit();
    const d = m.device();
    d.write(d.ctx, 0x8000_0128, 32, 0x68);
    try std.testing.expect(m.uartPush(2, 'B'));
    try std.testing.expectEqual(@as(u4, 0), m.irqLevel());
    d.write(d.ctx, 0x8000_1704, 32, 0x7000); // enabling receive service sees an already queued byte
    try std.testing.expectEqual(@as(u64, 0x8000), d.read(d.ctx, 0x8000_1310, 32));
    try std.testing.expectEqual(@as(u64, 4), d.read(d.ctx, 0x8000_1318, 32));
    d.write(d.ctx, 0x8000_1604, 32, 0x7000);
    try std.testing.expect(m.uartPush(3, 'C'));
    try std.testing.expectEqual(@as(u64, 0x8080), d.read(d.ctx, 0x8000_1310, 32));
    d.write(d.ctx, 0x8000_1100, 32, 0x0C);
    d.write(d.ctx, 0x8000_1104, 32, 0);
    d.write(d.ctx, 0x8000_0A18, 32, 1);
    m.tick(24);
    try std.testing.expectEqual(@as(u64, 7), d.read(d.ctx, 0x8000_1318, 32));
    d.write(d.ctx, 0x8000_1304, 32, 0);
    try std.testing.expectEqual(@as(u4, 8), m.irqLevel()); // compare event still awaits its own read
    try std.testing.expectEqual(@as(u64, 1), d.read(d.ctx, 0x8000_1300, 32));
    try std.testing.expectEqual(@as(u4, 0), m.irqLevel());
    try std.testing.expectEqual(@as(u64, 'B'), d.read(d.ctx, 0x8000_1700, 32));
    try std.testing.expectEqual(@as(u64, 'C'), d.read(d.ctx, 0x8000_1600, 32));
    try std.testing.expectEqual(@as(u64, 0), d.read(d.ctx, 0x8000_1318, 32));
    try std.testing.expect(m.uartPush(3, 'D'));
    try std.testing.expectEqual(@as(u4, 8), m.irqLevel());
    try std.testing.expectEqual(@as(u64, 'D'), d.read(d.ctx, 0x8000_1600, 32));
    try std.testing.expectEqual(@as(u4, 0), m.irqLevel());
    try std.testing.expect(m.uartPush(2, 'E'));
    d.write(d.ctx, 0x8000_1704, 32, 0);
    try std.testing.expectEqual(@as(u4, 0), m.irqLevel());
    try std.testing.expectEqual(@as(u64, 'E'), d.read(d.ctx, 0x8000_1700, 32));
    try std.testing.expectEqual(@as(u64, 0), d.read(d.ctx, 0x8000_1314, 32));
}
