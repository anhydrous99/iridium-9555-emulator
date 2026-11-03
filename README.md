# Iridium 9555 / 9575 Extreme firmware emulator

Runs original HT25003 (9555) and HL25003 (9575 Extreme) firmware instructions on XAP2, AVR, and SPARC interpreters,
with a local handset/debugging interface and offline satellite scenarios.

**This is a partial hardware emulator.** Experimental initialization runs the
original application through its animation to the home screen, renders its LCD
traffic and delivers software key events. The original Menu opens from the home
screen. Natural hardware boot and a firmware-connected satellite link remain incomplete.
The interface makes those boundaries visible.

## Run

Requires Python 3.10+ and Zig **0.17.0** on `PATH`. No Python packages, Node
packages, or external services are needed to run it. Node 18+ is used for UI tests.

The latest standard 9575 Extreme release verified on November 2, 2026 is
**HL25003**, listed by Iridium on January 13, 2026. The downloaded and extracted
images are in the ignored `firmware/9575/` directory. This profile is for the
standard Extreme; Extreme PTT's HP25003 application is a separate release.
See [firmware acquisition and hashes](docs/9575-firmware.md) for the manufacturer
listing, distributor download, checksums, and reproducible extraction command.

```sh
./run --model 9575 --initialize-ui
# Equivalently, identify the handset from its checked firmware container:
./run firmware/9575 --initialize-ui
./run firmware/9575 --inspect
```

The 9575 profile uses its own BC5 memory layout, application entry points,
filesystem and AVR configuration. Its original home screen, menus and LCD
traffic execute from HL25003. The UI selects the handset from the loaded image
and exposes its dedicated SOS and right-side convenience controls. A model switch
starts a new experiment and closes the previous handset's processors.

```sh
./run /home/arxherre/Documents/Projects/rev-firmware/firmware --initialize-ui
```

`./run --initialize-ui` defaults to the original 9555 directory under the current user's home.
`--model 9575` defaults to this repository's `firmware/9575` directory. The launcher builds
the native executor using Zig's cache, listens on all IPv4 interfaces
(`0.0.0.0:9555`), and opens a browser at `http://127.0.0.1:9555`.
From another device, open `http://<this-computer-IP>:9555`. Devices that can reach
the port share control of the same emulator session. Each browser owns its held
keys; a key held in several browsers is released after its final owner releases it.
Use `--host 127.0.0.1` for local-only access. Press Ctrl+C to stop the server and
CPU workers. Use
`--no-browser` to print the URL without opening it, or `--port 0` to choose a free port.

`--initialize-ui` runs original application-initialization routines at scheduler
boundaries. On a fresh image, the original firmware writes factory defaults and
requests a reset; the scenario performs a warm reset that preserves them, then
completes application initialization and resumes execution. After the boot
animation, the original home screen appears automatically with **Searching for
Iridium**, **Acquiring time**, **Menu** and **Help**. Press the left soft key to
open the original main menu. Initialization and animation take time to finish.
This remains an experimental startup scenario; natural hardware boot is
incomplete. Without the flag, the interface starts paused; **Initialize
application** invokes the same scenario.

Supply a directory to load BC5, AVR, telephony and PTT images. Telephony and PTT
are alternative modem images, executed in **independent** workers for inspection;
they are not two simultaneously active processors in a real handset.
The source panel lists the filename and SHA-256 of every loaded processor image.

```sh
./run /path/to/main.dfu
./run /path/to/modified-bc5.bin
./run /path/to/modified-avr.bin --image avr
./run /path/to/modified-trx.bin --image trx
./run /path/to/main.dfu --inspect
./run /path/to/firmware --headless --steps 7000000
```

Raw BC5 images and CSR-dfu2 containers use the selected HT25003 or HL25003 layout. The
three container CRCs are checked. A deliberate DFU patch with stale checksums
requires `--allow-invalid-crc`; mismatches remain in the image report. Raw images
are identified by SHA-256, with no claim of container integrity. The profile's
firmware version describes the supported layout, including same-layout patches.
Both packages contain identical modem images; `--model` selects their handset
context when loading them alone. A directory inherits its checked BC5 model.
Relinked images
with moved memory layouts require a new board profile. Installer EXEs and Intel
HEX are not accepted; use the extracted binaries in the supplied project.

The source firmware is read-only. Validated payloads are staged temporarily for
the workers; firmware bytes are not included in this repository. Reset reloads
the supplied image and discards the experiment's RAM and flash changes.

## Current behavior

- Original instructions execute directly; decompiled Zig firmware functions do
  not replace them. CPU/device implementations are reused from the supplied
  reverse-engineering project, with [provenance](native/PROVENANCE.md).
- Run, pause, bounded stepping, reset, processor state, RAM inspection/editing,
  and bounded BC5 function probes support firmware experiments. Invalid guest
  instructions, firmware panic entry, and memory faults are reported explicitly.
- All physical handset controls have press/release events and keyboard bindings.
  After experimental initialization, mapped controls call the original software
  input routine at a scheduler boundary. The left soft key opens the original
  main menu after the animation reaches the home screen. The convenience key
  opens the 9575's original **Enable GPS? / Current Location** screens. Its SOS
  key starts the original cancellable emergency countdown. GPS positions remain
  unavailable without a connected receiver; the emulator makes no emergency
  call or transmission. Electrical matrix scanning and the physical power
  circuit remain unresolved; power events are recorded without firmware delivery.
  See [control evidence](docs/9575-controls.md).
- The ST7541 model decodes the executing firmware's LCD command/data stream.
  Unknown pixels and capture errors are explicit. The handset profile places
  SEG127 at the left, so the original animation and Iridium lettering render
  in the correct direction. This mapping follows the original bitmap and visible
  text; electrical panel wiring and analog grayscale remain unverified.
  Original filesystem bitmaps are also available in a separate **asset preview**.
- Offline scenarios model signal/visibility, registration delay, incoming calls,
  answering, loss of coverage, and incoming SMS. Use **Advance 1 s** while paused.
  These scenarios are **not connected to the executing modem** and perform no
  radio transmission, audio transport, network authentication, or real calls.

The processors' interconnect, GPS receiver, remaining BlueCore peripherals, electrical keypad/LCD
transport, modem boot ROM, DSPs, RF timing, SIM/provisioning and network protocol
remain incomplete. The missing modem boot block is not present in the upgrade
package. See [hardware evidence](docs/hardware-evidence.md) for exact boundaries,
observed startup failures, and what needs to be established next.

## Test

```sh
./test
IRIDIUM_TEST_FIRMWARE=/home/arxherre/Documents/Projects/rev-firmware/firmware ./test
IRIDIUM_TEST_FIRMWARE=/path/to/9555 IRIDIUM_TEST_9575_FIRMWARE=firmware/9575 ./test
```

The first command runs CPU, bus, device, parser, IPC, local API, scenario and UI
input tests. The second also runs original-binary regressions: scheduler/event
loop milestones, original `memset` RAM effects, container-versus-payload parity,
visible intermediate animation frames followed by home, readable Menu/Help captions, menu
navigation and the original missing-SIM error. Deliberate opcode changes must
change execution, including an altered application initializer that must fail
visibly. The original-image suites run separately for each supplied handset
directory and are explicitly skipped when their environment variable is unset.

GitHub Actions runs the firmware-free suite on pushes and pull requests with
Python 3.10, Node 22, and checksum-verified Zig 0.17.0.

Tests establish only their asserted behavior. They do not establish hardware
equivalence, complete menus, satellite acquisition, call audio, or complete modem
operation. The UI behavior tests use a small DOM harness; they do not test browser
layout.

Headless mode prints hashes, CPU state, milestones and fidelity limits as JSON.
It exits 0 for completed instruction budgets, 1 for a host/input error, and 2
for a guest halt or panic. Exit 0 does not mean a complete handset boot.

See [architecture and debugger API](docs/architecture.md) to extend the models
or reproduce original-function probes.

See [performance evaluation](docs/performance.md) for measured optimizations,
raw benchmark samples and commands to reproduce the host, UI and CPU workloads.
