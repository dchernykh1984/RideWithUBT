"""Does the model turn real watts into the speed they really produced?

Everything else in the physics tests checks the model against published
calculators, which is checking arithmetic against arithmetic. This checks it
against a bicycle that actually went round this circuit: 8.9 km of Sokol in
866 seconds at 266 W average, a rider of 83 kg on a road bicycle with time
trial bars, recorded by their power meter.

The recording is kept in `build-data/calibration/`, stripped of everything the
question does not need - no coordinates, no heart rate, no date. A rider's
whereabouts are not a test fixture.

This is the test that would notice if the model drifted away from the road.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import pytest

from app.core.physics import (
    Air,
    Bike,
    steady_speed_ms,
    step_speed_ms,
    virtual_bike,
)

REFERENCE = (
    Path(__file__).resolve().parent.parent
    / "build-data"
    / "calibration"
    / "sokol-two-laps.json"
)
#: Where the circuit is, and how warm it was. The head unit read 27 C in the
#: sun, which is the air the tyres were actually rolling through.
ALTITUDE_M = 645.0
TEMPERATURE_C = 27.0


@dataclass(frozen=True)
class Sample:
    second: float
    watts: float
    speed_ms: float
    altitude_m: float


def recorded() -> list[Sample]:
    document = json.loads(REFERENCE.read_text(encoding="utf-8"))
    assert document["columns"] == ["second", "watts", "speed_ms", "altitude_m"]
    return [Sample(*row) for row in document["samples"]]


def rider() -> Bike:
    document = json.loads(REFERENCE.read_text(encoding="utf-8"))["rider"]
    return Bike.ridden_by(
        rider_kg=document["mass_kg"], bike_kg=9.0, bike_id=document["bike_id"]
    )


def ridden(bike: Bike) -> tuple[float, float]:
    """How far the model gets on these watts, and how far the rider got."""
    air = Air.at_altitude(ALTITUDE_M, temperature_c=TEMPERATURE_C)
    samples = recorded()
    speed = samples[0].speed_ms
    modelled = real = 0.0
    previous = samples[0]
    for sample in samples[1:]:
        seconds = sample.second - previous.second
        if not 0 < seconds <= 3:  # a pause in the recording is not a ride
            previous = sample
            continue
        average = (sample.speed_ms + previous.speed_ms) / 2
        run = max(average * seconds, 0.1)
        # Barometric altitude jitters by a few tenths of a metre per second,
        # which over one second of riding reads as a gradient far beyond
        # anything this circuit has. Bounded rather than smoothed: the point
        # here is the model, not the elevation.
        gradient = max(
            -0.15, min(0.15, (sample.altitude_m - previous.altitude_m) / run)
        )
        speed = step_speed_ms(speed, sample.watts, gradient, seconds, bike, air)
        modelled += speed * seconds
        real += average * seconds
        previous = sample
    return modelled, real


def test_the_recording_is_a_real_ride() -> None:
    samples = recorded()

    assert len(samples) > 800
    assert samples[-1].second > 800, "a quarter of an hour of riding"
    assert 200 < sum(s.watts for s in samples) / len(samples) < 320


def test_the_model_rides_the_distance_the_rider_actually_rode() -> None:
    """The whole point. Given what they really pushed, does the world move past
    at the speed the road did?"""
    modelled, real = ridden(rider())

    assert modelled == pytest.approx(real, rel=0.03), (
        f"model {modelled / 1000:.2f} km against a real {real / 1000:.2f} km"
    )


def test_the_recorded_conditions_are_written_down_with_it() -> None:
    """A ride without its air is not evidence of anything."""
    document = json.loads(REFERENCE.read_text(encoding="utf-8"))

    assert document["conditions"]["temperature_c"] > 0
    assert document["rider"]["mass_kg"] == 83.0
    assert document["rider"]["bike_id"] == "road-aerobars"


def test_nothing_personal_was_kept_with_it() -> None:
    """Only what the question needs: watts, speed, height, time.

    Checked on the shape rather than by searching the text, which would find
    the word "heart" in the note explaining that there is no heart rate in it.
    """
    document = json.loads(REFERENCE.read_text(encoding="utf-8"))

    assert document["columns"] == ["second", "watts", "speed_ms", "altitude_m"]
    assert all(len(row) == 4 for row in document["samples"])
    assert set(document) == {"comment", "rider", "conditions", "columns", "samples"}
    # A rider's whereabouts are not a test fixture. Sokol sits near 43.58 N,
    # 76.57 E, and nothing in here should be able to say so.
    assert not any(
        43.0 < abs(value) < 44.0 or 76.0 < abs(value) < 77.0
        for row in document["samples"]
        for value in row[1:]
    ), "something in the numbers looks like a coordinate"


def test_the_wrong_position_gets_the_answer_wrong() -> None:
    """Which is what makes the right one worth having. Sitting up through the
    same ride would have been visibly slower."""
    upright, real = ridden(
        Bike.ridden_by(rider_kg=83.0, bike_kg=9.0, bike_id="upright")
    )

    assert upright < real * 0.93


def test_the_bikes_are_ordered_the_way_a_rider_would_expect() -> None:
    """And the measured one sits where it should: faster than the drops,
    slower than a bicycle built for it rather than fitted with bars."""
    sitting_up = virtual_bike("upright").cda_m2
    hoods = virtual_bike("road").cda_m2
    drops = virtual_bike("road-drops").cda_m2
    clip_ons = virtual_bike("road-aerobars").cda_m2
    time_trial = virtual_bike("tt").cda_m2

    assert sitting_up > hoods > drops > clip_ons > time_trial


def test_a_measured_drag_figure_beats_the_catalogue() -> None:
    """Somebody who has been in a wind tunnel knows better than a table."""
    listed = Bike.ridden_by(bike_id="road")
    measured = Bike.ridden_by(bike_id="road", cda_m2=0.24)

    assert listed.cda_m2 == 0.32
    assert measured.cda_m2 == 0.24
    assert steady_speed_ms(250, 0.0, measured) > steady_speed_ms(250, 0.0, listed)


def test_a_bicycle_nobody_has_heard_of_falls_back_rather_than_breaking() -> None:
    assert virtual_bike("penny-farthing").cda_m2 == virtual_bike("road").cda_m2


def test_weight_is_the_rider_plus_the_bicycle() -> None:
    assert Bike.ridden_by(rider_kg=70.0, bike_kg=8.0).total_mass_kg == 78.0
