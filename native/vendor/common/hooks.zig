//! Process-global test hooks used by `rt.call` in verify builds (ARCHITECTURE §5.1, §7.2):
//! E5 call recording, callee-mode selection (`force`), intercepts (replay, test stubs),
//! `noreturn` handling and loop sync points. The harness sets them; `reset()` clears them.
const std = @import("std");

/// One ABI argument: raw bits (zero-extended) and the declared width in bits.
pub const Arg = struct { value: u64, bits: u16 };

/// One call leaving the function under test (E5). Its arguments are `argsOf(ev)`.
pub const CallEvent = struct { target: u32, first_arg: u32, n_args: u32 };

/// `isForced(a) = all != flip.contains(a)`, so "all except F" and "only S" are both one set.
pub const ForceSet = struct {
    all: bool = false,
    flip: std.AutoHashMapUnmanaged(u32, void) = .empty,
    pub fn isForced(s: *const ForceSet, addr: u32) bool {
        return s.all != s.flip.contains(addr);
    }
};

pub var gpa: std.mem.Allocator = std.heap.page_allocator;
/// Record E5 events for calls made at `depth == record_depth` (0 when the harness calls the
/// Zig body directly, 1 when it calls through the wrapper).
pub var recording: bool = false;
pub var record_depth: u32 = 0;
/// Current wrapper nesting depth, maintained by `rt.call`.
pub var depth: u32 = 0;
pub var calls: std.ArrayList(CallEvent) = .empty;
pub var call_args: std.ArrayList(Arg) = .empty;
/// Targets that run as original code instead of their Zig body (bridges always do).
pub var force: ForceSet = .{};
/// Replay/test stub: return a raw value to skip the call, or null to let it run.
/// Not consulted for `noreturn` targets.
pub var intercept: ?*const fn (target: u32, args: []const Arg) ?u64 = null;
/// Called on a `noreturn` wrapper: writes `noreturn_call(target, args)` and the state, then `_exit`.
pub var on_noreturn: ?*const fn (target: u32, args: []const Arg) noreturn = null;
/// `rt.sync(i)` at loop heads of `kind=loop` functions.
pub var on_sync: ?*const fn (index: u32) void = null;

pub fn recordCall(target: u32, args: []const Arg) void {
    const first: u32 = @intCast(call_args.items.len);
    call_args.appendSlice(gpa, args) catch @panic("hooks: out of memory");
    calls.append(gpa, .{ .target = target, .first_arg = first, .n_args = @intCast(args.len) }) catch @panic("hooks: out of memory");
}

pub fn argsOf(ev: CallEvent) []const Arg {
    return call_args.items[ev.first_arg..][0..ev.n_args];
}

/// Callee-original mode: every target except `except` runs as original code.
pub fn forceAllExcept(except: []const u32) !void {
    try setForce(true, except);
}

/// Only `only` run as original (integrated mode: `&.{}`; bisection: a subset).
pub fn forceOnly(only: []const u32) !void {
    try setForce(false, only);
}

fn setForce(all: bool, flip: []const u32) !void {
    force.all = all;
    force.flip.clearRetainingCapacity();
    for (flip) |a| try force.flip.put(gpa, a, {});
}

/// Clears all hook state between runs; keeps allocated capacity.
pub fn reset() void {
    recording = false;
    record_depth = 0;
    depth = 0;
    calls.clearRetainingCapacity();
    call_args.clearRetainingCapacity();
    force.all = false;
    force.flip.clearRetainingCapacity();
    intercept = null;
    on_noreturn = null;
    on_sync = null;
}

pub fn deinit() void {
    reset();
    calls.deinit(gpa);
    call_args.deinit(gpa);
    force.flip.deinit(gpa);
    calls = .empty;
    call_args = .empty;
    force = .{};
}
