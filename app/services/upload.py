"""Sending a ride to a service.

Both services want the same thing - the FIT file the app already wrote - and both
are reached directly from this machine with the rider's own credentials. What
differs is the call, so each is a small class behind one protocol, and everything
that decides *whether* to send is above them and tested.

A ride is marked as sent only when the service says it took it. An upload that
failed must be left looking unsent, or the rider quietly loses a ride.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from app.services.uploads import UploadLog

# Strava's name for a ride that happened indoors in a virtual world. It is what
# stops the ride being shown as one ridden outside.
STRAVA_VIRTUAL_RIDE = "VirtualRide"


class UploadError(RuntimeError):
    """The service would not take the ride."""


@dataclass(frozen=True)
class UploadResult:
    ride: Path
    service: str
    reference: str = ""
    problem: str = ""

    @property
    def ok(self) -> bool:
        return not self.problem


class Uploader(Protocol):
    """One service that takes rides."""

    @property
    def service(self) -> str: ...

    def upload(self, ride: Path) -> str:
        """Send one file. Returns the service's reference for it, or raises."""
        ...


@dataclass
class GarminUploader:
    """Garmin Connect takes the FIT file as it is."""

    client: object

    @property
    def service(self) -> str:
        return "garmin"

    def upload(self, ride: Path) -> str:
        upload_activity = getattr(self.client, "upload_activity", None)
        if upload_activity is None:  # pragma: no cover - guards a client swap
            raise UploadError("this Garmin client cannot upload")
        try:
            answer = upload_activity(str(ride))
        except Exception as error:
            raise UploadError(f"Garmin refused {ride.name}: {error}") from error
        return str(answer or "")


@dataclass
class StravaUploader:
    """Strava takes the file and a type, and the type matters.

    Sent as a plain ride, a lap of a virtual world would sit among rides done
    outdoors. `VirtualRide` is what marks it for what it is.
    """

    client: object
    activity_type: str = STRAVA_VIRTUAL_RIDE

    @property
    def service(self) -> str:
        return "strava"

    def upload(self, ride: Path) -> str:
        upload_activity = getattr(self.client, "upload_activity", None)
        if upload_activity is None:  # pragma: no cover - guards a client swap
            raise UploadError("this Strava client cannot upload")
        try:
            with ride.open("rb") as handle:
                answer = upload_activity(
                    activity_file=handle,
                    data_type="fit",
                    activity_type=self.activity_type,
                )
        except Exception as error:
            raise UploadError(f"Strava refused {ride.name}: {error}") from error
        return str(getattr(answer, "id", None) or answer or "")


def send(uploader: Uploader, rides: list[Path], log: UploadLog) -> list[UploadResult]:
    """Send the rides that have not gone to this service, and record what did.

    Recording only on success is the point: a ride whose upload failed has to
    look unsent, or it is quietly lost.
    """
    results = []
    for ride in log.pending(rides, uploader.service):
        try:
            reference = uploader.upload(ride)
        except UploadError as error:
            results.append(
                UploadResult(ride=ride, service=uploader.service, problem=str(error))
            )
            continue
        log.record(ride, uploader.service, reference)
        results.append(
            UploadResult(ride=ride, service=uploader.service, reference=reference)
        )
    return results
