"""One logo, three icon formats, built rather than hand-made.

An icon is the same drawing at eight sizes. Committing eight files and hoping
they stay in step is how an application ends up with an old logo in the dock
and a new one on the desktop, so they are all derived from the one drawing -
the same rule the worlds follow.
"""

from __future__ import annotations

import struct
from pathlib import Path

import pytest

from app import icons, paths
from app.imaging import Image, ImageError, decode_png, encode_png, resize

LOGO = (
    Path(__file__).resolve().parent.parent / "build-data" / "branding" / "ubt-logo.png"
)


def logo() -> Image:
    return decode_png(LOGO.read_bytes())


def flat(width: int, height: int, colour: tuple[int, int, int, int]) -> Image:
    return Image(width, height, tuple(tuple([colour] * width) for _ in range(height)))


# Reading a PNG back in.


def test_the_logo_is_read_as_the_picture_it_is() -> None:
    picture = logo()

    assert (picture.width, picture.height) == (600, 600)
    assert picture.pixels[0][0] == (0, 0, 0, 0), "the corner is transparent"


def test_a_picture_survives_being_written_and_read_back() -> None:
    original = flat(4, 3, (200, 100, 50, 255))

    again = decode_png(encode_png(original))

    assert again == original


@pytest.mark.parametrize(
    "colour", [(10, 20, 30, 255), (0, 0, 0, 0), (255, 255, 255, 128)]
)
def test_every_channel_comes_back_unchanged(colour: tuple[int, int, int, int]) -> None:
    assert decode_png(encode_png(flat(2, 2, colour))).pixels[0][0] == colour


def test_something_that_is_not_a_png_says_so() -> None:
    with pytest.raises(ImageError, match="not a PNG"):
        decode_png(b"this is a jpeg, honestly")


def test_a_png_with_no_picture_in_it_says_so() -> None:
    with pytest.raises(ImageError, match="no picture"):
        decode_png(b"\x89PNG\r\n\x1a\n")


# Making it smaller.


def test_shrinking_gives_the_size_asked_for() -> None:
    small = resize(logo(), 32)

    assert (small.width, small.height) == (32, 32)


def test_a_flat_colour_shrinks_to_the_same_flat_colour() -> None:
    small = resize(flat(60, 60, (255, 102, 0, 255)), 6)

    assert all(pixel == (255, 102, 0, 255) for row in small.pixels for pixel in row)


def test_shrinking_averages_rather_than_picking_one_pixel() -> None:
    """A line drawing is mostly thin parts; picking one pixel in thirty loses
    them, and the logo is a line drawing of a cyclist."""
    checks = Image(
        2,
        2,
        (
            ((0, 0, 0, 255), (255, 255, 255, 255)),
            ((255, 255, 255, 255), (0, 0, 0, 255)),
        ),
    )

    single = resize(checks, 1)

    assert single.pixels[0][0] == (127, 127, 127, 255)


def test_an_icon_has_to_be_some_size() -> None:
    with pytest.raises(ImageError):
        resize(logo(), 0)


# The formats.


def test_the_windows_icon_says_what_it_holds() -> None:
    data = icons.as_ico(logo(), sizes=(16, 32, 256))

    reserved, kind, count = struct.unpack("<HHH", data[:6])
    assert (reserved, kind) == (0, 1)
    assert count == 3


def test_every_entry_points_at_a_real_picture() -> None:
    """An offset that is wrong by one is an icon Windows silently ignores."""
    data = icons.as_ico(logo(), sizes=(16, 32))

    (count,) = struct.unpack("<H", data[4:6])
    for index in range(count):
        entry = data[6 + 16 * index : 6 + 16 * (index + 1)]
        length, offset = struct.unpack("<II", entry[8:16])
        picture = data[offset : offset + length]
        assert decode_png(picture).width in (16, 32)


def test_the_largest_windows_entry_is_written_as_zero() -> None:
    """256 does not fit in the byte the format gives it, and zero means 256."""
    data = icons.as_ico(logo(), sizes=(256,))

    assert data[6] == 0
    assert data[7] == 0


def test_the_mac_icon_is_a_container_of_the_right_length() -> None:
    data = icons.as_icns(logo(), types=((b"ic07", 128), (b"ic08", 256)))

    assert data[:4] == b"icns"
    assert struct.unpack(">I", data[4:8])[0] == len(data)


def test_every_mac_block_is_tagged_and_sized() -> None:
    wanted = ((b"ic07", 128), (b"ic08", 256))

    data = icons.as_icns(logo(), types=wanted)

    at = 8
    seen = []
    while at < len(data):
        kind = data[at : at + 4]
        (length,) = struct.unpack(">I", data[at + 4 : at + 8])
        seen.append(kind)
        assert decode_png(data[at + 8 : at + length]).width in (128, 256)
        at += length
    assert seen == [kind for kind, _ in wanted]


def test_a_size_used_twice_is_only_drawn_once() -> None:
    """The retina entries are the same pixels as their plain counterparts."""
    drawn = icons.sized(logo(), (256, 256, 128))

    assert sorted(drawn) == [128, 256]


# What actually ships.


def test_the_icons_in_the_tree_match_the_logo() -> None:
    """Generated files go stale. This is what notices."""
    root = LOGO.parent.parent.parent
    picture = logo()

    assert (root / "app" / "app.icns").read_bytes() == icons.as_icns(picture)
    assert (root / "app" / "app.ico").read_bytes() == icons.as_ico(picture)
    assert paths.packaged("branding", "icon.png").read_bytes() == icons.as_window_icon(
        picture
    )


def test_the_window_icon_ships_with_the_application() -> None:
    """Not just in the repository: inside the package that gets frozen."""
    assert paths.packaged("branding", "icon.png").exists()


# Every kind of PNG the logo could arrive as.


def build_png(
    rows: list[list[int]],
    width: int,
    *,
    depth: int = 8,
    colour: int = 6,
    interlace: int = 0,
    filters: list[int] | None = None,
) -> bytes:
    """A PNG assembled by hand, so each way of reading one can be exercised."""
    import zlib

    header = struct.pack(">IIBBBBB", width, len(rows), depth, colour, 0, 0, interlace)
    raw = bytearray()
    for index, row in enumerate(rows):
        raw.append(filters[index] if filters else 0)
        raw += bytes(row)

    def chunk(kind: bytes, payload: bytes) -> bytes:
        body = kind + payload
        return (
            struct.pack(">I", len(payload)) + body + struct.pack(">I", zlib.crc32(body))
        )

    return b"".join(
        [
            b"\x89PNG\r\n\x1a\n",
            chunk(b"IHDR", header),
            chunk(b"IDAT", zlib.compress(bytes(raw))),
            chunk(b"IEND", b""),
        ]
    )


def apply_filter(rows: list[list[int]], kind: int, channels: int) -> list[list[int]]:
    """Filter pixel rows the way a PNG encoder would, so decoding can undo it."""
    filtered = []
    previous = [0] * len(rows[0])
    for row in rows:
        line = []
        for index, value in enumerate(row):
            left = row[index - channels] if index >= channels else 0
            up = previous[index]
            upleft = previous[index - channels] if index >= channels else 0
            if kind == 0:
                line.append(value)
            elif kind == 1:
                line.append((value - left) & 0xFF)
            elif kind == 2:
                line.append((value - up) & 0xFF)
            elif kind == 3:
                line.append((value - (left + up) // 2) & 0xFF)
            else:
                estimate = left + up - upleft
                nearest = min(
                    (left, up, upleft),
                    key=lambda option: (
                        abs(estimate - option),
                        (left, up, upleft).index(option),
                    ),
                )
                line.append((value - nearest) & 0xFF)
        filtered.append(line)
        previous = row
    return filtered


@pytest.mark.parametrize("kind", [0, 1, 2, 3, 4])
def test_every_row_filter_a_png_may_use_is_undone(kind: int) -> None:
    """A real drawing arrives filtered, and an encoder picks per row: any of
    the five is legal. One this cannot undo is a silently wrong picture."""
    wanted = [
        [10, 20, 30, 255, 40, 50, 60, 255],
        [70, 80, 90, 255, 11, 12, 13, 255],
        [14, 15, 16, 255, 200, 210, 220, 255],
    ]

    picture = decode_png(
        build_png(
            apply_filter(wanted, kind, channels=4),
            width=2,
            filters=[kind] * len(wanted),
        )
    )

    assert picture.pixels[0][0] == (10, 20, 30, 255)
    assert picture.pixels[1][1] == (11, 12, 13, 255)
    assert picture.pixels[2][1] == (200, 210, 220, 255)


def test_a_filter_that_is_not_one_of_the_five_says_so() -> None:
    with pytest.raises(ImageError, match="filter 9"):
        decode_png(build_png([[0, 0, 0, 255]], width=1, filters=[9]))


@pytest.mark.parametrize(
    ("colour", "row", "expected"),
    [
        (0, [128], (128, 128, 128, 255)),
        (4, [128, 64], (128, 128, 128, 64)),
        (2, [10, 20, 30], (10, 20, 30, 255)),
        (6, [10, 20, 30, 40], (10, 20, 30, 40)),
    ],
    ids=["grey", "grey-alpha", "rgb", "rgba"],
)
def test_a_png_without_all_four_channels_is_given_them(
    colour: int, row: list[int], expected: tuple[int, int, int, int]
) -> None:
    """Everything downstream sees RGBA, whatever arrived."""
    picture = decode_png(build_png([row], width=1, colour=colour))

    assert picture.pixels[0][0] == expected


def test_a_sixteen_bit_png_is_refused_rather_than_misread() -> None:
    with pytest.raises(ImageError, match="16-bit"):
        decode_png(build_png([[0, 0, 0, 0, 0, 0, 0, 0]], width=1, depth=16))


def test_an_interlaced_png_is_refused_rather_than_misread() -> None:
    with pytest.raises(ImageError, match="interlaced"):
        decode_png(build_png([[0, 0, 0, 255]], width=1, interlace=1))


def test_a_palette_png_is_refused_rather_than_misread() -> None:
    """Colour type 3 needs the palette chunk, which this does not read."""
    with pytest.raises(ImageError, match="colour type 3"):
        decode_png(build_png([[0]], width=1, colour=3))


def test_a_png_that_stops_early_says_so() -> None:
    truncated = build_png([[0, 0, 0, 255], [0, 0, 0, 255]], width=1)
    header_end = truncated.index(b"IDAT")
    import zlib

    short = zlib.compress(bytes([0, 1, 2, 3, 4]))  # one row's worth, not two
    rebuilt = bytearray(truncated[: header_end - 4])
    rebuilt += struct.pack(">I", len(short))
    body = b"IDAT" + short
    rebuilt += body + struct.pack(">I", zlib.crc32(body))
    rebuilt += truncated[truncated.index(b"IEND") - 4 :]

    with pytest.raises(ImageError, match="ends before"):
        decode_png(bytes(rebuilt))
