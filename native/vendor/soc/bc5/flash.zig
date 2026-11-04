//! External flash behind the page window 0x8000–0x8FFF. This inferred board profile is compatible
//! with an Am29LV320DB: 4 MiB, eight 8-KiB bottom sectors and sixty-three 64-KiB sectors. It is not
//! a measured identification of the handset's part. Original firmware discovers geometry through
//! CFI; no firmware instructions or persistent-store records are supplied by this model.
//! Primary source: AMD Am29LV320D, publication 23579, Rev C+6, tables 4, 9–12 and 14:
//! https://www.insidegadgets.com/wp-content/uploads/2012/12/AM29LV320D.pdf
//! Programming and erase complete immediately. Erase suspend and protection changes are unmodelled.
const std = @import("std");

pub const State = enum(u8) { read, query, unlock1, unlock2, autoselect, program, erase_setup, erase_unlock1, erase_unlock2, bypass, bypass_program, bypass_reset };

pub const assumption = "inferred-am29lv320db-compatible";
pub const parameter_sector_words: u32 = 0x1000;
pub const main_sector_words: u32 = 0x8000;
/// 4 MiB part: the image and its filesystem fit in 2 Mi 16-bit words.
pub const size_words = 0x200000;
pub const manufacturer: u16 = 0x0001;
pub const device: u16 = 0x22F9;

/// Word-addressed CFI values from the selected part's datasheet. Unknown locations read erased.
fn query(p: u32) u16 {
    return switch (p & 0xFF) {
        0x10 => 'Q',
        0x11 => 'R',
        0x12 => 'Y',
        0x13 => 2,
        0x14, 0x16...0x1A, 0x1D, 0x1E, 0x20, 0x22, 0x24, 0x26, 0x29...0x2B => 0,
        0x15 => 0x40,
        0x1B => 0x27,
        0x1C => 0x36,
        0x1F => 4,
        0x21 => 10,
        0x23 => 5,
        0x25 => 4,
        0x27 => 22,
        0x28 => 2,
        0x2C => 2,
        // 8 x 8192 bytes followed by 63 x 65536 bytes.
        0x2D => 7,
        0x2E => 0,
        0x2F => 0x20,
        0x30 => 0,
        0x31 => 0x3E,
        0x32 => 0,
        0x33 => 0,
        0x34 => 1,
        0x35...0x3C => 0,
        0x40 => 'P',
        0x41 => 'R',
        0x42 => 'I',
        0x43, 0x44 => '1',
        0x45, 0x4A...0x4C => 0,
        0x46 => 2,
        0x47, 0x49 => 4,
        0x48 => 1,
        0x4D => 0xB5,
        0x4E => 0xC5,
        0x4F => 2,
        else => 0xFFFF,
    };
}

pub const Flash = struct {
    words: []u16 = &.{},
    state: State = .read,

    pub fn read(f: *const Flash, p: u32) u16 {
        if (f.state == .query) return query(p);
        if (f.state == .autoselect) return switch (p & 0xFF) {
            0 => manufacturer,
            1 => device,
            else => 0,
        };
        return if (p < f.words.len) f.words[p] else 0xFFFF;
    }

    pub fn write(f: *Flash, p: u32, v: u16) void {
        const a = p & 0x7FF;
        const cmd: u8 = @truncate(v);
        f.state = switch (f.state) {
            .program, .bypass_program => blk: {
                if (p < f.words.len) f.words[p] &= v; // programming only clears bits
                break :blk if (f.state == .bypass_program) .bypass else .read;
            },
            .read => if (cmd == 0x98 and a == 0x55) .query else if (cmd == 0xAA and a == 0x555) .unlock1 else .read,
            .autoselect => if (cmd == 0xF0) .read else if (cmd == 0x98 and a == 0x55) .query else .autoselect,
            .query => if (cmd == 0xF0) .read else .query,
            .unlock1 => if (cmd == 0x55 and a == 0x2AA) .unlock2 else .read,
            .unlock2 => if (a != 0x555) .read else switch (cmd) {
                0x90 => .autoselect,
                0xA0 => .program,
                0x80 => .erase_setup,
                0x20 => .bypass,
                else => .read,
            },
            .bypass => switch (cmd) {
                0xA0 => .bypass_program,
                0x90 => .bypass_reset,
                else => .bypass,
            },
            .bypass_reset => if (cmd == 0) .read else .bypass,
            .erase_setup => if (cmd == 0xAA and a == 0x555) .erase_unlock1 else .read,
            .erase_unlock1 => if (cmd == 0x55 and a == 0x2AA) .erase_unlock2 else .read,
            .erase_unlock2 => blk: {
                if (cmd == 0x10 and a == 0x555) @memset(f.words, 0xFFFF);
                if (cmd == 0x30) {
                    const length: u32 = if (p < 0x8000) parameter_sector_words else main_sector_words;
                    const start = p & ~(length - 1);
                    if (start < f.words.len) @memset(f.words[start..@min(start + length, f.words.len)], 0xFFFF);
                }
                break :blk .read;
            },
        };
    }
};

test "unlock, autoselect, program, sector erase" {
    var mem: [0x8000]u16 = @splat(0xFFFF);
    var f: Flash = .{ .words = &mem };
    f.write(0x5555, 0xAA);
    f.write(0x2AAA, 0x55);
    f.write(0x5555, 0x90);
    try std.testing.expectEqual(manufacturer, f.read(0));
    try std.testing.expectEqual(device, f.read(1));
    f.write(0, 0xF0);
    try std.testing.expectEqual(@as(u16, 0xFFFF), f.read(1));
    for ([_][2]u32{ .{ 0x5555, 0xAA }, .{ 0x2AAA, 0x55 }, .{ 0x5555, 0xA0 }, .{ 0x1234, 0x0F0F } }) |c| f.write(c[0], @intCast(c[1]));
    try std.testing.expectEqual(@as(u16, 0x0F0F), f.read(0x1234));
    for ([_][2]u32{ .{ 0x5555, 0xAA }, .{ 0x2AAA, 0x55 }, .{ 0x5555, 0x80 }, .{ 0x5555, 0xAA }, .{ 0x2AAA, 0x55 }, .{ 0x1000, 0x30 } }) |c| f.write(c[0], @intCast(c[1]));
    try std.testing.expectEqual(@as(u16, 0xFFFF), f.read(0x1234));
    try std.testing.expectEqual(State.read, f.state);
}

test "CFI geometry describes the same capacity and sector sizes as erase" {
    var mem: [16]u16 = @splat(0xCAFE);
    var f: Flash = .{ .words = &mem };
    f.write(0x55, 0x98);
    try std.testing.expectEqual(State.query, f.state);
    try std.testing.expectEqual(@as(u16, 'Q'), f.read(0x10));
    try std.testing.expectEqual(@as(u16, 'R'), f.read(0x11));
    try std.testing.expectEqual(@as(u16, 'Y'), f.read(0x12));
    try std.testing.expectEqual(@as(u16, 2), f.read(0x13));
    var words: u32 = 0;
    for (0..f.read(0x2C)) |region| {
        const p: u32 = 0x2D + @as(u32, @intCast(region)) * 4;
        const count = 1 + @as(u32, f.read(p)) + (@as(u32, f.read(p + 1)) << 8);
        const length = (@as(u32, f.read(p + 2)) + (@as(u32, f.read(p + 3)) << 8)) * 128;
        try std.testing.expectEqual(if (region == 0) parameter_sector_words else main_sector_words, length);
        words += count * length;
    }
    try std.testing.expectEqual(size_words, words);
    try std.testing.expectEqual(words * 2, @as(u32, 1) << @as(u5, @intCast(f.read(0x27))));
    f.write(0, 0xF0);
    try std.testing.expectEqual(State.read, f.state);
    try std.testing.expectEqual(@as(u16, 0xCAFE), f.read(0));
}

test "sector erase preserves adjacent persistent-store banks and follows main-sector boundaries" {
    var mem: [0x18000]u16 = @splat(0);
    var f: Flash = .{ .words = &mem };
    for ([_]u32{ 0x3456, 0x9999 }) |address| {
        for ([_][2]u32{ .{ 0x5555, 0xAA }, .{ 0x2AAA, 0x55 }, .{ 0x5555, 0x80 }, .{ 0x5555, 0xAA }, .{ 0x2AAA, 0x55 }, .{ address, 0x30 } }) |cycle|
            f.write(cycle[0], @intCast(cycle[1]));
    }
    for (mem, 0..) |word, address| {
        const erased = (address >= 0x3000 and address < 0x4000) or (address >= 0x8000 and address < 0x10000);
        try std.testing.expectEqual(if (erased) @as(u16, 0xFFFF) else 0, word);
    }
}

test "unlock bypass programs arbitrary words repeatedly and requires its two-cycle reset" {
    var mem: [16]u16 = @splat(0xFFFF);
    var f: Flash = .{ .words = &mem };
    for ([_][2]u32{ .{ 0x555, 0xAA }, .{ 0x2AA, 0x55 }, .{ 0x555, 0x20 } }) |cycle|
        f.write(cycle[0], @intCast(cycle[1]));
    try std.testing.expectEqual(State.bypass, f.state);
    // F0 is data after A0, and a normal reset command cannot exit bypass.
    for ([_]u16{ 0xABF0, 0x1234, 0x00FF }) |word| {
        f.write(7, 0xA0);
        f.write(2, word);
        try std.testing.expectEqual(State.bypass, f.state);
    }
    try std.testing.expectEqual(@as(u16, 0x0030), f.read(2));
    f.write(0, 0xF0);
    try std.testing.expectEqual(State.bypass, f.state);
    // A single 90 is not autoselect; the array remains readable until 00.
    f.write(0, 0x90);
    try std.testing.expectEqual(@as(u16, 0x0030), f.read(2));
    f.write(15, 0);
    try std.testing.expectEqual(State.read, f.state);
    // Bypass programming has ended; A0 alone must no longer program.
    f.write(0, 0xA0);
    f.write(3, 0);
    try std.testing.expectEqual(@as(u16, 0xFFFF), f.read(3));
}

test "CFI and autoselect remain read-only until reset and CFI accepts autoselect entry" {
    var mem: [16]u16 = @splat(0xFFFF);
    var f: Flash = .{ .words = &mem };
    for ([_][2]u32{ .{ 0x555, 0xAA }, .{ 0x2AA, 0x55 }, .{ 0x555, 0x90 } }) |cycle|
        f.write(cycle[0], @intCast(cycle[1]));
    for ([_]State{ .autoselect, .query }) |state| {
        if (state == .query) f.write(0x55, 0x98);
        try std.testing.expectEqual(state, f.state);
        for ([_][2]u32{ .{ 0x555, 0xAA }, .{ 0x2AA, 0x55 }, .{ 0x555, 0xA0 }, .{ 4, 0 } }) |cycle|
            f.write(cycle[0], @intCast(cycle[1]));
        try std.testing.expectEqual(state, f.state);
        try std.testing.expectEqual(@as(u16, 0xFFFF), mem[4]);
        f.write(0, 0xFF);
        try std.testing.expectEqual(state, f.state);
    }
    f.write(0xABCDE, 0xABF0);
    try std.testing.expectEqual(State.read, f.state);
    try std.testing.expectEqual(@as(u16, 0xFFFF), f.read(0));
}
