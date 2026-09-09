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
from pathlib import Path

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
    Texture,
    TextureStage,
    WindowProperties,
    loadPrcFileData,
)

from app.core.ride import DEFAULT_POWER_W, DEFAULT_WORLD, Ride, RideSetup
from app.core.session import RideState
from app.render.geometry import arrow_node, geom_node
from app.workout.model import DurationKind
from app.world.mesh import ground_plane, network_mesh
from app.world.navigation import Steer
from app.world.network import TrackNetwork

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
#: Where the generated surfaces live, inside the package so they travel with it.
TEXTURES = Path(__file__).parent.parent / "data" / "textures"
ASPHALT = (0.24, 0.24, 0.26, 1.0)
ARROW_COLOUR = (1.0, 0.78, 0.13, 1.0)
RIDER_COLOUR = (0.85, 0.16, 0.20, 1.0)
COMPANION_COLOUR = (0.20, 0.45, 0.85, 1.0)
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
    """The window. It builds the scene and, once a frame, draws where a ride is.

    Everything that decides anything - the sensors, the workout, the trainer, the
    recording - is a `Ride`, which needs no window and is tested without one.
    """

    def __init__(
        self,
        translate: Callable[[str], str],
        setup: RideSetup | None = None,
        *,
        headless: bool = False,
        offscreen: bool = False,
        ride: Ride | None = None,
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
        self.ride = ride or Ride(setup or RideSetup())

        self.ground = self._build_ground()
        self.track = self._build_track()
        self.rider = self._build_rider()
        self.companions: dict[str, NodePath] = {}
        self.arrow = self._build_arrow()
        if not headless:
            self._prepare_window(offscreen=offscreen)
        self.hud = self._build_hud(headless=headless or offscreen)
        self._light()
        self._bind_keys()
        self.taskMgr.add(self._tick, "ride")

    @property
    def state(self) -> RideState:
        return self.ride.state

    @property
    def network(self) -> TrackNetwork:
        return self.ride.network

    # Building the scene.

    def _build_ground(self) -> NodePath:
        """A backdrop under the circuit. Not terrain - the landscape around Sokol
        is not modelled - just something for the track to sit on."""
        mesh = ground_plane(self.network, GROUND_SIZE_M, GROUND_DROP_M)
        node = self.render.attachNewNode(geom_node(mesh, "ground"))
        self._dress(node, "ground.png", GROUND_COLOUR, repeat=GROUND_SIZE_M / 40.0)
        return node

    def _build_track(self) -> NodePath:
        node = self.render.attachNewNode(geom_node(network_mesh(self.network), "track"))
        self._dress(node, "track.png", ASPHALT)
        return node

    def _dress(
        self,
        node: NodePath,
        surface: str,
        fallback: tuple[float, ...],
        repeat: float = 1.0,
    ) -> None:
        """Put a generated surface on a node, or its flat colour if it is missing.

        A texture that failed to travel into a frozen build must not stop the
        ride: a grey road is worse to look at and perfectly rideable.
        """
        texture = self.loader.loadTexture(
            Filename.fromOsSpecific(str(TEXTURES / surface))
        )
        if texture is None:
            node.setColor(*fallback)
            return
        texture.setWrapU(Texture.WMRepeat)
        texture.setWrapV(Texture.WMRepeat)
        node.setTexture(texture)
        if repeat != 1.0:
            node.setTexScale(TextureStage.getDefault(), repeat, repeat)

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
        self.accept("arrow_left", self.ride.steer, [Steer.LEFT])
        self.accept("arrow_right", self.ride.steer, [Steer.RIGHT])
        self.accept("escape", self.userExit)
        # Space ends a step that runs until the rider says so.
        self.accept("space", self.ride.end_open_step)

    def _tick(self, task: Task) -> int:
        now = self._clock.getFrameTime()
        self.ride.advance(self._clock.getDt(), now)
        self._place_rider()
        self._place_companions()
        self._place_camera()
        self._place_arrow()
        self._update_hud()
        return Task.cont

    def _place_rider(self) -> None:
        point = self.state.point
        self.rider.setPos(point.x, point.y, point.z + 0.4)
        self.rider.setH(math.degrees(self.state.heading_rad) - 90.0)

    def _place_companions(self) -> None:
        """Draw whoever else is on the road, making a marker for anyone new.

        Markers are kept by id rather than rebuilt, because a network source will
        eventually add and drop riders mid-ride and rebuilding the scene graph
        every frame for that would be the wrong shape to have started with.
        """
        for companion in self.ride.companions:
            marker = self.companions.get(companion.id)
            if marker is None:
                marker = self.render.attachNewNode(arrow_node(companion.id))
                marker.setColor(*COMPANION_COLOUR)
                marker.setScale(1.2)
                self.companions[companion.id] = marker
            point = companion.point
            marker.setPos(point.x, point.y, point.z + 0.4)
            marker.setH(math.degrees(companion.heading_rad) - 90.0)

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
        lines += self._company_lines()
        lines += self._workout_lines()
        self.hud.setText("\n".join(lines))

    def _company_lines(self) -> list[str]:
        """Who is up the road and who is behind, in metres."""
        others = self.ride.companions
        if not others:
            return []
        mine = self.state.distance_m
        nearby = sorted(others, key=lambda other: abs(other.distance_m - mine))[:3]
        return [
            "",
            *(f"{other.name:>7}  {other.distance_m - mine:+.0f} m" for other in nearby),
        ]

    def _workout_lines(self) -> list[str]:
        if self.ride.workout is None:
            return []
        progress = self.ride.workout_progress
        if progress is None:  # pragma: no cover - guarded by the caller
            return []
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
            self.ride.advance(step, now)
        self._place_rider()
        self._place_camera()
        self._place_arrow()

    def userExit(self) -> None:  # noqa: N802 - overriding Panda3D's own name
        """Save the ride and release the radios, however the window was closed."""
        self.ride.save()
        self.ride.release()
        super().userExit()

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
        RideSetup(world_id=world_id, route_id=route_id, power_w=power_w),
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
    app = RideApp(translate, RideSetup(world_id=world_id), offscreen=True)
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
    app = RideApp(translate, RideSetup(world_id=world_id), headless=True)
    try:
        app.run_frames(SELFTEST_FRAMES)
    finally:
        app.destroy()
