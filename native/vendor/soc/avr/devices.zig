//! ATmega164P peripheral models with a 640/1280-family profile for system runs
//! (ARCHITECTURE §6.1, §7.4; avr-full §2, §3, §8-§10; docs/9575-native.md):
//! GPIO ports A-D (A-H/J/K/L for mega) with external and pin-change interrupts, Timer0/1/2 (normal, CTC, fast PWM, phase-correct,
//! TEMP-latched 16-bit access), USART0/1 (frame timing from UBRR/U2X/UCSRnC, 2-byte RX FIFO, DOR),
//! SPI (slave transfers driven by the host side, master transfers), EEPROM (EEMPE/EEPE sequence,
//! 3.4 ms write), watchdog (timed sequence, interrupt/reset), ADC (conversion timing, Timer0
//! compare-A auto trigger, host-set analog inputs), PRR clock gating, CLKPR timed sequence, and
//! Timer3/4/5 and compare C in the 640/1280 profile, input capture and external timer clocks, and
//! digital compare outputs/FOC, analog comparator, asynchronous Timer2 and byte-level master/slave
//! TWI with explicit host bus stimuli, SPM/fuse/lock semantics and interrupt-vector relocation.
//! Unimplemented registers (OCDR and reserved addresses) use tape unless strict coverage rejects them.
//!
//! 640/1280 register/interrupt/peripheral semantics: Microchip DS40002211A sections 14–26.
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
pub const EIMSK = 0x3D;
pub const EICRA = 0x69;
pub const EICRB = 0x6A;
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
pub const ACSR = 0x50;
pub const SMCR = 0x53;
pub const MCUSR = 0x54;
pub const MCUCR = 0x55;
pub const SPMCSR = 0x57;
pub const RAMPZ = 0x5B;
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
pub const ASSR = 0xB6;
pub const TWBR = 0xB8;
pub const TWSR = 0xB9;
pub const TWAR = 0xBA;
pub const TWDR = 0xBB;
pub const TWCR = 0xBC;
pub const TWAMR = 0xBD;
const async_registers = [_]u16{ TCCR2B, TCCR2A, OCR2B, OCR2A, TCNT2 };
pub const UCSR0A = 0xC0;
pub const UCSR1A = 0xC8;
pub const UCSR2A = 0xD0;
pub const UCSR3A = 0x130;
const uart_bases = [_]u16{ UCSR0A, UCSR1A, UCSR2A, UCSR3A };
const timer16_bases = [_]u16{ 0x80, 0x90, 0xA0, 0x120 };
const timer16_flags = [_]u16{ TIFR1, 0x38, 0x39, 0x3A };
const timer16_masks = [_]u16{ TIMSK1, 0x71, 0x72, 0x73 };
const port_bases = [_]u16{ 0x20, 0x23, 0x26, 0x29, 0x2C, 0x2F, 0x32, 0x100, 0x103, 0x106, 0x109 };

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
    pub const comparator = 23;
    pub const adc = 24;
    pub const ee_ready = 25;
    pub const twi = 26;
    pub const spm_ready = 27;
    pub const usart1_rx = 28;
    pub const usart1_udre = 29;
    pub const usart1_tx = 30;
};

const Access = enum { store, model, tape };

/// How each data address 0x20-0xFF is served.
const access: [0x100]Access = blk: {
    var a: [0x100]Access = @splat(.tape);
    for (0x20..0x2C) |x| a[x] = .model; // PINx/DDRx/PORTx
    for ([_]u8{ MCUSR, MCUCR, SPMCSR, TWSR, TWDR, TWCR, ASSR, ACSR, TIFR0, TIFR1, TIFR2, PCIFR, EIFR, EECR, GTCCR, TCCR0B, TCNT0, SPSR, SPDR, WDTCSR, CLKPR, ADCL, ADCH, ADCSRA, TCNT1L, TCNT1H, ICR1L, ICR1H, OCR1AL, OCR1AH, OCR1BL, OCR1BH, TCNT2, TCCR2B }) |x| a[x] = .model;
    for ([_]u8{ TWBR, TWAR, TWAMR, 0x3D, 0x3E, EEDR, EEARL, EEARH, TCCR0A, OCR0A, OCR0B, 0x4A, 0x4B, SPCR, SMCR, PRR, 0x66, PCICR, 0x69, 0x6B, 0x6C, 0x6D, TIMSK0, TIMSK1, TIMSK2, PCMSK3, ADCSRB, ADMUX, 0x7E, 0x7F, TCCR1A, TCCR1B, 0x82, TCCR2A, OCR2A, OCR2B }) |x| a[x] = .store;
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
    out_dropped: u64 = 0,
};

pub const Fuses = extern struct {
    low: u8 = 0x77,
    high: u8 = 0x99,
    extended: u8 = 0xFE,
    lock: u8 = 0xEA,
};

pub const TwiReply = enum(u8) { ack, nack, arbitration_lost, bus_error };
pub const TwiEvent = extern struct {
    pub const Kind = enum(u8) { start, address, write, read, stop };
    kind: Kind,
    value: u8 = 0,
};

const Twi = extern struct {
    busy: u32 = 0,
    action: Action = .none,
    master: u8 = 0,
    slave: u8 = 0, // 1: receiver, 2: general-call receiver, 3: transmitter
    reply: TwiReply = .nack,
    reply_value: u8 = 0xFF,
    out_head: u8 = 0,
    out_tail: u8 = 0,
    out_ring: [256]TwiEvent = @splat(.{ .kind = .start }),
    out_dropped: u64 = 0,
    const Action = enum(u8) { none, start, address, write, read, stop };
};

const Timer16 = extern struct {
    count: u16 = 0,
    capture: u16 = 0,
    compare: [3]u16 = @splat(0),
    output: [3]u8 = @splat(0),
    buffered: [3]u16 = @splat(0),
    temp: u8 = 0,
    down: u8 = 0,
    external_last: u8 = 0,
    capture_last: u8 = 0,
    capture_candidate: u8 = 0,
    capture_cycles: u8 = 0,
    compare_blocked: u8 = 0,
};

/// Snapshot part "dev": plain data only.
pub const State = extern struct {
    cycles: u64 = 0,
    /// Synchronous timers0/1/3/4/5 share a prescaler; Timer2 has its own.
    pre01: u64 = 0,
    pre2: u64 = 0,
    async_values: [5]u8 = @splat(0),
    async_pending: [5]u8 = @splat(0),
    wdt_count: u64 = 0,
    ee_busy: u32 = 0,
    ee_pending: extern struct { address: u16 = 0, data: u8 = 0, mode: u8 = 0 } = .{},
    adc_busy: u32 = 0,
    master_busy: u32 = 0,
    timer: [4]Timer16 = .{ .{}, .{}, .{}, .{} },
    twi: Twi = .{},
    fuse: Fuses = .{},
    spm_buffer: [256]u8 = @splat(0xFF),
    spm_buffer_state: enum(u8) { empty, loaded, invalid } = .empty,
    spm_pending: [256]u8 = @splat(0xFF),
    spm_busy: u32 = 0,
    spm_address: u32 = 0,
    spm_operation: u8 = 0,
    spm_window: u8 = 0,
    spm_nrww: u8 = 0,
    mcu_window: u8 = 0,
    mcu_irq_hold: u8 = 0,
    sleeping: u8 = 0,
    sleep_mode: u8 = 0,
    jtd_window: u8 = 0,
    jtd_request: u8 = 0,
    bod_window: u8 = 0,
    bod_active: u8 = 0,
    analog: [16]u16 = @splat(0x3FF),
    comparator: [2]u16 = @splat(0),
    bandgap: u16 = 0,
    ac_candidate: u8 = 0,
    ac_delay: u8 = 0,
    ext_last: u8 = 0,
    external0: u8 = 0,
    /// I/O registers by data address (index < 0x20 unused).
    io: [0x200]u8 = @splat(0),
    pins_in: [11]u8 = @splat(0),
    pin_last: [11]u8 = @splat(0),
    ocr0a_buf: u8 = 0,
    ocr0b_buf: u8 = 0,
    ocr2a_buf: u8 = 0,
    ocr2b_buf: u8 = 0,
    down: [3]u8 = @splat(0),
    compare8_blocked: [3]u8 = @splat(0),
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
    usart: [4]Usart = .{ .{}, .{}, .{}, .{} },
    ee: [4096]u8 = @splat(0xFF),
    /// Cycles of the running conversion left when it samples (sample-and-hold), and the sampled value.
    adc_hold: u32 = 0,
    adc_held: u16 = 0,
    adc_sampled: u8 = 0,
    adc_mux: u8 = 0,
    adc_locked: u8 = 0,
    /// Timer2 output compare B (the OC2B waveform, PD6 while COM2B drives the pin).
    oc2b: u8 = 0,
    oc2a: u8 = 0,
    oc0: [2]u8 = @splat(0),
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
    /// HL25003 uses the 8 KiB-SRAM ATmega640/1280 family register/vector layout.
    mega: bool = false,
    async_committing: bool = false,
    program: ?*emu.cpu.Prog = null,

    /// Power-on reset (EEPROM keeps its contents; the 1-Wire slave and its memory are on the board).
    pub fn reset(d: *Devices) void {
        d.resetWithCause(.power_on);
    }

    pub const ResetCause = enum(u8) { power_on = 1, external = 2 };

    pub fn resetWithCause(d: *Devices, cause: ResetCause) void {
        const ee = d.st.ee;
        const ee_busy = d.st.ee_busy;
        const ee_pending = d.st.ee_pending;
        const ow = d.st.ow;
        const fuse = d.st.fuse;
        const analog = d.st.analog;
        const comparator = d.st.comparator;
        const bandgap = d.st.bandgap;
        const pins = d.st.pins_in;
        const flags = d.st.io[MCUSR];
        const spm_pending = d.st.spm_pending;
        const spm_busy = d.st.spm_busy;
        const spm_address = d.st.spm_address;
        const spm_operation = d.st.spm_operation;
        const spm_nrww = d.st.spm_nrww;
        const spm_control = d.st.io[SPMCSR];
        d.st = .{};
        d.st.fuse = fuse;
        d.st.ee = ee;
        if (cause == .external and ee_busy != 0) {
            d.st.ee_busy = ee_busy;
            d.st.ee_pending = ee_pending;
            d.st.io[EECR] = (ee_pending.mode << 4) | 2;
        }
        d.st.ow = .{ .connected = ow.connected, .present = ow.present, .mem = ow.mem };
        d.st.analog = analog;
        d.st.comparator = comparator;
        d.st.bandgap = bandgap;
        d.st.pins_in = pins;
        if (cause == .external and spm_busy != 0) {
            d.st.spm_pending = spm_pending;
            d.st.spm_busy = spm_busy;
            d.st.spm_address = spm_address;
            d.st.spm_operation = spm_operation;
            d.st.spm_nrww = spm_nrww;
            d.st.io[SPMCSR] = spm_control & 0x7F;
        }
        d.st.io[UCSR0A] = 0x20;
        d.st.io[UCSR1A] = 0x20;
        d.st.io[UCSR0A + 2] = 0x06;
        d.st.io[UCSR1A + 2] = 0x06;
        d.st.io[CLKPR] = if (d.st.fuse.low & 0x80 == 0) @as(u8, 3) else 0;
        d.st.io[MCUSR] = (if (cause == .power_on) @as(u8, 0) else flags) | @backingInt(cause);
        d.st.io[0x66] = 0x80; // OSCCAL: factory value unknown [unk]
        d.st.io[ADCSRA] = 0;
        if (d.st.fuse.high & 0x10 == 0 or d.st.io[MCUSR] & 8 != 0) d.st.io[WDTCSR] = 0x08;
        d.st.io[TWSR] = 0xF8;
        d.st.io[TWDR] = 0xFF;
        d.st.io[TWAR] = 0xFE;
        d.pinChange();
        d.st.ext_last = d.extLevels();
        d.seedTimerPins();
        d.comparatorRefresh();
        if (d.mega) for (uart_bases[2..]) |base| {
            d.st.io[base] = 0x20;
            d.st.io[base + 2] = 0x06;
        };
    }

    pub fn device(d: *Devices) common.bus.Device {
        return .{ .ctx = d, .read = busRead, .write = busWrite };
    }

    pub fn sys(d: *Devices) emu.cpu.Sys {
        return .{ .ctx = d, .tick = sysTick, .pending = sysPending, .ack = sysAck, .sleep_enabled = sysSleep, .wdr = sysWdr, .spm = sysSpm, .program_read = sysProgramRead, .blocked = sysBlocked, .interrupts_enabled = sysInterruptsEnabled, .interrupt_base = sysInterruptBase, .bit_write_value = sysBitWriteValue, .sleeping = sysSleeping, .wake_cycles = sysWakeCycles };
    }

    // ---- host side (scenario stimulus) ------------------------------------------------------

    pub fn configureFuses(d: *Devices, low: u8, high: u8, extended: u8, lock: u8) void {
        d.st.fuse = .{ .low = low, .high = high, .extended = extended, .lock = lock | 0xC0 };
    }

    pub fn fuses(d: *const Devices) Fuses {
        return d.st.fuse;
    }

    pub fn bootStart(d: *const Devices) u16 {
        const max_words: u32 = if (d.mega) 0x10000 else 0x2000;
        const maximum: u32 = if (d.mega) 4096 else 1024;
        const size = maximum >> @as(u2, @truncate(d.st.fuse.high >> 1));
        return @intCast(max_words - size);
    }

    pub fn resetVector(d: *const Devices) u16 {
        return if (d.st.fuse.high & 1 == 0) d.bootStart() else 0;
    }

    /// Input levels, A–D for 164P; A–H/J/K/L for the 640/1280 profile.
    pub fn setPinsIn(d: *Devices, p: u4, levels: u8) void {
        d.st.pins_in[p] = levels;
        d.pinChange();
    }

    /// One byte arrives on USARTn's RXD line (queued behind earlier ones; false if the queue is full).
    pub fn uartPush(d: *Devices, n: u2, b: u8) bool {
        if (!d.ioRunning()) return false;
        const u = &d.st.usart[n];
        const next: u8 = (u.in_tail + 1) % @as(u8, u.in_ring.len);
        if (next == u.in_head) return false;
        u.in_ring[u.in_tail] = b;
        u.in_tail = next;
        return true;
    }

    /// Next byte USARTn finished transmitting, if any.
    pub fn uartPop(d: *Devices, n: u2) ?u8 {
        const u = &d.st.usart[n];
        if (u.out_head == u.out_tail) return null;
        defer u.out_head +%= 1;
        return u.out_ring[u.out_head];
    }

    /// The SPI master clocks one byte into this slave; returns the byte the slave shifted out, or
    /// null if the SPI is not an enabled slave (then MISO is not driven).
    pub fn spiTransfer(d: *Devices, master_out: u8) ?u8 {
        const spcr = d.st.io[SPCR];
        if (spcr & 0x40 == 0 or spcr & 0x10 != 0 or d.st.io[PRR] & PRSPI != 0 or !d.ioRunning()) return null;
        const out = d.st.spi_tx;
        d.st.spi_rx = master_out;
        d.st.spi_tx = master_out; // without a new SPDR write the shift register sends back what it got
        d.st.io[SPSR] |= 0x80;
        d.st.spif_seen = 0;
        return out;
    }

    /// Response from an external TWI peer to an in-flight master byte. No peer defaults to NACK
    /// for writes/addressing and undriven high bits (0xFF) for a master read.
    pub fn twiReply(d: *Devices, reply: TwiReply, value: u8) bool {
        const t = &d.st.twi;
        if (t.busy == 0 or (t.action != .address and t.action != .write and t.action != .read)) return false;
        t.reply = reply;
        t.reply_value = value;
        return true;
    }

    pub fn twiPop(d: *Devices) ?TwiEvent {
        const t = &d.st.twi;
        if (t.out_head == t.out_tail) return null;
        defer t.out_head +%= 1;
        return t.out_ring[t.out_head];
    }

    /// External master sends SLA+R/W to this AVR slave. TWINT stretches the bus until guest ack.
    pub fn twiAddress(d: *Devices, address: u7, read_mode: bool) bool {
        const io = &d.st.io;
        const t = &d.st.twi;
        if (io[PRR] & 0x80 != 0 or io[TWCR] & 0xC4 != 0x44 or t.master != 0) return false;
        const general = address == 0 and !read_mode and io[TWAR] & 1 != 0;
        const mask = io[TWAMR] >> 1;
        if (!general and ((address ^ (io[TWAR] >> 1)) & ~mask) != 0) return false;
        t.slave = if (read_mode) 3 else if (general) 2 else 1;
        d.twiStatus(if (read_mode) @as(u8, 0xA8) else if (general) 0x70 else 0x60);
        return true;
    }

    pub fn twiReceive(d: *Devices, value: u8) bool {
        const io = &d.st.io;
        const t = &d.st.twi;
        if (!d.ioRunning() or io[PRR] & 0x80 != 0 or io[TWCR] & 0x84 != 4 or (t.slave != 1 and t.slave != 2)) return false;
        io[TWDR] = value;
        const ack = io[TWCR] & 0x40 != 0;
        d.twiStatus(if (t.slave == 2) (if (ack) @as(u8, 0x90) else 0x98) else (if (ack) @as(u8, 0x80) else 0x88));
        if (!ack) t.slave = 0;
        return true;
    }

    pub fn twiTransmit(d: *Devices, ack: bool) ?u8 {
        const io = &d.st.io;
        const t = &d.st.twi;
        if (!d.ioRunning() or io[PRR] & 0x80 != 0 or io[TWCR] & 0x84 != 4 or t.slave != 3) return null;
        const value = io[TWDR];
        d.twiStatus(if (!ack) @as(u8, 0xC0) else if (io[TWCR] & 0x40 == 0) 0xC8 else 0xB8);
        if (!ack or io[TWCR] & 0x40 == 0) t.slave = 0;
        return value;
    }

    pub fn twiStop(d: *Devices) bool {
        const io = &d.st.io;
        const t = &d.st.twi;
        if (t.slave == 0 or io[TWCR] & 0x84 != 4) return false;
        t.slave = 0;
        d.twiStatus(0xA0);
        return true;
    }

    pub fn setAnalog(d: *Devices, ch: u4, v: u10) void {
        d.st.analog[ch] = v;
        d.comparatorRefresh();
    }

    /// AIN0/AIN1 samples in the same normalized reference units as host ADC inputs.
    pub fn setComparatorInputs(d: *Devices, positive: u10, negative: u10) void {
        d.st.comparator = .{ positive, negative };
        d.comparatorRefresh();
    }

    /// Normalized internal-reference sample supplied explicitly by the test fixture.
    pub fn setBandgap(d: *Devices, sample: u10) void {
        d.st.bandgap = sample;
        d.comparatorRefresh();
    }

    /// Supply independent Timer2 oscillator edges; CPU instructions do not invent an oscillator.
    pub fn asyncTick(d: *Devices, oscillator_ticks: u32) void {
        const io = &d.st.io;
        if (io[ASSR] & 0x20 == 0 or !d.asyncRunning()) return;
        const divs = [_]u64{ 0, 1, 8, 32, 64, 128, 256, 1024 };
        for (0..oscillator_ticks) |_| {
            const old = d.st.pre2;
            if (io[GTCCR] & 0x82 != 0x82) d.st.pre2 += 1;
            d.timer8(2, ticks(old, d.st.pre2, divs[io[TCCR2B] & 7]));
            for (&d.st.async_pending, 0..) |*remaining, index| {
                if (remaining.* == 0) continue;
                remaining.* -= 1;
                if (remaining.* == 0) {
                    d.async_committing = true;
                    d.write(async_registers[index], d.st.async_values[index]);
                    d.async_committing = false;
                    io[ASSR] &= ~(@as(u8, 1) << @intCast(index));
                }
            }
        }
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
    fn analogIn(d: *const Devices, ch: u4) u16 {
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
        const level = if (com >= 2 or (com == 1 and (wgm == 0 or wgm == 2))) d.st.oc2b != 0 else io[if (d.mega) @as(usize, 0x102) else 0x2B] & 0x40 != 0;
        const low: u8 = @intFromBool(io[if (d.mega) @as(usize, 0x101) else 0x2A] & 0x40 != 0 and level);
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

    pub fn uartCount(d: *const Devices) usize {
        return if (d.mega) 4 else 2;
    }
    pub fn portCount(d: *const Devices) usize {
        return if (d.mega) 11 else 4;
    }

    pub fn analogCount(d: *const Devices) usize {
        return if (d.mega) 16 else 8;
    }

    fn timerCount(d: *const Devices) usize {
        return if (d.mega) 4 else 1;
    }

    fn uartIndex(base: u16) u2 {
        return switch (base) {
            UCSR0A => 0,
            UCSR1A => 1,
            UCSR2A => 2,
            UCSR3A => 3,
            else => unreachable,
        };
    }

    fn portFor(d: *const Devices, a: u16) ?u4 {
        for (port_bases[0..d.portCount()], 0..) |base, i| {
            if (a >= base and a < base + 3) return @intCast(i);
        }
        return null;
    }

    fn registerAccess(d: *const Devices, a: u16) Access {
        if (d.mega) {
            for (uart_bases[2..]) |base| {
                if (a == base or a == base + 6) return .model;
                if (a > base and a < base + 6 and a != base + 3) return .store;
            }
            if (a == RAMPZ) return .model;
            if (a == 0x65 or a == EICRB or a == 0x7D or (a >= 0x71 and a <= 0x73)) return .store;
            if (a >= 0x38 and a <= 0x3A) return .model;
        }
        return if (a < access.len) access[a] else .tape;
    }

    pub fn modeledAccess(d: *const Devices, a: u16, write_access: bool) bool {
        _ = write_access;
        if (d.portFor(a) != null) return true;
        if (d.timerFor(a) != null) return true;
        return d.registerAccess(a) != .tape;
    }

    fn vector(d: *const Devices, v: u8) u8 {
        if (!d.mega) return v;
        return switch (v) {
            4...6 => v + 5,
            8...14 => v + 4,
            15...25 => v + 5,
            26 => 39,
            27 => 40,
            28...30 => v + 8,
            else => 255,
        };
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

    const OutputPin = struct { port: u4, bit: u3 };

    fn output8Pin(d: *const Devices, n: u2, c: usize) OutputPin {
        if (n == 0) return if (d.mega)
            (if (c == 0) .{ .port = 1, .bit = 7 } else .{ .port = 6, .bit = 5 })
        else
            .{ .port = 1, .bit = @intCast(3 + c) };
        return if (d.mega)
            (if (c == 0) .{ .port = 1, .bit = 4 } else .{ .port = 7, .bit = 6 })
        else
            .{ .port = 3, .bit = @intCast(7 - c) };
    }

    fn output16Pin(d: *const Devices, n: usize, c: usize) OutputPin {
        if (!d.mega) return .{ .port = 3, .bit = @intCast(5 - c) };
        return switch (n) {
            0 => .{ .port = 1, .bit = @intCast(5 + c) },
            1 => .{ .port = 4, .bit = @intCast(3 + c) },
            2 => .{ .port = 7, .bit = @intCast(3 + c) },
            3 => .{ .port = 10, .bit = @intCast(3 + c) },
            else => unreachable,
        };
    }

    fn output8Enabled(d: *const Devices, n: u2, c: usize) bool {
        const a: u16 = if (n == 0) TCCR0A else TCCR2A;
        const b: u16 = if (n == 0) TCCR0B else TCCR2B;
        const wgm = ((d.st.io[b] >> 1) & 4) | (d.st.io[a] & 3);
        const com = (d.st.io[a] >> @intCast(6 - 2 * c)) & 3;
        if (com == 0 or wgm == 4 or wgm == 6) return false;
        if (com != 1 or wgm == 0 or wgm == 2) return true;
        return c == 0 and (wgm == 5 or wgm == 7);
    }

    fn output16Enabled(d: *const Devices, n: usize, c: usize) bool {
        const a = timer16_bases[n];
        const wgm = ((d.st.io[a + 1] >> 1) & 0xC) | (d.st.io[a] & 3);
        const com = (d.st.io[a] >> @intCast(6 - 2 * c)) & 3;
        if (com == 0 or wgm == 13) return false;
        if (com != 1 or !timerPwm(&d.st.io, n)) return true;
        return c == 0 and (wgm == 9 or wgm == 11 or wgm == 14 or wgm == 15);
    }

    pub fn pin(d: *const Devices, p: u4) u8 {
        const ddr = d.st.io[port_bases[p] + 1];
        var port = d.st.io[port_bases[p] + 2];
        for ([_]u2{ 0, 2 }) |n| for (0..2) |c| {
            const out = d.output8Pin(n, c);
            if (out.port == p and d.output8Enabled(n, c)) {
                const bit = @as(u8, 1) << out.bit;
                const level = if (n == 0) d.st.oc0[c] else if (c == 0) d.st.oc2a else d.st.oc2b;
                port = (port & ~bit) | (@as(u8, level) << out.bit);
            }
        };
        for (0..d.timerCount()) |n| for (0..if (d.mega) @as(usize, 3) else 2) |c| {
            const out = d.output16Pin(n, c);
            if (out.port == p and d.output16Enabled(n, c)) {
                const bit = @as(u8, 1) << out.bit;
                port = (port & ~bit) | (d.st.timer[n].output[c] << out.bit);
            }
        };
        if (d.mega and p == 1 and d.output8Enabled(0, 0) and d.output16Enabled(0, 2)) {
            const level = if (d.st.io[port_bases[1] + 2] & 0x80 != 0)
                d.st.oc0[0] | d.st.timer[0].output[2]
            else
                d.st.oc0[0] & d.st.timer[0].output[2];
            port = (port & 0x7F) | (level << 7);
        }
        return (ddr & port) | (~ddr & d.st.pins_in[p]);
    }

    pub fn read(d: *Devices, a: u16) u8 {
        if (a >= (if (d.mega) @as(u16, 0x200) else 0x100)) return d.tapeRead(a);
        if (d.portFor(a)) |p| return if (a == port_bases[p]) d.pin(p) else d.st.io[a];
        if (d.timerFor(a)) |n| return d.timerRead(n, a - timer16_bases[n]);
        switch (d.registerAccess(a)) {
            .tape => return d.tapeRead(a),
            .store => return d.st.io[a],
            .model => {},
        }
        const io = &d.st.io;
        switch (a) {
            0x20, 0x23, 0x26, 0x29 => return d.pin(@intCast((a - 0x20) / 3)),
            RAMPZ => return io[a] & 1,
            TWSR => return if (io[TWCR] & 0x80 == 0) (io[a] & 3) | 0xF8 else io[a],
            CLKPR => return io[a] | (if (d.st.clk_window != 0) @as(u8, 0x80) else 0),
            ADCL => {
                d.st.adc_locked = 1;
                return io[ADCL];
            },
            ADCH => {
                d.st.adc_locked = 0;
                return io[ADCH];
            },
            SPSR => {
                if (io[SPSR] & 0x80 != 0) d.st.spif_seen = 1;
                return io[SPSR];
            },
            SPDR => {
                d.spiClearSeen();
                return d.st.spi_rx;
            },
            UCSR0A, UCSR1A, UCSR2A, UCSR3A => {
                const u = &d.st.usart[uartIndex(a)];
                var v = io[a] & 0x43; // TXC, U2X, MPCM
                if (u.rx_n > 0) v |= 0x80;
                if (u.tx_full == 0) v |= 0x20;
                if (u.dor != 0) v |= 0x08;
                return v;
            },
            UCSR0A + 6, UCSR1A + 6, UCSR2A + 6, UCSR3A + 6 => {
                const u = &d.st.usart[uartIndex(a - 6)];
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
        if (a >= (if (d.mega) @as(u16, 0x200) else 0x100)) return;
        if (d.st.io[ASSR] & 0x20 != 0 and !d.async_committing) {
            for (async_registers, 0..) |address, index| if (a == address) {
                d.st.async_values[index] = v;
                d.st.async_pending[index] = 2;
                d.st.io[ASSR] |= @as(u8, 1) << @intCast(index);
                return;
            };
        }
        if (d.portFor(a)) |p| {
            if (a == port_bases[p]) d.st.io[a + 2] ^= v else d.st.io[a] = v;
            d.pinChange();
            d.owDrive();
            return;
        }
        if (d.timerFor(a)) |n| {
            d.timerWrite(n, a - timer16_bases[n], v);
            return;
        }
        switch (d.registerAccess(a)) {
            .tape => return,
            .store => {
                const previous = d.st.io[a];
                const trigger = a == ADCSRB and d.adcTriggerLevel();
                d.st.io[a] = v;
                if (a == ADMUX and (previous ^ v) & 0x20 != 0) {
                    const encoded = @as(u16, d.st.io[ADCL]) | @as(u16, d.st.io[ADCH]) << 8;
                    const sample = if (previous & 0x20 != 0) encoded >> 6 else encoded;
                    const adjusted = if (v & 0x20 != 0) sample << 6 else sample;
                    d.st.io[ADCL] = @truncate(adjusted);
                    d.st.io[ADCH] = @truncate(adjusted >> 8);
                }
                if (a == PCMSK0 or a == 0x6C or a == 0x6D or a == PCMSK3) d.pinChange();
                if (a == EICRA or a == EICRB) d.externalInterrupts();
                if ((a == PRR or (d.mega and a == 0x65)) and previous & ~v != 0) d.captureInputs();
                if (a == ADMUX or a == ADCSRB or (a == PRR and (previous ^ v) & PRADC != 0)) d.comparatorRefresh();
                if (a == ADCSRB and !trigger and d.adcTriggerLevel()) d.adcTrigger(@truncate(v));
                if (a == TCCR0A or a == TCCR2A) {
                    d.pinChange();
                    d.owDrive();
                }
                return;
            },
            .model => {},
        }
        const io = &d.st.io;
        switch (a) {
            0x20, 0x23, 0x26, 0x29 => io[a + 2] ^= v, // writing PINx toggles PORTx
            0x21, 0x22, 0x24, 0x25, 0x27, 0x28, 0x2A, 0x2B => io[a] = v,
            TIFR0, TIFR1, TIFR2, 0x38, 0x39, 0x3A, PCIFR, EIFR => io[a] &= ~v,
            RAMPZ => io[a] = v & 1,
            SPMCSR => d.spmControl(v),
            MCUSR => io[a] &= v & 0x1F,
            MCUCR => {
                const previous = io[a];
                const selected = previous & 2;
                io[a] = (previous & 0xE0) | (v & 0x10) | selected;
                const requested_jtd = v & 0x80;
                if (requested_jtd != previous & 0x80) {
                    if (d.st.jtd_window != 0 and requested_jtd == d.st.jtd_request) {
                        io[a] = (io[a] & ~@as(u8, 0x80)) | requested_jtd;
                        d.st.jtd_window = 0;
                    } else {
                        d.st.jtd_request = requested_jtd;
                        d.st.jtd_window = 4;
                    }
                } else d.st.jtd_window = 0;
                if (!d.mega) {
                    if (v & 0x60 == 0x60) {
                        io[a] |= 0x60;
                        d.st.bod_window = 4;
                    } else if (d.st.bod_window != 0) {
                        io[a] = (io[a] & ~@as(u8, 0x60)) | (v & 0x60);
                        d.st.bod_window = 0;
                        if (v & 0x60 == 0x40) d.st.bod_active = 3;
                    }
                }
                if (v & 1 != 0) {
                    d.st.mcu_window = 4;
                    io[a] |= 1;
                } else if (d.st.mcu_window != 0) {
                    io[a] = (io[a] & ~@as(u8, 2)) | (v & 2);
                    d.st.mcu_window = 0;
                    d.st.mcu_irq_hold = 1;
                }
            },
            TWSR => io[a] = (io[a] & 0xF8) | (v & 3),
            TWDR => {
                if (io[TWCR] & 0x80 != 0) {
                    io[a] = v;
                    io[TWCR] &= ~@as(u8, 8);
                } else io[TWCR] |= 8;
            },
            TWCR => d.twiControl(v),
            ASSR => {
                io[a] = (io[a] & 0x1F) | (v & 0x60);
                if (v & 0x20 == 0) {
                    d.st.async_pending = @splat(0);
                    io[a] &= 0x60;
                }
            },
            GTCCR => {
                io[a] = v & 0x80;
                if (v & 0x01 != 0) d.st.pre01 = 0;
                if (v & 0x02 != 0) d.st.pre2 = 0;
                if (v & 0x80 != 0) io[a] |= v & 0x03; // TSM holds the prescalers in reset
            },
            TCCR0B, TCCR2B => {
                io[a] = v & 0x0F;
                const n: u2 = if (a == TCCR0B) 0 else 2;
                const ca: u16 = if (n == 0) TCCR0A else TCCR2A;
                const wgm = ((io[a] >> 1) & 4) | (io[ca] & 3);
                if (wgm == 0 or wgm == 2) {
                    for (0..2) |c| if (v & (@as(u8, 0x80) >> @intCast(c)) != 0) {
                        const level = if (n == 0) &d.st.oc0[c] else if (c == 0) &d.st.oc2a else &d.st.oc2b;
                        compareOutput(level, @truncate(io[ca] >> @intCast(6 - 2 * c)), false, false, true, false, false, false, false);
                    };
                }
                d.pinChange();
                d.owDrive();
            },
            TCNT0, TCNT2 => {
                io[a] = v;
                d.st.compare8_blocked[if (a == TCNT0) @as(usize, 0) else 2] = 1;
            },
            SPSR => io[a] = (io[a] & 0xFE) | (v & 0x01),
            SPDR => {
                d.spiClearSeen();
                d.st.spi_tx = v;
                if (io[SPCR] & 0x50 == 0x50 and io[PRR] & PRSPI == 0 and d.st.master_busy == 0) {
                    d.st.master_busy = 8 * spiDivider(io);
                } else if (d.st.master_busy != 0) io[SPSR] |= 0x40; // WCOL
            },
            UCSR0A, UCSR1A, UCSR2A, UCSR3A => {
                io[a] = (io[a] & ~@as(u8, 0x03)) | (v & 0x03); // U2X, MPCM
                if (v & 0x40 != 0) io[a] &= ~@as(u8, 0x40); // TXC is write-one-to-clear
            },
            UCSR0A + 6, UCSR1A + 6, UCSR2A + 6, UCSR3A + 6 => {
                const n: u2 = uartIndex(a - 6);
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
                const config = (v & 8) | (if (d.st.ee_busy != 0) io[a] & 0x30 else v & 0x30);
                if (v & 0x02 != 0 and mpe and d.st.ee_busy == 0 and d.st.spm_busy == 0) {
                    if (!d.mega and d.st.spm_buffer_state == .loaded) d.st.spm_buffer_state = .invalid;
                    d.st.ee_busy = @intCast(d.fCpu() * 34 / 10_000); // 3.4 ms
                    d.st.ee_pending = .{ .address = d.eeAddr(), .data = io[EEDR], .mode = (config >> 4) & 3 };
                    d.st.ee_window = 0;
                    io[a] = config | 0x02;
                } else {
                    io[a] = (io[a] & 0x02) | config | (if (mpe or v & 0x04 != 0) @as(u8, 0x04) else 0);
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
            ACSR => {
                io[a] = (io[a] & 0x30 & ~(v & 0x10)) | (v & 0xCF);
                d.comparatorRefresh();
                d.timerPinEdges();
            },
            ADCSRA => {
                const flags = io[a] & 0x10;
                io[a] = (v & 0xEF) | (flags & ~(v & 0x10)); // ADIF write-one-to-clear
                if (v & 0x80 == 0) {
                    io[a] &= ~@as(u8, 0x40);
                    d.st.adc_busy = 0;
                    d.st.adc_first = 1;
                } else if (v & 0x40 != 0 and d.st.adc_busy == 0) d.adcStart(false) else if (d.st.adc_busy != 0) io[a] |= 0x40; // ADSC: writing 0 has no effect
                d.comparatorRefresh();
            },
            ADCL, ADCH => {},
            else => io[a] = v,
        }
        if (a >= 0x20 and a <= 0x2B) {
            d.pinChange();
            d.owDrive();
        }
    }

    fn twiStatus(d: *Devices, status: u8) void {
        d.st.io[TWSR] = (d.st.io[TWSR] & 3) | status;
        d.st.io[TWCR] |= 0x80;
    }

    fn twiCapture(d: *Devices, event: TwiEvent) void {
        const t = &d.st.twi;
        if (t.out_tail +% 1 == t.out_head) {
            t.out_dropped +|= 1;
            return;
        }
        t.out_ring[t.out_tail] = event;
        t.out_tail +%= 1;
    }

    fn twiControl(d: *Devices, value: u8) void {
        const io = &d.st.io;
        const t = &d.st.twi;
        const old_interrupt = io[TWCR] & 0x80;
        io[TWCR] = (value & 0x75) | (io[TWCR] & 8) | (old_interrupt & ~(value & 0x80));
        if (value & 4 == 0) {
            t.busy = 0;
            t.action = .none;
            t.master = 0;
            t.slave = 0;
            return;
        }
        if (value & 0x80 == 0) return;
        if (value & 0x10 != 0) {
            if (t.master == 0) {
                io[TWCR] &= ~@as(u8, 0x10);
                t.slave = 0;
                return;
            }
            t.action = .stop;
        } else if (value & 0x20 != 0) {
            t.action = .start;
        } else if (t.master != 0) {
            t.action = switch (io[TWSR] & 0xF8) {
                0x08, 0x10 => .address,
                0x18, 0x20, 0x28, 0x30 => .write,
                0x40, 0x50 => .read,
                else => .none,
            };
        } else return; // slave waits for the external master's next byte
        if (t.action == .none) return;
        const bit_cycles: u32 = 16 + 2 * @as(u32, io[TWBR]) * (@as(u32, 1) << @intCast(2 * (io[TWSR] & 3)));
        t.busy = bit_cycles * (if (t.action == .start or t.action == .stop) @as(u32, 1) else 9);
        t.reply = .nack;
        t.reply_value = 0xFF;
    }

    fn twiDone(d: *Devices) void {
        const io = &d.st.io;
        const t = &d.st.twi;
        const action = t.action;
        t.action = .none;
        if (action != .start and action != .stop) {
            if (t.reply == .arbitration_lost or t.reply == .bus_error) {
                t.master = 0;
                t.slave = 0;
                d.twiStatus(if (t.reply == .arbitration_lost) @as(u8, 0x38) else 0);
                return;
            }
        }
        switch (action) {
            .none => {},
            .start => {
                d.twiCapture(.{ .kind = .start });
                d.twiStatus(if (t.master != 0) @as(u8, 0x10) else 0x08);
                t.master = 1;
                t.slave = 0;
            },
            .stop => {
                d.twiCapture(.{ .kind = .stop });
                t.master = 0;
                io[TWCR] &= ~@as(u8, 0x10);
                io[TWSR] = (io[TWSR] & 3) | 0xF8;
                if (io[TWCR] & 0x20 != 0) d.twiControl(io[TWCR] | 0x80);
            },
            .address => {
                d.twiCapture(.{ .kind = .address, .value = io[TWDR] });
                const read_mode = io[TWDR] & 1 != 0;
                const ack = t.reply == .ack;
                d.twiStatus(if (read_mode) (if (ack) @as(u8, 0x40) else 0x48) else (if (ack) @as(u8, 0x18) else 0x20));
            },
            .write => {
                d.twiCapture(.{ .kind = .write, .value = io[TWDR] });
                d.twiStatus(if (t.reply == .ack) @as(u8, 0x28) else 0x30);
            },
            .read => {
                io[TWDR] = t.reply_value;
                d.twiCapture(.{ .kind = .read, .value = io[TWDR] });
                d.twiStatus(if (io[TWCR] & 0x40 != 0) @as(u8, 0x50) else 0x58);
            },
        }
    }

    fn eeAddr(d: *const Devices) u12 {
        const mask: u8 = if (d.mega) 15 else 1;
        return @intCast(@as(u16, d.st.io[EEARH] & mask) << 8 | d.st.io[EEARL]);
    }

    fn spiClearSeen(d: *Devices) void {
        if (d.st.spif_seen != 0) {
            d.st.io[SPSR] &= ~@as(u8, 0xC0);
            d.st.spif_seen = 0;
        }
    }

    fn spiDivider(io: *const [0x200]u8) u32 {
        const sel = (io[SPCR] & 3) | @as(u8, io[SPSR] & 1) << 2;
        const divs = [8]u32{ 4, 16, 64, 128, 2, 8, 32, 64 };
        return divs[sel];
    }

    fn extCount(d: *const Devices) usize {
        return if (d.mega) 8 else 3;
    }

    fn extLevels(d: *const Devices) u8 {
        if (d.mega) return (d.pin(3) & 0x0F) | (d.pin(4) & 0xF0);
        return ((d.pin(3) >> 2) & 3) | (d.pin(1) & 4);
    }

    fn extMode(d: *const Devices, n: usize) u2 {
        return @truncate(d.st.io[if (n < 4) @as(usize, EICRA) else EICRB] >> @intCast((n % 4) * 2));
    }

    fn externalInterrupts(d: *Devices) void {
        const now = d.extLevels();
        for (0..d.extCount()) |n| {
            const bit = @as(u8, 1) << @intCast(n);
            const changed = (now ^ d.st.ext_last) & bit != 0;
            const clocked = d.externalEdgeClock(n);
            const mode = d.extMode(n);
            if (mode == 0) {
                d.st.io[EIFR] &= ~bit;
            } else if (clocked and changed and (mode == 1 or (mode == 2 and now & bit == 0) or (mode == 3 and now & bit != 0))) {
                const rising = d.st.io[EIFR] & bit == 0;
                d.st.io[EIFR] |= bit;
                if (n == 0 and rising) d.adcTrigger(2);
            }
            if (clocked) d.st.ext_last = (d.st.ext_last & ~bit) | (now & bit);
        }
    }

    fn externalEdgeClock(d: *const Devices, n: usize) bool {
        return d.ioRunning() or (d.mega and n < 4);
    }

    fn extPending(d: *const Devices) ?u8 {
        const levels = d.extLevels();
        for (0..d.extCount()) |n| {
            const bit = @as(u8, 1) << @intCast(n);
            if (d.st.io[EIMSK] & bit == 0) continue;
            if (if (d.extMode(n) == 0) levels & bit == 0 else d.st.io[EIFR] & bit != 0)
                return @intCast(n + 1);
        }
        return null;
    }

    fn timerClockLevel(d: *const Devices, n: usize) u8 {
        if (!d.mega) return (d.pin(1) >> @intCast(n)) & 1;
        return switch (n) {
            0 => (d.pin(3) >> 7) & 1,
            1 => (d.pin(3) >> 6) & 1,
            2 => (d.pin(4) >> 6) & 1,
            3 => (d.pin(7) >> 7) & 1,
            4 => (d.pin(10) >> 2) & 1,
            else => unreachable,
        };
    }

    fn captureLevel(d: *const Devices, n: usize) u8 {
        if (n == 0 and d.st.io[ACSR] & 4 != 0) return (d.st.io[ACSR] >> 5) & 1;
        if (!d.mega) return (d.pin(3) >> 6) & 1;
        return switch (n) {
            0 => (d.pin(3) >> 4) & 1,
            1 => (d.pin(4) >> 7) & 1,
            2 => d.pin(10) & 1,
            3 => (d.pin(10) >> 1) & 1,
            else => unreachable,
        };
    }

    fn seedTimerPins(d: *Devices) void {
        d.st.external0 = d.timerClockLevel(0);
        for (0..d.timerCount()) |n| {
            d.st.timer[n].external_last = d.timerClockLevel(n + 1);
            d.st.timer[n].capture_last = d.captureLevel(n);
            d.st.timer[n].capture_candidate = d.captureLevel(n);
        }
    }

    fn timerPinEdges(d: *Devices) void {
        if (!d.ioRunning()) return;
        const level0 = d.timerClockLevel(0);
        const previous0 = d.st.external0;
        d.st.external0 = level0;
        const clock0 = d.st.io[TCCR0B] & 7;
        if (level0 != previous0 and (clock0 == 6 or clock0 == 7) and level0 == clock0 - 6 and d.st.io[PRR] & PRTIM0 == 0) d.timer8(0, 1);
        for (timer16_bases[0..d.timerCount()], 0..) |base, n| {
            const t = &d.st.timer[n];
            const level = d.timerClockLevel(n + 1);
            const previous = t.external_last;
            t.external_last = level;
            const clock = d.st.io[base + 1] & 7;
            if (level != previous and (clock == 6 or clock == 7) and level == clock - 6 and d.timerPowered(n)) d.timer16(n, 1);
            d.captureInput(n);
        }
    }

    fn captureInputs(d: *Devices) void {
        if (!d.ioRunning()) return;
        for (0..d.timerCount()) |n| d.captureInput(n);
    }

    fn captureInput(d: *Devices, n: usize) void {
        if (!d.timerPowered(n)) return;
        const t = &d.st.timer[n];
        const capture = d.captureLevel(n);
        if (capture != t.capture_candidate) {
            t.capture_candidate = capture;
            t.capture_cycles = 0;
        }
        if (d.st.io[timer16_bases[n] + 1] & 0x80 == 0) d.captureEdge(n, capture);
    }

    fn timerPowered(d: *const Devices, n: usize) bool {
        const power: u8 = if (n == 0) PRTIM1 else @as(u8, 1) << @intCast(n + 2);
        return d.st.io[if (n == 0) @as(usize, PRR) else 0x65] & power == 0;
    }

    fn captureEdge(d: *Devices, n: usize, level: u8) void {
        const t = &d.st.timer[n];
        if (level == t.capture_last) return;
        t.capture_last = level;
        const control = d.st.io[timer16_bases[n] + 1];
        const wgm = ((control >> 1) & 0xC) | (d.st.io[timer16_bases[n]] & 3);
        if (wgm == 8 or wgm == 10 or wgm == 12 or wgm == 14) return; // ICRn supplies TOP.
        if (level == ((control >> 6) & 1)) {
            t.capture = t.count;
            d.timerFlags(timer16_flags[n], 0x20);
        }
    }

    fn pinChange(d: *Devices) void {
        d.externalInterrupts();
        d.timerPinEdges();
        if (d.mega) {
            const now = [_]u8{ d.pin(1), (d.pin(4) & 1) | (d.pin(8) << 1), d.pin(9) };
            for (now, 0..) |value, p| {
                if ((value ^ d.st.pin_last[p]) & d.st.io[PCMSK0 + p] != 0)
                    d.st.io[PCIFR] |= @as(u8, 1) << @intCast(p);
                d.st.pin_last[p] = value;
            }
            return;
        }
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
        if (d.st.fuse.high & 0x10 == 0) nv = (nv | 0x08) & ~@as(u8, 0x40);
        if (v & 0x18 == 0x18) d.st.wdt_window = 4;
        io[WDTCSR] = nv | (old & 0x80 & ~(v & 0x80));
    }

    fn wdtPeriod(d: *const Devices) u64 {
        const p = d.st.io[WDTCSR];
        const wdp: u6 = @intCast(@min((p & 7) | ((p >> 2) & 8), 9));
        // 2048 << wdp cycles of the 128 kHz oscillator, in CPU cycles
        return (@as(u64, 2048) << wdp) * d.fCpu() / 128_000;
    }

    fn comparatorRefresh(d: *Devices) void {
        const io = &d.st.io;
        if (io[ACSR] & 0x80 != 0) {
            d.st.ac_delay = 0;
            return;
        }
        const positive = if (io[ACSR] & 0x40 != 0) d.st.bandgap else d.st.comparator[0];
        const mux: u4 = @intCast((io[ADMUX] & 7) | (if (d.mega) io[ADCSRB] & 8 else @as(u8, 0)));
        const negative = if (io[ADCSRB] & 0x40 != 0 and io[ADCSRA] & 0x80 == 0 and io[PRR] & PRADC == 0) d.analogIn(mux) else d.st.comparator[1];
        const next: u8 = @intFromBool(positive > negative);
        if (next == (io[ACSR] >> 5) & 1) {
            d.st.ac_delay = 0;
        } else if (d.st.ac_delay == 0 or next != d.st.ac_candidate) {
            d.st.ac_candidate = next;
            d.st.ac_delay = 2;
        }
    }

    fn comparatorDone(d: *Devices) void {
        const io = &d.st.io;
        const next = d.st.ac_candidate;
        io[ACSR] = (io[ACSR] & ~@as(u8, 0x20)) | (next << 5);
        const mode = io[ACSR] & 3;
        if (mode == 0 or (mode == 2 and next == 0) or (mode == 3 and next != 0)) {
            const rising = io[ACSR] & 0x10 == 0;
            io[ACSR] |= 0x10;
            if (rising) d.adcTrigger(1);
        }
        if (io[ACSR] & 4 != 0) d.timerPinEdges();
    }

    fn adcTriggerLevel(d: *const Devices) bool {
        const io = &d.st.io;
        return switch (io[ADCSRB] & 7) {
            0 => false,
            1 => io[ACSR] & 0x10 != 0,
            2 => io[EIFR] & 1 != 0,
            3 => io[TIFR0] & 2 != 0,
            4 => io[TIFR0] & 1 != 0,
            5 => io[TIFR1] & 4 != 0,
            6 => io[TIFR1] & 1 != 0,
            7 => io[TIFR1] & 0x20 != 0,
            else => unreachable,
        };
    }

    fn timerFlags(d: *Devices, address: u16, flags: u8) void {
        const rising = flags & ~d.st.io[address];
        d.st.io[address] |= flags;
        if (address == TIFR0) {
            if (rising & 2 != 0) d.adcTrigger(3);
            if (rising & 1 != 0) d.adcTrigger(4);
        } else if (address == TIFR1) {
            if (rising & 4 != 0) d.adcTrigger(5);
            if (rising & 1 != 0) d.adcTrigger(6);
            if (rising & 0x20 != 0) d.adcTrigger(7);
        }
    }

    fn adcTrigger(d: *Devices, source: u3) void {
        const io = &d.st.io;
        if (d.adcRunning() and io[ADCSRA] & 0xA0 == 0xA0 and io[ADCSRB] & 7 == source and d.st.adc_busy == 0 and io[PRR] & PRADC == 0) d.adcStart(true);
    }

    // Conversion and sample-and-hold points follow the datasheet ADC Conversion Time table.
    fn adcStart(d: *Devices, auto: bool) void {
        const io = &d.st.io;
        const ps = [8]u32{ 2, 2, 4, 8, 16, 32, 64, 128 };
        // in half ADC clocks: conversion time, sample-and-hold point
        const conv: u32, const sh: u32 = if (d.st.adc_first != 0) .{ 50, 27 } else if (auto) .{ 27, 4 } else .{ 26, 3 };
        const half = ps[io[ADCSRA] & 7] / 2;
        d.st.adc_mux = (io[ADMUX] & 0x1F) | (if (d.mega) (io[ADCSRB] & 8) << 2 else @as(u8, 0));
        d.st.adc_first = 0;
        d.st.adc_busy = conv * half;
        d.st.adc_hold = (conv - sh) * half;
        d.st.adc_sampled = 0;
        io[ADCSRA] |= 0x40;
    }

    fn adcDone(d: *Devices) void {
        const io = &d.st.io;
        const v = d.st.adc_held;
        const res: u16 = if (io[ADMUX] & 0x20 != 0) v << 6 else v;
        if (d.st.adc_locked == 0) {
            io[ADCL] = @truncate(res);
            io[ADCH] = @truncate(res >> 8);
        }
        io[ADCSRA] = (io[ADCSRA] & ~@as(u8, 0x40)) | 0x10;
        if (io[ADCSRA] & 0xA0 == 0xA0 and io[ADCSRB] & 7 == 0) d.adcStart(false);
    }

    fn adcInput(d: *const Devices) u16 {
        const mux = d.st.adc_mux;
        const group: u4 = if (mux & 0x20 != 0) 8 else 0;
        const sel = mux & 0x1F;
        if (sel < 8) return d.analogIn(group + @as(u4, @intCast(sel)));
        if (sel == 31) return 0;
        if (sel == 30) return d.st.bandgap;
        const positive: u4, const negative: u4, const gain: i32 = if (sel < 16)
            .{ group + (if (sel < 12) @as(u4, 0) else 2) + @as(u4, @intCast(sel & 1)), group + (if (sel < 12) @as(u4, 0) else 2), if (sel & 2 == 0) 10 else 200 }
        else
            .{ group + @as(u4, @intCast(sel & 7)), group + (if (sel < 24) @as(u4, 1) else 2), 1 };
        const diff = (@as(i32, d.analogIn(positive)) - @as(i32, d.analogIn(negative))) * gain;
        const result: i16 = @intCast(std.math.clamp(@divTrunc(diff, 2), -512, 511));
        return @as(u16, @bitCast(result)) & 0x3FF;
    }

    fn uartFrameCycles(io: *const [0x200]u8, base: u16) u32 {
        const b = io[base + 1];
        const cc = io[base + 2];
        const ubrr: u32 = (@as(u32, io[base + 5] & 0x0F) << 8) | io[base + 4];
        const per_bit: u32 = (if (io[base] & 0x02 != 0) @as(u32, 8) else 16) * (ubrr + 1);
        const data: u32 = 5 + ((cc >> 1) & 3) + @as(u32, if (b & 0x04 != 0) 4 else 0);
        const bits = 1 + @min(data, 9) + @as(u32, if (cc & 0x20 != 0) 1 else 0) + @as(u32, if (cc & 0x08 != 0) 2 else 1);
        return bits * per_bit;
    }

    fn uartShift(d: *Devices, n: u2) void {
        const u = &d.st.usart[n];
        if (u.tx_busy != 0 or u.tx_full == 0) return;
        u.tx_shift = u.tx_buf;
        u.tx_full = 0;
        u.tx_busy = uartFrameCycles(&d.st.io, uart_bases[n]);
    }

    // ---- time ------------------------------------------------------------------------------

    fn pageSize(d: *const Devices) u32 {
        return if (d.mega) 256 else 128;
    }

    fn rwwLimit(d: *const Devices) u32 {
        return if (d.mega) 0x1E000 else 0x3800;
    }

    fn spmControl(d: *Devices, value: u8) void {
        const io = &d.st.io;
        if (d.st.ee_busy != 0) return;
        if (d.st.spm_busy != 0) {
            io[SPMCSR] = (io[SPMCSR] & 0x7F) | (value & 0x80);
            return;
        }
        const command = value & 0x3F;
        io[SPMCSR] = (io[SPMCSR] & 0x40) | (value & 0x80);
        switch (command) {
            1, 3, 5, 9, 0x11, 0x21 => {
                io[SPMCSR] |= command;
                d.st.spm_window = 4;
            },
            else => d.st.spm_window = 0,
        }
    }

    fn sysSpm(ctx: *anyopaque, cpu: *emu.Cpu, address: u32, word: u16) void {
        const d: *Devices = @ptrCast(@alignCast(ctx));
        const io = &d.st.io;
        if (cpu.st.pc < d.bootStart() or d.st.spm_window == 0 or d.st.spm_busy != 0 or d.st.ee_busy != 0) return;
        const command = io[SPMCSR] & 0x3F;
        d.st.spm_window = 0;
        d.program = cpu.prog;
        io[SPMCSR] &= 0xC0;
        switch (command) {
            1 => {
                if (d.st.spm_buffer_state == .invalid) return;
                const offset = (address & (d.pageSize() - 1)) & ~@as(u32, 1);
                d.st.spm_buffer[offset] &= @truncate(word);
                d.st.spm_buffer[offset + 1] &= @truncate(word >> 8);
                d.st.spm_buffer_state = .loaded;
                io[SPMCSR] &= ~@as(u8, 0x40);
            },
            3, 5 => {
                const byte_mask: u32 = if (d.mega) 0x1FFFF else 0x3FFF;
                const target = (address & byte_mask) & ~(d.pageSize() - 1);
                const boot = target >= @as(u32, d.bootStart()) * 2;
                if (d.st.fuse.lock & (if (boot) @as(u8, 0x10) else 4) == 0) return;
                if (command == 5 and d.st.spm_buffer_state == .invalid) {
                    cpu.stop = .undefined_spm_buffer;
                    return;
                }
                d.st.spm_address = target;
                d.st.spm_pending = d.st.spm_buffer;
                d.st.spm_operation = command;
                // Use the specified maximum 4.5 ms rather than inventing per-chip RC calibration.
                d.st.spm_busy = @intCast(d.fCpu() * 45 / 10_000);
                d.st.spm_nrww = @intFromBool(target >= d.rwwLimit());
                io[SPMCSR] |= command;
                if (d.st.spm_nrww == 0) io[SPMCSR] |= 0x40;
            },
            9 => {
                d.st.spm_pending[0] = @truncate(word);
                d.st.spm_operation = command;
                d.st.spm_busy = @intCast(d.fCpu() * 45 / 10_000);
                io[SPMCSR] |= command;
            },
            0x11 => {
                d.st.spm_buffer = @splat(0xFF);
                d.st.spm_buffer_state = .empty;
                io[SPMCSR] &= ~@as(u8, 0x40);
            },
            else => {},
        }
    }

    fn spmDone(d: *Devices) void {
        if (d.st.spm_operation == 9) {
            d.st.fuse.lock &= d.st.spm_pending[0] | 0xC0;
        } else if (d.program) |program| {
            const target = d.st.spm_address;
            const size = d.pageSize();
            if (d.st.spm_operation == 3) {
                @memset(program[target..][0..size], 0xFF);
            } else if (d.st.spm_operation == 5) {
                for (program[target..][0..size], d.st.spm_pending[0..size]) |*byte, value| byte.* &= value;
                d.st.spm_buffer = @splat(0xFF);
                d.st.spm_buffer_state = .empty;
            }
        }
        d.st.spm_nrww = 0;
        d.st.spm_operation = 0;
        d.st.io[SPMCSR] &= 0xC0;
    }

    fn sysProgramRead(ctx: *anyopaque, address: u32, pc: u16) ?u8 {
        const d: *Devices = @ptrCast(@alignCast(ctx));
        const io = &d.st.io;
        if (d.st.spm_window != 0) {
            const command = io[SPMCSR] & 0x3F;
            if (command == 9 or command == 0x21) {
                io[SPMCSR] &= 0xC0;
                d.st.spm_window = 0;
                if (command == 9) return switch (address) {
                    0 => d.st.fuse.low,
                    1 => d.st.fuse.lock,
                    2 => d.st.fuse.extended,
                    3 => d.st.fuse.high,
                    else => 0,
                };
                return switch (address) {
                    0 => 0x1E,
                    1 => d.st.io[0x66],
                    2 => if (d.mega) @as(u8, 0x97) else 0x94,
                    4 => if (d.mega) @as(u8, 3) else 0x0A,
                    else => 0,
                };
            }
        }
        const boot = @as(u32, d.bootStart()) * 2;
        if ((address >= boot and pc < d.bootStart() and d.st.fuse.lock & 0x20 == 0) or
            (address < boot and pc >= d.bootStart() and d.st.fuse.lock & 8 == 0)) return 0;
        if (address < d.rwwLimit() and io[SPMCSR] & 0x40 != 0) return 0xFF;
        return null;
    }

    fn sysBlocked(ctx: *anyopaque, pc: u16) bool {
        const d: *Devices = @ptrCast(@alignCast(ctx));
        return d.st.spm_nrww != 0 or (d.st.io[SPMCSR] & 0x40 != 0 and @as(u32, pc) * 2 < d.rwwLimit());
    }

    fn sysInterruptsEnabled(ctx: *anyopaque, pc: u16) bool {
        const d: *Devices = @ptrCast(@alignCast(ctx));
        if (d.st.mcu_window != 0) return false;
        if (d.st.mcu_irq_hold != 0) {
            d.st.mcu_irq_hold = 0;
            return false;
        }
        const relocated = d.st.io[MCUCR] & 2 != 0;
        return !((relocated and pc < d.bootStart() and d.st.fuse.lock & 8 == 0) or
            (!relocated and pc >= d.bootStart() and d.st.fuse.lock & 0x20 == 0));
    }

    fn sysInterruptBase(ctx: *anyopaque) u16 {
        const d: *Devices = @ptrCast(@alignCast(ctx));
        return if (d.st.io[MCUCR] & 2 != 0) d.bootStart() else 0;
    }

    fn sysBitWriteValue(ctx: *anyopaque, address: u16, bit: u3, set: bool) ?u8 {
        const d: *Devices = @ptrCast(@alignCast(ctx));
        if (d.portFor(address)) |p| if (address == port_bases[p]) return if (set) @as(u8, 1) << bit else 0;
        if (address == TIFR0 or address == TIFR1 or address == TIFR2 or
            (d.mega and address >= 0x38 and address <= 0x3A) or address == PCIFR or address == EIFR)
            return if (set) @as(u8, 1) << bit else 0;
        return null;
    }

    fn sysTick(ctx: *anyopaque, cycles: u32) void {
        const d: *Devices = @ptrCast(@alignCast(ctx));
        d.tick(cycles);
    }

    pub fn tick(d: *Devices, cycles: u32) void {
        if (cycles > 1 and d.adcRunning() and d.st.io[PRR] & PRADC == 0 and
            (d.st.adc_busy != 0 or d.st.io[ADCSRA] & 0xA0 == 0xA0))
        {
            // A timer edge can start or finish a conversion inside an instruction's clocks.
            for (0..cycles) |_| d.tick(1);
            return;
        }
        if (cycles > 1 and d.ioRunning()) {
            if (d.st.ac_delay != 0) {
                d.tick(1);
                d.tick(cycles - 1);
                return;
            }
            for (timer16_bases[0..d.timerCount()], 0..) |base, n| {
                const t = &d.st.timer[n];
                if (d.timerPowered(n) and d.st.io[base + 1] & 0x80 != 0 and t.capture_last != t.capture_candidate) {
                    const until = @min(cycles, 4 - @min(t.capture_cycles, @as(u8, 4)));
                    for (0..until) |_| d.tick(1);
                    d.tick(cycles - until);
                    return;
                }
            }
        }
        const io = &d.st.io;
        d.st.cycles += cycles;
        if (d.ioRunning() and d.st.ac_delay != 0) {
            d.st.ac_delay -|= @intCast(@min(cycles, 2));
            if (d.st.ac_delay == 0) d.comparatorDone();
        }
        d.st.jtd_window -|= @intCast(@min(cycles, 4));
        if (d.st.bod_window != 0) {
            d.st.bod_window -|= @intCast(@min(cycles, 4));
            if (d.st.bod_window == 0) io[MCUCR] &= ~@as(u8, 0x60);
        }
        if (d.st.bod_active != 0) {
            d.st.bod_active -|= @intCast(@min(cycles, 3));
            if (d.st.bod_active == 0) io[MCUCR] &= ~@as(u8, 0x40);
        }
        if (d.st.mcu_window != 0) {
            d.st.mcu_window -|= @intCast(@min(cycles, 4));
            if (d.st.mcu_window == 0) io[MCUCR] &= ~@as(u8, 1);
        }
        if (d.st.spm_window != 0) {
            d.st.spm_window -|= @intCast(@min(cycles, 4));
            if (d.st.spm_window == 0 and d.st.spm_busy == 0) io[SPMCSR] &= 0xC0;
        }
        d.tickReset(cycles);
        if (d.st.ee_window > 0) {
            d.st.ee_window -|= @intCast(@min(cycles, 255));
            if (d.st.ee_window == 0) io[EECR] &= ~@as(u8, 0x04);
        }
        if (d.st.wdt_window > 0) d.st.wdt_window -|= @intCast(@min(cycles, 255));
        if (d.st.clk_window > 0) d.st.clk_window -|= @intCast(@min(cycles, 255));
        // before the timers: a conversion they trigger in this tick counts from the next one
        if (d.adcRunning() and d.st.adc_busy > 0 and io[PRR] & PRADC == 0) {
            d.st.adc_busy -|= cycles;
            if (d.st.adc_sampled == 0 and d.st.adc_busy <= d.st.adc_hold) {
                d.st.adc_held = d.adcInput();
                d.st.adc_sampled = 1;
            }
            if (d.st.adc_busy == 0) d.adcDone();
        }
        // Synchronous timers share a prescaler; Timer2 has its own (GTCCR.TSM holds them).
        const old01 = d.st.pre01;
        const old2 = d.st.pre2;
        if (d.ioRunning() and io[GTCCR] & 0x81 != 0x81) d.st.pre01 += cycles;
        if (d.timer2Running() and io[GTCCR] & 0x82 != 0x82 and io[ASSR] & 0x20 == 0) d.st.pre2 += cycles;
        const div01 = [8]u64{ 0, 1, 8, 64, 256, 1024, 0, 0 };
        const div2 = [8]u64{ 0, 1, 8, 32, 64, 128, 256, 1024 };
        // External clocks arrive through GPIO edges; asynchronous Timer2 uses host oscillator ticks.
        if (io[PRR] & PRTIM0 == 0) d.timer8(0, ticks(old01, d.st.pre01, div01[io[TCCR0B] & 7]));
        for (timer16_bases[0..d.timerCount()], 0..) |base, n| {
            if (d.timerPowered(n))
                d.timer16(n, ticks(old01, d.st.pre01, div01[io[base + 1] & 7]));
        }
        if (d.timer2Running() and io[PRR] & PRTIM2 == 0 and io[ASSR] & 0x20 == 0) d.timer8(2, ticks(old2, d.st.pre2, div2[io[TCCR2B] & 7]));
        for (timer16_bases[0..d.timerCount()], 0..) |base, n| {
            if (d.ioRunning() and d.timerPowered(n) and io[base + 1] & 0x80 != 0) {
                const t = &d.st.timer[n];
                t.capture_cycles = @min(4, t.capture_cycles +| @as(u8, @intCast(@min(cycles, 4))));
                if (t.capture_cycles >= 4) d.captureEdge(n, t.capture_candidate);
            }
        }
        for (0..d.uartCount()) |k| {
            const mask: u8 = if (k == 0) PRUSART0 else if (d.mega) @as(u8, 1) << @intCast(k - 1) else PRUSART1;
            if (d.ioRunning() and io[if (d.mega and k > 0) 0x65 else PRR] & mask == 0) d.uartTick(@intCast(k), cycles);
        }
        if (d.ioRunning() and io[PRR] & 0x80 == 0) {
            var remaining = cycles;
            while (d.st.twi.busy != 0 and remaining >= d.st.twi.busy) {
                remaining -= d.st.twi.busy;
                d.st.twi.busy = 0;
                d.twiDone();
            }
            d.st.twi.busy -|= remaining;
        }
        if (d.ioRunning() and io[PRR] & PRSPI == 0 and d.st.master_busy > 0) {
            d.st.master_busy -|= cycles;
            if (d.st.master_busy == 0) {
                d.st.spi_rx = d.st.master_in;
                io[SPSR] |= 0x80;
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

    /// Nonvolatile programming has its own clock and continues while external reset is held.
    pub fn tickReset(d: *Devices, cycles: u32) void {
        if (d.st.spm_busy != 0) {
            d.st.spm_busy -|= cycles;
            if (d.st.spm_busy == 0) d.spmDone();
        }
        if (d.st.ee_busy != 0) {
            d.st.ee_busy -|= cycles;
            if (d.st.ee_busy == 0) {
                const transaction = d.st.ee_pending;
                if (transaction.mode != 2) d.st.ee[transaction.address] = 0xFF; // erase
                if (transaction.mode != 1) d.st.ee[transaction.address] &= transaction.data; // write
                d.st.io[EECR] &= ~@as(u8, 0x02);
            }
        }
    }

    fn ticks(old: u64, new: u64, div: u64) u64 {
        if (div == 0) return 0;
        return new / div - old / div;
    }

    fn uartTick(d: *Devices, n: u2, cycles: u32) void {
        const u = &d.st.usart[n];
        const base: u16 = uart_bases[n];
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
            } else u.out_dropped +|= 1;
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
            const old_compare = [_]u8{ oa.*, ob.* };
            const was_down = d.st.down[n] != 0;
            const blocked = d.st.compare8_blocked[n] != 0;
            d.st.compare8_blocked[n] = 0;
            const top_match = old == top and !(blocked and (wgm == 2 or wgm == 5 or wgm == 7));
            var flags: u8 = 0;
            if (!blocked and old == oa.*) flags |= 2; // OCFnA
            if (!blocked and old == ob.*) flags |= 4; // OCFnB
            const phase = wgm == 1 or wgm == 5;
            if (phase) {
                const down = &d.st.down[n];
                if (down.* == 0) {
                    if (top_match) {
                        down.* = 1;
                        io[rc] = old -% 1;
                        oa.* = io[roa];
                        ob.* = io[rob];
                    } else io[rc] = old +% 1;
                } else {
                    if (old == 0 and !blocked) {
                        down.* = 0;
                        io[rc] = 1;
                    } else {
                        io[rc] = old -% 1;
                        if (old == 1) flags |= 1; // TOV at BOTTOM
                    }
                }
            } else if (top_match) {
                io[rc] = 0;
                if (wgm != 2 or top == 0xFF) flags |= 1; // TOV at MAX/TOP (CTC: at MAX only)
                if (pwm) {
                    oa.* = io[roa];
                    ob.* = io[rob];
                }
            } else {
                io[rc] = old +% 1;
                if (wgm == 2 and old == 0xFF) flags |= 1; // CTC missed TOP still overflows at MAX.
            }
            d.timerFlags(rf, flags);
            var changed = false;
            for (0..2) |c| {
                if (!d.output8Enabled(n, c)) continue;
                const level = if (n == 0) &d.st.oc0[c] else if (c == 0) &d.st.oc2a else &d.st.oc2b;
                const before = level.*;
                const compare = old_compare[c];
                compareOutput(level, @truncate(io[ra] >> @intCast(6 - 2 * c)), pwm, phase, flags & (@as(u8, 2) << @intCast(c)) != 0, top_match and !phase, was_down, compare == top, compare == 0);
                changed = changed or level.* != before;
            }
            if (changed) {
                d.pinChange();
                d.owDrive();
            }
        }
    }

    fn compareOutput(level: *u8, com: u2, pwm: bool, phase: bool, match: bool, bottom: bool, down: bool, compare_top: bool, compare_zero: bool) void {
        if (com == 0) return;
        if (!pwm or com == 1) {
            if (match) level.* = switch (com) {
                1 => level.* ^ 1,
                2 => 0,
                3 => 1,
                0 => level.*,
            };
        } else if (phase) {
            if (compare_top) level.* = @intFromBool(com == 2) else if (compare_zero) level.* = @intFromBool(com == 3) else if (match) level.* = @intFromBool(if (com == 2) down else !down);
        } else {
            if (match and !compare_top) level.* = @intFromBool(com == 3);
            if (bottom) level.* = @intFromBool(com == 2);
        }
    }

    fn timerFor(d: *const Devices, a: u16) ?usize {
        for (timer16_bases[0..d.timerCount()], 0..) |base, n| {
            const end: u16 = if (d.mega) 14 else 12;
            if (a >= base and a < base + end and a != base + 3) return n;
        }
        return null;
    }

    fn timerPwm(io: *const [0x200]u8, n: usize) bool {
        const base = timer16_bases[n];
        const wgm = ((io[base + 1] >> 1) & 0xC) | (io[base] & 3);
        return wgm != 0 and wgm != 4 and wgm != 12 and wgm != 13;
    }

    fn timerRead(d: *Devices, n: usize, off: u16) u8 {
        const t = &d.st.timer[n];
        switch (off) {
            2 => return 0, // Force-output-compare bits are write-only.
            4, 6 => {
                const value = if (off == 4) t.count else t.capture;
                t.temp = @truncate(value >> 8);
                return @truncate(value);
            },
            5, 7 => return t.temp,
            8...13 => {
                const value = t.buffered[(off - 8) / 2];
                return if (off & 1 == 0) @truncate(value) else @truncate(value >> 8);
            },
            else => return d.st.io[timer16_bases[n] + off],
        }
    }

    fn timerWrite(d: *Devices, n: usize, off: u16, value: u8) void {
        const t = &d.st.timer[n];
        switch (off) {
            2 => {
                if (!timerPwm(&d.st.io, n)) {
                    for (0..if (d.mega) @as(usize, 3) else 2) |c| if (value & (@as(u8, 0x80) >> @intCast(c)) != 0) {
                        compareOutput(&t.output[c], @truncate(d.st.io[timer16_bases[n]] >> @intCast(6 - 2 * c)), false, false, true, false, false, false, false);
                    };
                    d.pinChange();
                }
            },
            5, 7, 9, 11, 13 => t.temp = value,
            4 => {
                t.count = @as(u16, t.temp) << 8 | value;
                t.compare_blocked = 1;
            },
            6 => {
                const base = timer16_bases[n];
                const wgm = ((d.st.io[base + 1] >> 1) & 0xC) | (d.st.io[base] & 3);
                if (wgm == 8 or wgm == 10 or wgm == 12 or wgm == 14)
                    t.capture = @as(u16, t.temp) << 8 | value;
            },
            8, 10, 12 => {
                const c = (off - 8) / 2;
                const base = timer16_bases[n];
                const mode = ((d.st.io[base + 1] >> 1) & 0xC) | (d.st.io[base] & 3);
                const mask: u16 = switch (mode) {
                    1, 5 => 0xFF,
                    2, 6 => 0x1FF,
                    3, 7 => 0x3FF,
                    else => 0xFFFF,
                };
                t.buffered[c] = (@as(u16, t.temp) << 8 | value) & mask;
                if (!timerPwm(&d.st.io, n)) t.compare[c] = t.buffered[c];
            },
            else => {
                d.st.io[timer16_bases[n] + off] = value;
                d.pinChange();
            },
        }
    }

    fn timer16(d: *Devices, n: usize, k: u64) void {
        const io = &d.st.io;
        const t = &d.st.timer[n];
        const base = timer16_bases[n];
        const wgm = ((io[base + 1] >> 1) & 0xC) | (io[base] & 3);
        const phase = (wgm >= 1 and wgm <= 3) or (wgm >= 8 and wgm <= 11);
        const ctc = wgm == 4 or wgm == 12;
        var i: u64 = 0;
        while (i < k) : (i += 1) {
            const top: u16 = switch (wgm) {
                0, 13 => 0xFFFF,
                1, 5 => 0x00FF,
                2, 6 => 0x01FF,
                3, 7 => 0x03FF,
                4, 9, 11, 15 => t.compare[0],
                else => t.capture,
            };
            const old = t.count;
            const was_down = t.down != 0;
            const old_compare = t.compare;
            const blocked = t.compare_blocked != 0;
            t.compare_blocked = 0;
            const top_match = old == top and !(blocked and (ctc or (wgm >= 8 and wgm != 13)));
            var flags: u8 = 0;
            for (t.compare[0..if (d.mega) @as(usize, 3) else 2], 0..) |compare, c| {
                if (!blocked and old == compare) flags |= @as(u8, 2) << @intCast(c);
            }
            if (phase) {
                if (t.down == 0) {
                    if (top_match) {
                        t.down = 1;
                        t.count = old -% 1;
                        if (wgm == 10 or wgm == 11 or wgm <= 3) t.compare = t.buffered;
                    } else t.count = old +% 1;
                } else if (old == 0 and !blocked) {
                    t.down = 0;
                    t.count = 1;
                } else {
                    t.count = old -% 1;
                    if (old == 1) {
                        flags |= 1;
                        if (wgm == 8 or wgm == 9) t.compare = t.buffered;
                    }
                }
                if ((wgm == 8 or wgm == 10) and !was_down and t.count == top) flags |= 0x20;
            } else if (top_match) {
                t.count = 0;
                if (!ctc or top == 0xFFFF) flags |= 1;
                if (wgm == 12 or wgm == 14) flags |= 0x20;
                if (!ctc and wgm != 0) t.compare = t.buffered;
            } else {
                t.count = old +% 1;
                if (ctc and old == 0xFFFF) flags |= 1;
            }
            d.timerFlags(timer16_flags[n], flags);
            var changed = false;
            for (old_compare[0..if (d.mega) @as(usize, 3) else 2], 0..) |compare, c| {
                if (!d.output16Enabled(n, c)) continue;
                const before = t.output[c];
                compareOutput(&t.output[c], @truncate(io[base] >> @intCast(6 - 2 * c)), timerPwm(io, n), phase, flags & (@as(u8, 2) << @intCast(c)) != 0, top_match and !phase, was_down, compare == top, compare == 0);
                changed = changed or t.output[c] != before;
            }
            if (changed) d.pinChange();
        }
    }

    // ---- interrupts ----------------------------------------------------------------------------

    fn sysPending(ctx: *anyopaque) ?u8 {
        const d: *Devices = @ptrCast(@alignCast(ctx));
        return if (d.st.sleeping != 0 and d.st.sleep_mode != 0) d.wakePending() else d.pending();
    }

    fn wakePending(d: *const Devices) ?u8 {
        const io = &d.st.io;
        var next: ?u8 = null;
        const levels = d.extLevels();
        for (0..d.extCount()) |n| {
            const bit = @as(u8, 1) << @intCast(n);
            if (io[EIMSK] & bit == 0) continue;
            const mode = d.extMode(n);
            if (mode != 0 and !d.externalEdgeClock(n)) continue;
            if (if (mode == 0) levels & bit == 0 else io[EIFR] & bit != 0)
                next = firstVector(next, @intCast(n + 1));
        }
        const pc = io[PCIFR] & io[PCICR];
        if (pc != 0) next = firstVector(next, d.vector(Vec.pcint0 + @as(u8, @ctz(pc))));
        if (io[WDTCSR] & 0xC0 == 0xC0) next = firstVector(next, d.vector(Vec.wdt));
        const twi_address = switch (io[TWSR] & 0xF8) {
            0x60, 0x68, 0x70, 0x78, 0xA8, 0xB0 => true,
            else => false,
        };
        if (twi_address and io[TWCR] & 0x85 == 0x85) next = firstVector(next, d.vector(Vec.twi));
        const adc_noise = d.st.sleep_mode == 1;
        if ((adc_noise and io[ASSR] & 0x20 != 0) or d.st.sleep_mode == 3 or d.st.sleep_mode == 7) {
            const flags = io[TIFR2] & io[TIMSK2] & 7;
            if (flags & 2 != 0) next = firstVector(next, d.vector(Vec.t2_compa));
            if (flags & 4 != 0) next = firstVector(next, d.vector(Vec.t2_compb));
            if (flags & 1 != 0) next = firstVector(next, d.vector(Vec.t2_ovf));
        }
        if (adc_noise) {
            if (io[ADCSRA] & 0x18 == 0x18) next = firstVector(next, d.vector(Vec.adc));
            if (d.eepromReady()) next = firstVector(next, d.vector(Vec.ee_ready));
            if (io[SPMCSR] & 0x81 == 0x80) next = firstVector(next, d.vector(Vec.spm_ready));
        }
        return next;
    }

    /// Lowest pending and enabled vector.
    pub fn pending(d: *const Devices) ?u8 {
        var next: ?u8 = d.extPending();
        if (d.pendingBase()) |vec| next = firstVector(next, d.vector(vec));
        for (0..d.timerCount()) |n| if (d.timerPending(n)) |vec| {
            next = firstVector(next, vec);
        };
        if (d.st.io[TWCR] & 0x85 == 0x85) next = firstVector(next, d.vector(Vec.twi));
        if (d.st.io[SPMCSR] & 0x81 == 0x80) next = firstVector(next, d.vector(Vec.spm_ready));
        if (d.mega) {
            if (d.usartPending(2)) |vec| next = firstVector(next, vec);
            if (d.usartPending(3)) |vec| next = firstVector(next, vec);
        }
        return next;
    }

    fn firstVector(previous: ?u8, candidate: u8) u8 {
        return if (previous) |old| @min(old, candidate) else candidate;
    }

    fn timerVector(d: *const Devices, n: usize) u8 {
        return if (!d.mega) Vec.t1_capt else ([_]u8{ 16, 31, 41, 46 })[n];
    }

    fn timerPending(d: *const Devices, n: usize) ?u8 {
        const flags = d.st.io[timer16_flags[n]] & d.st.io[timer16_masks[n]];
        const vector_number = d.timerVector(n);
        if (flags & 0x20 != 0) return vector_number;
        if (flags & 2 != 0) return vector_number + 1;
        if (flags & 4 != 0) return vector_number + 2;
        if (d.mega and flags & 8 != 0) return vector_number + 3;
        if (flags & 1 != 0) return vector_number + (if (d.mega) @as(u8, 4) else 3);
        return null;
    }

    fn eepromReady(d: *const Devices) bool {
        return d.st.io[EECR] & 0x0A == 0x08 and (d.mega or d.st.spm_busy == 0);
    }

    fn pendingBase(d: *const Devices) ?u8 {
        const io = &d.st.io;
        const pc = io[PCIFR] & io[PCICR];
        if (pc != 0) return Vec.pcint0 + @as(u8, @ctz(pc));
        if (io[WDTCSR] & 0xC0 == 0xC0) return Vec.wdt;
        const t2 = io[TIFR2] & io[TIMSK2] & 7;
        if (t2 & 2 != 0) return Vec.t2_compa;
        if (t2 & 4 != 0) return Vec.t2_compb;
        if (t2 & 1 != 0) return Vec.t2_ovf;
        const t0 = io[TIFR0] & io[TIMSK0] & 7;
        if (t0 & 2 != 0) return Vec.t0_compa;
        if (t0 & 4 != 0) return Vec.t0_compb;
        if (t0 & 1 != 0) return Vec.t0_ovf;
        if (io[SPSR] & 0x80 != 0 and io[SPCR] & 0x80 != 0) return Vec.spi;
        if (d.usartPending(0)) |v| return v;
        if (io[ACSR] & 0x18 == 0x18) return Vec.comparator;
        if (io[ADCSRA] & 0x18 == 0x18) return Vec.adc;
        if (d.eepromReady()) return Vec.ee_ready;
        return d.usartPending(1);
    }

    fn usartPending(d: *const Devices, n: u2) ?u8 {
        const base: u16 = uart_bases[n];
        const v0: u8 = ([_]u8{ Vec.usart0_rx, Vec.usart1_rx, 51, 54 })[n];
        const u = &d.st.usart[n];
        const b = d.st.io[base + 1];
        if (u.rx_n > 0 and b & 0x80 != 0) return v0;
        if (u.tx_full == 0 and b & 0x20 != 0) return v0 + 1;
        if (d.st.io[base] & 0x40 != 0 and b & 0x40 != 0) return v0 + 2;
        return null;
    }

    fn sysAck(ctx: *anyopaque, actual_vec: u8) void {
        const d: *Devices = @ptrCast(@alignCast(ctx));
        const io = &d.st.io;
        if (actual_vec >= 1 and actual_vec <= d.extCount()) {
            io[EIFR] &= ~(@as(u8, 1) << @intCast(actual_vec - 1));
            return;
        }
        for (0..d.timerCount()) |n| {
            const first = d.timerVector(n);
            const last = first + (if (d.mega) @as(u8, 4) else 3);
            if (actual_vec >= first and actual_vec <= last) {
                const bits = if (d.mega) &[_]u8{ 0x20, 2, 4, 8, 1 } else &[_]u8{ 0x20, 2, 4, 1 };
                io[timer16_flags[n]] &= ~bits[actual_vec - first];
                return;
            }
        }
        if (d.mega and (actual_vec == 53 or actual_vec == 56)) {
            io[if (actual_vec == 53) UCSR2A else UCSR3A] &= ~@as(u8, 0x40);
            return;
        }
        var vec = actual_vec;
        if (d.mega) {
            for (4..31) |old| {
                if (d.vector(@intCast(old)) == actual_vec) {
                    vec = @intCast(old);
                    break;
                }
            }
        }
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
            Vec.comparator => io[ACSR] &= ~@as(u8, 0x10),
            Vec.adc => io[ADCSRA] &= ~@as(u8, 0x10),
            else => {},
        }
    }

    fn sysSleep(ctx: *anyopaque) bool {
        const d: *Devices = @ptrCast(@alignCast(ctx));
        const mode = (d.st.io[SMCR] >> 1) & 7;
        return d.st.io[SMCR] & 1 != 0 and mode != 4 and mode != 5;
    }

    fn sysSleeping(ctx: *anyopaque, asleep: bool) void {
        const d: *Devices = @ptrCast(@alignCast(ctx));
        d.st.sleeping = @intFromBool(asleep);
        if (!asleep) {
            d.externalInterrupts();
            d.captureInputs();
            return;
        }
        d.st.sleep_mode = (d.st.io[SMCR] >> 1) & 7;
        if (d.st.sleep_mode <= 1 and d.st.io[ADCSRA] & 0x80 != 0 and d.st.adc_busy == 0 and d.st.io[PRR] & PRADC == 0) d.adcStart(false);
    }

    fn sysWakeCycles(ctx: *anyopaque) u32 {
        const d: *Devices = @ptrCast(@alignCast(ctx));
        // Crystal stabilization is a separate analog startup qualification; digital wake latency
        // is four clocks, or six for the crystal-running standby modes.
        return if (d.st.sleep_mode == 6 or d.st.sleep_mode == 7) 6 else 4;
    }

    fn ioRunning(d: *const Devices) bool {
        return d.st.sleeping == 0 or d.st.sleep_mode == 0;
    }

    fn adcRunning(d: *const Devices) bool {
        return d.st.sleeping == 0 or d.st.sleep_mode <= 1;
    }

    fn timer2Running(d: *const Devices) bool {
        return d.ioRunning() or d.st.sleep_mode == 3 or d.st.sleep_mode == 7;
    }

    fn asyncRunning(d: *const Devices) bool {
        return d.st.sleeping == 0 or d.st.sleep_mode == 0 or d.st.sleep_mode == 1 or d.st.sleep_mode == 3 or d.st.sleep_mode == 7;
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

test "external reset retains fixtures, seeds input history and preserves sticky reset causes" {
    for ([_]bool{ false, true }) |mega| {
        var d: Devices = .{ .mega = mega };
        d.reset();
        const port: u4 = if (mega) 3 else 1;
        const bit: u8 = if (mega) 0x80 else 1;
        d.setPinsIn(port, bit);
        d.setAnalog(0, 123);
        d.setComparatorInputs(900, 100);
        d.setBandgap(300);
        d.st.ee[7] = 0x5A;
        d.write(MCUSR, 0);
        d.resetWithCause(.external);
        try testing.expectEqual(@as(u8, 2), d.read(MCUSR));
        try testing.expectEqual(@as(u16, 123), d.st.analog[0]);
        try testing.expectEqual([2]u16{ 900, 100 }, d.st.comparator);
        try testing.expectEqual(@as(u16, 300), d.st.bandgap);
        try testing.expectEqual(@as(u8, 0x5A), d.st.ee[7]);
        d.write(TCCR0B, 7);
        d.tick(2);
        try testing.expectEqual(@as(u8, 0), d.read(TCNT0));
        try testing.expectEqual(@as(u8, 0), d.read(PCIFR));
        try testing.expectEqual(@as(u8, 0x20), d.read(ACSR) & 0x20);
        d.setPinsIn(port, 0);
        d.setPinsIn(port, bit);
        try testing.expectEqual(@as(u8, 1), d.read(TCNT0));
        d.st.io[MCUSR] = 0x0D; // Previously latched power-on, brown-out and watchdog resets.
        d.resetWithCause(.external);
        try testing.expectEqual(@as(u8, 0x0F), d.read(MCUSR));
        try testing.expectEqual(@as(u8, 8), d.read(WDTCSR) & 8);
        d.reset();
        try testing.expectEqual(@as(u8, 1), d.read(MCUSR));
    }
}

test "external timer flag edges trigger ADC samples on both profiles" {
    for ([_]bool{ false, true }) |mega| {
        for ([_]u3{ 3, 4, 5, 6 }) |source| {
            var d: Devices = .{ .mega = mega };
            d.reset();
            d.setAnalog(0, 555);
            d.write(ADCSRB, source);
            d.write(ADCSRA, 0xA0);
            const timer0 = source < 5;
            if (timer0) {
                d.write(OCR0A, 1);
                if (source == 4) d.write(TCNT0, 0xFF);
                d.write(TCCR0B, 7);
            } else {
                d.write(OCR1BH, 0);
                d.write(OCR1BL, 1);
                if (source == 6) {
                    d.write(TCNT1H, 0xFF);
                    d.write(TCNT1L, 0xFF);
                }
                d.write(TCCR1B, 7);
            }
            const port: u4 = if (mega) 3 else 1;
            const bit: u8 = if (timer0) (if (mega) 0x80 else 1) else (if (mega) 0x40 else 2);
            d.setPinsIn(port, bit);
            d.setPinsIn(port, 0);
            d.setPinsIn(port, bit);
            try testing.expect(d.st.adc_busy > 0);
            d.tick(50);
            try testing.expectEqual(@as(u8, 0x10), d.read(ADCSRA) & 0x50);
            const sample = @as(u16, d.read(ADCL)) | @as(u16, d.read(ADCH)) << 8;
            try testing.expectEqual(@as(u16, 555), sample);
            d.write(ADCSRA, 0xB0); // A high trigger flag alone cannot start another conversion.
            d.tick(100);
            try testing.expectEqual(@as(u32, 0), d.st.adc_busy);
            try testing.expectEqual(@as(u8, 0), d.read(ADCSRA) & 0x50);
        }
    }
}

test "changing ADC sources triggers only a low-to-high selected flag" {
    for ([_]bool{ false, true }) |mega| {
        var d: Devices = .{ .mega = mega };
        d.reset();
        d.write(ADCSRB, 2); // INT0 flag is low.
        d.write(ADCSRA, 0xA0);
        d.write(OCR0A, 1);
        d.write(TCCR0B, 1);
        d.tick(2);
        try testing.expect(d.read(TIFR0) & 2 != 0);
        d.write(TCCR0B, 0);
        try testing.expectEqual(@as(u32, 0), d.st.adc_busy);
        d.write(ADCSRB, 3);
        try testing.expect(d.st.adc_busy > 0);
        d.tick(50);
        d.write(ADCSRA, 0xB0);
        d.write(ADCSRB, 3); // Same high source: no new edge.
        try testing.expectEqual(@as(u32, 0), d.st.adc_busy);
        d.write(ADCSRB, 0); // Free-running selection itself must not trigger.
        try testing.expectEqual(@as(u32, 0), d.st.adc_busy);
        d.write(ADCSRB, 3);
        try testing.expect(d.st.adc_busy > 0);
    }
}

test "ICR writes commit only after selecting an ICR TOP mode on every timer" {
    for ([_]bool{ false, true }) |mega| {
        for (timer16_bases[0..if (mega) @as(usize, 4) else 1]) |base| {
            for (0..16) |mode| {
                var d: Devices = .{ .mega = mega };
                d.reset();
                d.write(base, @intCast(mode & 3));
                d.write(base + 1, @intCast((mode & 12) << 1));
                d.write(base + 7, 0x12);
                d.write(base + 6, 0x34);
                const capture = @as(u16, d.read(base + 6)) | @as(u16, d.read(base + 7)) << 8;
                const allowed = mode == 8 or mode == 10 or mode == 12 or mode == 14;
                try testing.expectEqual(@as(u16, if (allowed) 0x1234 else 0), capture);
            }
        }
    }
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
    try testing.expectEqual(@as(u16, 0x1234), d.st.timer[0].count);
    try testing.expectEqual(@as(u8, 0x34), d.read(TCNT1L));
    d.st.timer[0].count = 0xABCD; // changes between the two reads
    try testing.expectEqual(@as(u8, 0x12), d.read(TCNT1H)); // high byte latched by the low read
    d.st.timer[0].count = 0xFFFF;
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

test "all USARTs: TXC survives writing zero and clears only when written one" {
    for ([_]bool{ false, true }) |mega| {
        for (uart_bases[0..if (mega) @as(usize, 4) else 2], 0..) |base, port| {
            for ([_]u8{ 0x00, 0x03 }) |control| {
                var d: Devices = .{ .mega = mega };
                d.reset();
                const n: u2 = @intCast(port);
                const vector: u8 = if (mega) ([_]u8{ 27, 38, 53, 56 })[port] else if (n == 0) Vec.usart0_tx else Vec.usart1_tx;
                d.write(base, 0x03); // U2X, MPCM
                d.write(base + 1, 0x48); // TXEN, TXCIE
                d.write(base + 6, 0x41);
                d.tick(10 * 8); // Default UBRR=0, 8N1 with U2X.
                try testing.expectEqual(@as(?u8, 0x41), d.uartPop(n));
                try testing.expectEqual(@as(u8, 0x63), d.read(base));
                try testing.expectEqual(@as(?u8, vector), d.pending());

                d.write(base, control); // TXC=0 preserves the completed transmission.
                try testing.expectEqual(@as(u8, 0x60) | control, d.read(base));
                try testing.expectEqual(@as(?u8, vector), d.pending());
                d.write(base, 0x40 | control);
                try testing.expectEqual(@as(u8, 0x20) | control, d.read(base));
                try testing.expectEqual(@as(?u8, null), d.pending());
                d.write(base, 0x40 | control); // Writing one never sets TXC.
                try testing.expectEqual(@as(u8, 0x20) | control, d.read(base));
            }
        }
    }
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

test "programmed WDTON fuse forces a watchdog reset despite runtime disable or interrupt requests" {
    for ([_]bool{ false, true }) |mega| {
        var d: Devices = .{ .mega = mega };
        d.configureFuses(0x77, 0x89, 0xFE, 0xFF);
        d.reset();
        try testing.expectEqual(@as(u8, 0x08), d.read(WDTCSR) & 0x48);
        d.write(MCUSR, 0);
        d.write(WDTCSR, 0x18);
        d.write(WDTCSR, 0x40); // Attempt to replace reset mode with interrupt-only mode.
        try testing.expectEqual(@as(u8, 0x08), d.read(WDTCSR) & 0x48);
        d.tick(@intCast(d.wdtPeriod()));
        try testing.expectEqual(@as(u8, 1), d.st.reset_request);
        try testing.expectEqual(@as(u8, 0), d.read(WDTCSR) & 0x40);
    }
}

test "CTC missed TOP still sets overflow on the 8-bit and 16-bit MAX wrap" {
    for ([_]bool{ false, true }) |mega| {
        for ([_]u16{ TCCR0A, TCCR2A }) |base| {
            var d: Devices = .{ .mega = mega };
            d.reset();
            d.write(base, 2); // CTC; TOP=OCRnA.
            d.write(base + 1, 1); // Clock/1.
            d.write(base + 3, 10);
            d.write(base + 2, 0xFF); // Software has already passed TOP.
            d.tick(1);
            try testing.expectEqual(@as(u8, 0), d.read(base + 2));
            try testing.expectEqual(@as(u8, 1), d.read(if (base == TCCR0A) TIFR0 else TIFR2) & 1);
        }
        for (timer16_bases[0..if (mega) @as(usize, 4) else 1], 0..) |base, n| {
            var d: Devices = .{ .mega = mega };
            d.reset();
            d.write(base + 1, 0x09); // CTC mode4, clock/1.
            d.write(base + 9, 0);
            d.write(base + 8, 10);
            d.write(base + 5, 0xFF);
            d.write(base + 4, 0xFF);
            d.tick(1);
            try testing.expectEqual(@as(u16, 0), d.st.timer[n].count);
            try testing.expectEqual(@as(u8, 1), d.read(timer16_flags[n]) & 1);
        }
    }
}

test "A17 open bus: a read above SRAM or of a register without a model returns 0, the tape first" {
    var bus = try Bus.init(testing.allocator, &.{.{ .lo = 0x20, .hi = 0xFF, .kind = .mmio }}, &.{});
    defer bus.deinit();
    var d: Devices = .{ .bus = &bus, .open_bus = true };
    d.reset();
    bus.dev = d.device();
    bus.resetRun(100);
    try testing.expectEqual(@as(u64, 0), bus.read(0x51, 8)); // OCDR, no model
    try testing.expectEqual(@as(u64, 0), bus.read(0xF0F0, 8)); // above SRAM
    try testing.expectEqual(@as(?common.bus.Stop, null), bus.stop);
    var t = try common.tape.Tape.init(testing.allocator, &.{.{ .addr = 0x51, .value = 0xF8 }});
    defer t.deinit(testing.allocator);
    bus.tape = &t;
    try testing.expectEqual(@as(u64, 0xF8), bus.read(0x51, 8)); // a tape still answers first
    try testing.expectEqual(@as(u64, 0), bus.read(0x51, 8));
}

test "registers without a model come from the tape" {
    var data: emu.cpu.Data = @splat(0);
    var backing = [_]common.bus.Backing(u8){.{ .base = 0, .mem = &data }};
    const map = [_]common.bus.Range{.{ .lo = 0x20, .hi = 0xFF, .kind = .mmio }};
    var bus = try Bus.init(testing.allocator, &map, &backing);
    defer bus.deinit();
    var t = try common.tape.Tape.init(testing.allocator, &.{.{ .addr = 0x51, .value = 0xF8 }}); // OCDR
    defer t.deinit(testing.allocator);
    bus.tape = &t;
    var d = fresh();
    d.bus = &bus;
    bus.dev = d.device();
    try testing.expectEqual(@as(u64, 0xF8), bus.read(0x51, 8));
    try testing.expectEqual(@as(u64, 0x03), bus.read(CLKPR, 8)); // modelled: no tape
    _ = bus.read(0x51, 8);
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
    const next_match = @as(u16, d.st.ocr0a_buf -% d.read(TCNT0)) + 1;
    d.tick(next_match);
    try testing.expectEqual(@as(u8, 0x40), d.st.io[ADCSRA] & 0x40);
    d.tick(27);
    try testing.expectEqual(@as(u8, 0x10), d.st.io[ADCSRA] & 0x50);
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

test "640/1280 UARTs retain independent data and use the family interrupt vectors" {
    var d: Devices = .{ .mega = true };
    d.reset();
    for (uart_bases, [_]u8{ 25, 36, 51, 54 }, 0..) |base, vector_number, port| {
        d.write(base + 1, 0x98); // RXCIE, RXEN, TXEN
        const value: u8 = @intCast(65 + port);
        try testing.expect(d.uartPush(@intCast(port), value));
        d.tick(160);
        try testing.expectEqual(@as(?u8, vector_number), d.pending());
        try testing.expectEqual(value, d.read(base + 6));
        try testing.expectEqual(@as(?u8, null), d.pending());
        d.write(base + 6, value + 8);
        d.tick(160);
        try testing.expectEqual(@as(?u8, value + 8), d.uartPop(@intCast(port)));
    }
    d.write(0x65, 2); // PRR1.PRUSART2
    d.write(UCSR2A + 6, 0x55);
    d.tick(1000);
    try testing.expectEqual(@as(?u8, null), d.uartPop(2));
    d.write(0x65, 0);
    d.tick(160);
    try testing.expectEqual(@as(?u8, 0x55), d.uartPop(2));
}

test "640/1280 extended GPIO, interrupt acknowledgement and full EEPROM addressing" {
    var d: Devices = .{ .mega = true };
    d.reset();
    d.write(PCMSK0 + 2, 1); // PCINT16 = PK0
    d.write(PCICR, 4);
    d.setPinsIn(9, 1);
    try testing.expectEqual(@as(u8, 1), d.read(0x106));
    try testing.expectEqual(@as(?u8, 11), d.pending());
    const system = d.sys();
    system.ack(system.ctx, 11);
    try testing.expectEqual(@as(?u8, null), d.pending());
    d.write(0x10A, 0x20); // DDRL5 output
    d.write(0x109, 0x20); // PINL toggles PORTL
    try testing.expectEqual(@as(u8, 0x20), d.read(0x109));
    d.st.io[TIFR0] = 2;
    d.st.io[TIMSK0] = 2;
    try testing.expectEqual(@as(?u8, 21), d.pending());
    system.ack(system.ctx, 21);
    try testing.expectEqual(@as(?u8, null), d.pending());
    d.write(EEARH, 0x0F);
    d.write(EEARL, 0x80);
    d.write(EEDR, 0x5A);
    d.write(EECR, 4);
    d.write(EECR, 2);
    d.tick(@intCast(d.fCpu() * 34 / 10_000));
    try testing.expectEqual(@as(u8, 0x5A), d.st.ee[0xF80]);
    try testing.expectEqual(@as(u8, 0xFF), d.st.ee[0x180]);
}

test "640/1280 timers3-5: independent TEMP latches, all compare flags, vectors, PRR1 and TSM" {
    var d: Devices = .{ .mega = true };
    d.reset();
    const system = d.sys();
    for (timer16_bases[1..], 1..) |base, n| {
        d.write(base + 5, 0xAB);
        d.write(base + 4, 0xCD);
        d.write(timer16_bases[0] + 5, 0x12); // a different timer has its own TEMP register
        try testing.expectEqual(@as(u8, 0xCD), d.read(base + 4));
        d.st.timer[n].count = 0x5678;
        try testing.expectEqual(@as(u8, 0xAB), d.read(base + 5));
        d.write(base + 5, 0);
        d.write(base + 4, 0);
        for ([_]u16{ 8, 10, 12 }, 0..) |off, compare| {
            d.write(base + off + 1, 0);
            d.write(base + off, @intCast(compare + 2));
        }
        d.write(base + 1, 1); // clk/1, normal mode
        d.write(timer16_masks[n], 0x0E);
        d.tick(5);
        try testing.expectEqual(@as(u8, 0x0E), d.read(timer16_flags[n]));
        for (0..3) |compare| {
            const vector_number = d.timerVector(n) + 1 + @as(u8, @intCast(compare));
            try testing.expectEqual(@as(?u8, vector_number), d.pending());
            system.ack(system.ctx, vector_number);
        }
        try testing.expectEqual(@as(?u8, null), d.pending());
        const count = d.st.timer[n].count;
        d.write(0x65, @as(u8, 1) << @intCast(n + 2));
        d.tick(20);
        try testing.expectEqual(count, d.st.timer[n].count);
        d.write(0x65, 0);
        d.write(GTCCR, 0x81); // synchronous prescalers held reset
        d.tick(20);
        try testing.expectEqual(count, d.st.timer[n].count);
        d.write(GTCCR, 0);
        d.write(base + 5, 0xFF);
        d.write(base + 4, 0xFF);
        d.write(timer16_masks[n], 1);
        d.tick(1);
        try testing.expectEqual(@as(u16, 0), d.st.timer[n].count);
        try testing.expectEqual(@as(?u8, d.timerVector(n) + 4), d.pending());
        d.write(timer16_flags[n], 1);
        try testing.expectEqual(@as(?u8, null), d.pending());
        d.write(base + 1, 0);
    }
}

test "640/1280 compare C and timer3 retain hardware interrupt priority against UART1" {
    var d: Devices = .{ .mega = true };
    d.reset();
    d.write(TIMSK1, 9); // compare C and overflow enabled
    d.st.io[TIFR1] = 9;
    d.st.io[0x38] = 2;
    d.write(0x71, 2);
    d.write(UCSR1A + 1, 0x20); // UART1 data-register-empty vector36
    try testing.expectEqual(@as(?u8, 19), d.pending());
    Devices.sysAck(&d, 19);
    try testing.expectEqual(@as(?u8, 20), d.pending());
    Devices.sysAck(&d, 20);
    try testing.expectEqual(@as(?u8, 32), d.pending());
    Devices.sysAck(&d, 32);
    try testing.expectEqual(@as(?u8, 37), d.pending());
}

test "640/1280 timer3 CTC and PWM update all channels at the specified counter boundary" {
    var d: Devices = .{ .mega = true };
    d.reset();
    d.write(0x99, 0);
    d.write(0x98, 3); // OCR3A = TOP
    d.write(0x91, 9); // CTC, clk/1
    d.tick(4);
    try testing.expectEqual(@as(u16, 0), d.st.timer[1].count);
    try testing.expectEqual(@as(u8, 2), d.read(0x38) & 3); // compare at TOP, no overflow
    d.write(0x38, 0xFF);
    d.write(0x90, 1);
    d.write(0x91, 9); // mode5, fast 8-bit PWM
    d.write(0x99, 0);
    d.write(0x98, 12);
    d.write(0x9D, 0);
    d.write(0x9C, 9);
    try testing.expectEqual(@as(u16, 3), d.st.timer[1].compare[0]);
    d.tick(256);
    try testing.expectEqual(@as(u16, 12), d.st.timer[1].compare[0]);
    try testing.expectEqual(@as(u16, 9), d.st.timer[1].compare[2]);
    try testing.expectEqual(@as(u8, 1), d.read(0x38) & 1);
}

test "external interrupts: model pin maps, edge flags without masks, low-level retrigger and W1C" {
    for ([_]bool{ false, true }) |mega| {
        var d: Devices = .{ .mega = mega };
        d.reset();
        d.setPinsIn(3, 0xFF);
        if (mega) d.setPinsIn(4, 0xFF) else d.setPinsIn(1, 0xFF);
        d.write(EICRA, 0xAA); // falling edges, no interrupt masks yet
        if (mega) d.write(EICRB, 0xAA);
        d.setPinsIn(3, if (mega) 0xFE else 0xFB);
        try testing.expectEqual(@as(u8, 1), d.read(EIFR) & 1);
        try testing.expectEqual(@as(?u8, null), d.pending());
        d.write(EIMSK, 1);
        try testing.expectEqual(@as(?u8, 1), d.pending());
        Devices.sysAck(&d, 1);
        try testing.expectEqual(@as(?u8, null), d.pending());
        d.write(EICRA, 0); // low level while INT0 remains low
        try testing.expectEqual(@as(?u8, 1), d.pending());
        Devices.sysAck(&d, 1);
        try testing.expectEqual(@as(?u8, 1), d.pending()); // level remains asserted
        d.setPinsIn(3, 0xFF);
        try testing.expectEqual(@as(?u8, null), d.pending());
        d.write(EICRA, 0xFF); // rising edges
        if (mega) d.write(EICRB, 0xFF);
        d.setPinsIn(if (mega) 4 else 1, 0);
        d.setPinsIn(if (mega) 4 else 1, if (mega) 0x80 else 4);
        const bit: u8 = if (mega) 0x80 else 4;
        d.write(EIMSK, bit);
        try testing.expectEqual(@as(?u8, if (mega) 8 else 3), d.pending());
        d.write(EIFR, bit);
        try testing.expectEqual(@as(?u8, null), d.pending());
    }
}

test "external edge interrupts obey each profile's sleep clock domains" {
    for ([_]bool{ false, true }) |mega| {
        const count: usize = if (mega) 8 else 3;
        for (0..count) |n| {
            for ([_]u8{ 1, 2, 3, 6, 7 }) |mode| {
                var t: emu.cpu.TestRig = .{};
                try t.init(&.{ 0x9588, 0xE50A }); // SLEEP, LDI r16,0x5A; SREG.I remains clear.
                defer t.deinit();
                var d: Devices = .{ .mega = mega };
                d.reset();
                t.bus.dev = d.device();
                t.cpu.sys = d.sys();
                const bit: u8 = @as(u8, 1) << @intCast(n);
                const port: u4 = if (mega) (if (n < 4) 3 else 4) else (if (n < 2) 3 else 1);
                const pad: u8 = if (mega) bit else if (n < 2) bit << 2 else 4;
                const pcport: u4 = if (mega) 1 else 0;
                d.write(EICRA, 0xFF);
                if (mega) d.write(EICRB, 0xFF);
                d.write(EIMSK, bit);
                d.write(PCICR, 1);
                d.write(PCMSK0, 1);
                d.write(SMCR, (mode << 1) | 1);
                try t.steps(1);
                d.setPinsIn(port, pad);
                try t.steps(1);
                if (mega and n < 4) {
                    try testing.expectEqual(@as(u8, 0), t.cpu.st.sleeping);
                    try testing.expectEqual(bit, d.read(EIFR) & bit);
                } else {
                    try testing.expectEqual(@as(u8, 1), t.cpu.st.sleeping);
                    try testing.expectEqual(@as(u8, 0), d.read(EIFR) & bit);
                    d.setPinsIn(port, 0); // The entire pulse occurs while its detector is stopped.
                    d.setPinsIn(pcport, 1);
                    try t.steps(1);
                    try testing.expectEqual(@as(u8, 0), t.cpu.st.sleeping);
                    try testing.expectEqual(@as(u8, 0), d.read(EIFR) & bit);
                }
            }
        }
    }
}

test "low-level external interrupts still wake both profiles with the IO clock stopped" {
    for ([_]bool{ false, true }) |mega| {
        for ([_]u8{ 1, 2, 3, 6, 7 }) |mode| {
            var t: emu.cpu.TestRig = .{};
            try t.init(&.{ 0x9588, 0xE50A });
            defer t.deinit();
            var d: Devices = .{ .mega = mega };
            d.reset();
            t.bus.dev = d.device();
            t.cpu.sys = d.sys();
            d.setPinsIn(3, if (mega) 1 else 4);
            d.write(EIMSK, 1);
            d.write(SMCR, (mode << 1) | 1);
            try t.steps(1);
            try testing.expectEqual(@as(u8, 1), t.cpu.st.sleeping);
            d.setPinsIn(3, 0);
            try t.steps(1);
            try testing.expectEqual(@as(u8, 0), t.cpu.st.sleeping);
        }
    }
}

test "counter writes suppress exactly one timer-clock compare on every timer" {
    for ([_]bool{ false, true }) |mega| {
        for ([_]bool{ false, true }) |ctc| {
            for ([_]u16{ 0x1234, 0x1233 }) |preload| {
                const count: usize = if (mega) 4 else 1;
                for (timer16_bases[0..count], 0..) |base, n| {
                    for ([_]bool{ false, true }) |external| {
                        var d: Devices = .{ .mega = mega };
                        d.reset();
                        d.write(base, 0x40); // Toggle compare A output.
                        for (0..if (mega) @as(usize, 3) else 2) |c| {
                            d.write(base + @as(u16, @intCast(9 + 2 * c)), 0x12);
                            d.write(base + @as(u16, @intCast(8 + 2 * c)), 0x34);
                        }
                        d.write(base + 5, @truncate(preload >> 8));
                        d.write(base + 4, @truncate(preload));
                        d.tick(10); // The stopped timer must retain the suppression.
                        const clock_port: u4 = if (!mega) 1 else ([_]u4{ 3, 4, 7, 10 })[n];
                        const clock_bit: u8 = if (!mega) 2 else ([_]u8{ 0x40, 0x40, 0x80, 4 })[n];
                        d.write(base + 1, (if (ctc) @as(u8, 8) else 0) | (if (external) @as(u8, 7) else 1));
                        if (external) d.setPinsIn(clock_port, clock_bit) else d.tick(1);
                        try testing.expectEqual(@as(u8, 0), d.read(timer16_flags[n]));
                        try testing.expectEqual(preload + 1, d.st.timer[n].count);
                        if (external) {
                            d.setPinsIn(clock_port, 0);
                            d.setPinsIn(clock_port, clock_bit);
                        } else d.tick(1);
                        const matched = preload == 0x1233;
                        try testing.expectEqual(@as(u8, if (!matched) 0 else if (mega) 14 else 6), d.read(timer16_flags[n]));
                        try testing.expectEqual(@as(u8, @intFromBool(matched)), d.st.timer[n].output[0]);
                    }
                }
            }
            inline for ([_]u2{ 0, 2 }) |n| {
                for ([_]u8{ 42, 41 }) |preload| {
                    var d: Devices = .{ .mega = mega };
                    d.reset();
                    d.write(if (n == 0) TCCR0A else TCCR2A, if (ctc) 0x42 else 0x40);
                    d.write(if (n == 0) OCR0A else OCR2A, 42);
                    d.write(if (n == 0) TCNT0 else TCNT2, preload);
                    d.tick(10);
                    d.write(if (n == 0) TCCR0B else TCCR2B, 1);
                    d.tick(1);
                    try testing.expectEqual(@as(u8, 0), d.read(if (n == 0) TIFR0 else TIFR2));
                    try testing.expectEqual(preload + 1, d.read(if (n == 0) TCNT0 else TCNT2));
                    d.tick(1);
                    try testing.expectEqual(@as(u8, if (preload == 41) 2 else 0), d.read(if (n == 0) TIFR0 else TIFR2));
                }
            }
        }
    }
}

test "external timer clocks and noise-cancelled capture use actual model pins" {
    var d: Devices = .{ .mega = true };
    d.reset();
    d.write(0x91, 7); // Timer3 counts rising PE6 edges
    d.setPinsIn(4, 0x40);
    d.setPinsIn(4, 0);
    d.setPinsIn(4, 0x40);
    try testing.expectEqual(@as(u16, 2), d.st.timer[1].count);
    d.tick(100);
    try testing.expectEqual(@as(u16, 2), d.st.timer[1].count);
    d.write(0x91, 0xC1); // noise cancellation, rising ICP3 PE7, clk/1
    d.write(0x71, 0x20);
    d.setPinsIn(4, 0xC0);
    d.tick(3);
    try testing.expectEqual(@as(?u8, null), d.pending());
    d.setPinsIn(4, 0x40); // pulse shorter than four cycles must be ignored
    d.tick(10);
    try testing.expectEqual(@as(?u8, null), d.pending());
    const count = d.st.timer[1].count;
    d.setPinsIn(4, 0xC0);
    d.tick(10);
    try testing.expectEqual(@as(?u8, 31), d.pending());
    try testing.expectEqual(count + 4, d.st.timer[1].capture);
    try testing.expectEqual(@as(u8, @truncate(count + 4)), d.read(0x96));
    try testing.expectEqual(@as(u8, @truncate((count + 4) >> 8)), d.read(0x97));
    var small = fresh();
    small.write(TCCR0B, 7);
    small.setPinsIn(1, 1);
    try testing.expectEqual(@as(u8, 1), small.read(TCNT0));
    small.write(TCCR1B, 6);
    small.setPinsIn(1, 3);
    small.setPinsIn(1, 1);
    try testing.expectEqual(@as(u16, 1), small.st.timer[0].count);
}

test "external compare outputs consume each clock edge once, including zero-TOP CTC" {
    for ([_]bool{ false, true }) |mega| {
        for ([_]bool{ false, true }) |ctc| {
            var d: Devices = .{ .mega = mega };
            d.reset();
            const clock_port: u4 = if (mega) 3 else 1;
            const clock_bit: u8 = if (mega) 0x80 else 1;
            const out = d.output8Pin(0, 0);
            const out_bit = @as(u8, 1) << out.bit;
            d.write(port_bases[out.port] + 1, out_bit);
            d.write(TCCR0A, if (ctc) 0x42 else 0x40);
            d.write(OCR0A, 0);
            d.write(TCCR0B, 7);
            d.setPinsIn(clock_port, clock_bit);
            try testing.expectEqual(@as(u8, if (ctc) 0 else 1), d.read(TCNT0));
            try testing.expectEqual(out_bit, d.pin(out.port) & out_bit);
            d.setPinsIn(clock_port, clock_bit);
            try testing.expectEqual(@as(u8, if (ctc) 0 else 1), d.read(TCNT0));
            for (timer16_bases[0..d.timerCount()], 0..) |base, n| {
                var timer: Devices = .{ .mega = mega };
                timer.reset();
                const port: u4 = if (!mega) 1 else ([_]u4{ 3, 4, 7, 10 })[n];
                const bit: u8 = if (!mega) 2 else ([_]u8{ 0x40, 0x40, 0x80, 4 })[n];
                const output = timer.output16Pin(n, 0);
                const output_bit = @as(u8, 1) << output.bit;
                timer.write(port_bases[output.port] + 1, output_bit);
                timer.write(base, 0x40);
                timer.write(base + 1, if (ctc) 0x0F else 7);
                timer.setPinsIn(port, bit);
                try testing.expectEqual(@as(u16, if (ctc) 0 else 1), timer.st.timer[n].count);
                try testing.expectEqual(output_bit, timer.pin(output.port) & output_bit);
                timer.setPinsIn(port, bit);
                try testing.expectEqual(@as(u16, if (ctc) 0 else 1), timer.st.timer[n].count);
            }
        }
    }
}

test "power reduction stops both capture paths on every available 16-bit timer" {
    for ([_]bool{ false, true }) |mega| {
        for ([_]bool{ false, true }) |noise| {
            const count: usize = if (mega) 4 else 1;
            for (timer16_bases[0..count], 0..) |base, n| {
                var d: Devices = .{ .mega = mega };
                d.reset();
                const port: u4 = if (!mega) 3 else ([_]u4{ 3, 4, 10, 10 })[n];
                const bit: u8 = if (!mega) 0x40 else ([_]u8{ 0x10, 0x80, 1, 2 })[n];
                const power_register: u16 = if (n == 0) PRR else 0x65;
                const power: u8 = if (n == 0) PRTIM1 else @as(u8, 1) << @intCast(n + 2);
                d.write(base + 1, if (noise) 0xC1 else 0x41);
                d.write(timer16_masks[n], 0x20);
                d.write(power_register, power);
                d.setPinsIn(port, bit);
                d.tick(10);
                try testing.expectEqual(@as(u8, 0), d.read(timer16_flags[n]) & 0x20);
                try testing.expectEqual(@as(?u8, null), d.pending());
                d.write(power_register, 0);
                d.setPinsIn(port, 0);
                d.tick(4);
                d.setPinsIn(port, bit);
                d.tick(4);
                try testing.expectEqual(@as(u8, 0x20), d.read(timer16_flags[n]) & 0x20);
                try testing.expectEqual(@as(?u8, d.timerVector(n)), d.pending());
            }
        }
    }
}

test "ADC alignment is live during and after conversion without changing the latched channel" {
    for ([_]bool{ false, true }) |mega| {
        var d: Devices = .{ .mega = mega };
        d.reset();
        d.setAnalog(0, 0x2AB);
        d.setAnalog(1, 1);
        d.write(ADCSRA, 0xC0);
        d.write(ADMUX, 0x21); // Change alignment and select the next channel.
        d.tick(50);
        try testing.expectEqual(@as(u8, 0xC0), d.read(ADCL));
        try testing.expectEqual(@as(u8, 0xAA), d.read(ADCH));
        d.write(ADMUX, 1);
        try testing.expectEqual(@as(u8, 0xAB), d.read(ADCL));
        d.write(ADCSRA, 0xC0);
        d.tick(26); // The prior ADCL read blocks publication of the new sample.
        try testing.expectEqual(@as(u8, 2), d.read(ADCH));
        d.write(ADMUX, 0x21);
        try testing.expectEqual(@as(u8, 0xC0), d.read(ADCL));
        try testing.expectEqual(@as(u8, 0xAA), d.read(ADCH));
        d.write(ADCSRA, 0xC0);
        d.tick(26);
        try testing.expectEqual(@as(u8, 0x40), d.read(ADCL));
        try testing.expectEqual(@as(u8, 0), d.read(ADCH));
    }
}

test "comparator follows the ADC mux when its power-reduction clock is restored or removed" {
    for ([_]bool{ false, true }) |mega| {
        var d: Devices = .{ .mega = mega };
        d.reset();
        d.setAnalog(0, 100);
        d.setComparatorInputs(500, 900);
        d.write(PRR, PRADC);
        d.write(ADCSRB, 0x40);
        d.write(ACSR, 0x0B); // Rising-edge comparator interrupt.
        try testing.expectEqual(@as(u8, 0), d.read(ACSR) & 0x30);
        d.write(PRR, 0);
        d.tick(2);
        try testing.expectEqual(@as(u8, 0x30), d.read(ACSR) & 0x30);
        try testing.expect(d.pending() != null);
        d.write(ACSR, 0x1B);
        d.write(PRR, PRADC);
        d.tick(2);
        try testing.expectEqual(@as(u8, 0), d.read(ACSR) & 0x30);
    }
}

test "ICR-TOP phase PWM signals capture at TOP once per cycle on all 16-bit timers" {
    for ([_]bool{ false, true }) |mega| {
        const count: usize = if (mega) 4 else 1;
        for (timer16_bases[0..count], 0..) |base, n| {
            for ([_]u8{ 8, 10 }) |mode| {
                var d: Devices = .{ .mega = mega };
                d.reset();
                d.write(base, mode & 3);
                d.write(base + 1, (mode & 12) << 1);
                d.write(base + 7, 0);
                d.write(base + 6, 3);
                d.write(base + 1, ((mode & 12) << 1) | 1);
                d.write(timer16_masks[n], 0x20);
                d.tick(2);
                try testing.expectEqual(@as(?u8, null), d.pending());
                d.tick(1);
                try testing.expectEqual(@as(?u8, d.timerVector(n)), d.pending());
                d.write(timer16_flags[n], 0x20);
                d.tick(1);
                try testing.expectEqual(@as(?u8, null), d.pending());
                d.tick(5);
                try testing.expectEqual(@as(?u8, d.timerVector(n)), d.pending());
            }
        }
    }
}

test "640/1280 PB7 modulates both enabled compare outputs using PORTB7" {
    var d: Devices = .{ .mega = true };
    d.reset();
    d.write(0x24, 0x80);
    for ([_]u8{ 0, 1 }) |a| for ([_]u8{ 0, 1 }) |c| {
        d.write(TCCR0A, if (a == 0) 0x80 else 0xC0);
        d.write(TCCR0B, 0x80); // Force OC0A.
        d.write(TCCR1A, if (c == 0) 8 else 12);
        d.write(TCCR1A + 2, 0x20); // Force OC1C.
        d.write(0x25, 0);
        try testing.expectEqual((a & c) << 7, d.pin(1) & 0x80);
        d.write(0x25, 0x80);
        try testing.expectEqual((a | c) << 7, d.pin(1) & 0x80);
    };
    d.write(TCCR1A, 0);
    try testing.expectEqual(@as(u8, 0x80), d.pin(1) & 0x80);
    d.write(TCCR0A, 0);
    d.write(0x25, 0);
    try testing.expectEqual(@as(u8, 0), d.pin(1) & 0x80);
}

test "ADC extended mux is latched, differential conversion signed, and ADCL locks paired results" {
    var d: Devices = .{ .mega = true };
    d.reset();
    try testing.expectEqual(@as(usize, 16), d.analogCount());
    d.setAnalog(0, 123);
    d.setAnalog(8, 900);
    d.write(ADCSRB, 8); // MUX5 selects ADC8
    d.write(ADCSRA, 0xC0);
    d.write(ADCSRB, 0); // a mux change during conversion applies to the next conversion
    d.tick(50);
    try testing.expectEqual(@as(u8, @truncate(@as(u16, 900))), d.read(ADCL));
    try testing.expectEqual(@as(u8, 900 >> 8), d.read(ADCH));
    d.write(ADCSRA, 0xC0);
    d.tick(26);
    try testing.expectEqual(@as(u8, 123), d.read(ADCL));
    d.setAnalog(0, 400);
    d.write(ADCSRA, 0xC0);
    d.tick(26);
    try testing.expectEqual(@as(u8, 0), d.read(ADCH)); // locked prior result
    try testing.expectEqual(@as(u8, 123), d.read(ADCL));
    _ = d.read(ADCH);
    d.setAnalog(1, 600);
    d.write(ADMUX, 16); // ADC0 - ADC1, gain1, signed result = (400-600)/2
    d.write(ADCSRA, 0xC0);
    d.tick(26);
    const negative: u16 = @as(u16, d.read(ADCL)) | @as(u16, d.read(ADCH)) << 8;
    try testing.expectEqual(@as(u16, 0x39C), negative);
    var small = fresh();
    try testing.expectEqual(@as(usize, 8), small.analogCount());
}

test "ADC free running and timer1 overflow auto trigger preserve hardware flags" {
    var d = fresh();
    d.setAnalog(0, 333);
    d.write(ADCSRA, 0xE0); // enable, start, auto-trigger; source0 free-running
    d.tick(50);
    try testing.expectEqual(@as(u8, 0x50), d.read(ADCSRA) & 0x50); // ADIF and new ADSC
    _ = d.read(ADCL);
    _ = d.read(ADCH);
    d.write(ADCSRA, 0); // terminate free-running
    d.write(ADCSRB, 6); // timer1 overflow
    d.write(ADCSRA, 0xA0);
    d.write(TCNT1H, 0xFF);
    d.write(TCNT1L, 0xFF);
    d.write(TCCR1B, 1);
    d.tick(1);
    try testing.expectEqual(@as(u8, 0x40), d.read(ADCSRA) & 0x40);
    d.tick(50);
    try testing.expectEqual(@as(u8, 0x10), d.read(ADCSRA) & 0x50);
    d.write(TCNT1H, 0xFF);
    d.write(TCNT1L, 0xFF);
    d.tick(1); // TOV remains set: no new edge
    try testing.expectEqual(@as(u8, 0), d.read(ADCSRA) & 0x40);
    d.write(TIFR1, 1);
    d.write(TCNT1H, 0xFF);
    d.write(TCNT1L, 0xFF);
    d.tick(1);
    try testing.expectEqual(@as(u8, 0x40), d.read(ADCSRA) & 0x40);
}

test "strict peripheral coverage rejects unsupported blocks and selects the actual AVR profile" {
    var small = fresh();
    var large: Devices = .{ .mega = true };
    large.reset();
    try testing.expect(!small.modeledAccess(0x94, false)); // Timer3 absent on 164P
    try testing.expect(large.modeledAccess(0x94, false));
    try testing.expect(!small.modeledAccess(0x8C, false)); // Timer1 compare C absent on 164P
    try testing.expect(large.modeledAccess(0x8C, false));
    try testing.expect(!large.modeledAccess(0x51, false)); // OCDR
    try testing.expect(large.modeledAccess(ASSR, false)); // asynchronous Timer2
    try testing.expect(large.modeledAccess(SPMCSR, true)); // guest self-programming
    try testing.expect(large.modeledAccess(0x92, true)); // FOC drives modeled compare pins
    try testing.expect(large.modeledAccess(0x92, false)); // reads zero
}

test "timer force compare drives model-specific pins without changing counters or flags" {
    for ([_]bool{ false, true }) |mega| {
        var d: Devices = .{ .mega = mega };
        d.reset();
        const port: u4 = if (mega) 1 else 3;
        const bit: u8 = if (mega) 0x20 else 0x20; // OC1A = PB5/PD5
        d.write(port_bases[port] + 1, bit);
        d.write(TCCR1A, 0x40); // toggle OC1A, non-PWM
        d.write(TCCR1A + 2, 0x80);
        try testing.expectEqual(bit, d.pin(port) & bit);
        try testing.expectEqual(@as(u8, 0), d.read(TCCR1A + 2));
        try testing.expectEqual(@as(u16, 0), d.st.timer[0].count);
        try testing.expectEqual(@as(u8, 0), d.read(TIFR1));
        d.write(TCCR1A + 2, 0x80);
        try testing.expectEqual(@as(u8, 0), d.pin(port) & bit);
        d.write(TCCR1A, 0xC0); // set OC1A on forced match
        d.write(TCCR1A + 2, 0x80);
        try testing.expectEqual(bit, d.pin(port) & bit);
        d.write(port_bases[port] + 1, 0); // DDR still controls whether the timer drives the pad
        try testing.expectEqual(@as(u8, 0), d.pin(port) & bit);
        d.write(port_bases[port] + 1, bit);
        d.write(TCCR1A, 0); // disconnected: PORT latch supplies the level
        try testing.expectEqual(@as(u8, 0), d.pin(port) & bit);
    }
    var d: Devices = .{ .mega = true };
    d.reset();
    d.write(0x2D, 0x20); // DDRE5, OC3C
    d.write(0x90, 0x0C); // set OC3C
    d.write(0x92, 0x20); // FOC3C
    try testing.expectEqual(@as(u8, 0x20), d.pin(4) & 0x20);
    try testing.expectEqual(@as(u8, 0), d.read(0x38));
}

test "digital PWM outputs expose fast and phase-correct compare behavior on GPIO" {
    var d = fresh();
    d.write(0x24, 0x10); // DDRB4 = OC0B
    d.write(TCCR0A, 0x23); // fast PWM, non-inverting OC0B
    d.write(OCR0B, 3);
    d.st.ocr0b_buf = 3;
    d.write(TCNT0, 0xFF);
    d.write(TCCR0B, 1);
    d.tick(1); // BOTTOM sets output
    try testing.expectEqual(@as(u8, 0x10), d.pin(1) & 0x10);
    d.tick(4); // compare clears output
    try testing.expectEqual(@as(u8, 0), d.pin(1) & 0x10);
    d.write(TCCR0B, 0x41); // FOC0B in PWM must have no effect
    try testing.expectEqual(@as(u8, 0), d.pin(1) & 0x10);
    d.write(TCCR0A, 0x21); // phase correct
    d.write(TCNT0, 2);
    d.st.down[0] = 1;
    d.tick(1); // no compare yet
    try testing.expectEqual(@as(u8, 0), d.pin(1) & 0x10);
    d.write(TCNT0, 4);
    d.tick(1); // Counter write blocks this clock; the next one reaches compare naturally.
    try testing.expectEqual(@as(u8, 0), d.pin(1) & 0x10);
    d.tick(1); // compare while down-counting sets non-inverting output
    try testing.expectEqual(@as(u8, 0x10), d.pin(1) & 0x10);
    d.st.down[0] = 0;
    d.write(TCNT0, 2);
    d.tick(1);
    try testing.expectEqual(@as(u8, 0x10), d.pin(1) & 0x10);
    d.tick(1);
    try testing.expectEqual(@as(u8, 0), d.pin(1) & 0x10);
}

test "comparator synchronizes output, reports family interrupts, acknowledges and captures Timer1" {
    for ([_]bool{ false, true }) |mega| {
        var d: Devices = .{ .mega = mega };
        d.reset();
        d.write(ACSR, 0x0F); // interrupt enabled, rising edge, capture enabled
        d.write(TCCR1B, 0x41); // Timer1 clk/1, capture rising
        d.write(TIMSK1, 0x20);
        d.setComparatorInputs(800, 100);
        d.tick(1);
        try testing.expectEqual(@as(u8, 0), d.read(ACSR) & 0x20);
        d.tick(1);
        try testing.expectEqual(@as(u8, 0x30), d.read(ACSR) & 0x30);
        try testing.expectEqual(@as(?u8, if (mega) 16 else Vec.t1_capt), d.pending());
        Devices.sysAck(&d, if (mega) 16 else Vec.t1_capt);
        try testing.expectEqual(@as(?u8, if (mega) 28 else Vec.comparator), d.pending());
        Devices.sysAck(&d, if (mega) 28 else Vec.comparator);
        try testing.expectEqual(@as(?u8, null), d.pending());
        d.setComparatorInputs(0, 500); // falling edge ignored by rising-only comparator mode
        d.tick(2);
        try testing.expectEqual(@as(u8, 0), d.read(ACSR) & 0x30);
        d.write(ACSR, 0x08); // toggle mode, capture disconnected
        d.setComparatorInputs(600, 500);
        d.tick(2);
        try testing.expectEqual(@as(u8, 0x30), d.read(ACSR) & 0x30);
        d.write(ACSR, 0x18); // ACI write-one-to-clear; ACO is read-only
        try testing.expectEqual(@as(u8, 0x20), d.read(ACSR) & 0x30);
        d.write(ACSR, 0x80); // disable: host input changes do not signal interrupts
        d.setComparatorInputs(0, 500);
        d.tick(10);
        try testing.expectEqual(@as(?u8, null), d.pending());
    }
}

test "comparator ADC mux, explicit bandgap sample and ADC comparator-edge trigger" {
    var d: Devices = .{ .mega = true };
    d.reset();
    d.setAnalog(10, 800);
    d.setComparatorInputs(600, 100);
    d.write(ADMUX, 2);
    d.write(ADCSRB, 0x48); // ACME and MUX5: negative input ADC10
    d.tick(2);
    try testing.expectEqual(@as(u8, 0), d.read(ACSR) & 0x20);
    d.setAnalog(10, 400);
    d.tick(2);
    try testing.expectEqual(@as(u8, 0x20), d.read(ACSR) & 0x20);
    d.setBandgap(225);
    d.write(ACSR, 0x50); // bandgap positive, clear previous ACI
    d.tick(2);
    try testing.expectEqual(@as(u8, 0), d.read(ACSR) & 0x20);
    d.write(ADMUX, 30);
    d.write(ADCSRB, 0);
    d.write(ADCSRA, 0xC0);
    d.tick(50);
    const bandgap = @as(u16, d.read(ADCL)) | @as(u16, d.read(ADCH)) << 8;
    try testing.expectEqual(@as(u16, 225), bandgap);
    d.write(ACSR, 0x10); // external comparator inputs, clear ACI
    d.write(ADCSRB, 1); // comparator ADC trigger
    d.write(ADCSRA, 0xA0);
    d.setComparatorInputs(0, 100);
    d.tick(2);
    d.write(ACSR, 0x10);
    d.setComparatorInputs(600, 100);
    d.tick(2);
    try testing.expectEqual(@as(u8, 0x40), d.read(ADCSRA) & 0x40);
}

test "asynchronous Timer2 commits each register after two oscillator edges and ignores CPU clock" {
    for ([_]bool{ false, true }) |mega| {
        var d: Devices = .{ .mega = mega };
        d.reset();
        d.write(ASSR, 0x20);
        d.write(TCCR2B, 1);
        d.write(TCNT2, 0xFE);
        d.write(OCR2A, 0xFF);
        try testing.expectEqual(@as(u8, 0x19), d.read(ASSR) & 0x1F);
        d.tick(1000);
        try testing.expectEqual(@as(u8, 0), d.read(TCNT2));
        d.asyncTick(1);
        try testing.expectEqual(@as(u8, 0), d.read(TCNT2));
        try testing.expectEqual(@as(u8, 0x19), d.read(ASSR) & 0x1F);
        d.asyncTick(1);
        try testing.expectEqual(@as(u8, 0xFE), d.read(TCNT2));
        try testing.expectEqual(@as(u8, 0), d.read(ASSR) & 0x1F);
        d.write(PRR, PRTIM2); // PRR stops only synchronous Timer2
        d.asyncTick(2);
        try testing.expectEqual(@as(u8, 0), d.read(TCNT2));
        try testing.expectEqual(@as(u8, 3), d.read(TIFR2) & 3);
        d.write(TIMSK2, 2);
        try testing.expectEqual(@as(?u8, if (mega) 13 else Vec.t2_compa), d.pending());
        d.write(ASSR, 0);
        d.write(PRR, 0);
        d.tick(1);
        try testing.expectEqual(@as(u8, 1), d.read(TCNT2));
    }
}

test "TWI master has timed address/data ACK or NACK, repeated START, reads and auto-clearing STOP" {
    var d: Devices = .{ .mega = true };
    d.reset();
    d.write(TWBR, 2);
    d.write(TWSR, 1); // bit time = 16 + 2*2*4 = 32 clocks
    d.write(TWCR, 0xA5); // START, enable, interrupt enabled
    d.tick(31);
    try testing.expectEqual(@as(u8, 0), d.read(TWCR) & 0x80);
    d.tick(1);
    try testing.expectEqual(@as(u8, 0x09), d.read(TWSR));
    try testing.expectEqual(@as(?u8, 39), d.pending());
    Devices.sysAck(&d, 39); // TWI interrupt flag is software-cleared only
    try testing.expectEqual(@as(?u8, 39), d.pending());
    d.write(TWDR, 0xA0);
    d.write(TWCR, 0x85);
    try testing.expect(d.twiReply(.ack, 0));
    d.tick(32 * 9);
    try testing.expectEqual(@as(u8, 0x19), d.read(TWSR));
    d.write(TWDR, 0x42);
    d.write(TWCR, 0x85);
    try testing.expect(d.twiReply(.ack, 0));
    d.tick(32 * 9);
    try testing.expectEqual(@as(u8, 0x29), d.read(TWSR));
    d.write(TWCR, 0xA5); // repeated START keeps master ownership
    d.tick(32);
    try testing.expectEqual(@as(u8, 0x11), d.read(TWSR));
    d.write(TWDR, 0xA1);
    d.write(TWCR, 0x85);
    try testing.expect(d.twiReply(.ack, 0));
    d.tick(32 * 9);
    try testing.expectEqual(@as(u8, 0x41), d.read(TWSR));
    d.write(TWCR, 0xC5); // receive and ACK first byte
    try testing.expect(d.twiReply(.ack, 0xAB));
    d.tick(32 * 9);
    try testing.expectEqual(@as(u8, 0x51), d.read(TWSR));
    try testing.expectEqual(@as(u8, 0xAB), d.read(TWDR));
    d.write(TWCR, 0x85); // receive and NACK last byte
    try testing.expect(d.twiReply(.ack, 0xCD));
    d.tick(32 * 9);
    try testing.expectEqual(@as(u8, 0x59), d.read(TWSR));
    try testing.expectEqual(@as(u8, 0xCD), d.read(TWDR));
    d.write(TWCR, 0x95); // STOP is not an interrupt event
    d.tick(32);
    try testing.expectEqual(@as(u8, 0), d.read(TWCR) & 0x90);
    try testing.expectEqual(@as(u8, 0xF9), d.read(TWSR));
    try testing.expectEqual(@as(?u8, null), d.pending());
    const kinds = [_]TwiEvent.Kind{ .start, .address, .write, .start, .address, .read, .read, .stop };
    const values = [_]u8{ 0, 0xA0, 0x42, 0, 0xA1, 0xAB, 0xCD, 0 };
    for (kinds, values) |kind, value| {
        const event = d.twiPop().?;
        try testing.expectEqual(kind, event.kind);
        try testing.expectEqual(value, event.value);
    }
    try testing.expectEqual(@as(?TwiEvent, null), d.twiPop());
}

test "TWI no peer NACK, collision, clock gating, arbitration loss and bus errors remain visible" {
    var d = fresh();
    d.write(TWDR, 0x55); // TWINT clear: writing data is forbidden
    try testing.expectEqual(@as(u8, 0xFF), d.read(TWDR));
    try testing.expectEqual(@as(u8, 8), d.read(TWCR) & 8);
    d.write(TWCR, 0xA4);
    d.write(PRR, 0x80);
    d.tick(1000);
    try testing.expectEqual(@as(u8, 0), d.read(TWCR) & 0x80);
    d.write(PRR, 0);
    d.tick(16);
    d.write(TWDR, 0x20);
    try testing.expectEqual(@as(u8, 0), d.read(TWCR) & 8);
    d.write(TWCR, 0x84);
    d.tick(16 * 9);
    try testing.expectEqual(@as(u8, 0x20), d.read(TWSR)); // unacknowledged address
    for ([_]TwiReply{ .arbitration_lost, .bus_error }, [_]u8{ 0x38, 0 }) |reply, expected| {
        d.write(TWCR, 0xA4);
        d.tick(16);
        d.write(TWDR, 0x20);
        d.write(TWCR, 0x84);
        try testing.expect(d.twiReply(reply, 0));
        d.tick(16 * 9);
        try testing.expectEqual(expected, d.read(TWSR));
        try testing.expectEqual(@as(u8, 0), d.st.twi.master);
    }
    try testing.expect(!d.twiReply(.ack, 0)); // no in-flight byte
}

test "TWI slave address masks, general call, clock stretching, data ACK and transmitted bytes" {
    var d = fresh();
    d.write(TWAR, 0x51); // own address0x28, general calls enabled
    d.write(TWAMR, 2); // low address bit is don't-care
    d.write(TWCR, 0x44); // enable and ACK
    try testing.expect(!d.twiAddress(0x30, false));
    try testing.expect(d.twiAddress(0x29, false));
    try testing.expectEqual(@as(u8, 0x60), d.read(TWSR));
    try testing.expect(!d.twiReceive(1)); // TWINT stretches SCL until guest services it
    d.write(TWCR, 0xC4);
    try testing.expect(d.twiReceive(0xA5));
    try testing.expectEqual(@as(u8, 0x80), d.read(TWSR));
    try testing.expectEqual(@as(u8, 0xA5), d.read(TWDR));
    d.write(TWCR, 0xC4);
    try testing.expect(d.twiStop());
    try testing.expectEqual(@as(u8, 0xA0), d.read(TWSR));
    d.write(TWCR, 0xC4);
    try testing.expect(d.twiAddress(0, false));
    try testing.expectEqual(@as(u8, 0x70), d.read(TWSR));
    d.write(TWCR, 0x84); // next receive NACK
    try testing.expect(d.twiReceive(0x33));
    try testing.expectEqual(@as(u8, 0x98), d.read(TWSR));
    d.write(TWCR, 0xC4);
    try testing.expect(d.twiAddress(0x28, true));
    try testing.expectEqual(@as(u8, 0xA8), d.read(TWSR));
    d.write(TWDR, 0x12);
    d.write(TWCR, 0xC4);
    try testing.expectEqual(@as(?u8, 0x12), d.twiTransmit(true));
    try testing.expectEqual(@as(u8, 0xB8), d.read(TWSR));
    d.write(TWDR, 0x34);
    d.write(TWCR, 0xC4);
    try testing.expectEqual(@as(?u8, 0x34), d.twiTransmit(false));
    try testing.expectEqual(@as(u8, 0xC0), d.read(TWSR));
    try testing.expectEqual(@as(?u8, null), d.twiTransmit(true));
}

test "ELPM reads the1280 upper flash and increments RAMPZ across the physical wrap, LPM ignores it" {
    var t: emu.cpu.TestRig = .{};
    try t.init(&.{ 0x9107, 0x95D8, 0x9114 }); // ELPM r16,Z+; ELPM; LPM r17,Z
    defer t.deinit();
    var d: Devices = .{ .mega = true };
    d.reset();
    t.bus.dev = d.device();
    t.cpu.sys = d.sys();
    t.cpu.program_mask = 0xFFFF;
    t.prog[0x1FFFF] = 0xA5;
    t.prog[0x10100] = 0x5A;
    t.prog[0x100] = 0xC3;
    t.cpu.setSreg(0x55);
    t.cpu.setReg16(30, 0xFFFF);
    d.write(RAMPZ, 0xFF);
    try t.steps(1);
    try testing.expectEqual(@as(u8, 0xA5), t.cpu.reg(16));
    try testing.expectEqual(@as(u16, 0), t.cpu.reg16(30));
    try testing.expectEqual(@as(u8, 0), d.read(RAMPZ));
    t.cpu.setReg16(30, 0x100);
    d.write(RAMPZ, 1);
    try t.steps(1);
    try testing.expectEqual(@as(u8, 0x5A), t.cpu.reg(0));
    try t.steps(1);
    try testing.expectEqual(@as(u8, 0xC3), t.cpu.reg(17));
    try testing.expectEqual(@as(u8, 0x55), t.cpu.sregByte());
    try testing.expectEqual(@as(u64, 9), t.cpu.st.cycles);
    var small: emu.cpu.TestRig = .{};
    try small.init(&.{0x95D8});
    defer small.deinit();
    small.cpu.step();
    try testing.expectEqual(emu.cpu.Stop{ .invalid = 0 }, small.cpu.stop.?);
}

const SpmTest = struct {
    fn command(t: *emu.cpu.TestRig, d: *Devices, control: u8, address: u32, word: u16) !void {
        t.cpu.st.pc = d.bootStart();
        t.cpu.setReg16(30, @truncate(address));
        if (d.mega) d.write(RAMPZ, @truncate(address >> 16));
        t.cpu.setReg16(0, word);
        t.cpu.write(SPMCSR, control);
        try t.steps(1);
    }
};

test "external reset preserves pending flash programming but erases the temporary buffer" {
    for ([_]bool{ false, true }) |mega| {
        for ([_]u8{ 3, 5 }) |operation| {
            var t: emu.cpu.TestRig = .{};
            try t.init(&.{0x0000});
            defer t.deinit();
            var d: Devices = .{ .mega = mega };
            d.reset();
            d.configureFuses(0x77, 0x99, 0xFE, 0xFF);
            t.bus.dev = d.device();
            t.cpu.sys = d.sys();
            t.cpu.program_mask = if (mega) 0xFFFF else emu.cpu.pc_mask;
            const boot = @as(usize, d.bootStart()) * 2;
            std.mem.writeInt(u16, t.prog[boot..][0..2], 0x95E8, .little);
            @memset(t.prog[0x100..0x180], if (operation == 3) 0 else 0xFF);
            try SpmTest.command(&t, &d, 1, 0x100, 0xA55A);
            try SpmTest.command(&t, &d, operation, 0x100, 0);
            d.tick(137);
            const remaining = d.st.spm_busy;
            try testing.expect(remaining > 1);
            d.resetWithCause(.external);
            try testing.expectEqual(remaining, d.st.spm_busy);
            try testing.expectEqual(@as(u8, 0x40) | operation, d.read(SPMCSR));
            try testing.expectEqual(@as(u8, 0xFF), d.st.spm_buffer[0]);
            d.tick(remaining - 1);
            try testing.expectEqual(@as(u8, if (operation == 3) 0 else 0xFF), t.prog[0x100]);
            d.tick(1);
            const word = std.mem.readInt(u16, t.prog[0x100..][0..2], .little);
            try testing.expectEqual(@as(u16, if (operation == 3) 0xFFFF else 0xA55A), word);
            try testing.expectEqual(@as(u32, 0), d.st.spm_busy);
        }
    }
}

test "164P EEPROM invalidates loaded flash data until buffer erase while 1280 retains it" {
    for ([_]bool{ false, true }) |mega| {
        var t: emu.cpu.TestRig = .{};
        try t.init(&.{0x0000});
        defer t.deinit();
        var d: Devices = .{ .mega = mega };
        d.reset();
        d.configureFuses(0x77, 0x99, 0xFE, 0xFF);
        t.bus.dev = d.device();
        t.cpu.sys = d.sys();
        t.cpu.program_mask = if (mega) 0xFFFF else emu.cpu.pc_mask;
        const boot = @as(usize, d.bootStart()) * 2;
        std.mem.writeInt(u16, t.prog[boot..][0..2], 0x95E8, .little);
        try SpmTest.command(&t, &d, 1, 0x100, 0xA55A);
        d.write(EEDR, 0x77);
        d.write(EECR, 4);
        d.write(EECR, 2);
        d.tick(d.st.ee_busy);
        try testing.expectEqual(@as(u8, 0x77), d.st.ee[0]);
        if (!mega) {
            try testing.expectError(error.Stopped, SpmTest.command(&t, &d, 5, 0x100, 0));
            try testing.expectEqual(@as(emu.cpu.Stop, .undefined_spm_buffer), t.cpu.stop.?);
            try testing.expectEqual(@as(u32, 0), d.st.spm_busy);
            try testing.expectEqual(@as(u8, 0xFF), t.prog[0x100]);
            t.cpu.stop = null;
            try SpmTest.command(&t, &d, 0x11, 0, 0);
            try SpmTest.command(&t, &d, 1, 0x100, 0xA55A);
        }
        try SpmTest.command(&t, &d, 5, 0x100, 0);
        d.tick(d.st.spm_busy);
        try testing.expectEqual(@as(u16, 0xA55A), std.mem.readInt(u16, t.prog[0x100..][0..2], .little));
    }
}

test "EEPROM and flash self-programming exclude each other in either order" {
    for ([_]bool{ false, true }) |mega| {
        var t: emu.cpu.TestRig = .{};
        try t.init(&.{0x0000});
        defer t.deinit();
        var d: Devices = .{ .mega = mega };
        d.reset();
        d.configureFuses(0x77, 0x99, 0xFE, 0xFF);
        t.bus.dev = d.device();
        t.cpu.sys = d.sys();
        t.cpu.program_mask = if (mega) 0xFFFF else emu.cpu.pc_mask;
        const boot = @as(usize, d.bootStart()) * 2;
        std.mem.writeInt(u16, t.prog[boot..][0..2], 0x95E8, .little);
        try SpmTest.command(&t, &d, 3, 0x100, 0);
        try testing.expect(d.st.spm_busy > 0);
        d.write(EEDR, 0x5A);
        d.write(EECR, 4);
        d.write(EECR, 2);
        try testing.expectEqual(@as(u32, 0), d.st.ee_busy);
        d.tick(6800);
        try testing.expect(d.st.spm_busy > 0);
        try testing.expectEqual(@as(u8, 0xFF), d.st.ee[0]);
        d.tick(d.st.spm_busy);
        d.write(EECR, 4);
        d.write(EECR, 2);
        try testing.expect(d.st.ee_busy > 0);
        try SpmTest.command(&t, &d, 3, 0x100, 0);
        try testing.expectEqual(@as(u32, 0), d.st.spm_busy);
        d.tick(d.st.ee_busy);
        try testing.expectEqual(@as(u8, 0x5A), d.st.ee[0]);
        try SpmTest.command(&t, &d, 3, 0x100, 0);
        try testing.expect(d.st.spm_busy > 0);
    }
}

test "SPM instructions enforce boot and lock permissions, page erase/write timing, NOR writes and RWW enable" {
    for ([_]bool{ false, true }) |mega| {
        var t: emu.cpu.TestRig = .{};
        try t.init(&.{0x95E8}); // application SPM cannot self-program
        defer t.deinit();
        var d: Devices = .{ .mega = mega };
        d.reset();
        t.bus.dev = d.device();
        t.cpu.sys = d.sys();
        t.cpu.program_mask = if (mega) 0xFFFF else emu.cpu.pc_mask;
        const boot = @as(usize, d.bootStart()) * 2;
        std.mem.writeInt(u16, t.prog[boot..][0..2], 0x95E8, .little);
        @memset(t.prog[0x100..0x200], 0);
        t.cpu.write(SPMCSR, 3);
        t.cpu.setReg16(30, 0x100);
        try t.steps(1);
        try testing.expectEqual(@as(u32, 0), d.st.spm_busy);
        try testing.expectEqual(@as(u8, 0), t.prog[0x100]);
        try SpmTest.command(&t, &d, 3, 0x100, 0); // observed lock0xEA denies application writes
        try testing.expectEqual(@as(u32, 0), d.st.spm_busy);
        d.configureFuses(0x77, 0x99, 0xFE, 0xFF); // explicit unlocked programmer fixture
        try SpmTest.command(&t, &d, 1, 0x100, 0xE50A); // LDI r16,0x5A
        try SpmTest.command(&t, &d, 3, 0x100, 0);
        try testing.expect(d.st.spm_busy > 0);
        const remaining = d.st.spm_busy;
        d.tick(remaining - 1);
        try testing.expectEqual(@as(u8, 0), t.prog[0x100]);
        d.tick(1);
        try testing.expectEqual(@as(u8, 0xFF), t.prog[0x100]);
        try SpmTest.command(&t, &d, 5, 0x100, 0);
        d.tick(d.st.spm_busy);
        try testing.expectEqual(@as(u16, 0xE50A), std.mem.readInt(u16, t.prog[0x100..][0..2], .little));
        try testing.expectEqual(@as(u8, 0x40), d.read(SPMCSR));
        t.cpu.st.pc = 0x80;
        const cycles = t.cpu.st.cycles;
        try t.steps(1); // instruction fetch is blocked until RWW is explicitly re-enabled
        try testing.expectEqual(@as(u16, 0x80), t.cpu.st.pc);
        try testing.expectEqual(cycles + 1, t.cpu.st.cycles);
        try SpmTest.command(&t, &d, 0x11, 0, 0);
        t.cpu.st.pc = 0x80;
        try t.steps(1);
        try testing.expectEqual(@as(u8, 0x5A), t.cpu.reg(16));
        try SpmTest.command(&t, &d, 1, 0x100, 0xFFFF);
        try SpmTest.command(&t, &d, 5, 0x100, 0); // programming cannot turn zero bits back to ones
        d.tick(d.st.spm_busy);
        try testing.expectEqual(@as(u16, 0xE50A), std.mem.readInt(u16, t.prog[0x100..][0..2], .little));
        try SpmTest.command(&t, &d, 0x11, 0, 0);
        t.cpu.write(SPMCSR, 1);
        d.tick(4); // expired enable window
        t.cpu.st.pc = d.bootStart();
        t.cpu.setReg16(0, 0);
        try t.steps(1);
        try testing.expectEqual(@as(u8, 0xFF), d.st.spm_buffer[0]);
    }
}

test "NRWW self-programming stalls the CPU and lock programming never restores bits" {
    var t: emu.cpu.TestRig = .{};
    try t.init(&.{0x0000});
    defer t.deinit();
    var d: Devices = .{};
    d.reset();
    d.configureFuses(0x77, 0x99, 0xFE, 0xFF);
    t.bus.dev = d.device();
    t.cpu.sys = d.sys();
    const boot = @as(usize, d.bootStart()) * 2;
    std.mem.writeInt(u16, t.prog[boot..][0..2], 0x95E8, .little);
    try SpmTest.command(&t, &d, 9, 1, 0xEA);
    d.tick(d.st.spm_busy);
    try testing.expectEqual(@as(u8, 0xEA), d.fuses().lock);
    try SpmTest.command(&t, &d, 9, 1, 0xFF);
    d.tick(d.st.spm_busy);
    try testing.expectEqual(@as(u8, 0xEA), d.fuses().lock);
    d.configureFuses(0x77, 0x99, 0xFE, 0xFF);
    try SpmTest.command(&t, &d, 3, d.rwwLimit(), 0);
    const paused = t.cpu.st.pc;
    const remaining = d.st.spm_busy;
    try t.steps(10);
    try testing.expectEqual(paused, t.cpu.st.pc);
    try testing.expectEqual(remaining - 10, d.st.spm_busy);
    d.tick(d.st.spm_busy);
    try testing.expectEqual(@as(u8, 0xFF), t.prog[boot]);
    try testing.expectEqual(@as(u8, 0), d.read(SPMCSR));
}

test "LPM reads configured fuses/signature and boot lock protection through real guest instructions" {
    var t: emu.cpu.TestRig = .{};
    try t.init(&.{0x95C8}); // LPM r0,Z
    defer t.deinit();
    var d: Devices = .{};
    d.reset();
    t.bus.dev = d.device();
    t.cpu.sys = d.sys();
    for ([_]u8{ 0x77, 0xEA, 0xFE, 0x99 }, 0..) |expected, address| {
        t.cpu.st.pc = 0;
        t.cpu.setReg16(30, @intCast(address));
        t.cpu.write(SPMCSR, 9);
        try t.steps(1);
        try testing.expectEqual(expected, t.cpu.reg(0));
        try testing.expectEqual(@as(u8, 0), d.read(SPMCSR));
    }
    for ([_]u16{ 0, 2, 4 }, [_]u8{ 0x1E, 0x94, 0x0A }) |address, expected| {
        t.cpu.st.pc = 0;
        t.cpu.setReg16(30, address);
        t.cpu.write(SPMCSR, 0x21);
        try t.steps(1);
        try testing.expectEqual(expected, t.cpu.reg(0));
    }
    d.configureFuses(0x77, 0x99, 0xFE, 0xDF); // BLB12 blocks application LPM of boot flash
    t.prog[@as(usize, d.bootStart()) * 2] = 0xAB;
    t.cpu.st.pc = 0;
    t.cpu.setReg16(30, d.bootStart() * 2);
    try t.steps(1);
    try testing.expectEqual(@as(u8, 0), t.cpu.reg(0));
}

test "MCUCR interrupt relocation uses fuse-sized boot vectors and waits through the next instruction" {
    var t: emu.cpu.TestRig = .{};
    try t.init(&.{ 0x0000, 0x0000, 0x0000, 0x0000 });
    defer t.deinit();
    var d: Devices = .{};
    d.reset();
    d.configureFuses(0x77, 0x99, 0xFE, 0xFF);
    t.bus.dev = d.device();
    t.cpu.sys = d.sys();
    d.write(EIMSK, 1); // INT0 low-level input held low
    t.cpu.setSreg(0x80);
    t.cpu.write(MCUCR, 1);
    try t.steps(1); // IVCE disables interrupts, preserves SREG.I
    try testing.expectEqual(@as(u16, 1), t.cpu.st.pc);
    try testing.expectEqual(@as(u8, 0x80), t.cpu.sregByte());
    t.cpu.write(MCUCR, 2);
    try t.steps(1); // next instruction also completes before an IRQ
    try testing.expectEqual(@as(u16, 2), t.cpu.st.pc);
    try t.steps(1);
    try testing.expectEqual(d.bootStart() + 2, t.cpu.st.pc);
    try testing.expectEqual(@as(u16, 2), t.cpu.popPc());
    d.reset();
    d.write(MCUCR, 2); // no timed enable: IVSEL remains clear
    try testing.expectEqual(@as(u8, 0), d.read(MCUCR) & 2);
    d.write(MCUCR, 1);
    d.tick(4);
    d.write(MCUCR, 2); // expired timed enable
    try testing.expectEqual(@as(u8, 0), d.read(MCUCR) & 3);
    d.configureFuses(0x77, 0x98, 0xFE, 0xFF);
    try testing.expectEqual(@as(u16, 0x1C00), d.resetVector());
    d.reset();
    try testing.expectEqual(@as(u16, 0x1C00), d.resetVector());
}

test "SBI/CBI preserve unrelated write-one-to-clear flags and do not toggle other PIN bits" {
    var t: emu.cpu.TestRig = .{};
    try t.init(&.{ 0x9AA9, 0x98A8, 0x9A00 }); // SBI TIFR0,1; CBI TIFR0,0; SBI PINA,0
    defer t.deinit();
    var d: Devices = .{};
    d.reset();
    t.bus.dev = d.device();
    t.cpu.sys = d.sys();
    d.st.io[TIFR0] = 7;
    try t.steps(1);
    try testing.expectEqual(@as(u8, 5), d.read(TIFR0));
    try t.steps(1);
    try testing.expectEqual(@as(u8, 5), d.read(TIFR0));
    d.setPinsIn(0, 0xFF);
    try t.steps(1);
    try testing.expectEqual(@as(u8, 1), d.read(0x22));
}

test "SPM ready is a level IRQ, EEPROM excludes SPM, and MCUCR/MCUSR keep timed/W0C semantics" {
    for ([_]bool{ false, true }) |mega| {
        var d: Devices = .{ .mega = mega };
        d.reset();
        d.write(SPMCSR, 0x80);
        const vector_number: u8 = if (mega) 40 else Vec.spm_ready;
        try testing.expectEqual(@as(?u8, vector_number), d.pending());
        Devices.sysAck(&d, vector_number);
        try testing.expectEqual(@as(?u8, vector_number), d.pending());
        d.write(SPMCSR, 0);
        d.write(EECR, 4);
        d.write(EECR, 2);
        d.write(SPMCSR, 3);
        try testing.expectEqual(@as(u8, 0), d.read(SPMCSR));
        d.write(MCUCR, 0x80);
        try testing.expectEqual(@as(u8, 0), d.read(MCUCR) & 0x80);
        d.tick(4);
        d.write(MCUCR, 0x80); // expired first attempt cannot change JTD
        try testing.expectEqual(@as(u8, 0), d.read(MCUCR) & 0x80);
        d.write(MCUCR, 0x80);
        try testing.expectEqual(@as(u8, 0x80), d.read(MCUCR) & 0x80);
        d.write(MCUSR, 0xFF); // software cannot set hardware reset-cause flags
        try testing.expectEqual(@as(u8, 1), d.read(MCUSR));
        d.write(MCUSR, 0);
        try testing.expectEqual(@as(u8, 0), d.read(MCUSR));
        d.write(CLKPR, 0x80);
        try testing.expectEqual(@as(u8, 0x83), d.read(CLKPR));
        d.tick(4);
        try testing.expectEqual(@as(u8, 3), d.read(CLKPR));
    }
    var d = fresh();
    d.write(MCUCR, 0x60);
    d.tick(1);
    d.write(MCUCR, 0x40);
    try testing.expectEqual(@as(u8, 0x40), d.read(MCUCR) & 0x60);
    d.tick(3);
    try testing.expectEqual(@as(u8, 0), d.read(MCUCR) & 0x60);
}

test "1280 SLEEP with global interrupts clear wakes on asynchronous IRQ without clearing flags" {
    var t: emu.cpu.TestRig = .{};
    try t.init(&.{ 0x9588, 0xE50A }); // SLEEP; LDI r16,0x5A
    defer t.deinit();
    var d: Devices = .{ .mega = true };
    d.reset();
    t.bus.dev = d.device();
    t.cpu.sys = d.sys();
    d.write(SMCR, 5); // power-down, SE
    d.write(EICRA, 3); // INT0 rising edge
    d.write(EIMSK, 1);
    try t.steps(1);
    try testing.expectEqual(@as(u8, 1), t.cpu.st.sleeping);
    try t.steps(2);
    try testing.expectEqual(@as(u16, 1), t.cpu.st.pc);
    d.setPinsIn(3, 1); // Asynchronous INT0/PD0 rising.
    const cycles = t.cpu.st.cycles;
    try t.steps(1);
    try testing.expectEqual(@as(u8, 0), t.cpu.st.sleeping);
    try testing.expectEqual(@as(u16, 1), t.cpu.st.pc);
    try testing.expectEqual(cycles + 4, t.cpu.st.cycles);
    try testing.expectEqual(@as(u16, 0x4FF), t.cpu.st.sp);
    try testing.expectEqual(@as(u8, 1), d.read(EIFR));
    try t.steps(1);
    try testing.expectEqual(@as(u8, 0x5A), t.cpu.reg(16));
}

test "SEI followed by SLEEP takes pending IRQ after wake latency and returns after SLEEP" {
    var t: emu.cpu.TestRig = .{};
    try t.init(&.{ 0x9478, 0x9588, 0xE50A }); // SEI; SLEEP; LDI r16,0x5A
    defer t.deinit();
    std.mem.writeInt(u16, t.prog[0x40..][0..2], 0x9518, .little); // RETI, Timer0 compareA vector16
    var d: Devices = .{};
    d.reset();
    t.bus.dev = d.device();
    t.cpu.sys = d.sys();
    d.write(SMCR, 1); // Idle sleep
    d.write(TIMSK0, 2);
    d.st.io[TIFR0] = 2;
    try t.steps(2);
    try testing.expectEqual(@as(u8, 1), t.cpu.st.sleeping);
    try testing.expectEqual(@as(u16, 2), t.cpu.st.pc);
    const cycles = t.cpu.st.cycles;
    try t.steps(1);
    try testing.expectEqual(@as(u16, 0x20), t.cpu.st.pc);
    try testing.expectEqual(cycles + 8, t.cpu.st.cycles);
    try testing.expectEqual(@as(u8, 0), d.read(TIFR0));
    try t.steps(2);
    try testing.expectEqual(@as(u8, 0x5A), t.cpu.reg(16));
}

test "sleep clock domains stop synchronous peripherals, preserve watchdog and gate asynchronous Timer2" {
    for ([_]u8{ 1, 2, 3, 6, 7 }) |mode| {
        var t: emu.cpu.TestRig = .{};
        try t.init(&.{ 0x9588, 0x0000 });
        defer t.deinit();
        var d: Devices = .{};
        d.reset();
        t.bus.dev = d.device();
        t.cpu.sys = d.sys();
        d.write(TCCR0B, 1);
        d.write(TCCR1B, 1);
        d.write(UCSR0A + 1, 8);
        d.write(UCSR0A + 6, 0x41);
        d.write(SPCR, 0x50); // SPI master, clk/4
        d.write(SPDR, 0x55);
        d.write(ASSR, 0x20);
        d.write(TCCR2B, 1);
        d.asyncTick(2); // commit asynchronous clock source register
        d.write(SMCR, 1 | mode << 1);
        d.write(WDTCSR, 0x40); // watchdog interrupt remains active in every supported sleep mode
        try t.steps(1);
        const timer0 = d.read(TCNT0);
        const timer1 = d.st.timer[0].count;
        const timer2 = d.read(TCNT2);
        const uart_busy = d.st.usart[0].tx_busy;
        const spi_busy = d.st.master_busy;
        const watchdog = d.st.wdt_count;
        try t.steps(20);
        try testing.expectEqual(timer0, d.read(TCNT0));
        try testing.expectEqual(timer1, d.st.timer[0].count);
        try testing.expectEqual(uart_busy, d.st.usart[0].tx_busy);
        try testing.expectEqual(spi_busy, d.st.master_busy);
        try testing.expectEqual(watchdog + 20, d.st.wdt_count);
        d.asyncTick(10);
        try testing.expectEqual(timer2 + (if (mode == 2 or mode == 6) @as(u8, 0) else 10), d.read(TCNT2));
        try testing.expectEqual(@as(u8, 1), t.cpu.st.sleeping);
        d.tick(@intCast(d.wdtPeriod()));
        const cycles = t.cpu.st.cycles;
        try t.steps(1); // WDT wakes even though globalI remains clear
        try testing.expectEqual(@as(u8, 0), t.cpu.st.sleeping);
        try testing.expectEqual(cycles + (if (mode == 6 or mode == 7) @as(u64, 6) else 4), t.cpu.st.cycles);
    }
}

test "ADC noise reduction starts a conversion and wakes only eligible clock-domain interrupts" {
    var t: emu.cpu.TestRig = .{};
    try t.init(&.{ 0x9588, 0xE007 });
    defer t.deinit();
    var d: Devices = .{};
    d.reset();
    t.bus.dev = d.device();
    t.cpu.sys = d.sys();
    d.setAnalog(0, 600);
    d.write(ADCSRA, 0x88); // ADC enabled, ADC interrupt enabled, no software start
    d.write(TIMSK0, 2);
    d.st.io[TIFR0] = 2; // synchronous Timer0 flag cannot wake ADC-noise sleep
    d.write(SMCR, 3);
    try t.steps(1);
    try testing.expect(d.st.adc_busy != 0);
    try t.steps(50);
    try testing.expectEqual(@as(u8, 1), t.cpu.st.sleeping);
    try t.steps(1);
    try testing.expectEqual(@as(u8, 0), t.cpu.st.sleeping);
    try testing.expectEqual(@as(u8, 0x10), d.read(ADCSRA) & 0x10);
    try t.steps(1);
    try testing.expectEqual(@as(u8, 7), t.cpu.reg(16));
}

test "round4 external reset preserves the latched EEPROM transaction and programming time" {
    for ([_]bool{ false, true }) |mega| {
        for ([_]u8{ 0, 1, 2 }) |mode| {
            var d: Devices = .{ .mega = mega };
            d.reset();
            const address: u16 = if (mega) 0x823 else 0x123;
            d.st.ee[address] = 0xA5;
            d.write(EEARH, @truncate(address >> 8));
            d.write(EEARL, @truncate(address));
            d.write(EEDR, 0x5A);
            d.write(EECR, (mode << 4) | 4);
            d.write(EECR, (mode << 4) | 2);
            d.tick(37);
            const remaining = d.st.ee_busy;
            try testing.expect(remaining > 1);
            d.resetWithCause(.external);
            try testing.expectEqual(remaining, d.st.ee_busy);
            try testing.expectEqual(@as(u8, 2), d.read(EECR) & 2);
            d.write(EEARH, 0);
            d.write(EEARL, 0);
            d.write(EEDR, 0);
            d.write(EECR, 0x30); // New register contents must not alter the active write.
            d.tickReset(remaining - 1);
            try testing.expectEqual(@as(u8, 0xA5), d.st.ee[address]);
            d.resetWithCause(.external);
            d.tickReset(1);
            try testing.expectEqual(@as(u8, if (mode == 0) 0x5A else if (mode == 1) 0xFF else 0), d.st.ee[address]);
            try testing.expectEqual(@as(u8, 0xFF), d.st.ee[0]);
            try testing.expectEqual(@as(u8, 0), d.read(EECR) & 2);
            try testing.expectEqual(@as(u16, 0), d.st.timer[0].count);
            try testing.expectEqual(@as(u64, 0), d.st.cycles);
        }
    }
}

test "round4 writing variable PWM TOP suppresses transitions until the next match after MAX" {
    for ([_]bool{ false, true }) |mega| {
        const count: usize = if (mega) 4 else 1;
        for (timer16_bases[0..count], 0..) |base, n| {
            for ([_]u8{ 8, 9, 10, 11, 14, 15 }) |mode| {
                var d: Devices = .{ .mega = mega };
                d.reset();
                d.write(base + 8, 7); // Set OCR-A before enabling its double buffer.
                d.write(base, mode & 3);
                d.write(base + 1, (mode & 12) << 1);
                if (mode == 8 or mode == 10 or mode == 14) d.write(base + 6, 7);
                d.write(base + 4, 7);
                d.tick(10); // Suppression survives while the timer is stopped.
                d.write(base + 1, ((mode & 12) << 1) | 7);
                const port: u4 = if (!mega) 1 else ([_]u4{ 3, 4, 7, 10 })[n];
                const bit: u8 = if (!mega) 2 else ([_]u8{ 0x40, 0x40, 0x80, 4 })[n];
                d.setPinsIn(port, bit);
                try testing.expectEqual(@as(u16, 8), d.st.timer[n].count);
                try testing.expectEqual(@as(u8, 0), d.st.timer[n].down);
                d.timer16(n, 2);
                try testing.expectEqual(@as(u16, 10), d.st.timer[n].count);
                d.timer16(n, 0x10000 - 10 + 7);
                try testing.expectEqual(@as(u16, 7), d.st.timer[n].count);
                try testing.expectEqual(@as(u8, 0), d.st.timer[n].down);
                d.timer16(n, 1);
                try testing.expectEqual(@as(u16, if (mode >= 14) 0 else 6), d.st.timer[n].count);
            }
        }
    }
}

test "round4 capture samples held inputs after power or sleep clock restart with filter delay" {
    for ([_]bool{ false, true }) |mega| {
        for ([_]bool{ false, true }) |sleep| {
            for ([_]bool{ false, true }) |noise| {
                const count: usize = if (mega) 4 else 1;
                for (timer16_bases[0..count], 0..) |base, n| {
                    var d: Devices = .{ .mega = mega };
                    d.reset();
                    d.write(base + 1, if (noise) 0xC0 else 0x40);
                    d.write(base + 5, 0x12);
                    d.write(base + 4, 0x34);
                    const power_register: u16 = if (n == 0) PRR else 0x65;
                    const power: u8 = if (n == 0) PRTIM1 else @as(u8, 1) << @intCast(n + 2);
                    if (sleep) {
                        d.write(SMCR, 5);
                        Devices.sysSleeping(&d, true);
                    } else d.write(power_register, power);
                    const port: u4 = if (!mega) 3 else ([_]u4{ 3, 4, 10, 10 })[n];
                    const bit: u8 = if (!mega) 0x40 else ([_]u8{ 0x10, 0x80, 1, 2 })[n];
                    d.setPinsIn(port, bit);
                    d.tick(10);
                    try testing.expectEqual(@as(u8, 0), d.read(timer16_flags[n]) & 0x20);
                    if (sleep) Devices.sysSleeping(&d, false) else d.write(power_register, 0);
                    if (noise) {
                        d.tick(3);
                        try testing.expectEqual(@as(u8, 0), d.read(timer16_flags[n]) & 0x20);
                    }
                    d.tick(1);
                    try testing.expectEqual(@as(u8, 0x20), d.read(timer16_flags[n]) & 0x20);
                    try testing.expectEqual(@as(u16, 0x1234), d.st.timer[n].capture);
                }
            }
        }
    }
}

test "round4 TWI continues transmitting after address and data NACK" {
    for ([_]bool{ false, true }) |mega| {
        for ([_]bool{ false, true }) |data_nack| {
            var d: Devices = .{ .mega = mega };
            d.reset();
            d.write(TWCR, 0xA4);
            d.tick(16);
            d.write(TWDR, 0xA0);
            d.write(TWCR, 0x84);
            try testing.expect(d.twiReply(if (data_nack) .ack else .nack, 0));
            d.tick(16 * 9);
            if (data_nack) {
                d.write(TWDR, 0x11);
                d.write(TWCR, 0x84);
                try testing.expect(d.twiReply(.nack, 0));
                d.tick(16 * 9);
            }
            try testing.expectEqual(@as(u8, if (data_nack) 0x30 else 0x20), d.read(TWSR));
            d.write(TWDR, 0x22);
            d.write(TWCR, 0x84);
            try testing.expect(d.twiReply(.ack, 0));
            d.tick(16 * 9 - 1);
            try testing.expectEqual(@as(u8, 0), d.read(TWCR) & 0x80);
            d.tick(1);
            try testing.expectEqual(@as(u8, 0x28), d.read(TWSR));
            try testing.expectEqual(@as(u8, 0x80), d.read(TWCR) & 0x80);
            var last: ?TwiEvent = null;
            while (d.twiPop()) |event| last = event;
            try testing.expectEqual(TwiEvent.Kind.write, last.?.kind);
            try testing.expectEqual(@as(u8, 0x22), last.?.value);
        }
    }
}

test "round4 combined TWI STOP and START schedules a fresh timed START" {
    for ([_]bool{ false, true }) |mega| {
        var d: Devices = .{ .mega = mega };
        d.reset();
        d.write(TWCR, 0xA4);
        d.tick(16);
        try testing.expectEqual(TwiEvent.Kind.start, d.twiPop().?.kind);
        d.write(TWCR, 0xB4);
        d.tick(15);
        try testing.expectEqual(@as(?TwiEvent, null), d.twiPop());
        d.tick(1);
        try testing.expectEqual(TwiEvent.Kind.stop, d.twiPop().?.kind);
        try testing.expectEqual(@as(u8, 0x20), d.read(TWCR) & 0xB0);
        d.tick(15);
        try testing.expectEqual(@as(?TwiEvent, null), d.twiPop());
        try testing.expectEqual(@as(u8, 0), d.read(TWCR) & 0x80);
        d.tick(1);
        try testing.expectEqual(TwiEvent.Kind.start, d.twiPop().?.kind);
        try testing.expectEqual(@as(u8, 0x08), d.read(TWSR));
        try testing.expectEqual(@as(u8, 0x80), d.read(TWCR) & 0x80);
        d.write(TWCR, 0xB4);
        d.tick(32); // A batched tick must finish both STOP and the following START.
        try testing.expectEqual(TwiEvent.Kind.stop, d.twiPop().?.kind);
        try testing.expectEqual(TwiEvent.Kind.start, d.twiPop().?.kind);
        try testing.expectEqual(@as(u8, 0x08), d.read(TWSR));
        try testing.expectEqual(@as(u8, 0x80), d.read(TWCR) & 0x80);
    }
}

test "round4 reset clock advances nonvolatile programming without clocking other devices" {
    var d = fresh();
    d.write(EEDR, 0x5A);
    d.write(EECR, 4);
    d.write(EECR, 2);
    d.write(TCCR0B, 1);
    d.write(0x81, 1);
    d.write(ADCSRA, 0xC0);
    d.write(UCSR0A + 1, 0x08);
    d.write(UCSR0A + 6, 0x51);
    d.write(WDTCSR, 0x40);
    d.write(TWCR, 0xA4);
    const before = d.st;
    d.tickReset(before.ee_busy);
    try testing.expectEqual(@as(u8, 0x5A), d.st.ee[0]);
    try testing.expectEqual(before.cycles, d.st.cycles);
    try testing.expectEqual(before.pre01, d.st.pre01);
    try testing.expectEqual(before.pre2, d.st.pre2);
    try testing.expectEqualDeep(before.timer, d.st.timer);
    try testing.expectEqualDeep(before.usart, d.st.usart);
    try testing.expectEqual(before.adc_busy, d.st.adc_busy);
    try testing.expectEqual(before.wdt_count, d.st.wdt_count);
    try testing.expectEqualDeep(before.twi, d.st.twi);
}

test "round4 writing phase PWM BOTTOM while downcounting suppresses reversal until the next BOTTOM" {
    for ([_]bool{ false, true }) |mega| {
        const count: usize = if (mega) 4 else 1;
        for (timer16_bases[0..count], 0..) |base, n| {
            for ([_]u8{ 1, 2, 3, 8, 9, 10, 11 }) |mode| {
                var d: Devices = .{ .mega = mega };
                d.reset();
                d.write(base + 8, 7);
                d.write(base, mode & 3);
                d.write(base + 1, ((mode & 12) << 1) | 1);
                if (mode == 8 or mode == 10) d.write(base + 6, 7);
                const top: u16 = if (mode >= 8) 7 else (@as(u16, 1) << @intCast(mode + 7)) - 1;
                d.tick(@as(u32, top) + 1);
                try testing.expectEqual(@as(u8, 1), d.st.timer[n].down);
                d.write(base + 1, (mode & 12) << 1);
                d.write(base + 4, 0);
                d.tick(10);
                d.write(base + 1, ((mode & 12) << 1) | 1);
                d.tick(1);
                try testing.expectEqual(@as(u16, 0xFFFF), d.st.timer[n].count);
                try testing.expectEqual(@as(u8, 1), d.st.timer[n].down);
                d.timer16(n, 2);
                try testing.expectEqual(@as(u16, 0xFFFD), d.st.timer[n].count);
                d.timer16(n, 0xFFFD);
                try testing.expectEqual(@as(u16, 0), d.st.timer[n].count);
                try testing.expectEqual(@as(u8, 1), d.st.timer[n].down);
                d.timer16(n, 1);
                try testing.expectEqual(@as(u16, 1), d.st.timer[n].count);
                try testing.expectEqual(@as(u8, 0), d.st.timer[n].down);
            }
        }
    }
}

test "EEPROM retains programming mode through busy writes and external reset for the following SBI write" {
    for ([_]bool{ false, true }) |mega| {
        for ([_]u8{ 0, 1, 2 }) |mode| {
            var d: Devices = .{ .mega = mega };
            d.reset();
            d.st.ee[0] = 0xA5;
            d.write(EEDR, 0);
            d.write(EECR, (mode << 4) | 4);
            d.write(EECR, (mode << 4) | 2);
            d.write(EECR, ((mode ^ 3) << 4) | 8);
            try testing.expectEqual(mode << 4, d.read(EECR) & 0x30);
            try testing.expectEqual(@as(u8, 0x0A), d.read(EECR) & 0x0A);
            d.resetWithCause(.external);
            try testing.expectEqual((mode << 4) | 2, d.read(EECR));
            d.tickReset(d.st.ee_busy);
            d.write(EEDR, 0xFF);
            d.write(EECR, d.read(EECR) | 4);
            d.write(EECR, d.read(EECR) | 2);
            d.tickReset(d.st.ee_busy);
            try testing.expectEqual(@as(u8, if (mode == 2) 0 else 0xFF), d.st.ee[0]);
            d.resetWithCause(.external);
            try testing.expectEqual(@as(u8, 0), d.read(EECR));
        }
    }
}

test "Timer0 and Timer2 suppress written PWM TOP and BOTTOM through MAX before their next boundary" {
    for ([_]bool{ false, true }) |mega| {
        inline for ([_]u2{ 0, 2 }) |n| {
            const base: u16 = if (n == 0) TCCR0A else TCCR2A;
            const flags: u16 = if (n == 0) TIFR0 else TIFR2;
            for ([_]u8{ 5, 7 }) |mode| {
                var d: Devices = .{ .mega = mega };
                d.reset();
                d.write(base + 3, 7);
                d.write(base + 4, 3);
                d.write(base, mode & 3);
                d.write(base + 1, ((mode & 4) << 1) | 1);
                d.timer8(n, 1); // Prime the active PWM compare buffers.
                if (mode == 5) d.timer8(n, 256);
                d.write(base + 1, (mode & 4) << 1);
                d.write(base, (mode & 3) | 0x20); // Non-inverting OCnB starts low.
                d.write(base + 3, 9); // Buffered until a real TOP transition.
                d.write(base + 2, 7);
                d.write(flags, 0xFF);
                d.tick(10);
                d.write(base + 1, ((mode & 4) << 1) | 1);
                d.tick(1);
                try testing.expectEqual(@as(u8, 8), d.read(base + 2));
                try testing.expectEqual(@as(u8, 0), d.st.down[n]);
                try testing.expectEqual(@as(u8, 0), d.read(flags));
                try testing.expectEqual(@as(u8, 7), if (n == 0) d.st.ocr0a_buf else d.st.ocr2a_buf);
                try testing.expectEqual(@as(u8, 0), if (n == 0) d.st.oc0[1] else d.st.oc2b);
                d.timer8(n, 0x100 - 8 + 7);
                try testing.expectEqual(@as(u8, 7), d.read(base + 2));
                try testing.expectEqual(@as(u8, 0), d.st.down[n]);
                d.timer8(n, 1);
                try testing.expectEqual(@as(u8, if (mode == 5) 6 else 0), d.read(base + 2));
                try testing.expectEqual(@as(u8, 9), if (n == 0) d.st.ocr0a_buf else d.st.ocr2a_buf);
                if (mode == 7) try testing.expectEqual(@as(u8, 1), if (n == 0) d.st.oc0[1] else d.st.oc2b);
            }
            for ([_]u8{ 1, 5 }) |mode| {
                var d: Devices = .{ .mega = mega };
                d.reset();
                d.write(base + 3, 7);
                d.write(base, mode & 3);
                d.write(base + 1, ((mode & 4) << 1) | 1);
                d.timer8(n, if (mode == 1) 256 else 264);
                try testing.expectEqual(@as(u8, 1), d.st.down[n]);
                d.write(base + 1, (mode & 4) << 1);
                d.write(base + 2, 0);
                d.write(flags, 0xFF);
                d.write(base + 1, ((mode & 4) << 1) | 1);
                d.tick(1);
                try testing.expectEqual(@as(u8, 0xFF), d.read(base + 2));
                try testing.expectEqual(@as(u8, 1), d.st.down[n]);
                try testing.expectEqual(@as(u8, 0), d.read(flags));
                d.timer8(n, 0xFF);
                try testing.expectEqual(@as(u8, 0), d.read(base + 2));
                try testing.expectEqual(@as(u8, 1), d.st.down[n]);
                d.timer8(n, 1);
                try testing.expectEqual(@as(u8, 1), d.read(base + 2));
                try testing.expectEqual(@as(u8, 0), d.st.down[n]);
            }
        }
    }
}

test "comparator capture timestamps and filter samples are invariant across clock partitions and gating" {
    for ([_]bool{ false, true }) |mega| {
        for ([_]bool{ false, true }) |noise| {
            var initial: Devices = .{ .mega = mega };
            initial.reset();
            initial.write(TCCR1B, if (noise) 0xC1 else 0x41);
            initial.write(ACSR, 4);
            initial.tick(10);
            initial.setComparatorInputs(900, 100);
            var four = initial;
            four.tick(4);
            try testing.expectEqual(@as(u8, if (noise) 0 else 0x20), four.read(TIFR1) & 0x20);
            four.tick(1);
            try testing.expectEqual(@as(u16, if (noise) 15 else 11), four.st.timer[0].capture);
            for (0..3) |gate| {
                var start = initial;
                if (gate == 1) start.write(PRR, PRTIM1) else if (gate == 2) {
                    start.write(SMCR, 5);
                    Devices.sysSleeping(&start, true);
                }
                var reference = start;
                for (0..8) |_| reference.tick(1);
                if (gate == 1) reference.write(PRR, 0) else if (gate == 2) Devices.sysSleeping(&reference, false);
                for (0..8) |_| reference.tick(1);
                for (0..9) |split| {
                    var actual = start;
                    actual.tick(@intCast(split));
                    actual.tick(@intCast(8 - split));
                    if (gate == 1) actual.write(PRR, 0) else if (gate == 2) Devices.sysSleeping(&actual, false);
                    actual.tick(8);
                    try testing.expectEqualDeep(reference.st, actual.st);
                }
            }
        }
    }
}

test "TWI reads idle status while TWINT is clear without losing transition state or prescaler" {
    for ([_]bool{ false, true }) |mega| {
        for (0..4) |prescaler| {
            var d: Devices = .{ .mega = mega };
            d.reset();
            const p: u8 = @intCast(prescaler);
            d.write(TWSR, p);
            d.write(TWCR, 0xA4);
            try testing.expectEqual(@as(u8, 0xF8) | p, d.read(TWSR));
            d.tick(16);
            try testing.expectEqual(@as(u8, 0x08) | p, d.read(TWSR));
            d.write(TWDR, 0xA0);
            d.write(TWCR, 0x84);
            try testing.expectEqual(@as(u8, 0xF8) | p, d.read(TWSR));
            try testing.expectEqual(@as(u8, 0x08) | p, d.st.io[TWSR]);
            try testing.expect(d.twiReply(.bus_error, 0));
            d.tick(144);
            try testing.expectEqual(p, d.read(TWSR));
            d.write(TWCR, 0x94);
            d.tick(1000);
            try testing.expectEqual(@as(u8, 0xF8) | p, d.read(TWSR));
            d.write(TWCR, 0xA4);
            d.tick(16);
            d.write(TWDR, 0xA0);
            d.write(TWCR, 0x84);
            try testing.expect(d.twiReply(.ack, 0));
            d.tick(144);
            try testing.expectEqual(@as(u8, 0x18) | p, d.read(TWSR));
        }
    }
}

test "ADC trigger, sample and completion clocks are independent of tick grouping and gating" {
    for ([_]bool{ false, true }) |mega| {
        for ([_]u3{ 6, 3, 4, 5, 7, 0 }) |source| {
            var initial: Devices = .{ .mega = mega };
            initial.reset();
            initial.setAnalog(0, 123);
            initial.write(ADCSRB, source);
            initial.write(ADCSRA, if (source == 0) 0xE0 else 0xA0);
            switch (source) {
                3 => {
                    initial.write(OCR0A, 1);
                    initial.write(TCCR0A, 2);
                    initial.write(TCCR0B, 1);
                },
                4 => {
                    initial.write(TCNT0, 0xFF);
                    initial.write(TCCR0B, 1);
                },
                5 => {
                    initial.write(OCR1BL, 1);
                    initial.write(TCCR1B, 1);
                },
                6 => {
                    initial.write(TCNT1H, 0xFF);
                    initial.write(TCNT1L, 0xFF);
                    initial.write(TCCR1B, 1);
                },
                7 => {
                    initial.write(TCCR1B, 0x41);
                    initial.setPinsIn(3, if (mega) 0x10 else 0x40);
                },
                else => {},
            }
            var reference = initial;
            for (0..30) |_| reference.tick(1);
            reference.setAnalog(0, 900);
            for (0..50) |_| reference.tick(1);
            try testing.expectEqual(@as(u16, if (source == 0) 900 else 123), @as(u16, reference.st.io[ADCL]) | @as(u16, reference.st.io[ADCH]) << 8);
            for (0..31) |split| {
                var actual = initial;
                actual.tick(@intCast(split));
                actual.tick(@intCast(30 - split));
                actual.setAnalog(0, 900);
                actual.tick(50);
                try testing.expectEqualDeep(reference.st, actual.st);
            }
        }
        for (0..3) |gate| {
            var single: Devices = .{ .mega = mega };
            single.reset();
            single.setAnalog(0, 123);
            single.write(ADCSRB, 6);
            single.write(ADCSRA, 0xA0);
            single.write(TCNT1H, 0xFF);
            single.write(TCNT1L, 0xFF);
            single.write(TCCR1B, 1);
            single.tick(4);
            if (gate == 0) single.write(PRR, PRADC) else {
                single.write(SMCR, if (gate == 1) 5 else 3);
                Devices.sysSleeping(&single, true);
            }
            var batched = single;
            const remaining = single.st.adc_busy;
            for (0..7) |_| single.tick(1);
            batched.tick(7);
            try testing.expectEqualDeep(single.st, batched.st);
            if (gate != 2) try testing.expectEqual(remaining, single.st.adc_busy);
            if (gate == 0) {
                single.write(PRR, 0);
                batched.write(PRR, 0);
            } else {
                Devices.sysSleeping(&single, false);
                Devices.sysSleeping(&batched, false);
            }
            for (0..60) |_| single.tick(1);
            batched.tick(60);
            try testing.expectEqualDeep(single.st, batched.st);
        }
    }
}

test "164P EEPROM-ready interrupts and wake wait for flash programming while 1280 stays independent" {
    for ([_]bool{ false, true }) |mega| {
        var t: emu.cpu.TestRig = .{};
        try t.init(&.{0x0000});
        defer t.deinit();
        var d: Devices = .{ .mega = mega };
        d.reset();
        d.configureFuses(0x77, 0x99, 0xFE, 0xFF);
        t.bus.dev = d.device();
        t.cpu.sys = d.sys();
        t.cpu.program_mask = if (mega) 0xFFFF else emu.cpu.pc_mask;
        const boot = @as(usize, d.bootStart()) * 2;
        std.mem.writeInt(u16, t.prog[boot..][0..2], 0x95E8, .little);
        d.write(EECR, 8);
        const ready = d.vector(Vec.ee_ready);
        try testing.expectEqual(@as(?u8, ready), d.pending());
        try SpmTest.command(&t, &d, 3, 0x100, 0);
        try testing.expect(d.st.spm_busy > 1);
        try testing.expectEqual(@as(?u8, if (mega) ready else null), d.pending());
        d.write(SMCR, 3);
        Devices.sysSleeping(&d, true);
        try testing.expectEqual(@as(?u8, if (mega) ready else null), Devices.sysPending(&d));
        d.tickReset(d.st.spm_busy - 1);
        try testing.expectEqual(@as(?u8, if (mega) ready else null), Devices.sysPending(&d));
        d.tickReset(1);
        try testing.expectEqual(@as(?u8, ready), Devices.sysPending(&d));
        Devices.sysSleeping(&d, false);
        try testing.expectEqual(@as(?u8, ready), d.pending());
    }
}

test "fixed PWM masks each committed OCR channel to its resolution without narrowing other modes" {
    for ([_]bool{ false, true }) |mega| {
        const count: usize = if (mega) 4 else 1;
        for (timer16_bases[0..count], 0..) |base, n| {
            for ([_]u8{ 1, 2, 3, 5, 6, 7, 0, 4, 8, 9, 10, 11, 12, 13, 14, 15 }) |mode| {
                var d: Devices = .{ .mega = mega };
                d.reset();
                d.write(base, mode & 3);
                d.write(base + 1, (mode & 12) << 1);
                const mask: u16 = switch (mode) {
                    1, 5 => 0xFF,
                    2, 6 => 0x1FF,
                    3, 7 => 0x3FF,
                    else => 0xFFFF,
                };
                const expected = @as(u16, 0xF302) & mask;
                const channels: usize = if (mega) 3 else 2;
                for (0..channels) |channel| {
                    const address = base + 8 + @as(u16, @intCast(channel * 2));
                    d.write(address + 1, 0xF3);
                    d.write(address, 2);
                    const value = @as(u16, d.read(address)) | @as(u16, d.read(address + 1)) << 8;
                    try testing.expectEqual(expected, value);
                    try testing.expectEqual(expected, d.st.timer[n].buffered[channel]);
                    if (mask == 0xFFFF and !Devices.timerPwm(&d.st.io, n))
                        try testing.expectEqual(expected, d.st.timer[n].compare[channel]);
                }
                if (mask != 0xFFFF) {
                    d.timer16(n, @as(u32, mask) + 1);
                    for (0..channels) |channel| try testing.expectEqual(expected, d.st.timer[n].compare[channel]);
                }
            }
        }
    }
}
