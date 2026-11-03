//! SPARC V8 / LEON instruction decoder (ARCHITECTURE §6.2). An `Insn` is the raw word plus its
//! operation; operand fields are read from the word on demand. The decoder is lenient about
//! must-be-zero fields (the executor ignores them, as LEON does); `dis.zig` prints what
//! llvm-objdump --triple=sparc prints, and the parity check holds both to the same words.
const std = @import("std");

pub const Op = enum(u8) {
    // formats 1 and 2
    call,
    bicc,
    sethi,
    unimp,
    fbfcc,
    cbccc,
    // format 3, op = 2
    add,
    @"and",
    @"or",
    xor,
    sub,
    andn,
    orn,
    xnor,
    addx,
    umul,
    smul,
    subx,
    udiv,
    sdiv,
    addcc,
    andcc,
    orcc,
    xorcc,
    subcc,
    andncc,
    orncc,
    xnorcc,
    addxcc,
    umulcc,
    smulcc,
    subxcc,
    udivcc,
    sdivcc,
    taddcc,
    tsubcc,
    taddcctv,
    tsubcctv,
    mulscc,
    sll,
    srl,
    sra,
    rdasr,
    rdpsr,
    rdwim,
    rdtbr,
    wrasr,
    wrpsr,
    wrwim,
    wrtbr,
    fpop1,
    fpop2,
    cpop1,
    cpop2,
    jmpl,
    rett,
    ticc,
    flush,
    save,
    restore,
    // format 3, op = 3
    ld,
    ldub,
    lduh,
    ldd,
    st,
    stb,
    sth,
    std,
    ldsb,
    ldsh,
    ldstub,
    swap,
    lda,
    lduba,
    lduha,
    ldda,
    sta,
    stba,
    stha,
    stda,
    ldsba,
    ldsha,
    ldstuba,
    swapa,
    ldf,
    ldfsr,
    lddf,
    stf,
    stfsr,
    stdfq,
    stdf,
    ldc,
    ldcsr,
    lddc,
    stc,
    stcsr,
    stdcq,
    stdc,
    /// Not a V8 instruction (op2 1/3/5, unassigned op3): illegal_instruction.
    illegal,
};

const X = Op.illegal;

/// op = 2, indexed by op3.
const arith = [64]Op{
    .add,    .@"and", .@"or",    .xor,      .sub,    .andn,    .orn,    .xnor,
    .addx,   X,       .umul,     .smul,     .subx,   X,        .udiv,   .sdiv,
    .addcc,  .andcc,  .orcc,     .xorcc,    .subcc,  .andncc,  .orncc,  .xnorcc,
    .addxcc, X,       .umulcc,   .smulcc,   .subxcc, X,        .udivcc, .sdivcc,
    .taddcc, .tsubcc, .taddcctv, .tsubcctv, .mulscc, .sll,     .srl,    .sra,
    .rdasr,  .rdpsr,  .rdwim,    .rdtbr,    X,       X,        X,       X,
    .wrasr,  .wrpsr,  .wrwim,    .wrtbr,    .fpop1,  .fpop2,   .cpop1,  .cpop2,
    .jmpl,   .rett,   .ticc,     .flush,    .save,   .restore, X,       X,
};

/// op = 3, indexed by op3.
const mem = [64]Op{
    .ld,  .ldub,  .lduh,  .ldd,  .st,  .stb,     .sth,   .std,
    X,    .ldsb,  .ldsh,  X,     X,    .ldstub,  X,      .swap,
    .lda, .lduba, .lduha, .ldda, .sta, .stba,    .stha,  .stda,
    X,    .ldsba, .ldsha, X,     X,    .ldstuba, X,      .swapa,
    .ldf, .ldfsr, X,      .lddf, .stf, .stfsr,   .stdfq, .stdf,
    X,    X,      X,      X,     X,    X,        X,      X,
    .ldc, .ldcsr, X,      .lddc, .stc, .stcsr,   .stdcq, .stdc,
    X,    X,      X,      X,     X,    X,        X,      X,
};

pub const Insn = struct {
    op: Op,
    raw: u32,

    pub fn rd(i: Insn) u5 {
        return @truncate(i.raw >> 25);
    }
    pub fn rs1(i: Insn) u5 {
        return @truncate(i.raw >> 14);
    }
    pub fn rs2(i: Insn) u5 {
        return @truncate(i.raw);
    }
    /// i bit: the second operand is `simm13` instead of `rs2`.
    pub fn imm(i: Insn) bool {
        return i.raw & 0x2000 != 0;
    }
    pub fn simm13(i: Insn) i32 {
        return @as(i13, @bitCast(@as(u13, @truncate(i.raw))));
    }
    pub fn asi(i: Insn) u8 {
        return @truncate(i.raw >> 5);
    }
    /// Bicc/Ticc condition (bits 28:25).
    pub fn cond(i: Insn) u4 {
        return @truncate(i.raw >> 25);
    }
    pub fn annul(i: Insn) bool {
        return i.raw & 0x2000_0000 != 0;
    }
    pub fn imm22(i: Insn) u22 {
        return @truncate(i.raw);
    }
    /// Byte displacement of a Bicc (sign-extended disp22 × 4).
    pub fn disp22(i: Insn) i32 {
        return @as(i32, @as(i22, @bitCast(@as(u22, @truncate(i.raw))))) * 4;
    }
    /// Byte displacement of a call (disp30 × 4, wraps at 32 bits).
    pub fn disp30(i: Insn) u32 {
        return i.raw << 2;
    }
    pub fn op3(i: Insn) u6 {
        return @truncate(i.raw >> 19);
    }
};

pub fn decode(raw: u32) Insn {
    const op: Op = switch (raw >> 30) {
        1 => .call,
        0 => switch (@as(u3, @truncate(raw >> 22))) {
            0 => .unimp,
            2 => .bicc,
            4 => .sethi,
            6 => .fbfcc,
            7 => .cbccc,
            else => .illegal,
        },
        2 => arith[@as(u6, @truncate(raw >> 19))],
        else => mem[@as(u6, @truncate(raw >> 19))],
    };
    return .{ .op = op, .raw = raw };
}

test "decode fields" {
    const t = std.testing;
    const save = decode(0x9de3bfa0); // save %sp, -0x60, %sp
    try t.expectEqual(Op.save, save.op);
    try t.expectEqual(@as(u5, 14), save.rd());
    try t.expectEqual(@as(u5, 14), save.rs1());
    try t.expect(save.imm());
    try t.expectEqual(@as(i32, -0x60), save.simm13());
    const bg = decode(0x14bffff7); // bg 0x11410 at 0x11434
    try t.expectEqual(Op.bicc, bg.op);
    try t.expectEqual(@as(u4, 10), bg.cond());
    try t.expectEqual(@as(i32, -36), bg.disp22());
    const call = decode(0x5c01d7de); // call 0x700860bc at 0x10144
    try t.expectEqual(@as(u32, 0x700860bc), 0x10144 +% call.disp30());
    try t.expectEqual(Op.stha, decode(0xd2b20380).op);
    try t.expectEqual(@as(u8, 28), decode(0xd2b20380).asi());
    try t.expectEqual(Op.illegal, decode(0x00400000).op); // op2 = 1 (V9 BPcc)
    try t.expectEqual(Op.unimp, decode(0x00000008).op);
}
