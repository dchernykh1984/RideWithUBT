"""The team's logo, as the icon each platform wants.

Three formats, one picture. macOS reads `.icns`, Windows reads `.ico`, and the
window itself is given a plain PNG at runtime so the icon in the dock or the
taskbar is the same one while the application is running - not only on the file
a rider double-clicks.

Both container formats are simple enough to write directly, and both accept
PNGs inside them, which is why there is no image library here. What they need
is the same drawing at a handful of sizes, and `app/imaging.py` makes those
from the one logo committed under `build-data/branding/`.
"""

from __future__ import annotations

import struct
from collections.abc import Sequence

from app.imaging import Image, encode_png, resize

#: What Windows asks for. 256 goes in as a PNG, the rest as PNGs too - every
#: Windows since Vista reads them, and this application needs a far newer one.
ICO_SIZES = (16, 24, 32, 48, 64, 128, 256)

#: What macOS asks for, and the four-letter type it files each size under. The
#: retina entries are the same pixels as their plain counterparts at twice the
#: size, which is what a doubled icon is.
ICNS_TYPES: tuple[tuple[bytes, int], ...] = (
    (b"icp4", 16),
    (b"icp5", 32),
    (b"ic11", 32),
    (b"ic12", 64),
    (b"ic07", 128),
    (b"ic13", 256),
    (b"ic08", 256),
    (b"ic14", 512),
    (b"ic09", 512),
    (b"ic10", 1024),
)

#: The size the running window is given. Big enough for a dock, small enough
#: not to be worth more.
WINDOW_ICON_SIZE = 256


def sized(logo: Image, sizes: Sequence[int]) -> dict[int, bytes]:
    """The logo as a PNG at each size, made once and shared between formats."""
    return {size: encode_png(resize(logo, size)) for size in sorted(set(sizes))}


def as_ico(logo: Image, sizes: Sequence[int] = ICO_SIZES) -> bytes:
    """A Windows icon: a directory of entries, then the pictures."""
    pictures = sized(logo, sizes)
    order = sorted(pictures)
    offset = 6 + 16 * len(order)
    directory = bytearray(struct.pack("<HHH", 0, 1, len(order)))
    body = bytearray()
    for size in order:
        png = pictures[size]
        directory += struct.pack(
            "<BBBBHHII",
            0 if size >= 256 else size,  # 256 is written as zero
            0 if size >= 256 else size,
            0,  # not a palette
            0,  # reserved
            1,  # colour planes
            32,  # bits per pixel
            len(png),
            offset,
        )
        body += png
        offset += len(png)
    return bytes(directory + body)


def as_icns(logo: Image, types: Sequence[tuple[bytes, int]] = ICNS_TYPES) -> bytes:
    """A macOS icon: a header, then one tagged block per size."""
    pictures = sized(logo, [size for _, size in types])
    blocks = bytearray()
    for kind, size in types:
        png = pictures[size]
        blocks += kind + struct.pack(">I", len(png) + 8) + png
    return b"icns" + struct.pack(">I", len(blocks) + 8) + bytes(blocks)


def as_window_icon(logo: Image, size: int = WINDOW_ICON_SIZE) -> bytes:
    return encode_png(resize(logo, size))
