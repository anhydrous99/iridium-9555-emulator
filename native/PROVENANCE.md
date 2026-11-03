# Native executor provenance

The files in `vendor/` were copied from the user-supplied `/home/arxherre/Documents/Projects/rev-firmware/zig/` at git commit `c5564a5df4728d7a1e84006ae82caa8b698c9332`.
`vendor/SOURCE.tsv` records the original file hashes. No original firmware bytes or generated firmware translations are included.

The upstream tree has no top-level code license. These user-supplied sources are retained for this project; no broader redistribution license is asserted. Ghidra extension sources and their separate licenses are not included.

Local adaptations: slim module export roots omit external harnesses and tests requiring the upstream tree. The BC5 loader validates image length before allocation and frees allocations on failure. The BC5 map exposes inferred buffer-MMU registers/windows to the new `native/mmu.zig` model. A separate BC5 warm reset preserves RAM and programmed flash for the original retention checks, and reloads its code and constant windows; a fresh experiment still clears RAM and restores the supplied image. Watchdog timing is not assumed. New runtime adapters, protocol and build files live outside `vendor/`.

The common bus precomputes the 16-bit BC5 address classification in a 64 KiB table. Byte buses and wider addresses retain range lookup. Access logging, device routing, faults and fuel accounting are unchanged; exhaustive classification and original-firmware regressions cover the adaptation.

The BC5 flash model now uses an explicitly inferred Am29LV320DB-compatible profile, replacing the upstream inconsistent ID/geometry stub. Its CFI values and sector layout follow [AMD publication 23579, revision C+6](https://www.insidegadgets.com/wp-content/uploads/2012/12/AM29LV320D.pdf). The actual handset part is unidentified; command timing, erase suspend and protection changes are incomplete. No persistent-store values or handset application instructions are supplied by the model.

The AVR UART model records cumulative per-port output-capture losses when its bounded host queue fills. This adds host diagnostics without changing guest serial timing or status flags. The native adapter also stops when the existing AVR watchdog model requests a reset.

The UART status-register adapter preserves transmit-complete flags when software writes zero, and clears them when software writes one. The XAP2 executor charges each decoded instruction word to its execution fuel, so long modifier chains cannot bypass the host work limit.

These are instruction interpreters with partially inferred device models. BC5 IRQs, keypad wiring, LCD transfers, SPARC ASIC/interrupts and radio DSP behavior are incomplete. Reaching scheduler milestones does not establish full handset functionality. AVR device timing is deterministic but includes the documented upstream assumptions. Original `shortcut:` comments and model qualifications are retained.
