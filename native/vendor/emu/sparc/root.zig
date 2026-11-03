//! SPARC V8/LEON reference executor (ARCHITECTURE §6.2): `decode` (word -> operation and fields),
//! `dis` (llvm-objdump syntax, for decoder parity), `cpu` (integer unit on the common Bus).
//! Tests, from zig/:  zig test --dep common -Mroot=emu/sparc/root.zig -Mcommon=common/root.zig
//! The `sparc` tool (parity, boot, QEMU oracle, harness demo) is built by emu/sparc/build.sh.
const std = @import("std");

pub const decode = @import("decode.zig");
pub const dis = @import("dis.zig");
pub const cpu = @import("cpu.zig");

test {
    std.testing.refAllDecls(@This());
}
