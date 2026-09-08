"""Localisation: Russian, English and Kazakh.

Catalogues are plain gettext ``.po`` files under ``app/locale`` and are read
directly with polib, so there is no compile step and no ``.mo`` binary in the
repository. That also keeps translations out of the process-global state
``gettext.install`` sets up, which matters here because the renderer and the
settings screen can be asked to show different languages in the same run.

Source strings are English, because every tracked file in this repository is
ASCII; the translations themselves live in the ``.po`` files, which are not.
"""

from __future__ import annotations

import locale as locale_module
import os
from collections.abc import Mapping
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import polib

LOCALES: tuple[str, ...] = ("en", "ru", "kk")
DEFAULT_LOCALE = "en"
LOCALE_ENV_VAR = "RIDEWITHUBT_LANG"

LOCALE_DIR = Path(__file__).parent / "locale"


@dataclass(frozen=True)
class Translator:
    """A loaded catalogue. Call it to translate a source string."""

    locale: str
    catalog: Mapping[str, str]

    def __call__(self, message: str) -> str:
        return self.catalog.get(message, message)


def catalog_path(locale: str) -> Path:
    return LOCALE_DIR / f"{locale}.po"


def normalise(tag: str | None) -> str:
    """Reduce a locale tag such as ``ru_RU.UTF-8`` to a locale we ship."""
    if not tag:
        return DEFAULT_LOCALE
    language = tag.replace("-", "_").split("_", 1)[0].split(".", 1)[0].lower()
    return language if language in LOCALES else DEFAULT_LOCALE


def system_locale() -> str:
    """Best guess at the user's language, before any explicit setting."""
    override = os.environ.get(LOCALE_ENV_VAR)
    if override:
        return normalise(override)
    for name in ("LC_ALL", "LC_MESSAGES", "LANG"):
        value = os.environ.get(name)
        if value:
            return normalise(value)
    try:
        tag, _ = locale_module.getlocale(locale_module.LC_MESSAGES)
    except AttributeError, ValueError:  # pragma: no cover - platform dependent
        tag = None
    return normalise(tag)


@lru_cache(maxsize=len(LOCALES))
def load(locale: str = DEFAULT_LOCALE) -> Translator:
    """Load a catalogue. Unknown locales and missing files fall back to English."""
    locale = normalise(locale)
    path = catalog_path(locale)
    if not path.is_file():
        return Translator(locale=locale, catalog={})
    catalog = {
        entry.msgid: entry.msgstr
        for entry in polib.pofile(str(path))
        # A fuzzy entry is a machine-matched leftover from an edited source
        # string: gettext ignores those at runtime and so do we, rather than
        # showing a translation that belongs to different wording.
        if entry.msgstr and not entry.fuzzy and not entry.obsolete
    }
    return Translator(locale=locale, catalog=catalog)


def locale_name(locale: str) -> str:
    """The language's own name, for the language picker.

    Endonyms are translations, not code: every tracked source file here is ASCII,
    so "Russian" cannot be spelled in code. Each catalogue translates the string
    below into its own language instead.
    """
    return load(locale)("Language name")
