"""Build the application's icons from the team's logo.

One committed drawing, three generated files. Run it after changing the logo:

    uv run python scripts/make_icons.py
"""

from __future__ import annotations

from pathlib import Path

from app.icons import as_icns, as_ico, as_window_icon
from app.imaging import decode_png

ROOT = Path(__file__).resolve().parent.parent
LOGO = ROOT / "build-data" / "branding" / "ubt-logo.png"
BRANDING = ROOT / "app" / "data" / "branding"


def main() -> int:
    logo = decode_png(LOGO.read_bytes())
    BRANDING.mkdir(parents=True, exist_ok=True)
    written = {
        ROOT / "app" / "app.icns": as_icns(logo),
        ROOT / "app" / "app.ico": as_ico(logo),
        BRANDING / "icon.png": as_window_icon(logo),
    }
    for path, data in written.items():
        path.write_bytes(data)
        print(f"wrote {path.relative_to(ROOT)} - {len(data) / 1024:.0f} KiB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
