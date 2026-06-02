# Examples

Whole scripts you can read, run, and pull apart. They all open with the [client line](Getting-Started#start-with-a-client).

## Farm a mob for a drop

Keep fighting one mob until the thing you want drops, then head home.

```lua
local client = clients()[1]

client:farm_mob({
    mob_name   = "fortee thief",
    until_drop = "piercing onyx",
    playstyle  = "Wobbegong Frenzy[Epic] @ enemy | Wand @ enemy | pass",
})

client:go_to_dorm()
```

## Farm a dungeon

Same idea, but for a dungeon: walk in through the sigil, fight to the boss, reset, repeat.

```lua
local client = clients()[1]

client:farm_dungeon({
    until_drop = "goat horns",
    playstyle  = "Trap @ boss | Feint Mass @ aoe | Scarecrow[Epic] @ aoe | "
              .. "Headless Horseman[Epic] @ enemy | pass",

    -- teleport to the doorway, then the sigil. enter_sigil does the tp,
    -- the keypress, and the wait for the zone to load.
    enter = function()
        client:teleport(10561.376, -7543.887, 942.539)
        client:enter_sigil(11248.882, -6661.762, 942.669, { settle = 0.8 })
    end,

    -- once inside, walk up to the boss before the fight kicks off.
    pre_fight = function()
        client:waitfor_mob("lord groff", 15):to()
    end,

    exit_gate = "Start",
})

client:go_to_dorm()
```

## Swap decks for bosses

Watch for a boss, switch to a boss deck and a heavier playstyle, fight, then switch back.

```lua
local client = clients()[1]

while true do
    client:waitfor_freedom()
    if client:boss_nearby() then
        client:equip_deck("Boss")
        client:load_playstyle [[
            Feint @ enemy |
            Feint[Potent] @ enemy |
            Scarecrow[Colossal] @ aoe |
            pass
        ]]
        client:waitfor_battle_finish()
    end
end
```

## Pick a playstyle from what you see

Look at the enemies before committing, then load the playstyle that fits.

```lua
local client = clients()[1]

client:waitfor_battle_start()

local tanky = false
for _, e in ipairs(client:enemies()) do
    if e:is_boss() and e:health() > 100000 then tanky = true end
end

if tanky then
    client:load_playstyle [[
        Feint @ boss | any<blade> @ self |
        any<damage>[Colossal] @ boss | pass
    ]]
else
    client:load_playstyle [[ any<damage>[Epic] @ aoe | pass ]]
end

client:waitfor_battle_finish()
```

## Farm reagents across zones

```lua
local client = clients()[1]

client:farm_reagent{
    name   = "Black Lotus",
    amount = 50,
    zones  = { "Austrilund", "Nordrilund", "Vestrilund" },
}
```

## Two wizards at once

Leave P2 out of questing in the app's settings, then have this script arm each side's combat.

```lua
local p1, p2 = clients()[1], clients()[2]

p2:load_playstyle [[ pass ]]
p2:enable_combat()

p1:load_playstyle [[
    any<damage>[Epic] @ aoe |
    any<damage> @ enemy |
    pass
]]
p1:enable_combat()
```

## Do something to every client

`sky.each` runs the same thing on each one; `sky.mass_key` sends a key to all of them.

```lua
sky.each(clients(), function(c)
    if c:health_pct() < 50 then c:use_potion() end
end)

sky.mass_key(clients(), "W")   -- everyone forward
```
