# Adding a trainer

The trainer catalogue is data, not code. One JSON file per trainer in
`app/data/trainers/`, named after its id, so adding one is a single-file pull
request that cannot conflict with anyone else's.

```json
{
  "id": "wahoo-kickr-core",
  "brand": "Wahoo",
  "model": "KICKR CORE",
  "kind": "direct_drive",
  "resistance": "electromagnetic",
  "protocols": ["ftms", "fec"],
  "profile": null,
  "notes": ""
}
```

| Field | Meaning |
| --- | --- |
| `id` | Stable slug. Must equal the file name; settings store it. |
| `brand`, `model` | Shown to the rider, as written on the trainer. |
| `kind` | `direct_drive`, `wheel_on` or `roller`. |
| `resistance` | `fluid`, `air`, `magnetic`, `electromagnetic` or `motor_brake`. |
| `protocols` | `ftms` and/or `fec`; empty for a trainer with no electronics. |
| `profile` | A measured power curve, or `null`. |
| `notes` | Anything a rider needs to know. Optional. |

`resistance` is what decides how an uncalibrated trainer is estimated: fluid and
air units absorb power with the cube of wheel speed, magnetic units closer to the
square. `electromagnetic` and `motor_brake` are the units that measure their own
power, and those are never estimated - the device is believed.

The protocol list is a hint for the setup screen, not a promise. What a trainer
actually speaks is discovered when it connects, and the device wins where the two
disagree.

## Adding a measured profile

A profile is the one part that cannot be filled in from a specification sheet.
It is recorded, on a real trainer, against a real power meter:

1. Fit a power meter, choose your trainer and wheel in the settings, and turn on
   **record trainer data**.
2. Ride the whole usable speed range, from a slow warm-up to a hard effort, at
   one fixed resistance setting. Changing the lever half way through measures two
   trainers and fits neither.
3. The app fits `power = coefficient * speed ** exponent` to the samples and
   reports how well it fits. Under 25 W RMS it offers the result for
   contribution; above that it asks you to ride again.
4. It writes the trainer's file with the profile filled in. Open a pull request
   with that one file.

```json
"profile": {
  "coefficient": 0.3461,
  "exponent": 2.98,
  "offset_w": 0.0,
  "samples": 420,
  "rms_error_w": 4.2,
  "speed_range_kmh": [12.0, 45.0],
  "recorded_at": "2026-09-08",
  "wheel": "700c x 25 (2111 mm)",
  "tyre_pressure_bar": 6.5,
  "resistance_setting": "level 3",
  "contributor": "your name or handle"
}
```

The provenance fields are not paperwork. The same trainer on a different tyre, a
different pressure or a different resistance level is a different curve, so a
profile that does not say which of those it was recorded under cannot be reused
by anyone else. A profile whose conditions are missing will not be merged.

A trainer with manual resistance levels needs one entry per level people actually
use - give each its own `id` (`elite-novo-force-level-3`) and say so in `notes`.
