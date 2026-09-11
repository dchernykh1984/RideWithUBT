---
name: shipping-a-change
description: Branch, commit, open a pull request, and drive CI to green in this repo. Use whenever you are about to commit, push, open a PR, or check CI status.
---

# Shipping a change

## Branch

- Never commit to `main`. `git fetch origin && git switch -c <type>/<slug> origin/main`.
- The working tree may hold the maintainer's local data or untracked files. Stage only
  files you changed (`git add <path>`), never `git add -A`.

## Commit

- One line, Conventional Commits: `git commit -m "type(scope): summary"`. No body and no
  `Co-Authored-By` trailer. `cz check --rev-range origin/main..HEAD` runs in CI, and
  release-please builds CHANGELOG from these subjects, so the type matters (`feat`/`fix`
  are released; `chore`/`docs`/`test`/`style`/`refactor` are not).

## Look at what you did

**A green pipeline is not a change that works.** Run the application and look
at the result of anything a rider can see:

```
uv run python scripts/look.py            # every scene, into build-data/looks/
uv run python scripts/look.py start rider
```

Then open the pictures. Nothing in there asserts anything - a scene that
renders is not a scene that looks right, and reading the file names is not
looking.

Every one of these shipped past a full green pipeline and was found by opening
a picture:

- a rider drawn as a stack of horizontal slabs (limbs turned about their own
  length, which for a square cross-section is no rotation at all)
- wheels that were hairlines, then wheels whose spokes lay flat on the road
- a junction sign that could not be seen: placed a fixed distance in front of
  the rider's nose, lying edge-on at camera height, and one-sided so its back
  was not drawn
- a settings panel whose background was sized by padding with spaces, in a
  font that is not monospaced
- the pit lane painting its own edge lines across the racing surface
- a whole circuit shimmering into dashes for want of mipmaps
- Russian and Kazakh drawn as rows of empty boxes, and then - with a font that
  could draw them - every label still in English
- a language chosen in the settings, written to the file, and every label on
  the screen still English until the next launch
- a settings screen with no way off it but a key named in a footer

What to look for, by what you touched:

| Touched | Look at | For |
| --- | --- | --- |
| the rider or the bicycle | `rider`, `rider-tt` | limbs joined, wheels round, the position right for the bicycle |
| a panel, a row, a field | `start`, `settings`, `list`, `typing`, `trainers` | columns lined up, the card fitting its text, the box opaque and on top, a long list showing where in itself it is |
| any user-visible string | `start-ru`, `start-kk`, `settings-ru` | letters that draw, and nothing left in English |
| anything about the language | `language` | the screen it comes back to speaks what was just chosen |
| the world, the mesh, a texture | `pits`, `pit-exit`, `corner`, `straight`, `junction` | no seams, no markings across the road, nothing shimmering in the distance |

If a change is only arithmetic, say so and skip it. If it is anything a rider
sees, look.

## Keep the context in step

**A change to what the application does is not finished until the writing about it
matches.** In the same pull request, not a later one:

- `docs/architecture.md` when the change alters how a piece works or why - including
  the roadmap, which has gone stale before.
- `README.md` when it adds or renames a flag, or changes what a rider sees.
  `tests/test_documented.py` enforces flag parity, not prose accuracy.
- `CLAUDE.md` and `.claude/skills/*` when a convention, a command or a layout rule
  changes. These are what the next session reads instead of the codebase.
- Tests. A behaviour with no test is a behaviour the next change will break silently,
  and the coverage gate does not notice a *missing* case - only an unexecuted line.
- `scripts/look.py`, when a change adds something worth looking at: a scene
  nobody thought to add is a thing nobody will notice breaking.

If you find writing that has drifted out of step with the code, fix it while you are
there rather than leaving it. Stale guidance is worse than none: it is believed.

## Before pushing

- `uv run pytest` (coverage gate 90%), `uv run ruff check .`,
  `uv run ruff format --check .`, `uv run mypy app tests scripts`. pre-commit runs the
  same set on commit.
- Every tracked file must be ASCII (the `no-non-ascii` hook covers markdown too);
  `app/locale/*.po` is the one exception, since translations are not ASCII. `uv run`
  may rewrite `uv.lock`; keep it out of feature commits with `git checkout uv.lock` unless
  the lock itself is the change.

## Pull request

- `git push -u origin <branch>` then `gh pr create --base main --title "..." --body "..."`.
- PR body is real content only: no "Generated with Claude Code" line and no co-author
  footer.

## Watch CI to green

- Poll the authoritative rollup, not `gh pr checks` (its per-check status lags and can
  show `pending` after a job has finished):

  ```
  gh pr view <n> --json statusCheckRollup \
    --jq '[.statusCheckRollup[] | {name:(.name//.context), s:(.conclusion//.state)}]'
  ```

- Every check must be SUCCESS before requesting review.

## Generated files that must be regenerated, not edited

Several tracked files are derived from tracked inputs, and a test fails when they fall
out of step. Change the input, then run the generator:

| Generated | From | Command |
| --- | --- | --- |
| `app/data/worlds/*.json` | `build-data/<world>/` | `uv run python scripts/build_world.py <world>` |
| `app/data/textures/*.png` | `app/world/texture.py` | `uv run python scripts/make_textures.py` |
| `app/app.icns`, `app/app.ico`, `app/data/branding/icon.png` | `build-data/branding/ubt-logo.png` | `uv run python scripts/make_icons.py` |

Two more things are data rather than code and are edited directly, not
generated: `app/data/figure.json` (every measurement of the rider and the
bicycle) and `app/data/*.json` catalogues.

## Anything a rider reads

A user-visible string goes through `translate()` and into all three of
`app/locale/{en,ru,kk}.po` - English included, or the lookup misses. The names
of real things (a circuit, a route, a trainer) stay as they are: they are what
those things are called, not words to translate.

## Releases

release-please opens a release pull request as soon as a `feat` or `fix` lands on
`main`. **Merging your change is not the end of the job**: merge the release PR too,
then watch the release build until all four assets are attached
(`gh release view v<x.y.z> --json assets`). A release is not out until it has
linux-x86_64, linux-aarch64, macos-arm64 and windows-x64 on it - a build has broken on
one platform only before, leaving a published release short of a file.
