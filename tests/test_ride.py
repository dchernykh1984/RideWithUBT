"""A ride, without a window.

All of this used to live inside the renderer, which is excluded from coverage
because a Panda3D window cannot be made in a test worker. So none of it was
tested - and it is the half that decides things: which devices to connect, what
to tell the trainer, what to keep."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import pytest

from app import paths
from app.core.control import CommandKind, ControlMode
from app.core.ride import Ride, RideSetup, connect_paired
from app.sensors.base import Transport
from app.sensors.hub import SensorHub
from app.sensors.manager import DeviceManager
from app.sensors.types import Metric, Reading
from app.settings import Settings
from app.workout.model import DurationKind, Step, StepKind, Target, TargetKind, Workout
from app.world.navigation import Steer
from tests.test_device_manager import FakeTransport, device


@dataclass
class FakeLoop:
    """Runs what it is handed, at once, on this thread."""

    submitted: list[str] = field(default_factory=list)
    started: bool = False
    stopped: bool = False

    def start(self) -> None:
        self.started = True

    def submit(self, work: object) -> None:
        import asyncio

        self.submitted.append(type(work).__name__)
        asyncio.run(work)  # type: ignore[arg-type]

    def run(self, work: object, timeout: float = 10.0) -> None:
        self.submit(work)

    def stop(self) -> None:
        self.stopped = True


def ride(**setup: object) -> Ride:
    return Ride(setup=RideSetup(**setup))  # type: ignore[arg-type]


def pedal(ride_in_progress: Ride, seconds: float, step: float = 0.5) -> float:
    now = 0.0
    for _ in range(int(seconds / step)):
        now += step
        ride_in_progress.advance(step, now)
    return now


def intervals() -> Workout:
    return Workout(
        name="Intervals",
        steps=(
            Step(
                kind=StepKind.INTERVAL,
                name="Effort",
                duration=60.0,
                targets=(Target(TargetKind.POWER, 280.0, 300.0),),
            ),
            Step(kind=StepKind.REST, name="Open", duration_kind=DurationKind.OPEN),
        ),
    )


def test_a_ride_with_nothing_connected_still_goes_somewhere() -> None:
    """A rider with no sensors gets a stand-in, so the world can be ridden."""
    riding = ride(power_w=220.0)

    pedal(riding, seconds=60.0)

    assert riding.rider_source is not None
    assert riding.sensors is None
    assert riding.state.distance_m > 100
    assert riding.state.power_w == pytest.approx(220.0, rel=0.1)


def test_a_route_that_does_not_exist_is_refused_before_anything_starts() -> None:
    from app.world.network import NetworkError

    with pytest.raises(NetworkError, match="unknown route"):
        ride(route_id="nonesuch")


def test_paired_devices_replace_the_stand_in_rider() -> None:
    """A rider with their own power meter must not be riding an invented one."""
    strap = device("Meter")
    transport = FakeTransport(Transport.BLE, [strap])
    loop = FakeLoop()

    riding = Ride(
        setup=RideSetup(paired_device_ids=(strap.id,)),
        transports=(transport,),
        sensor_loop=loop,
    )

    assert riding.rider_source is None, "the stand-in stays out of the way"
    assert riding.sensors is not None
    assert loop.started
    assert riding.sensors.connected == (strap,)


def test_a_paired_device_that_is_not_there_is_simply_absent() -> None:
    loop = FakeLoop()

    riding = Ride(
        setup=RideSetup(paired_device_ids=("ble:gone",)),
        transports=(FakeTransport(Transport.BLE, []),),
        sensor_loop=loop,
    )

    assert riding.sensors is not None
    assert riding.sensors.connected == ()


async def test_connecting_takes_only_what_was_asked_for() -> None:
    wanted, unwanted = device("Mine"), device("Someone else's")
    transport = FakeTransport(Transport.BLE, [wanted, unwanted])
    manager = DeviceManager(hub=SensorHub(), transports=(transport,))

    await connect_paired(manager, (wanted.id,))

    assert manager.connected == (wanted,)


# Following a workout.


def test_the_workout_drives_the_stand_in_rider() -> None:
    riding = ride(workout=intervals(), power_w=120.0)

    pedal(riding, seconds=10.0)

    assert riding.state.power_w == pytest.approx(290.0, rel=0.1), "the step's target"
    assert riding.target_power_w == 290.0


def test_an_open_step_waits_for_the_rider() -> None:
    riding = ride(workout=intervals())
    pedal(riding, seconds=90.0)

    progress = riding.workout_progress
    assert progress is not None and progress.step is not None
    assert progress.step.step.name == "Open"

    riding.end_open_step()

    assert riding.workout is not None
    assert riding.workout.finished


def test_without_a_workout_there_is_nothing_to_hold() -> None:
    riding = ride()

    assert riding.workout_progress is None
    assert riding.target_power_w is None
    riding.end_open_step()  # and nothing breaks


# Commanding a trainer.


def commanded(mode: ControlMode, **setup: object) -> tuple[Ride, FakeTransport]:
    trainer = device("Trainer", controllable=True)
    transport = FakeTransport(Transport.BLE, [trainer])
    riding = Ride(
        setup=RideSetup(paired_device_ids=(trainer.id,), control_mode=mode, **setup),  # type: ignore[arg-type]
        transports=(transport,),
        sensor_loop=FakeLoop(),
    )
    return riding, transport


def test_in_simulation_the_trainer_is_told_the_slope() -> None:
    riding, transport = commanded(ControlMode.SIMULATION)

    riding.advance(0.5, now=1.0)

    trainer_id = next(iter(transport.controls))
    (command,) = transport.controls[trainer_id].applied
    assert command.kind is CommandKind.SIMULATION


def test_in_erg_the_trainer_is_told_the_workout_target() -> None:
    riding, transport = commanded(ControlMode.ERG, workout=intervals())

    riding.advance(0.5, now=1.0)

    trainer_id = next(iter(transport.controls))
    (command,) = transport.controls[trainer_id].applied
    assert command.kind is CommandKind.TARGET_POWER
    assert command.watts == 290.0


def test_with_control_off_the_trainer_is_left_alone() -> None:
    riding, transport = commanded(ControlMode.OFF)

    riding.advance(0.5, now=1.0)

    trainer_id = next(iter(transport.controls))
    assert transport.controls[trainer_id].applied == []


# Keeping it.


def test_a_ride_that_was_recorded_is_written_once() -> None:
    riding = ride(record=True)
    pedal(riding, seconds=30.0)

    first = riding.save()
    again = riding.save()

    assert first.ride_path is not None
    assert first.ride_path.parent == paths.activities_dir()
    assert again.ride_path is None, "a ride is saved once"


def test_a_ride_nobody_asked_to_record_leaves_nothing() -> None:
    riding = ride()
    pedal(riding, seconds=30.0)

    assert riding.save().ride_path is None


def test_a_trainer_profile_needs_a_trainer_and_a_wheel() -> None:
    """Without either there is nothing a measured curve could be attributed to."""
    Settings(trainer_id="generic-fluid").save()

    assert ride(capture_trainer=True).capture is None


def test_capturing_starts_when_the_setup_allows_it() -> None:
    Settings(
        trainer_id="generic-fluid", wheel_size_id="700c", wheel_width_id="25"
    ).save()

    riding = ride(capture_trainer=True)

    assert riding.capture is not None
    assert riding.capture.trainer.id == "generic-fluid"


def test_a_capture_with_nothing_in_it_writes_nothing() -> None:
    Settings(
        trainer_id="generic-fluid", wheel_size_id="700c", wheel_width_id="25"
    ).save()
    riding = ride(capture_trainer=True)

    pedal(riding, seconds=30.0)

    assert riding.save().profile_path is None


def test_a_measured_curve_is_written_out_ready_to_contribute(
    tmp_path: Path,
) -> None:
    Settings(
        trainer_id="generic-fluid", wheel_size_id="700c", wheel_width_id="25"
    ).save()
    riding = ride(capture_trainer=True)
    assert riding.capture is not None

    # A power meter and a speed sensor, sweeping the range the trainer is used at.
    for step in range(40):
        speed = 3.0 + 0.25 * step
        riding.hub.submit(Reading(Metric.SPEED, speed, at=float(step), source="wheel"))
        riding.hub.submit(
            Reading(Metric.POWER, 0.35 * speed**3, at=float(step), source="meter")
        )
        riding.capture.observe(riding.hub.snapshot(float(step)))

    outcome = riding.save()

    assert outcome.profile_path is not None
    assert outcome.profile_path.name == "generic-fluid.json"


# Letting go.


def test_releasing_disconnects_everything_and_stops_the_thread() -> None:
    trainer = device("Trainer", controllable=True)
    transport = FakeTransport(Transport.BLE, [trainer])
    loop = FakeLoop()
    riding = Ride(
        setup=RideSetup(paired_device_ids=(trainer.id,)),
        transports=(transport,),
        sensor_loop=loop,
    )

    riding.release()

    assert loop.stopped
    assert riding.sensors is None
    assert not transport.opened[0].connected


def test_releasing_a_ride_that_had_no_devices() -> None:
    riding = ride()

    riding.release()

    assert riding.sensor_loop is None


def test_steering_reaches_the_navigator() -> None:
    """A ride begins in the pits, so the first choice comes after the roll-out."""
    riding = ride(route_id="big-ring")
    while riding.navigator.upcoming is None:
        riding.navigator.advance(20.0)
    upcoming = riding.navigator.upcoming
    assert upcoming is not None

    chosen = riding.steer(Steer.LEFT)

    assert chosen is not None
    assert chosen in upcoming.exits


def test_the_pits_are_still_somewhere_you_can_turn_into() -> None:
    """Starting in the pit lane must not stop it being a choice on the lap.

    The rider leaves the pits at the exit and comes back to the entry a lap
    later, which is the same junction it always was.
    """
    riding = ride(route_id="big-ring")
    offered: set[str] = set()
    for _ in range(300):
        riding.navigator.advance(20.0)
        if riding.navigator.upcoming is not None:
            offered |= set(riding.navigator.upcoming.exits)

    assert "pit-lane-0" in offered
