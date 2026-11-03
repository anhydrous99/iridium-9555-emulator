//! SPARC V8 disassembly in llvm-objdump --triple=sparc syntax (llvm 21), so the decoder can be held
//! to the reference listing word for word (ARCHITECTURE §6.2 decoder parity). Compare with
//! whitespace collapsed: llvm separates alias mnemonics by a tab and others by a space.
//! The aliases follow llvm's SparcInstrAliases/printMemOperand: `mov` (or %g0,x,rd), `cmp`
//! (subcc rd=%g0), `tst` (orcc rs1,%g0,%g0), `ret`/`retl`/`jmp`/`call` (jmpl), `nop`, bare
//! `save`/`restore`. Words llvm rejects print as `<unknown>` only where the decoder also rejects them.
const std = @import("std");
const decode = @import("decode.zig");
const Insn = decode.Insn;
const Op = decode.Op;

const W = std.Io.Writer;

const reg_names = [32][]const u8{
    "%g0", "%g1", "%g2", "%g3", "%g4", "%g5", "%g6", "%g7",
    "%o0", "%o1", "%o2", "%o3", "%o4", "%o5", "%sp", "%o7",
    "%l0", "%l1", "%l2", "%l3", "%l4", "%l5", "%l6", "%l7",
    "%i0", "%i1", "%i2", "%i3", "%i4", "%i5", "%fp", "%i7",
};
const bcc = [16][]const u8{ "bn", "be", "ble", "bl", "bleu", "bcs", "bneg", "bvs", "ba", "bne", "bg", "bge", "bgu", "bcc", "bpos", "bvc" };
const tcc = [16][]const u8{ "tn", "te", "tle", "tl", "tleu", "tcs", "tneg", "tvs", "ta", "tne", "tg", "tge", "tgu", "tcc", "tpos", "tvc" };
const fbcc = [16][]const u8{ "fbn", "fbne", "fblg", "fbul", "fbl", "fbug", "fbg", "fbu", "fba", "fbe", "fbue", "fbge", "fbuge", "fble", "fbule", "fbo" };
const cbcc = [16][]const u8{ "cbn", "cb123", "cb12", "cb13", "cb1", "cb23", "cb2", "cb3", "cba", "cb0", "cb03", "cb02", "cb023", "cb01", "cb013", "cb012" };

fn r(n: u5) []const u8 {
    return reg_names[n];
}

/// llvm names an `ldd`/`std` register pair by its first register's raw name (%o6, %i6).
fn pair(n: u5) []const u8 {
    return switch (n) {
        14 => "%o6",
        30 => "%i6",
        else => reg_names[n],
    };
}

fn hex(w: *W, v: i64) W.Error!void {
    if (v < 0) try w.print("-0x{x}", .{@as(u64, @intCast(-v))}) else try w.print("0x{x}", .{@as(u64, @intCast(v))});
}

/// Second ALU operand: `%rs2` or the signed immediate.
fn op2(w: *W, i: Insn) W.Error!void {
    if (i.imm()) try hex(w, i.simm13()) else try w.writeAll(r(i.rs2()));
}

/// llvm printMemOperand: rs1 unless %g0, then `+op2` unless it adds nothing.
fn memOp(w: *W, i: Insn) W.Error!void {
    const first = i.rs1() != 0;
    if (first) try w.writeAll(r(i.rs1()));
    const nothing = if (i.imm()) i.simm13() == 0 else i.rs2() == 0;
    if (first and nothing) return;
    if (first) try w.writeAll("+");
    try op2(w, i);
}

/// Formats one instruction at `pc` (branch and call targets are absolute).
pub fn format(w: *W, raw: u32, pc: u32) W.Error!void {
    const i = decode.decode(raw);
    switch (i.op) {
        .illegal => try w.writeAll("<unknown>"),
        .call => try w.print("call 0x{x}", .{pc +% i.disp30()}),
        .bicc, .fbfcc, .cbccc => {
            const names = switch (i.op) {
                .bicc => &bcc,
                .fbfcc => &fbcc,
                else => &cbcc,
            };
            try w.print("{s}{s}\t0x{x}", .{ names[i.cond()], if (i.annul()) ",a" else "", pc +% @as(u32, @bitCast(i.disp22())) });
        },
        .sethi => if (i.rd() == 0 and i.imm22() == 0) try w.writeAll("nop") else try w.print("sethi 0x{x}, {s}", .{ i.imm22(), r(i.rd()) }),
        .unimp => try w.print("unimp 0x{x}", .{i.imm22()}),
        .@"or" => if (i.rs1() == 0) {
            try w.writeAll("mov\t");
            try op2(w, i);
            try w.print(", {s}", .{r(i.rd())});
        } else try alu(w, i),
        .subcc => if (i.rd() == 0) {
            try w.print("cmp\t{s}, ", .{r(i.rs1())});
            try op2(w, i);
        } else try alu(w, i),
        .orcc => if (i.rd() == 0 and !i.imm() and i.rs2() == 0) try w.print("tst\t{s}", .{r(i.rs1())}) else try alu(w, i),
        .save, .restore => if (!i.imm() and i.rd() == 0 and i.rs1() == 0 and i.rs2() == 0) try w.writeAll(@tagName(i.op)) else try alu(w, i),
        .jmpl => {
            const ret_like = i.rd() == 0 and i.imm() and i.simm13() == 8;
            if (ret_like and i.rs1() == 31) return w.writeAll("ret");
            if (ret_like and i.rs1() == 15) return w.writeAll("retl");
            switch (i.rd()) {
                0 => try w.writeAll("jmp "),
                15 => try w.writeAll("call "),
                else => try w.writeAll("jmpl "),
            }
            try memOp(w, i);
            if (i.rd() != 0 and i.rd() != 15) try w.print(", {s}", .{r(i.rd())});
        },
        .rett, .flush => {
            try w.print("{s} ", .{@tagName(i.op)});
            try memOp(w, i);
        },
        .ticc => {
            try w.print("{s}\t", .{tcc[i.cond()]});
            if (i.rs1() != 0) {
                try w.print("{s} + ", .{r(i.rs1())});
            }
            if (i.imm()) try w.print("{d}", .{i.raw & 0x7F}) else try w.writeAll(r(i.rs2()));
        },
        .rdasr => if (i.rs1() == 0)
            try w.print("rd %y, {s}", .{r(i.rd())})
        else if (i.rs1() == 15 and i.rd() == 0)
            try w.writeAll("stbar")
        else
            try w.print("rd %asr{d}, {s}", .{ i.rs1(), r(i.rd()) }),
        .rdpsr, .rdwim, .rdtbr => try w.print("rd %{s}, {s}", .{ @tagName(i.op)[2..], r(i.rd()) }),
        .wrasr, .wrpsr, .wrwim, .wrtbr => {
            try w.print("wr {s}, ", .{r(i.rs1())});
            try op2(w, i);
            if (i.op != .wrasr) {
                try w.print(", %{s}", .{@tagName(i.op)[2..]});
            } else if (i.rd() == 0) try w.writeAll(", %y") else try w.print(", %asr{d}", .{i.rd()});
        },
        .fpop1, .fpop2, .cpop1, .cpop2 => try w.print("{s} 0x{x}", .{ @tagName(i.op), raw }),
        .ld, .ldub, .lduh, .ldd, .ldsb, .ldsh, .ldstub, .swap, .ldf, .ldfsr, .lddf, .ldc, .ldcsr, .lddc => {
            try w.print("{s} [", .{@tagName(i.op)});
            try memOp(w, i);
            try w.print("], {s}", .{if (i.op == .ldd) pair(i.rd()) else r(i.rd())});
        },
        .st, .stb, .sth, .std, .stf, .stfsr, .stdfq, .stdf, .stc, .stcsr, .stdcq, .stdc => {
            try w.print("{s} {s}, [", .{ @tagName(i.op), if (i.op == .std) pair(i.rd()) else r(i.rd()) });
            try memOp(w, i);
            try w.writeAll("]");
        },
        .lda, .lduba, .lduha, .ldda, .ldsba, .ldsha, .ldstuba, .swapa => {
            try w.print("{s} [", .{@tagName(i.op)});
            try memOp(w, i);
            try w.print("] {d}, {s}", .{ i.asi(), r(i.rd()) });
        },
        .sta, .stba, .stha, .stda => {
            try w.print("{s} {s}, [", .{ @tagName(i.op), r(i.rd()) });
            try memOp(w, i);
            try w.print("] {d}", .{i.asi()});
        },
        else => try alu(w, i),
    }
}

fn alu(w: *W, i: Insn) W.Error!void {
    try w.print("{s} {s}, ", .{ @tagName(i.op), r(i.rs1()) });
    try op2(w, i);
    try w.print(", {s}", .{r(i.rd())});
}

/// Whitespace-collapsed equality, the parity rule.
pub fn sameText(a: []const u8, b: []const u8) bool {
    var x = std.mem.tokenizeAny(u8, a, " \t");
    var y = std.mem.tokenizeAny(u8, b, " \t");
    while (true) {
        const p = x.next();
        const q = y.next();
        if (p == null or q == null) return p == null and q == null;
        if (!std.mem.eql(u8, p.?, q.?)) return false;
    }
}

test "llvm syntax on listing samples" {
    // (word, pc, llvm-objdump 21 text) taken from the P1/P2 listings and an encoding probe
    const cases = [_]struct { u32, u32, []const u8 }{
        .{ 0x821020e0, 0x10000, "mov\t0xe0, %g1" },
        .{ 0x81884000, 0x10004, "wr %g1, %g0, %psr" },
        .{ 0x031c0004, 0x10008, "sethi 0x1c0004, %g1" },
        .{ 0xc2a00040, 0x10024, "sta %g1, [%g0] 2" },
        .{ 0x80a16003, 0x1004c, "cmp\t%g5, 0x3" },
        .{ 0x12800008, 0x10050, "bne\t0x10070" },
        .{ 0x01000000, 0x10054, "nop" },
        .{ 0x8b444000, 0x10068, "rd %asr17, %g5" },
        .{ 0x10800008, 0x1006c, "ba 0x1008c" },
        .{ 0x81e00000, 0x10100, "save" },
        .{ 0x91d02000, 0x1013c, "ta\t0" },
        .{ 0x5c01d7de, 0x10144, "call 0x700860bc" },
        .{ 0x81c44000, 0x10238, "jmp %l1" },
        .{ 0x81cc8000, 0x1023c, "rett %l2" },
        .{ 0x9de3bfa0, 0x10254, "save %sp, -0x60, %sp" },
        .{ 0x99580000, 0x102e0, "rd %tbr, %o4" },
        .{ 0xc24fbf82, 0x1e308, "ldsb [%fp+-0x7e], %g1" },
        .{ 0x9fc04000, 0x11ddc, "call %g1" },
        .{ 0x81c7e00c, 0x775cc, "jmp %i7+0xc" },
        .{ 0xadc52140, 0x70085c6c, "jmpl %l4+0x140, %l6" },
        .{ 0xd0820040, 0x110c4, "lda [%o0] 2, %o0" },
        .{ 0xd2b20380, 0x11240, "stha %o1, [%o0] 28" },
        .{ 0xc2202000, 0x9f870, "st %g1, [0x0]" },
        .{ 0x30800021, 0x114bc, "ba,a\t0x11540" },
        .{ 0x14bffff7, 0x11434, "bg\t0x11410" },
        .{ 0x80924000, 0xbc00c, "tst\t%o1" },
        .{ 0x80900009, 0x1000, "orcc %g0, %o1, %g0" },
        .{ 0x99e83fff, 0x11f0c, "restore %g0, -0x1, %o4" },
        .{ 0x81c7e008, 0x11604, "ret" },
        .{ 0x81c3e008, 0x1108c, "retl" },
        .{ 0x00000008, 0x583f8, "unimp 0x8" },
        .{ 0x91d06003, 0x1024, "ta\t%g1 + 3" },
        .{ 0x83d00005, 0x1030, "te\t%g5" },
        .{ 0x81d84002, 0x1064, "flush %g1+%g2" },
        .{ 0x81c82004, 0x1068, "rett 0x4" },
        .{ 0xa7800000, 0x70048fe0, "wr %g0, %g0, %asr19" },
        .{ 0x82580000 | 0xb000 | (2 << 14), 0x1080, "smul %g2, -0x1000, %g1" },
        .{ 0x8248a005, 0x1084, "<unknown>" },
        .{ 0x0080_0004, 0x107c, "bn\t0x108c" },
        .{ 0xfc3d60b0, 0x70085d74, "std %i6, [%l5+0xb0]" },
        .{ 0xfc1ba038, 0x700861c4, "ldd [%sp+0x38], %i6" },
    };
    var buf: [128]u8 = undefined;
    for (cases) |c| {
        var w: W = .fixed(&buf);
        try format(&w, c[0], c[1]);
        if (!sameText(w.buffered(), c[2])) {
            std.debug.print("0x{x:0>8}: got '{s}' want '{s}'\n", .{ c[0], w.buffered(), c[2] });
            return error.TestUnexpectedResult;
        }
    }
}
