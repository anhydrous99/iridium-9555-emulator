# GPS receiver coordinate-range guards

This note records pre-cleanup phase observations. Artifact paths are local-only
files ignored by Git. See the
[factory-suite instructions](factory-e2e.md#running-the-factory-suite)
to collect a new run; that command does not recreate historical
reconciliation directories.

Four [receiver-input tests](../tests/test_factory_gps_range_e2e.py) require an
impossible latitude or longitude to leave the last valid fix intact. All four
currently fail on HL25003: the original AVR publishes the supplied invalid
coordinate and the BC5 accepts it into the current-position cache. These are
robustness checks on out-of-range receiver input, not a claim that a physical
receiver emits such values or that normal RF acquisition fails.

Each case starts fresh original BC5, AVR and TRX workers, acknowledges the
actual startup warnings, selects RealTime and obtains the same valid control:
37.774900 / -122.419400, 30 metres and eight satellites. The full 13-word cache
and complete original-font latitude, longitude, altitude and satellite rows
must match before invalid input is supplied.

The external UART0 input is a complete new epoch: UBX NAV-POSLLH, NAV-SOL,
NAV-TIMEUTC and NAV-VELNED, then NMEA GST. All checksums, epoch times and frame
lengths remain valid. NAV-SOL uses fix type 3 and flags 1, avoiding the separate
[validity-byte defect](gps-solution-validity.md). Only one coordinate is outside
its geographic bounds. The signed inputs fit the protocol's 32-bit fields.

| Case | Offered latitude / longitude | Observed cached latitude / longitude |
| --- | --- | --- |
| North | +91 / +45 | +91 / +45 |
| South | -91 / -45 | -91 / -45 |
| East | +12.5 / +181 | +12.5 / +181 |
| West | -12.5 / -181 | -12.5 / -181 |

After the full epoch and 10 million further original instructions, all four
replace the prior cache, retain the valid-position flag and report nine
satellites. No processor halts. The required retention assertion fails; the
later legal-recovery/reopen/Home assertions stay enabled but are unreached.
Separate [legal boundary tests](../tests/test_factory_gps_coordinate_limits_e2e.py)
already cover exact ±90/±180 endpoints and nearby valid recovery.

Original AVR routine `2B5A` converts a signed coordinate into sign, degrees,
minutes and a fractional minute. NAV-POSLLH path `2D34` calls it for both
coordinates and stores those fields without a geographic limit check in
these paths. The runtime cases establish that the selected impossible values
also pass the downstream cache path. The disassembly was freshly compared
against 14,296 listed bytes of the pinned original AVR image; the relevant
excerpts and source proof are preserved with the diagnostic package. No
firmware image, guest cache, parser callback or display pixel was patched.

The recorded pre-cleanup phase reconciliation
(`test-artifacts/factory-storage-settings-gps/report.json`)
preserves the four ordinary failures separately from
harness errors, skips and the earlier GPS validity/altitude failures. Clock
synchronization, fix age, RF loss/reacquisition and other invalid input classes
remain outside these four assertions.
