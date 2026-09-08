# Build inputs

What the world generators read. Tracked so a build is reproducible and a change
to a circuit's geometry shows up in a diff - but **not shipped**: none of this is
in the `app` package, so it does not travel into the frozen application. What
ships is what the generators write, under `app/data/`.

## Adding or rebuilding a world

Each world is a directory holding three files:

| File | What it is |
| --- | --- |
| `overpass.ql` | The Overpass query that produced the extract. Keep it, so the extract can be refreshed. |
| `overpass.json` | The extract itself: the raceway ways of one circuit, with geometry. |
| `recipe.json` | Which way is the circuit proper, which are its alternative sections, and the named configurations built from them. |

Rebuild with:

```bash
uv run python scripts/build_world.py sokol
```

That writes `app/data/worlds/<id>.json`. Commit the result: the application reads
the built file and never runs a generator or touches the network.

## Refreshing an extract

```bash
curl -s -X POST -d @build-data/sokol/overpass.ql \
  https://overpass-api.de/api/interpreter -o build-data/sokol/overpass.json
```

OpenStreetMap data is available under the Open Database Licence.

## What the recipe does not have to say

The junctions. A node that more than one of the named ways passes through is a
place where the rider can choose, and the generator finds those itself; the way
named `main_way` supplies the default at each of them. So a recipe only has to
name the ways and say which configurations exist.
