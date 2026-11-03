# Performance evaluation

Six optimizations reduce repeated display work and native execution overhead.
On this machine, constructing and serializing a BC5 session with an unchanged
live display is **8.3× faster**, the JavaScript framebuffer paint workload is
**1.76× faster**, and original application initialization takes **15% less time**.
The full home-screen framebuffer and native state checkpoints match baseline.

## Results

These are median wall times from seven samples, after warming each workload.
Baseline is commit `484a759`; both native builds use ReleaseSafe and Zig 0.17.0.
The host is an AMD Ryzen 7 3800X running Linux, Python 3.14.4 and Node 22.22.1.
Samples and source/executable hashes are retained in [baseline.json](performance/baseline.json)
and [optimized.json](performance/optimized.json).

| Workload | Before | Combined | Less time |
| --- | ---: | ---: | ---: |
| Unchanged LCD projection | 4.275 ms | 0.031 ms | 99.3% |
| Fresh full LCD stream and projection | 4.617 ms | 3.910 ms | 15.3% |
| BC5 session state and JSON, unchanged display | 8.109 ms | 0.975 ms | 88.0% |
| Loopback HTTP state poll | 7.715 ms | 1.944 ms | 74.8% |
| JavaScript framebuffer redraw | 8.006 ms | 4.562 ms | 43.0% |
| Original application initialization | 1,142.743 ms | 971.749 ms | 15.0% |

HTTP measurements use a real synthetic AVR worker and a complete test LCD,
including connection setup, response transfer and client JSON parsing. The
response remains 117,085 bytes. BC5 state measurements use the original image
after 120 million animation instructions. The UI benchmark uses Node with a
small DOM/canvas stub; its times cover JavaScript work, excluding browser layout
and GPU drawing. Unchanged UI signature checks remain about 0.255 ms.

## Kept changes

- Cache the payload SHA-256 on each immutable firmware object. State polling
  previously hashed the multi-megabyte BC5 payload twice per request.
- Cache the LCD projection until another nonempty stream fragment arrives.
  Return separate pixel, evidence-mask and palette lists so callers cannot
  corrupt the cached display or earlier snapshots. Errors invalidate the cache
  along with the fragment that caused them.
- Handle display-off and entire-display overrides outside the pixel loop, and
  combine the two horizontal mapping reversals before projecting pixels.
- Write RGBA channels directly into the image buffer, removing 16,384 temporary
  array allocations per complete UI repaint.
- Classify BC5 data addresses through a 64 KiB lookup table. Wider addresses and
  byte buses retain range lookup; device routing, fuel, faults and logs remain
  in the normal access path.
- Select the native CPU instruction loop once per run request. The interpreter
  still executes every instruction and performs its existing observations.

## Candidate selection

The independent host experiments measured state construction plus JSON with a
complete test LCD and the original BC5 image:

| Candidate | Median |
| --- | ---: |
| Baseline | 7.982 ms |
| Payload hash cache only | 5.097 ms |
| LCD projection cache only | 3.954 ms |
| Both caches | 0.987 ms |

The lookup table alone improved BC5 but slowed the other native workloads by
about 3–4%. Adding loop specialization removed those regressions relative to
baseline. A separate comparison pinned all workers to CPU 2, rotated variant
order, discarded two warm-up rounds and measured nine rounds per variant.
Each timing includes reset and seven million original instructions:

| Processor | Baseline | Loop specialization | Combined |
| --- | ---: | ---: | ---: |
| BC5 | 210.394 ms | 209.288 ms | 179.513 ms |
| AVR | 274.584 ms | 256.569 ms | 257.598 ms |
| Telephony SPARC | 223.985 ms | 219.404 ms | 218.103 ms |
| PTT SPARC | 233.116 ms | 217.869 ms | 223.210 ms |
| Sum of these independent workloads | 942.079 ms | 903.131 ms | 878.424 ms |

The combined version has the lowest total and improves every processor relative
to baseline. Loop specialization alone remains slightly faster for AVR and PTT;
the combined version's BC5 gain outweighs those differences. These sums compare
independent instruction workloads, not synchronized handset execution.
[experiments.json](performance/experiments.json) retains the component samples.

## Validation and limits

`IRIDIUM_TEST_FIRMWARE=/path/to/firmware ./test` covers the native unit suite,
protocol and host regressions, UI tests, original initialization, animation,
readable Menu/Help output, menu navigation, absent-SIM behavior and deliberate
firmware mutation failures. New checks cover all four RGBA shades, snapshot
isolation, payload identity and exhaustive 16-bit address classification.

All four complete native JSON states after seven million steps match baseline.
The complete original home-screen framebuffer hash also matches. A separate
comparison of 120 randomized LCD streams matched baseline across fragmented
writes, partial RAM, orientation, scrolling, reverse video, overrides and sleep.

Caching retains approximately 256 KiB of projected LCD lists and 64 KiB of bus
classification per BC5 session, plus small metadata. Fresh display changes still
require projection; unchanged-display gains do not apply to every animation
frame. Hardware performance counters were unavailable in this environment;
native conclusions use repeated wall-clock measurements. Timing results are
local measurements, not CI thresholds or physical hardware clock estimates.

## Reproduce

```sh
zig build -j2
python3 tools/benchmark.py --output /tmp/performance.json
python3 tools/benchmark.py --firmware /path/to/firmware --output /tmp/performance-original.json
```

No proprietary firmware is needed for the first benchmark. Original images add
four CPU workloads, application initialization and the original live-display
state workload. The scripts use only Python and Node standard libraries. Use
`--samples 9`, `--engine /path/to/iridium-core`, or `--profile /tmp/polls.prof`
for additional samples, another native build, or a Python polling profile.
Run variants sequentially on the same machine without concurrent builds/tests;
on Linux, `taskset -c 2` can pin the benchmark and its workers to the same core.
