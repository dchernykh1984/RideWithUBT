"""The structural rule of this project, enforced rather than documented.

Only `app/render/` may import Panda3D. Everything else has to run headless, which
is what keeps the physics, the sensors and the workout engine testable without a
GPU - and what would let a second frontend be built later without touching them.
A violation is easy to add by accident and expensive to unpick once other code
depends on it, so it fails here.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

RENDER_PACKAGES = frozenset({"panda3d", "direct"})
APP_DIR = Path(__file__).resolve().parent.parent / "app"
RENDER_DIR = APP_DIR / "render"


def headless_modules() -> list[Path]:
    return sorted(
        path
        for path in APP_DIR.rglob("*.py")
        if RENDER_DIR not in path.parents and path != RENDER_DIR
    )


def imported_roots(source: str) -> set[str]:
    roots: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".", 1)[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            roots.add(node.module.split(".", 1)[0])
    return roots


@pytest.mark.parametrize("module", headless_modules(), ids=lambda path: path.name)
def test_only_the_renderer_imports_panda3d(module: Path) -> None:
    offenders = imported_roots(module.read_text(encoding="utf-8")) & RENDER_PACKAGES

    assert not offenders, (
        f"{module.relative_to(APP_DIR.parent)} imports {sorted(offenders)}; "
        "only app/render may."
    )


def test_the_guard_actually_sees_the_modules() -> None:
    """A path bug here would silently pass the rule for every file."""
    names = {path.name for path in headless_modules()}

    assert {"cli.py", "i18n.py", "settings.py", "paths.py"} <= names
    assert "app.py" not in names  # app/render/app.py is the module it must exclude
