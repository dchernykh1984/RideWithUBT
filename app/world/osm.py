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
import math
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field, replace
from itertools import pairwise
from pathlib import Path
from typing import Any

from app.world import elevation, smooth
from app.world.buildings import Building, height_for, kind_of
from app.world.geo import Origin
from app.world.network import (
    Junction,
    NetworkError,
    Point,
    Route,
    Segment,
    Start,
    TrackNetwork,
)
from app.world.offset import (
    TAPER_STEP_M,
    densify,
    offset_varying,
    ramps,
)
from app.world.smooth import smooth_polyline

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
class PitLane:
    """A lane alongside the circuit, built rather than traced.

    OpenStreetMap has the racing surface of most circuits and the pit lane beside
    it far less often. Where it is missing, offsetting the circuit's own points
    gives a lane that is exactly parallel to the track - which is what a pit lane
    is - and puts the entry and the rejoin on real nodes, so they become a
    junction and a merge like any other.

    ``entry_node`` and ``exit_node`` are OpenStreetMap node ids on the circuit.
    ``offset_m`` is metres to the left of the direction of travel, so a negative
    value puts the lane on the inside of a clockwise circuit.
    """

    entry_node: int
    exit_node: int
    offset_m: float
    id: str = "pit-lane"
    width_m: float = 8.0
    surface: str = "asphalt"
    #: How far the lane takes to leave the track and to come back to it. Without
    #: this the lane runs alongside at full offset and then stops in the grass.
    taper_m: float = 60.0


@dataclass(frozen=True)
class StartOn:
    """Where a ride begins, as a person would say it: on the pit lane, halfway.

    A fraction rather than a distance, because the length of a lane is a thing
    the build works out and a person writing this file should not have to.
    """

    key: str
    fraction: float = 0.0


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
    #: How much track the ground profile is averaged over. It is a property of
    #: the elevation model, not of the terrain: a coarse one needs a wide window
    #: to keep its rounding from becoming hills, a better one needs less.
    elevation_window_m: float = elevation.DEFAULT_WINDOW_M
    start_node: int | None = None
    pit_lane: PitLane | None = None
    #: How finely the road is rebuilt as a curve through the surveyed points.
    curve_spacing_m: float = smooth.DEFAULT_SPACING_M
    #: How tall each kind of building stands in this world. Open data has the
    #: footprints and hardly ever the heights, so they are stated here.
    building_heights: dict[str, float] = field(default_factory=dict)
    #: Where a ride begins: a named group of segments, and how far along it. At
    #: an autodrome that is the pit lane, because that is where a session
    #: starts - not the first node the survey happened to record.
    start_on: StartOn | None = None

    @property
    def ways(self) -> dict[str, int]:
        return {MAIN_WAY_KEY: self.main_way, **self.links}


def load_buildings(
    path: Path,
    origin: Origin,
    heights: dict[str, float] | None = None,
    ground_m: float = 0.0,
) -> tuple[Building, ...]:
    """Read surveyed footprints into buildings standing on the ground.

    Height is the one thing open data almost never has, so it comes from the
    recipe by kind. Everything else - where it stands, what shape it is - is
    the survey's, which is the whole point of using it rather than inventing
    scenery.
    """
    document = json.loads(path.read_text(encoding="utf-8"))
    built = []
    for element in document.get("elements", ()):
        geometry = element.get("geometry") or ()
        if len(geometry) < 3:
            continue  # a line or a point is not a building
        kind = kind_of(element.get("tags", {}))
        built.append(
            Building(
                id=str(element["id"]),
                kind=kind,
                footprint=tuple(
                    _point(origin, (node["lat"], node["lon"]), ground_m)
                    for node in geometry
                ),
                height_m=height_for(kind, heights),
            )
        )
    return tuple(built)


def load_heights(path: Path) -> dict[int, float]:
    """Read the sampled ground height of each node, as the fetch script wrote it."""
    document = json.loads(path.read_text(encoding="utf-8"))
    return {int(node): float(height) for node, height in document["nodes"].items()}


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
        elevation_window_m=float(
            raw.get("elevation_window_m", elevation.DEFAULT_WINDOW_M)
        ),
        curve_spacing_m=float(raw.get("curve_spacing_m", smooth.DEFAULT_SPACING_M)),
        building_heights={
            str(kind): float(height)
            for kind, height in raw.get("building_heights", {}).items()
        },
        start_node=int(raw["start_node"]) if "start_node" in raw else None,
        pit_lane=_parse_pit_lane(raw.get("pit_lane")),
        start_on=_parse_start_on(raw.get("start_on")),
    )


def _parse_start_on(raw: dict[str, Any] | None) -> StartOn | None:
    if raw is None:
        return None
    return StartOn(
        key=str(raw["key"]),
        fraction=float(raw.get("fraction", 0.0)),
    )


def _parse_pit_lane(raw: dict[str, Any] | None) -> PitLane | None:
    if raw is None:
        return None
    return PitLane(
        entry_node=int(raw["entry_node"]),
        exit_node=int(raw["exit_node"]),
        offset_m=float(raw["offset_m"]),
        id=str(raw.get("id", "pit-lane")),
        width_m=float(raw.get("width_m", 8.0)),
        surface=str(raw.get("surface", "asphalt")),
        taper_m=float(raw.get("taper_m", 60.0)),
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
    way: Way,
    key: str,
    breaks: Iterable[int],
    origin: Origin,
    recipe: Recipe,
    heights: dict[int, float] | None = None,
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
                # Through a curve, not between the surveyed points: joining
                # them with straight lines makes a corner out of flats meeting
                # at angles, and the rider's heading really does snap round at
                # each one.
                points=smooth_polyline(
                    [
                        _point(
                            origin,
                            way.coordinates[index],
                            (heights or {}).get(way.nodes[index], 0.0),
                        )
                        for index in range(start, end + 1)
                    ],
                    recipe.curve_spacing_m,
                ),
                width_m=recipe.width_m,
                surface=way.tags.get("surface", recipe.surface),
            )
        )
    return segments


def _point(
    origin: Origin, coordinate: tuple[float, float], height: float = 0.0
) -> Point:
    x, y = origin.to_local(*coordinate)
    return Point(x=x, y=y, z=height)


def way_distances(way: Way, origin: Origin) -> list[float]:
    """How far along the way each of its nodes is."""
    points = [origin.to_local(*coordinate) for coordinate in way.coordinates]
    distances = [0.0]
    for before, after in pairwise(points):
        distances.append(distances[-1] + math.dist(before, after))
    return distances


def smoothed_heights(
    selected: dict[str, Way], raw: dict[int, float], origin: Origin, window_m: float
) -> dict[int, float]:
    """A rideable ground profile for every node of every way.

    The circuit is smoothed as the loop it is, so the profile joins across the
    start line. Each branch is smoothed on its own and then tilted to meet the
    circuit at both ends, which keeps its own shape without leaving a step at the
    junction it leaves from.
    """
    main = selected[MAIN_WAY_KEY]
    heights = dict(
        zip(
            main.nodes,
            elevation.smooth(
                way_distances(main, origin),
                [raw.get(node, 0.0) for node in main.nodes],
                window_m=window_m,
                closed=main.nodes[0] == main.nodes[-1],
            ),
            strict=True,
        )
    )
    for key, way in selected.items():
        if key == MAIN_WAY_KEY:
            continue
        smoothed = elevation.smooth(
            way_distances(way, origin),
            [raw.get(node, 0.0) for node in way.nodes],
            window_m=window_m,
        )
        joined = elevation.levelled(
            smoothed,
            start=heights.get(way.nodes[0], smoothed[0]),
            end=heights.get(way.nodes[-1], smoothed[-1]),
        )
        for node, height in zip(way.nodes, joined, strict=True):
            heights.setdefault(node, height)
    return heights


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


def span(way: Way, from_node: int, to_node: int) -> list[int]:
    """The indices of the way's nodes from one to another, in travel order.

    A closed way is a ring, so a span may run off the end and round to the front;
    an open one may not.
    """
    for node in (from_node, to_node):
        if node not in way.nodes:
            raise NetworkError(f"node {node} is not on way {way.id}")
    start = way.nodes.index(from_node)
    end = way.nodes.index(to_node)
    if start < end:
        return list(range(start, end + 1))
    closed = way.nodes[0] == way.nodes[-1]
    if not closed:
        raise NetworkError(
            f"way {way.id} does not run from node {from_node} to node {to_node}"
        )
    ring = len(way.nodes) - 1
    return [index % ring for index in range(start, end + ring + 1)]


def build_pit_lane(
    pit: PitLane,
    main: Way,
    origin: Origin,
    heights: dict[int, float] | None = None,
    track_width_m: float = 12.0,
) -> Segment:
    """A lane beside the circuit, between two of its nodes.

    It leaves the track from its kerb and comes back to it there: the inner
    edge starts on the edge of the racing surface and swings out, and the outer
    edge follows it a lane's width further. At the two ends the lane has no
    width at all, which is what a merge looks like.

    Built from its two edges rather than from a centre line and a width. A lane
    tapered by moving its centre line runs *across* the track for as long as
    the two overlap - its own painted edges drawn over the racing surface - and
    leaves a wedge of grass where the two part company. Both were on screen.

    It follows the circuit's own ground, because it runs beside it.
    """
    indices = span(main, pit.entry_node, pit.exit_node)
    along = densify(
        [
            _point(
                origin,
                main.coordinates[index],
                (heights or {}).get(main.nodes[index], 0.0),
            )
            for index in indices
        ],
        TAPER_STEP_M,
    )
    # The lane's centre still reaches the node it is joined to - a rider comes
    # off it onto the circuit and must not step sideways to do so - but its
    # width eases from nothing, so at the merge there is no lane to paint
    # across the racing surface.
    _ = track_width_m
    return Segment(
        id=f"{pit.id}-0",
        start_node=node_id(pit.entry_node),
        end_node=node_id(pit.exit_node),
        points=offset_varying(along, ramps(along, pit.taper_m, pit.offset_m)),
        width_m=pit.width_m,
        width_profile=ramps(along, pit.taper_m, pit.width_m),
        surface=pit.surface,
    )


def build(
    recipe: Recipe,
    ways: dict[int, Way],
    raw_heights: dict[int, float] | None = None,
) -> TrackNetwork:
    """Turn an extract plus a recipe into a network, junctions and all."""
    selected = _select(recipe, ways)
    main = selected[MAIN_WAY_KEY]
    start = recipe.start_node if recipe.start_node is not None else main.nodes[0]
    selected[MAIN_WAY_KEY] = _rotate_to_start(main, start)
    origin = Origin(*selected[MAIN_WAY_KEY].coordinates[0])

    heights = (
        smoothed_heights(selected, raw_heights, origin, recipe.elevation_window_m)
        if raw_heights
        else {}
    )

    breaks = split_nodes(list(selected.values()), start)
    if recipe.pit_lane is not None:
        # The lane's ends have to break the circuit too, or the rider would be
        # carried straight past the place they can turn into it.
        breaks |= {recipe.pit_lane.entry_node, recipe.pit_lane.exit_node}
    by_key = {
        key: split_way(way, key, breaks, origin, recipe, heights)
        for key, way in selected.items()
    }
    if recipe.pit_lane is not None:
        by_key[recipe.pit_lane.id] = [
            build_pit_lane(
                recipe.pit_lane,
                selected[MAIN_WAY_KEY],
                origin,
                heights,
                recipe.width_m,
            )
        ]
    segments = [segment for group in by_key.values() for segment in group]
    junctions = _junctions(segments, by_key[MAIN_WAY_KEY], recipe.announce_m)
    routes = _routes(recipe, by_key, junctions, start)
    return TrackNetwork(
        id=recipe.id,
        name=recipe.name,
        segments=tuple(segments),
        junctions=tuple(junctions),
        routes=tuple(routes),
        origin=origin,
        start=_start(recipe.start_on, by_key),
    )


def _start(start_on: StartOn | None, by_key: dict[str, list[Segment]]) -> Start | None:
    """Turn "halfway along the pit lane" into a segment and a distance.

    A named group can be several segments once the splitting is done, so the
    fraction is of the whole group's length and lands on whichever segment
    holds it.
    """
    if start_on is None:
        return None
    group = by_key.get(start_on.key)
    if not group:
        raise NetworkError(
            f"a ride is meant to start on {start_on.key!r}, which this world "
            "has no segments for"
        )
    total = sum(segment.length_m for segment in group)
    wanted = total * min(max(start_on.fraction, 0.0), 1.0)
    for segment in group:
        if wanted <= segment.length_m:
            return Start(segment_id=segment.id, offset_m=wanted)
        wanted -= segment.length_m
    last = group[-1]
    return Start(segment_id=last.id, offset_m=last.length_m)


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


def build_from_files(
    recipe_path: Path,
    extract_path: Path,
    elevation_path: Path | None = None,
    buildings_path: Path | None = None,
) -> TrackNetwork:
    """Build a world from its tracked inputs.

    Elevation is optional: a world without it is flat, which is wrong but not
    misleading. So are the buildings: a world without them is an empty field,
    which is what this looked like.
    """
    heights = (
        load_heights(elevation_path)
        if elevation_path is not None and elevation_path.is_file()
        else None
    )
    recipe = load_recipe(recipe_path)
    network = build(recipe, load_extract(extract_path), heights)
    if buildings_path is None or not buildings_path.is_file():
        return network
    if network.origin is None:  # pragma: no cover - every built world has one
        return network
    return replace(
        network,
        buildings=load_buildings(
            buildings_path,
            network.origin,
            recipe.building_heights,
            ground_m=_ground_of(network),
        ),
    )


def _ground_of(network: TrackNetwork) -> float:
    """The height buildings stand at: the same ground the track sits on.

    Open data has no ground height for a building's corners, and a building
    floating above or sunk into the field is worse than one a metre out.
    """
    heights = [point.z for segment in network.segments for point in segment.points]
    return min(heights) if heights else 0.0
