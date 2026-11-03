//! Flat guest spaces addressed by 16-bit pointers (ARCHITECTURE §3.2, §4.1, §4.2):
//! - BC5 data space: one `[0x10000]u16` array, flash window and ROM regions included, so E3
//!   compares all 64 Ki words. u32 values are stored high word first (`U32`).
//! - AVR SRAM (`[0x500]u8`, LE like the host) and AVR progmem (`[0x4000]u8`, separate ROM array).
//! The image's `mem.zig` owns the array and binds it once: `const S = mem16.Flat(&data, .big);`.
const std = @import("std");
const native_endian = @import("builtin").cpu.arch.endian();

pub const Bc5Data = [0x10000]u16;
pub const AvrData = [0x500]u8;
pub const AvrProg = [0x4000]u8;

/// Typed overlays and `Ptr(T)` on one flat array. `word_order` is the order of units in a value
/// wider than one unit (BC5 `.big`, AVR `.little`). When it differs from the host's, overlay
/// types may not contain native ints wider than a unit (use `U32`), which is checked at comptime.
pub fn Flat(comptime data: anytype, comptime word_order: std.lang.Endian) type {
    const Arr = @typeInfo(@TypeOf(data)).pointer.child;
    const Unit = @typeInfo(Arr).array.child;
    const len = @typeInfo(Arr).array.len;
    const ua = @alignOf(Unit);
    return struct {
        pub const Elem = Unit;

        fn units(comptime T: type) comptime_int {
            if (@sizeOf(T) % @sizeOf(Unit) != 0) @compileError(@typeName(T) ++ ": size is not a whole number of units");
            return @sizeOf(T) / @sizeOf(Unit);
        }

        fn checkWords(comptime T: type) void {
            if (word_order == native_endian) return;
            switch (@typeInfo(T)) {
                .int, .bool, .@"enum", .float => if (@sizeOf(T) > @sizeOf(Unit))
                    @compileError(@typeName(T) ++ ": native multi-unit value has the wrong word order here; use U32 or two units"),
                .@"struct" => |s| if (s.layout == .@"packed") {
                    if (@sizeOf(T) > @sizeOf(Unit)) @compileError(@typeName(T) ++ ": packed struct wider than a unit");
                } else inline for (s.field_types) |F| checkWords(F),
                .array => |a| checkWords(a.child),
                else => {},
            }
        }

        /// Overlay of `T` at guest address `addr` (the address is in units).
        pub fn at(comptime T: type, addr: u32) *align(ua) T {
            comptime checkWords(T);
            if (addr + units(T) > len) @panic("mem16.at: overlay outside the guest array");
            return @ptrCast(&data[addr]);
        }

        /// Guest address of a host pointer into the array.
        pub fn addrOf(p: anytype) u16 {
            const off = @intFromPtr(p) -% @intFromPtr(data);
            if (off >= @sizeOf(Arr) or off % @sizeOf(Unit) != 0) @panic("mem16.addrOf: pointer is not into the guest array");
            return @intCast(off / @sizeOf(Unit));
        }

        /// 16-bit guest data pointer, stored exactly as the original stores it.
        pub fn Ptr(comptime T: type) type {
            return enum(u16) {
                none = 0,
                _,
                const P = @This();
                pub const Target = T;

                /// Host view; null for `none`. Only for ram/rom targets: MMIO goes through the bus.
                pub fn get(p: P) ?*align(ua) T {
                    return if (p == .none) null else at(T, @backingInt(p));
                }
                pub fn of(x: *align(ua) const T) P {
                    return @fromBackingInt(@intCast(addrOf(x)));
                }
                pub fn fromAddr(a: u16) P {
                    return @fromBackingInt(@intCast(a));
                }
                pub fn addr(p: P) u16 {
                    return @backingInt(p);
                }
                /// `p + n` in elements, wrapping at 16 bits like the guest.
                pub fn add(p: P, n: i32) P {
                    const a: i32 = @backingInt(p);
                    return @fromBackingInt(@intCast(@as(u16, @truncate(@as(u32, @bitCast(a +% n *% units(T)))))));
                }
                pub fn cast(p: P, comptime U: type) Ptr(U) {
                    return @fromBackingInt(@intCast(@backingInt(p)));
                }
                pub fn slice(p: P, n: usize) []align(ua) T {
                    if (@backingInt(p) + n * units(T) > len) @panic("mem16.Ptr.slice: outside the guest array");
                    const first: [*]align(ua) T = @ptrCast(&data[@backingInt(p)]);
                    return first[0..n];
                }
            };
        }
    };
}

/// BC5 32-bit value, high word first (AH:AL order).
pub const U32 = extern struct {
    hi: u16,
    lo: u16,
    pub fn init(x: u32) U32 {
        return .{ .hi = @truncate(x >> 16), .lo = @truncate(x) };
    }
    pub fn get(v: U32) u32 {
        return @as(u32, v.hi) << 16 | v.lo;
    }
    pub fn set(v: *U32, x: u32) void {
        v.* = init(x);
    }
    pub fn toAbi(v: U32) u64 {
        return v.get();
    }
    pub fn fromAbi(x: u64) U32 {
        return init(@truncate(x));
    }
};

/// BC5 far code pointer as stored (hi, lo): value = code word + 0x800C (bc5-arch §0).
/// `addr()` is the registry address (Ghidra code byte address = word * 2).
pub const CodePtr = extern struct {
    hi: u16,
    lo: u16,
    pub const bias = 0x800C;
    pub const none: CodePtr = .{ .hi = 0, .lo = 0 };

    pub fn fromAddr(byte_addr: u32) CodePtr {
        std.debug.assert(byte_addr % 2 == 0);
        return fromRaw(byte_addr / 2 + bias);
    }
    pub fn fromRaw(v: u32) CodePtr {
        return .{ .hi = @truncate(v >> 16), .lo = @truncate(v) };
    }
    pub fn raw(p: CodePtr) u32 {
        return @as(u32, p.hi) << 16 | p.lo;
    }
    /// Registry address; a value below the bias (e.g. null) is a safety panic.
    pub fn addr(p: CodePtr) u32 {
        return (p.raw() - bias) * 2;
    }
    pub fn toAbi(p: CodePtr) u64 {
        return p.raw();
    }
    pub fn fromAbi(x: u64) CodePtr {
        return fromRaw(@truncate(x));
    }
};

/// BC5 data addresses `[window_lo, window_end)` are the read-only flash window.
/// 0x0000–0x00FF shadow it (low register page/RAM) and are not loaded from the image.
pub const window_lo = 0x0100;
pub const window_end = 0x3C80;
/// Image word of data address 0 in bc5_main.bin (image byte 0x3096BE, bc5-data §1).
pub const main_window_base = 0x184B5F;

/// `data[a] = image[base + a]` for the window (0x3C7E/0x3C7F are the DFU CRC words).
pub fn fillWindow(data: *Bc5Data, image_words: []const u16, base: u32) error{ImageTooShort}!void {
    if (base + window_end > image_words.len) return error.ImageTooShort;
    @memcpy(data[window_lo..window_end], image_words[base + window_lo ..][0 .. window_end - window_lo]);
}

/// BC5 image bytes (little-endian u16 words) to words. `dst.len` must be `bytes.len / 2`.
pub fn loadWords(dst: []u16, bytes: []const u8) void {
    std.debug.assert(dst.len == bytes.len / 2);
    for (dst, 0..) |*w, i| w.* = std.mem.readInt(u16, bytes[2 * i ..][0..2], .little);
}

/// AVR code pointer: a progmem word address, as stored in the progmem state tables.
pub const WordCodePtr = enum(u16) {
    none = 0,
    _,
    pub fn fromAddr(byte_addr: u32) WordCodePtr {
        std.debug.assert(byte_addr % 2 == 0);
        return @fromBackingInt(@intCast(@as(u16, @intCast(byte_addr / 2))));
    }
    pub fn addr(p: WordCodePtr) u32 {
        return @as(u32, @backingInt(p)) * 2;
    }
};

// ---------------------------------------------------------------------------------------------
const testing = std.testing;

const T5 = struct {
    var data: Bc5Data align(16384) = @splat(0);
    var sram: AvrData = @splat(0);
};
const S = Flat(&T5.data, .big);
const A = Flat(&T5.sram, .little);

// bc5-arch §3 task record: 7 words, task table in the window at 0x0704.
const QueueHead = extern struct { head: u16, tail: u16 };
const Task = extern struct {
    init: CodePtr,
    handler: CodePtr,
    queues: S.Ptr(QueueHead),
    queue_count: u16,
    level: u16,
};

test "BC5 overlay sizes and offsets" {
    try testing.expectEqual(14, @sizeOf(Task));
    try testing.expectEqual(0, @offsetOf(Task, "init"));
    try testing.expectEqual(4, @offsetOf(Task, "handler"));
    try testing.expectEqual(8, @offsetOf(Task, "queues"));
    try testing.expectEqual(10, @offsetOf(Task, "queue_count"));
    try testing.expectEqual(12, @offsetOf(Task, "level"));
    try testing.expectEqual(2, @sizeOf(S.Ptr(QueueHead)));
    try testing.expectEqual(4, @sizeOf(U32));
    try testing.expectEqual(4, @sizeOf(CodePtr));

    @memset(&T5.data, 0);
    // task 1 starts 7 words after 0x0704; fields land on the original word offsets
    T5.data[0x070B] = 0x0005;
    T5.data[0x070C] = 0x87D3;
    T5.data[0x070F] = 0xF100;
    T5.data[0x0710] = 3;
    const tasks = S.at([27]Task, 0x0704);
    try testing.expectEqual(@as(u32, 0x0A0F8E), tasks[1].init.addr());
    try testing.expectEqual(@as(u16, 0xF100), tasks[1].queues.addr());
    try testing.expectEqual(@as(u16, 3), tasks[1].queue_count);
    try testing.expectEqual(S.addrOf(&tasks[1].level), 0x0711);
    tasks[2].level = 0x55;
    try testing.expectEqual(@as(u16, 0x55), T5.data[0x0704 + 2 * 7 + 6]);
}

test "BC5 Ptr round-trips" {
    @memset(&T5.data, 0);
    const q = S.at(QueueHead, 0xA010);
    const p = S.Ptr(QueueHead).of(q);
    try testing.expectEqual(@as(u16, 0xA010), p.addr());
    try testing.expectEqual(q, p.get().?);
    try testing.expectEqual(@as(?*align(2) QueueHead, null), S.Ptr(QueueHead).none.get());
    try testing.expectEqual(@as(u16, 0xA014), p.add(2).addr());
    try testing.expectEqual(@as(u16, 0xA00E), p.add(-1).addr());
    try testing.expectEqual(@as(u16, 0x0001), S.Ptr(u16).fromAddr(0xFFFF).add(2).addr()); // wraps like the guest
    p.get().?.tail = 9;
    try testing.expectEqual(@as(u16, 9), T5.data[0xA011]);
    const w = p.cast(u16).slice(4);
    try testing.expectEqual(@as(usize, 4), w.len);
    try testing.expectEqual(@as(u16, 9), w[1]);
    // a pointer stored in guest memory is the same 16-bit value the original stores
    const slot = S.at(S.Ptr(QueueHead), 0xB000);
    slot.* = p;
    try testing.expectEqual(@as(u16, 0xA010), T5.data[0xB000]);
}

test "U32 is high word first; CodePtr encodes byte/2 + 0x800C" {
    @memset(&T5.data, 0);
    const v = S.at(U32, 0xC000);
    v.set(0x12345678);
    try testing.expectEqual(@as(u16, 0x1234), T5.data[0xC000]);
    try testing.expectEqual(@as(u16, 0x5678), T5.data[0xC001]);
    try testing.expectEqual(@as(u32, 0x12345678), v.get());
    try testing.expectEqual(@as(u64, 0x12345678), v.toAbi());
    try testing.expectEqual(U32.init(0xAABBCCDD), U32.fromAbi(0xAABBCCDD));

    const c = CodePtr.fromAddr(0x0A0F8E);
    try testing.expectEqual(@as(u32, 0x0A0F8E / 2 + 0x800C), c.raw());
    try testing.expectEqual(@as(u16, 0x0005), c.hi);
    try testing.expectEqual(@as(u16, 0x87D3), c.lo);
    try testing.expectEqual(@as(u32, 0x0A0F8E), c.addr());
    try testing.expectEqual(c, CodePtr.fromAbi(c.toAbi()));
    try testing.expectEqual(@as(u32, 0x4), CodePtr.fromRaw(0x800E).addr()); // IRQ stub entry
}

test "BC5 window fill and word loading" {
    @memset(&T5.data, 0);
    const img = try testing.allocator.alloc(u16, main_window_base + window_end);
    defer testing.allocator.free(img);
    for (img, 0..) |*w, i| w.* = @truncate(i);
    try fillWindow(&T5.data, img, main_window_base);
    try testing.expectEqual(@as(u16, 0), T5.data[0x00FF]); // low page not loaded
    try testing.expectEqual(@as(u16, @truncate(main_window_base + 0x100)), T5.data[0x0100]);
    try testing.expectEqual(@as(u16, @truncate(main_window_base + 0x3C7F)), T5.data[0x3C7F]);
    try testing.expectEqual(@as(u16, 0), T5.data[0x3C80]);
    try testing.expectError(error.ImageTooShort, fillWindow(&T5.data, img[0 .. img.len - 1], main_window_base));

    var words: [2]u16 = undefined;
    loadWords(&words, &.{ 0x34, 0x12, 0xCD, 0xAB });
    try testing.expectEqualSlices(u16, &.{ 0x1234, 0xABCD }, &words);
}

test "AVR byte overlay: packed avr-gcc layout, LE, unaligned u16" {
    const Link = extern struct { state: u8, len: u8 align(1), crc: u16 align(1), ptr: A.Ptr(u8) align(1) };
    try testing.expectEqual(6, @sizeOf(Link));
    try testing.expectEqual(2, @offsetOf(Link, "crc"));
    try testing.expectEqual(4, @offsetOf(Link, "ptr"));
    @memset(&T5.sram, 0);
    const l = A.at(Link, 0x0129); // odd address: fine, the overlay is align(1)
    l.crc = 0x1234;
    l.ptr = A.Ptr(u8).fromAddr(0x0138);
    try testing.expectEqualSlices(u8, &.{ 0x34, 0x12, 0x38, 0x01 }, T5.sram[0x012B..0x012F]);
    try testing.expectEqual(@as(u16, 0x0129), A.addrOf(l));
    l.ptr.get().?.* = 0x77;
    try testing.expectEqual(@as(u8, 0x77), T5.sram[0x0138]);
    const u = A.at(u16, 0x0101);
    u.* = 0xBEEF;
    try testing.expectEqual(@as(u8, 0xEF), T5.sram[0x0101]);

    const cp = WordCodePtr.fromAddr(0x0AA2);
    try testing.expectEqual(@as(u16, 0x0551), @backingInt(cp));
    try testing.expectEqual(@as(u32, 0x0AA2), cp.addr());
}
