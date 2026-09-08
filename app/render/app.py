"""The Panda3D window: the track, a rider on it, and the junction arrow.

What this does *not* do is decide anything. Where the rider is, which way the
junction arrow points and what pressing left does are all `app/world`, which runs
headless and is tested. This module reads that state once a frame and draws it.

The rider moves at a fixed speed for now. Power, gradient and the rest arrive
with the ride physics; until then a constant speed is enough to ride the circuit
and see that the geometry, the junctions and the steering all work.
"""

from __future__ import annotations

import math
from collections.abc import Callable

from direct.gui.OnscreenText import OnscreenText
from direct.showbase.ShowBase import ShowBase
from direct.task.Task import Task
from panda3d.core import (
    AmbientLight,
    ClockObject,
    DirectionalLight,
    Filename,
    LVector3,
    NodePath,
    OrthographicLens,
    TextNode,
    WindowProperties,
    loadPrcFileData,
)

from app.core.recorder import RideRecorder
from app.core.session import RideSession, RideState
from app.render.geometry import arrow_node, geom_node
from app.sensors.hub import SensorHub
from app.sensors.simulated import SimulatedSensors, steady
from app.workout.engine import WorkoutEngine
from app.workout.model import DurationKind, Workout
from app.world.description import load as load_world
from app.world.mesh import Mesh, network_mesh
from app.world.navigation import Navigator, Steer
from app.world.network import TrackNetwork

DEFAULT_WORLD = "sokol"
# What the stand-in rider pushes until real sensors are connected.
DEFAULT_POWER_W = 200.0
# Frames the self-test renders before it is satisfied the engine really runs.
SELFTEST_FRAMES = 5

# The chase camera sits behind and above the rider, looking well ahead so the
# track reads as a ribbon running into the distance rather than as a wall.
CAMERA_BEHIND_M = 16.0
CAMERA_HEIGHT_M = 5.0
CAMERA_LOOK_AHEAD_M = 50.0
CAMERA_LOOK_HEIGHT_M = 1.0
# Panda3D's default far plane is a thousand metres, which is less than the far
# side of a circuit: without this the track is sliced off at the horizon.
CAMERA_NEAR_M = 0.5
CAMERA_FAR_M = 6000.0

ARROW_HEIGHT_M = 5.0
ARROW_SCALE = 2.5
SKY = (0.53, 0.71, 0.87, 1.0)
ASPHALT = (0.24, 0.24, 0.26, 1.0)
ARROW_COLOUR = (1.0, 0.78, 0.13, 1.0)
RIDER_COLOUR = (0.85, 0.16, 0.20, 1.0)
# A plain backdrop under the circuit. Not terrain - the landscape around Sokol is
# not modelled - just something for the track to sit on so it does not float.
GROUND_COLOUR = (0.42, 0.45, 0.34, 1.0)
GROUND_SIZE_M = 8000.0
GROUND_DROP_M = 0.15

# Room left around the circuit in a plan view, and how far above it to sit. The
# lens is orthographic, so the height only has to clear the world.
PLAN_MARGIN = 1.08
PLAN_CAMERA_HEIGHT_M = 4000.0


class RideApp(ShowBase):
    """The application window."""

    def __init__(
        self,
        translate: Callable[[str], str],
        world_id: str = DEFAULT_WORLD,
        route_id: str | None = None,
        power_w: float = DEFAULT_POWER_W,
        *,
        headless: bool = False,
        offscreen: bool = False,
        record: bool = False,
        workout: Workout | None = None,
    ):
        if headless:
            # No graphics pipe at all: the frozen-app smoke test in CI runs on a
            # machine with no display, and an offscreen buffer would still need
            # one on some drivers.
            loadPrcFileData("headless", "window-type none")
        elif offscreen:
            # A real framebuffer with nothing on screen, so a picture of the
            # world can be taken on a machine nobody is sitting at.
            loadPrcFileData("offscreen", "window-type offscreen")
        super().__init__()
        self.translate = translate
        self._clock = ClockObject.getGlobalClock()
        self.network: TrackNetwork = load_world(world_id)
        route = self.network.route(route_id) if route_id else None
        self.navigator = Navigator(self.network, route=route)

        # No sensors are connected yet, so a stand-in rider pushes a steady
        # power into the same hub a real power meter would report to. Swapping
        # in the Bluetooth or ANT+ source changes this line and nothing else.
        self.hub = SensorHub()
        self.rider_source = SimulatedSensors(steady(power_w=power_w))
        self.session = RideSession(self.navigator, hub=self.hub)
        self.state: RideState = self.session.update(0.0, now=0.0)
        # A picture of the world or a smoke test is not a ride, so neither of
        # those leaves a file behind in the rider's activity store.
        self.recorder = RideRecorder() if record else None
        self.workout = WorkoutEngine(workout) if workout else None
        self._last_distance_m = 0.0

        self.ground = self._build_ground()
        self.track = self._build_track()
        self.rider = self._build_rider()
        self.arrow = self._build_arrow()
        if not headless:
            self._prepare_window(offscreen=offscreen)
        self.hud = self._build_hud(headless=headless or offscreen)
        self._light()
        self._bind_keys()
        self.taskMgr.add(self._tick, "ride")

    # Building the scene.

    def _build_ground(self) -> NodePath:
        """One big quad under everything, a touch below the track surface."""
        half = GROUND_SIZE_M / 2.0
        mesh = Mesh(
            vertices=(
                (-half, -half, -GROUND_DROP_M),
                (half, -half, -GROUND_DROP_M),
                (half, half, -GROUND_DROP_M),
                (-half, half, -GROUND_DROP_M),
            ),
            tex_coords=((0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)),
            triangles=((0, 1, 2), (0, 2, 3)),
        )
        node = self.render.attachNewNode(geom_node(mesh, "ground"))
        node.setColor(*GROUND_COLOUR)
        return node

    def _build_track(self) -> NodePath:
        node = self.render.attachNewNode(geom_node(network_mesh(self.network), "track"))
        node.setColor(*ASPHALT)
        return node

    def _build_rider(self) -> NodePath:
        """A marker, not a model: something to follow while the world is built."""
        node = self.render.attachNewNode(arrow_node("rider"))
        node.setColor(*RIDER_COLOUR)
        node.setScale(1.2)
        return node

    def _build_arrow(self) -> NodePath:
        node = self.render.attachNewNode(arrow_node("junction-arrow"))
        node.setColor(*ARROW_COLOUR)
        node.setScale(ARROW_SCALE)
        node.hide()
        return node

    def _prepare_window(self, *, offscreen: bool) -> None:
        self.setBackgroundColor(*SKY)
        self.disableMouse()
        lens = self.cam.node().getLens()
        lens.setNearFar(CAMERA_NEAR_M, CAMERA_FAR_M)
        if offscreen:
            # An offscreen buffer is not a window: it has no title bar to name.
            return
        properties = WindowProperties()
        properties.setTitle(f"RideWithUBT - {self.translate('Virtual training world')}")
        self.win.requestProperties(properties)

    def _build_hud(self, *, headless: bool) -> OnscreenText | None:
        if headless:
            return None
        return OnscreenText(
            text="",
            pos=(-1.3, 0.9),
            scale=0.06,
            fg=(1, 1, 1, 1),
            shadow=(0, 0, 0, 0.6),
            align=TextNode.ALeft,
            mayChange=True,
        )

    def _light(self) -> None:
        ambient = AmbientLight("ambient")
        ambient.setColor((0.55, 0.55, 0.6, 1))
        sun = DirectionalLight("sun")
        sun.setColor((0.7, 0.68, 0.6, 1))
        sun_path = self.render.attachNewNode(sun)
        sun_path.setHpr(35, -60, 0)
        self.render.setLight(self.render.attachNewNode(ambient))
        self.render.setLight(sun_path)

    def _bind_keys(self) -> None:
        """Left and right move the junction arrow; nothing else steers."""
        self.accept("arrow_left", self.navigator.steer, [Steer.LEFT])
        self.accept("arrow_right", self.navigator.steer, [Steer.RIGHT])
        self.accept("escape", self.userExit)
        # Space ends a step that runs until the rider says so.
        self.accept("space", self._end_open_step)

    def _end_open_step(self) -> None:
        if self.workout is not None:
            self.workout.advance()

    # Every frame.

    def _tick(self, task: Task) -> int:
        now = self._clock.getFrameTime()
        for reading in self.rider_source.sample(now, now):
            self.hub.submit(reading)
        self.state = self.session.update(self._clock.getDt(), now=now)
        self._follow_workout(self._clock.getDt())
        if self.recorder is not None:
            self.recorder.observe(self.state)
        self._place_rider()
        self._place_camera()
        self._place_arrow()
        self._update_hud()
        return Task.cont

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
        if step is None:
            return
        target = step.step.power
        if target is not None:
            self.rider_source.profile = steady(power_w=target.middle)

    def _place_rider(self) -> None:
        point = self.state.point
        self.rider.setPos(point.x, point.y, point.z + 0.4)
        self.rider.setH(math.degrees(self.state.heading_rad) - 90.0)

    def _place_camera(self) -> None:
        # With no window there is no camera: the self-test still runs the world
        # and the scene graph, which is what it is there to check.
        if self.camera is None:
            return
        point = self.state.point
        heading = self.state.heading_rad
        back = LVector3(-math.cos(heading), -math.sin(heading), 0.0) * CAMERA_BEHIND_M
        self.camera.setPos(
            point.x + back.x,
            point.y + back.y,
            point.z + CAMERA_HEIGHT_M,
        )
        ahead = LVector3(math.cos(heading), math.sin(heading), 0.0)
        self.camera.lookAt(
            point.x + ahead.x * CAMERA_LOOK_AHEAD_M,
            point.y + ahead.y * CAMERA_LOOK_AHEAD_M,
            point.z + CAMERA_LOOK_HEIGHT_M,
        )

    def _place_arrow(self) -> None:
        """Above the track ahead, pointing the way the rider is currently going."""
        upcoming = self.state.upcoming
        if upcoming is None:
            self.arrow.hide()
            return
        point = self.state.point
        heading = self.state.heading_rad
        ahead = min(upcoming.distance_m, CAMERA_LOOK_AHEAD_M * 2)
        self.arrow.setPos(
            point.x + math.cos(heading) * ahead,
            point.y + math.sin(heading) * ahead,
            point.z + ARROW_HEIGHT_M,
        )
        self.arrow.setH(math.degrees(heading + upcoming.bearing_rad) - 90.0)
        self.arrow.show()

    def _update_hud(self) -> None:
        if self.hud is None:
            return
        state = self.state
        estimated = " (estimated)" if state.power_estimated else ""
        lines = [
            f"{state.speed_kmh:5.1f} km/h",
            f"{state.power_w:5.0f} W{estimated}",
            f"{state.distance_m / 1000:5.2f} km",
        ]
        if state.cadence_rpm is not None:
            lines.append(f"{state.cadence_rpm:5.0f} rpm")
        if state.heart_rate_bpm is not None:
            lines.append(f"{state.heart_rate_bpm:5.0f} bpm")
        if abs(state.gradient) >= 0.005:
            lines.append(f"{state.gradient * 100:5.1f} %")
        if state.upcoming is not None:
            lines.append(
                f"{state.upcoming.chosen_exit} in {state.upcoming.distance_m:.0f} m"
            )
        lines += self._workout_lines()
        self.hud.setText("\n".join(lines))

    def _workout_lines(self) -> list[str]:
        if self.workout is None:
            return []
        progress = self.workout.progress()
        if progress.finished:
            return ["", self.translate("Workout complete")]
        step = progress.step
        if step is None:  # pragma: no cover - finished covers this
            return []
        lines = ["", f"{step.step.label}  {step.index + 1}/{progress.steps_total}"]
        if step.remaining is None:
            lines.append(self.translate("Press space when ready"))
        elif step.step.duration_kind is DurationKind.TIME:
            lines.append(f"{step.remaining:.0f} s left")
        else:
            lines.append(f"{step.remaining:.0f} m left")
        target = step.step.power
        if target is not None:
            held = (
                ""
                if step.on_target is None
                else ("  on target" if step.on_target else "  off target")
            )
            lines.append(f"{target.low:.0f}-{target.high:.0f} W{held}")
        return lines

    def ride_forward(self, seconds: float, step: float = 0.5) -> None:
        """Ride on without drawing, to reach a point on the circuit."""
        now = 0.0
        while now < seconds:
            now += step
            for reading in self.rider_source.sample(now, now):
                self.hub.submit(reading)
            self.state = self.session.update(step, now=now)
        self._place_rider()
        self._place_camera()
        self._place_arrow()

    def userExit(self) -> None:  # noqa: N802 - overriding Panda3D's own name
        """Save the ride on the way out, however the window was closed."""
        self.save_ride()
        super().userExit()

    def save_ride(self) -> str | None:
        """Write the recording into the activity store, if there is one."""
        if self.recorder is None or self.recorder.is_empty:
            return None
        path = self.recorder.save()
        self.recorder = None  # a ride is saved once
        return str(path)

    def run_frames(self, count: int) -> None:
        """Render a fixed number of frames and return, instead of looping forever."""
        for _ in range(count):
            self.taskMgr.step()


def screenshot(
    translate: Callable[[str], str],
    path: str,
    world_id: str = DEFAULT_WORLD,
    route_id: str | None = None,
    seconds: float = 0.0,
    power_w: float = DEFAULT_POWER_W,
) -> None:
    """Render the world into an image file rather than onto a screen.

    For looking at what a change did to the track without sitting in front of it,
    and for showing it to someone who is not at this machine. ``seconds`` rides
    that far into the lap first, so any part of the circuit can be pictured.
    """
    app = RideApp(
        translate,
        world_id=world_id,
        route_id=route_id,
        power_w=power_w,
        offscreen=True,
    )
    try:
        app.ride_forward(seconds)
        app.run_frames(SELFTEST_FRAMES)
        app.win.saveScreenshot(Filename.fromOsSpecific(path))
    finally:
        app.destroy()


def plan_view(
    translate: Callable[[str], str],
    path: str,
    world_id: str = DEFAULT_WORLD,
    size_px: int = 1400,
) -> None:
    """Draw the whole world from directly above, into an image file.

    The generators write worlds nobody has looked at. A plan view is how a change
    to a recipe gets reviewed: the shape of the circuit, where the alternatives
    branch off and where the pit lane runs are all visible at a glance, and a
    mistake in any of them is obvious in a way a diff of coordinates is not.
    """
    loadPrcFileData("plan", f"win-size {size_px} {size_px}")
    app = RideApp(translate, world_id=world_id, offscreen=True)
    try:
        # Nothing moves in a plan view, so the ride does not run.
        app.taskMgr.remove("ride")
        app.rider.hide()
        app.arrow.hide()
        points = [point for segment in app.network.segments for point in segment.points]
        xs = [point.x for point in points]
        ys = [point.y for point in points]
        span = max(max(xs) - min(xs), max(ys) - min(ys)) * PLAN_MARGIN
        centre_x = (min(xs) + max(xs)) / 2
        centre_y = (min(ys) + max(ys)) / 2

        lens = OrthographicLens()
        lens.setFilmSize(span, span)
        app.cam.node().setLens(lens)
        app.camera.setPos(centre_x, centre_y, PLAN_CAMERA_HEIGHT_M)
        app.camera.lookAt(centre_x, centre_y, 0.0)
        app.camera.setH(0.0)

        app.run_frames(SELFTEST_FRAMES)
        app.win.saveScreenshot(Filename.fromOsSpecific(path))
    finally:
        app.destroy()


def selftest(translate: Callable[[str], str], world_id: str = DEFAULT_WORLD) -> None:
    """Boot the engine headless, build the real world and render a few frames.

    Called by the packaged app in CI, so a Panda3D that failed to freeze - or a
    world file that failed to travel with it - raises here rather than on a
    user's machine.
    """
    app = RideApp(translate, world_id=world_id, headless=True)
    try:
        app.run_frames(SELFTEST_FRAMES)
    finally:
        app.destroy()
