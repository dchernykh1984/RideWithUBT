# Working in RideWithUBT

A Python 3.14 desktop application: an offline-first virtual world for indoor cycling
training. The renderer is Panda3D; the entry point is `app/cli.py` (console script
`ridewithubt`). Read `docs/architecture.md` before changing structure - it records why
the pieces are split the way they are.

## Conventions

- Python 3.14, everything through uv: `uv run pytest`, `uv run ruff check .`,
  `uv run mypy app tests`.
- Never commit to `main`. Branch off `origin/main`, one logical change per commit.
- Commit messages: one-line Conventional Commits, no body, no `Co-Authored-By` trailer
  and no co-author line. `cz check --rev-range origin/main..HEAD` runs on every PR, and
  release-please builds `CHANGELOG.md` from these subjects, so the type matters (`fix`
  and `feat` are released; `chore`/`docs`/`test`/`style`/`refactor` are not).
- ASCII only in tracked files (`uv.lock`, `CHANGELOG.md` and `app/locale/*.po` are
  exempt - translations cannot be ASCII). A pre-commit hook and the `.claude` PostToolUse
  guard both enforce it. Chat in any language; code stays ASCII.
- Before committing run the full gate: `uv run pytest` (coverage gate 90%),
  `uv run ruff check .`, `uv run ruff format --check .`, `uv run mypy app tests`.
  `uv run` may rewrite `uv.lock`; keep it out of feature commits with
  `git checkout uv.lock` unless the lock itself is the change.

## The one rule about layout

Only `app/render/` may import Panda3D or touch the window. The simulation, the sensors,
the workout engine and the world model must run headless, because that is what makes
them testable and what would let a second frontend exist later. A `from panda3d...`
import anywhere else is a bug.

## What the tests do not cover

`app/render/*` is excluded from coverage (`pyproject.toml`, `[tool.coverage.run]`):
a `ShowBase` is process-global and does not survive pytest-xdist workers. The renderer is
covered instead by `ridewithubt --selftest`, which boots the engine with no window and
renders a few frames - CI runs it against the *frozen* app, so a packaging mistake fails
the build rather than a user's first launch.

## Where data lives

`app/data/` is inside the package, so it ships in the frozen app: catalogues,
textures, world descriptions. Anything only a generator needs - a raw
OpenStreetMap extract, say - belongs in `build-data/` at the root instead, tracked
but not shipped. Adding a trainer or a wheel size is a data change; see
`docs/trainers.md`.

## Skills

- `shipping-a-change` - branch, commit, open the PR, watch CI to green.
- `review-cycle` - review a branch or PR and land the fixes.
