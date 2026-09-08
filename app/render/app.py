"""The Panda3D window.

Deliberately thin for now: it opens a window and draws nothing but the empty
world. Its job in this first version is to prove the engine is packaged and
starts on all three platforms; the world, the rider and the HUD land on top of
it.
"""

from __future__ import annotations

from collections.abc import Callable

from direct.showbase.ShowBase import ShowBase
from panda3d.core import WindowProperties, loadPrcFileData

# Frames the self-test renders before it is satisfied the engine really runs.
SELFTEST_FRAMES = 5


class RideApp(ShowBase):
    """The application window."""

    def __init__(self, translate: Callable[[str], str], *, headless: bool = False):
        if headless:
            # No graphics pipe at all: the frozen-app smoke test in CI runs on a
            # machine with no display, and an offscreen buffer would still need
            # one on some drivers.
            loadPrcFileData("headless", "window-type none")
        super().__init__()
        self.translate = translate
        if not headless:
            properties = WindowProperties()
            properties.setTitle(f"RideWithUBT - {translate('Virtual training world')}")
            self.win.requestProperties(properties)
            self.setBackgroundColor(0.53, 0.71, 0.87)

    def run_frames(self, count: int) -> None:
        """Render a fixed number of frames and return, instead of looping forever."""
        for _ in range(count):
            self.taskMgr.step()


def selftest(translate: Callable[[str], str]) -> None:
    """Boot the engine headless and render a few frames.

    Called by the packaged app in CI: a Panda3D that failed to freeze correctly
    raises here rather than on a user's machine.
    """
    app = RideApp(translate, headless=True)
    try:
        app.run_frames(SELFTEST_FRAMES)
    finally:
        app.destroy()
