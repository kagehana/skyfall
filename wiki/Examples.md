# Examples

Whole scripts, start to finish — read them, run them, take what you need. They all open with the [client line](Getting-Started#start-with-a-client).

If you only want the quick path, three wrappers cover the usual grinds:

```lua
local client = clients()[1]

client:kill_boss{ mob = 'Lord Nightshade',
                  playstyle = 'Feint @ boss | any<damage>[Colossal] @ boss | pass' }

client:farm_mob{ mob_name = 'fortee thief', until_drop = 'piercing onyx',
                 playstyle = 'Wand @ enemy | pass' }

client:farm_dungeon{ until_drop = 'goat horns',
                     enter = function() client:enter_sigil(11248, -6661, 942) end }
```

Everything below is the hand-rolled version. More lines, but you can see exactly what's going on and bend it to whatever you're doing.

## Camp a boss for a drop

The wrapper above hides the boring parts: what if the boss isn't up, what if you're low on health. Here's the whole thing in the open — fight, hop to a fresh realm when nobody's home, top off between pulls, stop the moment it drops.

```lua
local client = clients()[1]

local WANT = 'Dragoon'   -- any Dragoon piece; got_drop matches a substring

client:load_playstyle [[
    Feint @ boss |
    any<blade> @ self |
    any<damage>[Colossal] @ boss |
    ?(self.health < 35%) any<heal> @ self |
    pass
]]

client:enable_combat()

while not client:got_drop(WANT) do
    client:waitfor_freedom()

    local boss = client:nearest_boss(2500)

    if not boss then
        client:change_realm()              -- empty realm, try another
    else
        if client:health_pct() < 60 and client:has_potion() then
            client:use_potion()
        end

        boss:to()                          -- land on it to start the fight
        
        client:waitfor_battle_start(15)
        client:waitfor_battle_finish()
    end
end

print(WANT .. ' dropped — done.')
client:go_to_dorm()
```

## Let the fight decide the plan

You don't have to commit to one playstyle. Wait for the battle, look at who's actually in the circle, then load the plan that fits. One boss gets the single-target treatment; a crowd gets AoE.

```lua
local client = clients()[1]

client:waitfor_battle_start()

local foes, boss = client:enemies(), nil
for _, e in ipairs(foes) do
    if e:is_boss() then boss = e end
end

if boss then
    client:load_playstyle [[
        Feint @ boss | any<blade> @ self |
        any<damage>[Colossal] @ boss |
        ?(self.health < 30%) any<heal> @ self | pass
    ]]
elseif #foes >= 3 then
    client:load_playstyle [[ Feint Mass @ aoe | any<damage>[Epic] @ aoe | pass ]]
else
    client:load_playstyle [[ any<damage>[Epic] @ enemy | pass ]]
end

client:enable_combat()              -- load first, then arm — enable_combat is
client:waitfor_battle_finish()      -- what hands the new plan to the engine
```

## Ping you when something good drops

Run this next to whatever's doing the fighting. It checks the drop log after each battle and messages a Discord webhook the first time one of your wanted items shows up — once each, no spam.

```lua
local client = clients()[1]

-- Your own webhook (Discord → Server Settings → Integrations → Webhooks).
-- Treat it like a password; don't paste it into scripts you share.
local WEBHOOK = 'https://discord.com/api/webhooks/XXXXX/YYYYY'
local WATCH   = { 'Amulet of the Sea', 'Brilliant Sapphire', 'Krokopatra Statue' }

local function ping(text)
    client:http_post(WEBHOOK, json.encode({ content = text }))
end

local seen = {}
while true do
    client:waitfor_battle_start()
    client:waitfor_battle_finish()
    for _, item in ipairs(WATCH) do
        if not seen[item] and client:got_drop(item) then
            seen[item] = true
            ping('Got **' .. item .. '**')
        end
    end
end
```

## Babysit an overnight quester

The quester is good, but it can get wedged on a bad teleport. This rides along: it keeps your health up, and if the wizard hasn't changed zones in ten minutes — which almost always means it's stuck — it pokes you.

The trick is using *zone changes* as a heartbeat. Moving means progress; not moving for a long time means trouble.

```lua
local client = clients()[1]

local WEBHOOK     = 'https://discord.com/api/webhooks/XXXXX/YYYYY'
local STUCK_AFTER = 600          -- seconds in one place before we worry

local zone, since = client:zone(), clock()

while true do
    if client:health_pct() < 50 and client:has_potion() then
        client:use_potion()
    end

    local now = client:zone()
    if now ~= zone then
        zone, since = now, clock()                       -- moved on, all good
    elseif clock() - since > STUCK_AFTER then
        client:http_post(WEBHOOK, json.encode({ content = 'stuck in ' .. zone }))
        since = clock()                                  -- re-arm so it pings once
    end

    sleep(15)
end
```

## Run a team off one script

`clients()` is the whole team, and `sky.each` runs the same thing across all of them. Let p1 lead and quest (toggle questing in the app); the rest just need to fight when they get pulled in. Arm everyone once, then keep the group alive in a loop.

```lua
local team = clients()

sky.each(team, function(c)
    c:load_playstyle [[ any<damage>[Epic] @ aoe | any<damage> @ enemy | pass ]]
    c:enable_combat()
    c:enable_dialog()
end)

while true do
    sky.each(team, function(c)
        if c:health_pct() < 45 and c:has_potion() then c:use_potion() end
    end)
    sleep(10)
end
```

## Shrug off a missed click

Anything that drives the game's UI can drop a click once in a while. `sky.retry` just runs it again if it throws — here, up to four tries to get the deck equipped.

```lua
local client = clients()[1]

sky.retry(4, function() client:equip_deck('Boss') end)
```
