#!/usr/bin/env python
"""Generate the surfaces the track is drawn with.

    uv run python scripts/make_textures.py

Writes `app/data/textures/*.png`. Like the built worlds, the results are tracked:
the application never generates them, it loads them, and a change to the code
that makes them shows up as a change to the images in a diff.
"""

from __future__ import annotations

import sys
from pathlib import Path

from app.world.texture import encode_png, ground_cover, track_surface

TEXTURES = Path(__file__).parent.parent / "app" / "data" / "textures"
SURFACES = {"track.png": track_surface, "ground.png": ground_cover}


def main() -> int:
    TEXTURES.mkdir(parents=True, exist_ok=True)
    for name, make in SURFACES.items():
        path = TEXTURES / name
        data = encode_png(make())
        path.write_bytes(data)
        print(f"wrote {path.name} ({len(data)} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
