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


def test_a_fresh_install_has_no_trainer_or_wheel() -> None:
    settings = Settings()

    assert settings.trainer is None
    assert settings.wheel is None
    assert not settings.record_trainer_data


def test_a_configured_wheel_and_trainer_come_back_as_objects() -> None:
    settings = Settings(
        trainer_id="generic-fluid", wheel_size_id="700c", wheel_width_id="25"
    )

    wheel = settings.wheel
    trainer = settings.trainer
    assert wheel is not None and trainer is not None
    assert 2090 < wheel.rollout_mm < 2125
    assert trainer.name == "Generic Fluid trainer"


def test_a_measured_rollout_is_used_even_with_a_size_saved() -> None:
    settings = Settings(
        wheel_size_id="700c", wheel_width_id="25", measured_rollout_mm=2088.0
    )

    wheel = settings.wheel
    assert wheel is not None
    assert wheel.rollout_mm == 2088.0


@pytest.mark.parametrize(
    "settings",
    [
        Settings(wheel_size_id="700c"),
        Settings(wheel_size_id="unicycle", wheel_width_id="25"),
        Settings(wheel_size_id="700c", wheel_width_id="99"),
    ],
)
def test_an_unusable_saved_wheel_asks_again_rather_than_failing(
    settings: Settings,
) -> None:
    """A catalogue entry can disappear between versions; that is not a crash."""
    assert settings.wheel is None


def test_a_trainer_that_is_no_longer_shipped_asks_again() -> None:
    assert Settings(trainer_id="retired-model").trainer is None


def test_the_whole_setup_survives_a_round_trip() -> None:
    saved = Settings(
        language="kk",
        trainer_id="kinetic-road-machine",
        wheel_size_id="700c",
        wheel_width_id="28",
        record_trainer_data=True,
    )
    saved.save()

    assert Settings.load() == saved
