# Riding together

RideWithUBT rides alone by default and works with the network cable pulled. When
you do want company, it is company you arranged: you name a host, and that host
copies datagrams between the people who named it. This project runs no such
host, has no account system, and is not on the path between you and anyone else.

## Getting a group ride going

One person runs the room. Any machine reachable by the others will do - a laptop
on the club's wifi, a spare box, a small VPS someone already pays for:

```bash
ridewithubt --host-room            # port 51820
ridewithubt --host-room 9000       # or one you choose
```

Everyone else joins it, and gives themselves a name to be known by:

```bash
ridewithubt --name Askar --ride-with 192.168.1.20
ridewithubt --name Dana  --ride-with clubhouse.local:9000
```

That is the whole setup. The name is saved, so it is said once. Riders on
different worlds do not see each other even in the same room, so a room can be
left running.

Pace partners still work alongside it: `--partners 220 --ride-with ...` puts a
steady rider on the road next to the real ones.

## What is sent

One UDP datagram per rider, five times a second, holding one JSON object:

```json
{
  "v": 1,
  "id": "9f2a1c4e7b8d0a35",
  "name": "Askar",
  "world": "sokol",
  "x": 120.5,
  "y": -33.25,
  "z": 645.0,
  "heading": 1.5,
  "distance": 4400.0,
  "speed": 11.1,
  "cadence": 90.0,
  "power": 240.0
}
```

| Field | Meaning |
| --- | --- |
| `v` | Protocol version. A client ignores what it does not recognise. |
| `id` | Random hex, made up on the rider's machine. Not derived from anything. |
| `name` | What other riders see. Whatever they typed, up to 24 characters. |
| `world` | Which world they are riding. Riders in different worlds never meet. |
| `x`, `y`, `z` | Where they are, in world metres. |
| `heading` | Which way they are pointing, radians. |
| `distance` | How far into the ride, metres. |
| `speed` | Metres per second. |
| `cadence`, `power` | Omitted entirely when there is no sensor for them. |

That is the whole of it. No heart rate, no workout, no weight, no FTP, no
account, no e-mail address, no machine identifier, no ride history. A rider who
never joins a room never even has an `id`: it is generated on the way into one.

## What a relay does

Receive a datagram; if it decodes as a rider, remember the sender's address and
copy the datagram to every other address in the room riding the same world.
Forget a rider five seconds after they go quiet. Keep nothing on disk.

`app/services/room.py` is one such relay in about a hundred lines. Anyone can
write another in any language - the format above is the whole contract.

### If you put one on the public internet

Don't, unless you mean it. A relay forwards to whoever has recently spoken, so a
forged source address could point other riders' datagrams at a third party. The
room is capped at 64 riders, which bounds that, and it is a non-issue on a home
or club network or across a VPN. It has not been hardened for anything else, and
saying so plainly is better than implying otherwise.

## What is deliberately not here

- **No server of ours.** Not for presence, not for accounts, not for uploads:
  rides go straight from your machine to Garmin or Strava.
- **No account, and no login to ride with people.** A room is an address.
- **No fallback to a hosted room.** If the relay you named is unreachable, you
  ride alone and the application says so. It does not go looking elsewhere.
