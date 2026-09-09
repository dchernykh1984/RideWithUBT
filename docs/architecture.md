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

The rule is what makes the renderer thin enough to trust without tests, and it
took a second pass to hold: the window had quietly grown a device manager, a
workout, a recorder and a trainer director - two hundred lines of code that
decided things, sitting in the one module excluded from coverage.

That is now a `Ride` (`app/core/ride.py`): the world, the rider and everything
they brought, with nothing that draws. `RideApp` builds the scene and, once a
frame, asks a ride where the rider is and draws them there. The shape of the
track is worked out in `app/world/mesh.py`, which has no graphics in it either.

The test for the rule is not "does it import Panda3D" but "could this be tested".
Anything in `app/render` that answers no to the second while passing the first is
in the wrong file.

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

Commanding one has two modes and an off. **ERG** holds the workout's target power
whatever the rider spins at, which is what makes an interval an interval.
**Simulation** makes the pedals as heavy as the slope under the rider, which is
what makes a course a course.

The other half of that job is *not* sending commands. A command shares the radio
with the trainer's own readings, and asking it something sixty times a second
floods that: the data stutters and the trainer lags behind the course. So a
command goes out only when the value moved enough for a rider to feel - five
watts, a tenth of a percent - or when it has stood long enough to be worth
repeating in case the trainer missed it.

The scales are where the mistakes hide, and a wrong one does not fail: the
trainer simply holds the wrong number. FE-C sends power in quarter watts and
grade as a percentage shifted by two hundred so a descent stays positive; FTMS
sends whole watts and hundredths of a percent, signed. A target outside what a
trainer could hold is refused rather than allowed to wrap, because wrapping is
the failure that would silently ask for the opposite.

## Devices, and the thread they live on

One manager knows about both radios so nothing above it does: it scans them at
once, opens the devices the rider paired, points their readings at the hub, and
passes trainer commands to whichever connected device can take them. A radio that
is missing is not an error - a rider with no ANT+ stick is still offered what
Bluetooth found.

Both radios are asynchronous and the renderer is a synchronous loop that must not
be blocked for a millisecond, so device work runs on its own thread with its own
event loop. The two meet in exactly two places: readings go into the hub, which
takes a lock, and commands go out without being waited for. Not waiting is the
point - a trainer command that took a hundred milliseconds to acknowledge would
otherwise drop three frames.

Connecting is not waited for either. A scan takes seconds, and a window that will
not draw until the radios have finished looking is a window that looks broken;
devices simply start reporting when they answer.

Pairing stores ids, not devices. At the start of a ride the app looks for what it
knows and connects whatever answers; a device that does not is absent rather than
an error.

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

What gets fitted is the **wheel's** speed against **measured** power, and both
qualifications carry weight. The speed on screen is what the course and the
physics say the rider is doing; the trainer only knows how fast its own roller is
turning, so fitting the ride's speed would produce a curve describing the virtual
world - and it would look entirely plausible. An estimated power came from a
trainer curve, so fitting that would rediscover the curve it came from. Both are
refused rather than quietly used.

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

- **Garmin Connect** - workouts, and the training plan's calendar, pulled
  directly from the rider's own account,
  using their credentials, with nothing in between. Two of Garmin's names do not
  say what they mean and are read rather than trusted: an open step's end
  condition is `lap.button`, and a power target's type is `power.zone` whether
  its values are watts or a zone.
- **`training_plan_generator` JSON** - the format already in use in this
  workspace: `steps` of `warmup`/`interval`/`rest`/`cooldown`/`repeat` with
  power, cadence and heart-rate targets, and duration by time, distance or open.

Both are parsed into one workout model, so the interval engine, the HUD and the
recorder do not care where a session came from.

A **plan** is a calendar, not a workout: dates with workouts on them. The app does
not run the plan - it has no opinion about periodisation and no business having
one - it only knows which workout today's ride is meant to be, so `--today` rides
it without the rider looking it up on their phone first. Garmin has moved the
fields of a scheduled entry around between versions of its own API, so the
reading looks for each in the places it has been, and an entry that gives up
neither a date nor a name is **skipped and named** rather than guessed at: a plan
that half-loads is worse than one that says which days it could not read, because
the rider would ride the wrong thing and never know.

The plan format has one trap worth naming: its `duration_seconds` field holds
metres when the step beside it says `"duration_type": "distance"`, and nothing at
all when it says `"open"`. Read as seconds regardless, a one kilometre effort
becomes a seventeen minute one and nothing looks wrong until the rider is still
going.

The engine watches; it never drives. It is told how much time and distance have
passed and how hard the rider is pushing, and answers which step they are in and
whether they are holding the target. Time that overruns a step carries into the
next one, because throwing it away drifts a workout of thirty-second intervals by
a frame every interval. An open step never ends on its own - that is the whole
point of one - so the rider ends it.

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

The pit lane is not in the extract either, so it is built rather than traced: the
generator offsets the circuit's own points between two of its nodes, which makes
the lane exactly parallel to the track and puts its entry and rejoin on real
nodes - a junction and a merge like any other. Its shape is therefore real and
its position is local knowledge: Sokol's runs along the shorter of the two long
straights, on the left, and the circuit runs clockwise. A test asserts both,
because a refreshed extract with the way drawn the other way round would reverse
the lap and move the lane to the other side of the track without failing
anything else.

Elevation is not in the extract either. It is sampled separately from an open
model and tracked beside the geometry, and it is **smoothed before it is used**:
SRTM rounds to the metre every 30 m while a circuit's points are 10 m apart, so
raw neighbouring differences are mostly rounding - they put a 22% wall on a
circuit that rises and falls six metres in four and a half kilometres.

Gradient is also measured over a fixed length of track rather than between
whichever two described points happen to be adjacent. How far apart those are is
a fact about how the circuit was mapped - three metres in one corner, eight
hundred down a straight - and dividing a height difference by three metres turns
rounding into a wall on its own.

Both corrections earn their place for the same reason: the gradient goes into the
power model and out to the rider's legs through a smart trainer. A fake slope is
not a cosmetic wobble, it is resistance somebody actually pushes against. What
Sokol has left is a 1.2% maximum and about seven metres of climb a lap, which is
worth eleven km/h at 200 W between its shallowest descent and its steepest rise.

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

## The ride

Power in, speed out. Every step, the hub says how hard the rider is pushing, the
track under them says how steep it is, the standard cycling power model says how
fast that makes them go, and the navigator moves them that far.

**Speed is computed, never read from a device.** A trainer reports the speed of
its own flywheel, which is a fact about the trainer and not about the virtual
course: believing it would leave the gradient doing nothing, so a climb would
cost effort and change no number the rider sees.

The model's constants are measured figures rather than ones picked to feel right,
because they decide whether the speed on screen matches the speed the same effort
gives outdoors - and a workout ridden at the wrong effort is worse than no
workout. Eighty kilos on the hoods at 200 W comes out at 33.5 km/h on the flat
and 15.1 km/h on a five percent climb, which is what every power calculator
agrees on, and the tests assert those numbers rather than the model's own
arithmetic.

One deliberate departure from the textbook: at walking pace the propulsive term
P/v claims an acceleration no bicycle can produce, so acceleration is capped at
what a strong rider manages off the line. Down there the limit is torque and
traction, not power.

The air comes from the world as well. Sokol sits about 650 m up, where the air is
five percent thinner than at sea level - worth the better part of a kilometre an
hour at 200 W, which is more than the difference between a good day and a bad
one. A world that does not say how high it is gets sea level.

## Storage

One static tree, chosen per platform, holding everything the app knows:
settings, generated worlds and every recorded ride as a FIT file. No profiles, no
scattered directories, no hidden cache elsewhere - backing up that one directory
backs up everything. `RIDEWITHUBT_HOME` moves it; the tests use that.

FIT is written here rather than by a library: it is what Garmin Connect and
Strava both want for a ride with power in it, nothing in Python writes it well,
and the format is a documented, stable binary layout that is a few hundred lines
to encode. The tests decode what the writer produces with `fitparse`, an
independent implementation - a writer verified against its own reader agrees with
itself and nothing else.

**A recording carries where it happened, and says it was virtual.** A world
records the coordinate its origin sits on, so a position in the world can be
written back out as a real one; the file also carries the virtual-activity mark
that Garmin Connect and Strava read. Both facts are true at once and both are
written: this lap happened at this place, and it happened indoors. That is what
lets a virtual lap sit on the map of the circuit and be compared with the real
ones ridden there - which is the point of modelling a real circuit rather than an
invented one.

A world with no origin - one that is not anywhere - records no positions rather
than made-up ones.

## Credentials

The operating system's own credential store, through `keyring`: the Keychain on
macOS, the Credential Locker on Windows, the Secret Service on Linux. That is the
only place this app puts a password, and settings keep the account name only.

A machine with no credential store gets a clear failure rather than a quiet
fallback to a file. Writing a password into the data directory would be a
surprise, and the sort nobody finds until it has already happened. The
environment can override a lookup, which is how the tests run and how a headless
setup supplies a credential without a keyring at all.

## Uploads

Direct, and only on request. Garmin Connect and Strava are called from the
rider's machine with the rider's own credentials. Nothing is relayed, mirrored or
queued on a server belonging to this project, because there is no such server.

Strava is OAuth, so the rider registers **their own** API application. This app
has no client of its own to hand out, and holding one would put every rider's
rides behind a key that is not theirs. Strava rotates refresh tokens, so each
refresh stores the new one - miss that and the next upload is the last one that
works.

A ride is sent to Strava as a **VirtualRide**. Sent as a plain ride, a lap of a
virtual world would sit among rides done outdoors.

**A ride is marked as sent only when the service says it took it.** An upload log
in the data tree records what went where; recording on failure would quietly lose
a ride, and not recording at all would make two rides on the service out of one
file. The log is keyed by file name and service, deliberately not by anything
inside the file: a re-recorded ride is a new file and should go up again.

## Riding with other people

Over a network, out of scope for now - but the shape it needs exists and is used,
which is the difference between groundwork and a paragraph. A ride holds
companions; a `CompanionSource` says where they are; the renderer draws whoever
is there without asking where they came from.

The source that exists needs no network at all: **pace partners**, riders holding
a steady power round the same circuit on the same physics and the same ground.
They are useful on their own - one to sit in with, one to work at, one to chase -
and they prove the machinery, which a protocol with no implementation would not.

A network source implements the same protocol and nothing above it changes. When
it arrives it will be opt-in per ride, it will carry only position, speed,
cadence and power, and the application will stay exactly as usable with the cable
pulled: with no companions there is simply nobody else on the road.

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

**A frozen application is not the application.** PyInstaller works out what to
include by reading imports, so anything reached lazily - a Bluetooth backend, a
credential store, a service client - can be left out without a word, and the
failure lands on a user's machine the first time they try to upload a ride. So
`--selftest` imports every part a rider reaches only sometimes, and the frozen
binary is the thing CI runs it on. `app/selfcheck.py` holds that list.

The full matrix can also be run on demand (`build.yml`, workflow dispatch),
because a release attaches its assets *after* the release exists: a build that
only fails on Windows would otherwise leave a published release missing a file.

Windows on ARM is not built: Panda3D publishes no wheel for it.

## Roadmap

1. Scaffold: tooling, CI, packaging, localisation, a window that opens. *(done)*
2. Wheel and tyre catalogue, rollout, virtual power, trainer catalogue and the
   profile format and fit. *(done)*
3. Sensor layer: BLE and ANT+ behind one interface, plus a simulated source.
   *(done)*
4. Ride physics and the ride session; recording to FIT in the activity store.
   *(done)*
5. World description and the track network: segments, junctions, both Sokol
   rings and the pit lane, built from open data. *(done, except elevation)*
6. The renderer draws the track and moves a rider along it, with the junction
   arrow and its keyboard control. *(done)*
7. Workout model, Garmin and `training_plan_generator` import, interval engine
   with ERG control for smart trainers. *(model, plan import and engine done;
   Garmin import and ERG still to come)*
8. Trainer profile capture mode and the pull-request flow for contributing one.
9. Garmin and Strava upload.
