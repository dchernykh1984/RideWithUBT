from __future__ import annotations

from pathlib import Path

import polib
import pytest

from app import i18n


@pytest.mark.parametrize(
    ("tag", "expected"),
    [
        ("ru", "ru"),
        ("ru_RU.UTF-8", "ru"),
        ("kk-KZ", "kk"),
        ("EN", "en"),
        ("de_DE", "en"),
        ("", "en"),
        (None, "en"),
    ],
)
def test_normalise(tag: str | None, expected: str) -> None:
    assert i18n.normalise(tag) == expected


def test_system_locale_prefers_the_app_override(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LANG", "ru_RU.UTF-8")
    monkeypatch.setenv(i18n.LOCALE_ENV_VAR, "kk")

    assert i18n.system_locale() == "kk"


def test_system_locale_reads_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(i18n.LOCALE_ENV_VAR, raising=False)
    monkeypatch.delenv("LC_ALL", raising=False)
    monkeypatch.delenv("LC_MESSAGES", raising=False)
    monkeypatch.setenv("LANG", "ru_RU.UTF-8")

    assert i18n.system_locale() == "ru"


def test_system_locale_falls_back_to_the_platform(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for name in (i18n.LOCALE_ENV_VAR, "LC_ALL", "LC_MESSAGES", "LANG"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(i18n.locale_module, "getlocale", lambda _: ("kk_KZ", "UTF-8"))

    assert i18n.system_locale() == "kk"


def test_translation_differs_from_the_source_string() -> None:
    translate = i18n.load("ru")

    assert translate("Settings") != "Settings"
    assert translate("Settings")


def test_unknown_source_strings_pass_through() -> None:
    assert i18n.load("ru")("not in any catalogue") == "not in any catalogue"


def test_unknown_locale_falls_back_to_english() -> None:
    assert i18n.load("de")("Settings") == "Settings"


def test_missing_catalogue_leaves_the_source_strings(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(i18n, "LOCALE_DIR", tmp_path)

    translate = i18n.load("ru")

    assert translate.locale == "ru"
    assert translate("Settings") == "Settings"


def test_fuzzy_and_empty_entries_are_ignored(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    catalogue = polib.POFile()
    catalogue.append(polib.POEntry(msgid="Ride", msgstr="stale", flags=["fuzzy"]))
    catalogue.append(polib.POEntry(msgid="Settings", msgstr=""))
    catalogue.save(str(tmp_path / "ru.po"))
    monkeypatch.setattr(i18n, "LOCALE_DIR", tmp_path)

    translate = i18n.load("ru")

    assert translate("Ride") == "Ride"
    assert translate("Settings") == "Settings"


@pytest.mark.parametrize("locale", i18n.LOCALES)
def test_every_locale_names_itself(locale: str) -> None:
    name = i18n.locale_name(locale)

    assert name
    assert name != "Language name"


@pytest.mark.parametrize("locale", [code for code in i18n.LOCALES if code != "en"])
def test_catalogues_cover_every_source_string(locale: str) -> None:
    """A missing entry shows English to a user who asked for another language."""
    english = set(i18n.load("en").catalog)
    translated = set(i18n.load(locale).catalog)

    assert english - translated == set()
