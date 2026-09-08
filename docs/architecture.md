# Architecture

The decisions this project is built on, and why. Change the code freely; change
this document when a decision changes.

## What RideWithUBT is

A virtual world you ride in while your bike is on a trainer. It shows a real
place, reads your sensors, can run a structured workout, records the ride and
hands the recording to Garmin Connect or Strava.

It is **offline-first in the strong sense**: the application is fully usable with
the network cable pulled. There is no account, no login and no server that has to
be up for you to ride. The only network traffic is what you ask for - fetching a
workout from Garmin Connect, uploading a finished ride - and it goes **directly**
from your machine to that service. RideWithUBT operates no server that ride data
passes through, and adding one is explicitly out of scope.

Riding with other people is a later, opt-in feature (see *Multiplayer*), designed
for now so it can be added without turning the app inside out.

## Language and stack

**Python 3.14, rendered with Panda3D.** The alternatives considered were a Godot
frontend driven by a Python core, and Godot alone.

What decided it:

- Every device and service library this project needs exists in Python and
  nowhere else in usable form: `bleak` and `pycycling` for Bluetooth Low Energy
  sensors and FTMS/FE-C trainer control, `openant` for ANT+ USB sticks,
  `garminconnect`, `stravalib`, `python-fitparse`, `gpxpy`. Several are already
  in use in sibling projects here.
- Panda3D is a C++ engine with Python as its first-class language. Since 1.10.16
  it ships wheels for CPython 3.14 on Windows, macOS and Linux, which is exactly
  the platform set this project targets. Rendering, culling and the scene graph
  run in C++; the Python side updates a handful of entities per frame, which is
  not where the time goes.
- One language means one toolchain, one test suite and one packaging pipeline,
  matching how the other projects in this workspace are already built.

What we accept in exchange:

- The picture will be plainer than a commercial title's. That is a content and
  shader problem, not a language problem, and it is not what this app is for.
- Android is not a target. Panda3D's Android support is experimental and `bleak`
  does not work there at all. If tablets are ever wanted, the answer is a
  separate frontend speaking to the same core, not a rewrite - which is what the
  layout rule below protects.

## Layout

```
app/
  cli.py          entry point; imports the renderer lazily
  paths.py        the single static data tree
  settings.py     user settings
  i18n.py         localisation
  locale/         ru, en, kk catalogues (.po)
  render/         Panda3D. The ONLY package allowed to import it.
```

Planned, in the order they are meant to arrive:

```
  core/           units, rider and bike model, ride physics, ride session
  trainer/        wheel and tyre sizes, virtual power, trainer profiles
  sensors/        BLE and ANT+ device layer behind one interface
  workout/        workout model, plan import, the interval engine
  world/          world description, generators, the built scene graph
  services/       Garmin Connect and Strava, called directly
  storage/        the activity store and FIT writing
  data/           catalogues, textures and world descriptions (tracked, shipped)
build-data/       raw generator inputs, tracked but not shipped
```

Data lives in two places for one reason: `app/data/` is inside the package, so it
travels into the frozen app, while `build-data/` holds inputs only the generators
need - a raw OpenStreetMap extract is worth tracking for reproducibility and
worth leaving out of a user's download.

**The one structural rule: only `app/render/` may import Panda3D or touch the
window.** Everything else has to run headless. That is what keeps the physics,
the sensors and the workout engine testable in CI without a GPU, and what would
let a second frontend be added later without touching them.

## Sensors

One interface, two transports. A sensor is a source of typed readings - power,
cadence, speed, heart rate, trainer status - and the rest of the app never learns
whether a reading arrived over Bluetooth or ANT+.

- **Bluetooth Low Energy** through `bleak` for the radio, with the standard
  characteristics parsed here rather than by a library: Cycling Power, Cycling
  Speed and Cadence, Heart Rate, and the Fitness Machine Service's Indoor Bike
  Data. Those payloads are public and stable, and parsing them ourselves is what
  makes the whole translation path - bytes in, readings out - testable with no
  radio, which a library wrapped around a live client is not.
- **ANT+** through `openant` for the radio and a USB stick (ANTUSB2 /
  ANTUSB-m), with the device profile pages parsed here for the same reason as the
  Bluetooth ones. Windows needs the libusb driver, Linux needs the udev rule
  `openant` installs, macOS needs libusb only. openant drives the stick from its
  own blocking loop, so the node runs in a worker thread behind a small radio
  interface - which is also what lets the connect path be tested without one.

Smart trainers are first-class: where a trainer exposes FTMS or Tacx FE-C the app
both reads its power and writes resistance back to it, which is what makes ERG
intervals and on-course gradient real rather than cosmetic.

## Power, wheels and trainer profiles

This works in **both directions**, and which direction is active is an explicit
setting, not a guess.

**Forward - estimate power.** You have a plain trainer and a speed sensor. You
tell the app the trainer model, the wheel diameter (700c, 650b, 29, 27.5, 26, 28
and so on) and the tyre width (23, 25, 28, 30, 32 mm, 2.1 in, ...), or type an
exact rollout in millimetres if you have measured it. Wheel speed and the
trainer's power curve then give power. The catalogue of standard sizes ships with
the app; the manual entry is always available because catalogue rollouts are
nominal.

**Reverse - measure a trainer.** You have both a speed sensor and a real power
meter. Turn on *record trainer data* and ride: the app pairs measured wheel speed
with measured power, fits a curve, and writes a trainer profile. That profile is
a data file in this repository's `data/trainers/` directory, and the app offers
to open a pull request with it, so the next person with the same trainer gets a
calibrated curve instead of a guess. This is a separate, deliberately entered
mode with its own screen - it is never on by default and never silently
collecting.

Profiles are versioned data, reviewed like code. A profile carries the trainer
model, the resistance setting it was recorded at, the tyre and pressure, the
sample count and the fit error, because a curve without those is not reusable.

The catalogue ships with the popular trainers and **no profiles at all**: a
measured curve is the one thing that cannot be invented, so until someone records
one, a classic trainer is estimated from a generic curve for its resistance type
and every watt it produces is marked uncalibrated. Smart trainers are never
estimated - they measure their own power, and the device is believed.

The catalogue is a hint, not an authority. Which protocols a trainer really
speaks is discovered when it connects; the entries exist so a rider can set up
before anything is plugged in. One file per trainer, so contributing one is a
pull request that cannot conflict with anyone else's.

## Workouts and plans

Two sources, one internal model:

- **Garmin Connect** - workouts and training plans pulled directly from the
  user's own account, using their credentials, with nothing in between.
- **`training_plan_generator` JSON** - the format already in use in this
  workspace: `steps` of `warmup`/`interval`/`rest`/`cooldown`/`repeat` with
  power, cadence and heart-rate targets, and duration by time, distance or open.

Both are parsed into one workout model, so the interval engine, the HUD and the
recorder do not care where a session came from.

## The world

**Worlds are generated by code from data tracked in this repository.** There is
no hand-built 3D scene to maintain and nothing downloaded at build time: a world
is a description file plus its inputs - track geometry from OpenStreetMap,
elevation from an open terrain model, and textures authored here - and a
generator turns them into a scene. The inputs live in `build-data/`, the built
world in `app/data/worlds/`, and both are tracked, which is what makes a build
reproducible and a world reviewable in a pull request.

The junctions are not written down. A node that more than one of the named ways
passes through is a place where the rider can choose, and the generator finds
those itself; the way named as the circuit proper supplies the default at each.
So a recipe only names the ways and the configurations, and the same code builds
any circuit whose alternatives are drawn as separate ways - which is how
OpenStreetMap draws them.

The first and, for now, only world is the **Sokol International Racetrack** near
Almaty. Nothing is copied from any existing simulator's version of it - the
geometry comes from OpenStreetMap and the textures are ours. Its four published
configurations - big ring, big ring with chicane, small ring, small ring with
chicane - fall out of the generator as four routes over one network, and each
measures within a couple of percent of the published length. The shortfall is
expected and one-sided: OpenStreetMap traces the centre of the track, while a
circuit is measured along its racing line.

Elevation is not in the extract, so the built circuit is flat for now. The format
carries it and the physics reads it, so filling it in from a terrain model
changes the generator and nothing else.

**Only the track surface is modelled**: both rings and the pit lane. The
surrounding landscape is not the point of this app and is not built.

That makes the world a *road network*, not a loop: the big ring (4.495 km), the
small ring (3.535 km) and the pit lane share sections and part at junctions. The
network is a graph of track segments joined at nodes, and every node with more
than one exit is a junction the rider steers through.

### Junctions

A junction is announced before it arrives, not at it. An arrow appears overhead
while the rider is still approaching, pointing at the way they are *currently*
going to go - the default, which is the big ring unless the description says
otherwise. Pressing left or right swings the arrow to the other exit, and it can
be changed as many times as the rider likes while the junction is still ahead.
Whichever way the arrow points at the moment the rider reaches the node is the
way they go.

This is deliberately not a steering model. The rider is never off the racing
line, cannot crash and cannot miss a turn by reacting late; the only decision is
which branch, and it is made in advance and shown the whole time. Announce
distance is a property of the junction, so a fast approach can be given more
warning than a slow one.

Adding a second world later means adding a description and its inputs, not
touching the engine. That is the only sense in which the map system is
"extensible" - the extension point is data, not a plugin API.

## Storage

One static tree, chosen per platform, holding everything the app knows:
settings, generated worlds and every recorded ride as a FIT file. No profiles, no
scattered directories, no hidden cache elsewhere - backing up that one directory
backs up everything. `RIDEWITHUBT_HOME` moves it; the tests use that.

## Uploads

Direct, and only on request. Garmin Connect and Strava are called from the user's
machine with the user's own credentials. Nothing is relayed, mirrored or queued
on a server belonging to this project, because there is no such server.

## Multiplayer

Out of scope for now, designed for anyway. The ride session already treats other
riders as a list of remote entities with position, speed, cadence and power, so a
network source can be added beside the local one later. When it arrives, it will
be opt-in per ride, it will carry only that telemetry, and the app will stay
fully functional with it switched off.

## Localisation

Russian, English and Kazakh, first-class from the start. Source strings are
English because every tracked source file is ASCII; the translations live in
gettext `.po` catalogues under `app/locale/`, read directly with polib - no
compile step and no `.mo` binaries in the repository.

## Packaging and release

Conventional Commits drive release-please, which cuts the release and tags it.
The same run builds portable, unsigned artifacts with PyInstaller for Linux
x86_64 and aarch64, Windows x64 and macOS arm64, and attaches them to the
release. Pull requests get a fast Linux-only smoke build that freezes the app and
then runs `--selftest` against the frozen binary, so a packaging break is caught
before it ships.

Windows on ARM is not built: Panda3D publishes no wheel for it.

## Roadmap

1. Scaffold: tooling, CI, packaging, localisation, a window that opens. *(done)*
2. Wheel and tyre catalogue, rollout, virtual power, trainer catalogue and the
   profile format and fit. *(done)*
3. Sensor layer: BLE and ANT+ behind one interface, plus a simulated source.
   *(done)*
4. Ride physics and the ride session; recording to FIT in the activity store.
5. World description and the track network: segments, junctions, and both Sokol
   rings built from open data. *(done, except the pit lane and elevation)*
6. The renderer draws the track and moves a rider along it, with the junction
   arrow and its keyboard control.
7. Workout model, Garmin and `training_plan_generator` import, interval engine
   with ERG control for smart trainers.
8. Trainer profile capture mode and the pull-request flow for contributing one.
9. Garmin and Strava upload.
