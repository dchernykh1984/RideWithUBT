"""Which rides have gone where.

An upload is not idempotent: sending the same file twice makes two rides on a
service, and the rider then deletes one by hand. So the app keeps a record of
what it has already sent, in the same static data tree as everything else.

The record is keyed by file name and service. It is deliberately not keyed by
anything inside the file: a ride re-recorded or edited is a new file and should
go up again, and one already sent should not.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import dataclass, field, fields
from datetime import UTC, datetime
from pathlib import Path

from app import paths

LOG_NAME = "uploads.json"


@dataclass(frozen=True)
class UploadRecord:
    """One ride, sent to one service, at one moment."""

    ride: str
    service: str
    at: str
    reference: str = ""

    @property
    def key(self) -> tuple[str, str]:
        return (self.ride, self.service)


@dataclass
class UploadLog:
    """What has been sent, and what has not."""

    records: list[UploadRecord] = field(default_factory=list)

    @classmethod
    def load(cls, directory: Path | None = None) -> UploadLog:
        path = _log_path(directory)
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except OSError, ValueError:
            return cls()
        if not isinstance(raw, list):
            return cls()
        return cls([_record(item) for item in raw if _usable(item)])

    def save(self, directory: Path | None = None) -> Path:
        path = _log_path(directory)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps([record.__dict__ for record in self.records], indent=2) + "\n",
            encoding="utf-8",
        )
        return path

    def sent(self, ride: Path | str, service: str) -> bool:
        name = ride.name if isinstance(ride, Path) else ride
        return any(record.key == (name, service) for record in self.records)

    def record(
        self, ride: Path | str, service: str, reference: str = ""
    ) -> UploadRecord:
        name = ride.name if isinstance(ride, Path) else ride
        entry = UploadRecord(
            ride=name,
            service=service,
            at=datetime.now(UTC).isoformat(timespec="seconds"),
            reference=reference,
        )
        self.records.append(entry)
        return entry

    def pending(self, rides: Iterable[Path], service: str) -> list[Path]:
        """The rides that have not gone to this service yet, oldest first."""
        return [ride for ride in rides if not self.sent(ride, service)]

    def services_for(self, ride: Path | str) -> list[str]:
        name = ride.name if isinstance(ride, Path) else ride
        return sorted(record.service for record in self.records if record.ride == name)


def _log_path(directory: Path | None) -> Path:
    return (directory or paths.data_root()) / LOG_NAME


def _usable(item: object) -> bool:
    return isinstance(item, dict) and {"ride", "service", "at"} <= set(item)


def _record(item: dict[str, str]) -> UploadRecord:
    """Build a record, ignoring anything a newer version wrote beside it.

    A log this version cannot fully understand must not stop it from uploading -
    the alternative is a rider who upgraded, went back, and can no longer send a
    ride anywhere.
    """
    known = {field.name for field in fields(UploadRecord)}
    return UploadRecord(**{key: value for key, value in item.items() if key in known})
