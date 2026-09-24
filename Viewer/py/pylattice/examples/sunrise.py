from dataclasses import dataclass
from copy import deepcopy

from pylattice.format import STANDARD_MODULE
from pylattice.examples.colors import (
    hsv,
    vary,
    color_at,
    blend_paint,
    transition,
    ColorTransition,
    Keyframe,
    BLUE,
    ROSE,
    ORANGE,
    ROSY_WHITE,
    DEEP_ROSE,
    DEEP_ORANGE,
)
from pylattice import ModuleEdge, ModuleFrame, LatticeClient
from pylattice.lattice_client import fetch_lattice_shape
from pylattice.examples.tempo import Event

color_transitions = [
    ColorTransition(
        module_level=0,
        edges=[ModuleEdge.D1, ModuleEdge.E1, ModuleEdge.D2, ModuleEdge.E2],
        keyframes=[Keyframe(0, BLUE)],
    ),
    ColorTransition(
        module_level=0,
        ends=["bottom"],
        edges=[ModuleEdge.C1, ModuleEdge.C2],
        keyframes=[Keyframe(0, BLUE)],
    ),
    ColorTransition(
        module_level=0,
        ends=["top"],
        edges=[ModuleEdge.C1, ModuleEdge.C2],
        keyframes=[Keyframe(0, BLUE), Keyframe(0.5, ROSE), Keyframe(0.75, ORANGE)],
    ),
    ColorTransition(
        module_level=0,
        ends=["bottom"],
        edges=[ModuleEdge.A1, ModuleEdge.B1, ModuleEdge.A2, ModuleEdge.B2],
        keyframes=[Keyframe(0, BLUE), Keyframe(0.25, ROSE), Keyframe(0.75, ORANGE)],
    ),
    ColorTransition(
        module_level=0,
        ends=["top"],
        edges=[ModuleEdge.A1, ModuleEdge.B1, ModuleEdge.A2, ModuleEdge.B2],
        keyframes=[Keyframe(0, BLUE), Keyframe(0.25, ROSE)],
    ),
    ColorTransition(
        module_level=0,
        edges=[ModuleEdge.F1, ModuleEdge.F2],
        keyframes=[Keyframe(0, BLUE), Keyframe(0.5, ROSE)],
    ),
    ColorTransition(
        module_level=1,
        ends=["bottom"],
        edges=[ModuleEdge.D1, ModuleEdge.E1],
        keyframes=[
            Keyframe(0, BLUE),
            Keyframe(0.33, ROSY_WHITE, ease_in=0.13),
            Keyframe(0.45, [DEEP_ROSE, DEEP_ROSE, DEEP_ORANGE]),
            Keyframe(0.55, [DEEP_ROSE, DEEP_ORANGE]),
            Keyframe(0.9, ROSY_WHITE),
        ],
    ),
    ColorTransition(
        module_level=1,
        ends=["top"],
        edges=[ModuleEdge.D1, ModuleEdge.E1],
        keyframes=[
            Keyframe(0, BLUE),
            Keyframe(0.33, ROSY_WHITE, ease_in=0.13),
            Keyframe(0.45, [DEEP_ROSE, DEEP_ROSE, DEEP_ORANGE]),
            Keyframe(0.55, [DEEP_ROSE, DEEP_ORANGE]),
            Keyframe(0.9, BLUE),
        ],
    ),
    ColorTransition(
        module_level=1,
        edges=[ModuleEdge.D2, ModuleEdge.E2],
        keyframes=[
            Keyframe(0, BLUE),
            Keyframe(0.9, ROSY_WHITE, ease_in=0.7),
        ],
    ),
    ColorTransition(
        module_level=1,
        edges=[ModuleEdge.C1, ModuleEdge.C2],
        keyframes=[Keyframe(0, BLUE)],
    ),
    ColorTransition(
        module_level=1,
        edges=[ModuleEdge.A1, ModuleEdge.B1, ModuleEdge.A2, ModuleEdge.B2],
        keyframes=[Keyframe(0, BLUE)],
    ),
    ColorTransition(
        module_level=1,
        edges=[ModuleEdge.F1, ModuleEdge.F2],
        keyframes=[Keyframe(0, BLUE)],
    ),
]


@dataclass
class SunStage:
    level: int
    edges: list[ModuleEdge]


@dataclass
class Sun:
    start: float  # frac when the sun begins rising
    end: float  # frac when it's fully risen
    hue_range: tuple[float, float]
    hue_period: int  # ms
    value_range: tuple[float, float]
    value_period: int  # ms
    stages: list[SunStage]
    x: int  # which module the sun rises in


sun = Sun(
    start=0.33,
    end=0.9,
    hue_range=(0.015, 0.08),
    hue_period=500,
    value_range=(0.8, 1.0),
    value_period=700,
    stages=[
        SunStage(level=0, edges=[ModuleEdge.B1, ModuleEdge.A2]),
        SunStage(level=1, edges=[ModuleEdge.F1, ModuleEdge.F2]),
        SunStage(level=1, edges=[ModuleEdge.D2, ModuleEdge.E1]),
    ],
    x=1,
)


client = LatticeClient()


def sun_fiber_color(
    sun: Sun, now: Event, end_index: int, fiber: int
) -> tuple[float, float, float]:
    channel = end_index * 4 + fiber

    hue_offset = sun.hue_period * (channel / 8)
    h = vary(now, sun.hue_range[0], sun.hue_range[1], sun.hue_period, hue_offset)

    value_offset = sun.value_period * (channel / 8)
    v = vary(
        now, sun.value_range[0], sun.value_range[1], sun.value_period, value_offset
    )

    return hsv(h, 0.99, v)


def sun_on(sun: Sun, now: Event, frac: float, frames: dict[int, ModuleFrame]) -> None:
    if frac <= sun.start:
        return

    stage_span = (sun.end - sun.start) / len(sun.stages)
    for i, stage in enumerate(sun.stages):
        stage_start = sun.start + i * stage_span
        local = transition((frac - stage_start) / stage_span)
        frame = frames[stage.level]
        for edge in stage.edges:
            blend_paint(
                frame,
                edge,
                local,
                lambda end_index, f: sun_fiber_color(sun, now, end_index, f),
            )


def sunrise(color_transitions: list[ColorTransition], duration: int):
    shape = fetch_lattice_shape()
    if shape is None:
        raise RuntimeError("couldn't fetch lattice shape - is serve.py running?")

    level_frames = {level: ModuleFrame.blank() for level in range(shape["levels"])}

    start = Event.for_now()
    while True:
        now = Event.for_now()
        elapsed = now.when - start.when
        frac = elapsed / duration

        for group in color_transitions:
            level = group.module_level
            frame = level_frames[level]
            edges = group.edges
            group.keyframes.sort(key=lambda k: k.at)
            color = color_at(group.keyframes, frac)

            for edge in edges:
                e = frame[edge].ends
                for end in group.ends or ("top", "bottom"):
                    arr = getattr(e, end)
                    for f in range(4):
                        arr[f][:] = color[f]

        sun_frames = {level: deepcopy(frame) for level, frame in level_frames.items()}
        sun_on(sun, now, frac, sun_frames)

        for level, frame in level_frames.items():
            data = STANDARD_MODULE.serialize(frame)
            sun_data = STANDARD_MODULE.serialize(sun_frames[level])
            client.send(sun.x, level, sun_data)
            for x in range(shape["perRow"]):
                if x == sun.x:
                    continue
                client.send(x, level, data)

        if elapsed > duration:
            break


sunrise(color_transitions, duration=30000)
