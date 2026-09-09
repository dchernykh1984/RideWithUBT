"""Making the surfaces the track is drawn with.

No photographs. A texture taken from somewhere is somebody's, and this project
does not use anybody's work without saying so - the same reason its geometry
comes from open data. These are generated: value noise for the grain of asphalt,
a pair of white lines where the track's edges are, and a coarser green for the
ground around it.

Generated is not a compromise here, it is the better fit. A texture that comes
out of a seed is small in the repository, reproducible from the code that made
it, and adjustable by changing a number rather than by finding another picture.

The images tile along the track and not across it: the ribbon's texture runs 0 to
1 across its width, however wide the track is, and repeats every few metres along
its length. So the top edge of an image meets its own bottom edge every few
metres, all the way round the circuit.

The grain is per-pixel, which is what makes that join invisible without any work:
neighbouring rows inside the image differ by exactly as much as the two rows
across the seam, so there is nothing there to see. A smoother, structured noise
would need wrapping; this one does not, and a test says so rather than leaving
the next person to wonder whether it was forgotten.
"""

from __future__ import annotations

import struct
import zlib
from dataclasses import dataclass

# A texture the track's whole width maps onto. Wider than it needs to be across,
# so the painted edges stay crisp when a rider is close to one.
DEFAULT_SIZE = 256
#: Where the edge lines sit, as a fraction of the track's width, and how wide.
EDGE_INSET = 0.035
EDGE_WIDTH = 0.022

ASPHALT = (74, 76, 80)
ASPHALT_GRAIN = 16
LINE = (232, 232, 228)
GRASS = (104, 112, 74)
GRASS_GRAIN = 18

Colour = tuple[int, int, int]


@dataclass(frozen=True)
class Image:
    """An RGB image, as rows of bytes."""

    width: int
    height: int
    pixels: bytes

    def __post_init__(self) -> None:
        expected = self.width * self.height * 3
        if len(self.pixels) != expected:
            raise ValueError(
                f"{self.width}x{self.height} needs {expected} bytes, got "
                f"{len(self.pixels)}"
            )

    def at(self, x: int, y: int) -> Colour:
        start = (y * self.width + x) * 3
        red, green, blue = self.pixels[start : start + 3]
        return (red, green, blue)


def encode_png(image: Image) -> bytes:
    """A PNG, written with nothing but the standard library.

    Pillow would do this in a line and is another dependency in the shipped
    application for the sake of a build-time script; the format's simplest form
    is a header, one deflated block and a checksum.
    """
    stride = image.width * 3
    raw = b"".join(
        b"\x00" + image.pixels[row * stride : (row + 1) * stride]
        for row in range(image.height)
    )
    return (
        b"\x89PNG\r\n\x1a\n"
        + _chunk(
            b"IHDR", struct.pack(">IIBBBBB", image.width, image.height, 8, 2, 0, 0, 0)
        )
        + _chunk(b"IDAT", zlib.compress(raw, 9))
        + _chunk(b"IEND", b"")
    )


def _chunk(kind: bytes, data: bytes) -> bytes:
    body = kind + data
    return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body))


def _grain(x: int, y: int, seed: int) -> float:
    """Deterministic per-pixel noise in 0..1."""
    return _hash(x, y, seed)


def _hash(x: int, y: int, seed: int) -> float:
    value = (x * 374761393 + y * 668265263 + seed * 1442695040888963407) & 0xFFFFFFFF
    value = (value ^ (value >> 13)) * 1274126177 & 0xFFFFFFFF
    return ((value ^ (value >> 16)) & 0xFFFF) / 0xFFFF


def _shade(base: Colour, grain: float, amount: int) -> Colour:
    shift = int((grain - 0.5) * 2 * amount)
    return tuple(  # type: ignore[return-value]
        max(0, min(255, channel + shift)) for channel in base
    )


def track_surface(size: int = DEFAULT_SIZE, seed: int = 1) -> Image:
    """Asphalt with a white line painted along each edge.

    The image's x axis runs across the track, so the lines are columns: this is
    what puts an edge line at the edge whatever the track's width.
    """
    pixels = bytearray()
    for y in range(size):
        for x in range(size):
            across = x / (size - 1)
            grain = _grain(x, y, seed)
            if _on_a_line(across):
                pixels.extend(_shade(LINE, grain, 6))
            else:
                pixels.extend(_shade(ASPHALT, grain, ASPHALT_GRAIN))
    return Image(width=size, height=size, pixels=bytes(pixels))


def _on_a_line(across: float) -> bool:
    from_edge = min(across, 1.0 - across)
    return EDGE_INSET <= from_edge < EDGE_INSET + EDGE_WIDTH


def ground_cover(size: int = DEFAULT_SIZE, seed: int = 2) -> Image:
    """The rough green the circuit sits on. Not terrain - a backdrop."""
    pixels = bytearray()
    for y in range(size):
        for x in range(size):
            grain = _grain(x, y, seed)
            pixels.extend(_shade(GRASS, grain, GRASS_GRAIN))
    return Image(width=size, height=size, pixels=bytes(pixels))
