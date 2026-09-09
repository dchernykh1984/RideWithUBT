"""Sending rides, and not sending them twice.

The failure that matters here is silent: a ride marked as sent when it was not,
which the rider never notices because nothing went wrong on screen."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from app import paths
from app.services.upload import (
    STRAVA_VIRTUAL_RIDE,
    GarminUploader,
    StravaUploader,
    UploadError,
    send,
)
from app.services.uploads import UploadLog


def ride(tmp_path: Path, name: str) -> Path:
    path = tmp_path / name
    path.write_bytes(b"a fit file")
    return path


class FakeGarmin:
    def __init__(self, fail: bool = False) -> None:
        self.fail = fail
        self.uploaded: list[str] = []

    def upload_activity(self, path: str) -> str:
        if self.fail:
            raise RuntimeError("that ride is already on Garmin")
        self.uploaded.append(path)
        return "12345"


class FakeStrava:
    def __init__(self, fail: bool = False) -> None:
        self.fail = fail
        self.calls: list[dict[str, object]] = []

    def upload_activity(self, **kwargs: Any) -> object:
        if self.fail:
            raise RuntimeError("rate limit exceeded")
        # The file has to still be open when Strava reads it, which is easy to
        # break by closing it before the call rather than around it.
        assert not kwargs["activity_file"].closed
        self.calls.append(
            {"data_type": kwargs["data_type"], "activity_type": kwargs["activity_type"]}
        )
        return type("Upload", (), {"id": 999})()


# The log.


def test_a_fresh_log_has_sent_nothing() -> None:
    log = UploadLog()

    assert not log.sent("ride.fit", "garmin")
    assert log.services_for("ride.fit") == []


def test_a_recorded_ride_is_not_offered_again() -> None:
    log = UploadLog()
    log.record("ride.fit", "garmin", "12345")

    assert log.sent("ride.fit", "garmin")
    assert not log.sent("ride.fit", "strava"), "each service is its own question"
    assert log.services_for("ride.fit") == ["garmin"]


def test_pending_is_what_has_not_gone_to_this_service(tmp_path: Path) -> None:
    one, two = ride(tmp_path, "one.fit"), ride(tmp_path, "two.fit")
    log = UploadLog()
    log.record(one, "strava")

    assert log.pending([one, two], "strava") == [two]
    assert log.pending([one, two], "garmin") == [one, two]


def test_the_log_survives_being_written_and_read() -> None:
    log = UploadLog()
    log.record("ride.fit", "strava", "999")
    log.save()

    assert UploadLog.load().sent("ride.fit", "strava")
    assert (paths.data_root() / "uploads.json").is_file()


def test_a_log_that_is_not_there_is_empty() -> None:
    assert UploadLog.load().records == []


@pytest.mark.parametrize("content", ["not json", '{"not": "a list"}', "[1, 2, 3]"])
def test_an_unusable_log_does_not_stop_the_app(content: str) -> None:
    """Better to offer a ride twice than to refuse to upload anything."""
    paths.ensure_data_tree()
    (paths.data_root() / "uploads.json").write_text(content, encoding="utf-8")

    assert UploadLog.load().records == []


def test_a_half_written_entry_is_dropped() -> None:
    paths.ensure_data_tree()
    (paths.data_root() / "uploads.json").write_text(
        json.dumps([{"ride": "a.fit"}, {"ride": "b.fit", "service": "s", "at": "now"}]),
        encoding="utf-8",
    )

    assert [record.ride for record in UploadLog.load().records] == ["b.fit"]


# Sending.


def test_garmin_gets_the_file_as_it_is(tmp_path: Path) -> None:
    client = FakeGarmin()
    target = ride(tmp_path, "one.fit")

    reference = GarminUploader(client=client).upload(target)

    assert client.uploaded == [str(target)]
    assert reference == "12345"


def test_strava_is_told_the_ride_was_virtual(tmp_path: Path) -> None:
    """Sent as a plain ride it would sit among rides done outdoors."""
    client = FakeStrava()

    reference = StravaUploader(client=client).upload(ride(tmp_path, "one.fit"))

    assert client.calls == [{"data_type": "fit", "activity_type": STRAVA_VIRTUAL_RIDE}]
    assert reference == "999"


@pytest.mark.parametrize(
    ("uploader", "expected"),
    [("garmin", "already on Garmin"), ("strava", "rate limit")],
)
def test_a_refusal_is_reported_with_what_the_service_said(
    tmp_path: Path, uploader: str, expected: str
) -> None:
    sender = (
        GarminUploader(client=FakeGarmin(fail=True))
        if uploader == "garmin"
        else StravaUploader(client=FakeStrava(fail=True))
    )

    with pytest.raises(UploadError, match=expected):
        sender.upload(ride(tmp_path, "one.fit"))


def test_sending_records_only_what_actually_went(tmp_path: Path) -> None:
    """A ride whose upload failed has to look unsent, or it is quietly lost."""
    log = UploadLog()
    rides = [ride(tmp_path, "one.fit")]

    results = send(GarminUploader(client=FakeGarmin(fail=True)), rides, log)

    assert not results[0].ok
    assert not log.sent(rides[0], "garmin")
    assert log.pending(rides, "garmin") == rides


def test_sending_twice_sends_once(tmp_path: Path) -> None:
    """Two uploads of one file make two rides, which the rider deletes by hand."""
    client = FakeGarmin()
    log = UploadLog()
    rides = [ride(tmp_path, "one.fit"), ride(tmp_path, "two.fit")]
    uploader = GarminUploader(client=client)

    first = send(uploader, rides, log)
    again = send(uploader, rides, log)

    assert len(first) == 2 and all(result.ok for result in first)
    assert again == []
    assert len(client.uploaded) == 2


def test_one_failure_does_not_stop_the_others(tmp_path: Path) -> None:
    class Fussy:
        service = "garmin"

        def upload(self, path: Path) -> str:
            if path.name == "one.fit":
                raise UploadError("no")
            return "ok"

    log = UploadLog()
    rides = [ride(tmp_path, "one.fit"), ride(tmp_path, "two.fit")]

    results = send(Fussy(), rides, log)

    assert [result.ok for result in results] == [False, True]
    assert log.services_for("two.fit") == ["garmin"]
