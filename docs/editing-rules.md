# Editing the rules

All the game knowledge is one file: `data/areas.toml`. One table per area,
keyed by the exact name D2R shows in the top-right corner.

```toml
[area."Jail Level 1"]
act = 1
next = "Jail Level 2"
has_waypoint = true
to_waypoint = { dir = "left", tip = "Turn left from the entrance to reach the waypoint." }
to_next = { dir = "left", tip = "From the waypoint, turn left for the stairs down (they are straight ahead from the entrance)." }
confidence = "high"
source = "maxroll, cheatsheet"
levels = [10, 41, 71]          # alvl on Normal, Nightmare, Hell
quests = []                    # quest objectives located here
uniques = []                   # superuniques that spawn here
notes = []                     # anything else worth a line
farm = []                      # farm-run routes: how to reach Countess/Pit/... fast
immune = ["cold", "fire"]      # Hell immunities possible here (omit the key = unknown)
```

| Field | Meaning |
|---|---|
| `to_waypoint` | from the **entrance** to the waypoint |
| `to_next` | from the **waypoint** (or the entrance if `has_waypoint = false`) to the exit |
| `dir` | `left straight right back` (character-relative) · `corner edge opposite near inside path` (outdoor shape rules) · `fixed` (static layout) · `random` (**no accepted rule** — say so in the tip) · `none` |
| `confidence` | `high` = both sources agree · `medium` = one source · `low` = inferred |
| `ocr_name` | only when the on-screen name differs from the key (Act 2 and Act 3 both show "Sewers Level 1") |

Tips are full sentences and wrap in the overlay, so length is not a concern.

The file is validated on startup: an unknown `dir`, a `next` that names an
area that doesn't exist, or bad TOML shows as one clear error rather than a
hint that silently never appears. `python -m pytest test_areas.py` checks the
same things plus a few invariants (every `random` tip says "no accepted rule",
every entry cites a source).

## Where the rules come from

- [Maxroll — D2R Map Reading](https://maxroll.gg/d2/resources/map-reading)
- [d2r-speedrun-cheatsheet](https://github.com/minimapletinytools/d2r-speedrun-cheatsheet)
  (from Teo-'s guide on speedrun.com)
- [PureDiablo — Area Levels](https://www.purediablo.com/diablo-2/diablo-2-area-levels)
- [PureDiablo — Experience](https://www.purediablo.com/d2wiki/Experience) (the
  ±5 / 81-62-43-24-5 % penalty table behind the CLVL line)

## When a rule is wrong in play

Press `Ctrl+F12` (or the *Flag current area as wrong* button). The area name is
appended to `debug/flagged.log` with a timestamp, so wrong entries can be fixed
in a batch after the session instead of interrupting it.

## Superunique facts — `data/superuniques.toml`

One table per boss, keyed by the exact name used in `uniques`:

```toml
[unique."Pindleskin"]
mlvl = 86                 # Hell
tc = 87                   # Hell treasure class; 87 = can drop everything
immune = ["poison"]       # Hell
base = "Reanimated Horde"
note = ""                 # optional, shown after the facts
```

`test_areas.py` checks that every name in an area's `uniques` has an entry.
