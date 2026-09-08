"""Test-wide isolation of the user data tree.

Every test runs against a throwaway data directory: the app otherwise writes
settings into the maintainer's real one, and a test that saves settings would
change the language of their installed build.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from app import i18n, paths


@pytest.fixture(autouse=True)
def isolated_data_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv(paths.HOME_ENV_VAR, str(tmp_path / "data"))
    return tmp_path / "data"


@pytest.fixture(autouse=True)
def clear_catalog_cache() -> Iterator[None]:
    """Catalogues are cached for the process; a test must not inherit that."""
    i18n.load.cache_clear()
    yield
    i18n.load.cache_clear()
