"""Writing FIT files.

FIT is what Garmin Connect and Strava both want for a ride with power in it, and
it is the only format that carries the whole recording without losing something.
Nothing in Python writes it well, so this writes it: the format is a documented,
stable binary layout, and encoding it here is a few hundred lines that we control
and can test.

The structure is small once stated. A file is a header, a run of records and a
checksum. Each record is either a *definition* - this local slot now means this
global message, with these fields, in this order - or *data* in the shape the
last definition for that slot laid out. Numbers are little endian, and each field
has a scale and an offset it is stored in, so speed goes on disk in millimetres
per second and altitude in fifths of a metre above minus five hundred.

The tests decode what this writes with `fitparse`, an independent implementation,
rather than with this module's own reader - because a writer checked against
itself agrees with itself and nothing else.
"""

from __future__ import annotations

import struct
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime

# FIT counts seconds from this moment rather than from the unix epoch.
FIT_EPOCH = datetime(1989, 12, 31, tzinfo=UTC)
PROTOCOL_VERSION = 0x20  # 2.0
PROFILE_VERSION = 2140
HEADER_SIZE = 14
FIT_SIGNATURE = b".FIT"

# Base types, as the format numbers them. The high bit marks a multi-byte type.
BASE_ENUM = 0x00
BASE_UINT8 = 0x02
BASE_UINT16 = 0x84
BASE_SINT32 = 0x85
BASE_UINT32 = 0x86
BASE_UINT32Z = 0x8C

BASE_SIZES = {
    BASE_ENUM: 1,
    BASE_UINT8: 1,
    BASE_UINT16: 2,
    BASE_SINT32: 4,
    BASE_UINT32: 4,
    BASE_UINT32Z: 4,
}
BASE_FORMATS = {
    BASE_ENUM: "B",
    BASE_UINT8: "B",
    BASE_UINT16: "H",
    BASE_SINT32: "i",
    BASE_UINT32: "I",
    BASE_UINT32Z: "I",
}
# What a field is set to when there is nothing to say: all ones, except for the
# "z" types where zero is the invalid value.
INVALID = {
    BASE_ENUM: 0xFF,
    BASE_UINT8: 0xFF,
    BASE_UINT16: 0xFFFF,
    BASE_SINT32: 0x7FFFFFFF,
    BASE_UINT32: 0xFFFFFFFF,
    BASE_UINT32Z: 0,
}

# Global message numbers.
MESSAGE_FILE_ID = 0
MESSAGE_SESSION = 18
MESSAGE_LAP = 19
MESSAGE_RECORD = 20
MESSAGE_ACTIVITY = 34

# Enumerated values used below.
FILE_TYPE_ACTIVITY = 4
MANUFACTURER_DEVELOPMENT = 255
SPORT_CYCLING = 2
SUB_SPORT_VIRTUAL_ACTIVITY = 58
EVENT_LAP = 9
EVENT_SESSION = 8
EVENT_TYPE_STOP = 1
ACTIVITY_TYPE_MANUAL = 0
ACTIVITY_EVENT = 26

# Semicircles: the whole circle in 32 bits, which is how FIT stores coordinates.
SEMICIRCLES_PER_DEGREE = 2**31 / 180
# Scales the format stores things at.
DISTANCE_SCALE = 100  # centimetres
SPEED_SCALE = 1000  # millimetres per second
TIME_SCALE = 1000  # milliseconds
ALTITUDE_SCALE = 5
ALTITUDE_OFFSET = 500

CRC_TABLE = (
    0x0000, 0xCC01, 0xD801, 0x1400, 0xF001, 0x3C00, 0x2800, 0xE401,
    0xA001, 0x6C00, 0x7800, 0xB401, 0x5000, 0x9C01, 0x8801, 0x4400,
)  # fmt: skip


def crc16(data: bytes) -> int:
    """The checksum FIT puts at the end of a file, and inside its header."""
    crc = 0
    for byte in data:
        for nibble in (byte & 0x0F, (byte >> 4) & 0x0F):
            carry = CRC_TABLE[crc & 0xF]
            crc = (crc >> 4) & 0x0FFF
            crc = crc ^ carry ^ CRC_TABLE[nibble]
    return crc


def timestamp(moment: datetime) -> int:
    """Seconds since the FIT epoch."""
    if moment.tzinfo is None:
        raise ValueError("a recorded time without a timezone is not a time")
    return int((moment - FIT_EPOCH).total_seconds())


def semicircles(degrees: float) -> int:
    return round(degrees * SEMICIRCLES_PER_DEGREE)


@dataclass(frozen=True)
class Field:
    """One field of a message: which field it is, and how it is stored."""

    number: int
    base_type: int

    @property
    def size(self) -> int:
        return BASE_SIZES[self.base_type]


@dataclass
class Definition:
    """A local slot, and what the messages sent in it will contain."""

    local_number: int
    global_number: int
    fields: Sequence[Field]

    def encode(self) -> bytes:
        header = bytes([0x40 | self.local_number])
        body = struct.pack("<BBHB", 0, 0, self.global_number, len(self.fields))
        for item in self.fields:
            body += bytes([item.number, item.size, item.base_type])
        return header + body

    def encode_values(self, values: dict[int, int | None]) -> bytes:
        """One data message. Fields the caller left out are marked invalid."""
        out = bytes([self.local_number])
        for item in self.fields:
            value = values.get(item.number)
            if value is None:
                value = INVALID[item.base_type]
            out += struct.pack("<" + BASE_FORMATS[item.base_type], value)
        return out


@dataclass
class FitWriter:
    """Builds a FIT file one message at a time."""

    body: bytearray = field(default_factory=bytearray)
    _definitions: dict[int, Definition] = field(default_factory=dict)

    def define(self, definition: Definition) -> None:
        self._definitions[definition.local_number] = definition
        self.body += definition.encode()

    def write(self, local_number: int, values: dict[int, int | None]) -> None:
        definition = self._definitions.get(local_number)
        if definition is None:
            raise ValueError(f"local message {local_number} was never defined")
        self.body += definition.encode_values(values)

    def to_bytes(self) -> bytes:
        """The finished file: header, body, checksum."""
        header = struct.pack(
            "<BBHI4s",
            HEADER_SIZE,
            PROTOCOL_VERSION,
            PROFILE_VERSION,
            len(self.body),
            FIT_SIGNATURE,
        )
        header += struct.pack("<H", crc16(header))
        content = header + bytes(self.body)
        return content + struct.pack("<H", crc16(content))
