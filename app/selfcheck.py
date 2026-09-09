"""Proving the packaged application is whole.

A frozen application is not the application: PyInstaller works out what to
include by reading imports, and anything reached lazily - a Bluetooth backend, a
credential store, a service client - can be left out without a word. The failure
then happens on a user's machine, the first time they try to upload a ride.

So the self-test imports every part that a user reaches only sometimes, and CI
runs it against the frozen binary. It costs a second and it turns "your upload
crashed" into "the build failed".
"""

from __future__ import annotations

import importlib.util
import sys

#: Everything imported lazily, or only on a path a user might not take for weeks.
LATE_IMPORTS = (
    "app.sensors.ant",
    "app.sensors.ant_protocol",
    "app.sensors.ble",
    "app.sensors.ble_protocol",
    "app.sensors.control",
    "app.sensors.discovery",
    "app.sensors.loop",
    "app.sensors.manager",
    "app.services.credentials",
    "app.services.garmin",
    "app.services.garmin_session",
    "app.services.strava_session",
    "app.services.upload",
    "app.services.uploads",
    "app.storage.activity",
    "app.storage.fit",
    "app.trainer.capture",
    "app.workout.engine",
    "app.workout.garmin_format",
    "app.workout.library",
)
#: Third-party packages that are only reached when a rider actually uses them.
LATE_DEPENDENCIES = ("bleak", "garminconnect", "keyring", "openant", "stravalib")
#: Tools that belong to the tests and must not travel into a build. `fitparse`
#: reads the FIT files this app writes, which is a thing to check with, not to
#: ship - it was in the list above once, and the frozen build said so.
DEV_ONLY = ("fitparse", "pytest", "ruff")


def missing(modules: tuple[str, ...] = LATE_IMPORTS) -> list[str]:
    """Import each module, and report the ones that are not there."""
    problems = []
    for name in modules:
        try:
            importlib.import_module(name)
        except Exception as error:
            problems.append(f"{name}: {error}")
    return problems


def missing_dependencies() -> list[str]:
    """The same for the packages a frozen build might have left behind."""
    return [name for name in LATE_DEPENDENCIES if not _present(name)]


def stowaway_dev_tools() -> list[str]:
    """Test-only tools that ended up in a build, which only a build can have.

    Running from a checkout they are all present and all welcome, so this asks
    only of a frozen application - where they mean the packaging swept up the
    test suite.
    """
    if not getattr(sys, "frozen", False):
        return []
    return [name for name in DEV_ONLY if _present(name)]


def _present(name: str) -> bool:
    try:
        return importlib.util.find_spec(name) is not None
    except ImportError, ValueError:  # pragma: no cover - a broken installation
        return False
