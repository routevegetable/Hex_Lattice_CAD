"""Every field the instrument can patch, and what each one is wired to.

A field is a value per end. This is the whole menu the web UI offers and a
preset can name - docs/beatstep.svg has the same thing as a control layout.
"""

import operator
from typing import Callable
from pylattice.examples.tempo import Event
from pylattice.fields.artnet import artnet_universes
from pylattice.fields.burst import BurstField
from pylattice.fields.controls import CCField, StrobeField
from pylattice.fields.loops import LoopsField, LoopTracesField
from pylattice.fields.fire import FireField
from pylattice.fields.gradient import VGradientField
from pylattice.fields.lfo import LFOField
from pylattice.fields.hexes import HexesField
from pylattice.fields.mask import D1, D2, EdgeMaskField, H, RandomLinesField, V
from pylattice.fields.operators import (
    Arity,
    Cycle,
    GradientChooser,
    Randomize,
    Operator,
    ProbZap,
    Select,
)
from pylattice.fields.random import NoteRandomField
from pylattice.fields.ripple import NoteRippleField
from pylattice.fields.rotary import RotaryField
from pylattice.fields.scope import ScopeFieldBetter
from pylattice.fields.trace import RandomTraceField, TraceLinesField
from pylattice.fields.types import ScalarField, average, divide
from pylattice.fields.wipe import NoteWipeField
from pylattice.graph import EndRef
from pylattice.instrument.gradients import GRADIENTS
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
    PA5,
    PA6,
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



class Math(Operator):
    """A plain callable as an operator: its arguments evaluated, then handed
    over as numbers.

    The arity comes in with the callable rather than being set on the class,
    because that is what has it - `operator.add` takes two, `average` takes
    however many it is given.
    """

    def __init__(self, c: Callable, arity: Arity):
        self._c = c
        self.arity = arity

    def get(self, now: Event, end: EndRef, *args: ScalarField) -> float:
        arg_values = [arg.get(now, end) for arg in args]
        return self._c(*arg_values)

class FIELDS:

    # CC fields
    fader_a = CCField(midi.for_("fader_a"), value=KA1)
    fader_b = CCField(midi.for_("fader_b"), value=KA2)
    fader_c = CCField(midi.for_("fader_c"), value=14)
    fader_d = CCField(midi.for_("fader_d"), value=15)
    fader_e = CCField(midi.for_("fader_e"), value=16)
    fader_f = CCField(midi.for_("fader_f"), value=17)
    fader_g = CCField(midi.for_("fader_g"), value=18)
    fader_h = CCField(midi.for_("fader_h"), value=19)
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
    trace = RandomTraceField(
        graph, midi.for_("trace"), note=PB5, speed=KB5, aim=KB6, attack=108
    )

    # The same trace, kept to the lattice's straight lines. Shares trace's
    # speed and attack - it is the same head on the same trail - and has a pad,
    # a decay and a mode of its own.
    trace_lines = TraceLinesField(graph, midi.for_("trace_lines"), note=PB7,
                                  speed=KB5, attack=108, decay=121, mode=120,
                                  nodes=125)

    # A spot going round and round one flat line of the lattice
    scope = ScopeFieldBetter(
        graph, midi.for_("scope"), speed=KB7, pattern=KB8, attack=106
    )

    # Rotated versions of scope
    scope180 = ScopeFieldBetter(
        graph, midi.for_("scope"), speed=KB7, pattern=KB8, attack=106, phase_offset=0.5
    )
    scope120 = ScopeFieldBetter(
        graph, midi.for_("scope"), speed=KB7, pattern=KB8, attack=106, phase_offset=0.3
    )
    scope240 = ScopeFieldBetter(
        graph, midi.for_("scope"), speed=KB7, pattern=KB8, attack=106, phase_offset=0.6
    )

    # Closed figures scattered about, each with a trail going round it. Every
    # knob on the box is spoken for, so these three start off the desk - map
    # them onto something from the expression editor.
    loops = LoopsField(
        graph,
        midi.for_("loops"),
        note=PA4,
        shape=103,
        copies=104,
        speed=105,
        attack=107,
    )

    # What those figures fire out of their corners. Its own field with its own
    # pad and knobs, so the bodies and the traces can be patched to different
    # things and dialled apart.
    loop_traces = LoopTracesField(
        loops,
        midi.for_("loop_traces"),
        fire=PA5,
        speed=122,
        attack=123,
        decay=124,
    )

    # Complete hexes, selected by the same pattern knob as scope
    hexes = HexesField(graph, midi.for_("hexes"), pattern=KB8)

    # Fire climbing from the bottom, as hard as its knob says. No pad: it
    # burns at whatever the knob is left at.
    fire = FireField(graph, midi.for_("fire"), rate=117)

    # Rotary
    rotary = RotaryField(graph, midi.for_("rotary"), period=KA5, parts=KA6, shape=KA7)

    # The same rotation, half a turn round. Not a second field: it shares
    # rotary's phase, so the two stay opposite whichever of them is in a slot.
    rotary180 = rotary.turned(0.5)

    v_rotary = RotaryField(
        graph, midi.for_("v_rotary"), period=KA5, parts=KA6, shape=KA7, vert=True
    )

    v_rotary180 = v_rotary.turned(0.5)

    # A sine over time with no shape to it, for making something breathe. Off
    # the desk, like loops - patch it in from the expression editor.
    lfo = LFOField(midi.for_("lfo"), rate=118)

    # The same cycle, read further round it - thirds and a half. Not LFOs of
    # their own: they share lfo's phase, so they keep their spacing whichever
    # of them is in a slot.
    lfo180 = lfo.turned(0.5)
    lfo120 = lfo.turned(1 / 3)
    lfo240 = lfo.turned(2 / 3)

    # Art-Net pixels, per universe: red, green, blue, and their average
    artnet0_r, artnet0_g, artnet0_b, artnet0_v = ARTNET[0]
    artnet1_r, artnet1_g, artnet1_b, artnet1_v = ARTNET[1]
    artnet2_r, artnet2_g, artnet2_b, artnet2_v = ARTNET[2]
    artnet3_r, artnet3_g, artnet3_b, artnet3_v = ARTNET[3]

    # Some number of edges from one family of lines - d1, d2 or h - re-picked
    # by the same pad that re-rolls random.
    random_lines = RandomLinesField(graph, midi.for_("random_lines"),
                                    note=PB6, count=119)

    v_edges = EdgeMaskField(V)
    h_edges = EdgeMaskField(H)
    d1_edges = EdgeMaskField(D1)
    d2_edges = EdgeMaskField(D2)

    strobe0 = StrobeField(midi.for_("strobe0"), strobe=PA1, attack=110, decay=111)
    strobe1 = StrobeField(midi.for_("strobe1"), strobe=PA2, attack=112, decay=113)
    strobe2 = StrobeField(midi.for_("strobe2"), strobe=PA3, attack=115, decay=116)

    v_gradient = VGradientField(midi.for_("v_gradient"), origin=KA6)

    burst = BurstField(graph, midi.for_("burst"), note=PB8, decay=KA7, attack=109)


class OPERATORS:
    """
    Long-lived, like the fields: one object per operator, shared by every
    operation that names it.
    """

    add = Math(operator.add, Arity.BINARY)
    sub = Math(operator.sub, Arity.BINARY)
    mul = Math(operator.mul, Arity.BINARY)
    div = Math(divide, Arity.BINARY)
    avg = Math(average, Arity.NARY)

    # One field out of several, picked by a knob - `select(ripple, wipe1, fire)`
    select = Select(midi.for_("select"), select=81)

    # The same, picked by the clock instead of by hand - `cycle(ripple, wipe1)`
    # alternates between them. The knob is how long one of them holds, 2s down
    # to 60ms, so adding another appends a turn rather than shortening the
    # others. CC 86.
    cycle = Cycle(midi.for_("cycle"), rate=86)

    # And picked at random, on PA6 - `randomize(ripple, wipe1, fire)` jumps to
    # one of them on every press and stays there. No knob: how often it changes
    # is whatever is playing the pad.
    randomize = Randomize(midi.for_("randomize"), note=PA6)

    # A gradient read at a field: `gradient_1_h(v_gradient)` is the hue of
    # gradient 1 at wherever up the lattice that field says, and the _s beside
    # it is the saturation of the same gradient at the same place. Unary - the
    # gradient is chosen on a knob, not written into the expression.
    #
    gradient_1_h = GradientChooser(True, midi.for_("gradient_1"), 82, GRADIENTS)
    gradient_1_s = GradientChooser(False, midi.for_("gradient_1"), 82, GRADIENTS)
    gradient_2_h = GradientChooser(True, midi.for_("gradient_2"), 83, GRADIENTS)
    gradient_2_s = GradientChooser(False, midi.for_("gradient_2"), 83, GRADIENTS)
    gradient_3_h = GradientChooser(True, midi.for_("gradient_3"), 84, GRADIENTS)
    gradient_3_s = GradientChooser(False, midi.for_("gradient_3"), 84, GRADIENTS)

    # The prob_zaps effect as a value: `prob_zap(fader_a)` flashes ends at the
    # rate that knob asks for, and whatever is reading it gets the flash.
    prob_zap = ProbZap(graph, midi.for_("prob_zap"), length=85)
    