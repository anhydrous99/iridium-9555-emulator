//! HT25003/HL25003 keypad contract recovered from original scanner 0x68438 and mapper
//! 0x71476/0x715CC. Rows and columns share PIO 6–10; PIO 11 strobes an external row latch.
//! Inference: sample on the rising edge. The firmware holds row data across both edges,
//! so these images cannot distinguish a rising-edge latch from a falling-edge latch.
const std = @import("std");

pub const mask: u16 = 0x07C0;
pub const strobe: u16 = 0x0800;
pub const codes = [5][5]u16{
    .{ 0x96, 0x82, 0x97, 0x8D, 0x8C },
    .{ 0x65, 0x66, 0x67, 0x83, 0x2A },
    .{ 0x68, 0x69, 0x6A, 0xA1, 0x2B },
    .{ 0x6B, 0x6C, 0x6D, 0xAA, 0x2C },
    .{ 0x79, 0x64, 0x78, 0xA0, 0x2D },
};

pub const Model = struct {
    pressed: u25 = 0,
    rows: u16 = 0,
    clock_high: bool = false,

    pub fn setKey(m: *Model, code: u16, pressed: bool) error{UnknownKey}!void {
        for (codes, 0..) |row, r| for (row, 0..) |value, c| {
            if (value != code) continue;
            const bit = @as(u25, 1) << @intCast(r * 5 + c);
            if (pressed) m.pressed |= bit else m.pressed &= ~bit;
            return;
        };
        return error.UnknownKey;
    }

    pub fn writeGpio(m: *Model, output: u16, direction: u16) void {
        const high = output & direction & strobe != 0;
        if (high and !m.clock_high) m.rows = output & direction & mask;
        m.clock_high = high;
    }

    pub fn inputs(m: *const Model) u16 {
        var columns: u16 = 0;
        // Only directly closed contacts conduct; these images do not establish ghosting behavior.
        for (0..5) |r| {
            if (m.rows & (@as(u16, 0x40) << @intCast(r)) == 0) continue;
            for (0..5) |c| {
                if (m.pressed & (@as(u25, 1) << @intCast(r * 5 + c)) != 0)
                    columns |= @as(u16, 0x40) << @intCast(c);
            }
        }
        return columns;
    }
};

fn select(m: *Model, rows: u16) void {
    m.writeGpio(rows, mask | strobe);
    m.writeGpio(rows | strobe, mask | strobe);
    m.writeGpio(rows, mask | strobe);
    m.writeGpio(0, mask | strobe);
    m.writeGpio(0, strobe);
}

test "all 25 original key codes conduct only their decoded row and column" {
    for (codes, 0..) |row, r| for (row, 0..) |code, c| {
        var m: Model = .{};
        try m.setKey(code, true);
        select(&m, @as(u16, 0x40) << @intCast(r));
        try std.testing.expectEqual(@as(u16, 0x40) << @intCast(c), m.inputs());
        select(&m, @as(u16, 0x40) << @intCast((r + 1) % 5));
        try std.testing.expectEqual(@as(u16, 0), m.inputs());
        select(&m, mask);
        try m.setKey(code, false);
        try std.testing.expectEqual(@as(u16, 0), m.inputs());
    };
}

test "the external latch retains row selection after firmware clears outputs and changes direction" {
    var m: Model = .{};
    try m.setKey(0x96, true);
    try std.testing.expectEqual(@as(u16, 0), m.inputs());
    select(&m, 0x40);
    try std.testing.expectEqual(@as(u16, 0x40), m.rows);
    try std.testing.expectEqual(@as(u16, 0x40), m.inputs());
    m.writeGpio(0, 0);
    try std.testing.expectEqual(@as(u16, 0x40), m.inputs());
    try m.setKey(0x96, false);
    try std.testing.expectEqual(@as(u16, 0), m.inputs());
}

test "only a driven rising strobe captures rows, and changing data while high leaves the latch alone" {
    var m: Model = .{};
    m.writeGpio(strobe | 0x40, mask); // strobe configured as input
    try std.testing.expectEqual(@as(u16, 0), m.rows);
    m.writeGpio(strobe | 0x40, mask | strobe);
    try std.testing.expectEqual(@as(u16, 0x40), m.rows);
    m.writeGpio(strobe | 0x80, mask | strobe);
    try std.testing.expectEqual(@as(u16, 0x40), m.rows);
    m.writeGpio(0x80, mask | strobe);
    m.writeGpio(strobe | 0x80, mask | strobe);
    try std.testing.expectEqual(@as(u16, 0x80), m.rows);
    m.writeGpio(0, mask | strobe);
    m.writeGpio(strobe | 0x400, 0x40 | strobe); // un-driven high output latch bits do not select rows
    try std.testing.expectEqual(@as(u16, 0), m.rows);
}

test "multiple contacts combine directly selected columns without adding ghost paths" {
    var m: Model = .{};
    try m.setKey(0x96, true); // row0,col0
    try m.setKey(0x82, true); // row0,col1
    try m.setKey(0x65, true); // row1,col0
    try m.setKey(0x67, true); // row1,col2
    select(&m, 0x40);
    try std.testing.expectEqual(@as(u16, 0xC0), m.inputs());
    select(&m, 0x80);
    try std.testing.expectEqual(@as(u16, 0x140), m.inputs());
    select(&m, 0xC0);
    try std.testing.expectEqual(@as(u16, 0x1C0), m.inputs());
    select(&m, 0x100);
    try std.testing.expectEqual(@as(u16, 0), m.inputs());
}

test "unestablished keys fail atomically, including SOS absent from both supplied matrices" {
    var m: Model = .{};
    try m.setKey(0xAA, true);
    select(&m, mask);
    const before = m;
    try std.testing.expectError(error.UnknownKey, m.setKey(0xAB, true));
    try std.testing.expectError(error.UnknownKey, m.setKey(0xFFFF, false));
    try std.testing.expectEqual(before, m);
}
