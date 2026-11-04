//! Inferred BC5 buffer MMU, derived from original functions F58C, F63C, F77E,
//! F83E, F856, F882 and FA5A. See docs/hardware-evidence.md.
//! This is an explicit hardware hypothesis, not a hardware-verified model.
const std = @import("std");

pub const assumption = "inferred-bc5-buffer-mmu";
pub const Error = error{
    InvalidFreeList,
    InvalidHandle,
    InvalidPageTable,
    OutOfPages,
    InvalidPage,
    DoubleFree,
    InvalidPageClear,
    UnallocatedRead,
};

const ram_base = 0xA000;
const ram_end = 0xCA80;
const page_bytes = 128;
const page_count = (ram_end - ram_base) * 2 / page_bytes;

pub const Model = struct {
    data: *[0x10000]u16,
    system_control: *u16,
    cursor: u16 = 0,
    free_start: u16 = 0,
    free_end: u16 = 0,
    allocated: [page_count]bool = @splat(false),
    pending_clear: ?u16 = null,

    pub fn handles(addr: u16) bool {
        return (addr >= 0x6E and addr <= 0x71) or
            (addr >= 0x4000 and addr < 0x8000) or addr == 0xFD05 or addr == 0xFFCF;
    }

    pub fn read(m: *Model, addr: u16) Error!?u16 {
        if (addr == 0xFFCF) return m.cursor;
        if ((addr >= 0x6E and addr <= 0x71) or addr == 0xFD05) return m.data[addr];
        if (addr >= 0x4000 and addr < 0x8000) {
            const target = try m.translate(addr, false);
            return (m.data[target.word] >> target.shift) & 0xFF;
        }
        return null;
    }

    pub fn write(m: *Model, addr: u16, value: u16) Error!bool {
        switch (addr) {
            0x6E, 0x6F => {
                if (value > 0xFF) return error.InvalidHandle;
                m.data[addr] = value;
            },
            0x70 => try m.initialize(value),
            0x71 => {
                if (value != 0) try m.release(value);
                m.data[addr] = value;
            },
            0xFD05 => {
                // F77E supplies a byte offset into data RAM, then frees that page via 71.
                if (value >= 0x8000) return error.InvalidPageClear;
                m.pending_clear = value;
                m.data[addr] = value;
            },
            0xFFCF => return error.InvalidFreeList,
            0x4000...0x7FFF => {
                const target = try m.translate(addr, true);
                const mask = @as(u16, 0xFF) << target.shift;
                m.data[target.word] = (m.data[target.word] & ~mask) | ((value & 0xFF) << target.shift);
            },
            else => return false,
        }
        return true;
    }

    fn initialize(m: *Model, start: u16) Error!void {
        if (start == 0) {
            m.cursor = 0;
            m.free_start = 0;
            m.free_end = 0;
            m.pending_clear = null;
            m.allocated = @splat(false);
            m.data[0x70] = 0;
            return;
        }
        if (start < ram_base or start >= ram_end) return error.InvalidFreeList;
        var seen: [page_count]bool = @splat(false);
        var end: u16 = start;
        while (m.data[end] != 0) : (end += 1) {
            const page = m.data[end];
            if (page >= page_count or seen[page] or end + 1 >= ram_end) return error.InvalidFreeList;
            seen[page] = true;
        }
        for (seen, 0..) |present, page| {
            if (present and ram_base + page * (page_bytes / 2) <= end) return error.InvalidFreeList;
        }
        m.cursor = start;
        m.free_start = start;
        m.free_end = end;
        m.allocated = @splat(false);
        m.pending_clear = null;
        m.data[0x70] = start;
    }

    const ByteAddress = struct { word: u16, shift: u4 };

    pub fn readBuffer(m: *Model, handle: u16, offset: u32) Error!u8 {
        const target = try m.translateBuffer(handle, offset, false);
        return @truncate(m.data[target.word] >> target.shift);
    }

    pub fn writeBuffer(m: *Model, handle: u16, offset: u32, value: u8) Error!void {
        const target = try m.translateBuffer(handle, offset, true);
        const mask = @as(u16, 0xFF) << target.shift;
        m.data[target.word] = (m.data[target.word] & ~mask) | (@as(u16, value) << target.shift);
    }

    fn translate(m: *Model, address: u16, allocate: bool) Error!ByteAddress {
        const window: u16 = if (address < 0x6000) 0x4000 else 0x6000;
        const handle = m.data[if (window == 0x4000) 0x6E else 0x6F];
        return m.translateBuffer(handle, address - window, allocate);
    }

    fn translateBuffer(m: *Model, handle: u16, byte_offset: u32, allocate: bool) Error!ByteAddress {
        if (handle == 0 or handle > 0xFF) return error.InvalidHandle;
        const descriptor_address = ram_base + handle * 2;
        const descriptor = m.data[descriptor_address];
        if (descriptor == 0 or descriptor == 0xFFFF) return error.InvalidHandle;
        const table_words = @as(u16, 1) << @as(u4, @intCast(descriptor >> 13));
        const byte_capacity = @as(u32, table_words) * 2 * page_bytes;
        const offset = (@as(u32, m.data[descriptor_address + 1]) +% byte_offset) & (byte_capacity - 1);
        const pointer_scale: u16 = if (m.system_control.* & 0x800 != 0) 2 else 1;
        const table_address = @as(u32, ram_base) + (descriptor & 0x1FFF) * pointer_scale;
        if (table_address < ram_base or table_address + table_words > 0xE000) return error.InvalidPageTable;
        const page_index = offset / page_bytes;
        const table_word: u16 = @intCast(table_address + page_index / 2);
        const table_shift: u4 = @intCast((page_index & 1) * 8);
        var page = (m.data[table_word] >> table_shift) & 0xFF;
        if (page == 0) {
            // shortcut: unallocated reads fault until their hardware behavior is established.
            if (!allocate) return error.UnallocatedRead;
            page = try m.acquire();
            m.data[table_word] = (m.data[table_word] & ~(@as(u16, 0xFF) << table_shift)) | (page << table_shift);
        }
        if (page >= page_count) return error.InvalidPage;
        const byte = @as(u32, page) * page_bytes + offset % page_bytes;
        return .{ .word = @intCast(ram_base + byte / 2), .shift = @intCast((byte & 1) * 8) };
    }

    fn acquire(m: *Model) Error!u16 {
        if (m.cursor == 0 or m.cursor >= m.free_end) return error.OutOfPages;
        const page = m.data[m.cursor];
        if (page == 0 or page >= page_count or m.allocated[page]) return error.InvalidFreeList;
        if (ram_base + @as(u32, page) * (page_bytes / 2) <= m.free_end) return error.InvalidFreeList;
        m.allocated[page] = true;
        m.cursor += 1;
        return page;
    }

    fn release(m: *Model, page: u16) Error!void {
        if (page >= page_count) return error.InvalidPage;
        if (!m.allocated[page] or m.cursor <= m.free_start) return error.DoubleFree;
        if (m.pending_clear) |index| {
            const word = @as(u32, ram_base) + index / 2;
            if (word >= 0xE000) return error.InvalidPageClear;
            const shift: u4 = @intCast((index & 1) * 8);
            if ((m.data[word] >> shift) & 0xFF != page) return error.InvalidPageClear;
            m.data[word] &= ~(@as(u16, 0xFF) << shift);
            m.pending_clear = null;
        }
        m.cursor -= 1;
        m.data[m.cursor] = page;
        m.allocated[page] = false;
    }
};

const Fixture = struct {
    var data: [0x10000]u16 = undefined;
    var control: u16 = 0;

    fn setup() !Model {
        @memset(&data, 0);
        control = 0x800;
        data[0xA002] = 0x8000 | ((0xD000 - ram_base) / 2);
        data[0xA004] = 0x8000 | ((0xD020 - ram_base) / 2);
        for (0..4) |i| data[0xA100 + i] = @intCast(6 + i);
        var m: Model = .{ .data = &data, .system_control = &control };
        _ = try m.write(0x70, 0xA100);
        _ = try m.write(0x6E, 1);
        _ = try m.write(0x6F, 1);
        return m;
    }
};

test "two MMU windows share one handle, distinct handles retain independent bytes" {
    var m = try Fixture.setup();
    _ = try m.write(0x4000, 0x12);
    _ = try m.write(0x4001, 0x34);
    try std.testing.expectEqual(@as(u16, 0x3412), Fixture.data[0xA180]);
    try std.testing.expectEqual(@as(?u16, 0x12), try m.read(0x6000));
    _ = try m.write(0x6E, 2);
    _ = try m.write(0x4000, 0xAB);
    try std.testing.expectEqual(@as(?u16, 0x12), try m.read(0x6000));
    try std.testing.expectEqual(@as(?u16, 0xAB), try m.read(0x4000));
    _ = try m.write(0x6E, 1);
    try std.testing.expectEqual(@as(?u16, 0x34), try m.read(0x4001));
    try std.testing.expectEqual(@as(?u16, 0xA102), try m.read(0xFFCF));
}

test "128-byte page boundaries and descriptor offsets wrap independently of windows" {
    var m = try Fixture.setup();
    _ = try m.write(0x407F, 0x7F);
    _ = try m.write(0x4080, 0x80);
    try std.testing.expectEqual(@as(u16, 0x0706), Fixture.data[0xD000]);
    Fixture.data[0xA003] = 127;
    try std.testing.expectEqual(@as(?u16, 0x7F), try m.read(0x6000));
    try std.testing.expectEqual(@as(?u16, 0x80), try m.read(0x6001));
    Fixture.data[0xA003] = 4095;
    _ = try m.write(0x6001, 0x5A);
    Fixture.data[0xA003] = 0;
    try std.testing.expectEqual(@as(?u16, 0x5A), try m.read(0x4000));
}

test "page clear, release and reuse return actual pages without aliasing live buffers" {
    var m = try Fixture.setup();
    _ = try m.write(0x4000, 0x11);
    _ = try m.write(0x4080, 0x22);
    _ = try m.write(0xFD05, (0xD000 - ram_base) * 2);
    _ = try m.write(0x71, 6);
    try std.testing.expectEqual(@as(u16, 0x0700), Fixture.data[0xD000]);
    try std.testing.expectEqual(@as(?u16, 0xA101), try m.read(0xFFCF));
    try std.testing.expectError(error.DoubleFree, m.write(0x71, 6));
    _ = try m.write(0x6E, 2);
    _ = try m.write(0x4000, 0x33);
    try std.testing.expectEqual(@as(?u16, 0x22), try m.read(0x6080));
    try std.testing.expectEqual(@as(u16, 6), Fixture.data[0xD020]);
}

test "invalid descriptors, malformed free lists and unallocated reads fail explicitly" {
    var m = try Fixture.setup();
    try std.testing.expectError(error.UnallocatedRead, m.read(0x4000));
    try std.testing.expectError(error.InvalidHandle, m.write(0x6E, 256));
    Fixture.data[0xA002] = 0xFFFF;
    try std.testing.expectError(error.InvalidHandle, m.write(0x4000, 1));
    Fixture.data[0xA002] = 0x8000 | 0x1FFF;
    try std.testing.expectError(error.InvalidPageTable, m.write(0x4000, 1));
    Fixture.data[0xA101] = 6;
    try std.testing.expectError(error.InvalidFreeList, m.write(0x70, 0xA100));
}

test "page exhaustion preserves the existing page mappings" {
    var m = try Fixture.setup();
    for (0..4) |i| _ = try m.write(@intCast(0x4000 + i * 128), @intCast(i + 1));
    try std.testing.expectError(error.OutOfPages, m.write(0x4200, 99));
    try std.testing.expectEqual(@as(u16, 0), Fixture.data[0xD002]);
    try std.testing.expectEqual(@as(?u16, 1), try m.read(0x6000));
    try std.testing.expectEqual(@as(?u16, 4), try m.read(0x6180));
}

test "unscaled page table pointer and reset follow the selected register mode" {
    var m = try Fixture.setup();
    Fixture.control = 0;
    Fixture.data[0xA002] = 0x8000 | (0xB000 - ram_base);
    _ = try m.write(0x4000, 0xFE);
    try std.testing.expectEqual(@as(u16, 6), Fixture.data[0xB000]);
    _ = try m.write(0x70, 0);
    try std.testing.expectEqual(@as(?u16, 0), try m.read(0xFFCF));
    try std.testing.expectEqual(@as(?u16, null), try m.read(0xFFB5));
    try std.testing.expect(!try m.write(0xFFB5, 1));
}
