#!/usr/bin/env python3
"""One-time offline extraction of a 2D node-shape outline from the hinge tube
geometry in `Hinge Hexagon.obj`, for lite2d.html's Phase 1 (see
../LITE2D_PLAN.md). Not part of the runtime app — run once, paste the output.

The OBJ has 6 "g Small-Small Tube" groups (the 6 tube instances per segment,
same ones index.html/lite.html find via `/tube/i.test(name)` in the GLTF
path). Two are vertical (hinge pin C, leg F); we pick C — the leftmost/lower
mean-X one, per lite.html's `prepFilaments()` comment "the leftmost tube is
concentric with the left hinge" — since the node markers in the 2D viewer
represent hinge joints. Vertices are projected to (X, Z) — dropping Y depth,
per MEASUREMENTS.md's axis convention — then reduced to a convex hull and
normalized to a small origin-centered, unit-scaled outline.

The pin is a plain, axis-aligned cylinder (confirmed by inspecting its vertex
cloud: circular cross-section, flat end caps), so the outline comes out as a
simple long capsule/rectangle — that's a faithful face-on silhouette of the
real geometry, not an extraction bug.
"""
import sys
from pathlib import Path

OBJ_PATH = Path(__file__).parent / "Hinge Hexagon.obj"
GROUP_NAME = "Small-Small Tube"


def parse_tube_groups(path):
    """Return a list of vertex lists, one per contiguous 'g Small-Small Tube' block."""
    groups = []
    current = None
    with open(path) as f:
        for line in f:
            if line.startswith("g "):
                name = line[2:].strip()
                current = [] if name == GROUP_NAME else None
                if current is not None:
                    groups.append(current)
            elif line.startswith("v ") and current is not None:
                _, x, y, z = line.split()[:4]
                current.append((float(x), float(y), float(z)))
    return groups


def bbox(points, axis):
    vals = [p[axis] for p in points]
    return min(vals), max(vals)


def classify_and_pick_hinge_pin(groups):
    """Of the 6 tube groups, return the vertices for the hinge-pin tube (C):
    the vertical one (Z range dominates X/Y range) with the smaller mean X."""
    verticals = []
    for pts in groups:
        (x0, x1) = bbox(pts, 0)
        (z0, z1) = bbox(pts, 2)
        rx, rz = x1 - x0, z1 - z0
        if rz > 2 * rx:  # vertical: same test lite.html's prepFilaments() uses
            mean_x = sum(p[0] for p in pts) / len(pts)
            verticals.append((mean_x, pts))
    if len(verticals) != 2:
        print(f"warning: expected 2 vertical tubes, found {len(verticals)}", file=sys.stderr)
    verticals.sort(key=lambda t: t[0])
    return verticals[0][1]  # smaller mean X = leftmost = hinge pin (C)


def project_xz(points):
    """Drop Y (depth) -> face-on (X, Z) view, per MEASUREMENTS.md axis convention."""
    return [(x, z) for (x, y, z) in points]


def convex_hull(points):
    """Andrew's monotone chain, stdlib only. Returns hull points, CCW, no repeat."""
    pts = sorted(set(points))
    if len(pts) <= 2:
        return pts

    def cross(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])

    lower = []
    for p in pts:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], p) <= 0:
            lower.pop()
        lower.append(p)
    upper = []
    for p in reversed(pts):
        while len(upper) >= 2 and cross(upper[-2], upper[-1], p) <= 0:
            upper.pop()
        upper.append(p)
    return lower[:-1] + upper[:-1]


def normalize(points):
    """Center on the bbox center, scale so the longest half-extent is 1.0."""
    xs = [p[0] for p in points]
    zs = [p[1] for p in points]
    cx, cz = (min(xs) + max(xs)) / 2, (min(zs) + max(zs)) / 2
    half = max(max(xs) - cx, max(zs) - cz, cx - min(xs), cz - min(zs))
    return [((x - cx) / half, (z - cz) / half) for (x, z) in points]


def to_svg_path(points):
    parts = [f"M {points[0][0]:.4f},{points[0][1]:.4f}"]
    parts += [f"L {x:.4f},{z:.4f}" for (x, z) in points[1:]]
    parts.append("Z")
    return " ".join(parts)


def to_js_array(points):
    inner = ", ".join(f"[{x:.4f},{z:.4f}]" for (x, z) in points)
    return f"[{inner}]"


def main():
    groups = parse_tube_groups(OBJ_PATH)
    print(f"found {len(groups)} '{GROUP_NAME}' groups", file=sys.stderr)
    pin_verts = classify_and_pick_hinge_pin(groups)
    print(f"hinge pin tube: {len(pin_verts)} vertices", file=sys.stderr)

    flat = project_xz(pin_verts)
    hull = convex_hull(flat)
    outline = normalize(hull)
    print(f"hull: {len(outline)} points (from {len(flat)} projected verts)", file=sys.stderr)

    print("\n-- SVG path (paste as NODE_SHAPE_PATH) --")
    print(to_svg_path(outline))
    print("\n-- JS point array (alternative form) --")
    print(to_js_array(outline))


if __name__ == "__main__":
    main()
