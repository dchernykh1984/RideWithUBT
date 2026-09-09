"""Logging in to Garmin Connect.

The one place a real client is built, kept apart from everything that uses one so
the rest is tested against a fake. The password comes from the operating system's
credential store; it is never written into the data directory and never sent
anywhere but Garmin.
"""

from __future__ import annotations

from app.services.credentials import Credential, secret
from app.services.garmin import GarminWorkouts

SERVICE = "garmin"


class GarminLoginError(RuntimeError):
    """Garmin would not let us in."""


def credential_for(username: str) -> Credential:
    return Credential(service=SERVICE, username=username)


def connect_to_garmin(username: str) -> GarminWorkouts:  # pragma: no cover - network
    """Log in and return something that can read the account's workouts."""
    from garminconnect import Garmin

    password = secret(credential_for(username))
    try:
        client = Garmin(username, password)
        client.login()
    except Exception as error:
        raise GarminLoginError(f"could not sign in to Garmin as {username}") from error
    return GarminWorkouts(client=client)
