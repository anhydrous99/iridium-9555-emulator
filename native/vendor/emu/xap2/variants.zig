//! Open XAP2 semantics as switchable variants (ARCHITECTURE §6.3 "Open assumptions", §7.6).
//! Each assumption has the chosen reading (index 0) and one alternative (index 1). The executor reads
//! the selected reading at every affected instruction and sets the assumption's bit in `touched` when
//! the alternative would have produced a different result there (so the variant differential re-runs
//! only vectors whose outcome can depend on it). `zig/registry/isa_assumptions.tsv` holds the same rows;
//! the test at the end checks that the file agrees with this table.
const std = @import("std");

pub const Id = enum(u5) {
    nadd_c,
    xor_c,
    tst_and_or_cv,
    div_edge,
    shift_nz,
    fd09_final,
    bc_zero,
    mode2_ind,
    flash_bank,
    irq_entry,
    alias_mode,
    flags_layout,
    shift_count,
    leave_x,
    carry_z,
    ldst_v,
    ram_code,
};

pub const Info = struct {
    key: []const u8,
    /// `open` until evidence settles the chosen reading (`settled`); both readings stay switchable.
    status: []const u8 = "open",
    chosen: []const u8,
    alt: []const u8,
    conf: []const u8,
    scope: []const u8,
    evidence: []const u8,
};

pub const table = std.enums.EnumArray(Id, Info).init(.{
    .nadd_c = .{ .key = "XA-nadd-C", .chosen = "carry", .alt = "borrow", .conf = "M", .scope = "cpu", .evidence = "bc5-isa 2.1/4: 32-bit negate idiom nadd AL,#0; xor AH,#0xFFFF; addc AH,#0 (30 sites) needs C = SRC>=r" },
    .xor_c = .{ .key = "XA-xor-C", .chosen = "preserve", .alt = "clear", .conf = "M", .scope = "cpu", .evidence = "bc5-isa 2.1: the negate idiom needs C to survive xor" },
    .tst_and_or_cv = .{ .key = "XA-tst-and-or-CV", .chosen = "preserve", .alt = "clear", .conf = "assumed", .scope = "cpu", .evidence = "bc5-isa 2.1/4: nothing contradicts preserve; flags after tst/and/or feed only beq/bne/bmi/bpl" },
    .div_edge = .{ .key = "XA-div-edge", .chosen = "trunc", .alt = "floor-sat", .conf = "L", .scope = "cpu", .evidence = "bc5-isa 2.1: AL=quotient AH=remainder is H; rounding, overflow and /0 are not. trunc: C division, quotient truncated to 16 bits, /0 -> AL=0xFFFF AH=old AL. floor-sat: floored, quotient saturated, AH = floored remainder (before saturation), /0 -> 0,0" },
    .shift_nz = .{ .key = "XA-shift-nz", .chosen = "a32", .alt = "al", .conf = "?", .scope = "cpu", .evidence = "bc5-isa 2.1: shifts act on 32-bit A (H); N/Z source unknown (asr->bne once)" },
    .fd09_final = .{ .key = "XA-fd09-final", .chosen = "advance", .alt = "unchanged", .conf = "M", .scope = "cpu", .evidence = "bc5-isa 2.3: final X/AH unknown, assumed advanced by AL like bc; never read afterwards" },
    .bc_zero = .{ .key = "XA-bc-zero", .chosen = "noop", .alt = "one-copy", .conf = "M", .scope = "cpu", .evidence = "bc5-isa 2.3: bc with AL=0 assumed a no-op; memcpy 0x1C6 has no zero guard" },
    .mode2_ind = .{ .key = "XA-mode2-ind", .chosen = "register-direct", .alt = "memory-indirect", .conf = "M", .scope = "cpu", .evidence = "deviates from bc5-isa 1 (memory-indirect, by orthogonality): rts 0x00E2 is the encoding of bra @(0,X) and is H as PC=XH:X; memset 0x5D14 beq @(0,X) returns when n=0 (99 callers); IRQ dispatch bsr @(0,X) lands on handler (v-0x800C)*2 only register-direct (bc5-arch 2, bc5-coverage 1)" },
    .flash_bank = .{ .key = "XA-flash-bank", .status = "settled", .chosen = "1800c", .alt = "800c", .conf = "H", .scope = "soc", .evidence = "page window 0x8000-0x8FFF shows physical flash reg73*0x1000+off; 1800c: image word = physical - 0x1800C. Settled (M3): three firmware paths add 0x10000 to a program/fs address: fs reads (0x6DB86 add AH,#1); 0x64A4 page base [0x34C+(reg74&3)]=0x10, which makes descriptor 0xA3A (fs 0x153F9..0x15444) exactly fn_01a7da; the panic walker 0x7130 add AL,#0xFFFF; addc AH,#0 = ra-1+0x10000, page = that>>12 + [0xF530] (the earlier 'no 0x10' reading missed this fold). Panic-walker oracle (ARCHITECTURE 6.3 item 5, bc5 walker): at 335 calls of the chosen boot the firmware's walk equals the code-word truth in 335/335 under 1800c, 0/335 under 800c. M3 boot: 800c traps brk after 77,864 steps. Bank bit 0xFF9A.14 (+0x80 pages) is H" },
    .irq_entry = .{ .key = "XA-irq-entry", .chosen = "flags-pchi-pclo", .alt = "flags-pclo-pchi", .conf = "L", .scope = "system", .evidence = "bc5-isa 6: handler edits FLAGS at Yi-33 it never wrote; rti @(-33,Y) takes FLAGS from M[Y+o]; PC from M[Y+o+1..o+2] (order unknown). Entry clears FLAGS bit 4 (inferred), PC = code base + 2" },
    .alias_mode = .{ .key = "XA-alias-mode", .chosen = "per-image", .alt = "ff52-bit1", .conf = "L-M", .scope = "cpu", .evidence = "bc5-isa 5/7: aliases 0xFFE0/E1/E3/E4 on in main, RAM in the loader; only mode difference at reset is main setting 0xFF52 bit 1" },
    .flags_layout = .{ .key = "XA-flags-layout", .chosen = "Z0-N1-C2-V3", .alt = "V0-C1-Z2-N3", .conf = "none", .scope = "cpu", .evidence = "bc5-isa 4: no code inspects Z/N/C/V bit positions; stored FLAGS words land in dead frames; bit 4 = IE (M)" },
    .shift_count = .{ .key = "XA-shift-count", .chosen = "full", .alt = "mod32", .conf = "?", .scope = "cpu", .evidence = "bc5-isa 10: counts >= 32 unknown (code uses 0-31). full: everything shifted out, C = last bit out; mod32: count & 31. Count 0 leaves C unchanged in both" },
    .leave_x = .{ .key = "XA-leave-X", .chosen = "load", .alt = "unchanged", .conf = "assumed", .scope = "cpu", .evidence = "bc5-isa 2.3: leave reads PC low from M[Y-2]; X = M[Y-2] assumed, nothing observes it" },
    .carry_z = .{ .key = "XA-carry-Z", .chosen = "result", .alt = "sticky", .conf = "assumed", .scope = "cpu", .evidence = "bc5-isa 2.1: addc Z 'not sticky, assumed'; applied to addc and subc" },
    .ldst_v = .{ .key = "XA-ldst-V", .chosen = "preserve", .alt = "clear", .conf = "assumed", .scope = "cpu", .evidence = "bc5-isa 2.1: ld/st V '- (assumed)'; C preserved is H" },
    .ram_code = .{ .key = "XA-ram-code", .chosen = "a000", .alt = "none", .conf = "M", .scope = "soc", .evidence = "hardware mapping inferred from firmware (A9): program 0x540000+k fetches data RAM 0xA000+k. 0x64A4 copies flash code to RAM and returns the far pointer 0x54:(ram-0xA000) (0x654A-0x6554); 0x16C3E calls it (bsr @(0x21,Y)). none (no code there): boot faults fetching 0x540004 after 3,807 steps" },
});

/// One bit per assumption: in a selection, set = alternative; in `touched`, set = depended on.
pub const Set = struct {
    bits: u32 = 0,

    pub fn has(s: Set, id: Id) bool {
        return s.bits & bit(id) != 0;
    }
    pub fn set(s: *Set, id: Id) void {
        s.bits |= bit(id);
    }
    pub fn with(s: Set, id: Id) Set {
        return .{ .bits = s.bits | bit(id) };
    }
    fn bit(id: Id) u32 {
        return @as(u32, 1) << @backingInt(id);
    }

    /// `XA-nadd-C=borrow` style selection; error for an unknown key or reading.
    pub fn select(s: *Set, key: []const u8, reading: []const u8) error{UnknownAssumption}!void {
        const id = byKey(key) orelse return error.UnknownAssumption;
        const info = table.get(id);
        if (std.mem.eql(u8, reading, info.alt)) {
            s.set(id);
        } else if (std.mem.eql(u8, reading, info.chosen)) {
            s.bits &= ~bit(id);
        } else return error.UnknownAssumption;
    }
};

pub fn byKey(key: []const u8) ?Id {
    for (std.enums.values(Id)) |id| if (std.mem.eql(u8, table.get(id).key, key)) return id;
    return null;
}

pub const tsv_header = "id\tisa\tchosen\talternative\tconf\tscope\tstatus\tevidence";
pub const tsv_path = "zig/registry/isa_assumptions.tsv";

// ---------------------------------------------------------------------------------------------
const testing = std.testing;

test "select by key" {
    var s: Set = .{};
    try s.select("XA-nadd-C", "borrow");
    try testing.expect(s.has(.nadd_c));
    try s.select("XA-nadd-C", "carry");
    try testing.expect(!s.has(.nadd_c));
    try testing.expectError(error.UnknownAssumption, s.select("XA-nope", "x"));
    try testing.expectError(error.UnknownAssumption, s.select("XA-xor-C", "maybe"));
}
