"""Look at what a change actually did.

Tests say the arithmetic is right. They cannot say the rider looks like a
person, that a panel fits on its own background, that a road stops shimmering
at two hundred metres, or that a label came out in Russian - and every one of
those has shipped broken past a green pipeline.

So this runs the application, puts it in a named situation and takes a picture,
and drives the keyboard through the real key handling rather than around it.
Run it after a change that anybody can see:

    uv run python scripts/look.py                 # every scene
    uv run python scripts/look.py start settings  # just these
    uv run python scripts/look.py --into /tmp/x   # somewhere of your choosing

Then open the pictures. That is the point: nothing here asserts anything, and
a scene that renders is not a scene that looks right.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

DEFAULT_INTO = Path("build-data/looks")


@dataclass(frozen=True)
class Scene:
    """One picture: where the ride has got to, and what is on the screen."""

    name: str
    what: str
    seconds: float = 0.0
    language: str = "en"
    bike_id: str = "road"
    watts: float = 220.0
    #: A panel to open, and a row on it to work: the front screen, the
    #: settings, a list laid out, a number being typed into.
    panel: str = ""
    open_row: str = ""
    typing: str = ""
    #: A value to pick in the open list, and whether to press Save afterwards -
    #: which is how a language chosen in the settings is looked at on the
    #: screen it comes back to.
    choose: str = ""
    save: bool = False
    #: Where the camera is, as a rider who dragged it there would have it:
    #: round from behind, up from the road, and how far off.
    turn_deg: float = 0.0
    lift_deg: float = 0.0
    distance_m: float = 0.0
    crank_deg: float = 90.0

    @property
    def swung(self) -> bool:
        """Whether this scene moves the camera off where a ride puts it."""
        return bool(self.turn_deg or self.lift_deg or self.distance_m)


SCENES: tuple[Scene, ...] = (
    Scene("start", "the front screen, as the application opens", panel="start"),
    Scene(
        "start-ru",
        "the same screen in Russian - the alphabet and the labels",
        panel="start",
        language="ru",
    ),
    Scene(
        "start-kk",
        "and in Kazakh, which needs letters Russian does not",
        panel="start",
        language="kk",
    ),
    Scene("settings", "the settings, every row of them", panel="settings"),
    Scene(
        "settings-ru",
        "the settings in Russian - the screen a rider spends longest on",
        panel="settings",
        language="ru",
    ),
    Scene(
        "list",
        "a list laid out to pick from, with the one in use marked",
        panel="start",
        open_row="Route",
    ),
    Scene(
        "typing",
        "a number being typed into, with what has been typed so far",
        panel="start",
        open_row="Ride without sensors",
        typing="24",
    ),
    Scene(
        "trainers",
        "a list longer than the screen, a windowful at a time",
        panel="settings",
        open_row="Trainer",
    ),
    Scene(
        "language",
        "Russian chosen and saved - the screen it comes back to speaks it",
        panel="settings",
        open_row="Language",
        choose="ru",
        save=True,
    ),
    Scene("pits", "standing in the pit lane, where a ride begins", seconds=1.0),
    Scene("pit-exit", "rejoining the circuit - the merge, and the markings", 40.0),
    Scene("junction", "the sign at a junction, and what it says", 66.0),
    Scene("corner", "a corner, which should be a curve and not a polygon", 118.0),
    Scene("straight", "the pit straight: buildings, and the road far away", 460.0),
    Scene(
        "rider",
        "the rider, from beside them",
        40.0,
        turn_deg=90.0,
        lift_deg=8.0,
        distance_m=6.0,
    ),
    Scene(
        "rider-tt",
        "and on a time trial bicycle, which is a different shape",
        40.0,
        bike_id="tt",
        turn_deg=90.0,
        lift_deg=8.0,
        distance_m=6.0,
    ),
    Scene(
        "view-side",
        "the view dragged a quarter turn round the rider, mid-ride",
        460.0,
        turn_deg=90.0,
        lift_deg=12.0,
        distance_m=14.0,
    ),
    Scene(
        "view-front",
        "and all the way round, looking back down the road at them",
        460.0,
        turn_deg=180.0,
        lift_deg=10.0,
        distance_m=10.0,
    ),
    Scene(
        "view-above",
        "dragged upwards, which is as far up as it goes",
        460.0,
        turn_deg=40.0,
        lift_deg=70.0,
        distance_m=20.0,
    ),
)


@dataclass
class Look:
    """The application, held open long enough to be looked at."""

    into: Path
    app: Any = None
    taken: list[Path] = field(default_factory=list)

    def take(self, scene: Scene) -> Path:
        from panda3d.core import Filename

        self._open(scene)
        path = self.into / f"{scene.name}.png"
        self.app.win.saveScreenshot(Filename.fromOsSpecific(str(path)))
        self.taken.append(path)
        return path

    def _open(self, scene: Scene) -> None:
        from app import i18n
        from app.core.ride import Ride, RideSetup
        from app.render.app import SELFTEST_FRAMES, RideApp
        from app.settings import Settings

        settings = Settings.load()
        settings.virtual_bike_id = scene.bike_id
        settings.save()

        self.app = RideApp(
            i18n.load(scene.language),
            ride=Ride(RideSetup(simulated_watts=scene.watts)),
            offscreen=True,
        )
        # Offscreen deliberately draws no overlay - a picture of the world is
        # what that mode is for. Put it back, because the overlay is half of
        # what there is to look at.
        self.app.font = self.app._font()
        self.app.hud = self.app._build_hud(headless=False)
        self.app.menu_text = self.app._build_menu_text(headless=False)
        self.app.popup_text = self.app._build_popup_text(headless=False)
        self._panel(scene)
        self.app.ride_forward(scene.seconds)
        self.app.run_frames(SELFTEST_FRAMES)
        if scene.swung:
            self._swing_the_view(scene)

    def _panel(self, scene: Scene) -> None:
        """Open a screen and work a row on it, through the real key handling."""
        from app.core.preferences import KEEP, SetupMenu
        from app.core.startscreen import StartScreen

        if scene.panel == "settings":
            # The front screen stays underneath: the settings are reached from
            # it, and closing them comes back to it.
            self.app.screen = StartScreen(speaks=self.app.translate)
            self.app.menu = SetupMenu(
                speaks=self.app.translate,
                scanner=lambda _s: _pretend_sensors(),
            )
            self.app.menu.scan()
        elif scene.panel == "start":
            self.app.screen = StartScreen(speaks=self.app.translate)
        else:
            self.app.screen = None
        panel = self.app.menu or self.app.screen
        if panel is not None and scene.open_row:
            wanted = panel.row(scene.open_row)
            panel.selected = next(
                index for index, row in enumerate(panel.rows) if row is wanted
            )
            self.app._menu_enter()
            for character in scene.typing:
                self.app.messenger.send("keystroke", [character])
            if scene.choose and panel.picking is not None:
                panel.picking.row.point_at(scene.choose)
                panel.picking.index = panel.picking.row.index
                self.app._menu_enter()
        if scene.save and self.app.menu is not None:
            self.app.menu.selected = next(
                index
                for index, row in enumerate(self.app.menu.rows)
                if row.name == KEEP
            )
            self.app._menu_enter()
        self.app._redraw_panel()

    def _swing_the_view(self, scene: Scene) -> None:
        """Put the camera where a rider dragging the mouse would have put it.

        Through the same `Chase` the mouse drives, rather than by placing the
        camera by hand: a picture taken some other way is a picture of
        something the application does not do.
        """
        import math

        self.app.taskMgr.remove("ride")
        self.app.chase.turn_deg = scene.turn_deg
        self.app.chase.lift_deg = scene.lift_deg
        self.app.chase.distance_m = scene.distance_m
        self.app._place_camera()
        self.app.rider.pedal_at(math.radians(scene.crank_deg))
        self.app.graphicsEngine.renderFrame()
        self.app.graphicsEngine.renderFrame()

    def close(self) -> None:
        if self.app is not None:
            self.app.destroy()
            self.app = None


def _pretend_sensors() -> list[Any]:
    from app.core.preferences import Found

    return [
        Found("ble:D2:4C:8A:11", "Wahoo KICKR CORE"),
        Found("ble:E1:07:3B:5F", "Garmin HRM-Pro"),
        Found("ant:26714", "Speed and cadence"),
    ]


def main(argv: list[str]) -> int:
    into = DEFAULT_INTO
    if "--into" in argv:
        at = argv.index("--into")
        into = Path(argv[at + 1])
        argv = argv[:at] + argv[at + 2 :]
    wanted = [scene for scene in SCENES if not argv or scene.name in argv]
    unknown = set(argv) - {scene.name for scene in SCENES}
    if unknown:
        print(f"no such scene: {', '.join(sorted(unknown))}", file=sys.stderr)
        print(f"there is: {', '.join(scene.name for scene in SCENES)}")
        return 2
    into.mkdir(parents=True, exist_ok=True)
    for scene in wanted:
        # One application per picture: a ShowBase is process-global and does
        # not come back cleanly after being torn down.
        code = _in_its_own_process(scene, into)
        if code != 0:  # pragma: no cover - a scene that will not render
            print(f"{scene.name} did not render", file=sys.stderr)
            return code
        print(f"{into / (scene.name + '.png')}  - {scene.what}")
    print(f"\n{len(wanted)} to look at. Open them.")
    return 0


def _in_its_own_process(scene: Scene, into: Path) -> int:
    import subprocess

    # This interpreter, this file, and a scene name that came from the list
    # above - nothing here is anybody else's input.
    return subprocess.run(  # noqa: S603
        [sys.executable, __file__, "--one", scene.name, "--into", str(into)],
        capture_output=True,
        check=False,
    ).returncode


def _one(name: str, into: Path) -> int:
    scene = next(scene for scene in SCENES if scene.name == name)
    look = Look(into)
    try:
        look.take(scene)
    finally:
        look.close()
    return 0


if __name__ == "__main__":
    arguments = sys.argv[1:]
    if "--one" in arguments:
        at = arguments.index("--one")
        directory = Path(arguments[arguments.index("--into") + 1])
        raise SystemExit(_one(arguments[at + 1], directory))
    raise SystemExit(main(arguments))
