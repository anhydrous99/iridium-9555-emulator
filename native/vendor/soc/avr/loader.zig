//! Loader of avr.bin (ARCHITECTURE §3.4): program memory, cold reset, materialized start and the
//! loader self-check. avr-gcc's `__init_reset` (0x0132) clears r1 and SREG, sets SP = 0x04FF, copies
//! .data (4 bytes, flash 0x21E2 -> SRAM 0x100), clears .bss 0x104-0x47C and calls `main` (0x0E96)
//! (avr-full §1, §12). Materialized start applies those effects directly; the self-check runs the
//! real startup code from a cold reset over poisoned SRAM and compares.
const std = @import("std");
const emu = @import("emu_avr");
const Cpu = emu.Cpu;

pub const image_len = 8678;
pub const data_src = 0x21E2;
pub const data_dst = 0x100;
pub const data_len = 4;
pub const bss_lo = 0x104;
pub const bss_end = 0x47D;
pub const ramend: u16 = 0x4FF;
pub const reset_addr = 0x0132;
pub const main_addr = 0x0E96;
/// `event_loop` loop head (registry sync_pcs 0x055b): flags_dispatch is called here every pass.
pub const idle_addr = 0x0AB6;

pub fn load(prog: *emu.cpu.Prog, bytes: []const u8) error{BadImage}!void {
    if (bytes.len != image_len) return error.BadImage;
    @memset(prog, 0xFF); // erased flash beyond the image
    @memcpy(prog[0..image_len], bytes);
}

/// Power-on state of the CPU: PC 0, SP = RAMEND, SREG 0, registers 0. SRAM is not touched (its
/// power-on content is undefined).
pub fn coldReset(c: *Cpu) void {
    c.st = .{ .sp = ramend };
    @memset(c.data[0..32], 0);
    c.stop = null;
}

/// The state `__init_reset` leaves at `call main`, for the memory and registers it defines.
pub fn materialize(c: *Cpu) void {
    @memcpy(c.data[data_dst..][0..data_len], c.prog[data_src..][0..data_len]);
    @memset(c.data[bss_lo..bss_end], 0);
    c.data[1] = 0;
    c.setSreg(0);
    c.st.sp = ramend;
}

pub const SelfCheck = struct { steps: u64, cycles: u64, bytes: u32, mismatches: u32, first_bad: ?u16 };

/// Cold boot over SRAM poisoned with 0xA5 until the first instruction of `main`, then compare
/// every byte the copy loops own (0x100-0x47C) with the materialized image. Restores nothing.
pub fn selfCheck(c: *Cpu) error{StartupDidNotReachMain}!SelfCheck {
    @memset(c.data[0x100..], 0xA5);
    coldReset(c);
    var steps: u64 = 0;
    while (c.st.pc != main_addr / 2) : (steps += 1) {
        if (steps == 100_000 or c.stopped()) return error.StartupDidNotReachMain;
        c.step();
    }
    var want: emu.cpu.Data = c.data.*;
    var shadow: Cpu = .{ .data = &want, .prog = c.prog, .bus = c.bus };
    materialize(&shadow);
    var r: SelfCheck = .{ .steps = steps, .cycles = c.st.cycles, .bytes = bss_end - data_dst, .mismatches = 0, .first_bad = null };
    if (c.st.sp != ramend - 2) r.mismatches += 1; // main entered by `call` from the top of the stack
    for (data_dst..bss_end) |a| if (c.data[a] != want[a]) {
        r.mismatches += 1;
        if (r.first_bad == null) r.first_bad = @intCast(a);
    };
    if (c.data[1] != 0 or c.st.ie != 0) r.mismatches += 1; // r1 = 0 (__zero_reg__), interrupts still off
    return r;
}
