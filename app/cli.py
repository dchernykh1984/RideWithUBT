"""Command line entry point.

The packaged app is launched through this module, so it stays free of Panda3D
imports until a window is actually wanted: `--version` and `--languages` have to
work on a machine with no display and no GPU.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from collections.abc import Callable, Sequence

from app import __version__, i18n, paths, selfcheck
from app.sensors.discovery import default_transports
from app.sensors.hub import SensorHub
from app.sensors.manager import DeviceManager
from app.services.credentials import CredentialsError
from app.services.garmin_session import GarminLoginError, connect_to_garmin
from app.services.strava_session import (
    CLIENT_ID,
    CLIENT_SECRET,
    StravaKeys,
    StravaSetupError,
    authorize_url,
    connect_to_strava,
    exchange_strava_code,
)
from app.services.upload import GarminUploader, Uploader, send
from app.services.uploads import UploadLog
from app.settings import Settings
from app.storage import activities as activity_store
from app.workout import library as workout_library
from app.world.description import available_worlds
from app.world.description import load as load_world
from app.world.navigation import lap_length_m

# Repeated here rather than imported from app.render, which must not be imported
# until a window is actually wanted.
DEFAULT_WORLD = "sokol"
DEFAULT_POWER_W = 200.0
DEFAULT_SCAN_SECONDS = 6.0
DEFAULT_IMPORT_LIMIT = 20


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
        "--capture-trainer",
        action="store_true",
        help="Measure this trainer's power curve during the ride and write it out.",
    )
    parser.add_argument(
        "--no-record",
        action="store_true",
        help="Ride without keeping the recording.",
    )
    parser.add_argument(
        "--scan",
        nargs="?",
        type=float,
        const=DEFAULT_SCAN_SECONDS,
        metavar="SECONDS",
        help="Look for sensors on every radio, list what answered, and exit.",
    )
    parser.add_argument(
        "--pair",
        metavar="DEVICE_ID",
        help="Remember a device, so it is connected at the start of every ride.",
    )
    parser.add_argument(
        "--unpair",
        metavar="DEVICE_ID",
        help="Forget a paired device.",
    )
    parser.add_argument(
        "--devices",
        action="store_true",
        help="List the paired devices, and exit.",
    )
    parser.add_argument(
        "--workout",
        metavar="NAME_OR_PATH",
        help="Ride a structured workout: a name from the library, or a file.",
    )
    parser.add_argument(
        "--import-garmin",
        nargs="?",
        type=int,
        const=DEFAULT_IMPORT_LIMIT,
        metavar="COUNT",
        help="Download your latest Garmin Connect workouts into the library.",
    )
    parser.add_argument(
        "--garmin-user",
        metavar="EMAIL",
        help="The Garmin Connect account to use. Remembered after the first time.",
    )
    parser.add_argument(
        "--workouts",
        action="store_true",
        help="List the workouts in the library, and exit.",
    )
    parser.add_argument(
        "--upload",
        nargs="?",
        const="all",
        choices=["all", "garmin", "strava"],
        metavar="SERVICE",
        help="Send the rides that have not gone up yet.",
    )
    parser.add_argument(
        "--strava-setup",
        nargs=2,
        metavar=("CLIENT_ID", "CLIENT_SECRET"),
        help="Start connecting your own Strava API application.",
    )
    parser.add_argument(
        "--strava-code",
        metavar="CODE",
        help="Finish connecting Strava, with the code from the browser.",
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


def print_languages(active: str) -> None:
    for code in i18n.LOCALES:
        marker = "*" if code == active else " "
        print(f"{marker} {code}  {i18n.locale_name(code)}")


def scan_for_devices(seconds: float) -> None:
    found = asyncio.run(
        DeviceManager(hub=SensorHub(), transports=default_transports()).scan(seconds)
    )
    for device in found:
        metrics = ", ".join(sorted(device.metrics))
        control = " (controllable)" if device.controllable else ""
        print(f"{device.id}\n    {device.label}{control}\n    {metrics}")
    if not found:
        print("nothing answered - check the sensors are awake and in range")


def pair_device(device_id: str) -> None:
    settings = Settings.load()
    if device_id not in settings.paired_device_ids:
        settings.paired_device_ids.append(device_id)
        settings.save()
    print(f"paired {device_id}")


def unpair_device(device_id: str) -> None:
    settings = Settings.load()
    if device_id in settings.paired_device_ids:
        settings.paired_device_ids.remove(device_id)
        settings.save()
    print(f"unpaired {device_id}")


def print_paired_devices() -> None:
    paired = Settings.load().paired_device_ids
    for device_id in paired:
        print(device_id)
    if not paired:
        print("no devices paired yet - run --scan to find them")


def import_garmin_workouts(limit: int, username: str | None) -> None:
    """Download workouts into the library, reporting each one as it lands."""
    settings = Settings.load()
    account = username or settings.garmin_username
    if not account:
        print("say which account with --garmin-user EMAIL")
        return
    try:
        workouts = connect_to_garmin(account)
    except (CredentialsError, GarminLoginError) as error:
        print(str(error))
        return
    if account != settings.garmin_username:
        settings.garmin_username = account
        settings.save()
    summaries = workouts.list(limit)
    for summary, workout, problem in workouts.download(summaries):
        if workout is None:
            print(f"skipped {summary.name}: {problem}")
            continue
        print(f"{workout.name} -> {workout_library.save(workout).name}")
    if not summaries:
        print("that account has no workouts to import")


def upload_rides(which: str) -> None:
    """Send whatever has not gone up, to whichever service was asked for."""
    rides = activity_store.rides()
    if not rides:
        print("no rides to upload")
        return
    log = UploadLog.load()
    for service in ("garmin", "strava") if which == "all" else (which,):
        uploader = _uploader_for(service)
        if uploader is None:
            continue
        for result in send(uploader, rides, log):
            if result.ok:
                print(f"{result.ride.name} -> {service} {result.reference}".rstrip())
            else:
                print(result.problem)
    log.save()


def _uploader_for(service: str) -> Uploader | None:
    try:
        if service == "garmin":
            username = Settings.load().garmin_username
            if not username:
                print("say which Garmin account with --garmin-user EMAIL")
                return None
            return GarminUploader(client=connect_to_garmin(username).client)
        return connect_to_strava()
    except (CredentialsError, GarminLoginError, StravaSetupError) as error:
        print(str(error))
        return None


def start_strava_setup(client_id: str, client_secret: str) -> None:
    StravaKeys.write(CLIENT_ID, client_id)
    StravaKeys.write(CLIENT_SECRET, client_secret)
    print("open this, allow access, then copy the `code` from the address bar:")
    print(authorize_url(client_id))
    print("then run: ridewithubt --strava-code CODE")


def finish_strava_setup(code: str) -> None:
    try:
        exchange_strava_code(code)
    except StravaSetupError as error:
        print(str(error))
        return
    print("Strava connected")


def print_rides() -> None:
    recorded = activity_store.rides()
    for path in recorded:
        print(f"{path.name}  {path.stat().st_size / 1024:.0f} KB")
    if not recorded:
        print(f"no rides yet, in {paths.activities_dir()}")


def print_workouts() -> None:
    library = workout_library.load_library()
    for workout in library:
        total = workout.total_time_s
        length = f"{total / 60:.0f} min" if total else "open ended"
        print(f"{workout.name}  ({len(workout.ridden_steps)} steps, {length})")
    if not len(library):
        print(f"no workouts yet, in {paths.workouts_dir()}")
    for broken in workout_library.unreadable():
        print(f"could not read {broken.name}")


def print_worlds() -> None:
    for world_id in available_worlds():
        world = load_world(world_id)
        print(f"{world_id}  {world.name}")
        for route in world.routes:
            lap = lap_length_m(world, route) / 1000
            print(f"    {route.id:22} {route.name:26} {lap:.3f} km")


def listings(args: argparse.Namespace, language: str) -> int | None:
    """The commands that answer a question and exit.

    None of these open a window, so none of them may reach for the renderer -
    which is why they are answered before it is imported.
    """
    asked = (
        (args.languages, lambda: print_languages(language)),
        (args.scan is not None, lambda: scan_for_devices(args.scan)),
        (args.pair, lambda: pair_device(args.pair)),
        (args.unpair, lambda: unpair_device(args.unpair)),
        (args.devices, print_paired_devices),
        (args.upload is not None, lambda: upload_rides(args.upload)),
        (
            args.strava_setup is not None,
            lambda: start_strava_setup(*(args.strava_setup or ("", ""))),
        ),
        (args.strava_code, lambda: finish_strava_setup(args.strava_code)),
        (
            args.import_garmin is not None,
            lambda: import_garmin_workouts(args.import_garmin, args.garmin_user),
        ),
        (args.rides, print_rides),
        (args.workouts, print_workouts),
        (args.worlds, print_worlds),
    )
    for wanted, report in asked:
        if wanted:
            report()
            return 0
    return None


def render(args: argparse.Namespace, translate: Callable[[str], str]) -> int:
    """Everything that needs the engine, and therefore imports it."""
    from app.render.app import RideApp, plan_view, screenshot, selftest

    if args.selftest:
        problems = (
            selfcheck.missing()
            + [
                f"{name}: not in this build"
                for name in selfcheck.missing_dependencies()
            ]
            + [
                f"{name}: a test tool that should not ship"
                for name in selfcheck.stowaway_dev_tools()
            ]
        )
        if problems:
            for problem in problems:
                print(f"missing from this build: {problem}")
            return 1
        selftest(translate, world_id=args.world)
        print(
            f"selftest ok - {len(selfcheck.LATE_IMPORTS)} late imports and "
            f"{len(selfcheck.LATE_DEPENDENCIES)} late dependencies present"
        )
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

    settings = Settings.load()
    RideApp(
        translate,
        world_id=args.world,
        route_id=args.route,
        power_w=args.power,
        record=not args.no_record,
        workout=workout_library.find(args.workout) if args.workout else None,
        paired_device_ids=settings.paired_device_ids,
        control_mode=settings.trainer_control,
        capture_trainer=args.capture_trainer or settings.record_trainer_data,
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
