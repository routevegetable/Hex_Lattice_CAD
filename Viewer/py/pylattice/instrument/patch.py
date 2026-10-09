"""Saving and restoring a patch: where the knobs are, and what drives what."""
import copy
import json
import operator
from dataclasses import dataclass, field
from pathlib import Path

from pylattice.examples.midi import MIDI
from pylattice.fields.types import CombinedField, ConstantField, ScalarField, average, divide
from pylattice.instrument.types import Effect

# What drives a slot, as JSON. A live field cannot be pickled - the MIDI-backed
# ones hold closures, and a copy would be detached from the desk anyway - so
# what gets written is how to find or rebuild it:
#
#   "rotary"                                  a field declared in FIELDS
#   0.25                                      a constant
#   {"op": "mul", "a": "ripple", "b": 0.5}    a combination, nested freely
FieldRef = str | float | dict

OPS = {"add": operator.add, "sub": operator.sub, "mul": operator.mul,
       "div": divide, "avg": average}
OP_NAMES = {op: name for name, op in OPS.items()}


def encode_field(field: ScalarField, names: dict[int, str]) -> FieldRef:
    """A field as JSON, given the names of the fields worth naming."""
    name = names.get(id(field))
    if name is not None:
        return name

    if isinstance(field, ConstantField):
        return field.value

    if isinstance(field, CombinedField) and field.op in OP_NAMES:
        return {
            "op": OP_NAMES[field.op],
            "a": encode_field(field.a, names),
            "b": encode_field(field.b, names),
        }

    raise ValueError(f"cannot write down a {type(field).__name__} that has no name")


def decode_field(ref: FieldRef, by_name: dict[str, ScalarField]) -> ScalarField:
    """The inverse: look the name up, or build what it describes."""
    if isinstance(ref, str):
        if ref not in by_name:
            raise ValueError(f"no field {ref!r}")
        return by_name[ref]

    if isinstance(ref, (int, float)):
        return ConstantField(ref)

    if isinstance(ref, dict):
        if ref.get("op") not in OPS:
            raise ValueError(f"no operator {ref.get('op')!r} - try {', '.join(OPS)}")
        return CombinedField(OPS[ref["op"]],
                             decode_field(ref["a"], by_name),
                             decode_field(ref["b"], by_name))

    raise ValueError(f"cannot read a field from {ref!r}")


def named(namespace: type, kind: type) -> dict[str, object]:
    """The `kind` things declared in a class body, in the order written."""
    return {name: value for name, value in vars(namespace).items()
            if isinstance(value, kind)}


@dataclass
class Patch:
    """Every setting there is: where the knobs are, and what drives what.

        Patch.capture(midi, FIELDS, EFFECTS).save("preset.json")
        Patch.load("preset.json").apply(midi, FIELDS, EFFECTS)
    """

    # CC number -> value
    ccs: dict[int, int]

    # effect.slot -> what drives it
    slots: dict[str, FieldRef]

    # Whether this has drifted from what is on disk. The bank fills it in when
    # it hands a preset out; `compare=False` keeps it out of equality, which is
    # what the bank works dirtiness out with in the first place.
    dirty: bool = field(default=False, compare=False)

    @classmethod
    def capture(cls, midi: MIDI, fields: type, effects: type) -> "Patch":
        """Read the current patch off the live objects."""
        field_names = {id(field): name for name, field in named(fields, ScalarField).items()}

        slots = {}
        for effect_name, effect in named(effects, Effect).items():
            for slot_name, slot in effect.get_slots().items():
                if slot.field is None:
                    continue                # nothing plugged in
                # A combination or a constant is written out as how to rebuild
                # it; anything else unnamed cannot be, and is left out.
                try:
                    slots[f"{effect_name}.{slot_name}"] = encode_field(slot.field, field_names)
                except ValueError:
                    pass

        # get_ccs hands back the controls themselves; a preset only wants
        # where each one is sitting - and only for controls the instrument
        # actually watches. Anything else that turned up on the wire (a bank
        # select, an all-notes-off) is not a setting of ours.
        return cls(ccs={control: state.value
                        for control, state in midi.get_ccs().items() if state.watched},
                   slots=slots)

    def apply(self, midi: MIDI, fields: type, effects: type, whole: bool = True):
        """Put the knobs back and re-patch the slots.

        With `whole`, the patch is the entire picture: a slot it does not
        mention ends up with nothing in it, rather than keeping whatever the
        patch before left there. That is what makes an empty patch mean
        something - it is a blank rig, and reverting to one clears it.

        Without it, the patch is a set of changes and everything it says
        nothing about is left alone - which is what editing one slot from the
        UI wants, since it sends only the slot it touched.
        """
        for control, value in self.ccs.items():
            midi.set_cc(control, value)

        by_name = named(fields, ScalarField)
        by_effect = named(effects, Effect)

        # Work the whole thing out before changing anything, so a patch naming
        # a field that has gone fails without half-applying.
        wanted: dict[str, dict[str, ScalarField]] = {}
        for target, ref in self.slots.items():
            effect_name, _, slot_name = target.partition(".")

            if effect_name not in by_effect:
                # A preset outlives the code it was written against. An effect
                # that has since gone is not a reason to drop everything else
                # the preset says - leave that slot out and carry on.
                print(f"{target}: no effect {effect_name!r}, skipped")
                continue

            if slot_name not in by_effect[effect_name].get_slots():
                print(f"{target}: {effect_name!r} has no slot {slot_name!r}, skipped")
                continue

            try:
                field = decode_field(ref, by_name)
            except ValueError as e:
                raise ValueError(f"{target}: {e}") from None

            wanted.setdefault(effect_name, {})[slot_name] = field

        for effect_name, effect in by_effect.items():
            mine = wanted.get(effect_name, {})

            if whole:
                for slot_name, slot in effect.get_slots().items():
                    if slot_name not in mine:
                        slot.clear()

            if mine:
                effect.bind(**mine)

    def copy(self) -> "Patch":
        """An independent copy. The slot refs nest, so they go deep - two
        patches must never share a dict, or editing one edits the other."""
        return Patch(ccs=dict(self.ccs), slots=copy.deepcopy(self.slots))

    def save(self, path: str):
        Path(path).write_text(json.dumps({"ccs": self.ccs, "slots": self.slots}, indent=2))

    @classmethod
    def load(cls, path: str) -> "Patch":
        saved = json.loads(Path(path).read_text())
        # JSON keys are strings; CC numbers are not.
        return cls(ccs={int(cc): v for cc, v in saved["ccs"].items()},
                   slots=saved["slots"])


@dataclass
class PresetBank:
    """A fixed set of preset slots, one file each, under `directory`.

    Every preset is held in memory as well as on disk. The cached copy is the
    live one - the instrument renders from the cached patch of whatever is
    selected - so turning a knob makes that entry drift from its file, and
    that drift is what `dirty` means. Saving writes the cache out; reverting
    throws it away and reads the file back.
    """

    directory: Path
    size: int = 16

    def __post_init__(self):
        self.directory = Path(self.directory)
        self.directory.mkdir(parents=True, exist_ok=True)

        # number -> the patch as it is now, and as it is on disk. Two copies,
        # never the same object, so comparing them means something.
        self._cache: dict[int, Patch] = {}
        self._stored: dict[int, Patch] = {}
        self.reload()

    # -- the files --------------------------------------------------------

    def path(self, number: int) -> Path:
        self.check(number)
        return self.directory / f"{number:02d}.json"

    def check(self, number: int):
        if not 0 <= number < self.size:
            raise ValueError(f"preset {number} is outside 0-{self.size - 1}")

    def exists(self, number: int) -> bool:
        return self.path(number).exists()

    def saved(self) -> list[int]:
        """Which slots have a file."""
        return [n for n in range(self.size) if self.exists(n)]

    def reload(self):
        """Fill the cache from storage.

        Every slot gets a patch, file or no file - an unwritten one is a patch
        that says nothing, which applies cleanly and changes nothing. There is
        no such thing as an empty preset to guard against.
        """
        self._cache, self._stored = {}, {}

        for number in range(self.size):
            stored = self._from_storage(number)
            self._stored[number] = stored
            self._cache[number] = stored.copy()

    def _from_storage(self, number: int) -> Patch:
        """A preset's file, or a patch that does nothing if it has none."""
        if not self.exists(number):
            return Patch(ccs={}, slots={})

        return Patch.load(self.path(number))

    # -- the cache --------------------------------------------------------

    def get_all(self) -> dict[int, Patch]:
        """Every preset the bank holds, copied - reading cannot disturb what
        the instrument is rendering - and each one told whether it is dirty."""
        return {number: self._handed_out(number) for number in self._cache}

    def _handed_out(self, number: int) -> Patch:
        """A copy of a cached preset, carrying its dirty flag."""
        patch = self._cache[number].copy()
        patch.dirty = self.dirty(number)
        return patch

    def read(self, number: int) -> Patch:
        """A preset as it stands, edits included."""
        self.check(number)
        return self._handed_out(number)

    def put(self, number: int, patch: Patch):
        """Hold a patch as a preset's current state. Dirty from here if it
        differs from the file."""
        self.check(number)
        self._cache[number] = patch.copy()

    def dirty(self, number: int) -> bool:
        """Whether a preset has drifted from its file."""
        self.check(number)
        return self._cache[number] != self._stored[number]

    def dirty_presets(self) -> list[int]:
        return [number for number in sorted(self._cache) if self.dirty(number)]

    def save(self, number: int):
        """Write a preset's cached patch out. It stops being dirty."""
        self.check(number)
        patch = self._cache[number]

        patch.save(self.path(number))
        self._stored[number] = patch.copy()

    def revert(self, number: int) -> Patch:
        """Throw a preset's edits away and read its file back - or empty it,
        if it has never been written."""
        self.check(number)

        stored = self._from_storage(number)
        self._stored[number] = stored
        self._cache[number] = stored.copy()

        return self._handed_out(number)

    def write(self, number: int, preset: Patch):
        """Put a patch in and save it in one go."""
        self.put(number, preset)
        self.save(number)
