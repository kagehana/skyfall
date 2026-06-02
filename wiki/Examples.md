# Examples

Complete, runnable scripts. Every script that touches a client opens with the
[preamble](Getting-Started#the-preamble).

## Farm a mob until a drop

```lua
local client = clients()[1]

client:farm_mob({
    mob_name   = "fortee thief",
    until_drop = "piercing onyx",
    playstyle  = "Wobbegong Frenzy[Epic] @ enemy | Wand @ enemy | pass",
})

client:go_to_dorm()
```

## Farm a dungeon (sigil entry → fight → reset)

```lua
local client = clients()[1]

client:farm_dungeon({
    until_drop = "goat horns",
    playstyle  = "Trap @ boss | Feint Mass @ aoe | Scarecrow[Epic] @ aoe | "
              .. "Headless Horseman[Epic] @ enemy | pass",

    -- waypoint teleport, then the sigil; enter_sigil does tp + key + zone wait
    enter = function()
        client:teleport(10561.376, -7543.887, 942.539)
        client:enter_sigil(11248.882, -6661.762, 942.669, { settle = 0.8 })
    end,

    -- walk up to the boss before combat begins
    pre_fight = function()
        client:waitfor_mob("lord groff", 15):to()
    end,

    exit_gate = "Start",
})

client:go_to_dorm()
```

## Boss-deck swap loop

Detect a boss, swap to a boss deck, arm a heavier playstyle, fight, repeat.

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

## Conditional playstyle from live combat state

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

## Reagent farm across zones

```lua
local client = clients()[1]

client:farm_reagent{
    name   = "Black Lotus",
    amount = 50,
    zones  = { "Austrilund", "Nordrilund", "Vestrilund" },
}
```

## Duo: exclude P2 from questing, arm both sides

```lua
-- In Settings → Questing, set "Exclude from Questing" on P2 so P1's Quester
-- ignores it. This script just arms each side's combat.
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

## Multi-client orchestration with `sky`

```lua
sky.each(clients(), function(c)
    if c:health_pct() < 50 then c:use_potion() end
end)

sky.mass_key(clients(), "W")   -- everyone walks forward
```
