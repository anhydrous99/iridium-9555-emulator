//! Executor unit tests on hand-assembled words (semantics: bc5-isa.md §2–§4, §8).
const std = @import("std");
const testing = std.testing;
const common = @import("common");
const hooks = common.hooks;
const cpu = @import("cpu.zig");
const Flat = @import("flat.zig").Flat;

const base = cpu.image_base;

/// Word for opcode/reg/mode with a one-byte operand (`full` in -128..127).
fn w(op: u4, reg: u2, mode: u2, full: i8) u16 {
    return @as(u16, @as(u8, @bitCast(full))) << 8 | @as(u16, op) << 4 | @as(u16, reg) << 2 | mode;
}
const AH = 0;
const AL = 1;
const X = 2;
const Y = 3;

const T = struct {
    m: Flat = .{},
    seg: [1]cpu.Segment = undefined,

    fn init(t: *T, words: []const u16, alias: bool) !*cpu.Core {
        t.seg = .{.{ .base = base, .words = words }};
        try t.m.init(testing.allocator, &t.seg, alias);
        t.m.core.cpu.pc = base;
        t.m.core.cpu.y = 0xFC00;
        return &t.m.core;
    }
};

test "opt-in FLAGS bank selection applies to offset and zero-offset instruction forms" {
    var t: T = .{};
    const code = [_]u16{ 0xFF05, 0xFE05, 0x0005, 0x0005 };
    const c = try t.init(&code, true);
    defer t.m.deinit();
    c.banked_interrupts = true;
    c.cpu.x = 0x1111;
    c.cpu.y = 0xC000;
    c.cpu.ux = 0x2222;
    c.cpu.uy = 0xD000;
    t.m.data[0xBFFF] = 0x10;
    t.m.data[0xCFFE] = 0;
    t.m.data[0xC000] = 0x10;
    t.m.data[0xD000] = 0x10;
    c.step();
    try testing.expectEqual(@as(u16, 0x2222), c.cpu.x);
    try testing.expectEqual(@as(u16, 0xD000), c.cpu.y);
    c.step();
    try testing.expectEqual(@as(u16, 0x1111), c.cpu.x);
    try testing.expectEqual(@as(u16, 0xC000), c.cpu.y);
    c.step();
    c.step();
    try testing.expectEqual(@as(u16, 0x2222), c.cpu.x);
    try testing.expectEqual(@as(u16, 0x1111), c.cpu.ux);
    try testing.expectEqual(@as(u16, 0xD000), c.cpu.y);
    try testing.expectEqual(@as(u16, 0xC000), c.cpu.uy);
}

test "banked interrupt saves its frame on the inactive stack and RTI restores the user bank" {
    var t: T = .{};
    const code = [_]u16{ 0, 0, 0xDF0D };
    const c = try t.init(&code, true);
    defer t.m.deinit();
    c.banked_interrupts = true;
    c.cpu.pc = base + 0x20;
    c.cpu.x = 0x1111;
    c.cpu.y = 0xC000;
    c.cpu.ux = 0x2222;
    c.cpu.uy = 0xD000;
    c.cpu.flags = 0x10;
    const original = c.cpu;
    try testing.expect(c.interrupt(base));
    try testing.expectEqual(@as(u16, 0x2222), c.cpu.x);
    try testing.expectEqual(@as(u16, 0xD000), c.cpu.y);
    try testing.expectEqual(@as(u16, 0x10), t.m.data[0xCFDF]);
    try testing.expectEqual(@as(u16, 0), t.m.data[0xCFE0]);
    try testing.expectEqual(@as(u16, 0x802C), t.m.data[0xCFE1]);
    try testing.expect(!c.interrupt(base));
    c.step();
    try testing.expectEqualDeep(original, c.cpu);
}

test "banked scratch registers follow the supervisor stack and preserve an outer context" {
    var t: T = .{};
    const code = [_]u16{0x0004};
    const c = try t.init(&code, true);
    defer t.m.deinit();
    c.banked_interrupts = true;
    c.cpu.flags = 0x10;
    c.cpu.y = 0xC000;
    c.cpu.uy = 0xD000;
    t.m.data[0xFFF8] = 0xDEAD;
    t.m.data[0xCFF8] = 0xABCD;
    try testing.expectEqual(@as(u16, 0xABCD), c.read(0xFFF8));
    c.write(0xFFF8, 0x1234);
    try testing.expectEqual(@as(u16, 0x1234), t.m.data[0xCFF8]);
    try testing.expectEqual(@as(u16, 0xDEAD), t.m.data[0xFFF8]);
    c.unpackFlags(0);
    try testing.expectEqual(@as(u16, 0x1234), c.read(0xFFF8));
    c.cpu.y = 0xCF00;
    c.cpu.uy = 0xCE00;
    c.write(0xFFFD, 0xCF00);
    c.unpackFlags(0x10);
    try testing.expectEqual(@as(u16, 0xCF00), c.read(0xFFFD));
    c.write(0xFFF8, 0x5678);
    try testing.expectEqual(@as(u16, 0x5678), t.m.data[0xCEF8]);
    c.cpu.uy = 0xD000;
    try testing.expectEqual(@as(u16, 0x1234), c.read(0xFFF8));
    c.write(0xFFE1, 0xBEEF);
    try testing.expectEqual(@as(u16, 0xBEEF), c.cpu.al);
}

test "bsr leaves the return address in X/XH, rts returns to XH:X; brk halts" {
    var t: T = .{};
    const code = [_]u16{
        w(1, AL, 0, 5), // ld AL,#5
        w(9, 3, 0, 3), // bsr +3 (cw 0x800D -> 0x8010)
        0x0004, // brk
        w(1, AH, 0, 0), // filler (a 0x0000 here would be a prefix)
        w(3, AL, 0, 1), // add AL,#1
        0x00E2, // rts
    };
    const c = try t.init(&code, true);
    defer t.m.deinit();
    try testing.expectEqual(cpu.Halt{ .trap = .brk }, c.run(100));
    try testing.expectEqual(@as(u16, 6), c.cpu.al);
    try testing.expectEqual(@as(u16, 0x800E), c.cpu.x);
    try testing.expectEqual(@as(u16, 0), c.cpu.xh);
    try testing.expectEqual(@as(u16, 0), c.depth);
    try testing.expectEqual(@as(u64, 5), c.steps);
}

test "enter stores XH/X at Y-1/Y-2 and moves Y; leave restores them and returns" {
    var t: T = .{};
    const code = [_]u16{ 0xFC0B, 0xFC0F }; // enter -4; leave -4
    const c = try t.init(&code, true);
    defer t.m.deinit();
    c.cpu.x = 0x1234;
    c.cpu.xh = 5;
    c.step();
    try testing.expectEqual(@as(u16, 0xFBFC), c.cpu.y);
    try testing.expectEqual(@as(u16, 5), t.m.data[0xFBFF]);
    try testing.expectEqual(@as(u16, 0x1234), t.m.data[0xFBFE]);
    c.cpu.x = 0;
    c.cpu.xh = 0;
    try testing.expectEqual(cpu.Halt{ .fault = 0x51234 }, c.run(10));
    try testing.expectEqual(@as(u16, 0xFC00), c.cpu.y);
    try testing.expectEqual(@as(u16, 0x1234), c.cpu.x);
}

test "32-bit negate idiom needs nadd C = carry (XA-nadd-C)" {
    const code = [_]u16{ w(7, AL, 0, 0), w(0xD, AH, 0, -1), w(4, AH, 0, 0), 0x0004 };
    for ([_][3]u32{ .{ 5, 0xFFFF_FFFB, 0 }, .{ 0x1_0000, 0xFFFF_0000, 0 }, .{ 0x1_0000, 0xFFFE_0000, 1 } }) |case| {
        var t: T = .{};
        const c = try t.init(&code, true);
        defer t.m.deinit();
        if (case[2] == 1) c.sel.set(.nadd_c);
        c.cpu.ah = @truncate(case[0] >> 16);
        c.cpu.al = @truncate(case[0]);
        _ = c.run(10);
        try testing.expectEqual(case[1], @as(u32, c.cpu.ah) << 16 | c.cpu.al);
        try testing.expect(c.touched.has(.nadd_c));
    }
}

test "brxl jumps to addr+1+X; bcz is C or Z; memory-indirect and register-direct returns" {
    var t: T = .{};
    var code = [_]u16{ 0xFE09, 0, 0, 0, 0, 0, 0, 0 };
    code[5] = 0x0004;
    const c = try t.init(&code, true);
    defer t.m.deinit();
    c.cpu.x = 4;
    c.step();
    try testing.expectEqual(base + 5, c.cpu.pc);

    var t2: T = .{};
    const code2 = [_]u16{ w(8, AL, 0, 5), w(2, 3, 0, 2), 0x0004, 0x0004 }; // cmp AL,#5; bcz +2
    const c2 = try t2.init(&code2, true);
    defer t2.m.deinit();
    c2.cpu.al = 5;
    _ = c2.run(2);
    try testing.expectEqual(base + 3, c2.cpu.pc);
    c2.cpu.pc = base;
    c2.cpu.al = 6; // 6 - 5: no borrow, not zero -> fall through
    _ = c2.run(2);
    try testing.expectEqual(base + 2, c2.cpu.pc);
    c2.cpu.pc = base;
    c2.cpu.al = 4; // borrow
    _ = c2.run(2);
    try testing.expectEqual(base + 3, c2.cpu.pc);

    var t3: T = .{};
    const code3 = [_]u16{ 0xFF2B, 0xFFE3 }; // st X,@(-1,Y); bra @(-1,Y)
    const c3 = try t3.init(&code3, true);
    defer t3.m.deinit();
    c3.cpu.x = 0x9000;
    c3.cpu.xh = 0x0001;
    _ = c3.run(2);
    try testing.expectEqual(@as(u32, 0x19000), c3.cpu.pc);

    var t4: T = .{};
    const code4 = [_]u16{ w(8, AL, 0, 0), 0x00F6 }; // cmp AL,#0; beq @(0,X) (memset 0x5D14)
    const c4 = try t4.init(&code4, true);
    defer t4.m.deinit();
    c4.cpu.x = 0x800E;
    _ = c4.run(2);
    try testing.expectEqual(@as(u32, 0x800E), c4.cpu.pc);
    try testing.expect(c4.touched.has(.mode2_ind));
}

test "bc and FD09 block copies; bc with AL=0 is a no-op" {
    var t: T = .{};
    const code = [_]u16{ 0xFF09, 0xFD09, 0xFF09 };
    const c = try t.init(&code, true);
    defer t.m.deinit();
    for (0..3) |k| t.m.data[0xA000 + k] = @intCast(0x10 + k);
    c.cpu.x = 0xA000;
    c.cpu.y = 0xB000;
    c.cpu.al = 3;
    c.step();
    try testing.expectEqualSlices(u16, &.{ 0x10, 0x11, 0x12 }, t.m.data[0xB000..0xB003]);
    try testing.expectEqual(@as(u16, 0xA003), c.cpu.x);
    try testing.expectEqual(@as(u16, 0xB003), c.cpu.y);
    try testing.expectEqual(@as(u16, 0), c.cpu.al);
    try testing.expectEqual(cpu.Z | cpu.N | cpu.C | cpu.V, c.cpu.fq); // bc5-isa §4, §10
    c.cpu.x = 0xA000;
    c.cpu.ah = 0xC000;
    c.cpu.al = 2;
    c.step();
    try testing.expectEqualSlices(u16, &.{ 0x10, 0x11 }, t.m.data[0xC000..0xC002]);
    try testing.expectEqual(@as(u16, 0xC002), c.cpu.ah);
    try testing.expectEqual(@as(u16, 0), c.cpu.al);
    const y = c.cpu.y;
    c.step(); // AL = 0
    try testing.expectEqual(y, c.cpu.y);
    try testing.expect(c.touched.has(.bc_zero));
}

test "bc whose destination keeps crossing 0xFFE1/0xFFE3/0xFFE4 traps illegal after copy_limit words, registers kept" {
    var t: T = .{};
    const code = [_]u16{0xFF09};
    const c = try t.init(&code, true);
    defer t.m.deinit();
    // Y=FFE1 reloads AL=10, Y=FFE3 sets X=0x9FFE (+1), Y=FFE4 sets Y=0xFFE0 (+1): a 4-word cycle.
    t.m.data[0xA000] = 10;
    t.m.data[0xA002] = 0x9FFE;
    t.m.data[0x9FFF] = 0xFFE0;
    c.cpu.x = 0xA000;
    c.cpu.y = 0xFFE1;
    c.cpu.al = 10;
    c.cpu.flags = cpu.C;
    const before = c.cpu;
    try testing.expectEqual(cpu.Halt{ .trap = .illegal }, c.run(5));
    try testing.expectEqual(before, c.cpu);
    try testing.expectEqual(@as(u64, cpu.Core.copy_limit) * 2 + 2, std.math.maxInt(u64) - t.m.bus.fuel);
}

test "codeword fuel bounds modifier chains without charging observational fetch; refilling recovers" {
    var code: [4096]u16 = @splat(0x0009);
    code[code.len - 1] = w(0xA, 1, 0, 1); // lsr #1
    var t: T = .{};
    const c = try t.init(&code, true);
    defer t.m.deinit();
    c.cpu.al = 0x8000;
    const before = c.cpu;
    t.m.bus.resetRun(4); // One instruction unit, then three modifier codewords.
    try testing.expectEqual(cpu.Halt.fuel_exhausted, c.run(1));
    try testing.expectEqual(common.bus.Stop.fuel_exhausted, t.m.bus.stop.?);
    try testing.expectEqual(@as(u64, 0), t.m.bus.fuel);
    try testing.expectEqual(@as(u64, 0), c.steps);
    try testing.expectEqual(before, c.cpu);

    // Observation still works after exhaustion and preserves the stop and budget.
    const insn = c.fetch(base).?;
    try testing.expectEqual(@as(u32, code.len), insn.n);
    try testing.expectEqual(@as(u64, 0), t.m.bus.fuel);
    try testing.expectEqual(common.bus.Stop.fuel_exhausted, t.m.bus.stop.?);

    t.m.bus.resetRun(code.len + 1); // Exactly enough for the instruction and all its codewords.
    try testing.expectEqual(cpu.Halt.steps, c.run(1));
    try testing.expectEqual(@as(?common.bus.Stop, null), t.m.bus.stop);
    try testing.expectEqual(@as(u64, 0), t.m.bus.fuel);
    try testing.expectEqual(@as(u64, 1), c.steps);
    try testing.expectEqual(@as(u16, 0x4000), c.cpu.al);
    try testing.expectEqual(base + code.len, c.cpu.pc);
    try testing.expectEqual(cpu.Halt.fuel_exhausted, c.run(1));
}

test "codeword fuel boundaries distinguish an exhausted budget from an unmapped word" {
    for ([_]u64{ 0, 1, 2, 3 }) |fuel| {
        var t: T = .{};
        const c = try t.init(&.{w(1, AL, 0, 7)}, true);
        defer t.m.deinit();
        t.m.bus.resetRun(fuel);
        const expected: cpu.Halt = if (fuel < 2) .fuel_exhausted else .steps;
        try testing.expectEqual(expected, c.run(1));
        try testing.expectEqual(@as(u16, if (fuel < 2) 0 else 7), c.cpu.al);
        try testing.expectEqual(@as(u64, if (fuel < 2) 0 else 1), c.steps);
        try testing.expectEqual(fuel - @min(fuel, 2), t.m.bus.fuel);
    }
    for ([_]u64{ 2, 3 }) |fuel| {
        var t: T = .{};
        const c = try t.init(&.{0x0009}, true);
        defer t.m.deinit();
        t.m.bus.resetRun(fuel);
        // Trying the unmapped word costs fuel too; no fuel takes precedence over a fetch fault.
        const expected: cpu.Halt = if (fuel == 2) .fuel_exhausted else .{ .fault = base };
        try testing.expectEqual(expected, c.run(1));
        try testing.expectEqual(@as(u64, 0), c.steps);
        try testing.expectEqual(base, c.cpu.pc);
        try testing.expectEqual(@as(u64, 0), t.m.bus.fuel);
    }
}

test "enter re-reads Y after each store (bc5-isa §8 order): M[Y-1] is the Y alias" {
    var t: T = .{};
    const code = [_]u16{0xFE0B}; // enter -2
    const c = try t.init(&code, true);
    defer t.m.deinit();
    c.cpu.y = 0xFFE5;
    c.cpu.xh = 0;
    c.cpu.x = 0x802E;
    c.step(); // XH -> 0xFFE4 sets Y = 0; X -> M[0xFFFE]; Y = 0 - 2
    try testing.expectEqual(@as(u16, 0xFFFE), c.cpu.y);
    try testing.expectEqual(@as(u16, 0x802E), t.m.data[0xFFFE]);
}

test "32-bit shifts on AH:AL with C = last bit out; N/Z source is XA-shift-nz" {
    var t: T = .{};
    const code = [_]u16{ 0x0009, w(0xA, 1, 0, 1), w(0xA, 0, 0, 16), w(0xA, 1, 0, 31) };
    const c = try t.init(&code, true);
    defer t.m.deinit();
    c.cpu.al = 3;
    c.step(); // lsr #1
    try testing.expectEqual(@as(u16, 1), c.cpu.al);
    try testing.expect(c.cpu.flags & cpu.C != 0);
    c.step(); // asl #16
    try testing.expectEqual(@as(u16, 1), c.cpu.ah);
    try testing.expectEqual(@as(u16, 0), c.cpu.al);
    try testing.expect(c.cpu.flags & cpu.Z == 0); // 32-bit A is non-zero
    try testing.expect(c.touched.has(.shift_nz)); // AL alone is zero
    try testing.expectEqual(cpu.Z | cpu.N | cpu.V, c.cpu.fq); // asl N/Z/V are '?' (bc5-isa §2.1)
    c.cpu.ah = 0x8000;
    c.step(); // asr #31: sign fill
    try testing.expectEqual(@as(u16, 0xFFFF), c.cpu.ah);
    try testing.expectEqual(@as(u16, 0xFFFF), c.cpu.al);
    try testing.expectEqual(cpu.V, c.cpu.fq); // asr gives nz
}

test "udiv: AL = quotient, AH = remainder; umult 32-bit product; flags unknown" {
    var t: T = .{};
    const code = [_]u16{ 0x0009, w(9, 1, 0, 3), 0x0009, w(9, 0, 0, -1) };
    const c = try t.init(&code, true);
    defer t.m.deinit();
    c.cpu.ah = 1;
    c.cpu.al = 0;
    c.step();
    try testing.expectEqual(@as(u16, 0x5555), c.cpu.al);
    try testing.expectEqual(@as(u16, 1), c.cpu.ah);
    try testing.expectEqual(cpu.Z | cpu.N | cpu.C | cpu.V, c.cpu.fq);
    c.step(); // umult #0xFFFF
    try testing.expectEqual(@as(u32, 0x5555 * 0xFFFF), @as(u32, c.cpu.ah) << 16 | c.cpu.al);
}

test "register aliases 0xFFE1/0xFFE4 in the main image, plain RAM in the loader" {
    const code = [_]u16{0xE119}; // ld X,@0xffe1
    for ([_]bool{ true, false }) |alias| {
        var t: T = .{};
        const c = try t.init(&code, alias);
        defer t.m.deinit();
        c.cpu.al = 0x77;
        t.m.data[0xFFE1] = 0x55;
        c.step();
        try testing.expectEqual(@as(u16, if (alias) 0x77 else 0x55), c.cpu.x);
    }
}

test "calls are recorded at depth 0 only (E5) and the call tracker pops on return" {
    hooks.gpa = testing.allocator;
    hooks.reset();
    defer hooks.deinit();
    hooks.recording = true;
    var t: T = .{};
    const code = [_]u16{
        w(9, 3, 0, 3), // 800C bsr 0x800F
        0x0004, //        800D brk
        w(1, AH, 0, 0), // 800E filler
        w(9, 3, 0, 2), // 800F bsr 0x8011 (inside the callee: not recorded)
        0x00E2, //        8010
        0x00E2, //        8011 rts -> 0x8010 pops the nested frame
    };
    const c = try t.init(&code, true);
    defer t.m.deinit();
    _ = c.run(3);
    try testing.expectEqual(@as(usize, 1), hooks.calls.items.len);
    try testing.expectEqual(cpu.byteAddr(0x800F), hooks.calls.items[0].target);
    try testing.expectEqual(@as(u16, 1), c.depth);
}

test "N-version fixes (NVERSION.md Z1-Z3): clear readings define a '?' flag; decode across segments; code at the sentinel runs" {
    // Z1: asr #0 leaves V '?' (V = 0); and AH,#0 under XA-tst-and-or-CV=clear writes V = 0, so V is known.
    var t: T = .{};
    const c = try t.init(&.{ 0x00A4, 0x00C0 }, true);
    defer t.m.deinit();
    try c.sel.select("XA-tst-and-or-CV", "clear");
    _ = c.run(2);
    try testing.expectEqual(@as(u16, 0), c.cpu.fq & cpu.V);
    try testing.expect(c.touched.has(.tst_and_or_cv));

    // Z2: a prefix (or `u`) before an unmapped word faults; before the next segment it is a prefix.
    var m: Flat = .{};
    const split = [_]cpu.Segment{ .{ .base = 0x1000, .words = &.{0x0100} }, .{ .base = 0x1001, .words = &.{0x0514} } };
    try m.init(testing.allocator, &split, true);
    defer m.deinit();
    m.core.cpu.pc = 0x1000;
    _ = m.core.run(1);
    try testing.expectEqual(@as(u16, 0x105), m.core.cpu.al); // ld AL,#0x105
    try testing.expectEqual(@as(u32, 0x1002), m.core.cpu.pc);
    for ([_]u16{ 0x0100, 0x0009 }) |last| {
        var f: Flat = .{};
        const one = [_]cpu.Segment{.{ .base = 0x1000, .words = &.{last} }};
        try f.init(testing.allocator, &one, true);
        defer f.deinit();
        f.core.cpu.pc = 0x1000;
        try testing.expectEqual(cpu.Halt{ .fault = 0x1000 }, f.core.run(1));
        try testing.expectEqual(@as(u64, 0), f.core.steps);
    }

    // Z3: the ABI sentinel ends a run only when no code is mapped there.
    var s: Flat = .{};
    const top = [_]cpu.Segment{.{ .base = cpu.sentinel, .words = &.{ 0x0514, 0x0004 } }};
    try s.init(testing.allocator, &top, true);
    defer s.deinit();
    s.core.cpu.pc = cpu.sentinel;
    try testing.expectEqual(cpu.Halt{ .trap = .brk }, s.core.run(5));
    try testing.expectEqual(@as(u16, 5), s.core.cpu.al);
}
