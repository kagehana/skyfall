# Navigation

SkyFall navigates with native zone data — no reliance on the in-game quest
arrow for traversal.

## Moving within a zone

| Method | Use |
|---|---|
| `client:teleport(x, y, z)` | Snap to an exact point (verified + retried) |
| `client:teleport_near(x, y, z)` | Snap to a walkable point near a target |
| `client:navigate(x, y, z)` | Pathfind-walk along the navmesh |
| `client:follow_path(points)` | Teleport through a sequence of positional `{x,y,z}` points |

```lua
local client = clients()[1]

client:tp_to_quest()                                 -- toward the quest objective

-- follow_path points are positional {x, y, z}; an optional `sleep` pauses after each
client:follow_path({ {0, 0, 0}, {500, 120, 0} })

local p = client:position()                          -- positional: p[1], p[2], p[3]
client:teleport(p[1], p[2], p[3])
```

## Traveling between zones

`to_zone` runs the native traversal engine (BFS over zone-map data plus gate,
world-hop, and interactive-teleporter handlers):

```lua
client:to_zone("WizardCity/WC_Hub")
client:waitfor_zone("WC_Hub")
```

## Gates

A gate is any zone transition or dungeon entrance. List what's reachable, then
walk through one by name (substring match):

```lua
for _, g in ipairs(client:list_gates()) do print(g) end

client:go_through_gate("Dungeon")
client:exit_dungeon()              -- alias: go_through_gate("Start")
```

## Realms

Spawns (mobs, reagents) deplete per realm. Hop to repopulate them:

```lua
client:change_realm()
```

## Reagent farming

Reagent nodes have **no fixed coordinates** — they spawn at random path nodes,
so SkyFall reads node positions from the zone WAD and matches live reagents by
template id (names are unreliable).

| Method | Returns |
|---|---|
| `client:reagent_nodes(name)` | Offline spawn-node `{x,y,z}` list for one reagent |
| `client:reagent_spawns()` | Every reagent in the zone as `{name,x,y,z}` rows |
| `client:reagents_present([dist])` | Live in-range reagents as `{name,x,y,z}` |
| `client:farm_reagent{...}` | Full sweep → harvest → realm-hop loop |

```lua
-- manual sweep of whatever is up right now
for _, r in ipairs(client:reagents_present(800)) do
    client:teleport(r.x, r.y, r.z)
    client:send_key("X")
end

-- hands-off loop: collect 50 Sandstone across these zones, hopping realms
client:farm_reagent{
    name      = "Sandstone",
    amount    = 50,
    zones     = { "Krokotopia/KT_Hub", "Krokotopia/KT_Tomb" },
    hop_realms = true,
}
```

When you don't have node data, `client:zone_chunks()` returns a nav-mesh sweep
grid covering the whole zone as a coarse fallback.
