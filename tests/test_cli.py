from __future__ import annotations

import sys
import types
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from typing import Any

import pytest

from app import __version__, cli, i18n
from app.settings import Settings

Translate = Callable[[str], str]


class FakeRideApp:
    """Stand-in for the Panda3D window, which needs a GPU the test runner lacks."""

    def __init__(self, translate: Translate) -> None:
        self.translate = translate
        self.ran = False

    def run(self) -> None:
        self.ran = True


@dataclass
class FakeRenderer:
    """A fake `app.render.app`, recording what the CLI asked it to do."""

    apps: list[FakeRideApp] = field(default_factory=list)
    selftests: list[Translate] = field(default_factory=list)

    def build_app(self, translate: Translate) -> FakeRideApp:
        app = FakeRideApp(translate)
        self.apps.append(app)
        return app

    def selftest(self, translate: Translate) -> None:
        self.selftests.append(translate)

    def as_module(self) -> types.ModuleType:
        # Typed as Any because a module's attributes are set, not declared; this
        # is the shape `app.cli` imports, not a class it could be checked against.
        module: Any = types.ModuleType("app.render.app")
        module.RideApp = self.build_app
        module.selftest = self.selftest
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
    assert not renderer.apps
    assert capsys.readouterr().out.strip() == "selftest ok"


def test_default_run_opens_a_localised_window(renderer: FakeRenderer) -> None:
    assert cli.main(["--lang", "ru"]) == 0

    (app,) = renderer.apps
    assert app.ran
    assert app.translate("Settings") != "Settings"
