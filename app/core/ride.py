"""A ride, with nothing that draws it.

Everything the renderer used to do between frames lives here: connecting the
rider's devices, moving the world under them, following a workout, telling a
smart trainer what to hold, keeping the recording, measuring a trainer's curve.
None of it needs a window, and all of it decides something - which is exactly the
wrong combination for code living inside the module that owns the graphics, where
it cannot be tested.

What is left in `app/render` is the scene: build it, and once a frame ask a ride
where the rider is and draw them there.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

from app import paths
from app.core.companions import (
    Companion,
    CompanionSource,
    NoCompany,
    PacePartners,
    Peloton,
)
from app.core.control import ControlMode, TrainerDirector
from app.core.presence import RiderState
from app.core.recorder import RideRecorder
from app.core.session import RideSession, RideState
from app.sensors.hub import SensorHub
from app.sensors.loop import Loop, SensorLoop
from app.sensors.manager import DeviceManager, DeviceTransport
from app.sensors.simulated import SimulatedSensors, steady
from app.settings import Settings
from app.trainer.capture import TrainerCapture
from app.workout.engine import WorkoutEngine, WorkoutProgress
from app.workout.model import Workout
from app.world.description import load as load_world
from app.world.navigation import Navigator, Steer
from app.world.network import Route

DEFAULT_WORLD = "sokol"
#: What a stand-in rider pushes when one is asked for without a number.
DEFAULT_POWER_W = 200.0


@dataclass(frozen=True)
class RideSetup:
    """What to ride, and how. Everything the rider chose before starting."""

    world_id: str = DEFAULT_WORLD
    route_id: str | None = None
    #: Watts a stand-in rider pushes, with nobody pedalling. None is the normal
    #: case: the rider's own legs, through their own sensors. This is for
    #: looking at the world without a trainer attached, and it is never a
    #: training session - see `records`.
    simulated_watts: float | None = None
    record: bool = False
    workout: Workout | None = None
    paired_device_ids: Sequence[str] = ()
    control_mode: ControlMode = ControlMode.OFF
    capture_trainer: bool = False
    #: Powers to put pace partners on the circuit at. Empty is riding alone.
    partner_watts: Sequence[float] = ()
    #: Who we are to other riders in a room: a name they read, and an id their
    #: machines tell us apart by. Both are only ever sent to a relay the rider
    #: named, and neither exists until they join one.
    rider_id: str = ""
    rider_name: str = ""

    @property
    def simulated(self) -> bool:
        return self.simulated_watts is not None

    @property
    def records(self) -> bool:
        """Whether this ride leaves a file behind.

        A ride nobody pedalled is not a ride. Recording one would put invented
        watts in the rider's activity store and, from there, into Garmin or
        Strava next to the real ones - so a simulated ride is never kept,
        whatever else was asked for.
        """
        return self.record and not self.simulated


@dataclass(frozen=True)
class RideOutcome:
    """What a finished ride left behind, if anything."""

    ride_path: Path | None = None
    profile_path: Path | None = None


@dataclass
class Ride:
    """One ride in progress: the world, the rider, and everything they brought."""

    setup: RideSetup = field(default_factory=RideSetup)
    settings: Settings | None = None
    transports: Sequence[DeviceTransport] | None = None
    sensor_loop: Loop | None = None
    hub: SensorHub = field(default_factory=SensorHub)
    #: Riders from somewhere else - a relay, over a network. Handed in rather
    #: than built here: that client owns a socket, and sockets are
    #: `app/services`, not the ride.
    others: CompanionSource | None = None

    def __post_init__(self) -> None:
        # Read once: two reads could see different files and set the ride up with
        # one rider's wheel and another's trainer.
        settings = self.settings = self.settings or Settings.load()
        #: The rider's own weight and position, not a generic one: on a flat
        #: circuit those decide what speed a given effort is worth.
        self.bike = settings.bike
        self.network = load_world(self.setup.world_id)
        route = self.network.route(self.setup.route_id) if self.setup.route_id else None
        self.navigator = Navigator(self.network, route=route)
        # The rider's own weight and position, not a generic one: on a flat
        # circuit those two decide what speed a given effort is worth, and a
        # speed that does not match the road is the whole point of getting
        # right.
        self.session = RideSession(self.navigator, hub=self.hub, bike=self.bike)
        self.director = TrainerDirector(mode=self.setup.control_mode)
        self.workout = WorkoutEngine(self.setup.workout) if self.setup.workout else None
        # A picture of the world, a smoke test, or a ride nobody pedalled is not
        # a ride, so none of them leaves a file behind in the activity store.
        self.recorder = RideRecorder() if self.setup.records else None
        self.capture = self._prepare_capture()
        self.sensors = self._prepare_sensors()
        # Real sensors and the stand-in rider report to the same hub, and only
        # one is ever used. A stand-in has to be asked for: riding along on
        # invented watts because nothing was connected is not a thing to do by
        # default, and it is how a session got recorded that nobody pedalled.
        watts = self.setup.simulated_watts
        self.rider_source = (
            SimulatedSensors(steady(power_w=watts))
            if watts is not None and not self.sensors
            else None
        )
        self.company: CompanionSource = self._prepare_company(route)
        self._last_distance_m = 0.0
        self.state: RideState = self.session.update(0.0, now=0.0)

    # Setting up.

    def _prepare_company(self, route: Route | None) -> CompanionSource:
        """Who else is on the road: made-up riders, real ones, or nobody.

        Both at once is a real thing to want - a club ride with a partner to
        chase - so they compose rather than exclude one another.
        """
        sources: list[CompanionSource] = []
        if self.setup.partner_watts:
            sources.append(
                PacePartners.holding(
                    self.network,
                    self.setup.partner_watts,
                    route,
                    # The same bicycle the rider is on, so a 220 W partner is
                    # somebody to sit behind rather than a number that happens
                    # to move at a different speed for no visible reason.
                    bike=self.bike,
                )
            )
        if self.others is not None:
            sources.append(self.others)
        if not sources:
            return NoCompany()
        return sources[0] if len(sources) == 1 else Peloton(tuple(sources))

    def _prepare_capture(self) -> TrainerCapture | None:
        """Measure this trainer's curve during the ride, if asked and possible.

        It needs a trainer to attribute the curve to and a wheel to turn a speed
        sensor's revolutions into a speed; without either there is nothing a
        profile could be recorded against.
        """
        if not self.setup.capture_trainer or self.settings is None:
            return None
        trainer, wheel = self.settings.trainer, self.settings.wheel
        if trainer is None or wheel is None:
            return None
        return TrainerCapture(trainer=trainer, wheel=wheel)

    def _prepare_sensors(self) -> DeviceManager | None:
        """Connect the rider's own devices, on a thread of their own.

        The connecting is not waited for. A scan takes seconds, and a window that
        will not draw until the radios have finished looking is a window that
        looks broken; devices simply start reporting when they answer.
        """
        if not self.setup.paired_device_ids:
            return None
        if self.transports is None:
            from app.sensors.discovery import default_transports

            self.transports = default_transports()
        loop = self.sensor_loop or SensorLoop()
        loop.start()
        self.sensor_loop = loop
        wheel = self.settings.wheel if self.settings else None
        manager = DeviceManager(hub=self.hub, transports=self.transports, wheel=wheel)
        loop.submit(connect_paired(manager, tuple(self.setup.paired_device_ids)))
        return manager

    # Riding.

    def advance(self, seconds: float, now: float) -> RideState:
        """Move the ride on by one step, and report where it got to."""
        if self.rider_source is not None:
            for reading in self.rider_source.sample(now, now):
                self.hub.submit(reading)
        self.state = self.session.update(seconds, now=now)
        self.company.report(self.me())
        self.company.advance(seconds)
        self._follow_workout(seconds)
        self._command_trainer(now)
        if self.capture is not None:
            self.capture.observe(self.hub.snapshot(now))
        if self.recorder is not None:
            self.recorder.observe(self.state)
        return self.state

    def steer(self, direction: Steer) -> str | None:
        return self.navigator.steer(direction)

    def end_open_step(self) -> None:
        """What a rider does when a step runs until they say so."""
        if self.workout is not None:
            self.workout.advance()

    def me(self) -> RiderState:
        """Where we are, in the only terms other riders are told anything.

        Position, heading, speed, distance, cadence, power. Not a heart rate,
        not a workout, not a name for the machine - the smallest thing that
        lets somebody else draw us on their road.
        """
        return RiderState(
            id=self.setup.rider_id,
            name=self.setup.rider_name,
            world_id=self.setup.world_id,
            x=self.state.point.x,
            y=self.state.point.y,
            z=self.state.point.z,
            heading_rad=self.state.heading_rad,
            distance_m=self.state.distance_m,
            speed_ms=self.state.speed_ms,
            cadence_rpm=self.state.cadence_rpm,
            power_w=self.state.power_w,
        )

    @property
    def companions(self) -> Sequence[Companion]:
        """Everyone else on the road right now."""
        return self.company.companions()

    @property
    def workout_progress(self) -> WorkoutProgress | None:
        return self.workout.progress() if self.workout else None

    def _follow_workout(self, seconds: float) -> None:
        """Move the workout on, and let its target drive the stand-in rider.

        A real rider is told the target and decides whether to hold it; the
        stand-in simply holds it, which is what makes a workout visible before
        any sensor is connected.
        """
        if self.workout is None:
            return
        covered = self.state.distance_m - self._last_distance_m
        self._last_distance_m = self.state.distance_m
        progress = self.workout.update(seconds, covered, self.state.power_w)
        step = progress.step
        if step is None or self.rider_source is None:
            return
        target = step.step.power
        if target is not None:
            self.rider_source.profile = steady(power_w=target.middle)

    def _command_trainer(self, now: float) -> None:
        """Tell the trainer what to hold, when there is anything new to say."""
        if self.sensors is None or self.sensor_loop is None:
            return
        command = self.director.update(
            now, gradient=self.state.gradient, target_w=self.target_power_w
        )
        if command is not None:
            self.sensor_loop.submit(self.sensors.apply(command))

    @property
    def target_power_w(self) -> float | None:
        """What the workout is asking for right now, if it is asking for watts."""
        progress = self.workout_progress
        if progress is None or progress.step is None:
            return None
        target = progress.step.step.power
        return target.middle if target is not None else None

    # Finishing.

    def save(self) -> RideOutcome:
        """Write out whatever this ride produced. Safe to call more than once."""
        return RideOutcome(
            ride_path=self._save_ride(), profile_path=self._save_profile()
        )

    def _save_ride(self) -> Path | None:
        if self.recorder is None or self.recorder.is_empty:
            return None
        path = self.recorder.save()
        self.recorder = None  # a ride is saved once
        return path

    def _save_profile(self) -> Path | None:
        if self.capture is None or not self.capture.report().publishable:
            return None
        path = self.capture.write_contribution(paths.contributions_dir())
        self.capture = None
        return path

    def release(self) -> None:
        """Disconnect every device and stop the sensor thread."""
        if self.sensors is not None and self.sensor_loop is not None:
            self.sensor_loop.run(self.sensors.disconnect_all())
        if self.sensor_loop is not None:
            self.sensor_loop.stop()
        self.sensors, self.sensor_loop = None, None


async def connect_paired(manager: DeviceManager, wanted: tuple[str, ...]) -> None:
    """Connect whichever paired devices answer. One that does not is absent."""
    found = await manager.scan()
    await manager.connect_all(device for device in found if device.id in wanted)
