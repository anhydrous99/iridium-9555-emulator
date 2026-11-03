pub const machine = @import("machine.zig");
pub const devices = @import("devices.zig");
test {
    @import("std").testing.refAllDecls(@This());
}
