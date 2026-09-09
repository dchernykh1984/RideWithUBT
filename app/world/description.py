"""Reading a world from its description file.

A world is data: one JSON file per world under ``app/data/worlds``, holding the
segments, the junctions and the named routes. Adding a world is adding a file,
which is the whole of what "extensible maps" means here - the extension point is
data, not a plugin API.

The files are written by the generators, not by hand: a track is thousands of
points. Points are therefore stored as bare ``[x, y, z]`` arrays rather than
objects, which is worth a lot of bytes across a whole circuit.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

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

WORLDS_DIR = Path(__file__).parent.parent / "data" / "worlds"


def parse_point(raw: Any) -> Point:
    if len(raw) == 2:
        return Point(float(raw[0]), float(raw[1]))
    return Point(float(raw[0]), float(raw[1]), float(raw[2]))


def parse_segment(raw: dict[str, Any]) -> Segment:
    return Segment(
        id=str(raw["id"]),
        start_node=str(raw["start_node"]),
        end_node=str(raw["end_node"]),
        points=tuple(parse_point(point) for point in raw["points"]),
        width_m=float(raw.get("width_m", 10.0)),
        surface=str(raw.get("surface", "asphalt")),
    )


def parse_junction(raw: dict[str, Any]) -> Junction:
    return Junction(
        node=str(raw["node"]),
        exits=tuple(str(exit_id) for exit_id in raw["exits"]),
        default_exit=str(raw["default_exit"]),
        announce_m=float(raw.get("announce_m", 150.0)),
    )


def parse_route(raw: dict[str, Any]) -> Route:
    return Route(
        id=str(raw["id"]),
        name=str(raw["name"]),
        start_segment=str(raw["start_segment"]),
        choices={
            str(node): str(exit_id) for node, exit_id in raw.get("choices", {}).items()
        },
    )


def parse_origin(raw: dict[str, Any] | None) -> Origin | None:
    if raw is None:
        return None
    return Origin(lat=float(raw["lat"]), lon=float(raw["lon"]))


def parse_start(raw: dict[str, Any] | None) -> Start | None:
    if raw is None:
        return None
    return Start(
        segment_id=str(raw["segment"]),
        offset_m=float(raw.get("offset_m", 0.0)),
    )


def parse_world(raw: dict[str, Any]) -> TrackNetwork:
    """Build a network from a parsed description, checking it as it goes."""
    try:
        return TrackNetwork(
            id=str(raw["id"]),
            name=str(raw["name"]),
            segments=tuple(parse_segment(item) for item in raw["segments"]),
            junctions=tuple(parse_junction(item) for item in raw.get("junctions", ())),
            routes=tuple(parse_route(item) for item in raw.get("routes", ())),
            origin=parse_origin(raw.get("origin")),
            start=parse_start(raw.get("start")),
        )
    except KeyError as error:
        raise NetworkError(f"world description is missing {error.args[0]!r}") from None


def load_world(path: Path) -> TrackNetwork:
    return parse_world(json.loads(path.read_text(encoding="utf-8")))


def world_path(world_id: str, directory: Path = WORLDS_DIR) -> Path:
    return directory / f"{world_id}.json"


def available_worlds(directory: Path = WORLDS_DIR) -> list[str]:
    """Every world that ships with the app, by id."""
    if not directory.is_dir():
        return []
    return sorted(path.stem for path in directory.glob("*.json"))


def load(world_id: str, directory: Path = WORLDS_DIR) -> TrackNetwork:
    path = world_path(world_id, directory)
    if not path.is_file():
        raise NetworkError(f"no world {world_id!r} in {directory}")
    return load_world(path)


def describe(network: TrackNetwork) -> dict[str, Any]:
    """The inverse of `parse_world`, for the generators to write."""
    document: dict[str, Any] = {
        "id": network.id,
        "name": network.name,
        "segments": [
            {
                "id": segment.id,
                "start_node": segment.start_node,
                "end_node": segment.end_node,
                "width_m": segment.width_m,
                "surface": segment.surface,
                "points": [
                    [round(point.x, 3), round(point.y, 3), round(point.z, 3)]
                    for point in segment.points
                ],
            }
            for segment in network.segments
        ],
        "junctions": [
            {
                "node": junction.node,
                "exits": list(junction.exits),
                "default_exit": junction.default_exit,
                "announce_m": junction.announce_m,
            }
            for junction in network.junctions
        ],
        "routes": [
            {
                "id": route.id,
                "name": route.name,
                "start_segment": route.start_segment,
                "choices": dict(route.choices),
            }
            for route in network.routes
        ],
    }
    if network.origin is not None:
        document["origin"] = {
            "lat": round(network.origin.lat, 9),
            "lon": round(network.origin.lon, 9),
        }
    if network.start is not None:
        document["start"] = {
            "segment": network.start.segment_id,
            "offset_m": round(network.start.offset_m, 3),
        }
    return document
