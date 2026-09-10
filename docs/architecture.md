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
workout from Garmin Connect, uploading a finished ride, joining a group ride you
were given the address of - and each goes **directly** from your machine to the
other end. RideWithUBT operates no server that ride data passes through, and
adding one is explicitly out of scope.

That last one is the case to watch, because it is the one that could quietly
stop the sentence above being true. Riding with other people is opt-in per ride
and points at a host the rider named - a laptop on their network, a box a club
runs. See *Riding with other people*, and `docs/protocol.md` for what a relay
does and what it is told.

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

**The application opens on a front screen, not on the track.** Dropping a rider
straight into a lap with a stand-in pedalling was the wrong first thing to see.
What is on it is what changes every session - which circuit, which way round,
which workout, and go. What is behind Settings is what changes once: the
trainer, the sensors, the wheel, the rider's weight. `app/core/startscreen.py`
holds that list, `app/core/rows.py` holds the rows both screens are built from,
and the renderer draws either through the same panel.

**Both answer to the mouse.** A menu that only takes the arrow keys is one
somebody reaches for with a mouse and finds does nothing. Moving the pointer
marks a row, clicking works it, the wheel steps through a list. Which row the
pointer is over is arithmetic - a top, a line height, a count - so it is a
`Layout` in `app/core/rows.py` and not a sum in the renderer.

The settings screen is the same rule applied to a menu, and it is where a rider
now does everything: weight, bicycle, wheel, tyre, trainer, trainer control,
scanning and pairing sensors, the language, and the stand-in rider. None of
that needs a window to be decided, so `app/core/preferences.py` holds a
`SetupMenu` - rows, where each points, what the choices are worth - and the
renderer draws its lines and hands it key presses. It is the same catalogue and
the same settings file the command line writes.

Two things about it are worth saying:

- **Scanning is handed in.** It is the one thing a settings screen does that
  reaches outside the machine, so the menu takes a callable rather than
  importing a radio, and every one of its tests runs on a machine with no
  Bluetooth in the room.
- **Closing the menu applies everything at once.** `Ride.reconsider` takes up
  the new weight, the new bicycle, a newly paired sensor and the stand-in
  rider without restarting: a menu that only takes effect next time is a menu a
  rider does not trust. Turning the stand-in on mid-ride throws away what was
  recorded so far, because a file that is part real and part invented is worse
  than no file.

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

## The rider you can see

A red triangle told a rider where they were and nothing else. A cyclist tells
them something no number does: whether the pedals are turning, and how fast.

The figure is built rather than loaded - a frozen application carries no model
file it could fail to find - out of the two shapes in `app/world/solids.py`, a
box and a tube. `app/core/figure.py` holds the dimensions of a road bicycle and
the pedal stroke: the pedals go round a circle the size of the cranks, and each
leg finds its knee by the same two-bone geometry a real one uses, bending
forwards because the other solution to those two circles is a leg bending the
wrong way. The renderer places what that produces and decides nothing, so a
pedal stroke is checked without a window.

The cranks turn at whatever a cadence sensor reports, and at a plain average
when nothing is measuring: a figure sitting frozen on a moving bicycle looks
broken, and that is the state most riders will see first. Below five revolutions
a minute the legs stop, because a sensor reports small numbers as a wheel coasts
to a halt.

**A rider sits differently on each bicycle**, and the figure does too:
`POSTURES` puts the shoulders and the hands where that position puts them, from
sitting up to a time trial bicycle with the forearms on extensions. Drawing
them all the same would say the choice does not matter, when it is worth six
kilometres an hour - and the speed on screen already says otherwise. It is the
same person on all of them, so the torso is the same length and the saddle the
same height above the pedals; what moves is everything else.

**Everything a person is made of is round.** A cyclist built from boxes reads
as a stack of boxes, which is what the first one was: limbs are tubes, the head
is a ball, the body is a tube flattened into an oval, and the wheels have deep
rims that can actually be seen - a four-centimetre tyre is a hairline at any
distance, and a bicycle whose wheels have vanished is a person floating. A time
trial bicycle gets a rear disc, which is the most recognisable shape in cycling
and says from across the circuit what somebody is riding.

The other half of reading as a person is width. From behind - the view from the
saddle, and the one that was unreadable - a rider is shoulders, a back and two
legs, and the first figure had shoulders as wide as its hips and its legs
almost touching. `SHOULDER_WIDTH_M`, `HIP_WIDTH_M` and `FOOT_SPACING_M` are why
it now reads as a person rather than a column of blocks.

Two things this cost, both worth having:

- **Meshes can carry their own normals now.** The track and the ground are lit
  as if facing straight up and look right; a person made of boxes lit that way
  is a flat cut-out, because every face takes the same light.
- **Everything is measured from the bottom bracket**, which is what puts the
  bicycle on the tarmac rather than through it - without it the pedals swing
  seventeen centimetres below the road at the bottom of every stroke.

## The sign at a junction

The overhead arrow was there from the start and could not be seen. Three things
were wrong with it and each was invisible until somebody took a picture:

- It was placed a fixed hundred metres in front of the rider's nose. On a bend
  that is out in the grass. It stands at the junction now, which is where a
  sign about a junction belongs.
- It lay flat at the height of the camera, so from the saddle it was a line a
  few pixels tall. It stands upright facing back down the road, like a sign
  over a road.
- It was a single triangle, and tipping it towards the rider showed its back,
  which is not drawn at all. A sign has no back.

The arrow also leans by a fixed amount rather than by the true angle between
the roads, and the head-up display says "left" or "right" by the exit's place
in the order rather than by its bearing. The exits at this circuit part company
by six or seven degrees: drawn honestly, the sign points straight up whichever
way the rider is about to go, and the words say "straight on" for both. Which
of the two roads they are taking is the thing they need to know, so that is
what is shown - a symbol, not a survey.

## The rider, and what they are riding

Two numbers decide what a given effort is worth, and neither can be guessed.
Weight decides every climb and every acceleration. Drag decides everything on
the flat, which on this circuit is nearly all of it: at 250 W, sitting up gives
34.5 km/h and a time trial bicycle gives 41.0.

So `physics.BIKES` is a small catalogue - sitting up, on the hoods, in the
drops, a road bicycle with clip-on bars, a proper time trial bicycle - and the
rider picks one, says what they and their bicycle weigh, and may override the
drag figure with one they measured, the same way a measured wheel rollout beats
the catalogue's.

**One of those figures is measured rather than quoted.** A real ride at this
circuit - 8.9 km in 866 s at 266 W average, a rider of 83 kg on a road bicycle
with clip-on time trial bars, in air at 645 m and 27 degrees - solves for a CdA
of 0.267 m2 over its whole energy budget. That recording is kept in
`build-data/calibration/`, stripped of everything the question does not need:
no coordinates, no heart rate, no date, because a rider's whereabouts are not a
test fixture.

`tests/test_calibration.py` replays it. Given the watts that were really
pushed, the model rides 8.96 km where the bicycle rode 8.92 - four tenths of a
percent over a quarter of an hour. Every other physics test checks arithmetic
against published arithmetic; this is the one that checks it against the road,
and the one that would notice the model drifting away from it.

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

The textures are generated too, by `scripts/make_textures.py`: value noise for
the grain of asphalt, a white line at each edge of the track, a coarser green for
the ground. A texture taken from somewhere is somebody's, and the same reasoning
that puts the geometry in open data keeps photographs out of the repository.

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

**The road is rebuilt as a curve, not joined up with straight lines.** A survey
records a corner as a point every thirteen metres or so, and a rider going
round the chords between them has their heading snap by up to twenty-six
degrees at a time - which is what riding it looked like. `app/world/smooth.py`
puts a centripetal Catmull-Rom spline through the surveyed points and samples
it every four metres, then eases the result towards itself a few times. The
spline alone is not enough: it turns smoothly but changes *how sharply* it
turns in one step at every surveyed point, because a coarse survey does not sit
on a smooth curve, and a rider feels that step as a flick of the bars. Easing
takes the step from sixteen degrees to under two and moves the road by at most
1.3 m, at the sharpest hairpin only - a tenth of the width of the track, and
closer to the asphalt than the survey was.

The heading is blended between one edge and the next rather than read off
whichever edge the rider is on. A road is a list of straight pieces however
finely it is drawn, and reading the heading off the current piece makes the
view sit still and then snap at every join.

**A ride begins where a session does: halfway down the pit lane.** That is a
different thing from where a lap is measured from, and the two are kept apart -
`TrackNetwork.start` places the rider, `Route.start_segment` measures the lap.
Conflating them would either stand the rider on the track when they should be
rolling out of a box, or count the pit lane as part of a circuit that does not
include it. The recipe says it the way a person would ("on the pit lane,
halfway") and the build turns that into a segment and a distance, because the
length of the lane is something the build works out.

**The pit lane is built from its width, not only from its offset.** A lane
tapered by moving its centre line alone runs *across* the racing surface for as
long as the two overlap - painting its own edge lines over the road a rider is
on - and leaves a wedge of grass where the two part company. Both were on
screen. Its width now eases from nothing at each end, so where it merges there
is no lane to paint; its centre still reaches the node it is joined to, because
a rider coming off it onto the circuit must not step sideways to do so.

Textures are mipmapped and filtered anisotropically. Without that a road at two
hundred metres is a shimmer of dashes where its edge line should be and a
grandstand is a moire of stripes: the whole circuit crawled, which is what
sampling a surface once per pixel looks like when you are looking along it.

The pit lane is not in the extract either, so it is built rather than traced: the
generator offsets the circuit's own points between two of its nodes, which makes
the lane exactly parallel to the track and puts its entry and rejoin on real
nodes - a junction and a merge like any other. The offset eases in and out over
sixty metres, so the lane leaves the track and rejoins it the way a real one
does; at a constant offset it ran alongside at full width and then stopped in
the grass. That taper needs points to happen at, and open data gives a straight
between two nodes as exactly two of them, so the line is resampled first. Its shape is therefore real and
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

**What stands beside the track is modelled too, and it is real.**
OpenStreetMap has the footprints of the buildings at this circuit, surveyed in
the same trace as the track: the pit garages, the grandstand, the race hotel.
They stand where they really stand and are the shape they really are, which is
the entire reason for using survey data rather than inventing scenery. What
open data does not have is how tall they are, so heights come from the recipe
by kind - a grandstand is not a garage - and are stated rather than guessed at
per building.

Photographs were the obvious alternative and are the wrong tool: they give
texture and nothing else - not position, not shape, not scale - and they are
somebody's to license. Footprints plus stated heights give a rider what they
actually need from scenery, which is knowing where they are on the lap. Every
corner looked like every other corner without them.

The buildings live in the world file, not in the renderer: there will be other
maps, and everything about a map belongs in the map.

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

## A ride nobody pedalled

The application used to ride along by itself. With no sensors connected a
stand-in rider pushed a steady 200 W, the world went past, and the session was
written to the activity store like any other - from where it would have gone to
Garmin or Strava and sat next to the real ones. That is not a fallback, it is a
fabricated training record.

A stand-in now has to be asked for by name and given a number
(`--simulate 240`), the screen says so while it is happening, and such a ride
is never recorded whatever else was asked for - `RideSetup.records` is a
separate question from `RideSetup.record` for exactly this reason. With nothing
connected and nothing asked for, the rider does not move, and the screen says
why.

It stays because it is genuinely useful: looking at a world, taking a picture
of it, testing a change without a trainer in the room.

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

A ride holds companions; a `CompanionSource` says where they are; the renderer
draws whoever is there without asking where they came from. There are two kinds
of source and the code above them cannot tell which it is holding.

**Pace partners** need no network at all: riders holding a steady power round the
same circuit, on the same physics and the same ground. One to sit in with, one to
work at, one to chase.

**A room** is real people. `NetworkCompany` (`app/services/company.py`) sends one
datagram five times a second to an address the rider typed and draws whoever
answers. `app/services/room.py` is the relay that copies those datagrams between
riders - about a hundred lines, run by whoever is organising the ride. Both
compose through `Peloton`, because a club ride with a partner to chase is two
sources and one road.

**There is no RideWithUBT server, and adding one would be a change to what this
application is.** A room is a host the rider named. Nothing about the ride
travels through anything belonging to this project, which is the same promise the
upload path makes, kept the same way.

The split follows the offline rule: the *format* is `app/core/presence.py`, pure
and exhaustively tested - including every way a stranger's datagram can be
malformed, which is the part that matters, because all of it arrives from
machines this application has never met. The *socket* is in `app/services`,
where `tests/test_offline.py` names it and says why.

What goes on the wire is position, heading, speed, distance, cadence, power and
a name the rider chose. Not a heart rate, not a workout, not an account. A rider
who never joins a room never even has an id. `docs/protocol.md` is the whole
contract, written so somebody else can implement a relay without reading this
code.

## The icon

The team's logo, at eight sizes, in the three shapes each platform wants:
`.icns` for macOS, `.ico` for Windows, and a plain PNG the running window is
given so the icon in the dock is the same picture as the one on the file a
rider double-clicked.

They are generated rather than hand-made. The logo is committed once under
`build-data/branding/`, `scripts/make_icons.py` derives the rest, and a test
fails if what is in the tree no longer matches - which is what stops an old
logo living on in the dock after a new one lands on the desktop. That is the
same rule the worlds follow: keep the source, generate the artefacts.

Both container formats accept PNGs inside them and are simple enough to write
directly (`app/icons.py`), so there is no image library in the dependency list
for this. `app/imaging.py` reads the logo back in and averages pixels down to
each size - a box average rather than nearest-neighbour, because the logo is a
line drawing and picking one pixel in thirty loses the thin parts of it.

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

**Being packaged is not the same as being reachable**, which cost a release.
Panda3D finds its display modules - the code that opens a window - through a
`plugin-path` defaulting to `<auto>`: deduce it from where my own libraries
are. In a frozen bundle that deduction fails, and so does the matching one for
the `.prc` files that say to open a window in the first place. The library was
in the build, loadable, and never looked at. Every test passed, the self-test
passed on the frozen binary on all four platforms, and the application died a
second after being double-clicked - with no traceback anywhere a user would
see it, because a double-clicked app has nowhere to print one.

`app/frozen.py` finds those files by looking rather than deducing, and
`--selftest` now asks Panda3D what it can actually draw with and fails the
build when the answer is nothing. That check is the point: a self-test that
runs with no window can never need a display module, so it could pass forever
while the application would not start.

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
   rings and the pit lane, built from open data. *(done)*
6. The renderer draws the track and moves a rider along it, with the junction
   arrow and its keyboard control. *(done)*
7. Workout model, Garmin and `training_plan_generator` import, interval engine
   with ERG control for smart trainers. *(done)*
8. Trainer profile capture mode and the pull-request flow for contributing one.
   *(done)*
9. Garmin and Strava upload. *(done)*
10. Riding with other people: the presence format, a relay anyone can run, and
    the client that joins one. *(done)*
