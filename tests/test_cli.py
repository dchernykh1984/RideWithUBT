from __future__ import annotations

import sys
import types
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

from app import __version__, cli, i18n
from app.settings import Settings

Translate = Callable[[str], str]


class FakeRideApp:
    """Stand-in for the Panda3D window, which needs a GPU the test runner lacks."""

    def __init__(self, translate: Translate, setup: Any = None, **options: Any) -> None:
        self.translate = translate
        self.setup = setup
        self.options = options
        self.ran = False

    def run(self) -> None:
        self.ran = True


@dataclass
class FakeRenderer:
    """A fake `app.render.app`, recording what the CLI asked it to do."""

    apps: list[FakeRideApp] = field(default_factory=list)
    selftests: list[dict[str, Any]] = field(default_factory=list)
    screenshots: list[dict[str, Any]] = field(default_factory=list)
    plans: list[dict[str, Any]] = field(default_factory=list)

    def build_app(
        self, translate: Translate, setup: Any = None, **options: Any
    ) -> FakeRideApp:
        app = FakeRideApp(translate, setup, **options)
        self.apps.append(app)
        return app

    def selftest(self, translate: Translate, **options: Any) -> None:
        self.selftests.append(options)

    def screenshot(self, translate: Translate, path: str, **options: Any) -> None:
        self.screenshots.append({"path": path, **options})

    def plan_view(self, translate: Translate, path: str, **options: Any) -> None:
        self.plans.append({"path": path, **options})

    def as_module(self) -> types.ModuleType:
        # Typed as Any because a module's attributes are set, not declared; this
        # is the shape `app.cli` imports, not a class it could be checked against.
        module: Any = types.ModuleType("app.render.app")
        module.RideApp = self.build_app
        module.selftest = self.selftest
        module.screenshot = self.screenshot
        module.plan_view = self.plan_view
        return module


@pytest.fixture
def renderer(monkeypatch: pytest.MonkeyPatch) -> Iterator[FakeRenderer]:
    fake = FakeRenderer()
    monkeypatch.setitem(sys.modules, "app.render.app", fake.as_module())
    yield fake


def test_version_is_reported(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exit_info:
        cli.main(["--version"])

    assert exit_info.value.code == 0
    assert capsys.readouterr().out.strip() == __version__


def test_languages_lists_all_of_them_and_marks_the_active_one(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert cli.main(["--languages", "--lang", "kk"]) == 0

    lines = capsys.readouterr().out.splitlines()
    assert len(lines) == len(i18n.LOCALES)
    assert [line for line in lines if line.startswith("*")] == [
        lines[i18n.LOCALES.index("kk")]
    ]


def test_lang_flag_overrides_the_saved_setting() -> None:
    Settings(language="ru").save()

    assert cli.resolve_language("kk") == "kk"


def test_without_the_flag_the_saved_setting_is_used() -> None:
    Settings(language="ru").save()

    assert cli.resolve_language(None) == "ru"


def test_selftest_runs_the_engine_and_reports(
    renderer: FakeRenderer, capsys: pytest.CaptureFixture[str]
) -> None:
    assert cli.main(["--selftest"]) == 0

    assert len(renderer.selftests) == 1
    assert renderer.selftests[0]["world_id"] == "sokol"
    assert not renderer.apps
    assert "selftest ok" in capsys.readouterr().out


def test_default_run_opens_a_localised_window(renderer: FakeRenderer) -> None:
    assert cli.main(["--lang", "ru"]) == 0

    (app,) = renderer.apps
    assert app.ran
    assert app.translate("Settings") != "Settings"
    assert app.setup.world_id == "sokol"


def test_the_world_route_and_power_reach_the_renderer(
    renderer: FakeRenderer,
) -> None:
    assert (
        cli.main(["--world", "sokol", "--route", "small-ring", "--power", "240"]) == 0
    )

    (app,) = renderer.apps
    assert app.setup.route_id == "small-ring"
    assert app.setup.power_w == 240.0


def test_worlds_lists_every_configuration_with_its_lap(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Reads the shipped world, so it also proves the world file travels."""
    assert cli.main(["--worlds"]) == 0

    out = capsys.readouterr().out
    assert "Sokol International Racetrack" in out
    assert "big-ring" in out
    assert "small-ring-chicane" in out
    assert "4.4" in out, "the lap distance is shown"


def test_a_screenshot_is_asked_for_where_it_was_requested(
    renderer: FakeRenderer, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    target = str(tmp_path / "shot.png")

    assert cli.main(["--screenshot", target, "--at", "90"]) == 0

    (shot,) = renderer.screenshots
    assert shot["path"] == target
    assert shot["seconds"] == 90.0
    assert not renderer.apps, "a screenshot does not open a window"
    assert f"wrote {target}" in capsys.readouterr().out


def test_a_plan_view_draws_the_world_from_above(
    renderer: FakeRenderer, tmp_path: Path
) -> None:
    target = str(tmp_path / "plan.png")

    assert cli.main(["--plan", target, "--world", "sokol"]) == 0

    (plan,) = renderer.plans
    assert plan["path"] == target
    assert plan["world_id"] == "sokol"
    assert not renderer.apps


def test_the_ride_is_recorded_unless_asked_otherwise(renderer: FakeRenderer) -> None:
    assert cli.main([]) == 0

    (app,) = renderer.apps
    assert app.setup.record is True


def test_no_record_rides_without_keeping_it(renderer: FakeRenderer) -> None:
    assert cli.main(["--no-record"]) == 0

    (app,) = renderer.apps
    assert app.setup.record is False


def test_rides_reports_an_empty_store(capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main(["--rides"]) == 0

    assert "no rides yet" in capsys.readouterr().out


def test_rides_lists_what_has_been_recorded(
    capsys: pytest.CaptureFixture[str],
) -> None:
    from datetime import UTC, datetime

    from app.storage import activities

    activities.save(b"x" * 2048, datetime(2026, 9, 9, 6, 30, tzinfo=UTC))

    assert cli.main(["--rides"]) == 0

    assert "20260909T063000.fit" in capsys.readouterr().out


def test_workouts_reports_an_empty_library(capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main(["--workouts"]) == 0

    assert "no workouts yet" in capsys.readouterr().out


def test_workouts_lists_what_can_be_ridden(
    capsys: pytest.CaptureFixture[str],
) -> None:
    import json
    import shutil

    from app import paths

    paths.ensure_data_tree()
    shutil.copy(
        Path(__file__).parent / "data" / "cycling_intervals.json",
        paths.workouts_dir() / "intervals.json",
    )
    (paths.workouts_dir() / "broken.json").write_text(
        json.dumps({"name": "B", "steps": [{"type": "sprint"}]}), encoding="utf-8"
    )

    assert cli.main(["--workouts"]) == 0

    out = capsys.readouterr().out
    assert "3x8 Cycling Intervals" in out
    assert "open ended" in out, "a workout with an open step has no fixed length"
    assert "could not read broken.json" in out


def test_a_workout_reaches_the_renderer(renderer: FakeRenderer) -> None:
    example = str(Path(__file__).parent / "data" / "cycling_intervals.json")

    assert cli.main(["--workout", example]) == 0

    (app,) = renderer.apps
    assert app.setup.workout.name == "3x8 Cycling Intervals"


def test_riding_without_a_workout_passes_none(renderer: FakeRenderer) -> None:
    assert cli.main([]) == 0

    (app,) = renderer.apps
    assert app.setup.workout is None


def test_pairing_and_unpairing_a_device(capsys: pytest.CaptureFixture[str]) -> None:
    from app.settings import Settings

    assert cli.main(["--pair", "ble:AA:BB"]) == 0
    assert Settings.load().paired_device_ids == ["ble:AA:BB"]

    assert cli.main(["--devices"]) == 0
    assert "ble:AA:BB" in capsys.readouterr().out

    assert cli.main(["--unpair", "ble:AA:BB"]) == 0
    assert Settings.load().paired_device_ids == []


def test_pairing_the_same_device_twice_keeps_one() -> None:
    from app.settings import Settings

    cli.main(["--pair", "ble:AA:BB"])
    cli.main(["--pair", "ble:AA:BB"])

    assert Settings.load().paired_device_ids == ["ble:AA:BB"]


def test_unpairing_something_that_was_never_paired() -> None:
    assert cli.main(["--unpair", "ble:nothing"]) == 0


def test_devices_reports_an_empty_list(capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main(["--devices"]) == 0

    assert "no devices paired yet" in capsys.readouterr().out


def test_a_scan_that_finds_nothing_says_so(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(cli, "default_transports", list)

    assert cli.main(["--scan", "0.01"]) == 0

    assert "nothing answered" in capsys.readouterr().out


def test_a_scan_lists_what_answered(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from app.sensors.base import DeviceInfo, Transport
    from app.sensors.types import Metric

    found = DeviceInfo(
        id="ble:AA",
        name="KICKR",
        transport=Transport.BLE,
        metrics=frozenset({Metric.POWER}),
        controllable=True,
    )

    class OneDevice:
        transport = Transport.BLE

        async def scan(self, seconds: float) -> list[DeviceInfo]:
            return [found]

        def open(self, device: DeviceInfo, wheel: object) -> object:  # pragma: no cover
            raise NotImplementedError

        def control_for(self, source: object) -> None:  # pragma: no cover
            return None

    monkeypatch.setattr(cli, "default_transports", lambda: [OneDevice()])

    assert cli.main(["--scan"]) == 0

    out = capsys.readouterr().out
    assert "ble:AA" in out
    assert "controllable" in out
    assert "power" in out


def test_importing_without_an_account_says_what_is_missing(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert cli.main(["--import-garmin"]) == 0

    assert "--garmin-user" in capsys.readouterr().out


def test_a_failed_sign_in_is_reported_not_raised(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A wrong password is an everyday thing, not a stack trace."""

    def refuse(username: str) -> object:
        raise cli.GarminLoginError(f"could not sign in to Garmin as {username}")

    monkeypatch.setattr(cli, "connect_to_garmin", refuse)

    assert cli.main(["--import-garmin", "--garmin-user", "rider@example.com"]) == 0

    assert "could not sign in" in capsys.readouterr().out


def test_importing_writes_the_workouts_and_remembers_the_account(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from app.services.garmin import GarminWorkouts
    from app.settings import Settings
    from app.workout import library
    from tests.test_garmin_format import step, workout
    from tests.test_garmin_service import FakeGarmin

    client = FakeGarmin({"a": workout(step(seconds=600.0), name="Threshold")})
    monkeypatch.setattr(
        cli, "connect_to_garmin", lambda username: GarminWorkouts(client=client)
    )

    assert cli.main(["--import-garmin", "3", "--garmin-user", "rider@example.com"]) == 0

    assert "Threshold -> threshold.json" in capsys.readouterr().out
    assert Settings.load().garmin_username == "rider@example.com"
    assert library.load_library().named("Threshold").total_time_s == 600.0


def test_importing_from_an_account_with_nothing_in_it(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from app.services.garmin import GarminWorkouts
    from tests.test_garmin_service import FakeGarmin

    monkeypatch.setattr(
        cli,
        "connect_to_garmin",
        lambda username: GarminWorkouts(client=FakeGarmin({})),
    )

    assert cli.main(["--import-garmin", "--garmin-user", "rider@example.com"]) == 0

    assert "no workouts to import" in capsys.readouterr().out


def test_uploading_with_no_rides_says_so(capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main(["--upload"]) == 0

    assert "no rides to upload" in capsys.readouterr().out


def test_uploading_to_garmin_without_an_account(
    capsys: pytest.CaptureFixture[str],
) -> None:
    from datetime import UTC, datetime

    from app.storage import activities

    activities.save(b"ride", datetime(2026, 9, 9, 6, 30, tzinfo=UTC))

    assert cli.main(["--upload", "garmin"]) == 0

    assert "--garmin-user" in capsys.readouterr().out


def test_a_ride_goes_up_once(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from datetime import UTC, datetime

    from app.services.upload import StravaUploader
    from app.storage import activities
    from tests.test_uploads import FakeStrava

    activities.save(b"ride", datetime(2026, 9, 9, 6, 30, tzinfo=UTC))
    client = FakeStrava()
    monkeypatch.setattr(cli, "connect_to_strava", lambda: StravaUploader(client=client))

    assert cli.main(["--upload", "strava"]) == 0
    assert "-> strava 999" in capsys.readouterr().out

    assert cli.main(["--upload", "strava"]) == 0
    assert capsys.readouterr().out == "", "the second run has nothing to send"
    assert len(client.calls) == 1


def test_strava_setup_prints_where_to_go(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    written: dict[str, str] = {}
    monkeypatch.setattr(
        cli.StravaKeys,
        "write",
        staticmethod(lambda name, value: written.update({name: value})),
    )

    assert cli.main(["--strava-setup", "12345", "shhh"]) == 0

    out = capsys.readouterr().out
    assert "strava.com/oauth/authorize" in out
    assert "client_id=12345" in out
    assert "--strava-code" in out
    assert written == {"client_id": "12345", "client_secret": "shhh"}


def test_finishing_strava_setup_reports_a_refusal(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def refuse(code: str) -> None:
        raise cli.StravaSetupError("Strava would not take that code")

    monkeypatch.setattr(cli, "exchange_strava_code", refuse)

    assert cli.main(["--strava-code", "abc"]) == 0

    assert "would not take that code" in capsys.readouterr().out


def test_finishing_strava_setup(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(cli, "exchange_strava_code", lambda code: None)

    assert cli.main(["--strava-code", "abc"]) == 0

    assert "Strava connected" in capsys.readouterr().out


def test_a_build_missing_a_late_import_fails_the_self_test(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """The whole point: a packaging mistake fails the build, not a rider's upload."""
    monkeypatch.setattr(
        cli.selfcheck, "missing", lambda *args: ["app.services.upload: no module"]
    )

    assert cli.main(["--selftest"]) == 1

    assert "missing from this build" in capsys.readouterr().out


def test_a_world_that_does_not_exist_is_a_message_not_a_traceback(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A typed name is a thing a person gets wrong, not a thing that went wrong."""
    assert cli.main(["--world", "nowhere", "--worlds"]) == 0  # listing still works
    capsys.readouterr()

    assert cli.main(["--world", "nowhere", "--selftest"]) == 2

    out = capsys.readouterr().out
    assert "no world 'nowhere'" in out
    assert "--worlds lists" in out
    assert "Traceback" not in out


def test_a_route_that_does_not_exist_points_at_the_listing(
    renderer: FakeRenderer, capsys: pytest.CaptureFixture[str]
) -> None:
    assert cli.main(["--route", "nonesuch"]) == 2

    out = capsys.readouterr().out
    assert "unknown route 'nonesuch'" in out
    assert "--worlds lists" in out


def test_a_workout_that_does_not_exist_points_at_its_own_listing(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert cli.main(["--workout", "nonesuch"]) == 2

    out = capsys.readouterr().out
    assert "no workout named 'nonesuch'" in out
    assert "--workouts lists" in out


def test_the_setup_commands_reach_the_settings(
    capsys: pytest.CaptureFixture[str],
) -> None:
    from app.settings import Settings

    assert cli.main(["--wheel", "700c", "25"]) == 0
    assert cli.main(["--trainer", "kinetic-road-machine"]) == 0
    assert cli.main(["--control", "erg"]) == 0
    capsys.readouterr()

    assert cli.main(["--setup"]) == 0
    out = capsys.readouterr().out
    assert "Kinetic Road Machine" in out
    assert "700c x 25" in out
    assert Settings.load().control_mode == "erg"


def test_a_wheel_that_does_not_exist_is_refused_with_a_code(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert cli.main(["--wheel", "unicycle", "25"]) == 2

    assert "--wheels lists" in capsys.readouterr().out


def test_the_catalogues_can_be_listed(capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main(["--wheels"]) == 0
    assert "700c" in capsys.readouterr().out

    assert cli.main(["--trainers"]) == 0
    assert "wahoo-kickr-core" in capsys.readouterr().out


def test_a_measured_rollout_can_be_set_from_the_command_line(
    capsys: pytest.CaptureFixture[str],
) -> None:
    from app.settings import Settings

    assert cli.main(["--rollout", "2088"]) == 0

    assert "2088 mm" in capsys.readouterr().out
    assert Settings.load().measured_rollout_mm == 2088.0


def test_the_schedule_says_when_there_is_none(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert cli.main(["--schedule"]) == 0

    assert "--import-schedule" in capsys.readouterr().out


def test_the_schedule_marks_today(capsys: pytest.CaptureFixture[str]) -> None:
    from datetime import date, timedelta

    from app.workout.schedule import Schedule, ScheduledRide

    Schedule.of(
        [
            ScheduledRide(on=date.today(), workout_name="Threshold"),
            ScheduledRide(on=date.today() + timedelta(days=2), workout_name="Recovery"),
        ]
    ).save()

    assert cli.main(["--schedule"]) == 0

    out = capsys.readouterr().out
    assert "today        Threshold" in out
    assert "Recovery" in out


def test_riding_today_takes_the_workout_the_plan_names(
    renderer: FakeRenderer, capsys: pytest.CaptureFixture[str]
) -> None:
    import shutil
    from datetime import date

    from app import paths
    from app.workout.schedule import Schedule, ScheduledRide

    paths.ensure_data_tree()
    shutil.copy(
        Path(__file__).parent / "data" / "cycling_intervals.json",
        paths.workouts_dir() / "intervals.json",
    )
    Schedule.of(
        [ScheduledRide(on=date.today(), workout_name="3x8 Cycling Intervals")]
    ).save()

    assert cli.main(["--today"]) == 0

    (app,) = renderer.apps
    assert app.setup.workout is not None
    assert app.setup.workout.name == "3x8 Cycling Intervals"
    assert "today: 3x8 Cycling Intervals" in capsys.readouterr().out


def test_riding_today_with_nothing_scheduled_says_so(
    renderer: FakeRenderer, capsys: pytest.CaptureFixture[str]
) -> None:
    assert cli.main(["--today"]) == 0

    (app,) = renderer.apps
    assert app.setup.workout is None
    assert "nothing scheduled for today" in capsys.readouterr().out


def test_a_named_workout_wins_over_the_plan(renderer: FakeRenderer) -> None:
    """Asking for something specific is asking for it, plan or no plan."""
    import shutil
    from datetime import date

    from app import paths
    from app.workout.schedule import Schedule, ScheduledRide

    paths.ensure_data_tree()
    shutil.copy(
        Path(__file__).parent / "data" / "cycling_intervals.json",
        paths.workouts_dir() / "intervals.json",
    )
    Schedule.of([ScheduledRide(on=date.today(), workout_name="Something else")]).save()

    assert cli.main(["--today", "--workout", "3x8 Cycling Intervals"]) == 0

    (app,) = renderer.apps
    assert app.setup.workout.name == "3x8 Cycling Intervals"


def test_importing_a_schedule_without_an_account(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert cli.main(["--import-schedule"]) == 0

    assert "--garmin-user" in capsys.readouterr().out


def test_importing_a_schedule_stores_it_and_its_workouts(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from datetime import date

    from app.services.garmin import GarminWorkouts
    from app.workout import library
    from app.workout.schedule import Schedule
    from tests.test_garmin_format import step, workout
    from tests.test_garmin_service import FakeGarmin

    plan_day = date.today().isoformat()
    client = FakeGarmin(
        {"a": workout(step(seconds=600.0), name="Threshold")},
        scheduled=[
            {
                "calendarDate": plan_day,
                "workout": {"workoutName": "Threshold", "workoutId": "a"},
            }
        ],
    )
    monkeypatch.setattr(
        cli, "connect_to_garmin", lambda username: GarminWorkouts(client=client)
    )

    assert cli.main(["--import-schedule", "7", "--garmin-user", "me@example.com"]) == 0

    out = capsys.readouterr().out
    assert "1 rides scheduled" in out
    assert "Threshold -> threshold.json" in out
    assert len(Schedule.load()) == 1
    assert library.load_library().named("Threshold").total_time_s == 600.0


def test_importing_a_plan_with_nothing_in_it(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from app.services.garmin import GarminWorkouts
    from tests.test_garmin_service import FakeGarmin

    client = FakeGarmin({})
    monkeypatch.setattr(
        cli, "connect_to_garmin", lambda username: GarminWorkouts(client=client)
    )

    assert cli.main(["--import-schedule", "--garmin-user", "me@example.com"]) == 0

    assert "nothing scheduled in the next 28 days" in capsys.readouterr().out
