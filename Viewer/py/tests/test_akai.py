"""The Akai's pads, knobs and faders arrive as the BSP controls they stand for."""

import mido

from pylattice.examples.midi import MIDI, Controller
from pylattice.instrument.akai import (
    AKAI_CC_VALUES, AKAI_CCS, AKAI_PADS,
    KA1, KA2, KA3, KA4, KA5, KA6, KA7, KA8, KB1, KB2, KB3, KB4, KB5, KB6, KB7, KB8,
    PA1, PA4, PA5, PA8, PB1, PB8,
)

AKAI = Controller(pads=AKAI_PADS, ccs=AKAI_CCS, values=AKAI_CC_VALUES)


class Port:
    """A MIDI input with some messages waiting on it."""

    def __init__(self, *msgs):
        self.msgs = list(msgs)

    def poll(self):
        return self.msgs.pop(0) if self.msgs else None


def cc(control, value=64):
    return mido.Message("control_change", control=control, value=value)


def note(n, type="note_on"):
    return mido.Message(type, note=n, velocity=100)


def test_every_bsp_pad_has_exactly_one_akai_note():
    assert sorted(AKAI_PADS.values()) == list(range(36, 52))


def test_every_bsp_control_has_exactly_one_akai_control_except_the_unused_two():
    # rotary.parts and rotary.shape do nothing, so the two BSP knobs they share
    # with v_gradient and burst are each mapped once, and nothing else is.
    knobs = [KA1, KA2, KA3, KA4, KA5, KA6, KA7, KA8,
             KB1, KB2, KB3, KB4, KB5, KB6, KB7, KB8]
    assert sorted(AKAI_CCS.values()) == sorted(knobs)


def test_a_pad_counts_as_its_bsp_pad():
    assert AKAI.translate(note(81)).note == PA1
    assert AKAI.translate(note(86)).note == PA4
    assert AKAI.translate(note(74, "note_off")).note == PB1
    assert AKAI.translate(note(72)).note == PB8


def test_translation_is_one_lookup_not_a_chain():
    # The Akai's 48-51 are the BSP's PA5-PA8, and its 67 is PB5 (40): what comes
    # out is not looked up again.
    assert AKAI.translate(note(48)).note == PA5
    assert AKAI.translate(note(51)).note == PA8
    assert AKAI.translate(note(67)).note == 40
    # Likewise the CCs: the Akai's 16 is burst.decay, the BSP's 16 is KB4.
    assert AKAI.translate(cc(16)).control == KA7
    assert AKAI.translate(cc(27)).control == KB4


def test_what_the_akai_does_not_map_is_dropped():
    assert AKAI.translate(note(60)) is None
    assert AKAI.translate(cc(20)) is None       # not a control we mapped
    assert AKAI.translate(cc(74)) is None       # a BSP number: not the Akai's


def test_a_program_change_means_the_same_everywhere():
    msg = mido.Message("program_change", program=5)

    assert AKAI.translate(msg) == msg


def test_the_scope_fader_is_cut_into_the_five_patterns():
    pattern = {v: AKAI.translate(cc(19, v)).value for v in range(128)}

    assert pattern[0] == 0 and pattern[127] == 4
    assert pattern[25] == 0 and pattern[26] == 1       # 128 / 5 = 25.6 a step
    assert set(pattern.values()) == {0, 1, 2, 3, 4}
    assert list(pattern.values()) == sorted(pattern.values())


def test_an_ordinary_control_keeps_its_value():
    assert AKAI.translate(cc(12, 99)).value == 99


def test_only_the_akais_port_is_translated():
    # Ableton's CC 16 is the BSP's KB4 and must stay so; the Akai's is KA7.
    midi = MIDI(None)
    midi._inputs = [(None, Port(cc(16, 10))), (AKAI, Port(cc(16, 20)))]

    midi.tick()

    ccs = midi.get_ccs_by_number()
    assert ccs[KB4].value == 10
    assert ccs[KA7].value == 20


def test_an_akai_pad_is_heard_by_the_bsp_pad():
    midi = MIDI(None)
    get = midi.note(PA1)
    midi._inputs = [(AKAI, Port(note(81)))]

    midi.tick()

    assert get()[0].data == 100
