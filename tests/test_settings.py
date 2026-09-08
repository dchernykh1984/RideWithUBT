from __future__ import annotations

import pytest

from app import paths
from app.settings import Settings


def test_defaults_follow_the_system_language(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RIDEWITHUBT_LANG", "kk_KZ.UTF-8")
    assert Settings().language == ""
    assert Settings().effective_language == "kk"


def test_explicit_language_wins_over_the_system(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("RIDEWITHUBT_LANG", "kk")
    assert Settings(language="ru").effective_language == "ru"


def test_save_then_load_round_trip() -> None:
    Settings(language="kk").save()

    assert paths.settings_file().is_file()
    assert Settings.load() == Settings(language="kk")


def test_load_without_a_file_returns_defaults() -> None:
    assert Settings.load() == Settings()


@pytest.mark.parametrize("content", ["not json at all", '["a", "list"]'])
def test_load_survives_an_unusable_file(content: str) -> None:
    paths.ensure_data_tree()
    paths.settings_file().write_text(content, encoding="utf-8")

    assert Settings.load() == Settings()


def test_unknown_keys_are_dropped_not_rejected() -> None:
    settings = Settings.from_dict({"language": "ru", "from_a_newer_build": 42})

    assert settings == Settings(language="ru")
