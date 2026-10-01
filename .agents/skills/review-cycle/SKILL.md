---
name: review-cycle
description: Review a branch or PR for correctness and cleanup, then land the fixes. Use when asked to review the current diff or a PR before it merges.
---

# Review cycle

- Review the actual diff against `origin/main`, not the whole tree.
- Prefer real correctness bugs; report cleanup only when it clearly earns its place. Do
  not invent findings to hit a count.
- Apply the valid fixes on the branch, re-run the local gate (`uv run pytest`,
  `uv run ruff check .`, `uv run mypy app tests scripts`), and push.
- Keep each fix a one-line Conventional Commit with no attribution or co-author line.
- Then drive CI back to green (see the shipping-a-change skill) before handing back.

## What has actually gone wrong here before

Worth checking on any diff that touches these, because each of them shipped:

- **A test that cannot fail.** A parameter the body never uses; an assertion that
  restates the code. Try deliberately breaking the behaviour and confirm the test
  notices.
- **A patch script that matched nothing.** Editing files with `str.replace` and no
  `assert old in t` silently does nothing, and the gate then passes on unchanged code.
- **A number pinned to a default.** `Bike()` moved and three physics tests started
  measuring something else. State the fixture explicitly when the point is a figure.
- **Geometry checked on the wrong quantity.** How hard a road turns is not the same as
  how suddenly it changes; a hairpin is not a jerk.
- **Writing left behind.** A roadmap item still marked "to come" after it shipped, a
  README flag that no longer exists, an architecture note describing the old shape.
