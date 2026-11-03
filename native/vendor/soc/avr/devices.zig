//! ATmega164P peripheral models for system runs (ARCHITECTURE §6.1, §7.4; avr-full §2, §3, §8-§10):
//! GPIO ports A-D with pin-change interrupts, Timer0/1/2 (normal, CTC, fast PWM, phase-correct,
//! TEMP-latched 16-bit access), USART0/1 (frame timing from UBRR/U2X/UCSRnC, 2-byte RX FIFO, DOR),
//! SPI (slave transfers driven by the host side, master transfers), EEPROM (EEMPE/EEPE sequence,
//! 3.4 ms write), watchdog (timed sequence, interrupt/reset), ADC (conversion timing, Timer0
//! compare-A auto trigger, host-set analog inputs), PRR clock gating, CLKPR timed sequence, and
//! plain storage for configuration registers. Registers with no model (ACSR, OCDR, TWI, reserved
//! addresses) fall back to the tape: a read pops the bus tape, a write is ignored (it is logged).
//!
//! In function tests the bus has no device (every mmio read is taped, §7.4); these models drive
//! system runs (boot, scenarios) through `bus.dev` and the CPU's `Sys` interface.
const std = @import("std");
const common = @import("common");
const emu = @import("emu_avr");
const Bus = emu.cpu.Bus;

/// Crystal frequency [inf avr-full §2: ≈16 MHz, CKDIV8 programmed, main sets ÷2 -> 8 MHz].
pub const f_osc: u64 = 16_000_000;

// Data addresses.
pub const PINA = 0x20;
pub const TIFR0 = 0x35;
pub const TIFR1 = 0x36;
pub const TIFR2 = 0x37;
pub const PCIFR = 0x3B;
pub const EIFR = 0x3C;
pub const EECR = 0x3F;
pub const EEDR = 0x40;
pub const EEARL = 0x41;
pub const EEARH = 0x42;
pub const GTCCR = 0x43;
pub const TCCR0A = 0x44;
pub const TCCR0B = 0x45;
pub const TCNT0 = 0x46;
pub const OCR0A = 0x47;
pub const OCR0B = 0x48;
pub const SPCR = 0x4C;
pub const SPSR = 0x4D;
pub const SPDR = 0x4E;
pub const SMCR = 0x53;
pub const MCUSR = 0x54;
pub const WDTCSR = 0x60;
pub const CLKPR = 0x61;
pub const PRR = 0x64;
pub const PCICR = 0x68;
pub const PCMSK0 = 0x6B;
pub const TIMSK0 = 0x6E;
pub const TIMSK1 = 0x6F;
pub const TIMSK2 = 0x70;
pub const PCMSK3 = 0x73;
pub const ADCL = 0x78;
pub const ADCH = 0x79;
pub const ADCSRA = 0x7A;
pub const ADCSRB = 0x7B;
pub const ADMUX = 0x7C;
pub const TCCR1A = 0x80;
pub const TCCR1B = 0x81;
pub const TCNT1L = 0x84;
pub const TCNT1H = 0x85;
pub const ICR1L = 0x86;
pub const ICR1H = 0x87;
pub const OCR1AL = 0x88;
pub const OCR1AH = 0x89;
pub const OCR1BL = 0x8A;
pub const OCR1BH = 0x8B;
pub const TCCR2A = 0xB0;
pub const TCCR2B = 0xB1;
pub const TCNT2 = 0xB2;
pub const OCR2A = 0xB3;
pub const OCR2B = 0xB4;
pub const UCSR0A = 0xC0;
pub const UCSR1A = 0xC8;

// PRR bits
const PRADC = 0x01;
const PRUSART0 = 0x02;
const PRSPI = 0x04;
const PRTIM1 = 0x08;
const PRUSART1 = 0x10;
const PRTIM0 = 0x20;
const PRTIM2 = 0x40;

/// Interrupt vector numbers (ATmega164P; byte address = 4 * vector).
pub const Vec = struct {
    pub const pcint0 = 4;
    pub const wdt = 8;
    pub const t2_compa = 9;
    pub const t2_compb = 10;
    pub const t2_ovf = 11;
    pub const t1_capt = 12;
    pub const t1_compa = 13;
    pub const t1_compb = 14;
    pub const t1_ovf = 15;
    pub const t0_compa = 16;
    pub const t0_compb = 17;
    pub const t0_ovf = 18;
    pub const spi = 19;
    pub const usart0_rx = 20;
    pub const usart0_udre = 21;
    pub const usart0_tx = 22;
    pub const adc = 24;
    pub const ee_ready = 25;
    pub const usart1_rx = 28;
    pub const usart1_udre = 29;
    pub const usart1_tx = 30;
};

const Access = enum { store, model, tape };

/// How each data address 0x20-0xFF is served.
const access: [0x100]Access = blk: {
    var a: [0x100]Access = @splat(.tape);
    for (0x20..0x2C) |x| a[x] = .model; // PINx/DDRx/PORTx
    for ([_]u8{ TIFR0, TIFR1, TIFR2, PCIFR, EIFR, EECR, GTCCR, TCCR0B, TCNT0, SPSR, SPDR, WDTCSR, CLKPR, ADCL, ADCH, ADCSRA, TCNT1L, TCNT1H, ICR1L, ICR1H, OCR1AL, OCR1AH, OCR1BL, OCR1BH, TCNT2, TCCR2B }) |x| a[x] = .model;
    for ([_]u8{ 0x3D, 0x3E, EEDR, EEARL, EEARH, TCCR0A, OCR0A, OCR0B, 0x4A, 0x4B, SPCR, SMCR, MCUSR, 0x55, 0x57, PRR, 0x66, PCICR, 0x69, 0x6B, 0x6C, 0x6D, TIMSK0, TIMSK1, TIMSK2, PCMSK3, ADCSRB, ADMUX, 0x7E, 0x7F, TCCR1A, TCCR1B, 0x82, TCCR2A, OCR2A, OCR2B, 0xB6 }) |x| a[x] = .store;
    for ([_]u8{ UCSR0A, UCSR1A }) |b| {
        a[b] = .model; // UCSRnA
        a[b + 1] = .store; // UCSRnB
        a[b + 2] = .store; // UCSRnC
        a[b + 4] = .store; // UBRRnL
        a[b + 5] = .store; // UBRRnH
        a[b + 6] = .model; // UDRn
    }
    // 0x3D/0x3E above are EIMSK and GPIOR0 (0x3D/0x3E data); SPL/SPH/SREG (0x5D-0x5F) are the CPU's.
    break :blk a;
};

pub const Usart = extern struct {
    rx_fifo: [2]u8 = @splat(0),
    rx_n: u8 = 0,
    tx_buf: u8 = 0,
    tx_full: u8 = 0,
    tx_shift: u8 = 0,
    dor: u8 = 0,
    _pad: u8 = 0,
    tx_busy: u32 = 0,
    rx_busy: u32 = 0,
    /// Host -> device bytes waiting on the line.
    in_ring: [64]u8 = @splat(0),
    in_head: u8 = 0,
    in_tail: u8 = 0,
    /// Device -> host bytes that finished transmitting.
    out_head: u8 = 0,
    out_tail: u8 = 0,
    out_ring: [256]u8 = @splat(0),
};

/// Snapshot part "dev": plain data only.
pub const State = extern struct {
    cycles: u64 = 0,
    /// Prescaler counters (cycles since the last prescaler reset): Timer0/1 share one, Timer2 has its own.
    pre01: u64 = 0,
    pre2: u64 = 0,
    wdt_count: u64 = 0,
    ee_busy: u32 = 0,
    adc_busy: u32 = 0,
    master_busy: u32 = 0,
    tcnt1: u16 = 0,
    ocr1a: u16 = 0,
    ocr1b: u16 = 0,
    icr1: u16 = 0,
    /// Double-buffered OCR values written in PWM modes (applied at TOP/BOTTOM).
    ocr1a_buf: u16 = 0,
    ocr1b_buf: u16 = 0,
    analog: [8]u16 = @splat(0x3FF),
    /// I/O registers by data address (index < 0x20 unused).
    io: [0x100]u8 = @splat(0),
    pins_in: [4]u8 = @splat(0),
    pin_last: [4]u8 = @splat(0),
    ocr0a_buf: u8 = 0,
    ocr0b_buf: u8 = 0,
    ocr2a_buf: u8 = 0,
    ocr2b_buf: u8 = 0,
    down: [3]u8 = @splat(0),
    temp1: u8 = 0,
    spi_rx: u8 = 0,
    spi_tx: u8 = 0,
    spif_seen: u8 = 0,
    master_in: u8 = 0xFF,
    ee_window: u8 = 0,
    wdt_window: u8 = 0,
    clk_window: u8 = 0,
    adc_first: u8 = 1,
    reset_request: u8 = 0,
    _pad: [5]u8 = @splat(0),
    usart: [2]Usart = .{ .{}, .{} },
    ee: [512]u8 = @splat(0xFF),
    /// Cycles of the running conversion left when it samples (sample-and-hold), and the sampled value.
    adc_hold: u32 = 0,
    adc_held: u16 = 0,
    adc_sampled: u8 = 0,
    /// Timer2 output compare B (the OC2B waveform, PD6 while COM2B drives the pin).
    oc2b: u8 = 0,
    ow: OneWire = .{},
};

/// The 1-Wire bus of avr-full §9 and a DS27xx-style slave on it [inf: the board; the gauge family from
/// the command set]. PD6 (OC2B) drives the bus low through an inverting stage (PD6 high = bus low) and
/// ADC1 samples it. With `connected` set, ADC1 reads the bus (low while the master or the slave pulls it,
/// else the pull-up's full scale) instead of the host's `analog[1]`, so a read slot's bit follows the
/// protocol, not when the conversion happens to sample. Times are device cycles at the current clock.
/// The slave: a reset pulse (low >= 480 us) is answered with a presence pulse (low from 30 to 150 us
/// after the release); write slots are sampled 30 us after the falling edge (released by then: 1);
/// a 0 bit in a read slot holds the bus low for 30 us from the master's falling edge. Protocol: Skip
/// ROM 0xCC, then Read Data 0x69 [addr] (bytes of `mem` from addr, LSB first), Write Data 0x6C [addr]
/// (into `mem`), Copy 0x48 / Recall 0xB8 / Lock 0x6A [addr] (no data).
/// shortcut: Read/Match/Search ROM and the EEPROM blocks behind Copy/Recall/Lock are not modelled (the
/// image sends Skip ROM only and never reads back a copied block). The bus does not reach PINA1: a
/// digital read of PA1 (SPI reg 4, gpio_access) or a pin change on it (PCMSK0 bit 1, SPI reg 16) sees
/// the host's `setPinsIn` level, not the bus; route the bus level into `pin(0)` (with pin-change
/// events at the slave's timed edges) if a scenario has the SPI master read PA1 while it is connected.
pub const OneWire = extern struct {
    /// Cycle of the master's last falling edge; the slave pulls the bus low in [low_from, low_until).
    fell_at: u64 = 0,
    low_from: u64 = 0,
    low_until: u64 = 0,
    /// 1: ADC1 reads the bus (host: `owConnect`); 0: ADC1 reads `analog[1]`.
    connected: u8 = 0,
    /// 1: the slave answers on the bus; 0: nothing does (no presence pulse, every bit 1).
    present: u8 = 0,
    master_low: u8 = 0,
    phase: Phase = .idle,
    bit: u8 = 0,
    shift: u8 = 0,
    cmd: u8 = 0,
    addr: u8 = 0,
    /// The slave's memory (DS2784 map: 0x0C voltage, 0x0E current, 0x10 accumulated current, ...).
    mem: [256]u8 = @splat(0),

    pub const Phase = enum(u8) { idle, rom_cmd, fn_cmd, address, read_data, write_data };
};

pub const Devices = struct {
    st: State = .{},
    /// For the tape fallback (`bus.tape`, `bus.halt`).
    bus: ?*Bus = null,
    /// A17, hypothesis AV-open-bus (API.md): a read above SRAM or of a register without a model and with
    /// an exhausted or no tape returns 0 instead of ending the run. Set for system runs (`enableSystem`).
    open_bus: bool = false,

    /// Power-on reset (EEPROM keeps its contents; the 1-Wire slave and its memory are on the board).
    pub fn reset(d: *Devices) void {
        const ee = d.st.ee;
        const ow = d.st.ow;
        d.st = .{};
        d.st.ee = ee;
        d.st.ow = .{ .connected = ow.connected, .present = ow.present, .mem = ow.mem };
        d.st.io[UCSR0A] = 0x20;
        d.st.io[UCSR1A] = 0x20;
        d.st.io[UCSR0A + 2] = 0x06;
        d.st.io[UCSR1A + 2] = 0x06;
        d.st.io[CLKPR] = 0x03; // CKDIV8 programmed (lfuse 0x77, avr-full §2)
        d.st.io[MCUSR] = 0x01; // PORF
        d.st.io[0x66] = 0x80; // OSCCAL: factory value unknown [unk]
        d.st.io[ADCSRA] = 0;
        for (0..4) |p| d.st.pin_last[p] = d.pin(@intCast(p));
    }

    pub fn device(d: *Devices) common.bus.Device {
        return .{ .ctx = d, .read = busRead, .write = busWrite };
    }

    pub fn sys(d: *Devices) emu.cpu.Sys {
        return .{ .ctx = d, .tick = sysTick, .pending = sysPending, .ack = sysAck, .sleep_enabled = sysSleep, .wdr = sysWdr };
    }

    // ---- host side (scenario stimulus) ------------------------------------------------------

    /// Levels the outside world drives on port `p` (0 = A .. 3 = D) input pins.
    pub fn setPinsIn(d: *Devices, p: u2, levels: u8) void {
        d.st.pins_in[p] = levels;
        d.pinChange();
    }

    /// One byte arrives on USARTn's RXD line (queued behind earlier ones; false if the queue is full).
    pub fn uartPush(d: *Devices, n: u1, b: u8) bool {
        const u = &d.st.usart[n];
        const next: u8 = (u.in_tail + 1) % @as(u8, u.in_ring.len);
        if (next == u.in_head) return false;
        u.in_ring[u.in_tail] = b;
        u.in_tail = next;
        return true;
    }

    /// Next byte USARTn finished transmitting, if any.
    pub fn uartPop(d: *Devices, n: u1) ?u8 {
        const u = &d.st.usart[n];
        if (u.out_head == u.out_tail) return null;
        defer u.out_head +%= 1;
        return u.out_ring[u.out_head];
    }

    /// The SPI master clocks one byte into this slave; returns the byte the slave shifted out, or
    /// null if the SPI is not an enabled slave (then MISO is not driven).
    pub fn spiTransfer(d: *Devices, master_out: u8) ?u8 {
        const spcr = d.st.io[SPCR];
        if (spcr & 0x40 == 0 or spcr & 0x10 != 0 or d.st.io[PRR] & PRSPI != 0) return null;
        const out = d.st.spi_tx;
        d.st.spi_rx = master_out;
        d.st.spi_tx = master_out; // without a new SPDR write the shift register sends back what it got
        d.st.io[SPSR] |= 0x80;
        d.st.spif_seen = 0;
        return out;
    }

    pub fn setAnalog(d: *Devices, ch: u3, v: u10) void {
        d.st.analog[ch] = v;
    }

    /// Connects the 1-Wire bus model to ADC1 (`OneWire`), with the slave answering or not (`present`).
    /// Its memory is `st.ow.mem`.
    pub fn owConnect(d: *Devices, present: bool) void {
        d.st.ow.connected = 1;
        d.st.ow.present = @intFromBool(present);
        d.st.ow.phase = .idle;
        d.st.ow.low_until = 0;
    }

    /// The level ADC channel `ch` sees now.
    fn analogIn(d: *const Devices, ch: u3) u16 {
        const ow = &d.st.ow;
        if (ch != 1 or ow.connected == 0) return d.st.analog[ch];
        const now = d.st.cycles;
        const low = ow.master_low != 0 or (now >= ow.low_from and now < ow.low_until);
        return if (low) 0 else 0x3FF;
    }

    fn us(d: *const Devices, n: u64) u64 {
        return n * d.fCpu() / 1_000_000;
    }

    /// Recomputes the master's drive of the bus (PD6 high = bus low) after a change of DDRD, PORTD,
    /// TCCR2A or OC2B, and feeds its edges to the slave.
    fn owDrive(d: *Devices) void {
        const io = &d.st.io;
        const ow = &d.st.ow;
        // OC2B has the pin for COM2B 2/3, and for COM2B 1 (toggle) outside PWM; else PORTD6 does
        const com = (io[TCCR2A] >> 4) & 3;
        const wgm = ((io[TCCR2B] >> 1) & 4) | (io[TCCR2A] & 3);
        const level = if (com >= 2 or (com == 1 and (wgm == 0 or wgm == 2))) d.st.oc2b != 0 else io[0x2B] & 0x40 != 0;
        const low: u8 = @intFromBool(io[0x2A] & 0x40 != 0 and level);
        if (low == ow.master_low) return;
        ow.master_low = low;
        if (ow.connected == 0 or ow.present == 0) return;
        const now = d.st.cycles;
        if (low != 0) {
            ow.fell_at = now;
            if (ow.phase == .read_data) {
                if ((ow.shift >> @intCast(ow.bit)) & 1 == 0) {
                    ow.low_from = now;
                    ow.low_until = now + d.us(30);
                }
                ow.bit += 1;
                if (ow.bit == 8) {
                    ow.bit = 0;
                    ow.addr +%= 1;
                    ow.shift = ow.mem[ow.addr];
                }
            }
            return;
        }
        const width = now - ow.fell_at;
        if (width >= d.us(480)) {
            ow.* = .{ .connected = 1, .present = 1, .mem = ow.mem, .phase = .rom_cmd, .low_from = now + d.us(30), .low_until = now + d.us(150) };
            return;
        }
        if (ow.phase == .idle or ow.phase == .read_data) return;
        if (width < d.us(30)) ow.shift |= @as(u8, 1) << @intCast(ow.bit);
        ow.bit += 1;
        if (ow.bit < 8) return;
        const b = ow.shift;
        ow.bit = 0;
        ow.shift = 0;
        switch (ow.phase) {
            .rom_cmd => ow.phase = if (b == 0xCC) .fn_cmd else .idle,
            .fn_cmd => {
                ow.cmd = b;
                ow.phase = switch (b) {
                    0x69, 0x6C, 0x48, 0xB8, 0x6A => .address,
                    else => .idle,
                };
            },
            .address => {
                ow.addr = b;
                ow.phase = switch (ow.cmd) {
                    0x69 => .read_data,
                    0x6C => .write_data,
                    else => .idle,
                };
                ow.shift = if (ow.phase == .read_data) ow.mem[b] else 0;
            },
            .write_data => {
                ow.mem[ow.addr] = b;
                ow.addr +%= 1;
            },
            .idle, .read_data => unreachable,
        }
    }

    /// CPU clock (CLKPR division of the crystal).
    pub fn fCpu(d: *const Devices) u64 {
        return f_osc >> @intCast(@min(d.st.io[CLKPR] & 0x0F, 8));
    }

    // ---- register access ----------------------------------------------------------------------

    fn busRead(ctx: *anyopaque, addr: u32, bits: u8) u64 {
        _ = bits;
        const d: *Devices = @ptrCast(@alignCast(ctx));
        return d.read(@intCast(addr));
    }

    fn busWrite(ctx: *anyopaque, addr: u32, bits: u8, v: u64) void {
        _ = bits;
        const d: *Devices = @ptrCast(@alignCast(ctx));
        d.write(@intCast(addr), @truncate(v));
    }

    fn tapeRead(d: *Devices, a: u16) u8 {
        const b = d.bus orelse return 0;
        if (b.tape) |t| if (t.pop(a)) |v| return @truncate(v);
        if (d.open_bus) return 0;
        b.halt(.tape_exhausted);
        return 0;
    }

    pub fn pin(d: *const Devices, p: u2) u8 {
        const ddr = d.st.io[PINA + 3 * @as(u16, p) + 1];
        const port = d.st.io[PINA + 3 * @as(u16, p) + 2];
        return (ddr & port) | (~ddr & d.st.pins_in[p]);
    }

    pub fn read(d: *Devices, a: u16) u8 {
        if (a >= 0x100) return d.tapeRead(a);
        switch (access[a]) {
            .tape => return d.tapeRead(a),
            .store => return d.st.io[a],
            .model => {},
        }
        const io = &d.st.io;
        switch (a) {
            0x20, 0x23, 0x26, 0x29 => return d.pin(@intCast((a - 0x20) / 3)),
            TCNT1L => {
                d.st.temp1 = @truncate(d.st.tcnt1 >> 8);
                return @truncate(d.st.tcnt1);
            },
            ICR1L => {
                d.st.temp1 = @truncate(d.st.icr1 >> 8);
                return @truncate(d.st.icr1);
            },
            TCNT1H, ICR1H => return d.st.temp1,
            OCR1AL => return @truncate(d.st.ocr1a_buf),
            OCR1AH => return @truncate(d.st.ocr1a_buf >> 8),
            OCR1BL => return @truncate(d.st.ocr1b_buf),
            OCR1BH => return @truncate(d.st.ocr1b_buf >> 8),
            SPSR => {
                if (io[SPSR] & 0x80 != 0) d.st.spif_seen = 1;
                return io[SPSR];
            },
            SPDR => {
                d.spiClearSeen();
                return d.st.spi_rx;
            },
            UCSR0A, UCSR1A => {
                const u = &d.st.usart[if (a == UCSR0A) 0 else 1];
                var v = io[a] & 0x43; // TXC, U2X, MPCM
                if (u.rx_n > 0) v |= 0x80;
                if (u.tx_full == 0) v |= 0x20;
                if (u.dor != 0) v |= 0x08;
                return v;
            },
            UCSR0A + 6, UCSR1A + 6 => {
                const u = &d.st.usart[if (a == UCSR0A + 6) 0 else 1];
                const v = u.rx_fifo[0];
                if (u.rx_n > 0) {
                    u.rx_fifo[0] = u.rx_fifo[1];
                    u.rx_n -= 1;
                    u.dor = 0;
                }
                return v;
            },
            else => return io[a],
        }
    }

    pub fn write(d: *Devices, a: u16, v: u8) void {
        if (a >= 0x100) return;
        switch (access[a]) {
            .tape => return,
            .store => {
                d.st.io[a] = v;
                if (a == PCMSK0 or a == 0x6C or a == 0x6D or a == PCMSK3) d.pinChange();
                if (a == TCCR2A) d.owDrive();
                return;
            },
            .model => {},
        }
        const io = &d.st.io;
        switch (a) {
            0x20, 0x23, 0x26, 0x29 => io[a + 2] ^= v, // writing PINx toggles PORTx
            0x21, 0x22, 0x24, 0x25, 0x27, 0x28, 0x2A, 0x2B => io[a] = v,
            TIFR0, TIFR1, TIFR2, PCIFR, EIFR => io[a] &= ~v,
            GTCCR => {
                io[a] = v & 0x80;
                if (v & 0x01 != 0) d.st.pre01 = 0;
                if (v & 0x02 != 0) d.st.pre2 = 0;
                if (v & 0x80 != 0) io[a] |= v & 0x03; // TSM holds the prescalers in reset
            },
            TCCR0B, TCCR2B => {
                io[a] = v & 0x0F; // FOC bits read as zero
                if (a == TCCR2B) d.owDrive(); // WGM22: whether COM2B 1 gives OC2B the pin
            },
            TCNT0, TCNT2 => io[a] = v,
            TCNT1H, ICR1H, OCR1AH, OCR1BH => d.st.temp1 = v,
            TCNT1L => d.st.tcnt1 = @as(u16, d.st.temp1) << 8 | v,
            ICR1L => d.st.icr1 = @as(u16, d.st.temp1) << 8 | v,
            OCR1AL => {
                d.st.ocr1a_buf = @as(u16, d.st.temp1) << 8 | v;
                if (!t1Pwm(io)) d.st.ocr1a = d.st.ocr1a_buf;
            },
            OCR1BL => {
                d.st.ocr1b_buf = @as(u16, d.st.temp1) << 8 | v;
                if (!t1Pwm(io)) d.st.ocr1b = d.st.ocr1b_buf;
            },
            SPSR => io[a] = (io[a] & 0xFE) | (v & 0x01),
            SPDR => {
                d.spiClearSeen();
                d.st.spi_tx = v;
                if (io[SPCR] & 0x50 == 0x50 and io[PRR] & PRSPI == 0 and d.st.master_busy == 0) {
                    d.st.master_busy = 8 * spiDivider(io);
                } else if (d.st.master_busy != 0) io[SPSR] |= 0x40; // WCOL
            },
            UCSR0A, UCSR1A => {
                io[a] = (io[a] & ~@as(u8, 0x43)) | (v & 0x03); // U2X, MPCM
                if (v & 0x40 != 0) io[a] &= ~@as(u8, 0x40); // TXC is write-one-to-clear
            },
            UCSR0A + 6, UCSR1A + 6 => {
                const n: u1 = if (a == UCSR0A + 6) 0 else 1;
                const u = &d.st.usart[n];
                if (io[a - 6 + 1] & 0x08 == 0 or u.tx_full != 0) return; // TXEN off or buffer full: ignored
                u.tx_buf = v;
                u.tx_full = 1;
                d.uartShift(n);
            },
            EECR => {
                // EEMPE stays set for 4 cycles after it is written; EEPE written inside that window
                // starts a write. EEPE is otherwise status (set while programming).
                const mpe = d.st.ee_window != 0;
                if (v & 0x02 != 0 and mpe and d.st.ee_busy == 0) {
                    d.st.ee_busy = @intCast(d.fCpu() * 34 / 10_000); // 3.4 ms
                    d.st.ee_window = 0;
                    io[a] = (io[a] & 0x02) | (v & 0x38) | 0x02;
                } else {
                    io[a] = (io[a] & 0x02) | (v & 0x38) | (if (mpe or v & 0x04 != 0) @as(u8, 0x04) else 0);
                    if (v & 0x04 != 0) d.st.ee_window = 4;
                }
                if (v & 0x01 != 0 and d.st.ee_busy == 0) io[EEDR] = d.st.ee[d.eeAddr()];
            },
            WDTCSR => d.wdtWrite(v),
            CLKPR => {
                if (v == 0x80) {
                    d.st.clk_window = 4;
                } else if (v & 0x80 == 0 and d.st.clk_window != 0) {
                    io[a] = v & 0x0F;
                    d.st.clk_window = 0;
                }
            },
            ADCSRA => {
                const flags = io[a] & 0x10;
                io[a] = (v & 0xEF) | (flags & ~(v & 0x10)); // ADIF write-one-to-clear
                if (v & 0x80 == 0) {
                    io[a] &= ~@as(u8, 0x40);
                    d.st.adc_busy = 0;
                    d.st.adc_first = 1;
                } else if (v & 0x40 != 0 and d.st.adc_busy == 0) d.adcStart(false) else if (d.st.adc_busy != 0) io[a] |= 0x40; // ADSC: writing 0 has no effect
            },
            ADCL, ADCH => {},
            else => io[a] = v,
        }
        if (a >= 0x20 and a <= 0x2B) {
            d.pinChange();
            d.owDrive();
        }
    }

    fn eeAddr(d: *const Devices) u9 {
        return @truncate(@as(u16, d.st.io[EEARH] & 1) << 8 | d.st.io[EEARL]);
    }

    fn spiClearSeen(d: *Devices) void {
        if (d.st.spif_seen != 0) {
            d.st.io[SPSR] &= ~@as(u8, 0xC0);
            d.st.spif_seen = 0;
        }
    }

    fn spiDivider(io: *const [0x100]u8) u32 {
        const sel = (io[SPCR] & 3) | @as(u8, io[SPSR] & 1) << 2;
        const divs = [8]u32{ 4, 16, 64, 128, 2, 8, 32, 64 };
        return divs[sel];
    }

    fn pinChange(d: *Devices) void {
        for (0..4) |p| {
            const now = d.pin(@intCast(p));
            const changed = now ^ d.st.pin_last[p];
            d.st.pin_last[p] = now;
            const msk = d.st.io[if (p == 3) PCMSK3 else PCMSK0 + p];
            if (changed & msk != 0) d.st.io[PCIFR] |= @as(u8, 1) << @intCast(p);
        }
    }

    fn wdtWrite(d: *Devices, v: u8) void {
        const io = &d.st.io;
        const old = io[WDTCSR];
        var nv = (old & 0x7F & ~@as(u8, 0x10)); // keep config, WDCE self-clears
        if (v & 0x80 != 0) nv &= ~@as(u8, 0x80); // WDIF write-one-to-clear
        nv = (nv & ~@as(u8, 0x40)) | (v & 0x40); // WDIE any time
        if (d.st.wdt_window != 0) {
            nv = (nv & ~@as(u8, 0x2F)) | (v & 0x2F); // WDE, WDP3..0
            d.st.wdt_window = 0;
        } else if (v & 0x08 != 0) nv |= 0x08; // WDE can be set any time
        if (io[MCUSR] & 0x08 != 0) nv |= 0x08; // WDRF forces WDE
        if (v & 0x18 == 0x18) d.st.wdt_window = 4;
        io[WDTCSR] = nv | (old & 0x80 & ~(v & 0x80));
    }

    fn wdtPeriod(d: *const Devices) u64 {
        const p = d.st.io[WDTCSR];
        const wdp: u6 = @intCast(@min((p & 7) | ((p >> 2) & 8), 9));
        // 2048 << wdp cycles of the 128 kHz oscillator, in CPU cycles
        return (@as(u64, 2048) << wdp) * d.fCpu() / 128_000;
    }

    // shortcut: conversion time and sample-and-hold point in ADC clocks per the datasheet's "ADC
    // Conversion Time" table (first 25 / S&H 13.5, auto-triggered 13.5 / 2, normal 13 / 1.5), not
    // checked offline (hypothesis AV-adc-sh); the input is sampled at the S&H point, not at the end.
    fn adcStart(d: *Devices, auto: bool) void {
        const io = &d.st.io;
        const ps = [8]u32{ 2, 2, 4, 8, 16, 32, 64, 128 };
        // in half ADC clocks: conversion time, sample-and-hold point
        const conv: u32, const sh: u32 = if (d.st.adc_first != 0) .{ 50, 27 } else if (auto) .{ 27, 4 } else .{ 26, 3 };
        const half = ps[io[ADCSRA] & 7] / 2;
        d.st.adc_first = 0;
        d.st.adc_busy = conv * half;
        d.st.adc_hold = (conv - sh) * half;
        d.st.adc_sampled = 0;
        io[ADCSRA] |= 0x40;
    }

    fn adcDone(d: *Devices) void {
        const io = &d.st.io;
        const v = d.st.adc_held;
        const res: u16 = if (io[ADMUX] & 0x20 != 0) v << 6 else v; // ADLAR
        io[ADCL] = @truncate(res);
        io[ADCH] = @truncate(res >> 8);
        io[ADCSRA] = (io[ADCSRA] & ~@as(u8, 0x40)) | 0x10;
    }

    fn uartFrameCycles(io: *const [0x100]u8, base: u16) u32 {
        const b = io[base + 1];
        const cc = io[base + 2];
        const ubrr: u32 = (@as(u32, io[base + 5] & 0x0F) << 8) | io[base + 4];
        const per_bit: u32 = (if (io[base] & 0x02 != 0) @as(u32, 8) else 16) * (ubrr + 1);
        const data: u32 = 5 + ((cc >> 1) & 3) + @as(u32, if (b & 0x04 != 0) 4 else 0);
        const bits = 1 + @min(data, 9) + @as(u32, if (cc & 0x20 != 0) 1 else 0) + @as(u32, if (cc & 0x08 != 0) 2 else 1);
        return bits * per_bit;
    }

    fn uartShift(d: *Devices, n: u1) void {
        const u = &d.st.usart[n];
        if (u.tx_busy != 0 or u.tx_full == 0) return;
        u.tx_shift = u.tx_buf;
        u.tx_full = 0;
        u.tx_busy = uartFrameCycles(&d.st.io, if (n == 0) UCSR0A else UCSR1A);
    }

    // ---- time ------------------------------------------------------------------------------

    fn sysTick(ctx: *anyopaque, cycles: u32) void {
        const d: *Devices = @ptrCast(@alignCast(ctx));
        d.tick(cycles);
    }

    pub fn tick(d: *Devices, cycles: u32) void {
        const io = &d.st.io;
        d.st.cycles += cycles;
        if (d.st.ee_window > 0) {
            d.st.ee_window -|= @intCast(@min(cycles, 255));
            if (d.st.ee_window == 0) io[EECR] &= ~@as(u8, 0x04);
        }
        if (d.st.wdt_window > 0) d.st.wdt_window -|= @intCast(@min(cycles, 255));
        if (d.st.clk_window > 0) d.st.clk_window -|= @intCast(@min(cycles, 255));
        // before the timers: a conversion they trigger in this tick counts from the next one
        if (d.st.adc_busy > 0 and io[PRR] & PRADC == 0) {
            d.st.adc_busy -|= cycles;
            if (d.st.adc_sampled == 0 and d.st.adc_busy <= d.st.adc_hold) {
                d.st.adc_held = d.analogIn(@truncate(io[ADMUX]));
                d.st.adc_sampled = 1;
            }
            if (d.st.adc_busy == 0) d.adcDone();
        }
        // Timer0/Timer1 share a prescaler, Timer2 has its own (GTCCR.TSM holds them).
        const old01 = d.st.pre01;
        const old2 = d.st.pre2;
        if (io[GTCCR] & 0x81 != 0x81) d.st.pre01 += cycles;
        if (io[GTCCR] & 0x82 != 0x82) d.st.pre2 += cycles;
        const div01 = [8]u64{ 0, 1, 8, 64, 256, 1024, 0, 0 };
        const div2 = [8]u64{ 0, 1, 8, 32, 64, 128, 256, 1024 };
        // shortcut: external clock sources (T0/T1 pins, CS = 6/7) and Timer2 asynchronous mode
        // (ASSR.AS2) do not count; the image uses neither.
        const ocf0a = io[TIFR0] & 2;
        if (io[PRR] & PRTIM0 == 0) d.timer8(0, ticks(old01, d.st.pre01, div01[io[TCCR0B] & 7]));
        // ADC auto trigger on Timer0 compare A (ADTS = 011): the flag's rising edge starts a conversion,
        // whether or not the interrupt is taken (a flag still set gives no edge)
        if (ocf0a == 0 and io[TIFR0] & 2 != 0 and io[ADCSRA] & 0xA0 == 0xA0 and io[ADCSRB] & 7 == 3 and d.st.adc_busy == 0 and io[PRR] & PRADC == 0) d.adcStart(true);
        if (io[PRR] & PRTIM1 == 0) d.timer16(ticks(old01, d.st.pre01, div01[io[TCCR1B] & 7]));
        if (io[PRR] & PRTIM2 == 0) d.timer8(2, ticks(old2, d.st.pre2, div2[io[TCCR2B] & 7]));
        for (0..2) |k| if (io[PRR] & @as(u8, if (k == 0) PRUSART0 else PRUSART1) == 0) d.uartTick(@intCast(k), cycles);
        if (d.st.master_busy > 0) {
            d.st.master_busy -|= cycles;
            if (d.st.master_busy == 0) {
                d.st.spi_rx = d.st.master_in;
                io[SPSR] |= 0x80;
            }
        }
        if (d.st.ee_busy > 0) {
            d.st.ee_busy -|= cycles;
            if (d.st.ee_busy == 0) {
                const a = d.eeAddr();
                const mode = (io[EECR] >> 4) & 3;
                if (mode != 2) d.st.ee[a] = 0xFF; // erase
                if (mode != 1) d.st.ee[a] &= io[EEDR]; // write
                io[EECR] &= ~@as(u8, 0x02);
            }
        }
        const wdt = io[WDTCSR];
        if (wdt & 0x48 != 0) {
            d.st.wdt_count += cycles;
            if (d.st.wdt_count >= d.wdtPeriod()) {
                d.st.wdt_count = 0;
                if (wdt & 0x40 != 0) io[WDTCSR] |= 0x80 else {
                    io[MCUSR] |= 0x08;
                    d.st.reset_request = 1;
                }
            }
        }
    }

    fn ticks(old: u64, new: u64, div: u64) u64 {
        if (div == 0) return 0;
        return new / div - old / div;
    }

    fn uartTick(d: *Devices, n: u1, cycles: u32) void {
        const u = &d.st.usart[n];
        const base: u16 = if (n == 0) UCSR0A else UCSR1A;
        const io = &d.st.io;
        var left = cycles;
        while (left > 0 and u.tx_busy > 0) {
            const step = @min(left, u.tx_busy);
            u.tx_busy -= step;
            left -= step;
            if (u.tx_busy != 0) break;
            if (u.out_tail +% 1 != u.out_head) {
                u.out_ring[u.out_tail] = u.tx_shift;
                u.out_tail +%= 1;
            }
            if (u.tx_full != 0) d.uartShift(n) else io[base] |= 0x40; // TXC
        }
        if (io[base + 1] & 0x10 == 0) return; // RXEN off: the line is not sampled
        left = cycles;
        while (left > 0) {
            if (u.rx_busy == 0) {
                if (u.in_head == u.in_tail) return;
                u.rx_busy = uartFrameCycles(io, base);
            }
            const step = @min(left, u.rx_busy);
            u.rx_busy -= step;
            left -= step;
            if (u.rx_busy != 0) return;
            const b = u.in_ring[u.in_head];
            u.in_head = (u.in_head + 1) % @as(u8, u.in_ring.len);
            if (u.rx_n < 2) {
                u.rx_fifo[u.rx_n] = b;
                u.rx_n += 1;
            } else u.dor = 1;
        }
    }

    /// One count of Timer0 (`n` = 0) or Timer2 (`n` = 2), `k` times.
    fn timer8(d: *Devices, comptime n: u2, k: u64) void {
        const io = &d.st.io;
        const ra: u16 = if (n == 0) TCCR0A else TCCR2A;
        const rb: u16 = if (n == 0) TCCR0B else TCCR2B;
        const rc: u16 = if (n == 0) TCNT0 else TCNT2;
        const roa: u16 = if (n == 0) OCR0A else OCR2A;
        const rob: u16 = if (n == 0) OCR0B else OCR2B;
        const rf: u16 = if (n == 0) TIFR0 else TIFR2;
        const wgm = ((io[rb] >> 1) & 4) | (io[ra] & 3);
        const pwm = wgm == 1 or wgm == 3 or wgm == 5 or wgm == 7;
        var i: u64 = 0;
        while (i < k) : (i += 1) {
            const oa = if (pwm) (if (n == 0) &d.st.ocr0a_buf else &d.st.ocr2a_buf) else &io[roa];
            const ob = if (pwm) (if (n == 0) &d.st.ocr0b_buf else &d.st.ocr2b_buf) else &io[rob];
            const top: u8 = if (wgm == 2) io[roa] else if (wgm == 5 or wgm == 7) oa.* else 0xFF;
            const old = io[rc];
            var flags: u8 = 0;
            if (old == oa.*) flags |= 2; // OCFnA
            if (old == ob.*) flags |= 4; // OCFnB
            const phase = wgm == 1 or wgm == 5;
            if (phase) {
                const down = &d.st.down[n];
                if (down.* == 0) {
                    if (old >= top) {
                        down.* = 1;
                        io[rc] = old -% 1;
                        oa.* = io[roa];
                        ob.* = io[rob];
                    } else io[rc] = old + 1;
                } else {
                    if (old == 0) {
                        down.* = 0;
                        io[rc] = 1;
                    } else {
                        io[rc] = old - 1;
                        if (old == 1) flags |= 1; // TOV at BOTTOM
                    }
                }
            } else if (old == top) {
                io[rc] = 0;
                if (wgm != 2 or top == 0xFF) flags |= 1; // TOV at MAX/TOP (CTC: at MAX only)
                if (pwm) {
                    oa.* = io[roa];
                    ob.* = io[rob];
                }
            } else io[rc] = old +% 1;
            io[rf] |= flags;
            if (n == 2) d.oc2bStep(wgm, flags & 4 != 0, old == top and !phase);
        }
    }

    /// OC2B after one Timer2 count (`match`: compare B; `bottom`: TOP -> BOTTOM in fast PWM), then the
    /// 1-Wire master's drive. Fast PWM: COM2B 2 clears on match and sets at BOTTOM, 3 the opposite;
    /// normal/CTC: 1 toggles, 2 clears, 3 sets on match.
    /// shortcut: phase-correct PWM and the other timers' compare outputs are not modelled (the image
    /// drives only OC2B, in fast PWM, avr-full §9).
    fn oc2bStep(d: *Devices, wgm: u8, match: bool, bottom: bool) void {
        const com = (d.st.io[TCCR2A] >> 4) & 3;
        const was = d.st.oc2b;
        if (wgm == 3 or wgm == 7) {
            if (match and com >= 2) d.st.oc2b = @intFromBool(com == 3);
            if (bottom and com >= 2) d.st.oc2b = @intFromBool(com == 2);
        } else if (wgm == 0 or wgm == 2) {
            if (match) d.st.oc2b = switch (com) {
                1 => was ^ 1,
                2 => 0,
                3 => 1,
                else => was,
            };
        }
        if (d.st.oc2b != was) d.owDrive();
    }

    fn t1Pwm(io: *const [0x100]u8) bool {
        const wgm = ((io[TCCR1B] >> 1) & 0xC) | (io[TCCR1A] & 3);
        return wgm != 0 and wgm != 4 and wgm != 12 and wgm != 13;
    }

    fn timer16(d: *Devices, k: u64) void {
        const io = &d.st.io;
        const wgm = ((io[TCCR1B] >> 1) & 0xC) | (io[TCCR1A] & 3);
        const top: u16 = switch (wgm) {
            0, 13 => 0xFFFF,
            1, 5 => 0x00FF,
            2, 6 => 0x01FF,
            3, 7 => 0x03FF,
            4, 9, 11, 15 => d.st.ocr1a,
            else => d.st.icr1, // 8, 10, 12, 14
        };
        const phase = (wgm >= 1 and wgm <= 3) or (wgm >= 8 and wgm <= 11);
        const ctc = wgm == 4 or wgm == 12;
        var i: u64 = 0;
        while (i < k) : (i += 1) {
            const old = d.st.tcnt1;
            var flags: u8 = 0;
            if (old == d.st.ocr1a) flags |= 2;
            if (old == d.st.ocr1b) flags |= 4;
            if (phase) {
                if (d.st.down[1] == 0) {
                    if (old >= top) {
                        d.st.down[1] = 1;
                        d.st.tcnt1 = old -% 1;
                        if (wgm == 10 or wgm == 11 or wgm <= 3) d.applyOcr1();
                    } else d.st.tcnt1 = old + 1;
                } else if (old == 0) {
                    d.st.down[1] = 0;
                    d.st.tcnt1 = 1;
                } else {
                    d.st.tcnt1 = old - 1;
                    if (old == 1) {
                        flags |= 1;
                        if (wgm == 8 or wgm == 9) d.applyOcr1(); // PFC updates at BOTTOM
                    }
                }
            } else if (old == top) {
                d.st.tcnt1 = 0;
                if (!ctc or top == 0xFFFF) flags |= 1;
                if (ctc and wgm == 12) flags |= 0x20; // ICF1 when ICR1 is TOP
                if (!ctc and wgm != 0) d.applyOcr1();
            } else d.st.tcnt1 = old +% 1;
            io[TIFR1] |= flags;
        }
    }

    fn applyOcr1(d: *Devices) void {
        d.st.ocr1a = d.st.ocr1a_buf;
        d.st.ocr1b = d.st.ocr1b_buf;
    }

    // ---- interrupts ----------------------------------------------------------------------------

    fn sysPending(ctx: *anyopaque) ?u8 {
        const d: *Devices = @ptrCast(@alignCast(ctx));
        return d.pending();
    }

    /// Lowest pending and enabled vector.
    pub fn pending(d: *const Devices) ?u8 {
        const io = &d.st.io;
        const pc = io[PCIFR] & io[PCICR];
        if (pc != 0) return Vec.pcint0 + @as(u8, @ctz(pc));
        if (io[WDTCSR] & 0xC0 == 0xC0) return Vec.wdt;
        const t2 = io[TIFR2] & io[TIMSK2] & 7;
        if (t2 & 2 != 0) return Vec.t2_compa;
        if (t2 & 4 != 0) return Vec.t2_compb;
        if (t2 & 1 != 0) return Vec.t2_ovf;
        const t1 = io[TIFR1] & io[TIMSK1] & 0x27;
        if (t1 & 0x20 != 0) return Vec.t1_capt;
        if (t1 & 2 != 0) return Vec.t1_compa;
        if (t1 & 4 != 0) return Vec.t1_compb;
        if (t1 & 1 != 0) return Vec.t1_ovf;
        const t0 = io[TIFR0] & io[TIMSK0] & 7;
        if (t0 & 2 != 0) return Vec.t0_compa;
        if (t0 & 4 != 0) return Vec.t0_compb;
        if (t0 & 1 != 0) return Vec.t0_ovf;
        if (io[SPSR] & 0x80 != 0 and io[SPCR] & 0x80 != 0) return Vec.spi;
        if (d.usartPending(0)) |v| return v;
        if (io[ADCSRA] & 0x18 == 0x18) return Vec.adc;
        if (io[EECR] & 0x0A == 0x08) return Vec.ee_ready;
        return d.usartPending(1);
    }

    fn usartPending(d: *const Devices, n: u1) ?u8 {
        const base: u16 = if (n == 0) UCSR0A else UCSR1A;
        const v0: u8 = if (n == 0) Vec.usart0_rx else Vec.usart1_rx;
        const u = &d.st.usart[n];
        const b = d.st.io[base + 1];
        if (u.rx_n > 0 and b & 0x80 != 0) return v0;
        if (u.tx_full == 0 and b & 0x20 != 0) return v0 + 1;
        if (d.st.io[base] & 0x40 != 0 and b & 0x40 != 0) return v0 + 2;
        return null;
    }

    fn sysAck(ctx: *anyopaque, vec: u8) void {
        const d: *Devices = @ptrCast(@alignCast(ctx));
        const io = &d.st.io;
        switch (vec) {
            4...7 => io[PCIFR] &= ~(@as(u8, 1) << @intCast(vec - 4)),
            Vec.wdt => {
                io[WDTCSR] &= ~@as(u8, 0x80);
                if (io[WDTCSR] & 0x08 != 0) io[WDTCSR] &= ~@as(u8, 0x40); // interrupt-and-reset mode
            },
            Vec.t2_compa => io[TIFR2] &= ~@as(u8, 2),
            Vec.t2_compb => io[TIFR2] &= ~@as(u8, 4),
            Vec.t2_ovf => io[TIFR2] &= ~@as(u8, 1),
            Vec.t1_capt => io[TIFR1] &= ~@as(u8, 0x20),
            Vec.t1_compa => io[TIFR1] &= ~@as(u8, 2),
            Vec.t1_compb => io[TIFR1] &= ~@as(u8, 4),
            Vec.t1_ovf => io[TIFR1] &= ~@as(u8, 1),
            Vec.t0_compa => io[TIFR0] &= ~@as(u8, 2),
            Vec.t0_compb => io[TIFR0] &= ~@as(u8, 4),
            Vec.t0_ovf => io[TIFR0] &= ~@as(u8, 1),
            Vec.spi => io[SPSR] &= ~@as(u8, 0x80),
            Vec.usart0_tx => io[UCSR0A] &= ~@as(u8, 0x40),
            Vec.usart1_tx => io[UCSR1A] &= ~@as(u8, 0x40),
            Vec.adc => io[ADCSRA] &= ~@as(u8, 0x10),
            else => {},
        }
    }

    fn sysSleep(ctx: *anyopaque) bool {
        const d: *Devices = @ptrCast(@alignCast(ctx));
        return d.st.io[SMCR] & 1 != 0;
    }

    fn sysWdr(ctx: *anyopaque) void {
        const d: *Devices = @ptrCast(@alignCast(ctx));
        d.st.wdt_count = 0;
    }
};

// ---------------------------------------------------------------------------------------------
const testing = std.testing;

fn fresh() Devices {
    var d: Devices = .{};
    d.reset();
    return d;
}

test "Timer1 normal mode at clk/1024; TEMP-latched 16-bit read; PRR gating" {
    var d = fresh();
    d.write(PRR, 0xFF);
    d.write(TCCR1B, 5);
    d.tick(5000);
    try testing.expectEqual(@as(u8, 0), d.read(TCNT1L)); // PRTIM1 set: stopped
    d.write(PRR, 0xF7);
    d.tick(1023);
    try testing.expectEqual(@as(u8, 1), d.read(TCNT1L)); // the prescaler kept running: 6023/1024 - 5000/1024
    d.write(TCNT1H, 0x12);
    d.write(TCNT1L, 0x34);
    try testing.expectEqual(@as(u16, 0x1234), d.st.tcnt1);
    try testing.expectEqual(@as(u8, 0x34), d.read(TCNT1L));
    d.st.tcnt1 = 0xABCD; // changes between the two reads
    try testing.expectEqual(@as(u8, 0x12), d.read(TCNT1H)); // high byte latched by the low read
    d.st.tcnt1 = 0xFFFF;
    d.tick(1024);
    try testing.expectEqual(@as(u8, 1), d.st.io[TIFR1] & 1); // TOV1
    try testing.expectEqual(@as(u8, 6), d.st.io[TIFR1] & 6); // OCF1A/B: OCR1A/B are 0, passed at 0 -> 1
    d.write(TIFR1, 0x01);
    try testing.expectEqual(@as(u8, 6), d.st.io[TIFR1]); // write-one-to-clear, per bit
}

test "Timer0 fast PWM: compare and overflow flags, interrupt priority and acknowledge" {
    var d = fresh();
    d.write(TCCR0A, 0x03); // WGM01:0 = 3 fast PWM, TOP 0xFF
    d.write(OCR0A, 0x10);
    d.write(TCCR0B, 0x01); // clk/1
    d.write(TIMSK0, 0x03); // OCIE0A, TOIE0
    d.st.ocr0a_buf = 0x10; // buffer applied at TOP; start with it loaded
    d.tick(0x11);
    try testing.expectEqual(@as(u8, 0x11), d.st.io[TCNT0]);
    try testing.expectEqual(@as(u8, 2), d.st.io[TIFR0] & 3); // OCF0A (OCF0B too: OCR0B = 0 was passed)
    try testing.expectEqual(@as(?u8, Vec.t0_compa), d.pending());
    Devices.sysAck(&d, Vec.t0_compa);
    try testing.expectEqual(@as(?u8, null), d.pending());
    d.tick(0x100 - 0x11);
    try testing.expectEqual(@as(u8, 0), d.st.io[TCNT0]);
    try testing.expectEqual(@as(?u8, Vec.t0_ovf), d.pending());
}

test "USART: frame timing from UBRR/U2X, UDRE/TXC, RX FIFO with overrun" {
    var d = fresh();
    d.write(UCSR0A, 0x02); // U2X
    d.write(UCSR0A + 4, 8); // UBRR 8 (avr-full §6: 115200 at 8 MHz)
    d.write(UCSR0A + 1, 0x18); // RXEN, TXEN
    d.write(UCSR0A + 6, 0x41);
    try testing.expectEqual(@as(u8, 0x22), d.read(UCSR0A)); // shifted at once: UDRE again
    d.write(UCSR0A + 6, 0x42);
    try testing.expectEqual(@as(u8, 0x02), d.read(UCSR0A)); // buffer full
    const frame = 10 * 8 * 9;
    d.tick(frame - 1);
    try testing.expectEqual(@as(?u8, null), d.uartPop(0));
    d.tick(1);
    try testing.expectEqual(@as(?u8, 0x41), d.uartPop(0));
    d.tick(frame);
    try testing.expectEqual(@as(?u8, 0x42), d.uartPop(0));
    try testing.expectEqual(@as(u8, 0x62), d.read(UCSR0A)); // TXC set, UDRE
    for ([_]u8{ 1, 2, 3 }) |b| try testing.expect(d.uartPush(0, b));
    d.tick(3 * frame);
    try testing.expectEqual(@as(u8, 0x88), d.read(UCSR0A) & 0x88); // RXC, DOR
    try testing.expectEqual(@as(u8, 1), d.read(UCSR0A + 6));
    try testing.expectEqual(@as(u8, 2), d.read(UCSR0A + 6));
    try testing.expectEqual(@as(u8, 0), d.read(UCSR0A) & 0x80);
}

test "SPI slave: transfer exchanges SPDR, SPIF cleared by SPSR read then SPDR access" {
    var d = fresh();
    try testing.expectEqual(@as(?u8, null), d.spiTransfer(0x80)); // not enabled
    d.write(SPCR, 0xC0);
    d.write(SPDR, 0x25);
    try testing.expectEqual(@as(?u8, 0x25), d.spiTransfer(0x80));
    try testing.expectEqual(@as(?u8, Vec.spi), d.pending());
    try testing.expectEqual(@as(u8, 0x80), d.read(SPSR));
    try testing.expectEqual(@as(u8, 0x80), d.read(SPDR));
    try testing.expectEqual(@as(u8, 0), d.read(SPSR));
    try testing.expectEqual(@as(?u8, 0x80), d.spiTransfer(0x09)); // no new SPDR write: echoes
}

test "GPIO and pin change: PINx from DDR/PORT/outside, PCIFR on a masked change, PINx toggles" {
    var d = fresh();
    d.write(0x21, 0xF1); // DDRA
    d.write(0x22, 0x01);
    d.setPinsIn(0, 0x02);
    try testing.expectEqual(@as(u8, 0x03), d.read(0x20));
    d.write(PCICR, 0x0F);
    d.write(PCMSK0, 0x02);
    d.setPinsIn(0, 0x00);
    try testing.expectEqual(@as(?u8, Vec.pcint0), d.pending());
    d.write(0x20, 0x01); // toggle PORTA0
    try testing.expectEqual(@as(u8, 0x00), d.st.io[0x22]);
}

test "EEPROM: write needs EEMPE then EEPE within 4 cycles, takes 3.4 ms; read" {
    var d = fresh();
    d.write(EEARL, 0x10);
    d.write(EEDR, 0x5A);
    d.write(EECR, 0x02); // EEPE without EEMPE: ignored
    try testing.expectEqual(@as(u32, 0), d.st.ee_busy);
    d.write(EECR, 0x04);
    d.write(EECR, 0x02);
    try testing.expectEqual(@as(u8, 0x02), d.st.io[EECR] & 0x02);
    d.tick(@intCast(d.fCpu() * 34 / 10_000));
    try testing.expectEqual(@as(u8, 0), d.st.io[EECR] & 0x02);
    d.write(EEDR, 0);
    d.write(EECR, 0x01);
    try testing.expectEqual(@as(u8, 0x5A), d.read(EEDR));
}

test "watchdog: timed sequence, interrupt mode timeout" {
    var d = fresh();
    d.write(WDTCSR, 0x40); // WDIE, 16 ms
    d.tick(@intCast(d.wdtPeriod()));
    try testing.expectEqual(@as(?u8, Vec.wdt), d.pending());
    d.write(WDTCSR, 0x18);
    d.write(WDTCSR, 0x00); // inside the window: WDE cleared, WDIE cleared too (written 0)
    try testing.expectEqual(@as(u8, 0x80), d.st.io[WDTCSR]);
}

test "A17 open bus: a read above SRAM or of a register without a model returns 0, the tape first" {
    var bus = try Bus.init(testing.allocator, &.{.{ .lo = 0x20, .hi = 0xFF, .kind = .mmio }}, &.{});
    defer bus.deinit();
    var d: Devices = .{ .bus = &bus, .open_bus = true };
    d.reset();
    bus.dev = d.device();
    bus.resetRun(100);
    try testing.expectEqual(@as(u64, 0), bus.read(0xB9, 8)); // TWSR, no model
    try testing.expectEqual(@as(u64, 0), bus.read(0xF0F0, 8)); // above SRAM
    try testing.expectEqual(@as(?common.bus.Stop, null), bus.stop);
    var t = try common.tape.Tape.init(testing.allocator, &.{.{ .addr = 0xB9, .value = 0xF8 }});
    defer t.deinit(testing.allocator);
    bus.tape = &t;
    try testing.expectEqual(@as(u64, 0xF8), bus.read(0xB9, 8)); // a tape still answers first
    try testing.expectEqual(@as(u64, 0), bus.read(0xB9, 8));
}

test "registers without a model come from the tape" {
    var data: emu.cpu.Data = @splat(0);
    var backing = [_]common.bus.Backing(u8){.{ .base = 0, .mem = &data }};
    const map = [_]common.bus.Range{.{ .lo = 0x20, .hi = 0xFF, .kind = .mmio }};
    var bus = try Bus.init(testing.allocator, &map, &backing);
    defer bus.deinit();
    var t = try common.tape.Tape.init(testing.allocator, &.{.{ .addr = 0xB9, .value = 0xF8 }}); // TWSR
    defer t.deinit(testing.allocator);
    bus.tape = &t;
    var d = fresh();
    d.bus = &bus;
    bus.dev = d.device();
    try testing.expectEqual(@as(u64, 0xF8), bus.read(0xB9, 8));
    try testing.expectEqual(@as(u64, 0x03), bus.read(CLKPR, 8)); // modelled: no tape
    _ = bus.read(0xB9, 8);
    try testing.expectEqual(common.bus.Stop.tape_exhausted, bus.stop.?);
}

test "ADC: OCF0A's rising edge starts the conversion (no interrupt needed), a flag left set gives none; sampled at S&H" {
    var d = fresh();
    d.write(ADMUX, 0x21); // ADLAR, ADC1
    d.write(ADCSRB, 3); // trigger: Timer0 compare A
    d.write(ADCSRA, 0xA1); // ADEN, ADATE, ADC clock /2
    d.st.adc_first = 0; // past the first (25-clock) conversion
    d.write(TCCR0A, 0x03); // fast PWM
    d.write(OCR0A, 4);
    d.st.ocr0a_buf = 4;
    d.write(TCCR0B, 0x01); // clk/1
    d.setAnalog(1, 0x200);
    d.tick(5); // the counter passes 4: OCF0A rises
    try testing.expectEqual(@as(u8, 2), d.st.io[TIFR0] & 2);
    try testing.expectEqual(@as(u8, 0x40), d.st.io[ADCSRA] & 0x40); // converting, no interrupt taken
    d.tick(4); // past the S&H point (2 ADC clocks = 4 cycles): a later input change is not seen
    d.setAnalog(1, 0x3FF);
    d.tick(27 - 4);
    try testing.expectEqual(@as(u8, 0x10), d.st.io[ADCSRA] & 0x50); // ADIF, done
    try testing.expectEqual(@as(u8, 0x80), d.st.io[ADCH]);
    d.write(ADCSRA, d.st.io[ADCSRA] | 0x10); // clear ADIF; OCF0A stays set
    d.tick(256);
    try testing.expectEqual(@as(u8, 0), d.st.io[ADCSRA] & 0x50); // no edge, no conversion
    Devices.sysAck(&d, Vec.t0_compa); // the ISR clears the flag: the next match triggers again
    d.tick(256);
    try testing.expectEqual(@as(u8, 0x40), d.st.io[ADCSRA] & 0x40);
}

test "1-Wire: OC2B pulses on PD6 drive the bus; the slave answers reset, Skip ROM and Read Data" {
    var d = fresh();
    d.write(0x2A, 0x40); // DDRD6: PD6 output, PORTD6 = 0 (bus released)
    d.write(TCCR2A, 0x23); // fast PWM, COM2B1: OC2B has PD6 (driven by hand below, timer stopped)
    d.owConnect(true);
    d.st.ow.mem[0x42] = 0xA5;
    d.st.ow.mem[0x43] = 0x2B;
    const S = struct {
        // one master low pulse of `low_us`, then the rest of a `slot_us` slot; returns ADC1 at `sample_us`
        fn slot(dv: *Devices, low_us: u64, slot_us: u64, sample_us: u64) u16 {
            const u = dv.us(1);
            dv.st.oc2b = 1;
            dv.owDrive();
            var t: u64 = 0;
            var level: u16 = 0xFFFF;
            while (t < slot_us * u) : (t += 1) {
                if (t == low_us * u) {
                    dv.st.oc2b = 0;
                    dv.owDrive();
                }
                if (t == sample_us * u) level = dv.analogIn(1);
                dv.st.cycles += 1;
            }
            return level;
        }
        fn writeByte(dv: *Devices, b: u8) void {
            for (0..8) |k| _ = slot(dv, if ((b >> @intCast(k)) & 1 != 0) 7 else 61, 103, 0);
        }
        fn readByte(dv: *Devices) u8 {
            var b: u8 = 0;
            for (0..8) |k| if (slot(dv, 7, 103, 18) != 0) {
                b |= @as(u8, 1) << @intCast(k);
            };
            return b;
        }
    };
    try testing.expectEqual(@as(u16, 0), S.slot(&d, 488, 900, 488 + 64)); // presence pulse
    S.writeByte(&d, 0xCC);
    S.writeByte(&d, 0x69);
    S.writeByte(&d, 0x42);
    try testing.expectEqual(@as(u8, 0xA5), S.readByte(&d));
    try testing.expectEqual(@as(u8, 0x2B), S.readByte(&d)); // the next address
    _ = S.slot(&d, 488, 900, 0); // reset: Skip ROM, Write Data 0x10 [0x3C]
    S.writeByte(&d, 0xCC);
    S.writeByte(&d, 0x6C);
    S.writeByte(&d, 0x10);
    S.writeByte(&d, 0x3C);
    try testing.expectEqual(@as(u8, 0x3C), d.st.ow.mem[0x10]);
    d.owConnect(false); // nobody answers: no presence
    try testing.expectEqual(@as(u16, 0x3FF), S.slot(&d, 488, 900, 488 + 64));
}

test "1-Wire: COM2B 1 (toggle) gives OC2B the pin outside PWM only" {
    var d = fresh();
    d.write(0x2A, 0x40); // DDRD6: PD6 output, PORTD6 = 0
    d.owConnect(true);
    d.st.oc2b = 1;
    d.write(TCCR2A, 0x12); // CTC, COM2B 1: OC2B (high) has PD6, the bus is low
    try testing.expectEqual(@as(u8, 1), d.st.ow.master_low);
    d.write(TCCR2B, 0x08); // WGM22: mode 6 (reserved, not CTC): PORTD6 has the pin
    try testing.expectEqual(@as(u8, 0), d.st.ow.master_low);
    d.write(TCCR2B, 0x00);
    try testing.expectEqual(@as(u8, 1), d.st.ow.master_low);
    d.write(TCCR2A, 0x13); // fast PWM: COM2B 1 is reserved (normal port operation)
    try testing.expectEqual(@as(u8, 0), d.st.ow.master_low);
}
