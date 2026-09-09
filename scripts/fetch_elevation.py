#!/usr/bin/env python
"""Fetch the ground height of every node of a world's ways.

    uv run python scripts/fetch_elevation.py sokol

Writes `build-data/<id>/elevation.json`, which the generator reads. Like the
Overpass extract beside it, this is a deliberate step run by hand and the result
is tracked, so a build never touches the network.

The source is SRTM's 30 m dataset through the public Open Topo Data service. It
is free and rate limited - a hundred points a request, a request a second - so
this paces itself.
"""

from __future__ import annotations

import json
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

from app.world.osm import load_extract, load_recipe

BUILD_DATA = Path(__file__).parent.parent / "build-data"
SERVICE = "https://api.opentopodata.org/v1/srtm30m"
DATASET = "srtm30m"
BATCH = 100
PAUSE_S = 1.1
TIMEOUT_S = 60


def fetch(points: list[tuple[float, float]]) -> list[float]:
    locations = "|".join(f"{lat},{lon}" for lat, lon in points)
    url = f"{SERVICE}?{urllib.parse.urlencode({'locations': locations})}"
    with urllib.request.urlopen(url, timeout=TIMEOUT_S) as answer:  # noqa: S310
        body = json.load(answer)
    if body.get("status") != "OK":
        raise RuntimeError(f"elevation service said {body.get('status')!r}")
    return [float(item["elevation"]) for item in body["results"]]


def main(argv: list[str]) -> int:
    if len(argv) != 1:
        print(__doc__)
        return 2
    world_id = argv[0]
    directory = BUILD_DATA / world_id
    recipe = load_recipe(directory / "recipe.json")
    ways = load_extract(directory / "overpass.json")

    wanted: dict[int, tuple[float, float]] = {}
    for way_id in recipe.ways.values():
        way = ways[way_id]
        for node, coordinate in zip(way.nodes, way.coordinates, strict=True):
            wanted.setdefault(node, coordinate)

    nodes = list(wanted)
    heights: dict[str, float] = {}
    for start in range(0, len(nodes), BATCH):
        batch = nodes[start : start + BATCH]
        for node, height in zip(batch, fetch([wanted[n] for n in batch]), strict=True):
            heights[str(node)] = height
        print(f"{len(heights)}/{len(nodes)} nodes")
        if start + BATCH < len(nodes):
            time.sleep(PAUSE_S)

    path = directory / "elevation.json"
    path.write_text(
        json.dumps({"dataset": DATASET, "nodes": heights}, indent=1) + "\n",
        encoding="utf-8",
    )
    print(f"wrote {path}: {min(heights.values()):.0f}-{max(heights.values()):.0f} m")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
