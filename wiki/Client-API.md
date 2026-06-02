# Client API — `LuaClient`

`clients()[1]` returns a `LuaClient`. These methods are the bulk of the
scripting surface — every call takes the `client:` receiver.

```lua
local client = clients()[1]
```

Below: curated notes and examples for the common areas, then the **full method
reference** grouped by category.

---

## State & stats

Vitals and basic predicates. Percentages are 0–100.

```lua
if client:health_pct() < 40 then client:use_potion() end
print(client:zone(), "lvl", client:level(), "school", client:focus_school())
```

## Movement & position

`teleport` snaps to an exact coordinate (verified + retried); `navigate`
pathfinds along the navmesh; `teleport_near` lands on a walkable point *near* a
target instead of on top of it.

```lua
client:navigate(-120, 5400, 0)

local p = client:position()                   -- positional {x,y,z}: p[1],p[2],p[3]
client:teleport(p[1], p[2], p[3])

client:tp_to_quest()                          -- walk to the current quest objective
```

> **Coordinate shapes:** `position()`, `quest_position()`, and mob `location()`
> return *positional* arrays — index them `[1] [2] [3]`. The reagent and
> `zone_chunks()` rows are *keyed* — use `.x` / `.y` / `.z` (and `.name`).

## Entities & mobs

Lookups return [`LuaMob`](Mob-API) objects (or lists). Names match
case-insensitively against both the internal and display name.

```lua
local boss = client:nearest_boss()
if boss then boss:near_to() end               -- walk up to it

for _, m in ipairs(client:mobs_by_title("elite")) do
    print(m:name(), m:distance())
end
```

`waitfor_mob` blocks for a *combat* mob; `waitfor_entity` blocks for any world
entity (NPCs, scenery, players).

## Combat control

`load_playstyle` sets the priority list and `enable_combat` hands the fight to
the native engine; `waitfor_battle_finish` drives it to completion. See
[Combat Playstyles](Combat-Playstyles) for the DSL. `enemies()`, `allies()`,
and `combatants()` return [`LuaCombatant`](Combatant-API) objects for
inspecting the live battle.

```lua
client:load_playstyle [[
    Feint @ enemy |
    any<damage>[Colossal] @ enemy |
    ?(self.health < 25%) Satyr @ self |
    pass
]]
client:waitfor_battle_finish()
```

## Dialog & UI

`enable_dialog` runs a background watcher that auto-advances dialog; `auto_dialog`
clicks through a single conversation synchronously. Window methods take a
[path array](Getting-Started#ui-window-paths).

```lua
client:enable_dialog()
client:interact()                 -- talk to whatever you're facing
```

## Inventory, drops & farming

```lua
client:farm_mob{
    mob_name   = "fortee thief",
    until_drop = "piercing onyx",
    playstyle  = "Wobbegong Frenzy[Epic] @ enemy | Wand @ enemy | pass",
}
```

`farm_dungeon` takes the same `playstyle` / `until_drop` / `max_runs` keys plus
`enter`, `pre_fight`, `exit_gate`, and `on_run_end` callbacks; `kill_boss` takes
`mob` and `playstyle`. See [Examples](Examples) for full loops.

## Reagents

Offline node data comes from the zone WAD; live matching uses template ids
(reliable, unlike names). `farm_reagent` is the full sweep-harvest-hop loop.

```lua
for _, r in ipairs(client:reagents_present(800)) do   -- keyed rows: r.name, r.x …
    client:teleport(r.x, r.y, r.z)
end
client:farm_reagent{ name = "Black Lotus", amount = 50 }   -- sweep the current zone
```

---

## Full method reference

<!-- AUTOGEN:LuaClient START — generated from source; do not edit. Run: python -m src.lang.docgen --emit -->
#### State & stats

| Method | Signature | Description |
|---|---|---|
| `health` | `() -> int` | Current health points |
| `max_health` | `() -> int` | Maximum health points |
| `health_pct` | `() -> float` | Health as a percentage of max (0–100) |
| `mana` | `() -> int` | Current mana points |
| `max_mana` | `() -> int` | Maximum mana points |
| `mana_pct` | `() -> float` | Mana as a percentage of max (0–100) |
| `energy` | `() -> int` | Current energy (used for pet/gardening/fishing) |
| `level` | `() -> int` | Wizard level |
| `focus_school` | `() -> str` | Primary magic school name (e.g. "Fire") |
| `is_full_hp` | `() -> bool` | True when health is at maximum |
| `in_danger` | `(hp_pct: float = 25.0) -> bool` | True when health is below `hp_pct` (default 25%) |

#### Position & movement

| Method | Signature | Description |
|---|---|---|
| `x` | `() -> float` | Own X world coordinate |
| `y` | `() -> float` | Own Y world coordinate |
| `z` | `() -> float` | Own Z world coordinate |
| `position` | `()` | Own position as a positional `{x, y, z}` array — index `[1] [2] [3]` |
| `facing` | `() -> float` | Own yaw (facing angle) in radians |
| `distance_to` | `(x: float, y: float, z: float) -> float` | Distance from the client to `(x, y, z)` |
| `at_position` | `(x: float, y: float, z: float, tolerance: float = 75.0) -> bool` | True if within `tolerance` units of `(x, y, z)` |
| `teleport` | `(x: float, y: float, z: float)` | Teleport to `(x, y, z)` — verified and retried |
| `teleport_near` | `(x: float, y: float, z: float, dist: float = 180.0, scan_radius: float = 1500.0)` | Teleport to a navmesh point near `(x, y, z)`, not on top of it |
| `navigate` | `(x: float, y: float, z: float)` | Pathfind-walk to `(x, y, z)` along the navmesh |
| `follow_path` | `(points)` | Teleport through a sequence of positional `{x,y,z}` points (optional per-point `sleep`) |
| `release_mouse` | `()` | Release a held mouse button (clears a stuck drag) |

#### Zones & realms

| Method | Signature | Description |
|---|---|---|
| `zone` | `() -> str` | Current zone name; records it as the baseline for `waitfor_zone_change` |
| `zone_quiet` | `() -> str` | Current zone name without updating the change baseline — for tight poll loops |
| `in_zone` | `(name: str) -> bool` | True if the current zone name contains `name` |
| `to_zone` | `(name: str)` | Native traversal to a named zone (BFS + gate handlers) |
| `change_realm` | `()` | Hop to a different game realm so spawns repopulate |
| `zone_chunks` | `()` | Nav-mesh sweep grid `{x,y,z}` covering the whole current zone |

#### Gates & dungeons

| Method | Signature | Description |
|---|---|---|
| `list_gates` | `()` | Names of every zone gate/transition reachable here |
| `go_through_gate` | `(name: str, back_distance: float = 250.0, hold_seconds: float = 4.0, max_dist: float = None) -> bool` | Walk through the gate whose name contains `name` |
| `exit_dungeon` | `(gate: str = Start) -> bool` | Leave via the named gate (default "Start") — reads as English |

#### Waiting & lifecycle

| Method | Signature | Description |
|---|---|---|
| `is_free` | `() -> bool` | True when not loading / in dialog / in combat / animating |
| `is_loading` | `() -> bool` | True while a zone load is in progress |
| `in_combat` | `() -> bool` | True while a battle is active |
| `waitfor_freedom` | `(window: float = None)` | Block until the client is idle (no load/dialog/combat) |
| `waitfor_battle_start` | `(window: float = None)` | Block until a battle begins |
| `waitfor_battle_finish` | `(window: float = None)` | Drive combat until the battle ends |
| `waitfor_dialog` | `(window: float = None)` | Block until an advance-dialog button appears |
| `waitfor_window` | `(path, window: float = None)` | Block until the UI window at `path` is visible |
| `waitfor_zone` | `(name: str, window: float = None)` | Block until the zone name contains `name` |
| `waitfor_zone_change` | `(current: str = None, window: float = None)` | Block until the zone changes from `current` |
| `waitfor_entity` | `(name: str, window: float = None, max_dist: float = None)` | Block until any entity matching `name` exists |
| `waitfor_entity_gone` | `(name: str, max_dist: float = None, window: float = None)` | Block until no entity matching `name` remains in range |
| `waitfor_mob` | `(name: str, window: float = None, max_dist: float = None)` | Block until a combat mob matching `name` exists |
| `waitfor_mob_gone` | `(name: str, max_dist: float = None, window: float = None)` | Block until no mob matching `name` remains in range |

#### Entities & mobs

| Method | Signature | Description |
|---|---|---|
| `entities` | `(max_dist: float = None)` | All world entities in range as `LuaMob` objects |
| `mobs` | `(max_dist: float = None)` | All combat-capable NPC entities as `LuaMob` objects |
| `mobs_by_school` | `(school: str, max_dist: float = None)` | Mobs whose primary school contains `school` |
| `mobs_by_title` | `(title: str, max_dist: float = None)` | Mobs by title ("boss", "elite", "minion", …) |
| `find_mob` | `(name: str, max_dist: float = None)` | First entity whose name contains `name` (case-insensitive) |
| `find_mobs` | `(name: str, max_dist: float = None)` | All entities whose name contains `name` |
| `find_mobs_sorted` | `(name: str, max_dist: float = None)` | Matching entities sorted nearest-first |
| `nearest_mob` | `(max_dist: float = None)` | Closest entity, or nil if none |
| `nearest_boss` | `(max_dist: float = None)` | Closest boss entity, or nil if none |
| `nearest_named` | `(name: str, max_dist: float = None)` | Closest entity matching `name`, or nil |
| `has_mob` | `(name: str, max_dist: float = None) -> bool` | True if any entity matches `name` |
| `boss_nearby` | `(max_dist: float = 5000) -> bool` | True if a boss is within `max_dist` (default 5000) |
| `mob_by_id` | `(global_id: int)` | Entity with exact `global_id`, or nil |
| `mob_by_template` | `(template_id: int)` | First entity with matching `template_id`, or nil |
| `go_to_npc` | `(name: str, max_dist: float = None)` | Find an NPC by name and navigate to it |
| `dump_entities` | `(max_dist: float = 5000, needle: str = None)` | Log every nearby entity (optionally filtered by `needle`) |
| `dump_npcs` | `(max_dist: float = 5000)` | Log nearby NPC entities only |

#### Combat control

| Method | Signature | Description |
|---|---|---|
| `enable_combat` | `()` | Hand combat to the native engine for this client |
| `disable_combat` | `()` | Stop the native combat engine |
| `load_playstyle` | `(config)` | Set the combat priority list (see Combat Playstyles) |
| `combatants` | `()` | All combat participants as `LuaCombatant` objects |
| `enemies` | `()` | Enemy-team combatants as `LuaCombatant` objects |
| `allies` | `()` | Friendly-team combatants as `LuaCombatant` objects |
| `pass_turn` | `()` | Pass the current combat turn |
| `flee` | `()` | Flee the current battle |
| `cast_spell` | `(hand_index: int, target: int = 0)` | Cast the card at `hand_index` on combat `target` |
| `enchant_card` | `(enchant_index: int, target_index: int)` | Apply enchant at `enchant_index` to the card at `target_index` |
| `discard_card` | `(hand_index: int)` | Discard the card at `hand_index` |
| `fuse_cards` | `(primary_index: int, secondary_index: int, fused_spell_id: int = 0)` | Fuse two cards into a TC (optionally a specific `fused_spell_id`) |
| `draw_tc` | `()` | Draw a treasure card into hand |
| `pet_willcast` | `(spell_name: str, target: int)` | Queue the pet's may-cast `spell_name` at `target` |
| `set_pip_school` | `(school: str)` | Set the archmastery pip school via the spellbook UI |
| `set_focus_school` | `(school: str)` | Set the focus school via the spellbook UI |

#### Dialog & UI

| Method | Signature | Description |
|---|---|---|
| `enable_dialog` | `()` | Start the auto-advance dialog watcher |
| `disable_dialog` | `()` | Stop the auto-advance dialog watcher |
| `auto_dialog` | `(max_clicks: int = 30) -> int` | Spam space through dialog until the advance button stops; returns clicks made |
| `interact` | `(window: float = 1.5, await_dialog: bool = True)` | Press the interact key and (optionally) wait for dialog |
| `send_key` | `(key: str, secs: float = 0.1)` | Press `key`, held for `secs` |
| `click_window` | `(path)` | Click the UI window at `path` |
| `window_text` | `(path) -> str` | Text of the UI window at `path` |
| `window_visible` | `(path) -> bool` | True if the window at `path` is visible |
| `window_disabled` | `(path) -> bool` | True if the window at `path` is greyed-out/disabled |
| `dump_windows` | `(max_depth: int = 4, only_visible: bool = False)` | Log the UI window tree to `max_depth` |

#### Inventory & items

| Method | Signature | Description |
|---|---|---|
| `backpack` | `()` | All backpack items as `LuaItem` objects |
| `equipped` | `()` | All equipped items as `LuaItem` objects |
| `find_item` | `(name: str)` | First backpack item whose name contains `name`, or nil |
| `find_equipped` | `(name: str)` | First equipped item whose name contains `name`, or nil |
| `has_item` | `(name: str) -> bool` | True if any backpack item matches `name` |
| `item_count` | `(name: str) -> int` | Count of backpack items matching `name` |
| `bag_used` | `() -> int` | Backpack slots in use |
| `bag_max` | `() -> int` | Total backpack slots |
| `equip_deck` | `(name: str, window: float = 20.0)` | Equip the deck preset whose name contains `name` |

#### Drops & farming

| Method | Signature | Description |
|---|---|---|
| `recent_drops` | `(n: int = 25)` | Last `n` dropped item names (most recent last) |
| `got_drop` | `(name: str) -> bool` | True if `name` appears in the recent drop log |
| `has_drops` | `(names) -> bool` | True only if *every* name in `names` has dropped recently |
| `farm_dungeon` | `(opts) -> int` | Re-run a dungeon until a target drop or run count |
| `farm_mob` | `(opts) -> int` | Find + engage a named mob repeatedly until a drop or count |
| `farm_until` | `(drop_name: str, body, max_runs: int = 1000) -> int` | Run `body(i)` until `drop_name` appears, up to `max_runs` |
| `kill_boss` | `(opts=None)` | Engage a boss (named or nearest) and fight to completion |

#### Reagents

| Method | Signature | Description |
|---|---|---|
| `reagent_nodes` | `(name: str)` | Offline spawn-node `{x,y,z}` list for a reagent in this zone |
| `reagent_spawns` | `()` | Every reagent in this zone as `{name,x,y,z}` rows (offline WAD data) |
| `reagents_present` | `(max_dist: float = 3000)` | Live reagents in range as `{name,x,y,z}`, matched by template id |
| `reagent_debug` | `(max_dist: float = 600)` | Log reagent template-id resolution for diagnosing matches |
| `farm_reagent` | `(name=None, amount=None, zones=None, hop_realms=True)` | Full farm loop: sweep nodes across `zones`, harvest, hop realms |

#### Quests

| Method | Signature | Description |
|---|---|---|
| `current_quest_name` | `() -> str` | Name of the active tracked quest |
| `current_goal_name` | `() -> str` | Text of the active quest goal |
| `quest_destination_zone` | `() -> str` | Zone the current quest points to |
| `quest_position` | `()` | Quest-arrow target position as a positional `{x,y,z}` array |
| `quest_in_zone` | `(needle: str, settle: float = 0.5) -> bool` | True if the quest destination is in the current zone |
| `tracking_quest` | `(needle: str) -> bool` | True if the tracked quest name contains `needle` |
| `tracking_goal` | `(needle: str) -> bool` | True if the tracked goal text contains `needle` |
| `tp_to_quest` | `()` | Teleport toward the current quest objective |
| `dump_quest` | `()` | Log the full quest/goal state |
| `exclude_from_questing` | `(excluded: bool = True)` | Flag this client in/out of the shared questing loop |

#### Health management

| Method | Signature | Description |
|---|---|---|
| `has_potion` | `() -> bool` | True if at least one full potion charge is available |
| `potion_count` | `() -> float` | Number of full potion charges (fractional, e.g. 1.5) |
| `use_potion` | `() -> bool` | Click the potion button to refill HP and mana |
| `ensure_health` | `(min_pct: float = 50.0) -> bool` | Pop a potion if HP is below `min_pct`; returns whether it did |
| `wait_until_healed` | `(target_pct: float = 95.0, window: float = 60.0) -> bool` | Block until HP recovers to `target_pct` |

#### Travel & social

| Method | Signature | Description |
|---|---|---|
| `go_to_dorm` | `()` | Click the compass dorm teleporter |
| `friend_tp` | `(friend_name: str) -> bool` | Teleport to an online friend by name via the friends list |
| `enter_sigil` | `(x: float, y: float, z: float, opts=None)` | Teleport to a sigil and trigger entry (waits for the popup) |

#### HTTP

| Method | Signature | Description |
|---|---|---|
| `http_get` | `(url: str, headers=None) -> str` | HTTP GET; returns the response body as text |
| `http_post` | `(url: str, body: str = , headers=None) -> str` | HTTP POST with optional `body`; returns response text |
| `http_put` | `(url: str, body: str = , headers=None) -> str` | HTTP PUT with optional `body`; returns response text |
| `http_patch` | `(url: str, body: str = , headers=None) -> str` | HTTP PATCH with optional `body`; returns response text |
| `http_delete` | `(url: str, headers=None) -> str` | HTTP DELETE; returns response text |

#### Diagnostics & logging

| Method | Signature | Description |
|---|---|---|
| `log` | `(msg: str)` | Write a client-tagged log line |
| `log_state` | `(label: str = state)` | Log a compact snapshot of client state under `label` |
| `lookup_template` | `(template_id)` | Resolve a template id to its name via the WAD cache |
<!-- AUTOGEN:LuaClient END -->
