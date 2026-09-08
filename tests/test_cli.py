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

    def __init__(self, translate: Translate, **options: Any) -> None:
        self.translate = translate
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

    def build_app(self, translate: Translate, **options: Any) -> FakeRideApp:
        app = FakeRideApp(translate, **options)
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
    assert capsys.readouterr().out.strip() == "selftest ok"


def test_default_run_opens_a_localised_window(renderer: FakeRenderer) -> None:
    assert cli.main(["--lang", "ru"]) == 0

    (app,) = renderer.apps
    assert app.ran
    assert app.translate("Settings") != "Settings"
    assert app.options["world_id"] == "sokol"


def test_the_world_route_and_power_reach_the_renderer(
    renderer: FakeRenderer,
) -> None:
    assert (
        cli.main(["--world", "sokol", "--route", "small-ring", "--power", "240"]) == 0
    )

    (app,) = renderer.apps
    assert app.options["route_id"] == "small-ring"
    assert app.options["power_w"] == 240.0


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
    assert app.options["record"] is True


def test_no_record_rides_without_keeping_it(renderer: FakeRenderer) -> None:
    assert cli.main(["--no-record"]) == 0

    (app,) = renderer.apps
    assert app.options["record"] is False


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
    assert app.options["workout"].name == "3x8 Cycling Intervals"


def test_riding_without_a_workout_passes_none(renderer: FakeRenderer) -> None:
    assert cli.main([]) == 0

    (app,) = renderer.apps
    assert app.options["workout"] is None
