"""Command line entry point.

The packaged app is launched through this module, so it stays free of Panda3D
imports until a window is actually wanted: `--version` and `--languages` have to
work on a machine with no display and no GPU.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable, Sequence

from app import __version__, i18n, paths
from app.settings import Settings
from app.storage import activities as activity_store
from app.world.description import available_worlds
from app.world.description import load as load_world
from app.world.navigation import lap_length_m

# Repeated here rather than imported from app.render, which must not be imported
# until a window is actually wanted.
DEFAULT_WORLD = "sokol"
DEFAULT_POWER_W = 200.0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ridewithubt",
        description="Offline-first virtual world for indoor cycling training.",
    )
    parser.add_argument("--version", action="version", version=__version__)
    parser.add_argument(
        "--lang",
        choices=i18n.LOCALES,
        help="Language for this run; overrides the saved setting.",
    )
    parser.add_argument(
        "--languages",
        action="store_true",
        help="List the available languages and exit.",
    )
    parser.add_argument(
        "--world",
        default=DEFAULT_WORLD,
        help="Which world to ride. Defaults to the Sokol circuit.",
    )
    parser.add_argument(
        "--route",
        help="Which configuration of the world to ride, by id.",
    )
    parser.add_argument(
        "--power",
        type=float,
        default=DEFAULT_POWER_W,
        help="Watts the stand-in rider pushes, until sensors are connected.",
    )
    parser.add_argument(
        "--worlds",
        action="store_true",
        help="List the worlds and their routes, and exit.",
    )
    parser.add_argument(
        "--screenshot",
        metavar="PATH",
        help="Render the world into an image file instead of onto a screen.",
    )
    parser.add_argument(
        "--at",
        type=float,
        default=0.0,
        metavar="SECONDS",
        help="With --screenshot, how far into the lap to ride before the picture.",
    )
    parser.add_argument(
        "--no-record",
        action="store_true",
        help="Ride without keeping the recording.",
    )
    parser.add_argument(
        "--rides",
        action="store_true",
        help="List the recorded rides in the activity store, and exit.",
    )
    parser.add_argument(
        "--plan",
        metavar="PATH",
        help="Draw the whole world from above into an image file, and exit.",
    )
    parser.add_argument(
        "--selftest",
        action="store_true",
        help="Start the engine without a window, render a few frames and exit.",
    )
    return parser


def resolve_language(requested: str | None) -> str:
    return (
        i18n.normalise(requested) if requested else Settings.load().effective_language
    )


def listings(args: argparse.Namespace, language: str) -> int | None:
    """The commands that answer a question and exit.

    None of these open a window, so none of them may reach for the renderer -
    which is why they are answered before it is imported.
    """
    if args.languages:
        for code in i18n.LOCALES:
            marker = "*" if code == language else " "
            print(f"{marker} {code}  {i18n.locale_name(code)}")
        return 0

    if args.rides:
        recorded = activity_store.rides()
        for path in recorded:
            print(f"{path.name}  {path.stat().st_size / 1024:.0f} KB")
        if not recorded:
            print(f"no rides yet, in {paths.activities_dir()}")
        return 0

    if args.worlds:
        for world_id in available_worlds():
            world = load_world(world_id)
            print(f"{world_id}  {world.name}")
            for route in world.routes:
                lap = lap_length_m(world, route) / 1000
                print(f"    {route.id:22} {route.name:26} {lap:.3f} km")
        return 0

    return None


def render(args: argparse.Namespace, translate: Callable[[str], str]) -> int:
    """Everything that needs the engine, and therefore imports it."""
    from app.render.app import RideApp, plan_view, screenshot, selftest

    if args.selftest:
        selftest(translate, world_id=args.world)
        print("selftest ok")
        return 0

    if args.plan:
        plan_view(translate, args.plan, world_id=args.world)
        print(f"wrote {args.plan}")
        return 0

    if args.screenshot:
        screenshot(
            translate,
            args.screenshot,
            world_id=args.world,
            route_id=args.route,
            seconds=args.at,
            power_w=args.power,
        )
        print(f"wrote {args.screenshot}")
        return 0

    RideApp(
        translate,
        world_id=args.world,
        route_id=args.route,
        power_w=args.power,
        record=not args.no_record,
    ).run()
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    language = resolve_language(args.lang)
    translate = i18n.load(language)

    answered = listings(args, language)
    if answered is not None:
        return answered
    return render(args, translate)


if __name__ == "__main__":
    sys.exit(main())
