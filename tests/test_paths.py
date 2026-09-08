from __future__ import annotations

import sys
from pathlib import Path

import pytest

from app import paths


def test_home_env_var_wins(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv(paths.HOME_ENV_VAR, str(tmp_path / "elsewhere"))
    assert paths.data_root() == tmp_path / "elsewhere"


@pytest.mark.parametrize(
    ("platform", "env", "expected"),
    [
        ("darwin", {}, Path.home() / "Library/Application Support/RideWithUBT"),
        ("win32", {"APPDATA": "/roaming"}, Path("/roaming/RideWithUBT")),
        ("win32", {}, Path.home() / "AppData/Roaming/RideWithUBT"),
        ("linux", {"XDG_DATA_HOME": "/xdg"}, Path("/xdg/RideWithUBT")),
        ("linux", {}, Path.home() / ".local/share/RideWithUBT"),
    ],
)
def test_platform_defaults(
    monkeypatch: pytest.MonkeyPatch,
    platform: str,
    env: dict[str, str],
    expected: Path,
) -> None:
    monkeypatch.delenv(paths.HOME_ENV_VAR, raising=False)
    monkeypatch.delenv("APPDATA", raising=False)
    monkeypatch.delenv("XDG_DATA_HOME", raising=False)
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setattr(sys, "platform", platform)
    assert paths.data_root() == expected


def test_ensure_data_tree_is_idempotent(isolated_data_root: Path) -> None:
    paths.ensure_data_tree()
    root = paths.ensure_data_tree()

    assert root == isolated_data_root
    assert paths.activities_dir().is_dir()
    assert paths.worlds_dir().is_dir()
    # The settings file is not created eagerly, only its directory.
    assert not paths.settings_file().exists()
