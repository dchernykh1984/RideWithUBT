#!/usr/bin/env python
"""Build a world description from its tracked inputs.

    uv run python scripts/build_world.py sokol

Reads `build-data/<id>/recipe.json` and `build-data/<id>/overpass.json`, and
writes `app/data/worlds/<id>.json`. Nothing is downloaded: refreshing an extract
is a separate, deliberate step documented in `build-data/README.md`.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from app.world.description import describe, world_path
from app.world.navigation import lap_length_m
from app.world.osm import build_from_files

BUILD_DATA = Path(__file__).parent.parent / "build-data"


def main(argv: list[str]) -> int:
    if len(argv) != 1:
        print(__doc__)
        return 2
    world_id = argv[0]
    directory = BUILD_DATA / world_id
    network = build_from_files(
        directory / "recipe.json",
        directory / "overpass.json",
        directory / "elevation.json",
        directory / "buildings.json",
    )
    output = world_path(world_id)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(describe(network), indent=1) + "\n", encoding="utf-8")
    print(
        f"wrote {output} - {len(network.segments)} segments, "
        f"{len(network.junctions)} junctions, {len(network.routes)} routes, "
        f"{len(network.buildings)} buildings"
    )
    for route in network.routes:
        print(f"  {route.id:24} {lap_length_m(network, route) / 1000:.3f} km")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
