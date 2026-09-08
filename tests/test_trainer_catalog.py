from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.trainer import catalog
from app.trainer.catalog import (
    Trainer,
    TrainerDataError,
    UnknownTrainerError,
    load_catalogue,
    parse_trainer,
)


def valid_raw(**overrides: object) -> dict[str, object]:
    raw: dict[str, object] = {
        "id": "example-one",
        "brand": "Example",
        "model": "One",
        "kind": "wheel_on",
        "resistance": "fluid",
        "protocols": [],
        "profile": None,
        "notes": "",
    }
    raw.update(overrides)
    return raw


def write(directory: Path, raw: dict[str, object]) -> Path:
    path = directory / f"{raw['id']}.json"
    path.write_text(json.dumps(raw), encoding="utf-8")
    return path


def test_the_shipped_catalogue_loads() -> None:
    trainers = catalog.catalogue()

    assert len(trainers) >= 30
    assert len({trainer.id for trainer in trainers}) == len(trainers)


def test_every_shipped_trainer_can_be_shown_and_used() -> None:
    for trainer in catalog.catalogue():
        assert trainer.name.strip()
        assert trainer.kind in catalog.KINDS
        assert trainer.resistance in catalog.RESISTANCES
        # Either the trainer measures its own power, or the app can estimate it.
        assert trainer.reports_own_power or trainer.power_curve() is not None


def test_the_catalogue_offers_a_way_in_for_an_unlisted_trainer() -> None:
    ids = {trainer.id for trainer in catalog.catalogue()}

    assert {"generic-fluid", "generic-magnetic", "generic-smart-ftms"} <= ids


def test_nothing_ships_with_a_profile_yet() -> None:
    """Profiles are measured, not invented; the first one arrives by pull request."""
    assert not [t for t in catalog.catalogue() if t.is_calibrated]


def test_lookup_by_id() -> None:
    assert catalog.catalogue().get("generic-fluid").brand == "Generic"

    with pytest.raises(UnknownTrainerError, match="nonesuch"):
        catalog.catalogue().get("nonesuch")


def test_grouping_by_brand_is_alphabetical() -> None:
    grouped = catalog.catalogue().by_brand()

    assert list(grouped) == sorted(grouped)
    assert all(grouped.values())


def test_a_smart_trainer_is_believed_rather_than_estimated() -> None:
    trainer = catalog.catalogue().get("generic-smart-ftms")

    assert trainer.is_smart
    assert trainer.reports_own_power
    assert trainer.power_curve() is None


def test_a_classic_trainer_gets_an_uncalibrated_curve() -> None:
    trainer = catalog.catalogue().get("generic-fluid")

    assert not trainer.is_smart
    assert not trainer.is_calibrated
    assert trainer.power_curve() is not None


def test_a_recorded_profile_replaces_the_generic_curve(tmp_path: Path) -> None:
    write(
        tmp_path,
        valid_raw(
            profile={
                "coefficient": 0.4,
                "exponent": 2.9,
                "samples": 120,
                "rms_error_w": 4.2,
                "speed_range_kmh": [12.0, 45.0],
                "recorded_at": "2026-09-08",
                "wheel": "700c x 25 (2111 mm)",
            }
        ),
    )

    trainer = load_catalogue(tmp_path).get("example-one")

    assert trainer.is_calibrated
    assert trainer.power_curve() == trainer.profile.curve  # type: ignore[union-attr]
    assert trainer.profile.speed_range_kmh == (12.0, 45.0)  # type: ignore[union-attr]


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"kind": "hovercraft"}, "unknown kind"),
        ({"resistance": "steam"}, "unknown resistance"),
        ({"protocols": ["ftms", "smoke-signals"]}, "unknown protocols"),
    ],
)
def test_bad_values_are_rejected_with_the_file_named(
    overrides: dict[str, object], message: str
) -> None:
    raw = valid_raw(**overrides)

    with pytest.raises(TrainerDataError, match=message):
        parse_trainer(raw, Path(f"{raw['id']}.json"))


def test_a_missing_field_is_rejected() -> None:
    raw = valid_raw()
    del raw["brand"]

    with pytest.raises(TrainerDataError, match="missing 'brand'"):
        parse_trainer(raw, Path("example-one.json"))


def test_the_id_must_match_the_file_name() -> None:
    """Otherwise two files could claim one id and the loser would vanish silently."""
    with pytest.raises(TrainerDataError, match="does not match the file name"):
        parse_trainer(valid_raw(), Path("something-else.json"))


def test_an_unlisted_directory_loads_to_an_empty_catalogue(tmp_path: Path) -> None:
    assert len(load_catalogue(tmp_path)) == 0


def test_trainers_are_returned_in_a_stable_order(tmp_path: Path) -> None:
    for name in ("zebra", "alpha", "middle"):
        write(tmp_path, valid_raw(id=name))

    assert [t.id for t in load_catalogue(tmp_path)] == ["alpha", "middle", "zebra"]


def test_name_reads_the_way_a_picker_needs_it() -> None:
    trainer = Trainer(
        id="x",
        brand="Wahoo",
        model="KICKR CORE",
        kind="direct_drive",
        resistance="electromagnetic",
        protocols=("ftms",),
    )

    assert trainer.name == "Wahoo KICKR CORE"
