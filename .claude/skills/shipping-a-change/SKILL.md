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

## Releases

release-please opens a release pull request as soon as a `feat` or `fix` lands on
`main`. **Merging your change is not the end of the job**: merge the release PR too,
then watch the release build until all four assets are attached
(`gh release view v<x.y.z> --json assets`). A release is not out until it has
linux-x86_64, linux-aarch64, macos-arm64 and windows-x64 on it - a build has broken on
one platform only before, leaving a published release short of a file.
