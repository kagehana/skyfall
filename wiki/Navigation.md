# Navigation

SkyFall finds its own way around using zone data it ships with — it doesn't lean on the in-game quest arrow to get places.

## Moving inside a zone

| Method | When to use it |
|---|---|
| `client:teleport(x, y, z)` | snap straight to a spot (it verifies and retries) |
| `client:teleport_near(x, y, z)` | land on walkable ground near a spot, not right on it |
| `client:navigate(x, y, z)` | actually walk there along the navmesh |
| `client:follow_path(points)` | hit a series of waypoints in order |

```lua
local client = clients()[1]

client:tp_to_quest()                       -- jump to wherever the quest points
client:follow_path({ {0, 0, 0}, {500, 120, 0} })   -- points are {x, y, z}
```

## Getting to another zone

`to_zone` does the heavy lifting — it works out a route across the worlds (gates, world hops, the teleporter NPCs) and takes you there:

```lua
client:to_zone("WizardCity/WC_Hub")
client:waitfor_zone("WC_Hub")
```

Zone names are the full path, like `WizardCity/WC_Hub`. `waitfor_zone` just needs enough of the name to match.

## Gates

A gate is any doorway between zones — a dungeon entrance, a sigil, a transition. List what's around you, then walk through one by name (it matches on a substring):

```lua
for _, g in ipairs(client:list_gates()) do print(g) end

client:go_through_gate("Dungeon")
client:exit_dungeon()              -- same as go_through_gate("Start")
```

## Realms

Mobs and reagents run out per realm. Hop to a fresh one and they come back:

```lua
client:change_realm()
```

## Reagents

Reagents are awkward: they don't sit at fixed coordinates — they spawn at random spots along a zone's paths. So SkyFall pulls the candidate spots from the zone's own files and matches what's actually there by template ID, since the names aren't reliable.

| Method | What you get |
|---|---|
| `client:reagent_nodes(name)` | the possible spots for one reagent, as `{x,y,z}` |
| `client:reagent_spawns()` | every reagent in the zone, as `{name,x,y,z}` |
| `client:reagents_present([dist])` | what's actually up nearby right now, as `{name,x,y,z}` |
| `client:farm_reagent{...}` | the whole thing: sweep, harvest, hop realms, repeat |

```lua
-- grab whatever's up right now
for _, r in ipairs(client:reagents_present(800)) do
    client:teleport(r.x, r.y, r.z)
    client:send_key("X")
end

-- or just let it run: 50 Black Lotus across these zones, hopping realms
client:farm_reagent{
    name      = "Black Lotus",
    amount    = 50,
    zones     = { "Austrilund", "Nordrilund", "Vestrilund" },
    hop_realms = true,
}
```

If you don't have node data for a zone, `client:zone_chunks()` gives you a rough grid covering the whole place to sweep as a fallback.
