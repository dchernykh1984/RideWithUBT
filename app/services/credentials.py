"""Where the rider's credentials are kept.

The operating system's own credential store, through `keyring`: the Keychain on
macOS, the Credential Locker on Windows, the Secret Service on Linux. That is the
only place this app puts a password.

A machine with no credential store - a bare Linux box with no desktop session -
gets a clear failure rather than a quiet fallback to a file. Writing a password
into the data directory would be a surprise, and the sort of surprise nobody
finds until it has already happened.

The environment can override a lookup, which is how the tests run and how a
headless setup can supply a credential without a keyring at all.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

SERVICE_PREFIX = "RideWithUBT"
ENV_PREFIX = "RIDEWITHUBT"


class CredentialsError(RuntimeError):
    """No credential, or nowhere to keep one."""


@dataclass(frozen=True)
class Credential:
    """One service's login: who, and the secret that proves it."""

    service: str
    username: str

    @property
    def keyring_service(self) -> str:
        return f"{SERVICE_PREFIX}:{self.service}"

    @property
    def env_var(self) -> str:
        return f"{ENV_PREFIX}_{self.service.upper()}_SECRET"


def secret(credential: Credential) -> str:
    """The stored secret, or an explanation of why there is not one."""
    override = os.environ.get(credential.env_var)
    if override:
        return override
    stored = _keyring().get_password(credential.keyring_service, credential.username)
    if not stored:
        raise CredentialsError(
            f"no {credential.service} credential for {credential.username}; "
            f"store one, or set {credential.env_var}"
        )
    return stored


def store(credential: Credential, value: str) -> None:
    """Put a secret in the operating system's credential store."""
    _keyring().set_password(credential.keyring_service, credential.username, value)


def forget(credential: Credential) -> None:
    _keyring().delete_password(credential.keyring_service, credential.username)


def _keyring():  # type: ignore[no-untyped-def]
    try:
        import keyring
    except ImportError as error:  # pragma: no cover - keyring is a dependency
        raise CredentialsError("keyring is not installed") from error
    try:
        keyring.get_keyring()
    except Exception as error:  # pragma: no cover - depends on the machine
        raise CredentialsError(
            "this machine has no credential store keyring can use"
        ) from error
    return keyring
