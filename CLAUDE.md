# Working in RideWithUBT

A Python 3.14 desktop application: an offline-first virtual world for indoor cycling
training. The renderer is Panda3D; the entry point is `app/cli.py` (console script
`ridewithubt`). Read `docs/architecture.md` before changing structure - it records why
the pieces are split the way they are.

## Conventions

- Python 3.14, everything through uv: `uv run pytest`, `uv run ruff check .`,
  `uv run mypy app tests scripts`.
- Never commit to `main`. Branch off `origin/main`, one logical change per commit.
- Commit messages: one-line Conventional Commits, no body, no `Co-Authored-By` trailer
  and no co-author line. `cz check --rev-range origin/main..HEAD` runs on every PR, and
  release-please builds `CHANGELOG.md` from these subjects, so the type matters (`fix`
  and `feat` are released; `chore`/`docs`/`test`/`style`/`refactor` are not).
- ASCII only in tracked files (`uv.lock`, `CHANGELOG.md` and `app/locale/*.po` are
  exempt - translations cannot be ASCII). A pre-commit hook and the `.claude` PostToolUse
  guard both enforce it. Chat in any language; code stays ASCII.
- Before committing run the full gate: `uv run pytest` (coverage gate 90%),
  `uv run ruff check .`, `uv run ruff format --check .`, `uv run mypy app tests scripts`.
  `uv run` may rewrite `uv.lock`; keep it out of feature commits with
  `git checkout uv.lock` unless the lock itself is the change.
- **Update the writing in the same change.** `docs/architecture.md`, `README.md`,
  this file and `.claude/skills/*` are part of the deliverable, not follow-up work -
  and so are the tests. If you find writing that has drifted, fix it while you are
  there. See the `shipping-a-change` skill.

## The two rules about layout

**Only `app/render/` may import Panda3D or touch the window.** The simulation, the
sensors, the workout engine and the world model must run headless, because that is what
makes them testable and what would let a second frontend exist later. A
`from panda3d...` import anywhere else is a bug (`tests/test_layout.py`).

**Only `app/services/` may reach a network.** Everything else must work with the cable
pulled. `tests/test_offline.py` names each module there and what it may reach, with the
reason; a new one that opens a socket fails until it is listed. Bluetooth and ANT+ are
not networks - they talk to what is in the room.

The renderer decides nothing. Anything in `app/render/` that could be tested but is not
is in the wrong file: that is how the settings menu ended up in `app/core/preferences.py`
and the ride loop in `app/core/ride.py`.

## What the tests do not cover

`app/render/*` is excluded from coverage (`pyproject.toml`, `[tool.coverage.run]`):
a `ShowBase` is process-global and does not survive pytest-xdist workers. The renderer is
covered instead by `ridewithubt --selftest`, which boots the engine with no window and
renders a few frames - CI runs it against the *frozen* app, so a packaging mistake fails
the build rather than a user's first launch.

## Where data lives

`app/data/` is inside the package, so it ships in the frozen app: catalogues, textures,
world descriptions, the icon. Anything only a generator needs - a raw OpenStreetMap
extract, the logo, a reference ride - belongs in `build-data/` at the root instead,
tracked but not shipped. Adding a trainer or a wheel size is a data change; see
`docs/trainers.md`.

The rider is data too: `app/data/figure.json` holds every measurement of the
figure and the bicycle it sits on. No number about how the rider looks belongs
in Python.

**Every word a rider reads goes through `translate`, and into all three
catalogues.** This application says it speaks Russian, Kazakh and English; a
screen labelled in English speaks one. The names of real things - a circuit, a
route, a trainer - are not translated, because they are what those things are
called. `app/data/fonts/DejaVuSans.ttf` ships because Panda3D's own font has no
Cyrillic and two of the three languages came out as empty boxes.

**Everything about a map lives in the map.** A world file carries its segments,
junctions, routes, origin, start position and buildings. There will be other maps, and
nothing about one should have to be found somewhere else.

Several tracked files are generated from those inputs and a test fails when they drift -
the worlds, the textures, the icons. Change the input and rerun the generator; the
`shipping-a-change` skill lists which command builds what.

## Things that look fine and are not

Learned the hard way; each cost a release or a wrong answer.

- **A packaged application is not the application.** `--selftest` runs on the *frozen*
  binary in CI and checks that lazily-reached modules imported and that Panda3D can
  actually find a display module. A build that imports cleanly can still fail to open a
  window - see `app/frozen.py`.
- **A ride nobody pedalled is not a ride.** Simulated riding must be asked for by name
  with a power, and is never recorded. `RideSetup.records` is deliberately a different
  question from `RideSetup.record`.
- **Uploads and rooms go straight from the rider's machine to the other end.** This
  project runs no server, and adding one changes what the application is.
- **There is no keyboard, mouse or font without a window.** `--screenshot` and
  `--selftest` run offscreen, where `mouseWatcherNode` and `buttonThrowers` are
  empty and a font need not load. Each of those has crashed a build once.
- **A menu is worked with a mouse.** Clicking a number opens it for typing;
  clicking a list opens the list. Stepping a weight to 83 kg with an arrow key
  is eighty-three key presses, and a row that cycles through forty trainers is
  one nobody reaches the end of.

## Skills

- `shipping-a-change` - branch, commit, open the PR, watch CI to green, cut the release,
  and keep the writing in step.
- `review-cycle` - review a branch or PR and land the fixes.
