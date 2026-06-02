# SkyFall Lua Scripting

SkyFall is a Wizard101 automation engine. You drive it from Lua — you write the scripts, it carries them out: moving your wizard, fighting, working through dialog, whatever you've written. This wiki covers that surface: the functions you call and how they fit together.

New here? Start with [Getting Started](Getting-Started). Looking something up? The API pages list every method and its signature.

## The pages

- **[Getting Started](Getting-Started)** — how a script is put together, and the globals you always have.
- **[Client API](Client-API)** — the big one: everything you do through a wizard (`client:...`).
- **[Mob API](Mob-API)** — things out in the world: NPCs, monsters, reagent nodes.
- **[Combatant API](Combatant-API)** — the fighters in a battle that's actually running.
- **[Item API](Item-API)** — backpack and equipped gear.
- **[Standard Library](Standard-Library)** — the `sky.*` helpers and the plain globals.
- **[Combat Playstyles](Combat-Playstyles)** — how you describe a fight to the engine.
- **[Navigation](Navigation)** — zones, gates, realms, reagents.
- **[Examples](Examples)** — whole scripts to read and borrow from.

## A quick taste

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

Most scripts take that shape: wait until the game's settled, check something, act, loop.

## What hands you what

A few calls return objects rather than plain values, and each kind has its own page:

| You call | You get |
|---|---|
| `clients()` | the client list — `clients()[1]` is your main wizard |
| `client:nearest_boss()`, `client:find_mob(name)` | a [Mob](Mob-API) |
| `client:enemies()`, `client:allies()` | [Combatants](Combatant-API) |
| `client:backpack()`, `client:find_item(name)` | [Items](Item-API) |

---

The method tables on the API pages are generated from SkyFall's source, so they always match what the engine actually exposes. The prose around them is hand-written. If you're hacking on SkyFall itself, regenerate them with `python -m src.lang.docgen --emit` rather than editing by hand.
