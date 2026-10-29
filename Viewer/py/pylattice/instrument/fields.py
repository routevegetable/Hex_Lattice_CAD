"""Every field the instrument can patch, and what each one is wired to.

A field is a value per end. This is the whole menu the web UI offers and a
preset can name - docs/beatstep.svg has the same thing as a control layout.
"""

from pylattice.fields.artnet import artnet_universes
from pylattice.fields.burst import BurstField
from pylattice.fields.controls import CCField, StrobeField
from pylattice.fields.loops import LoopsField
from pylattice.fields.fire import FireField
from pylattice.fields.gradient import VGradientField
from pylattice.fields.hexes import HexesField
from pylattice.fields.mask import EdgeMaskField
from pylattice.fields.random import NoteRandomField
from pylattice.fields.ripple import NoteRippleField
from pylattice.fields.rotary import RotaryField
from pylattice.fields.scope import ScopeFieldBetter
from pylattice.fields.trace import RandomTraceField
from pylattice.fields.wipe import NoteWipeField
from pylattice.graph import EdgeClass
from pylattice.instrument.hardware import (
    KA1,
    KA2,
    KA3,
    KA4,
    KA5,
    KA6,
    KA7,
    KA8,
    KB1,
    KB2,
    KB3,
    KB4,
    KB5,
    KB6,
    KB7,
    KB8,
    PA1,
    PA2,
    PA3,
    PA4,
    PB1,
    PB2,
    PB3,
    PB4,
    PB5,
    PB6,
    PB7,
    PB8,
    graph,
    midi,
)

ARTNET = artnet_universes(graph, count=4)


class FIELDS:

    # CC fields
    fader_a = CCField(midi.for_("fader_a"), value=KA1)
    fader_b = CCField(midi.for_("fader_b"), value=KA2)
    param_a = CCField(midi.for_("param_a"), value=KA3)
    param_b = CCField(midi.for_("param_b"), value=KA4)

    # Ripples
    ripple = NoteRippleField(graph, midi.for_("ripple"), note=PB1, speed=KB1)
    ripple2 = NoteRippleField(graph, midi.for_("ripple2"), note=PB2, speed=KB2)

    # Every edge jumps to a new random number
    random = NoteRandomField(midi.for_("random"), note=PB6, period=KA8)

    # Wipes
    wipe1 = NoteWipeField(midi.for_("wipe1"), note=PB3, speed=KB3)
    wipe2 = NoteWipeField(midi.for_("wipe2"), note=PB4, speed=KB4)

    # A particle tracing a path of its own from wherever it spawned
    trace = RandomTraceField(graph, midi.for_("trace"), note=PB5, speed=KB5, aim=KB6)

    # A spot going round and round one flat line of the lattice
    scope = ScopeFieldBetter(graph, midi.for_("scope"), speed=KB7, pattern=KB8)

    # Rotated versions of scope
    scope180 = ScopeFieldBetter(
        graph, midi.for_("scope"), speed=KB7, pattern=KB8, phase_offset=0.5
    )
    scope120 = ScopeFieldBetter(
        graph, midi.for_("scope"), speed=KB7, pattern=KB8, phase_offset=0.3
    )
    scope240 = ScopeFieldBetter(
        graph, midi.for_("scope"), speed=KB7, pattern=KB8, phase_offset=0.6
    )

    # Closed figures scattered about, each with a trail going round it. Every
    # knob on the box is spoken for, so these three start off the desk - map
    # them onto something from the expression editor.
    loops = LoopsField(graph, midi.for_("loops"),
                       note=PA4, shape=103, copies=104, speed=105)

    # Complete hexes, selected by the same pattern knob as scope
    hexes = HexesField(graph, midi.for_("hexes"), pattern=KB8)

    # Fire climbing from the bottom, as hard as PB7 is leaned on
    fire = FireField(graph, midi.for_("fire"), note=PB7)

    # Rotary
    rotary = RotaryField(graph, midi.for_("rotary"), period=KA5, parts=KA6, shape=KA7)

    # The same rotation, half a turn round. Not a second field: it shares
    # rotary's phase, so the two stay opposite whichever of them is in a slot.
    rotary180 = rotary.turned(0.5)

    v_rotary = RotaryField(
        graph, midi.for_("v_rotary"), period=KA5, parts=KA6, shape=KA7, vert=True
    )

    v_rotary180 = v_rotary.turned(0.5)

    # Art-Net pixels, per universe: red, green, blue, and their average
    artnet0_r, artnet0_g, artnet0_b, artnet0_v = ARTNET[0]
    artnet1_r, artnet1_g, artnet1_b, artnet1_v = ARTNET[1]
    artnet2_r, artnet2_g, artnet2_b, artnet2_v = ARTNET[2]
    artnet3_r, artnet3_g, artnet3_b, artnet3_v = ARTNET[3]

    v_edges = EdgeMaskField({EdgeClass.C, EdgeClass.F})
    h_edges = EdgeMaskField({EdgeClass.A, EdgeClass.B, EdgeClass.D, EdgeClass.E})
    d1_edges = EdgeMaskField({EdgeClass.A, EdgeClass.C, EdgeClass.E, EdgeClass.F})
    d2_edges = EdgeMaskField({EdgeClass.B, EdgeClass.C, EdgeClass.D, EdgeClass.F})

    strobe0 = StrobeField(midi.for_("strobe0"), strobe=PA1)
    strobe1 = StrobeField(midi.for_("strobe1"), strobe=PA2)
    strobe2 = StrobeField(midi.for_("strobe2"), strobe=PA3)

    v_gradient = VGradientField(midi.for_("v_gradient"), origin=KA6)

    burst = BurstField(graph, midi.for_("burst"), note=PB8, decay=KA7)
