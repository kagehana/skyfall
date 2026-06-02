# SkyFall — Lua Scripting Wiki

**SkyFall** is a game-automation engine for Wizard101, written in Python. You
write bot scripts in **Lua**; a Lua bridge exposes the engine's async
operations as synchronous globals and `client:*` methods. Combat and navigation
are handled by native engines.

This wiki documents the **scripting surface** — everything you can call from a
`.lua` script.

## Start here

- **[Getting Started](Getting-Started)** — the script model, the required
  preamble, globals, and how scripts run.
- **[Client API](Client-API)** — the `client:*` methods (the bulk of the API).
- **[Mob API](Mob-API)** — `LuaMob`, returned by `find_mob`, `nearest_boss`, …
- **[Combatant API](Combatant-API)** — `LuaCombatant`, returned by `enemies`, `allies`, …
- **[Item API](Item-API)** — `LuaItem`, returned by `backpack`, `find_item`, …
- **[Standard Library](Standard-Library)** — globals + the `sky.*` recipes.
- **[Combat Playstyles](Combat-Playstyles)** — the playstyle priority DSL.
- **[Navigation](Navigation)** — zones, gates, realms, reagent farming.
- **[Examples](Examples)** — complete, runnable scripts.

## Quickstart

Every script that touches a client starts by grabbing the primary one:

```lua
local client = clients()[1]

while true do
    client:waitfor_freedom()
    if client:boss_nearby() then
        client:load_playstyle [[
            Feint @ enemy |
            any<damage>[Colossal] @ enemy |
            pass
        ]]
        client:waitfor_battle_finish()
    end
end
```

## Object model at a glance

| Call | Returns |
|---|---|
| `clients()` | table of `LuaClient` (1-indexed) |
| `client:find_mob(name)`, `client:nearest_boss()` | `LuaMob` |
| `client:enemies()`, `client:allies()`, `client:combatants()` | list of `LuaCombatant` |
| `client:backpack()`, `client:find_item(name)` | `LuaItem` |

---

> The method **reference tables** in this wiki are generated from source with
> `python -m src.lang.docgen --emit`. Edit the prose freely; regenerate the
> tables rather than hand-editing them. See the [Standard Library](Standard-Library)
> page footer for details.
