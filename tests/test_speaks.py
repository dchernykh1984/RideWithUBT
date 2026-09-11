"""Everything a rider reads, in the language they chose.

An application that says it speaks three languages and then shows half a screen
in English speaks one. This is the half that is easy to miss: sentences a panel
builds out of numbers it worked out itself, which by the time anybody draws them
are one string with a number baked in and cannot be translated then.
"""

from __future__ import annotations

import polib
import pytest

from app import i18n, paths
from app.core.physics import BIKES
from app.core.preferences import CONTROL_LABELS, SCAN, TRAINER, Found, SetupMenu
from app.core.startscreen import StartScreen


def catalogue(locale: str) -> dict[str, str]:
    return {
        entry.msgid: entry.msgstr
        for entry in polib.pofile(str(i18n.catalog_path(locale)))
    }


def russian() -> SetupMenu:
    return SetupMenu(speaks=i18n.load("ru"))


# The sentences a panel builds itself.


def test_the_summary_is_in_the_rider_s_language() -> None:
    setup = russian()
    setup.choice(TRAINER).point_at("kinetic-road-machine")

    said = setup.summary
    plain = SetupMenu().summary

    assert said != plain, "it came out in English"
    assert not said.isascii(), "and in an alphabet English does not have"
    assert "250" in said, "with the numbers still numbers"


def test_the_numbers_survive_being_translated() -> None:
    """Named rather than positional, so a translator can move them about."""
    setup = russian()
    setup.choice(TRAINER).point_at("kinetic-road-machine")

    said = setup.summary

    assert "%(" not in said, "a placeholder was left unfilled"
    assert any(character.isdigit() for character in said)


def test_what_is_still_missing_is_said_in_the_rider_s_language() -> None:
    setup = russian()
    setup.choice(TRAINER).choices = ()

    said = setup.summary

    assert "choose a wheel" not in said
    assert not said.isascii()


def test_a_scan_reports_in_the_rider_s_language() -> None:
    setup = SetupMenu(speaks=i18n.load("ru"), scanner=lambda _s: [])

    setup.scan()

    assert setup.note != "nothing answered - are they awake?"
    assert not setup.note.isascii()


def test_a_scan_that_found_something_counts_it_in_any_language() -> None:
    setup = SetupMenu(
        speaks=i18n.load("ru"),
        scanner=lambda _s: [Found("ble:AA", "One"), Found("ble:BB", "Two")],
    )

    setup.scan()

    assert "2" in setup.note


def test_a_build_with_no_radios_says_so_in_the_rider_s_language() -> None:
    setup = russian()

    setup.scan()

    assert setup.note != "no radios in this build"
    assert not setup.note.isascii()


def test_a_panel_nobody_gave_a_language_to_says_it_plainly() -> None:
    """Identity by default, so nothing that does not care has to know."""
    setup = SetupMenu()

    setup.scan()

    assert setup.note == "no radios in this build"


# Every fixed word on either screen, in every catalogue.


def fixed_words() -> set[str]:
    """The labels and readings the panels put on screen themselves.

    Not the names of real things - a circuit, a route, a trainer - which are
    what those things are called and are left alone.
    """
    words: set[str] = set()
    for panel in (StartScreen(), SetupMenu()):
        for name, _ in panel.columns():
            words.add(name.lstrip("> ").strip())
    words |= {
        "start",
        "none - just ride",
        "off - your own legs",
        "trainer, sensors, bike",
        "not chosen",
        "yes",
        "no",
        "paired",
        "not paired",
        "in use",
        "no radios in this build",
        "nothing answered - are they awake?",
        "measured",
        "estimated",
        "keep these",
        "leave them as they were",
        *CONTROL_LABELS.values(),
        SCAN,
    }
    # What a bicycle is is a word, not a name: "Road bicycle, in the drops"
    # describes a position a rider sits in, and every language has one.
    words |= {bike.name for bike in BIKES}
    return words


@pytest.mark.parametrize("locale", ["en", "ru", "kk"])
def test_every_word_a_panel_says_is_in_every_catalogue(locale: str) -> None:
    """A string that reaches one catalogue and not another is a screen that is
    half translated, which is how this was found."""
    known = catalogue(locale)

    missing = sorted(word for word in fixed_words() if word not in known)

    assert not missing, f"{locale} has no word for: {missing}"


@pytest.mark.parametrize("locale", ["ru", "kk"])
def test_nothing_is_left_in_english_by_accident(locale: str) -> None:
    known = catalogue(locale)

    same = sorted(
        word
        for word in fixed_words()
        if known.get(word, "") == word and not word.isdigit()
    )

    assert not same, f"{locale} still says these in English: {same}"


def test_the_catalogues_have_no_empty_translations() -> None:
    """An empty msgstr falls back to English silently."""
    for locale in ("en", "ru", "kk"):
        empty = [
            entry.msgid
            for entry in polib.pofile(str(i18n.catalog_path(locale)))
            if not entry.msgstr
        ]
        assert not empty, f"{locale} leaves these empty: {empty}"


def test_the_font_that_can_draw_them_ships_with_the_application() -> None:
    """Panda3D's own font is Latin only, and two of the three languages came
    out as rows of empty boxes."""
    font = paths.packaged("fonts", "DejaVuSans.ttf")

    assert font.exists()
    assert font.stat().st_size > 100_000
    assert (font.parent / "LICENCE.txt").exists(), "a font ships with its licence"
