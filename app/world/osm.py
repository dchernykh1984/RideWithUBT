"""Building a track network out of an OpenStreetMap extract.

The input is an Overpass response holding the raceway ways of one circuit, and a
recipe naming which way is the circuit proper and which are the alternative
sections that branch off it. Both are tracked in `build-data/`; the output is a
world description under `app/data/worlds`. Nothing is downloaded at build time,
so a build is reproducible and a change to the geometry is visible in a diff.

The junctions are not listed anywhere. They are found: a node that more than one
way passes through is a place where the rider has a choice, and the way named as
the circuit provides the default. That is what makes this a generator rather than
a transcription - the same code builds any circuit whose alternatives are drawn
as separate ways, which is how OpenStreetMap draws them.

Elevation is not in the extract, so every point comes out at zero. The format
carries it and the physics reads it; filling it in from a terrain model is a
separate change.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from itertools import pairwise
from pathlib import Path
from typing import Any

from app.world.geo import Origin
from app.world.network import (
    Junction,
    NetworkError,
    Point,
    Route,
    Segment,
    TrackNetwork,
)

MAIN_WAY_KEY = "main"


@dataclass(frozen=True)
class Way:
    """One OpenStreetMap way, with its nodes and their coordinates."""

    id: int
    nodes: tuple[int, ...]
    coordinates: tuple[tuple[float, float], ...]
    tags: dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if len(self.nodes) != len(self.coordinates):
            raise NetworkError(
                f"way {self.id} has nodes and geometry of different sizes"
            )
        if len(self.nodes) < 2:
            raise NetworkError(f"way {self.id} has fewer than two nodes")


@dataclass(frozen=True)
class RouteRecipe:
    """A named configuration, described by which alternatives it takes."""

    id: str
    name: str
    links: tuple[str, ...] = ()


@dataclass(frozen=True)
class Recipe:
    """How to turn one extract into one world."""

    id: str
    name: str
    main_way: int
    links: dict[str, int] = field(default_factory=dict)
    routes: tuple[RouteRecipe, ...] = ()
    width_m: float = 12.0
    surface: str = "asphalt"
    announce_m: float = 200.0
    start_node: int | None = None

    @property
    def ways(self) -> dict[str, int]:
        return {MAIN_WAY_KEY: self.main_way, **self.links}


def load_extract(path: Path) -> dict[int, Way]:
    """Read an Overpass JSON response into ways, keyed by id."""
    document = json.loads(path.read_text(encoding="utf-8"))
    ways = {}
    for element in document.get("elements", ()):
        if element.get("type") != "way" or "geometry" not in element:
            continue
        ways[element["id"]] = Way(
            id=element["id"],
            nodes=tuple(element["nodes"]),
            coordinates=tuple(
                (point["lat"], point["lon"]) for point in element["geometry"]
            ),
            tags=dict(element.get("tags", {})),
        )
    return ways


def load_recipe(path: Path) -> Recipe:
    raw = json.loads(path.read_text(encoding="utf-8"))
    return Recipe(
        id=str(raw["id"]),
        name=str(raw["name"]),
        main_way=int(raw["main_way"]),
        links={str(key): int(value) for key, value in raw.get("links", {}).items()},
        routes=tuple(
            RouteRecipe(
                id=str(item["id"]),
                name=str(item["name"]),
                links=tuple(str(link) for link in item.get("links", ())),
            )
            for item in raw.get("routes", ())
        ),
        width_m=float(raw.get("width_m", 12.0)),
        surface=str(raw.get("surface", "asphalt")),
        announce_m=float(raw.get("announce_m", 200.0)),
        start_node=int(raw["start_node"]) if "start_node" in raw else None,
    )


def node_id(osm_node: int) -> str:
    return f"n{osm_node}"


def split_nodes(ways: Sequence[Way], start_node: int) -> set[int]:
    """Every node where a segment has to begin or end.

    A node shared by two ways is a junction or a merge; a node a way returns to is
    a closed loop's seam. Both have to break the geometry, or a segment would run
    straight past a place the rider can leave from.
    """
    seen: dict[int, int] = {}
    for way in ways:
        for node in way.nodes:
            seen[node] = seen.get(node, 0) + 1
    return {node for node, count in seen.items() if count > 1} | {start_node}


def split_way(
    way: Way, key: str, breaks: Iterable[int], origin: Origin, recipe: Recipe
) -> list[Segment]:
    """Cut one way into segments at the given nodes."""
    at = set(breaks)
    cuts = [index for index, node in enumerate(way.nodes) if node in at]
    if not cuts or cuts[0] != 0:
        # A way always starts a segment, even one that joins nothing anywhere -
        # a stray way is a recipe mistake to report, not a crash to debug.
        cuts.insert(0, 0)
    if cuts[-1] != len(way.nodes) - 1:
        cuts.append(len(way.nodes) - 1)
    # The cut points come out of enumerate, so they are strictly increasing and
    # every pair spans at least one node.
    segments = []
    for number, (start, end) in enumerate(pairwise(cuts)):
        segments.append(
            Segment(
                id=f"{key}-{number}",
                start_node=node_id(way.nodes[start]),
                end_node=node_id(way.nodes[end]),
                points=tuple(
                    _point(origin, way.coordinates[index])
                    for index in range(start, end + 1)
                ),
                width_m=recipe.width_m,
                surface=way.tags.get("surface", recipe.surface),
            )
        )
    return segments


def _point(origin: Origin, coordinate: tuple[float, float]) -> Point:
    x, y = origin.to_local(*coordinate)
    # Elevation is not in the extract; the format carries it for when it is.
    return Point(x=x, y=y, z=0.0)


def _rotate_to_start(way: Way, start_node: int) -> Way:
    """Turn a closed way so it begins at the start node.

    A circuit's start and finish is where the rider begins, and a lap should be
    one segment run rather than a lap that wraps through the middle of one.
    """
    if way.nodes[0] == way.nodes[-1] and start_node in way.nodes:
        index = way.nodes.index(start_node)
        if index:
            ring = way.nodes[:-1]
            coordinates = way.coordinates[:-1]
            order = ring[index:] + ring[:index]
            points = coordinates[index:] + coordinates[:index]
            return Way(
                id=way.id,
                nodes=(*order, order[0]),
                coordinates=(*points, points[0]),
                tags=way.tags,
            )
    return way


def build(recipe: Recipe, ways: dict[int, Way]) -> TrackNetwork:
    """Turn an extract plus a recipe into a network, junctions and all."""
    selected = _select(recipe, ways)
    main = selected[MAIN_WAY_KEY]
    start = recipe.start_node if recipe.start_node is not None else main.nodes[0]
    selected[MAIN_WAY_KEY] = _rotate_to_start(main, start)
    origin = Origin(*selected[MAIN_WAY_KEY].coordinates[0])

    breaks = split_nodes(list(selected.values()), start)
    by_key = {
        key: split_way(way, key, breaks, origin, recipe)
        for key, way in selected.items()
    }
    segments = [segment for group in by_key.values() for segment in group]
    junctions = _junctions(segments, by_key[MAIN_WAY_KEY], recipe.announce_m)
    routes = _routes(recipe, by_key, junctions, start)
    return TrackNetwork(
        id=recipe.id,
        name=recipe.name,
        segments=tuple(segments),
        junctions=tuple(junctions),
        routes=tuple(routes),
    )


def _select(recipe: Recipe, ways: dict[int, Way]) -> dict[str, Way]:
    selected = {}
    for key, way_id in recipe.ways.items():
        if way_id not in ways:
            raise NetworkError(f"the extract has no way {way_id} (needed for {key!r})")
        selected[key] = ways[way_id]
    return selected


def _junctions(
    segments: Sequence[Segment], main: Sequence[Segment], announce_m: float
) -> list[Junction]:
    """Every node with more than one way out, defaulting to the circuit proper."""
    leaving: dict[str, list[str]] = {}
    for segment in segments:
        leaving.setdefault(segment.start_node, []).append(segment.id)
    on_main = {segment.id for segment in main}
    junctions = []
    for node, exits in sorted(leaving.items()):
        if len(exits) < 2:
            continue
        default = next((exit_id for exit_id in exits if exit_id in on_main), exits[0])
        junctions.append(
            Junction(
                node=node,
                exits=tuple(exits),
                default_exit=default,
                announce_m=announce_m,
            )
        )
    return junctions


def _routes(
    recipe: Recipe,
    by_key: dict[str, list[Segment]],
    junctions: Sequence[Junction],
    start_node: int,
) -> list[Route]:
    """One route per named configuration, as a set of choices at junctions."""
    start_segment = next(
        segment
        for segment in by_key[MAIN_WAY_KEY]
        if segment.start_node == node_id(start_node)
    )
    junction_nodes = {junction.node for junction in junctions}
    routes = []
    for wanted in recipe.routes:
        choices = {}
        for link in wanted.links:
            if link not in by_key:
                raise NetworkError(
                    f"route {wanted.id!r} takes {link!r}, "
                    "which the recipe does not name"
                )
            entry = by_key[link][0]
            if entry.start_node not in junction_nodes:
                raise NetworkError(
                    f"route {wanted.id!r} takes {link!r}, which does not branch off "
                    "anywhere the rider can choose"
                )
            choices[entry.start_node] = entry.id
        routes.append(
            Route(
                id=wanted.id,
                name=wanted.name,
                start_segment=start_segment.id,
                choices=choices,
            )
        )
    return routes


def build_from_files(recipe_path: Path, extract_path: Path) -> TrackNetwork:
    return build(load_recipe(recipe_path), load_extract(extract_path))


def describe_origin(recipe_path: Path, extract_path: Path) -> dict[str, Any]:
    """The world's origin on the globe, for anything that has to map back."""
    recipe = load_recipe(recipe_path)
    ways = load_extract(extract_path)
    main = ways[recipe.main_way]
    start = recipe.start_node if recipe.start_node is not None else main.nodes[0]
    rotated = _rotate_to_start(main, start)
    lat, lon = rotated.coordinates[0]
    return {"lat": lat, "lon": lon}
