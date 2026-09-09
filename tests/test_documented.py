"""Every command this application has is written down.

Documentation drifts silently: a flag is added, the README is not, and the only
way anybody finds the feature is by reading the source. Cheap to check, so it is
checked."""

from __future__ import annotations

from pathlib import Path

from app.cli import build_parser

README = Path(__file__).resolve().parent.parent / "README.md"


def flags() -> set[str]:
    return {
        option
        # argparse offers no public list of its options.
        for action in build_parser()._actions
        for option in action.option_strings
        if option.startswith("--")
    }


def test_every_flag_is_in_the_readme() -> None:
    text = README.read_text(encoding="utf-8")
    # `--help` is argparse's own and needs no telling.
    undocumented = sorted(
        flag for flag in flags() if flag != "--help" and flag not in text
    )

    assert undocumented == []


def test_the_readme_only_shows_flags_that_exist() -> None:
    """The other direction: an example nobody can run is worse than none."""
    import re

    text = README.read_text(encoding="utf-8")
    shown = {
        flag
        for line in re.findall(r"uv run ridewithubt ([^\n#]*)", text)
        for flag in re.findall(r"--[a-z-]+", line)
    }

    assert shown - flags() == set()
