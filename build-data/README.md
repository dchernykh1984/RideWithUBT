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
| `elevation.json` | The ground height at every node, sampled from an elevation model. |
| `recipe.json` | Which way is the circuit proper, which are its alternative sections, and the named configurations built from them. |

Rebuild with:

```bash
uv run python scripts/build_world.py sokol
```

That writes `app/data/worlds/<id>.json`. Commit the result: the application reads
the built file and never runs a generator or touches the network.

## The ground

OpenStreetMap has no heights, so they are sampled separately:

```bash
uv run python scripts/fetch_elevation.py sokol
```

That asks the public Open Topo Data service for SRTM's 30 m dataset, paces itself
to the service's rate limit, and writes `elevation.json`.

**The raw sample is not rideable.** SRTM samples every 30 m and rounds to the
metre, while a circuit's points are about 10 m apart, so the difference between
neighbours is mostly rounding - Sokol, which rises and falls six metres in four
and a half kilometres, contains a 22% wall in the raw data. The generator
therefore averages the profile along the track, over a window set by
`elevation_window_m` in the recipe. That window is a property of the elevation
model, not of the terrain: a coarse model needs a wide one, a better model needs
less. Sokol's is 400 m, which brings its steepest gradient to 1.2%.

This matters more than it would on a map. The gradient goes into the power model
and out to the rider's legs through a smart trainer, so a fake slope is
resistance somebody actually pushes against.

## The surfaces

The asphalt and the ground the circuit sits on are generated, not photographed:

```bash
uv run python scripts/make_textures.py
```

A texture taken from somewhere is somebody's, and this project does not use
anybody's work without saying so - the same reason its geometry comes from open
data. Generated also fits better: an image that comes out of a seed is small in
the repository, reproducible from the code that made it, and adjustable by
changing a number rather than by finding another picture.

The results go in `app/data/textures/` and are tracked. A test regenerates them
and compares, so nobody can quietly drop a photograph in.

## Refreshing an extract

```bash
curl -s -X POST -d @build-data/sokol/overpass.ql \
  https://overpass-api.de/api/interpreter -o build-data/sokol/overpass.json
```

OpenStreetMap data is available under the Open Database Licence.

## The pit lane

OpenStreetMap has the racing surface of most circuits and the pit lane beside it
far less often - for Sokol it has the circuit and nothing else. Where a recipe
declares a `pit_lane`, the generator builds one by offsetting the circuit's own
points between two of its nodes, so the lane is exactly parallel to the track and
its entry and rejoin land on real nodes: a junction and a merge like any other.

That makes the lane's shape real and **its position a matter of local knowledge**.
Sokol's runs along the shorter of the circuit's two long straights, on the left,
which is where the maintainer says it is. If a world's lane is somewhere else,
change `entry_node`, `exit_node` and the sign of `offset_m` in its recipe and
rebuild - nothing else has to change.

`offset_m` is metres to the left of the direction of travel, so its sign, not the
circuit's direction, is what puts a lane on one side or the other.

## What the recipe does not have to say

The junctions. A node that more than one of the named ways passes through is a
place where the rider can choose, and the generator finds those itself; the way
named `main_way` supplies the default at each of them. So a recipe only has to
name the ways and say which configurations exist.
