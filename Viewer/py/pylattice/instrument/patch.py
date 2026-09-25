"""Saving and restoring a patch: where the knobs are, and what drives what."""
import json
import operator
from dataclasses import dataclass
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

        return cls(ccs=midi.get_ccs(), slots=slots)

    def apply(self, midi: MIDI, fields: type, effects: type):
        """Put the knobs back and re-patch the slots."""
        for control, value in self.ccs.items():
            midi.set_cc(control, value)

        by_name = named(fields, ScalarField)
        by_effect = named(effects, Effect)

        for target, ref in self.slots.items():
            effect_name, _, slot_name = target.partition(".")

            if effect_name not in by_effect:
                raise ValueError(f"{target}: no effect {effect_name!r}")

            try:
                field = decode_field(ref, by_name)
            except ValueError as e:
                raise ValueError(f"{target}: {e}") from None

            by_effect[effect_name].bind(**{slot_name: field})

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
    """A fixed set of preset slots, one file each, under `directory`."""

    directory: Path
    size: int = 16

    def __post_init__(self):
        self.directory = Path(self.directory)
        self.directory.mkdir(parents=True, exist_ok=True)

    def path(self, number: int) -> Path:
        self.check(number)
        return self.directory / f"{number:02d}.json"

    def check(self, number: int):
        if not 0 <= number < self.size:
            raise ValueError(f"preset {number} is outside 0-{self.size - 1}")

    def exists(self, number: int) -> bool:
        return self.path(number).exists()

    def read(self, number: int) -> Patch:
        path = self.path(number)
        if not path.exists():
            raise FileNotFoundError(f"preset {number} has not been saved")
        return Patch.load(path)

    def write(self, number: int, preset: Patch):
        preset.save(self.path(number))

    def saved(self) -> list[int]:
        """Which slots have a file."""
        return [n for n in range(self.size) if self.exists(n)]
