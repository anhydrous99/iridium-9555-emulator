# Original boot animation

This preserves the earlier software-probe investigation. Current startup uses
the coupled AVR power input and GPIO matrix; see [inferred hardware](inferred-hardware.md).

The application bootstrap must enter the original power-on path before running
the scheduler. Calling the UI-start callback directly left the power/charging
state machines in their inactive states. About 2.6 million instructions later,
an original delayed callback placed the battery screen above the animation.

This was observed on both HT25003 (9555) and HL25003 (9575). In HL25003, frames
0, 1, and 2 of resource 21 reached the LCD, then `0x6B214 → 0x713E4 → 0x71728`
opened window 22. The window manager put it ahead of animation window 26.
Subsequent redraws displayed battery resource 4. The animation's frame counter
and 125,000 µs timer continued underneath it until the normal home transition.
Independent reads through original `0x6FA1C` matched resource frames 0, 1, 2, 3,
4, 49, and 97, ruling out missing asset bytes or a flash-page boundary failure.

The explicit bootstrap now executes these original routines, in order, after
application setup:

| Operation | HT25003 | HL25003 | Argument |
| --- | --- | --- | --- |
| Enter power-on and invoke the registered UI-start callback | `0x6BE4C` | `0x6BED0` | `AL=0` |
| Advance the associated charging/UI state | `0x6A092` | `0x6A092` | `AL=3` |

The first call runs the original power transition from state 1 to `0x10`; the
second advances the related state machine from 2 to 3. This is the call sequence
in the successful branch of the original power-on handler (`0x6B096` on HT25003,
`0x6B0AC` on HL25003). Calling that enclosing handler directly would still depend
on its unmodeled external-input guard, so the existing experimental bootstrap
uses the two explicit software boundaries. It does not write guest state flags,
patch instructions, suppress windows, or render extracted animation assets.

With this sequence, original instructions draw successive animation frames,
the animation window remains active through approximately 90 million scheduler
instructions, and the original home window appears at approximately 100 million.
The integration regression compares successive original LCD images with embedded
animation frames before checking the home screen and menu navigation. Some
frames have a few differing pixels in the panel's first column; comparisons of
the animation interior avoid conflating that existing edge artifact with frame
progression.

This corrects the explicit application's startup sequence. The physical power
circuit, board ADC completion, and complete natural hardware boot remain
unmodeled boundaries.
