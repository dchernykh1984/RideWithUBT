from __future__ import annotations

import asyncio

import pytest

from app.sensors.base import Transport
from app.sensors.hub import SensorHub
from app.sensors.simulated import (
    SOURCE_ID,
    RiderState,
    SimulatedSensors,
    intervals,
    steady,
    wobble,
)
from app.sensors.types import Metric, Reading


def test_it_announces_itself_as_a_device() -> None:
    device = SimulatedSensors().device

    assert device.transport is Transport.SIMULATED
    assert Metric.POWER in device.metrics
    assert not device.controllable
    assert device.label == "Simulated sensors (simulated)"


def test_a_sample_covers_every_metric_it_claims() -> None:
    source = SimulatedSensors()

    readings = source.sample(elapsed_s=0.0, now=100.0)

    assert {r.metric for r in readings} == source.device.metrics
    assert all(r.source == SOURCE_ID and r.at == 100.0 for r in readings)
    assert not any(r.estimated for r in readings)


def test_the_same_moment_always_gives_the_same_ride() -> None:
    """Determinism is what makes this usable in a test."""
    first = SimulatedSensors().sample(elapsed_s=17.0, now=0.0)
    second = SimulatedSensors().sample(elapsed_s=17.0, now=0.0)

    assert first == second


def test_values_move_but_stay_near_the_profile() -> None:
    source = SimulatedSensors(steady(power_w=200.0))

    powers = [
        next(
            r.value
            for r in source.sample(elapsed_s=t, now=0.0)
            if r.metric is Metric.POWER
        )
        for t in range(0, 30)
    ]

    assert len(set(powers)) > 1
    assert all(190 < power < 210 for power in powers)


def test_wobble_is_bounded_and_centred() -> None:
    values = [wobble(Metric.POWER, elapsed_s=t / 4) for t in range(200)]

    assert 0.95 < min(values) < 1.0 < max(values) < 1.05


def test_a_metric_with_no_wobble_is_left_alone() -> None:
    assert wobble(Metric.SPEED, elapsed_s=3.0) == 1.0


def test_steady_holds_one_effort() -> None:
    profile = steady(power_w=175.0, cadence_rpm=88.0, heart_rate_bpm=142.0)

    assert profile(0.0) == profile(600.0) == RiderState(175.0, 88.0, 142.0)


def test_intervals_alternate_work_and_rest() -> None:
    profile = intervals(work_s=60.0, rest_s=30.0, work_w=280.0, rest_w=120.0)

    assert profile(0.0).power_w == 280.0
    assert profile(59.0).power_w == 280.0
    assert profile(60.0).power_w == 120.0
    assert profile(89.0).power_w == 120.0
    # And the cycle repeats.
    assert profile(90.0).power_w == 280.0


def test_intervals_move_cadence_and_heart_rate_with_the_effort() -> None:
    profile = intervals(work_s=60.0, rest_s=30.0)

    work, rest = profile(10.0), profile(70.0)

    assert work.cadence_rpm > rest.cadence_rpm
    assert work.heart_rate_bpm > rest.heart_rate_bpm


async def test_connecting_feeds_a_hub_until_disconnected() -> None:
    collected: list[Reading] = []
    source = SimulatedSensors(interval_s=0.01)

    await source.connect(collected.append)
    await asyncio.sleep(0.05)
    await source.disconnect()
    delivered = len(collected)
    await asyncio.sleep(0.03)

    assert delivered > 0
    assert len(collected) == delivered, "readings kept arriving after disconnect"


async def test_connecting_twice_does_not_start_a_second_stream() -> None:
    source = SimulatedSensors(interval_s=0.01)
    collected: list[Reading] = []

    await source.connect(collected.append)
    await source.connect(collected.append)
    await asyncio.sleep(0.03)
    await source.disconnect()

    # One stream: every batch covers each metric exactly once.
    per_batch = len(source.device.metrics)
    assert len(collected) % per_batch == 0


async def test_disconnecting_without_connecting_is_harmless() -> None:
    await SimulatedSensors().disconnect()


async def test_what_it_produces_reads_back_through_the_hub() -> None:
    hub = SensorHub()
    source = SimulatedSensors(steady(power_w=210.0), interval_s=0.01)

    await source.connect(hub.submit)
    await asyncio.sleep(0.03)
    await source.disconnect()

    snapshot = hub.snapshot(now=asyncio.get_running_loop().time())
    assert snapshot.power is not None
    assert snapshot.power.value == pytest.approx(210.0, rel=0.05)
    assert not snapshot.power.estimated
