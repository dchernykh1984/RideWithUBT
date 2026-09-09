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

import importlib

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
LATE_DEPENDENCIES = ("bleak", "fitparse", "garminconnect", "keyring", "openant")


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
    """The same for the packages a frozen build might have left behind.

    `fitparse` is deliberately not in this list's own dependencies: it is a
    testing tool. It is checked because a build that somehow ships it is not
    wrong, only heavier - and because leaving it out of the check would hide a
    packaging change that swept it in.
    """
    return [
        name
        for name in LATE_DEPENDENCIES
        if importlib.util.find_spec(name) is None  # type: ignore[attr-defined]
    ]
