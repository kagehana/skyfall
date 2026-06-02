<div align="center">

# ✦ SkyFall

### The ideal Wizardry engine.

A native automation engine for Wizard101. Scripted in Lua, fought in code.

[![License: GPL v3](https://img.shields.io/badge/License-GPLv3-blue.svg)](LICENSE)
[![Python 3.13+](https://img.shields.io/badge/python-3.13+-blue.svg)](https://www.python.org/)
[![Docs: Wiki](https://img.shields.io/badge/docs-wiki-8A2BE2.svg)](../../wiki/Home)

</div>

<table><tr><td>

SkyFall is a Wizard101 engine you can use as much or as little as you want. Maybe
you just want the boring parts gone, so you let it win a fight, hop you across a
world, or farm reagents while you're off doing something else. Or maybe you hand
over the whole account and let it quest and grind for hours on its own. It does
both.

You can run it straight from the app, or write your own routines in **Lua** when
you want real control. Automate one wizard, or a whole team of them.

</td><td>

<img src="https://i.imgur.com/Nlij6cs.png" width="400"/>

</td></tr></table>

> SkyFall reads and writes the live memory of the Wizard101 client. Using it
> almost certainly violates the [KingsIsle Terms of Service](https://www.kingsisle.com/terms-of-use)
> and may get your account suspended or banned. **Use entirely at your own
> risk.** Provided "as is" under GPL-3.0 with no warranty.

---

## What it does

The headline is questing. Hand SkyFall a wizard and it plays the game for you:
it reads your current quest, gets itself to the objective, fights whatever's in
the way, clicks through the dialog, and moves on to the next one. It'll do that
across entire worlds, for as long as you leave it running.

That only works because the combat is real. It's an engine, not a key-masher.
You give it a strategy once, like which blades to stack and what to cast when
your health drops, and it reads the board every round and plays the cards
itself. The same engine farms bosses and dungeons for drops while you're away.

And when you want something specific, you write it in Lua. The full bot API is
there as plain commands, so a reagent farm, a four-wizard team, or a custom boss
rotation is only a few readable lines away.

---

## Install

### Pre-built binary

1. Grab the latest `Skyfall-vX.Y.Z.zip` from [Releases](../../releases).
2. Extract anywhere and run `SkyFall.exe`.
3. Launch Wizard101 from the **Launcher** tab, or open it yourself first.

### From source · Windows

Requires Python 3.13+ and [uv](https://docs.astral.sh/uv/).

```powershell
git clone https://github.com/kagehana/skyfall
cd skyfall
uv sync --group dev
uv run python skyfall.py
```

The custom `wizwalker` fork at `libs/wizwalker` is a `uv` workspace member, so
`uv sync` installs it for you.

---

## Your first script

Every script that touches a client opens by grabbing the primary one. This one
rides alongside the auto-quester: it leaves the wizard questing on its own, but
the moment a boss shows up it swaps to a boss deck and a heavier playstyle, then
swaps back for ordinary mobs.

```lua
-- grab first client
local client = clients()[1]

-- establish our preferences
local QUEST_DECK, BOSS_DECK = "Monster", "Boss"
local QUEST_PLAY            = [[
    {1} Deathblade @ self |
    Feint Mass @ aoe |
    Wobbegong Frenzy[Epic] @ aoe |
    pass
]]

local BOSS_PLAY             = [[
    Feint @ boss |
    any<blade> @ self |
    any<damage>[Colossal] @ boss |
    ?(self.health < 30%) any<heal> @ self |
    pass
]]

-- enable auto-dialog
client:enable_dialog()

-- boss discovery toggle
local on_boss = nil

-- keep it going
while true do
    -- ensure client can modify deck
    if client:is_free() then
        -- check if a boss is nearby
        local boss = client:boss_nearby()

        -- check if boss is around
        if boss ~= on_boss then
            -- modify deck & playstyle
            client:equip_deck(boss and BOSS_DECK or QUEST_DECK)
            client:load_playstyle(boss and BOSS_PLAY or QUEST_PLAY)

            -- force playstyle to be cached
            client:enable_combat()

            -- ensure we're in the proper mode
            on_boss = boss
        end
    end

    -- wait
    sleep(0.5)
end
```

Those `[[ ... ]]` blocks are the **combat DSL** — a pipe-separated priority list
with templates (`any<req>`), enchants (`[Enchant]`), conditionals (`?(expr)`),
chained casts (`&`), and round-specific lines (`{N}`). The engine walks it
top-to-bottom each round and plays the first move it can afford.

Scripting will become increasingly more intuitive as updates push. As it stands,
it already is. There's awareness about things like forcing a playstyle cache.

**The full scripting reference lives in the [📖 Wiki](../../wiki/Home):**
- [Getting Started](../../wiki/Getting-Started) — the script model & globals
- [Client API](../../wiki/Client-API) · [Mob](../../wiki/Mob-API) · [Combatant](../../wiki/Combatant-API) · [Item](../../wiki/Item-API)
- [Combat Playstyles](../../wiki/Combat-Playstyles) · [Navigation](../../wiki/Navigation) · [Examples](../../wiki/Examples)

---

## Develop

**Build the binary:**

```powershell
uv run --group dev pyinstaller --noconfirm --clean Skyfall.spec   # → dist/SkyFall.exe
```

**Run the tests** — no game required; the Lua bridge, sandbox, combat parser,
entity client, and zone graph all run under mocks:

```powershell
uv run --group dev pytest -q
```

---

## License

GPL-3.0-only. See [LICENSE](LICENSE).
