from dataclasses import dataclass
from enum import IntEnum
import math
from .frame import RGB, EndFrame, ModuleEdge, ModuleFrame
from .graph import EdgeClass


@dataclass
class ChannelData:
    data: list[RGB]



@dataclass
class FrameFormat:
    channel_edges: dict[int, list[tuple[ModuleEdge, bool]]]
    flip_order: tuple[int, int, int, int]

    def _ser_end(self, e: EndFrame, out: ChannelData, flip: bool) -> None:
        # `flip` swaps each adjacent pair (0<->1, 2<->3) — the strip runs down
        # one end and back up the other, wiring the latter end in swapped pairs.
        for j in range(4):
            px = e[self.flip_order[j] if flip else j]
            out.data.append(px)

    def serialize(self, frame: ModuleFrame) -> list[ChannelData]:
        """
        Write out a ModuleFrame to ChannelData
        """
        out: list[ChannelData] = []

        for ch in range(ModuleFrame.CHANNELS):

            # Serialize these edges
            edges = self.channel_edges[ch]

            # This many pixels
            channel_len = len(edges) * ModuleFrame.PIXELS_PER_EDGE

            channel = ChannelData(data=[])

            for edge, points_up in edges:
                e = frame[edge]
                if points_up:
                    self._ser_end(e.ends.bottom, channel, False)
                    self._ser_end(e.ends.top, channel, True)
                else:
                    self._ser_end(e.ends.top, channel, False)
                    self._ser_end(e.ends.bottom, channel, True)

            out.append(channel)

        return out

    def _deser_end(self, e: EndFrame, channel: ChannelData, o: int, flip: bool) -> int:
        # `flip` swaps each adjacent pair to match _ser_end.
        for j in range(4):
            # Each LED
            i = self.flip_order[j] if flip else j
            e[i] = channel.data[o]
            o += 1
        return o

    def deserialize(self, channels: list[ChannelData], frame: ModuleFrame):
        """Inverse of serialize: parse `data` back into this frame, in place."""

        assert len(channels) == ModuleFrame.CHANNELS

        o = 0
        for ch in range(ModuleFrame.CHANNELS):
            channel = channels[ch]
            for edge, points_up in self.channel_edges[ch]:
                e = frame[edge]
                if points_up:
                    o = self._deser_end(e.ends.bottom, channel, o, False)
                    o = self._deser_end(e.ends.top, channel, o, True)
                else:
                    o = self._deser_end(e.ends.top, channel, o, False)
                    o = self._deser_end(e.ends.bottom, channel, o, True)


STANDARD_MODULE = FrameFormat(
    channel_edges = {
        0: [(ModuleEdge.D1, True), (ModuleEdge.C1, True), (ModuleEdge.A1, True),
            (ModuleEdge.B1, False), (ModuleEdge.E2, True)],
        1: [(ModuleEdge.E1, True), (ModuleEdge.C2, True), (ModuleEdge.A2, True),
            (ModuleEdge.B2, False)],
        2: [(ModuleEdge.D2, False), (ModuleEdge.F2, False)],
        3: [(ModuleEdge.F1, False)],
    },

    flip_order = (1, 0, 3, 2)
)

WEIRD_TUBE = FrameFormat(
    channel_edges = {
        0: [(ModuleEdge.D1, True), (ModuleEdge.C1, True), (ModuleEdge.A1, True),
            (ModuleEdge.B1, False), (ModuleEdge.E2, True)],
        1: [(ModuleEdge.E1, True), (ModuleEdge.C2, True), (ModuleEdge.A2, True),
            (ModuleEdge.B2, False)],
        2: [(ModuleEdge.D2, False), (ModuleEdge.F2, False)],
        3: [(ModuleEdge.F1, False)],
    },

    flip_order = (3,1, 2,0)
)