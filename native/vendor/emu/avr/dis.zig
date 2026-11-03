//! Disassembly in llvm-objdump 21 syntax (`--triple=avr --mcpu=atmega164p`): the text after the
//! encoding bytes, `mnemonic\toperands`. Used for decoder parity (ARCHITECTURE §6.1) and reports.
const std = @import("std");
const dec = @import("decode.zig");

const sreg_set = [8][]const u8{ "sec", "sez", "sen", "sev", "ses", "seh", "set", "sei" };
const sreg_clr = [8][]const u8{ "clc", "clz", "cln", "clv", "cls", "clh", "clt", "cli" };
const br_set = [8][]const u8{ "brlo", "breq", "brmi", "brvs", "brlt", "brhs", "brts", "brie" };
const br_clr = [8][]const u8{ "brsh", "brne", "brpl", "brvc", "brge", "brhc", "brtc", "brid" };

/// Writes one instruction. `<unknown>` for invalid words, as llvm-objdump prints them.
pub fn format(w: *std.Io.Writer, i: dec.Insn) std.Io.Writer.Error!void {
    const k: u32 = @bitCast(i.k);
    switch (i.op) {
        .invalid => try w.writeAll("<unknown>"),
        .nop, .ret, .reti, .sleep, .@"break", .wdr, .spm, .ijmp, .icall => try w.writeAll(@tagName(i.op)),
        .lpm_r0 => try w.writeAll("lpm"),
        .elpm_r0 => try w.writeAll("elpm"),
        .add, .adc, .@"and", .eor => {
            const alias: ?[]const u8 = if (i.d != i.r) null else switch (i.op) {
                .add => "lsl",
                .adc => "rol",
                .@"and" => "tst",
                else => "clr",
            };
            if (alias) |a| try w.print("{s}\tr{d}", .{ a, i.d }) else try w.print("{s}\tr{d}, r{d}", .{ @tagName(i.op), i.d, i.r });
        },
        .movw, .muls, .mulsu, .fmul, .fmuls, .fmulsu, .cpc, .sbc, .cpse, .cp, .sub, .@"or", .mov, .mul => try w.print("{s}\tr{d}, r{d}", .{ @tagName(i.op), i.d, i.r }),
        .cpi, .sbci, .subi, .ori, .andi, .ldi, .adiw, .sbiw => try w.print("{s}\tr{d}, 0x{x}", .{ @tagName(i.op), i.d, k }),
        .ldd_y, .ldd_z => try w.print("ldd\tr{d}, {c}+{d}", .{ i.d, ptrName(i.op), k }),
        .std_y, .std_z => try w.print("std\t{c}+{d}, r{d}", .{ ptrName(i.op), k, i.r }),
        .lds => try w.print("lds\tr{d}, 0x{x}", .{ i.d, k }),
        .sts => try w.print("sts\t0x{x}, r{d}", .{ k, i.r }),
        .ld_x, .ld_x_inc, .ld_x_dec, .ld_y_inc, .ld_y_dec, .ld_z_inc, .ld_z_dec => try w.print("ld\tr{d}, {s}", .{ i.d, ptrMode(i.op) }),
        .st_x, .st_x_inc, .st_x_dec, .st_y_inc, .st_y_dec, .st_z_inc, .st_z_dec => try w.print("st\t{s}, r{d}", .{ ptrMode(i.op), i.r }),
        .lpm => try w.print("lpm\tr{d}, Z", .{i.d}),
        .lpm_inc => try w.print("lpm\tr{d}, Z+", .{i.d}),
        .elpm => try w.print("elpm\tr{d}, Z", .{i.d}),
        .elpm_inc => try w.print("elpm\tr{d}, Z+", .{i.d}),
        .pop, .com, .neg, .swap, .inc, .asr, .lsr, .ror, .dec => try w.print("{s}\tr{d}", .{ @tagName(i.op), i.d }),
        .push => try w.print("push\tr{d}", .{i.r}),
        .bset => try w.writeAll(sreg_set[i.r]),
        .bclr => try w.writeAll(sreg_clr[i.r]),
        .jmp, .call => try w.print("{s}\t0x{x}", .{ @tagName(i.op), k * 2 }),
        .cbi, .sbic, .sbi, .sbis => try w.print("{s}\t0x{x}, 0x{x}", .{ @tagName(i.op), i.d, i.r }),
        .in => try w.print("in\tr{d}, 0x{x}", .{ i.d, k }),
        .out => try w.print("out\t0x{x}, r{d}", .{ k, i.r }),
        .rjmp, .rcall => {
            try w.print("{s}\t", .{@tagName(i.op)});
            try offset(w, i.k);
        },
        .brbs, .brbc => {
            try w.print("{s}\t", .{if (i.op == .brbs) br_set[i.r] else br_clr[i.r]});
            try offset(w, i.k);
        },
        .bld, .bst, .sbrc, .sbrs => try w.print("{s}\tr{d}, 0x{x}", .{ @tagName(i.op), i.d, i.r }),
    }
}

/// `.+N` / `.-N`: byte offset relative to the next instruction.
fn offset(w: *std.Io.Writer, k: i32) std.Io.Writer.Error!void {
    if (k < 0) try w.print(".-{d}", .{-k * 2}) else try w.print(".+{d}", .{k * 2});
}

fn ptrName(op: dec.Op) u8 {
    return if (op == .ldd_y or op == .std_y) 'Y' else 'Z';
}

fn ptrMode(op: dec.Op) []const u8 {
    return switch (op) {
        .ld_x, .st_x => "X",
        .ld_x_inc, .st_x_inc => "X+",
        .ld_x_dec, .st_x_dec => "-X",
        .ld_y_inc, .st_y_inc => "Y+",
        .ld_y_dec, .st_y_dec => "-Y",
        .ld_z_inc, .st_z_inc => "Z+",
        .ld_z_dec, .st_z_dec => "-Z",
        else => unreachable,
    };
}

/// Formats into `buf` and returns the text.
pub fn text(buf: []u8, i: dec.Insn) []const u8 {
    var w: std.Io.Writer = .fixed(buf);
    format(&w, i) catch return w.buffered();
    return w.buffered();
}

/// One line of an llvm-objdump listing: the instruction's byte address and its text after the bytes.
pub const ListingLine = struct { addr: u32, text: []const u8 };

/// Parses `   132: 11 24        \tclr\tr1` (llvm-objdump -d). Null for headers and blank lines.
pub fn parseListingLine(line: []const u8) ?ListingLine {
    const colon = std.mem.indexOfScalar(u8, line, ':') orelse return null;
    const addr_txt = std.mem.trim(u8, line[0..colon], " ");
    const addr = std.fmt.parseInt(u32, addr_txt, 16) catch return null;
    const tab = std.mem.indexOfScalarPos(u8, line, colon, '\t') orelse return null;
    return .{ .addr = addr, .text = std.mem.trimEnd(u8, line[tab + 1 ..], " \r") };
}

/// Parity of `decode` + `format` against an llvm-objdump listing of `image` (byte addresses).
pub const Parity = struct {
    words: u32 = 0,
    insns: u32 = 0,
    mismatches: u32 = 0,
    first_bad: ?u32 = null,
};

pub fn listingParity(image: []const u8, listing: []const u8, report: ?*std.Io.Writer) Parity {
    var p: Parity = .{};
    var lines = std.mem.splitScalar(u8, listing, '\n');
    var buf: [64]u8 = undefined;
    while (lines.next()) |line| {
        const l = parseListingLine(line) orelse continue;
        if (l.addr + 1 >= image.len) continue;
        const w0 = std.mem.readInt(u16, image[l.addr..][0..2], .little);
        const w1 = if (l.addr + 3 < image.len) std.mem.readInt(u16, image[l.addr + 2 ..][0..2], .little) else 0;
        const i = dec.decode(w0, w1);
        const got = text(&buf, i);
        p.insns += 1;
        p.words += if (i.op == .invalid) 1 else i.len;
        if (!std.mem.eql(u8, got, l.text)) {
            p.mismatches += 1;
            if (p.first_bad == null) p.first_bad = l.addr;
            if (report) |r| r.print("0x{x}: ours '{s}' llvm '{s}'\n", .{ l.addr, got, l.text }) catch {};
        }
    }
    return p;
}

// ---------------------------------------------------------------------------------------------
const testing = std.testing;

test "format: llvm-objdump spellings" {
    var buf: [64]u8 = undefined;
    const cases = [_]struct { w: u16, n: u16 = 0, s: []const u8 }{
        .{ .w = 0x2411, .s = "clr\tr1" },
        .{ .w = 0xbe1f, .s = "out\t0x3f, r1" },
        .{ .w = 0xefcf, .s = "ldi\tr28, 0xff" },
        .{ .w = 0xc002, .s = "rjmp\t.+4" },
        .{ .w = 0x9005, .s = "lpm\tr0, Z+" },
        .{ .w = 0x920d, .s = "st\tX+, r0" },
        .{ .w = 0xf7d9, .s = "brne\t.-10" },
        .{ .w = 0x940e, .n = 0x074b, .s = "call\t0xe96" },
        .{ .w = 0x8360, .s = "std\tZ+0, r22" },
        .{ .w = 0x8d8a, .s = "ldd\tr24, Y+26" },
        .{ .w = 0x9733, .s = "sbiw\tr30, 0x3" },
        .{ .w = 0x91e0, .n = 0x025a, .s = "lds\tr30, 0x25a" },
        .{ .w = 0x9a13, .s = "sbi\t0x2, 0x3" },
        .{ .w = 0x95c8, .s = "lpm" },
        .{ .w = 0x94f8, .s = "cli" },
        .{ .w = 0xf001, .s = "breq\t.+0" },
        .{ .w = 0xcfff, .s = "rjmp\t.-2" },
        .{ .w = 0x0c00, .s = "lsl\tr0" },
        .{ .w = 0x9008, .s = "<unknown>" },
    };
    for (cases) |c| try testing.expectEqualStrings(c.s, text(&buf, dec.decode(c.w, c.n)));
}

test "parseListingLine" {
    const l = parseListingLine("     164: 0e 94 4b 07  \tcall\t0xe96").?;
    try testing.expectEqual(@as(u32, 0x164), l.addr);
    try testing.expectEqualStrings("call\t0xe96", l.text);
    try testing.expectEqual(@as(?ListingLine, null), parseListingLine("avr.elf:\tfile format elf32-avr"));
}
