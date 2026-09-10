"""Reading a PNG back in, and making it smaller.

The application already writes PNGs with nothing but the standard library, for
the textures it generates. This is the other direction, for the one image this
project does not generate: the team's logo, which becomes the icon a rider
double-clicks.

An icon is the same picture at eight sizes. Rather than commit eight hand-made
files and hope they stay in step, the logo is committed once and the sizes are
derived from it - which is the same rule the worlds follow, and means a new
logo is a one-file change.

Nothing here is a general image library. It reads the kind of PNG the logo is -
eight-bit, not interlaced - and says so plainly when handed anything else,
because a build that silently produces a wrong icon is worse than one that
stops.
"""

from __future__ import annotations

import struct
import zlib
from dataclasses import dataclass

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"

#: Channels per pixel, by PNG colour type. The two without an alpha channel are
#: read and given an opaque one, so everything downstream sees RGBA.
CHANNELS = {0: 1, 2: 3, 4: 2, 6: 4}


class ImageError(ValueError):
    """A PNG this cannot read. Said plainly rather than guessed at."""


@dataclass(frozen=True)
class Image:
    """A picture as rows of RGBA pixels."""

    width: int
    height: int
    pixels: tuple[tuple[tuple[int, int, int, int], ...], ...]


def decode_png(data: bytes) -> Image:
    """Read an eight-bit PNG into pixels."""
    if not data.startswith(PNG_SIGNATURE):
        raise ImageError("that is not a PNG")
    header, body = _chunks(data)
    width, height, depth, colour, _compress, _filter, interlace = struct.unpack(
        ">IIBBBBB", header
    )
    if depth != 8:
        raise ImageError(f"{depth}-bit PNGs are not read here, only 8-bit")
    if interlace:
        raise ImageError("interlaced PNGs are not read here")
    if colour not in CHANNELS:
        raise ImageError(f"colour type {colour} is not a kind of PNG this reads")
    channels = CHANNELS[colour]
    raw = zlib.decompress(body)
    return Image(width, height, _unfilter(raw, width, height, channels))


def resize(image: Image, size: int) -> Image:
    """The same picture at ``size`` square, by averaging the pixels that fall in
    each new one.

    A box average rather than nearest-neighbour: an icon is mostly a shrink,
    and picking one pixel out of thirty throws away the thin parts of a drawing
    - which for a line drawing of a cyclist is most of it.
    """
    if size <= 0:
        raise ImageError("an icon has to be some size")
    rows = []
    for y in range(size):
        top = y * image.height // size
        bottom = max(top + 1, (y + 1) * image.height // size)
        row = []
        for x in range(size):
            left = x * image.width // size
            right = max(left + 1, (x + 1) * image.width // size)
            row.append(_average(image, left, top, right, bottom))
        rows.append(tuple(row))
    return Image(size, size, tuple(rows))


def encode_png(image: Image) -> bytes:
    """Write it back out, as the icon formats want it."""
    raw = bytearray()
    for row in image.pixels:
        raw.append(0)  # filter type: none
        for red, green, blue, alpha in row:
            raw += bytes((red, green, blue, alpha))
    header = struct.pack(">IIBBBBB", image.width, image.height, 8, 6, 0, 0, 0)
    return b"".join(
        [
            PNG_SIGNATURE,
            _chunk(b"IHDR", header),
            _chunk(b"IDAT", zlib.compress(bytes(raw), 9)),
            _chunk(b"IEND", b""),
        ]
    )


def _average(
    image: Image, left: int, top: int, right: int, bottom: int
) -> tuple[int, int, int, int]:
    totals = [0, 0, 0, 0]
    count = 0
    for y in range(top, bottom):
        for x in range(left, right):
            pixel = image.pixels[y][x]
            for channel in range(4):
                totals[channel] += pixel[channel]
            count += 1
    return (
        totals[0] // count,
        totals[1] // count,
        totals[2] // count,
        totals[3] // count,
    )


def _chunks(data: bytes) -> tuple[bytes, bytes]:
    """The header, and every image chunk joined up."""
    header = b""
    body = bytearray()
    at = len(PNG_SIGNATURE)
    while at + 8 <= len(data):
        (length,) = struct.unpack(">I", data[at : at + 4])
        kind = data[at + 4 : at + 8]
        payload = data[at + 8 : at + 8 + length]
        if kind == b"IHDR":
            header = payload
        elif kind == b"IDAT":
            body += payload
        elif kind == b"IEND":
            break
        at += 12 + length
    if not header or not body:
        raise ImageError("that PNG has no picture in it")
    return header, bytes(body)


def _unfilter(
    raw: bytes, width: int, height: int, channels: int
) -> tuple[tuple[tuple[int, int, int, int], ...], ...]:
    """Undo the per-row filters PNG uses to make itself compress well."""
    stride = width * channels
    previous = bytearray(stride)
    rows = []
    at = 0
    for _ in range(height):
        if at >= len(raw):
            raise ImageError("that PNG ends before its last row")
        kind = raw[at]
        line = bytearray(raw[at + 1 : at + 1 + stride])
        at += 1 + stride
        _undo(kind, line, previous, channels)
        rows.append(_as_rgba(line, width, channels))
        previous = line
    return tuple(rows)


def _undo(kind: int, line: bytearray, previous: bytearray, channels: int) -> None:
    if kind == 0:
        return
    for index in range(len(line)):
        left = line[index - channels] if index >= channels else 0
        up = previous[index]
        upleft = previous[index - channels] if index >= channels else 0
        if kind == 1:
            line[index] = (line[index] + left) & 0xFF
        elif kind == 2:
            line[index] = (line[index] + up) & 0xFF
        elif kind == 3:
            line[index] = (line[index] + (left + up) // 2) & 0xFF
        elif kind == 4:
            line[index] = (line[index] + _paeth(left, up, upleft)) & 0xFF
        else:
            raise ImageError(f"filter {kind} is not one a PNG may use")


def _paeth(left: int, up: int, upleft: int) -> int:
    estimate = left + up - upleft
    by_left, by_up, by_upleft = (
        abs(estimate - left),
        abs(estimate - up),
        abs(estimate - upleft),
    )
    if by_left <= by_up and by_left <= by_upleft:
        return left
    return up if by_up <= by_upleft else upleft


def _as_rgba(
    line: bytearray, width: int, channels: int
) -> tuple[tuple[int, int, int, int], ...]:
    row = []
    for x in range(width):
        pixel = line[x * channels : (x + 1) * channels]
        if channels == 1:
            row.append((pixel[0], pixel[0], pixel[0], 255))
        elif channels == 2:
            row.append((pixel[0], pixel[0], pixel[0], pixel[1]))
        elif channels == 3:
            row.append((pixel[0], pixel[1], pixel[2], 255))
        else:
            row.append((pixel[0], pixel[1], pixel[2], pixel[3]))
    return tuple(row)


def _chunk(kind: bytes, payload: bytes) -> bytes:
    body = kind + payload
    return struct.pack(">I", len(payload)) + body + struct.pack(">I", zlib.crc32(body))
