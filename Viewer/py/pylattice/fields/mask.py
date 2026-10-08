"""Which edges count: a field that is 1 on the edge classes it names."""

from pylattice.examples.tempo import Event
from pylattice.fields.types import ScalarField
from pylattice.graph import EdgeClass, EndRef


class EdgeMaskField(ScalarField):
    def __init__(self, edges: set[EdgeClass]):
        self._edges = edges

    def get(self, now: Event, end: EndRef) -> float:

        return 1 if end.edge_class in self._edges else 0
