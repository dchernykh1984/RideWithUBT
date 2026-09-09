"""The radios this machine actually has.

Building the real transports is kept apart from everything that uses them, so a
test can hand a `DeviceManager` fakes and never touch a radio - and so the ANT+
stick is only reached for when somebody asks to scan.
"""

from __future__ import annotations

from app.sensors.ant import AntTransport
from app.sensors.ble import BleTransport
from app.sensors.manager import DeviceTransport


def default_transports() -> list[DeviceTransport]:
    """Bluetooth, and ANT+ if a stick can be opened.

    A missing stick is normal, not an error: most riders have none, and the ones
    who do plug it in when they want it.
    """
    transports: list[DeviceTransport] = [BleTransport()]
    ant = _ant_transport()
    if ant is not None:
        transports.append(ant)
    return transports


def _ant_transport() -> AntTransport | None:  # pragma: no cover - needs a stick
    from app.sensors.ant_radio import AntRadioError, OpenAntRadio

    try:
        return AntTransport(OpenAntRadio())
    except AntRadioError, ImportError, OSError:
        return None
