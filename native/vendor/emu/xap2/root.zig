//! XAP2 reference executor (ARCHITECTURE §6.3): decoder, CPU core, open-semantics variants, the flat
//! snippet machine. SoC bindings (memory map, devices, images) are in `soc/bc5`, `soc/bc5_loader`.
const std = @import("std");

pub const decode = @import("decode.zig");
pub const cpu = @import("cpu.zig");
pub const variants = @import("variants.zig");
pub const flat = @import("flat.zig");

test {
    std.testing.refAllDecls(@This());
    _ = @import("cpu_test.zig");
}
