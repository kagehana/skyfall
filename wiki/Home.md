# SkyFall Lua Scripting

SkyFall is a Wizard101 bot. You tell it what to do by writing small Lua scripts, and it runs them — walking your wizard around, fighting battles, talking to NPCs, whatever you've written. This wiki is about that side of it: the functions you can call and how they fit together.

Never written one before? Start with [Getting Started](Getting-Started). Just looking something up? The API pages list every method with its signature.

## The pages

- **[Getting Started](Getting-Started)** — how a script is put together, and the globals you always have on hand.
- **[Client API](Client-API)** — the big one. Everything you do through a wizard (`client:...`).
- **[Mob API](Mob-API)** — things out in the world: NPCs, monsters, reagent nodes.
- **[Combatant API](Combatant-API)** — the fighters in a battle that's actually running.
- **[Item API](Item-API)** — your backpack and equipped gear.
- **[Standard Library](Standard-Library)** — the `sky.*` helpers and the plain globals.
- **[Combat Playstyles](Combat-Playstyles)** — how you describe a fight to the combat engine.
- **[Navigation](Navigation)** — getting around: zones, gates, realms, reagents.
- **[Examples](Examples)** — whole scripts to read and borrow from.

## A quick taste

Grab your first client and go:

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

Most scripts have that shape: wait until the game's ready, check something, act, loop.

## What hands you what

A few calls give you objects back instead of plain numbers or strings, and each kind has its own page:

| You call | You get |
|---|---|
| `clients()` | the list of clients — `clients()[1]` is your main one |
| `client:nearest_boss()`, `client:find_mob(name)` | a [Mob](Mob-API) |
| `client:enemies()`, `client:allies()` | [Combatants](Combatant-API) |
| `client:backpack()`, `client:find_item(name)` | [Items](Item-API) |

---

One thing worth knowing: the method tables on the API pages are generated straight from SkyFall's source, so they always match what the bot really exposes. The writing around them is by hand. If you're hacking on SkyFall itself, regenerate the tables with `python -m src.lang.docgen --emit` instead of editing them.
