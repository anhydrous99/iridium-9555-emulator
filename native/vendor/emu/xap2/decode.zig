//! XAP2 instruction decoder (bc5-isa.md §1, §8). It mirrors `re/tools/isa/xap.py` field for field and
//! mnemonic for mnemonic, so the parity check can compare the two on every code word:
//! - a word whose low byte is 0 and that is followed by another word is a prefix, 0x0000 included;
//!   at most 2 prefixes; `ext = (ext << 8) + sext8(hi)`, `full = (ext << 8) + sext8(operand)`;
//! - 0x0009 is the `u` modifier (lsr/umult/udiv); the loop accepts it before or between prefixes.
//! `decode` indexes an image's word slice (file-end rules as xap.py on a file); the CPU decodes its
//! 24-bit code space through `decodeAt`, where an unmapped word is a fetch fault.
const std = @import("std");

/// Mnemonics exactly as xap.py spells them (`names`). The upper-case forms are xap.py's FIXED words
/// (operand 0); the lower-case op0 forms are the same instructions with an operand.
pub const Mnem = enum(u8) {
    nop,
    brk,
    sleep,
    sif,
    rts,
    brxl,
    bc,
    st_FLAGS,
    st_UX,
    st_UY,
    ld_FLAGS,
    ld_UX,
    ld_UY,
    st_XH,
    rti,
    ld_XH,
    st_flags,
    st_ux,
    st_uy,
    ld_flags,
    ld_ux,
    ld_uy,
    st_xh,
    ld_xh,
    enter,
    leave,
    op0u,
    ld,
    add,
    addc,
    sub,
    subc,
    nadd,
    cmp,
    @"or",
    @"and",
    xor,
    st,
    bgt,
    bge,
    ble,
    bcz,
    smult,
    umult,
    sdiv,
    udiv,
    tst,
    bsr,
    asl,
    asr,
    lsr,
    rol,
    ror,
    bra,
    blt,
    bpl,
    bmi,
    bne,
    beq,
    bcc,
    bcs,

    /// xap.py's `m` string.
    pub fn name(m: Mnem) []const u8 {
        return switch (m) {
            .st_FLAGS => "st FLAGS",
            .st_UX => "st UX",
            .st_UY => "st UY",
            .ld_FLAGS => "ld FLAGS",
            .ld_UX => "ld UX",
            .ld_UY => "ld UY",
            .st_XH => "st XH",
            .ld_XH => "ld XH",
            .st_flags => "st flags",
            .st_ux => "st ux",
            .st_uy => "st uy",
            .ld_flags => "ld flags",
            .ld_ux => "ld ux",
            .ld_uy => "ld uy",
            .st_xh => "st xh",
            .ld_xh => "ld xh",
            else => @tagName(m),
        };
    }
};

pub const Insn = struct {
    /// Index of the first word (prefixes and `u` included).
    a: u32,
    /// Words in the instruction (xap.py accepts any number of `u` words, so no small bound).
    n: u32,
    /// The consuming word.
    w: u16,
    op: u4,
    reg: u2,
    mode: u2,
    u: bool,
    npfx: u2,
    /// Full operand (prefix bytes sign-extended and accumulated).
    full: i32,
    m: Mnem,

    /// Index of the consuming word (relative branches count from it).
    pub fn cw(i: Insn) u32 {
        return i.a + i.n - 1;
    }
    pub fn nxt(i: Insn) u32 {
        return i.a + i.n;
    }
    pub fn operand(i: Insn) u8 {
        return @truncate(i.w >> 8);
    }
    pub fn full16(i: Insn) u16 {
        return @truncate(@as(u32, @bitCast(i.full)));
    }
};

fn sx8(b: u8) i32 {
    return @as(i8, @bitCast(b));
}

const alu = [16]?Mnem{ null, .ld, null, .add, .addc, .sub, .subc, .nadd, .cmp, null, null, .@"or", .@"and", .xor, null, null };
const br_e = [4]Mnem{ .bra, .blt, .bpl, .bmi };
const br_f = [4]Mnem{ .bne, .beq, .bcc, .bcs };
const br_2 = [4]Mnem{ .bgt, .bge, .ble, .bcz };

fn fixed(w: u16) ?Mnem {
    return switch (w) {
        0x0000 => .nop,
        0x0004 => .brk,
        0x0008 => .sleep,
        0x000C => .sif,
        0x00E2 => .rts,
        0xFE09 => .brxl,
        0xFF09 => .bc,
        0x0001 => .st_FLAGS,
        0x0002 => .st_UX,
        0x0003 => .st_UY,
        0x0005 => .ld_FLAGS,
        0x0006 => .ld_UX,
        0x0007 => .ld_UY,
        0x000A => .st_XH,
        0x000D => .rti,
        0x000E => .ld_XH,
        else => null,
    };
}

fn op0(reg: u2, mode: u2) Mnem {
    return switch (@as(u4, reg) << 2 | mode) {
        0b00_01 => .st_flags,
        0b00_10 => .st_ux,
        0b00_11 => .st_uy,
        0b01_01 => .ld_flags,
        0b01_10 => .ld_ux,
        0b01_11 => .ld_uy,
        0b10_10 => .st_xh,
        0b11_10 => .ld_xh,
        0b10_11 => .enter,
        0b11_11 => .leave,
        else => .op0u,
    };
}

/// Decodes the instruction at word index `start` of `ws` (xap.py `decode(ws, i)` on an image file).
/// A consuming word past the end of `ws` reads as 0, like xap.py.
pub fn decode(ws: []const u16, start: usize) Insn {
    return decodeAt(ws, sliceWord, ws.len, start).?;
}

fn sliceWord(ws: []const u16, i: usize) ?u16 {
    return ws[i];
}

/// xap.py `decode` over a word space of `len` words whose word `i` is `word(ctx, i)`, or null if
/// nothing is mapped there; reading an unmapped word makes the whole decode null (a fetch fault).
/// The CPU decodes its 2^24-word code space this way, so a prefix chain may cross segments.
pub fn decodeAt(ctx: anytype, comptime word: fn (@TypeOf(ctx), usize) ?u16, len: usize, start: usize) ?Insn {
    var i = start;
    var ext: i32 = 0;
    var npfx: u2 = 0;
    var u = false;
    var w: u16 = 0;
    while (i < len) : (i += 1) {
        w = word(ctx, i) orelse return null;
        if (w & 0xFF == 0 and npfx < 2 and i + 1 < len) {
            ext = (ext << 8) + sx8(@truncate(w >> 8));
            npfx += 1;
            continue;
        }
        if (w == 0x0009) {
            u = true;
            continue;
        }
        break;
    } else w = 0;
    const op: u4 = @truncate(w >> 4);
    const reg: u2 = @truncate(w >> 2);
    const mode: u2 = @truncate(w);
    const m: Mnem = if (fixed(w)) |f| f else switch (op) {
        0 => op0(reg, mode),
        2 => if (mode == 0) br_2[reg] else .st,
        9 => ([4]Mnem{ if (u) .umult else .smult, if (u) .udiv else .sdiv, .tst, .bsr })[reg],
        0xA => ([4]Mnem{ .asl, if (u) .lsr else .asr, .rol, .ror })[reg],
        0xE => br_e[reg],
        0xF => br_f[reg],
        else => alu[op].?,
    };
    return .{
        .a = @intCast(start),
        .n = @intCast(i - start + 1),
        .w = w,
        .op = op,
        .reg = reg,
        .mode = mode,
        .u = u,
        .npfx = npfx,
        .full = (ext << 8) + sx8(@truncate(w >> 8)),
        .m = m,
    };
}

pub fn isBranch(m: Mnem) bool {
    return switch (m) {
        .bra, .blt, .bpl, .bmi, .bne, .beq, .bcc, .bcs, .bgt, .bge, .ble, .bcz, .bsr => true,
        else => false,
    };
}

const reg_names = [4][]const u8{ "AH", "AL", "X", "Y" };

/// One line of text in xap.py's `Ins.text()` format (byte addresses = 2 * word index + `byte_base`).
pub fn format(i: Insn, w: *std.Io.Writer) std.Io.Writer.Error!void {
    const v = i.full16();
    if (isBranch(i.m)) {
        if (i.mode == 0) return w.print("{s} 0x{x}", .{ i.m.name(), 2 * @as(i64, i.cw()) + 2 * @as(i64, i.full) });
        try w.print("{s} ", .{i.m.name()});
        return src(i, w);
    }
    switch (i.m) {
        .enter, .leave => return w.print("{s} {d}", .{ i.m.name(), i.full }),
        .st_flags, .st_ux, .st_uy, .ld_flags, .ld_ux, .ld_uy, .st_xh, .ld_xh => return w.print("{s}, @({d},Y)", .{ i.m.name(), @as(i16, @bitCast(v)) }),
        .op0u => return w.print("op0u r{d} m{d} 0x{x}", .{ i.reg, i.mode, v }),
        .ld, .add, .addc, .sub, .subc, .nadd, .cmp, .@"or", .@"and", .xor, .st => {
            try w.print("{s} {s},", .{ i.m.name(), reg_names[i.reg] });
            return src(i, w);
        },
        .smult, .umult, .sdiv, .udiv, .tst, .asl, .asr, .lsr, .rol, .ror => {
            try w.print("{s} ", .{i.m.name()});
            return src(i, w);
        },
        else => return w.writeAll(i.m.name()),
    }
}

fn src(i: Insn, w: *std.Io.Writer) std.Io.Writer.Error!void {
    const v = i.full16();
    return switch (i.mode) {
        0 => w.print("#0x{x}", .{v}),
        1 => w.print("@0x{x}", .{v}),
        2 => w.print("@(0x{x},X)", .{v}),
        3 => w.print("@(0x{x},Y)", .{v}),
    };
}

// ---------------------------------------------------------------------------------------------
const testing = std.testing;

fn text(ws: []const u16, i: usize, buf: []u8) []const u8 {
    var w: std.Io.Writer = .fixed(buf);
    format(decode(ws, i), &w) catch unreachable;
    return w.buffered();
}

test "prefix folding: per-byte sign extension, 0x0000 as a prefix, at most two prefixes" {
    var buf: [64]u8 = undefined;
    // fd00 bd18 = ld X,#0xFCBD (reset UY); f900 6018 = ld X,#0xF960 (bc5-isa §1)
    try testing.expectEqualStrings("ld X,#0xfcbd", text(&.{ 0xfd00, 0xbd18 }, 0, &buf));
    try testing.expectEqualStrings("ld X,#0xf960", text(&.{ 0xf900, 0x6018 }, 0, &buf));
    // ff00 b90b = enter -327
    try testing.expectEqualStrings("enter -327", text(&.{ 0xff00, 0xb90b }, 0, &buf));
    // 0x8CE4C: 0200 d000 d79c = bsr 0xc6dfe (zero-as-prefix in the middle; NOTES §1.8)
    var ws: [0x46729]u16 = @splat(0);
    ws[0x46726] = 0x0200;
    ws[0x46727] = 0xd000;
    ws[0x46728] = 0xd79c;
    const ins = decode(&ws, 0x46726);
    try testing.expectEqual(@as(u32, 3), ins.n);
    try testing.expectEqual(Mnem.bsr, ins.m);
    try testing.expectEqual(@as(i64, 0xc6dfe), 2 * (@as(i64, ins.cw()) + ins.full));
    // three zero words: two prefixes then a standalone 0x0000 (nop), length 3
    const z = decode(&.{ 0, 0, 0, 0x00e2 }, 0);
    try testing.expectEqual(Mnem.nop, z.m);
    try testing.expectEqual(@as(u32, 3), z.n);
    // the last word of the slice is never a prefix
    try testing.expectEqual(Mnem.op0u, decode(&.{0x1200}, 0).m);
    // in a code space, a prefix or `u` before an unmapped word is a fetch fault
    const Half = struct {
        fn word(img: []const u16, i: usize) ?u16 {
            return if (i < img.len) img[i] else null;
        }
    };
    try testing.expectEqual(@as(?Insn, null), decodeAt(@as([]const u16, &.{0x1200}), Half.word, 1 << 24, 0));
    try testing.expectEqual(@as(?Insn, null), decodeAt(@as([]const u16, &.{0x0009}), Half.word, 1 << 24, 0));
}

test "u modifier selects lsr/umult/udiv; FIXED words; op0 Y-offset forms" {
    var buf: [64]u8 = undefined;
    try testing.expectEqualStrings("lsr #0xa", text(&.{ 0x0009, 0x0aa4 }, 0, &buf));
    try testing.expectEqualStrings("asr #0xa", text(&.{0x0aa4}, 0, &buf));
    try testing.expectEqualStrings("udiv @0xfff3", text(&.{ 0x0009, 0xf395 }, 0, &buf));
    try testing.expectEqualStrings("rts", text(&.{0x00e2}, 0, &buf));
    try testing.expectEqualStrings("bc", text(&.{0xff09}, 0, &buf));
    try testing.expectEqualStrings("brxl", text(&.{0xfe09}, 0, &buf));
    try testing.expectEqualStrings("op0u r2 m1 0xfffd", text(&.{0xfd09}, 0, &buf)); // FD09 block copy
    try testing.expectEqualStrings("op0u r3 m1 0xffdf", text(&.{0xdf0d}, 0, &buf)); // rti @(-33,Y)
    try testing.expectEqualStrings("st flags, @(-1,Y)", text(&.{0xff01}, 0, &buf));
    try testing.expectEqualStrings("ld xh, @(-1,Y)", text(&.{0xff0e}, 0, &buf));
    try testing.expectEqualStrings("leave -2", text(&.{0xfe0f}, 0, &buf));
    try testing.expectEqualStrings("st X,@(0xffff,Y)", text(&.{0xff2b}, 0, &buf));
    try testing.expectEqualStrings("bcz 0x0", text(&.{0x002c}, 0, &buf)); // op 2, mode 0: branch group
    try testing.expectEqualStrings("st X,@0xfffe", text(&.{0xfe29}, 0, &buf));
    // a run of 299 `u` words is one instruction, like xap.py (was a u8 overflow panic)
    var us: [300]u16 = @splat(0x0009);
    us[299] = 0x0aa4;
    const long = decode(&us, 0);
    try testing.expectEqual(@as(u32, 300), long.n);
    try testing.expectEqual(Mnem.lsr, long.m);
}
