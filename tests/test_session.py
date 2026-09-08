from __future__ import annotations

import pytest

from app.core.physics import Bike, steady_speed_ms
from app.core.session import RideSession
from app.sensors.hub import SensorHub
from app.sensors.types import Metric, Reading
from app.world.description import load
from app.world.navigation import Navigator, Steer, lap_length_m
from app.world.network import TrackNetwork
from tests.worlds import climbing_network, forked_network, loop_network


def hub_with(now: float = 0.0, **readings: float) -> SensorHub:
    hub = SensorHub()
    for name, value in readings.items():
        hub.submit(Reading(Metric[name.upper()], value, at=now, source="meter"))
    return hub


def session(
    network: TrackNetwork | None = None,
    hub: SensorHub | None = None,
    start: str | None = None,
) -> RideSession:
    return RideSession(
        Navigator(network or loop_network(), start_segment=start),
        hub=hub or SensorHub(),
    )


def ride(
    session: RideSession,
    seconds: float,
    power_w: float | None = None,
    step: float = 0.5,
    now: float = 0.0,
) -> float:
    """Ride for a while, with a power meter reporting every step if one is given.

    Feeding the hub each step is what a connected sensor does. A reading left to
    go stale means the device dropped out, which is a different test.
    """
    for _ in range(int(seconds / step)):
        now += step
        if power_w is not None:
            session.hub.submit(Reading(Metric.POWER, power_w, at=now, source="meter"))
        session.update(step, now=now)
    return now


def test_a_ride_with_nothing_connected_goes_nowhere() -> None:
    state = session().update(1.0, now=1.0)

    assert state.speed_ms == 0.0
    assert state.distance_m == 0.0
    assert not state.has_sensors


def test_power_moves_the_rider_through_the_world() -> None:
    ride_session = session()

    ride(ride_session, seconds=60.0, power_w=200.0)

    assert ride_session.speed_ms > 0
    assert ride_session.distance_m > 100.0
    assert ride_session.navigator.travelled_m == ride_session.distance_m


def test_the_speed_settles_where_the_power_model_says_it_should() -> None:
    """The session must not invent its own physics on top of the model's."""
    ride_session = session()

    ride(ride_session, seconds=900.0, power_w=200.0)

    assert ride_session.speed_ms == pytest.approx(
        steady_speed_ms(200.0, 0.0, Bike()), abs=0.05
    )


def test_the_gradient_under_the_wheels_is_what_slows_the_rider() -> None:
    flat = session()
    climb = session(climbing_network(), start="climb")

    ride(flat, seconds=60.0, power_w=200.0)
    now = ride(climb, seconds=60.0, power_w=200.0)

    assert climb.speed_ms < flat.speed_ms / 2
    assert climb.update(0.1, now=now).gradient == pytest.approx(0.1)


def test_speed_is_computed_and_never_taken_from_a_sensor() -> None:
    """A trainer's flywheel speed is a fact about the trainer, not the course."""
    ride_session = session(hub=hub_with(power=200.0, speed=25.0))

    state = ride_session.update(1.0, now=0.5)

    assert state.speed_ms < 5.0, "one second of 200 W is not 90 km/h"


def test_the_state_carries_the_rest_of_the_sensors_through() -> None:
    ride_session = session(hub=hub_with(power=210.0, cadence=88.0, heart_rate=147.0))

    state = ride_session.update(1.0, now=0.5)

    assert state.power_w == 210.0
    assert state.cadence_rpm == 88.0
    assert state.heart_rate_bpm == 147.0
    assert state.has_sensors
    assert not state.power_estimated


def test_an_estimate_is_still_marked_as_one_when_it_reaches_a_screen() -> None:
    hub = SensorHub()
    hub.submit(
        Reading(Metric.POWER, 180.0, at=0.0, source="generic-fluid", estimated=True)
    )

    assert session(hub=hub).update(1.0, now=0.5).power_estimated


def test_a_sensor_that_drops_out_stops_driving_the_ride() -> None:
    ride_session = session()
    now = ride(ride_session, seconds=60.0, power_w=250.0)
    moving = ride_session.speed_ms

    # Nothing new arrives, so the reading goes stale and the rider coasts down.
    ride(ride_session, seconds=120.0, now=now)

    assert moving > 0.0
    assert ride_session.speed_ms == 0.0


def test_elapsed_time_is_the_time_that_was_ridden() -> None:
    ride_session = session()

    ride(ride_session, seconds=30.0, power_w=200.0)

    assert ride_session.elapsed_s == pytest.approx(30.0)


def ride_until(
    session: RideSession,
    metres: float,
    power_w: float = 250.0,
    step: float = 0.5,
    now: float = 0.0,
) -> float:
    """Ride to a distance rather than for a time, so a test can stop somewhere."""
    while session.distance_m < metres:
        now = ride(session, seconds=step, power_w=power_w, step=step, now=now)
    return now


def test_the_junction_ahead_reaches_the_state() -> None:
    ride_session = session(forked_network(), start="approach")

    # The approach is 200 m and the junction announces itself with 150 m to go.
    now = ride_until(ride_session, metres=100.0)

    state = ride_session.update(0.5, now=now)
    assert state.upcoming is not None
    assert state.upcoming.chosen_exit == "straight"


def test_steering_during_a_ride_changes_where_it_goes() -> None:
    ride_session = session(forked_network(), start="approach")
    now = ride_until(ride_session, metres=100.0)

    ride_session.navigator.steer(Steer.LEFT)
    ride(ride_session, seconds=60.0, power_w=250.0, now=now)

    assert ride_session.navigator.position.segment_id == "left"


def test_a_lap_of_the_real_circuit_takes_about_as_long_as_it_should() -> None:
    """Two hundred watts round Sokol: a shade under eight minutes."""
    network = load("sokol")
    route = network.route("big-ring")
    ride_session = RideSession(Navigator(network, route=route))

    ride_until(ride_session, metres=lap_length_m(network, route), power_w=200.0)

    assert 7.0 < ride_session.elapsed_s / 60 < 9.0
