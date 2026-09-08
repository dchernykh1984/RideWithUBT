"""Command line entry point.

The packaged app is launched through this module, so it stays free of Panda3D
imports until a window is actually wanted: `--version` and `--languages` have to
work on a machine with no display and no GPU.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence

from app import __version__, i18n
from app.settings import Settings


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ridewithubt",
        description="Offline-first virtual world for indoor cycling training.",
    )
    parser.add_argument("--version", action="version", version=__version__)
    parser.add_argument(
        "--lang",
        choices=i18n.LOCALES,
        help="Language for this run; overrides the saved setting.",
    )
    parser.add_argument(
        "--languages",
        action="store_true",
        help="List the available languages and exit.",
    )
    parser.add_argument(
        "--selftest",
        action="store_true",
        help="Start the engine without a window, render a few frames and exit.",
    )
    return parser


def resolve_language(requested: str | None) -> str:
    return (
        i18n.normalise(requested) if requested else Settings.load().effective_language
    )


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    language = resolve_language(args.lang)
    translate = i18n.load(language)

    if args.languages:
        for code in i18n.LOCALES:
            marker = "*" if code == language else " "
            print(f"{marker} {code}  {i18n.locale_name(code)}")
        return 0

    # Imported here, not at module level, so the checks above never need a GPU.
    from app.render.app import RideApp, selftest

    if args.selftest:
        selftest(translate)
        print("selftest ok")
        return 0

    RideApp(translate).run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
