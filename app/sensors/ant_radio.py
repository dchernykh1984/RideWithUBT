"""The USB stick, driven by openant.

Everything here needs hardware, so nothing here is covered by the test suite -
it is excluded in `pyproject.toml` for the same reason `app/render` is. What can
be tested lives behind the `Radio` protocol in `ant.py`, which this implements.

Two things make this more than a thin wrapper. openant drives the stick from its
own blocking loop, so the node runs in a worker thread and every broadcast is
handed back to the event loop with `call_soon_threadsafe`. And each ANT+ profile
broadcasts at its own channel period, which has to be set before the channel is
opened or the sensor is simply never heard.
"""

from __future__ import annotations

import asyncio
import threading
from collections.abc import Callable
from typing import Any

from app.sensors import ant_protocol as pages

# The channel period each profile broadcasts at, in 1/32768 s. A wrong period
# does not error; the channel just stays silent.
CHANNEL_PERIODS: dict[int, int] = {
    pages.DEVICE_HEART_RATE: 8070,
    pages.DEVICE_POWER: 8182,
    pages.DEVICE_SPEED_CADENCE: 8086,
    pages.DEVICE_CADENCE: 8102,
    pages.DEVICE_SPEED: 8118,
    pages.DEVICE_FITNESS_EQUIPMENT: 8192,
}
RF_FREQUENCY = 57
# Zero means "any device of this type", which is how pairing works.
WILDCARD_DEVICE_NUMBER = 0


class AntRadioError(RuntimeError):
    """No stick, no driver, or openant is not installed."""


class OpenAntRadio:  # pragma: no cover - needs an ANT+ stick
    """Owns one ANT+ node and the channels opened on it."""

    def __init__(self) -> None:
        self._node: Any = None
        self._thread: threading.Thread | None = None
        self._channels: dict[tuple[int, int], Any] = {}
        self._lock = threading.Lock()

    def _ensure_node(self) -> Any:
        if self._node is not None:
            return self._node
        try:
            from openant.devices import ANTPLUS_NETWORK_KEY
            from openant.easy.node import Node
        except ImportError as error:
            raise AntRadioError(
                "openant is not available; ANT+ needs it and a USB stick"
            ) from error
        try:
            node = Node()
            node.set_network_key(0x00, ANTPLUS_NETWORK_KEY)
        except Exception as error:
            raise AntRadioError(
                "could not open an ANT+ stick: check that one is plugged in, and "
                "that libusb and its driver are installed"
            ) from error
        self._node = node
        self._thread = threading.Thread(target=node.start, daemon=True)
        self._thread.start()
        return node

    async def subscribe(
        self,
        device_type: int,
        device_number: int,
        on_broadcast: Callable[[bytes], None],
    ) -> None:
        loop = asyncio.get_running_loop()

        def deliver(data: Any) -> None:
            # Called on openant's thread; hop back to the event loop before
            # anything else in the app sees it.
            loop.call_soon_threadsafe(on_broadcast, bytes(data))

        await asyncio.to_thread(self._open, device_type, device_number, deliver)

    def _open(
        self, device_type: int, device_number: int, deliver: Callable[[Any], None]
    ) -> None:
        from openant.easy.channel import Channel

        node = self._ensure_node()
        with self._lock:
            key = (device_type, device_number)
            if key in self._channels:
                return
            channel = node.new_channel(Channel.Type.BIDIRECTIONAL_RECEIVE)
            channel.set_id(device_number, device_type, WILDCARD_DEVICE_NUMBER)
            channel.set_period(CHANNEL_PERIODS.get(device_type, 8192))
            channel.set_rf_freq(RF_FREQUENCY)
            channel.on_broadcast_data = deliver
            channel.open()
            self._channels[key] = channel

    async def unsubscribe(self, device_type: int, device_number: int) -> None:
        await asyncio.to_thread(self._close, device_type, device_number)

    def _close(self, device_type: int, device_number: int) -> None:
        with self._lock:
            channel = self._channels.pop((device_type, device_number), None)
        if channel is not None:
            channel.close()

    async def shutdown(self) -> None:
        """Close every channel and stop the node, releasing the stick."""
        await asyncio.to_thread(self._shutdown)

    def _shutdown(self) -> None:
        with self._lock:
            channels = list(self._channels.values())
            self._channels.clear()
        for channel in channels:
            channel.close()
        if self._node is not None:
            self._node.stop()
            self._node = None
