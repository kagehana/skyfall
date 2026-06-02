# Mob API — `LuaMob`

A `LuaMob` is any **world entity** — NPC, monster, scenery, reagent node, or
player. You get one from the client lookups:

```lua
local client = clients()[1]

local boss  = client:nearest_boss()              -- LuaMob or nil
local npc   = client:find_mob("Eudora Tangletree")
local elite = client:mobs_by_title("elite")[1]
```

All accessors read live memory each call, so re-read after the entity moves.

## Moving to a mob

Three ways to close distance, in increasing safety:

```lua
boss:to()           -- teleport directly onto it
boss:near_to()      -- teleport to a walkable point nearby (won't overlap)
boss:navigate_to()  -- pathfind-walk to it
```

## Identifying mobs

`template_id` is stable across sessions (match on it); `global_id` is
per-session. `title` returns `"easy"`, `"normal"`, `"elite"`, `"boss"`, or
`"minion"`; `is_boss()` is the boss shortcut.

```lua
for _, m in ipairs(client:mobs()) do
    if m:is_boss() then
        print(m:display_name(), m:school(), "lvl", m:level())
    end
end
```

NPC template fields (`level`, `school`, `starting_health`, …) are read from the
behavior template and fall back to sensible defaults when the entity has none.

---

## Full method reference

<!-- AUTOGEN:LuaMob START — generated from source; do not edit. Run: python -m src.lang.docgen --emit -->
#### Identity

| Method | Signature | Description |
|---|---|---|
| `name` | `() -> str` | Internal object name |
| `display_name` | `() -> str` | Localized display name shown in-game |
| `debug_name` | `() -> str` | Debug name string |
| `global_id` | `() -> int` | Per-session global object id |
| `perm_id` | `() -> int` | Permanent object id |
| `mobile_id` | `() -> int` | Mobile (actor) id |
| `template_id` | `() -> int` | Template id (stable across sessions) |
| `zone_tag_id` | `() -> int` | Zone tag id the entity belongs to |

#### Position & movement

| Method | Signature | Description |
|---|---|---|
| `distance` | `() -> float` | Distance from the client to this entity |
| `x` | `() -> float` | Entity X coordinate |
| `y` | `() -> float` | Entity Y coordinate |
| `z` | `() -> float` | Entity Z coordinate |
| `location` | `()` | Entity position as a positional `{x, y, z}` array |
| `yaw` | `() -> float` | Facing angle in radians |
| `pitch` | `() -> float` | Pitch in radians |
| `roll` | `() -> float` | Roll in radians |
| `height` | `() -> float` | Actor height |
| `scale` | `() -> float` | Model scale factor |
| `speed` | `() -> int` | Movement speed multiplier |
| `to` | `()` | Teleport the client directly onto this entity |
| `near_to` | `(dist: float = 180.0, scan_radius: float = 1500.0)` | Teleport the client to a navmesh point near this entity |
| `navigate_to` | `()` | Pathfind-walk the client to this entity |

#### NPC template data

| Method | Signature | Description |
|---|---|---|
| `is_boss` | `() -> bool` | True if the template is flagged a boss |
| `title` | `() -> str` | "easy", "normal", "elite", "boss", or "minion" |
| `level` | `() -> int` | NPC level |
| `starting_health` | `() -> int` | NPC starting health |
| `school` | `() -> str` | Primary school of focus |
| `secondary_school` | `() -> str` | Secondary school of focus |
| `intelligence` | `() -> float` | AI intelligence value |
| `aggressive_factor` | `() -> int` | Aggression value (higher = pulls sooner) |
| `max_shadow_pips` | `() -> int` | Maximum shadow pips the NPC can hold |
| `collision_radius` | `() -> float` | Collision cylinder radius |
| `hide_hp` | `() -> bool` | True if the NPC hides its current HP |
| `turn_towards_player` | `() -> bool` | True if the NPC turns to face the player |

#### Misc

| Method | Signature | Description |
|---|---|---|
| `behavior_names` | `()` | All behavior component names on this entity |
<!-- AUTOGEN:LuaMob END -->
