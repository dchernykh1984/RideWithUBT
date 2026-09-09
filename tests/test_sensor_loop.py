"""The thread the radios run on.

The renderer must never block on a radio, so the loop's contract is: hand work
across and carry on, and be safe to ask when nothing is running."""

from __future__ import annotations

import asyncio
import threading

from app.sensors.loop import SensorLoop


async def note(seen: list[str], value: str) -> str:
    seen.append(value)
    return value


def test_a_loop_that_was_never_started_runs_nothing() -> None:
    loop = SensorLoop()
    seen: list[str] = []

    assert loop.submit(note(seen, "a")) is None
    assert not loop.running
    assert seen == []


def test_work_handed_across_is_done_on_the_other_thread() -> None:
    loop = SensorLoop()
    loop.start()
    threads: list[int] = []

    async def which_thread() -> int:
        return threading.get_ident()

    try:
        assert loop.running
        threads.append(loop.run(which_thread()))
    finally:
        loop.stop()

    assert threads[0] != threading.get_ident()


def test_submitting_does_not_wait_for_the_answer() -> None:
    loop = SensorLoop()
    loop.start()
    done = threading.Event()

    async def slow() -> None:
        await asyncio.sleep(0.05)
        done.set()

    try:
        future = loop.submit(slow())
        assert future is not None
        assert not done.is_set(), "submit returned before the work finished"
        assert future.result(timeout=2.0) is None
        assert done.is_set()
    finally:
        loop.stop()


def test_starting_twice_keeps_one_thread() -> None:
    loop = SensorLoop()
    loop.start()
    try:
        loop.start()
        assert loop.running
    finally:
        loop.stop()


def test_stopping_leaves_it_safe_to_use() -> None:
    loop = SensorLoop()
    loop.start()
    loop.stop()

    assert not loop.running
    assert loop.submit(note([], "a")) is None
    assert loop.run(note([], "b")) is None


def test_stopping_something_never_started_is_harmless() -> None:
    SensorLoop().stop()
