from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.world import description
from app.world.navigation import Navigator, Steer
from app.world.network import NetworkError, Point
from tests.worlds import forked_network


def write(directory: Path, raw: dict[str, object], name: str = "world") -> Path:
    path = directory / f"{name}.json"
    path.write_text(json.dumps(raw), encoding="utf-8")
    return path


def test_a_world_survives_being_written_and_read_back() -> None:
    """The generators write this format; a round trip is what keeps it honest."""
    original = forked_network()

    restored = description.parse_world(description.describe(original))

    assert restored.id == original.id
    assert [s.id for s in restored.segments] == [s.id for s in original.segments]
    assert restored.total_length_m == pytest.approx(original.total_length_m)
    assert restored.junction_at("fork") == original.junction_at("fork")
    assert restored.route("left-route").choices == {"fork": "left"}


def test_a_round_tripped_world_still_rides_the_same() -> None:
    restored = description.parse_world(description.describe(forked_network()))
    navigator = Navigator(restored, start_segment="approach")
    navigator.advance(100.0)

    navigator.steer(Steer.LEFT)
    navigator.advance(150.0)

    assert navigator.position.segment_id == "left"


def test_points_may_leave_out_the_elevation() -> None:
    """Most of a flat circuit is easier to read, and smaller, without a third zero."""
    assert description.parse_point([10, 20]) == Point(10.0, 20.0, 0.0)
    assert description.parse_point([10, 20, 5]) == Point(10.0, 20.0, 5.0)


def test_defaults_fill_in_for_the_optional_fields() -> None:
    world = description.parse_world(
        {
            "id": "minimal",
            "name": "Minimal",
            "segments": [
                {
                    "id": "one",
                    "start_node": "a",
                    "end_node": "b",
                    "points": [[0, 0], [100, 0]],
                }
            ],
        }
    )

    segment = world.segment("one")
    assert segment.width_m == 10.0
    assert segment.surface == "asphalt"
    assert world.junctions == ()
    assert world.routes == ()


def test_a_missing_field_names_itself() -> None:
    with pytest.raises(NetworkError, match="'segments'"):
        description.parse_world({"id": "broken", "name": "Broken"})


def test_loading_from_a_file(tmp_path: Path) -> None:
    path = write(tmp_path, description.describe(forked_network()), name="test-fork")

    assert description.load_world(path).id == "test-fork"
    assert description.load("test-fork", tmp_path).id == "test-fork"


def test_a_world_that_is_not_there(tmp_path: Path) -> None:
    with pytest.raises(NetworkError, match="no world 'missing'"):
        description.load("missing", tmp_path)


def test_listing_the_worlds_that_ship(tmp_path: Path) -> None:
    write(tmp_path, description.describe(forked_network()), name="zebra")
    write(tmp_path, description.describe(forked_network()), name="alpha")

    assert description.available_worlds(tmp_path) == ["alpha", "zebra"]


def test_listing_a_directory_that_does_not_exist(tmp_path: Path) -> None:
    assert description.available_worlds(tmp_path / "nothing-here") == []


def test_the_shipped_worlds_all_load() -> None:
    """Whatever is in app/data/worlds must be readable, or a release ships broken."""
    for world_id in description.available_worlds():
        world = description.load(world_id)
        assert world.segments
        assert world.total_length_m > 0
