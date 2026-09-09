"""The promise this application makes, enforced rather than documented.

RideWithUBT is offline-first in the strong sense: usable with the network cable
pulled, with no account and no server of its own. The only traffic is what the
rider asks for - a workout fetched from their Garmin account, a ride uploaded to
their Strava - and it goes straight from their machine to that service.

That is a claim about the whole codebase, and claims about a whole codebase rot.
So it is checked: nothing outside `app/services/` may reach for the network at
all. A module that starts doing so fails here, with this docstring next to it.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

APP_DIR = Path(__file__).resolve().parent.parent / "app"
SERVICES_DIR = APP_DIR / "services"

#: Packages that talk to something over a network, or wrap something that does.
NETWORKING = frozenset(
    {
        "aiohttp",
        "garminconnect",
        "http",
        "httpx",
        "requests",
        "socket",
        "stravalib",
        "urllib",
        "urllib3",
        "websockets",
        "xmlrpc",
    }
)
#: Radios are not networks. Bluetooth and ANT+ talk to what is in the room, which
#: is the opposite of what this rule is about.
ALLOWED_RADIOS = frozenset({"bleak", "openant"})


def app_modules() -> list[Path]:
    return sorted(
        path for path in APP_DIR.rglob("*.py") if SERVICES_DIR not in path.parents
    )


def imported_roots(source: str) -> set[str]:
    roots: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".", 1)[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            roots.add(node.module.split(".", 1)[0])
    return roots


@pytest.mark.parametrize("module", app_modules(), ids=lambda path: path.name)
def test_only_the_services_reach_the_network(module: Path) -> None:
    offenders = imported_roots(module.read_text(encoding="utf-8")) & NETWORKING

    assert not offenders, (
        f"{module.relative_to(APP_DIR.parent)} imports {sorted(offenders)}; "
        "only app/services may talk to anything off this machine"
    )


def test_the_guard_is_looking_at_the_right_files() -> None:
    """A path mistake here would let the rule pass for everything."""
    names = {path.name for path in app_modules()}

    assert {"cli.py", "session.py", "hub.py", "app.py"} <= names
    assert "upload.py" not in names, "app/services is the exception, not the subject"


def test_the_radios_are_not_caught_by_this() -> None:
    """Bluetooth talks to what is in the room; that is the opposite of a network."""
    assert not (ALLOWED_RADIOS & NETWORKING)
    ble = imported_roots((APP_DIR / "sensors" / "ble.py").read_text(encoding="utf-8"))
    assert "bleak" in ble
    assert not ble & NETWORKING


def test_nothing_in_the_app_phones_home() -> None:
    """No telemetry, no update check, no analytics - not even in the services.

    Those may talk to Garmin and Strava, and to nowhere else.
    """
    allowed = {"garminconnect", "stravalib", "urllib"}
    for module in SERVICES_DIR.rglob("*.py"):
        reaching = imported_roots(module.read_text(encoding="utf-8")) & NETWORKING
        assert reaching <= allowed, (
            f"{module.name} reaches {sorted(reaching - allowed)}"
        )
