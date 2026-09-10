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
from dataclasses import replace
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
    SamplerState,
    TextNode,
    Texture,
    TextureStage,
    WindowProperties,
    loadPrcFile,
    loadPrcFileData,
)

from app import paths
from app.core.companions import departed
from app.core.figure import BOTTOM_BRACKET_M, Cranks, Rider
from app.core.preferences import Found, SetupMenu
from app.core.ride import DEFAULT_POWER_W, DEFAULT_WORLD, Ride, RideSetup
from app.core.rows import Layout
from app.core.session import RideState
from app.core.startscreen import StartScreen
from app.frozen import panda_config_dir, panda_plugin_dir
from app.render.cyclist import Cyclist
from app.render.geometry import arrow_node, geom_node
from app.settings import Settings
from app.workout.model import DurationKind, Workout
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
#: Space between the panel's text and the edge of its background, in ems.
MENU_PAD = 0.5
#: How hard to work at surfaces seen at a shallow angle, which for a road is
#: all of them. Sixteen is what a graphics card of the last decade does without
#: noticing; the road is the thing a rider looks at for an hour.
ANISOTROPY = 16

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
        self.cranks = Cranks()
        self.rider = self._build_rider()
        self.companions: dict[str, NodePath] = {}
        self.arrow = self._build_arrow()
        if not headless:
            self._prepare_window(offscreen=offscreen)
        self.font = None if headless else self._font()
        self.hud = self._build_hud(headless=headless or offscreen)
        self.menu: SetupMenu | None = None
        self.menu_text = self._build_menu_text(headless=headless or offscreen)
        # A picture of the world and the smoke test are not somebody sitting
        # down to ride, so neither opens on a front screen.
        self.screen: StartScreen | None = (
            None if headless or offscreen else self._build_start_screen()
        )
        self._light()
        self._bind_keys()
        self._redraw_panel()
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
        # Smaller copies for what is far away, and filtering that copes with a
        # surface seen almost edge-on. Without them a road at two hundred
        # metres is a shimmer of dashes where its edge line should be, and a
        # building's windows are a moire of stripes - the whole circuit
        # crawled, and that is the road being sampled once per pixel.
        texture.setMinfilter(SamplerState.FT_linear_mipmap_linear)
        texture.setMagfilter(SamplerState.FT_linear)
        texture.setAnisotropicDegree(ANISOTROPY)
        node.setTexture(texture)
        if repeat != 1.0:
            node.setTexScale(TextureStage.getDefault(), repeat, repeat)

    def _refresh_rider(self) -> None:
        """Put the rider on the bicycle they just chose.

        A rider sitting up on the hoods and one on a time trial bicycle are two
        quite different shapes, and that difference is the whole reason one is
        faster - drawing them the same would say the choice does not matter.
        """
        wanted = (self.ride.settings or Settings.load()).virtual_bike_id
        if wanted == self.rider.rider.bike_id:
            return
        self.rider.root.removeNode()
        self.rider = Cyclist(self.render, Rider(bike_id=wanted))

    def _build_rider(self) -> Cyclist:
        """A person on a bicycle, with legs that go round.

        A triangle told a rider where they were and nothing else. Legs turning
        say something no number does: that the pedals are going round, and how
        fast.
        """
        return Cyclist(self.render, Rider(bike_id=Settings.load().virtual_bike_id))

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

    def _font(self) -> object | None:
        """A typeface with Cyrillic in it.

        Panda3D's own font has none, so Russian and Kazakh came out as rows of
        empty boxes - two of the three languages this application speaks. The
        one that ships with it covers both, including the letters Kazakh needs
        that Russian does not.
        """
        path = paths.packaged("fonts", "DejaVuSans.ttf")
        if not path.exists():  # pragma: no cover - it ships with the app
            return None
        font = self.loader.loadFont(Filename.fromOsSpecific(str(path)).getFullpath())
        if font is not None:
            # Rendered big and scaled down, so text stays crisp at the size a
            # panel draws it rather than being a blur of a small bitmap.
            font.setPixelsPerUnit(80)
        return font

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
            font=self.font,
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
            font=self.font,
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
                    font=self.font,
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
        """Left and right move the junction arrow; nothing else steers.

        While a panel is up the same keys work the panel instead - and so does
        the mouse, because a menu that only answers to the arrows is a menu
        somebody reaches for with a mouse and finds does nothing.
        """
        self.accept("arrow_left", self._left)
        self.accept("arrow_right", self._right)
        self.accept("arrow_up", self._menu_key, [-1, 0])
        self.accept("arrow_down", self._menu_key, [1, 0])
        self.accept("escape", self._show_start_screen)
        # Space ends a step that runs until the rider says so.
        self.accept("space", self._space)
        # Tab opens the settings, and the arrows move about in it while it is up.
        self.accept("tab", self._toggle_menu)
        self.accept("enter", self._menu_enter)
        self.accept("mouse1", self._click)
        # Text, for fields that are typed into rather than stepped through.
        # There is no keyboard without a window, and a picture of the world is
        # taken without one.
        if self.buttonThrowers:
            self.buttonThrowers[0].node().setKeystrokeEvent("keystroke")
        self.accept("keystroke", self._typed)
        self.accept("backspace", self._backspace)
        self.accept("wheel_up", self._scroll, [1])
        self.accept("wheel_down", self._scroll, [-1])

    def _typed(self, character: str) -> None:
        """A keystroke, while a number field is open."""
        panel = self._panel()
        if panel is None or panel.typing is None:
            return
        panel.key(character)
        self._redraw_panel()

    def _backspace(self) -> None:
        panel = self._panel()
        if panel is None or panel.typing is None:
            return
        panel.backspace()
        self._redraw_panel()

    def _space(self) -> None:
        """Go, on the front screen; end an open workout step while riding."""
        panel = self._panel()
        if panel is not None and panel.busy:
            panel.key(" ")
            return
        if self.screen is not None:
            self._start_riding()
        else:
            self.ride.end_open_step()

    def _tick(self, task: Task) -> int:
        now = self._clock.getFrameTime()
        self._follow_mouse()
        if self.screen is not None:
            # The world stands still behind the front screen. Nobody is riding
            # yet, and a lap ticking past while a rider picks a circuit would
            # be a lap they did not do.
            self._place_camera()
            return Task.cont
        self.ride.advance(self._clock.getDt(), now)
        self._place_rider()
        self._place_companions()
        self._place_camera()
        self._place_arrow()
        self._update_hud()
        return Task.cont

    def _place_rider(self) -> None:
        point = self.state.point
        # Everything about the figure is measured from its bottom bracket, so
        # that is what sits above the road rather than the road's own height.
        self.rider.root.setPos(point.x, point.y, point.z + BOTTOM_BRACKET_M)
        self.rider.root.setH(math.degrees(self.state.heading_rad))
        # The cadence the sensors are reporting, or a plain average when
        # nothing is: a figure sitting frozen on a moving bicycle looks broken,
        # and that is what most riders will see first.
        self.cranks.advance(self._clock.getDt(), self.state.cadence_rpm)
        self.rider.pedal_at(self.cranks.angle_rad)

    def _left(self) -> None:
        """Left changes a setting while a panel is up, and steers when none is."""
        if self._panel() is None:
            self.ride.steer(Steer.LEFT)
        else:
            self._menu_key(0, -1)

    def _right(self) -> None:
        if self._panel() is None:
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
            self.menu = SetupMenu(scanner=self._scan_for_sensors, speaks=self.translate)
        else:
            self.menu.save()
            self.ride.reconsider(self.ride.setup.simulated_watts)
            self._refresh_rider()
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

    def _build_start_screen(self) -> StartScreen:
        """What the application opens on: pick a circuit, and go."""
        from app.workout import library

        return StartScreen(
            speaks=self.translate,
            workouts=library.load_library().workouts,
            on_ride=self._start_riding,
            on_settings=self._toggle_menu,
            on_quit=self.userExit,
        )

    def _start_riding(self) -> None:
        """Leave the front screen and begin, on whatever was chosen there."""
        if self.screen is None:  # pragma: no cover - only reachable from it
            return
        chosen = self.screen.save()
        workout = self.screen.chosen_workout
        watts = self.screen.simulated_watts
        self.screen = None
        self._hide_panel()
        if watts != self.ride.setup.simulated_watts:
            self.ride.reconsider(watts)
        if (
            chosen.world_id != self.ride.setup.world_id
            or chosen.route_id != (self.ride.setup.route_id or "")
            or workout is not self.ride.setup.workout
        ):
            self._change_ride(chosen, workout, watts)

    def _change_ride(
        self, chosen: Settings, workout: Workout | None, watts: float | None
    ) -> None:
        """Build the ride the rider asked for, and the scene that goes with it.

        The ride being replaced is finished first. A rider who does a lap, goes
        back to the front screen and picks a different route would otherwise
        have thrown that lap away without being told - the recording lives on
        the ride, and this is the only place one is discarded.
        """
        self.ride.save()
        self.ride.release()
        world_changed = chosen.world_id != self.ride.setup.world_id
        self.ride = Ride(
            replace(
                self.ride.setup,
                world_id=chosen.world_id,
                route_id=chosen.route_id or None,
                workout=workout,
                simulated_watts=watts,
            )
        )
        if not world_changed:
            return
        for node in (self.ground, self.track, self.buildings):
            if node is not None:
                node.removeNode()
        self.ground = self._build_ground()
        self.track = self._build_track()
        self.buildings = self._build_buildings()

    def _show_start_screen(self) -> None:
        """Escape: close an open field, then the panel, then the application."""
        panel = self._panel()
        if panel is not None and panel.busy:
            panel.cancel()
            self._redraw_panel()
            return
        if self.menu is not None:
            self._toggle_menu()
            return
        if self.screen is None:
            self.screen = self._build_start_screen()
            self._redraw_panel()
            return
        self.userExit()

    # The mouse. A menu that only answers to the arrows is a menu somebody
    # reaches for with a mouse and finds does nothing.

    def _panel(self) -> StartScreen | SetupMenu | None:
        return self.menu if self.menu is not None else self.screen

    def _layout(self) -> Layout | None:
        if self.menu_text is None:
            return None
        node = self.menu_text[1].textNode
        return Layout(
            top=MENU_TOP,
            line_height=MENU_SCALE * node.getLineHeight(),
            #: The title and the blank line under it, which are not rows.
            header=2,
        )

    def _row_under_the_mouse(self) -> int | None:
        panel, layout = self._panel(), self._layout()
        # There is no mouse without a window, and a picture of the world is
        # taken without one.
        watcher = self.mouseWatcherNode
        if panel is None or layout is None or watcher is None or not watcher.hasMouse():
            return None
        # The mouse is reported in render2d, where y runs -1 to 1 up the window;
        # the panel is laid out in aspect2d, which shares that vertical scale.
        return layout.row_at(self.mouseWatcherNode.getMouseY(), len(panel.rows))

    def _follow_mouse(self) -> None:
        """Mark whatever the pointer is over, the way a menu is expected to."""
        panel = self._panel()
        index = self._row_under_the_mouse()
        if panel is None or index is None:
            return
        if panel.point_at(index):
            self._redraw_panel()

    def _click(self) -> None:
        panel = self._panel()
        index = self._row_under_the_mouse()
        if panel is None or index is None:
            return
        panel.point_at(index)
        # A click opens the field: a list to pick from, or a number to type
        # into. Stepping a weight to 83 kg one arrow press at a time is
        # eighty-three key presses, and a list of forty trainers is a list
        # nobody reaches the end of.
        panel.activate()
        self._redraw_panel()

    def _scroll(self, by: int) -> None:
        panel = self._panel()
        if panel is None:
            return
        index = self._row_under_the_mouse()
        if index is not None:
            panel.point_at(index)
        panel.change(by)
        self._redraw_panel()

    def _redraw_panel(self) -> None:
        if self.menu is not None:
            self._update_menu()
        elif self.screen is not None:
            self._draw_start_screen()

    def _menu_enter(self) -> None:
        panel = self._panel()
        if panel is None:
            return
        panel.activate()
        self._redraw_panel()

    def _menu_key(self, rows: int, values: int) -> None:
        panel = self._panel()
        if panel is None:
            return
        if rows:
            panel.move(rows)
        if values:
            panel.change(values)
        self._redraw_panel()

    def _update_menu(self) -> None:
        if self.menu is None:
            self._hide_panel()
            return
        self._draw_panel(
            self.menu.columns(),
            self.translate(self.menu.title or "Settings"),
            "" if self.menu.busy else self.menu.summary,
            footer=self._panel_footer(self.menu),
        )

    def _label(self, name: str) -> str:
        """A row's label in the rider's language, marker and all.

        A screen that says it speaks three languages and then labels every row
        in English speaks one.

        A row comes with a marker in front of it and a heading comes without
        one, which is how the two are told apart here: the marker is put back
        afterwards because it is punctuation rather than a word, and a heading
        is shouted afterwards for the same reason.
        """
        plain = name.lstrip("> ")
        if not plain:  # pragma: no cover - every row has a name
            return name
        marker = name[: len(name) - len(plain)]
        translated = self.translate(plain)
        return f"{marker}{translated}" if marker else translated.upper()

    def _panel_footer(self, panel: StartScreen | SetupMenu) -> str:
        """What to do next, which depends on what is open."""
        if panel.typing is not None:
            return self.translate("Type a number, enter to keep it")
        if panel.picking is not None:
            return self.translate("Enter or click to choose, escape to go back")
        if panel is self.screen:
            return self.translate("Click a line to change it, space to ride")
        return self.translate("Click a line to change it, tab to close")

    def _draw_panel(
        self,
        rows: list[tuple[str, str]],
        title: str,
        summary: str,
        footer: str = "",
    ) -> None:
        """Draw a list of rows as a panel: title, two columns, a line beneath.

        The front screen and the settings are the same panel with different
        rows in it, so they are drawn by the same code - which is also what
        makes one layout enough for the mouse to find a row in either.
        """
        if self.menu_text is None:
            return
        card, labels, readings = self.menu_text
        # The ride's numbers are not what a rider is reading while a panel is
        # up, and they show through it from the same layer.
        if self.hud is not None:
            self.hud.hide()
        left = [title, ""]
        right = ["", ""]
        for name, reading in rows:
            left.append(self._label(name))
            right.append(self.translate(reading) if reading else reading)
        # Only the lines there is something to say on: a panel with nothing
        # underneath it should not reserve four rows of empty card for it.
        for line in (summary, footer):
            if line:
                left += ["", line]
                right += ["", ""]
        labels.setText("\n".join(left))
        readings.setText("\n".join(right))
        # The card is sized from what the font actually did with the text, not
        # from a count of characters padded with spaces. The font is
        # proportional: padding lines nothing up and a long line walks straight
        # off the edge of its own background, which is what happened.
        card.setText("\n".join(left))
        across = max(
            labels.textNode.getWidth(),
            MENU_COLUMN / MENU_SCALE + readings.textNode.getWidth(),
        )
        # getHeight measures the block from the first line's baseline, so the
        # last line hangs below it by its own descender.
        down = card.textNode.getHeight()
        card.textNode.setCardActual(-MENU_PAD, across + MENU_PAD, -down, 1.0)
        for part in self.menu_text:
            part.show()

    def _draw_start_screen(self) -> None:
        if self.screen is None:  # pragma: no cover - callers check first
            return
        self._draw_panel(
            self.screen.columns(),
            self.translate(self.screen.title) if self.screen.title else "RideWithUBT",
            "",
            footer=self._panel_footer(self.screen),
        )

    def _hide_panel(self) -> None:
        """Take the panel away - unless there is another one behind it.

        Closing the settings from the front screen leaves the front screen up,
        and the ride's numbers do not belong over that either.
        """
        if self.menu_text is None:
            return
        if self.screen is not None:
            self._draw_start_screen()
            return
        for part in self.menu_text:
            part.hide()
        if self.hud is not None:
            self.hud.show()

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
