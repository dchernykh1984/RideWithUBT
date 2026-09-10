"""The surfaces the track is drawn with.

Generated rather than photographed - a texture taken from somewhere is somebody's
- and generated deterministically, so the images in the repository can be checked
against the code that made them."""

from __future__ import annotations

import struct
import zlib
from itertools import pairwise
from pathlib import Path

import pytest

from app.world.texture import (
    ASPHALT,
    DEFAULT_SIZE,
    LINE,
    Image,
    encode_png,
    ground_cover,
    track_surface,
    wall,
)

TEXTURES = Path(__file__).resolve().parent.parent / "app" / "data" / "textures"


def chunks(data: bytes) -> list[tuple[bytes, bytes]]:
    """Walk a PNG, checking every chunk's own checksum on the way."""
    assert data[:8] == b"\x89PNG\r\n\x1a\n"
    found, offset = [], 8
    while offset < len(data):
        (length,) = struct.unpack(">I", data[offset : offset + 4])
        kind = data[offset + 4 : offset + 8]
        body = data[offset + 8 : offset + 8 + length]
        (checksum,) = struct.unpack(
            ">I", data[offset + 8 + length : offset + 12 + length]
        )
        assert checksum == zlib.crc32(kind + body), f"{kind!r} chunk is corrupt"
        found.append((kind, body))
        offset += 12 + length
    return found


def test_an_image_checks_its_own_size() -> None:
    with pytest.raises(ValueError, match="needs 12 bytes"):
        Image(width=2, height=2, pixels=b"\x00" * 6)


def test_a_written_png_is_a_png() -> None:
    data = encode_png(track_surface(size=32))

    kinds = [kind for kind, _ in chunks(data)]
    assert kinds == [b"IHDR", b"IDAT", b"IEND"]


def test_the_header_says_what_the_image_is() -> None:
    data = encode_png(track_surface(size=64))

    (_, header), *_ = chunks(data)
    width, height, depth, colour = struct.unpack(">IIBB", header[:10])
    assert (width, height) == (64, 64)
    assert (depth, colour) == (8, 2), "eight bits a channel, true colour"


def test_the_pixels_come_back_out_again() -> None:
    """Round-tripped through zlib and the row filters, which is where it breaks."""
    image = track_surface(size=16)

    raw = zlib.decompress(dict(chunks(encode_png(image)))[b"IDAT"])

    stride = image.width * 3
    for row in range(image.height):
        start = row * (stride + 1)
        assert raw[start] == 0, "every row is filtered as None"
        assert (
            raw[start + 1 : start + 1 + stride]
            == image.pixels[row * stride : (row + 1) * stride]
        )


def test_the_same_seed_makes_the_same_surface() -> None:
    """Otherwise the tracked images would change on every build for no reason."""
    assert track_surface(size=32).pixels == track_surface(size=32).pixels
    assert (
        track_surface(size=32, seed=1).pixels != track_surface(size=32, seed=9).pixels
    )


def test_the_track_is_painted_at_both_edges() -> None:
    surface = track_surface()

    middle_row = DEFAULT_SIZE // 2
    across = [surface.at(x, middle_row)[0] for x in range(DEFAULT_SIZE)]
    left = max(across[: DEFAULT_SIZE // 4])
    right = max(across[-DEFAULT_SIZE // 4 :])
    centre = max(across[DEFAULT_SIZE // 3 : 2 * DEFAULT_SIZE // 3])

    assert left > LINE[0] - 20 and right > LINE[0] - 20, "a line at each edge"
    assert centre < ASPHALT[0] + 30, "and none down the middle of a racetrack"


def test_the_lines_are_inside_the_edge_not_on_it() -> None:
    """Paint that ran off the side of the road would flicker along the rim."""
    surface = track_surface()
    row = DEFAULT_SIZE // 2

    assert surface.at(0, row)[0] < ASPHALT[0] + 30
    assert surface.at(DEFAULT_SIZE - 1, row)[0] < ASPHALT[0] + 30


def test_the_surface_joins_itself_along_the_track() -> None:
    """It repeats every few metres, so its last row meets its first.

    A seam would be a line across the road at that spacing, all the way round the
    circuit. What makes it invisible is that the grain is per-pixel: the two rows
    across the join differ by no more than any other neighbouring pair, so there
    is nothing there to see.
    """
    surface = track_surface()

    def step(top: int, bottom: int) -> float:
        return (
            sum(
                abs(surface.at(x, top)[0] - surface.at(x, bottom)[0])
                for x in range(DEFAULT_SIZE)
            )
            / DEFAULT_SIZE
        )

    across_the_seam = step(DEFAULT_SIZE - 1, 0)
    inside = [step(row, row + 1) for row in range(0, DEFAULT_SIZE - 1, 17)]

    assert across_the_seam <= max(inside) * 1.2


def test_the_ground_is_green_and_grainy() -> None:
    ground = ground_cover(size=64)

    reds = {ground.at(x, y)[0] for x in range(64) for y in range(64)}
    greens = {ground.at(x, y)[1] for x in range(64) for y in range(64)}
    assert len(reds) > 5, "not a flat colour"
    assert max(greens) > max(reds), "green"


def test_the_shipped_textures_are_what_the_code_makes() -> None:
    """Nobody can drop a photograph in: the images have to come from the seed."""
    assert (TEXTURES / "track.png").read_bytes() == encode_png(track_surface())
    assert (TEXTURES / "ground.png").read_bytes() == encode_png(ground_cover())


# The side of a building.


def test_a_wall_is_concrete_with_a_band_of_windows() -> None:
    """It is what makes a building read as a building rather than a grey box."""
    image = wall(size=64)

    top = _colour_at(image, x=32, y=4)
    middle = _colour_at(image, x=8, y=32)

    assert _brightness(top) > _brightness(middle), "windows are darker than concrete"


def test_the_windows_are_in_panes_rather_than_one_long_strip() -> None:
    image = wall(size=128)
    row = [_colour_at(image, x=x, y=64) for x in range(128)]

    dark = [_brightness(colour) < 120 for colour in row]
    runs = sum(1 for before, after in pairwise(dark) if before != after)

    assert runs >= 6, "four panes have eight edges between them"


def test_a_wall_has_ground_and_sky_ends_that_are_not_glazed() -> None:
    image = wall(size=64)

    assert _brightness(_colour_at(image, x=32, y=1)) > 120
    assert _brightness(_colour_at(image, x=32, y=62)) > 120


def test_a_wall_is_not_flat_colour() -> None:
    image = wall(size=32)
    shades = {_colour_at(image, x=x, y=2) for x in range(32)}

    assert len(shades) > 4, "concrete has grain in it"


def _colour_at(image: Image, x: int, y: int) -> tuple[int, int, int]:
    at = (y * image.width + x) * 3
    return (image.pixels[at], image.pixels[at + 1], image.pixels[at + 2])


def _brightness(colour: tuple[int, int, int]) -> float:
    return sum(colour) / 3
