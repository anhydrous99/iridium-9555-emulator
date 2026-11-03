//! avr5 (ATmega164P) instruction decoder (ARCHITECTURE §6.1). One `Insn` per opcode word (plus the
//! second word of lds/sts/jmp/call). The opcode map follows the AVR Instruction Set Manual; the only
//! encodings llvm-objdump decodes that this decoder rejects are `1001 000d dddd 1000` (llvm: `ld Rd, Y`)
//! and `1001 001r rrrr 1000` (llvm: `st Y, Rr`), which the manual does not list (QEMU rejects them too).
//! ELPM/EIJMP/EICALL/SPM Z+/DES/XCH/LAS/LAC/LAT are not avr5 and decode as `invalid`.
const std = @import("std");

pub const Op = enum(u8) {
    invalid,
    // d = Rd, r = Rr (register numbers 0..31)
    nop,
    movw, // d, r even
    muls, // d, r in 16..31
    mulsu, // d, r in 16..23
    fmul,
    fmuls,
    fmulsu,
    cpc,
    sbc,
    add,
    cpse,
    cp,
    sub,
    adc,
    @"and",
    eor,
    @"or",
    mov,
    mul,
    // d in 16..31, k = K (0..255)
    cpi,
    sbci,
    subi,
    ori,
    andi,
    ldi,
    // d (load) or r (store), k = displacement q (0..63)
    ldd_y,
    ldd_z,
    std_y,
    std_z,
    // k = data address (second word)
    lds,
    sts,
    // d (load) / r (store)
    ld_x,
    ld_x_inc,
    ld_x_dec,
    ld_y_inc,
    ld_y_dec,
    ld_z_inc,
    ld_z_dec,
    st_x,
    st_x_inc,
    st_x_dec,
    st_y_inc,
    st_y_dec,
    st_z_inc,
    st_z_dec,
    lpm_r0, // lpm (r0 <- (Z))
    lpm, // lpm Rd, Z
    lpm_inc, // lpm Rd, Z+
    pop,
    push, // r
    com,
    neg,
    swap,
    inc,
    asr,
    lsr,
    ror,
    dec,
    bset, // r = SREG bit
    bclr,
    ret,
    reti,
    sleep,
    @"break",
    wdr,
    spm,
    ijmp,
    icall,
    jmp, // k = word address (22 bits)
    call,
    adiw, // d in {24,26,28,30}, k = K (0..63)
    sbiw,
    cbi, // d = I/O address (0..31), r = bit
    sbic,
    sbi,
    sbis,
    in, // d, k = I/O address (0..63)
    out, // r, k = I/O address
    rjmp, // k = signed word offset (-2048..2047)
    rcall,
    brbs, // r = SREG bit, k = signed word offset (-64..63)
    brbc,
    bld, // d, r = bit
    bst,
    sbrc,
    sbrs,
};

pub const Insn = struct {
    op: Op,
    d: u8 = 0,
    r: u8 = 0,
    k: i32 = 0,
    /// Words: 2 for lds/sts/jmp/call.
    len: u2 = 1,
};

const invalid: Insn = .{ .op = .invalid };

/// True when `w` starts a two-word instruction (lds, sts, jmp, call). Skip instructions use it.
pub fn isTwoWord(w: u16) bool {
    return (w & 0xFC0F) == 0x9000 or (w & 0xFE0C) == 0x940C;
}

/// Decodes the opcode word `w`; `next` is the following program word (used by two-word instructions).
pub fn decode(w: u16, next: u16) Insn {
    const d5: u8 = @truncate((w >> 4) & 0x1F);
    const r5: u8 = @truncate((w & 0xF) | ((w >> 5) & 0x10));
    const d4: u8 = 16 + @as(u8, @truncate((w >> 4) & 0xF));
    const k8: i32 = ((w >> 4) & 0xF0) | (w & 0xF);
    const two: [4]Op = switch ((w >> 12) & 0xF) {
        0x0 => .{ .invalid, .cpc, .sbc, .add },
        0x1 => .{ .cpse, .cp, .sub, .adc },
        0x2 => .{ .@"and", .eor, .@"or", .mov },
        else => .{ .invalid, .invalid, .invalid, .invalid },
    };
    switch (w >> 12) {
        0x0, 0x1, 0x2 => {
            const sel = (w >> 10) & 3;
            if (w >> 12 == 0 and sel == 0) return decode00(w);
            return .{ .op = two[sel], .d = d5, .r = r5 };
        },
        0x3 => return .{ .op = .cpi, .d = d4, .k = k8 },
        0x4 => return .{ .op = .sbci, .d = d4, .k = k8 },
        0x5 => return .{ .op = .subi, .d = d4, .k = k8 },
        0x6 => return .{ .op = .ori, .d = d4, .k = k8 },
        0x7 => return .{ .op = .andi, .d = d4, .k = k8 },
        0x8, 0xA => {
            // 10q0 qqsd dddd yqqq
            const q: i32 = ((w >> 8) & 0x20) | ((w >> 7) & 0x18) | (w & 7);
            const y = (w >> 3) & 1 != 0;
            if ((w >> 9) & 1 == 0) return .{ .op = if (y) .ldd_y else .ldd_z, .d = d5, .k = q };
            return .{ .op = if (y) .std_y else .std_z, .r = d5, .k = q };
        },
        0x9 => return decode9(w, next, d5, r5),
        0xB => {
            const a: i32 = ((w >> 5) & 0x30) | (w & 0xF);
            if ((w >> 11) & 1 == 0) return .{ .op = .in, .d = d5, .k = a };
            return .{ .op = .out, .r = d5, .k = a };
        },
        0xC => return .{ .op = .rjmp, .k = signExtend(12, w & 0xFFF) },
        0xD => return .{ .op = .rcall, .k = signExtend(12, w & 0xFFF) },
        0xE => return .{ .op = .ldi, .d = d4, .k = k8 },
        0xF => {
            const b: u8 = @truncate(w & 7);
            switch ((w >> 10) & 3) {
                0 => return .{ .op = .brbs, .r = b, .k = signExtend(7, (w >> 3) & 0x7F) },
                1 => return .{ .op = .brbc, .r = b, .k = signExtend(7, (w >> 3) & 0x7F) },
                2 => {
                    if (w & 8 != 0) return invalid;
                    return .{ .op = if ((w >> 9) & 1 == 0) .bld else .bst, .d = d5, .r = b };
                },
                else => {
                    if (w & 8 != 0) return invalid;
                    return .{ .op = if ((w >> 9) & 1 == 0) .sbrc else .sbrs, .d = d5, .r = b };
                },
            }
        },
        else => unreachable,
    }
}

fn decode00(w: u16) Insn {
    switch ((w >> 8) & 3) {
        0 => return if (w == 0) .{ .op = .nop } else invalid,
        1 => return .{ .op = .movw, .d = @truncate(((w >> 4) & 0xF) * 2), .r = @truncate((w & 0xF) * 2) },
        2 => return .{ .op = .muls, .d = 16 + @as(u8, @truncate((w >> 4) & 0xF)), .r = 16 + @as(u8, @truncate(w & 0xF)) },
        else => {
            const d: u8 = 16 + @as(u8, @truncate((w >> 4) & 7));
            const r: u8 = 16 + @as(u8, @truncate(w & 7));
            const ops = [4]Op{ .mulsu, .fmul, .fmuls, .fmulsu };
            return .{ .op = ops[((w >> 6) & 2) | ((w >> 3) & 1)], .d = d, .r = r };
        },
    }
}

fn decode9(w: u16, next: u16, d5: u8, r5: u8) Insn {
    const lo = w & 0xF;
    switch ((w >> 9) & 7) {
        0 => {
            const op: Op = switch (lo) {
                0x0 => return .{ .op = .lds, .d = d5, .k = next, .len = 2 },
                0x1 => .ld_z_inc,
                0x2 => .ld_z_dec,
                0x4 => .lpm,
                0x5 => .lpm_inc,
                0x9 => .ld_y_inc,
                0xA => .ld_y_dec,
                0xC => .ld_x,
                0xD => .ld_x_inc,
                0xE => .ld_x_dec,
                0xF => .pop,
                else => return invalid,
            };
            return .{ .op = op, .d = d5 };
        },
        1 => {
            const op: Op = switch (lo) {
                0x0 => return .{ .op = .sts, .r = d5, .k = next, .len = 2 },
                0x1 => .st_z_inc,
                0x2 => .st_z_dec,
                0x9 => .st_y_inc,
                0xA => .st_y_dec,
                0xC => .st_x,
                0xD => .st_x_inc,
                0xE => .st_x_dec,
                0xF => .push,
                else => return invalid,
            };
            return .{ .op = op, .r = d5 };
        },
        2 => switch (lo) {
            0x0 => return .{ .op = .com, .d = d5 },
            0x1 => return .{ .op = .neg, .d = d5 },
            0x2 => return .{ .op = .swap, .d = d5 },
            0x3 => return .{ .op = .inc, .d = d5 },
            0x5 => return .{ .op = .asr, .d = d5 },
            0x6 => return .{ .op = .lsr, .d = d5 },
            0x7 => return .{ .op = .ror, .d = d5 },
            0xA => return .{ .op = .dec, .d = d5 },
            0x8 => {
                const s: u8 = @truncate((w >> 4) & 7);
                if ((w >> 8) & 1 == 0) return .{ .op = if ((w >> 7) & 1 == 0) .bset else .bclr, .r = s };
                return switch ((w >> 4) & 0xF) {
                    0x0 => .{ .op = .ret },
                    0x1 => .{ .op = .reti },
                    0x8 => .{ .op = .sleep },
                    0x9 => .{ .op = .@"break" },
                    0xA => .{ .op = .wdr },
                    0xC => .{ .op = .lpm_r0 },
                    0xE => .{ .op = .spm },
                    else => invalid,
                };
            },
            0x9 => return if (w == 0x9409) .{ .op = .ijmp } else if (w == 0x9509) .{ .op = .icall } else invalid,
            0xC, 0xD, 0xE, 0xF => {
                const hi: i32 = ((w >> 3) & 0x3E) | (w & 1);
                return .{ .op = if (lo < 0xE) .jmp else .call, .k = hi << 16 | next, .len = 2 };
            },
            else => return invalid,
        },
        3 => {
            const d: u8 = 24 + 2 * @as(u8, @truncate((w >> 4) & 3));
            const k: i32 = ((w >> 2) & 0x30) | (w & 0xF);
            return .{ .op = if ((w >> 8) & 1 == 0) .adiw else .sbiw, .d = d, .k = k };
        },
        4, 5 => {
            const ops = [4]Op{ .cbi, .sbic, .sbi, .sbis };
            return .{ .op = ops[(w >> 8) & 3], .d = @truncate((w >> 3) & 0x1F), .r = @truncate(w & 7) };
        },
        else => return .{ .op = .mul, .d = d5, .r = r5 },
    }
}

fn signExtend(comptime bits: u5, v: u16) i32 {
    const U = @Int(.unsigned, bits);
    const I = @Int(.signed, bits);
    return @as(I, @bitCast(@as(U, @truncate(v))));
}

// ---------------------------------------------------------------------------------------------
const testing = std.testing;

test "decode spot checks (encodings from re/tools/avr-map/code.dis)" {
    try testing.expectEqual(Insn{ .op = .eor, .d = 1, .r = 1 }, decode(0x2411, 0)); // clr r1
    try testing.expectEqual(Insn{ .op = .out, .r = 1, .k = 0x3f }, decode(0xbe1f, 0));
    try testing.expectEqual(Insn{ .op = .ldi, .d = 28, .k = 0xff }, decode(0xefcf, 0));
    try testing.expectEqual(Insn{ .op = .rjmp, .k = 2 }, decode(0xc002, 0));
    try testing.expectEqual(Insn{ .op = .lpm_inc, .d = 0 }, decode(0x9005, 0));
    try testing.expectEqual(Insn{ .op = .st_x_inc, .r = 0 }, decode(0x920d, 0));
    try testing.expectEqual(Insn{ .op = .brbc, .r = 1, .k = -5 }, decode(0xf7d9, 0)); // brne .-10
    try testing.expectEqual(Insn{ .op = .call, .k = 0x74b, .len = 2 }, decode(0x940e, 0x074b));
    try testing.expectEqual(Insn{ .op = .std_z, .r = 22, .k = 0 }, decode(0x8360, 0));
    try testing.expectEqual(Insn{ .op = .sbiw, .d = 30, .k = 3 }, decode(0x9733, 0));
    try testing.expectEqual(Insn{ .op = .lds, .d = 30, .k = 0x25a, .len = 2 }, decode(0x91e0, 0x025a));
    try testing.expectEqual(Insn{ .op = .sbi, .d = 2, .r = 3 }, decode(0x9a13, 0));
    try testing.expectEqual(Insn{ .op = .cpse, .d = 25, .r = 1 }, decode(0x1191, 0));
    try testing.expectEqual(Insn{ .op = .fmulsu, .d = 16, .r = 16 }, decode(0x0388, 0));
    try testing.expectEqual(Op.invalid, decode(0x9008, 0).op); // llvm: ld r0, Y (not in the manual)
    try testing.expectEqual(Op.invalid, decode(0x95d8, 0).op); // elpm: not avr5
    try testing.expectEqual(Op.invalid, decode(0xf808, 0).op); // bld with bit 3 set
    try testing.expect(isTwoWord(0x940e) and isTwoWord(0x91e0) and isTwoWord(0x9200) and !isTwoWord(0x9409));
    for (0..0x10000) |w| {
        const i = decode(@intCast(w), 0x1234);
        try testing.expectEqual(i.len == 2, isTwoWord(@intCast(w)) and i.op != .invalid);
    }
}
