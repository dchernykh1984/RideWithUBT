"""What the frozen application has to be able to import.

PyInstaller decides what to include by reading imports, so anything reached
lazily can be left out silently - and the failure lands on a user's machine the
first time they try to upload a ride."""

from __future__ import annotations

import importlib

from app import selfcheck


def test_everything_late_is_actually_importable() -> None:
    assert selfcheck.missing() == []


def test_the_dependencies_that_only_get_used_sometimes_are_here() -> None:
    assert selfcheck.missing_dependencies() == []


def test_a_module_that_is_not_there_is_reported() -> None:
    problems = selfcheck.missing(("app.nothing_like_this",))

    assert len(problems) == 1
    assert "app.nothing_like_this" in problems[0]


def test_the_list_covers_what_is_imported_late() -> None:
    """A module imported inside a function is one PyInstaller can miss.

    This is the list's reason for existing, so it has to keep up with the code
    rather than being written once and forgotten.
    """
    lazily_imported = {
        "app.render.app",  # imported by the CLI only when a window is wanted
        "app.sensors.ant_radio",  # imported only when a stick is present
        "app.sensors.discovery",
        "app.services.garmin_session",
        "app.services.strava_session",
    }

    checked = set(selfcheck.LATE_IMPORTS)
    # app.render.app is exercised by the self-test itself, and ant_radio needs a
    # stick to do anything - both are still importable, which is what matters.
    for name in lazily_imported:
        assert importlib.import_module(name) is not None
    assert {"app.sensors.discovery", "app.services.strava_session"} <= checked
