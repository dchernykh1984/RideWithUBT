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
from collections.abc import Callable, Sequence
from pathlib import Path

from direct.gui.OnscreenText import OnscreenText
from direct.showbase.ShowBase import ShowBase
from direct.task.Task import Task
from panda3d.core import (
    AmbientLight,
    ClockObject,
    DirectionalLight,
    Filename,
    GraphicsPipeSelection,
    LVector3,
    NodePath,
    OrthographicLens,
    TextNode,
    Texture,
    TextureStage,
    WindowProperties,
    loadPrcFile,
    loadPrcFileData,
)

from app import paths
from app.core.companions import departed
from app.core.preferences import Found, SetupMenu
from app.core.ride import DEFAULT_POWER_W, DEFAULT_WORLD, Ride, RideSetup
from app.core.session import RideState
from app.frozen import panda_config_dir, panda_plugin_dir
from app.render.geometry import arrow_node, geom_node
from app.workout.model import DurationKind
from app.world.mesh import buildings_mesh, ground_plane, network_mesh
from app.world.navigation import Steer, UpcomingJunction
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

ARROW_HEIGHT_M = 7.0
ARROW_SCALE = 4.0
# The arrow lies flat, and flat at the height of the camera is edge-on: from
# the saddle it was a line a few pixels tall, which is no use as a sign. Tipped
# towards the rider it reads as a gantry sign angled down at them, and still
# points the way it is pointing.
ARROW_TILT_DEG = -55.0
#: How far the sign leans to say "this way". A symbol, not a survey: the roads
#: at this circuit part company by six or seven degrees, which drawn honestly
#: is a sign pointing straight up whichever way the rider is about to go.
ARROW_LEAN_DEG = 35.0
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
#: What a building falls back to if its texture did not travel into a build.
WALL_COLOUR = (0.69, 0.67, 0.64, 1.0)

# The settings panel: where it sits, how big, and how far across the second
# column starts. In Panda3D's aspect2d, x runs about -1.33 to 1.33 and y from
# -1 to 1, so this is a card down the left of the screen.
MENU_LEFT = -1.15
MENU_TOP = 0.78
MENU_SCALE = 0.055
MENU_COLUMN = 0.72
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
        point_panda_at_its_own_files()
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
        self.buildings = self._build_buildings()
        self.rider = self._build_rider()
        self.companions: dict[str, NodePath] = {}
        self.arrow = self._build_arrow()
        if not headless:
            self._prepare_window(offscreen=offscreen)
        self.hud = self._build_hud(headless=headless or offscreen)
        self.menu: SetupMenu | None = None
        self.menu_text = self._build_menu_text(headless=headless or offscreen)
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

    def _build_buildings(self) -> NodePath | None:
        """What stands beside the track: the pit garages, the grandstand.

        The thing that tells a rider where they are on a lap is what is beside
        them. Without any of it, every corner looks like every other corner.
        """
        if not self.network.buildings:
            return None
        mesh = buildings_mesh(self.network)
        node = self.render.attachNewNode(geom_node(mesh, "buildings"))
        self._dress(node, "wall.png", WALL_COLOUR)
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
        # Tipped towards the rider it can end up showing its back, and a
        # one-sided triangle seen from behind is not drawn at all. A sign has
        # no back.
        node.setTwoSided(True)
        node.setLightOff()
        node.hide()
        return node

    def _window_icon(self) -> str | None:
        """The icon a running window shows, in the dock or the taskbar.

        The bundle's icon is what a rider double-clicks; this is what they look
        at for the next hour, and they are only the same picture if both are
        set.
        """
        icon = paths.packaged("branding", "icon.png")
        if not icon.exists():  # pragma: no cover - it ships with the application
            return None
        return Filename.fromOsSpecific(str(icon)).getFullpath()

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
        icon = self._window_icon()
        if icon is not None:
            properties.setIconFilename(icon)
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

    def _build_menu_text(self, *, headless: bool) -> list[OnscreenText] | None:
        """The settings panel: a card, two columns of text, and a footer.

        Two columns rather than one padded block. The font a window draws with
        is not monospaced, so padding with spaces lines nothing up and a long
        label shoves its value out into the middle of the screen.
        """
        if headless:
            return None
        card = OnscreenText(
            text="",
            pos=(MENU_LEFT, MENU_TOP),
            scale=MENU_SCALE,
            fg=(1, 1, 1, 0),
            bg=(0.04, 0.06, 0.09, 0.82),
            align=TextNode.ALeft,
            mayChange=True,
        )
        parts = [card]
        for x, colour in (
            (MENU_LEFT, (1, 1, 1, 1)),
            (MENU_LEFT + MENU_COLUMN, (0.75, 0.85, 1.0, 1)),
        ):
            parts.append(
                OnscreenText(
                    text="",
                    pos=(x, MENU_TOP),
                    scale=MENU_SCALE,
                    fg=colour,
                    align=TextNode.ALeft,
                    mayChange=True,
                )
            )
        for part in parts:
            part.hide()
        return parts

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
        self.accept("arrow_left", self._left)
        self.accept("arrow_right", self._right)
        self.accept("arrow_up", self._menu_key, [-1, 0])
        self.accept("arrow_down", self._menu_key, [1, 0])
        self.accept("escape", self.userExit)
        # Space ends a step that runs until the rider says so.
        self.accept("space", self.ride.end_open_step)
        # Tab opens the settings, and the arrows move about in it while it is up.
        self.accept("tab", self._toggle_menu)
        self.accept("enter", self._menu_enter)

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

    def _left(self) -> None:
        """Left changes a setting while the menu is up, and steers when it is not."""
        if self.menu is None:
            self.ride.steer(Steer.LEFT)
        else:
            self._menu_key(0, -1)

    def _right(self) -> None:
        if self.menu is None:
            self.ride.steer(Steer.RIGHT)
        else:
            self._menu_key(0, 1)

    def _toggle_menu(self) -> None:
        """Open the settings, or close them and keep what was chosen.

        Saving on the way out rather than on every keystroke: a rider stepping
        through the trainer list is looking, not choosing, and writing the file
        thirty times would make the last look the decision.
        """
        if self.menu is None:
            self.menu = SetupMenu(scanner=self._scan_for_sensors)
        else:
            self.menu.save()
            self.ride.reconsider(self.menu.simulated_watts)
            self.menu = None
        self._update_menu()

    def _scan_for_sensors(self, seconds: float) -> Sequence[Found]:
        """Ask the radios who is there, from inside the window.

        The scan runs on the sensor loop's own thread and this waits for it,
        which freezes the picture for a few seconds. That is the honest thing
        for a menu: a rider who pressed "scan" is waiting for an answer, and a
        world sliding past underneath while they wait is not useful to them.
        """
        from app.sensors.discovery import default_transports
        from app.sensors.manager import DeviceManager

        manager = DeviceManager(hub=self.ride.hub, transports=default_transports())
        found = self.ride.on_sensor_loop(manager.scan(seconds), seconds + 5.0)
        return [Found(device.id, device.label) for device in found]

    def _menu_enter(self) -> None:
        if self.menu is None:
            return
        self.menu.activate()
        self._update_menu()

    def _menu_key(self, rows: int, values: int) -> None:
        if self.menu is None:
            return
        if rows:
            self.menu.move(rows)
        if values:
            self.menu.change(values)
        self._update_menu()

    def _update_menu(self) -> None:
        if self.menu_text is None:
            return
        card, labels, readings = self.menu_text
        if self.menu is None:
            for part in self.menu_text:
                part.hide()
            if self.hud is not None:
                self.hud.show()
            return
        # The ride's numbers are not what a rider is reading while they are in
        # the settings, and they show through the panel from the same layer.
        if self.hud is not None:
            self.hud.hide()
        left = [self.translate("Settings"), ""]
        right = ["", ""]
        for name, reading in self.menu.columns():
            left.append(name)
            right.append(reading)
        left += ["", self.menu.summary, "", self.translate("Press tab to close")]
        right += ["", "", "", ""]
        # The card is the same block of text drawn invisibly, so its background
        # is exactly the size of what is on it however many rows there are -
        # and a menu that grows a row cannot outgrow its own panel.
        card.setText("\n".join(f"{line:<64}" for line in left))
        labels.setText("\n".join(left))
        readings.setText("\n".join(right))
        for part in self.menu_text:
            part.show()

    def _place_companions(self) -> None:
        """Draw whoever else is on the road: make markers, move them, take them
        away again when their rider is gone.

        Markers are kept by id rather than rebuilt, because riders come and go
        mid-ride over a network and rebuilding the scene graph every frame for
        that would be the wrong shape to have started with.
        """
        present = self.ride.companions
        for rider in departed(self.companions, present):
            self.companions.pop(rider).removeNode()
        for companion in present:
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
        # At the junction itself, not a fixed distance ahead of the rider: on a
        # bend, straight ahead is out in the grass.
        at = upcoming.point
        self.arrow.setPos(at.x, at.y, at.z + ARROW_HEIGHT_M)
        # Stood up to face the rider, like a sign over the road, with the
        # arrow turned within it: flat it is edge-on from the saddle, and
        # pointing down it says "here" rather than "this way".
        # A node faces +Y at H=0 and turns left as H grows, so a sign whose
        # face is to look back down the road at the rider sits at heading - 90.
        # Pitching it a quarter turn stands it upright; rolling it within its
        # own plane is what makes it point left or right.
        self.arrow.setHpr(
            math.degrees(self.state.heading_rad) - 90.0,
            90.0,
            upcoming.rank * ARROW_LEAN_DEG,
        )
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
            lines.append(self._junction_line(state.upcoming))
        lines += self._company_lines()
        lines += self._workout_lines()
        lines += self._standing_lines()
        self.hud.setText("\n".join(lines))

    def _standing_lines(self) -> list[str]:
        """Say what this ride is, when it is not a rider on a trainer.

        Both cases are worth a line on the screen. A simulated ride looks
        exactly like a real one from the saddle, and finding out afterwards
        that the numbers were invented is worse than being told now. A rider
        with nothing connected is standing still and needs to know why.
        """
        if self.ride.setup.simulated:
            return ["", self.translate("Simulated ride - not recorded")]
        if self.ride.rider_source is None and self.ride.sensors is None:
            return ["", self.translate("No sensors connected")]
        return []

    def _junction_line(self, upcoming: UpcomingJunction) -> str:
        """Which way the rider is about to go, in words a person uses.

        Not the name of the segment they are about to be on: `main-3` is how
        the world is stored, not something to tell somebody on a bicycle.
        """
        words = {-1: "left", 0: "straight on", 1: "right"}[upcoming.rank]
        return f"{self.translate(words)} in {upcoming.distance_m:.0f} m"

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
        # A picture is drawn by riding to the moment it shows, and nobody is
        # pedalling for it.
        RideSetup(world_id=world_id, route_id=route_id, simulated_watts=power_w),
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


def point_panda_at_its_own_files() -> str | None:
    """Tell a frozen Panda3D where its own files went.

    Two separate things are lost in a frozen build, and the first hides the
    second: the `.prc` files that say a window should be opened with `pandagl`,
    and the directory that module is actually in. Fixing only the path leaves
    an application that has been told nothing to load; fixing only the config
    leaves one that cannot find what it was told to load. Both, in that order.

    Running from source there is nothing to fix, and this does nothing.
    """
    configuration = panda_config_dir()
    if configuration is not None:
        # Confauto.prc before Config.prc, which is the order Panda3D reads them
        # in and the order they override one another in.
        for prc in sorted(configuration.glob("*.prc")):
            loadPrcFile(Filename.fromOsSpecific(str(prc)))
    directory = panda_plugin_dir()
    if directory is None:
        return None
    # After the files above, so that a `plugin-path` in one of them cannot put
    # the deduction we are working around back. Panda3D also has its own idea
    # of what a path looks like, which is not the operating system's on Windows.
    path = Filename.fromOsSpecific(str(directory)).getFullpath()
    loadPrcFileData("frozen", f"plugin-path {path}")
    return path


def display_modules_available() -> tuple[str, ...]:
    """The kinds of window this build can actually open.

    Empty means the application will not start, however well everything else
    was packaged - so the smoke test asks, rather than trusting that a build
    which imports cleanly can also draw.
    """
    point_panda_at_its_own_files()
    selection = GraphicsPipeSelection.getGlobalPtr()
    selection.loadAuxModules()
    return tuple(
        selection.getPipeType(index).getName()
        for index in range(selection.getNumPipeTypes())
    )


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
