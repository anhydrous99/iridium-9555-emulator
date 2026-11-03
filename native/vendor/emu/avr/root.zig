//! AVR core exports; parity requiring external firmware/tools is intentionally excluded.
const std = @import("std");
pub const cpu = @import("cpu.zig");
pub const decode = @import("decode.zig");
pub const dis = @import("dis.zig");
pub const abi = @import("abi.zig");
pub const Cpu = cpu.Cpu;
test {
    std.testing.refAllDecls(@This());
}
