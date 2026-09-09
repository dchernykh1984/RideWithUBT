"""Getting into Strava.

Strava is OAuth, which needs a browser once and then never again. The rider
registers their own API application - this app has no client of its own to hand
out, and holding one would put every rider's rides behind a key that is not
theirs - and the three secrets it produces go in the credential store.

After the first time, only the refresh token matters: it buys an access token
whenever one is needed, and the app stores the new refresh token each time,
because Strava rotates them.
"""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlencode

from app.services.credentials import Credential, secret, store

SERVICE = "strava"
# The names of the three slots in the credential store, not the secrets
# themselves - which is why the security lint is silenced here and only here.
CLIENT_ID = "client_id"
CLIENT_SECRET = "client_secret"  # noqa: S105
REFRESH_TOKEN = "refresh_token"  # noqa: S105

AUTHORIZE_URL = "https://www.strava.com/oauth/authorize"
# Strava demands a redirect even for an application with no web page to redirect
# to. localhost is the usual answer: the browser lands on nothing and the code is
# in the address bar.
REDIRECT_URI = "http://localhost/exchange_token"
# activity:write to upload, activity:read to see what came of it.
SCOPE = "activity:write,activity:read"


class StravaSetupError(RuntimeError):
    """Strava is not set up on this machine, or would not let us in."""


@dataclass(frozen=True)
class StravaKeys:
    """The three things Strava needs, each kept in the credential store."""

    @staticmethod
    def credential(name: str) -> Credential:
        return Credential(service=SERVICE, username=name)

    @classmethod
    def read(cls, name: str) -> str:
        return secret(cls.credential(name))

    @classmethod
    def write(cls, name: str, value: str) -> None:
        store(cls.credential(name), value)


def authorize_url(client_id: str) -> str:
    """Where the rider sends their browser, once."""
    query = urlencode(
        {
            "client_id": client_id,
            "response_type": "code",
            "redirect_uri": REDIRECT_URI,
            "approval_prompt": "auto",
            "scope": SCOPE,
        }
    )
    return f"{AUTHORIZE_URL}?{query}"


def exchange_strava_code(code: str) -> None:  # pragma: no cover - network
    """Turn the code from the browser into a refresh token, once."""
    from stravalib import Client

    try:
        answer = Client().exchange_code_for_token(
            client_id=int(StravaKeys.read(CLIENT_ID)),
            client_secret=StravaKeys.read(CLIENT_SECRET),
            code=code,
        )
    except Exception as error:
        raise StravaSetupError(f"Strava would not take that code: {error}") from error
    token = answer.get("refresh_token") if isinstance(answer, dict) else None
    if not token:
        raise StravaSetupError("Strava returned no refresh token")
    StravaKeys.write(REFRESH_TOKEN, str(token))


def connect_to_strava(client: object | None = None):  # type: ignore[no-untyped-def]
    """A Strava client with a fresh access token. Needs the setup to have run."""
    from app.services.upload import StravaUploader

    if client is None:  # pragma: no cover - network
        client = _refreshed_client()
    return StravaUploader(client=client)


def _refreshed_client():  # type: ignore[no-untyped-def]  # pragma: no cover - network
    from stravalib import Client

    client_id = StravaKeys.read(CLIENT_ID)
    client_secret = StravaKeys.read(CLIENT_SECRET)
    refresh_token = StravaKeys.read(REFRESH_TOKEN)
    client = Client()
    try:
        answer = client.refresh_access_token(
            client_id=int(client_id),
            client_secret=client_secret,
            refresh_token=refresh_token,
        )
    except Exception as error:
        raise StravaSetupError(
            f"Strava would not refresh the token: {error}"
        ) from error
    # Strava rotates refresh tokens, so the new one has to replace the old or the
    # next upload is the last one that works.
    new_refresh = answer.get("refresh_token") if isinstance(answer, dict) else None
    if new_refresh:
        StravaKeys.write(REFRESH_TOKEN, str(new_refresh))
    return client
