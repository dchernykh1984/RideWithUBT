"""Somewhere for the radios to run.

Bluetooth and ANT+ are asynchronous, and the renderer is a synchronous loop that
must not be blocked for a millisecond. So the device work runs on its own thread
with its own event loop, and the two meet in exactly two places: readings go into
the hub, which takes a lock, and commands go out through `submit`, which hands a
coroutine across and does not wait for it.

Not waiting is the point. A trainer command that took a hundred milliseconds to
acknowledge would otherwise drop three frames.
"""

from __future__ import annotations

import asyncio
import threading
from collections.abc import Coroutine
from concurrent.futures import Future
from typing import Any

# How long to give the loop to stop before giving up on it and moving on.
SHUTDOWN_TIMEOUT_S = 5.0


class SensorLoop:
    """An event loop on a thread of its own."""

    def __init__(self) -> None:
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._ready = threading.Event()

    @property
    def running(self) -> bool:
        return self._loop is not None and self._loop.is_running()

    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(target=self._run, name="sensors", daemon=True)
        self._thread.start()
        self._ready.wait(timeout=SHUTDOWN_TIMEOUT_S)

    def _run(self) -> None:
        loop = asyncio.new_event_loop()
        self._loop = loop
        asyncio.set_event_loop(loop)
        loop.call_soon(self._ready.set)
        loop.run_forever()
        loop.close()

    def submit(self, work: Coroutine[Any, Any, Any]) -> Future[Any] | None:
        """Start some device work and carry on. Returns None if nothing is running.

        The caller is a render frame, so it does not wait for the answer.
        """
        loop = self._loop
        if loop is None or not loop.is_running():
            work.close()
            return None
        return asyncio.run_coroutine_threadsafe(work, loop)

    def run(self, work: Coroutine[Any, Any, Any], timeout: float = 10.0) -> Any:
        """Start some device work and wait for it. For setup and shutdown only."""
        future = self.submit(work)
        if future is None:
            return None
        return future.result(timeout=timeout)

    def stop(self) -> None:
        loop, thread = self._loop, self._thread
        self._loop, self._thread = None, None
        self._ready.clear()
        if loop is None or thread is None:
            return
        loop.call_soon_threadsafe(loop.stop)
        thread.join(timeout=SHUTDOWN_TIMEOUT_S)
