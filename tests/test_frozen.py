"""Finding a frozen build's own files.

This exists because of a shipped release that did not start. Every test passed,
the self-test passed on the frozen binary on all four platforms, and the
application still died a second after being double-clicked: Panda3D could not
find the display module that was sitting right there in the bundle.

So the finding is tested, on directories laid out the way each platform's build
actually lays them out.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app import frozen


def build_a_bundle(root: Path, layout: str, extension: str) -> Path:
    """A directory shaped like one of the builds this project ships."""
    panda = root / "panda3d" if layout == "package" else root
    panda.mkdir(parents=True, exist_ok=True)
    (panda / f"libpandagl{extension}").write_bytes(b"not really a library")
    (panda / f"libp3tinydisplay{extension}").write_bytes(b"nor this")
    etc = panda / "etc"
    etc.mkdir()
    (etc / "Config.prc").write_text("load-display pandagl\n")
    (etc / "Confauto.prc").write_text("# generated\n")
    return panda


def freeze(monkeypatch: pytest.MonkeyPatch, root: Path) -> None:
    monkeypatch.setattr(frozen.sys, "frozen", True, raising=False)
    monkeypatch.setattr(frozen.sys, "_MEIPASS", str(root), raising=False)


def test_running_from_source_has_nothing_to_fix() -> None:
    """The whole thing must be inert outside a build."""
    assert frozen.bundled_root() is None
    assert frozen.panda_plugin_dir() is None
    assert frozen.panda_config_dir() is None


@pytest.mark.parametrize(
    ("platform", "extension"),
    [("macOS", ".dylib"), ("Linux", ".so"), ("Windows", ".dll")],
)
def test_the_display_module_is_found_on_every_platform(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, platform: str, extension: str
) -> None:
    panda = build_a_bundle(tmp_path, "package", extension)
    freeze(monkeypatch, tmp_path)

    assert frozen.panda_plugin_dir() == panda, platform


def test_a_build_that_flattened_the_package_still_works(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """PyInstaller has moved these between the root and a folder before."""
    build_a_bundle(tmp_path, "flat", ".so")
    freeze(monkeypatch, tmp_path)

    assert frozen.panda_plugin_dir() == tmp_path


def test_the_config_files_are_found_too(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Without these nothing is configured to open a window at all, and that
    fault hides the missing plugin path behind it."""
    panda = build_a_bundle(tmp_path, "package", ".dylib")
    freeze(monkeypatch, tmp_path)

    assert frozen.panda_config_dir() == panda / "etc"


def test_config_files_beside_a_flattened_build(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    build_a_bundle(tmp_path, "flat", ".so")
    freeze(monkeypatch, tmp_path)

    assert frozen.panda_config_dir() == tmp_path / "etc"


def test_a_bundle_without_the_module_says_so_rather_than_guessing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A wrong guess here is an application that does not open."""
    (tmp_path / "panda3d").mkdir()
    freeze(monkeypatch, tmp_path)

    assert frozen.panda_plugin_dir() is None


def test_an_empty_etc_is_not_a_config_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "panda3d" / "etc").mkdir(parents=True)
    freeze(monkeypatch, tmp_path)

    assert frozen.panda_config_dir() is None


def test_a_file_where_a_directory_should_be_is_not_followed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "panda3d").write_text("not a directory")
    freeze(monkeypatch, tmp_path)

    assert frozen.panda_plugin_dir() is None
    assert frozen.panda_config_dir() is None


def test_a_build_that_did_not_say_where_it_unpacked(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """One-file builds set `_MEIPASS`; falling back to the executable's own
    directory is what covers a build that does not."""
    build_a_bundle(tmp_path, "package", ".so")
    monkeypatch.setattr(frozen.sys, "frozen", True, raising=False)
    monkeypatch.delattr(frozen.sys, "_MEIPASS", raising=False)
    monkeypatch.setattr(frozen.sys, "executable", str(tmp_path / "ridewithubt"))

    assert frozen.bundled_root() == tmp_path
    assert frozen.panda_plugin_dir() == tmp_path / "panda3d"


def test_the_names_looked_for_are_the_ones_panda_ships() -> None:
    """`libpandagl` opens the window; `libp3tinydisplay` is the fallback that
    lets a machine with no OpenGL at least start."""
    assert frozen.DISPLAY_MODULES == ("libpandagl", "libp3tinydisplay")
