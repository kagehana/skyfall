# SkyFall — The Ideal Wizardry Engine
## Claude Development Guide

Read this before touching anything.

---

## What this project is

**SkyFall** is a game automation engine targeting Wizard101, written in Python. Bot scripts are written in **Lua** (`.lua` files) and run via a Lua bridge. The bridge exposes async wizwalker operations as synchronous Lua globals. Combat is handled natively by a custom engine. Navigation is handled natively with zone map data.

Core surfaces:
- `src/lang/bridge.py` — Lua runtime (lupa), async↔sync thread bridge, sandbox, wired into `skyfall.py` for the bot runner
- `src/lang/client.py` — every `client:*` Lua method (the bulk of the scripting API)
- `src/combat/` — native combat engine (handler, config, effects, math, snapshot, objects)
- `src/nav/client.py` — native entity client
- `src/nav/navigator.py` — `to_zone()` native zone-traversal engine; gate, world-hop and interactive-teleporter logic, with traversal data in `src/nav/data/`

---

## Running the project

```
python skyfall.py                       # launch the bot UI
test.bat                                # run the test suite (no game needed)
```

`test.bat` runs `py -3.13 -m pytest tests/ -v` and forwards extra args (e.g. `test.bat -k combat`, `test.bat -x`).

**Always run the test suite after making any change.**

---

## Releasing (CalVer)

Versions follow **CalVer `YYYY.M.D`** (calendar versioning — year.month.day, no
zero-padding), e.g. `2026.6.3`. The Windows file resource carries a 4-tuple with a
trailing `.0` build field, e.g. `2026.6.3.0`.

A release bumps the version in two files, builds the binary, then publishes a GitHub
release tagged with the bare CalVer string:

1. **Bump the version** (done by hand — there is no release script):
   - `pyproject.toml` → `version = "YYYY.M.D"`
   - `version_info.txt` → `filevers`/`prodvers` tuple `(YYYY, M, D, 0)` and the
     `FileVersion`/`ProductVersion` strings `YYYY.M.D.0`
2. **Build the binary** (onefile PyInstaller → `dist/SkyFall.exe`):
   ```
   uv run --group dev pyinstaller --noconfirm --clean skyfall.spec
   ```
   If `uv` is unavailable, run the spec directly: `py -3.13 -m PyInstaller --noconfirm --clean skyfall.spec`
3. **Commit** the version bump, then **publish** the release — tag and title are the
   bare CalVer string, the only asset is the raw `dist/SkyFall.exe`:
   ```
   gh release create YYYY.M.D dist/SkyFall.exe --title "YYYY.M.D" --generate-notes --notes-start-tag <prev-tag>
   ```

---

## Codebase structure

```
src/
    lang/
        bridge.py        — LuaBridge class: run .lua text or load .lua files,
                           async↔sync bridge, sandbox, hot reload, error surfacing
        client.py        — every `client:*` Lua-exposed method (the scripting API)
        docgen.py        — Lua script linter (lint_script)
        stdlib.lua       — sky.* helpers injected into every Lua runtime
    combat/
        config.py        — CombatConfig data classes + playstyle parser (parse_playstyle)
        effects.py       — spell effect flattening, requirement matching, hanging counts
        handler.py       — NativeCombat: round loop, card selection, enchanting,
                           gambit/clear/echo/swap, retry logic
        objects.py       — school ID constants, effect queries, stat helpers
        math.py          — combat damage math, cache utilities, simulation helpers
        snapshot.py      — Live Combat panel snapshot builder (Stats tab)
    nav/
        client.py        — EntityClient: entity queries, closest-entity, tp helpers, stats
        navigator.py     — to_zone(): native traversal engine (BFS + gate handlers)
        scraper.py       — WAD scraper for traversal data
        wad_scraper.py   — CLI: scrape teleport/gate data into nav/data/
        data/            — traversal data files (zoneMap.txt, gates_list.txt, etc.)
    objprop/
        reader.py        — little-endian bit reader for KI's ObjectProperty format
        typelist.py      — wiztype type-list loader (TypeList/TypeDef/Property)
        serializer.py    — native BINd deserializer (port of katsuba, ISC); deep/
                           shallow, zlib, recover_unknown (walks unregistered
                           classes to extract known nested objects)
    gui/
        tabs.py          — all build_*_tab functions (split-target for Phase 3b)
        main.py, dialog.py, theme.py, widgets.py, ...
    factory.py           — make_combat_handler(), delegate_combat_configs(), default_config
    questing.py          — quest automation loop
    spawns.py            — ZoneSpawns: offline reagent/spawn node positions from
                           zone WAD (spawnData+pathData+pathNodeData) + manifest
    launcher.py          — Wizard101 client launcher (replaces wizlaunch)
    autopet.py, camera.py, dance.py, deck.py, drops.py, inputs.py, locale.py,
    paths.py, screen.py, settings.py, sigil.py, teleport.py,
    utils.py, viewer.py, wad_icons.py
libs/
    wizwalker/           — custom wizwalker fork (must be installed, see below)
me/bots/
    questing.lua         — main questing script (Lua)
tests/                   — pytest suite (test_skyfall.py, test_patches.py)
```

---

## Lua scripting

Bot scripts are `.lua` files. The bridge registers all bot operations as Lua globals.

**Style:** all Lua scripts should be aesthetically pleasing, optimized, and minimalistic while keeping functionality. Concretely:
- Hoist invariants out of loops (e.g. `load_playstyle` called once, not per iteration).
- Prefer `waitfor_*` helpers over hand-rolled poll/sleep loops.
- Use short, aligned `local` constants at the top in lieu of magic strings.
- No decorative banner comments, no narration of obvious steps, no debug `print`s in finished scripts.
- Chain calls when it reads cleanly (`client:waitfor_mob(x, 15):to()`).
- Use the native `json` global instead of hand-rolled string escaping.

**Script preamble:** any Lua script that calls methods on a client (`client:teleport(...)`, `client:waitfor_mob(...)`, etc.) must start with:

```lua
local client = clients()[1]
```

`clients()` returns the hooked-client list; index `[1]` is the primary client. Always include this at the top of proposed scripts when at least one `client:` method is used. Skip it only for scripts that exclusively use globals (`sleep`, `print`, etc.) and never touch a `client:` method.

**Real globals** (no `client:` prefix): `sleep(secs)`, `clock()`, `clients()`, `print(...)`, and the `sky.*` stdlib (`sky.retry`, `sky.repeat_until`, `sky.times`, `sky.with_timeout`, `sky.dump`, `sky.log`, `sky.each`, `sky.mass_key`, `sky.any`).

**Common client methods** (all require `client:` prefix; see [src/lang/client.py](src/lang/client.py) for the full surface):

| Method | Description |
|---|---|
| `client:waitfor_freedom([w])` | wait until not in combat/dialog/loading |
| `client:waitfor_battle_start([w])` / `:waitfor_battle_finish([w])` | battle lifecycle |
| `client:waitfor_dialog([w])` | wait for an advance-dialog button |
| `client:waitfor_window(path, [w])` | wait for a UI window |
| `client:waitfor_zone(name, [w])` / `:waitfor_zone_change([cur], [w])` | zone waits |
| `client:waitfor_entity(name, [w], [max])` | any entity (NPCs, scenery, players) |
| `client:waitfor_mob(name, [w], [max])` | combat mob only (NPCBehavior + is_mob) |
| `client:send_key(key, [secs])` | press a key |
| `client:click_window(path)` / `:window_text(path)` / `:window_visible(path)` | UI ops |
| `client:boss_nearby([dist])` / `:in_zone(name)` / `:in_combat()` | predicates |
| `client:load_playstyle(cfg)` / `:enable_combat()` / `:disable_combat()` | combat control |
| `client:enable_dialog()` / `:disable_dialog()` | auto-advance dialog watcher |
| `client:teleport(x,y,z)` / `:navigate(x,y,z)` / `:to_zone(name)` | movement |
| `client:go_through_gate(name, ...)` / `:list_gates()` | gate handling |
| `client:reagent_nodes(name)` | offline reagent spawn-node `{x,y,z}` list for the current zone (from WAD) |
| `client:reagent_spawns()` | every reagent in the current zone as flat `{name,x,y,z}` rows |
| `client:reagents_present([dist])` | live reagents in range as `{name,x,y,z}`, matched by template ID (reliable, unlike name) |
| `client:farm_reagent{name=,amount=,zones=,hop_realms=}` | full farm loop: sweep node(s) across `zones` in order, harvest, close up to the first zone, hop realm; `name` filters to one reagent, `amount` stops at N collected. Also callable positionally: `farm_reagent([name])` |
| `client:change_realm()` | hop to a different game realm so depleted spawns repopulate |
| `client:zone_chunks()` | nav-mesh sweep grid `{x,y,z}` for the current zone (whole-zone fallback) |
| `client:health()` / `:mana()` / `:energy()` / `:zone()` | stat / state queries |
| `client:dump_entities([dist], [needle])` / `:dump_npcs([dist])` | diagnostics |

**Script example:**
```lua
local client = clients()[1]

local DECK = {"WorldView","DeckConfiguration","DeckConfigurationWindow",
               "ControlSprite","DeckPage","DeckName"}

while true do
    client:waitfor_freedom()
    if client:boss_nearby() then
        client:send_key("P")
        client:waitfor_window(DECK)
        while not client:window_text(DECK):find("Boss Deck") do
            client:click_window(NEXTDECK)
            sleep(0.7)
        end
        client:load_playstyle [[
            Feint @ enemy |
            Feint[Potent] @ enemy |
            Scarecrow[Colossal] @ enemy |
            pass
        ]]
        client:waitfor_battle_finish()
    end
end
```

---

## Combat playstyle format

Playstyle configs are pipe-separated priority lists. Pass as a Lua multiline string:

```lua
load_playstyle [[
    Feint @ enemy |
    any<damage>[Colossal] @ enemy |
    ?(self.health < 25%) Satyr @ self |
    pass
]]
```

**Spell syntax:**
- `SpellName @ target` — named spell
- `SpellName[Enchant] @ target` — with enchant
- `any<req> @ target` — template (matches any card satisfying requirement)
- `any<req1&req2> @ target` — multi-requirement template
- `SpellA @ target & EnchantB @ spell(any<blade>)` — `&` chains casts this turn
- `{1} Spell @ target` — round-specific
- `?(self.health < 25%) Spell @ target` — conditional
- `pass` — skip turn
- `willcast` — cast pet card

**Targets:** `self`, `enemy`, `enemy(N)`, `boss`, `ally`, `aoe`, `enemies`, `allies`, `spell(any<req>)`

**Requirements:** `damage`, `heal`, `blade`, `trap`, `ward`, `charm`, `aura`, `global`, `prism`, `pierce`, `dispel`, `dot`, `hot`, `mod_damage`, `aoe`, `damage&aoe`

---

## Adding a new bot function

1. Write an `async def` in the appropriate module
2. Register it in the bridge setup in `skyfall.py`:
   ```python
   bridge.register("my_func", my_async_func)
   ```
3. It becomes available as `my_func()` in all Lua scripts
4. Add a test in `tests/`

---

## Combat engine — how to extend

All combat code lives in `src/combat/`. The pipeline is:

1. `config.py` parses the playstyle string → `CombatConfig`
2. `handler.py` `NativeCombat.handle_round()` runs each round
3. `effects.py` provides `card_matches_reqs()` for template spell matching

To add a new spell type requirement:
1. Add it to `is_req_satisfied()` in `effects.py`
2. Add it to the `_REQ_TO_CAT` dict if it maps to a hanging category

---

## wizwalker API quick reference

**`combat_participant.py`**
- `owner_id_full()` — not `owner_id()`
- `team_id()` — not `team()`
- `stunned()` — returns int, truthy check works
- `player_health()` / `max_player_health()`
- `hanging_effects()` — not `spell_effects()`
- `pip_count()` → `.generic_pips()` / `.power_pips()` / `.shadow_pips()`

**`client_object.py`**
- `fetch_npc_behavior_template()` — not `npc_behavior_template()`
- `object_name()` — entity name for world filtering

**`behavior_template.py`**
- `boss_mob()` — not `boss()`

**SpellEffects enum — key names:**
- Damage: `damage`, `damage_no_crit`, `steal_health`
- Heal: `heal`, `heal_percent`
- Hanging: `modify_incoming_damage`, `modify_outgoing_damage`, `absorb_damage`
- Over-time: `damage_over_time`, `heal_over_time`
- Aura: `modify_accuracy`, `modify_power_pip_chance`, `crit_boost`, `crit_block`
- Prism: `modify_incoming_damage_type`

**EffectTarget enum — key names:**
- `enemy_single`, `multi_target_enemy`, `enemy_team`, `enemy_team_all_at_once`
- `friendly_single`, `multi_target_friendly`, `self`, `friendly_team`
- `target_global`

**School IDs:**

| School | ID |
|---|---|
| Fire | 2343174 |
| Ice | 72777 |
| Storm | 83375795 |
| Myth | 2448141 |
| Life | 2330892 |
| Death | 78318724 |
| Balance | 1027491821 |

---

## Test suite

```
test.bat
```

**Run after every change.** No game needed.

Key coverage areas (in `tests/test_skyfall.py`):
- Lua bridge: runtime, sandbox (incl. `python.eval` / dunder-walk escapes), stop signal, error callback
- Combat config parsing: every playstyle syntax form
- `delegate_combat_configs`: multi-client config splitting
- `EntityClient`: health/mana/potion helpers (mocked)
- Zone graph: data loading, BFS path finding


`tests/test_patches.py` covers `NativeCombat` round-handling. Some assertions in `TestNativeCombat` are currently out of sync with the handler's spell-selection flow — fix or prune before next major release.

---

## wizwalker fork

The upstream `wizwalker` package may be missing attributes the engine needs. The
custom fork lives at `libs/wizwalker`. `uv sync` installs it as a workspace member.

**Install it editable so `libs/wizwalker` is the single source of truth** — otherwise
a stale *copy* lands in site-packages and `py -3.13 skyfall.py` imports that instead of
your edits (this exact trap cost a whole debug cycle):

```
py -3.13 -m pip install -e libs/wizwalker --no-deps
```

Verify with `py -3.13 -c "import wizwalker, os; print(os.path.dirname(wizwalker.__file__))"`
— it must resolve to `libs/wizwalker/wizwalker`, not site-packages. After editing
Python you must fully restart SkyFall (Lua hot-reload won't reimport it); the game
client does **not** need restarting if the patterns still match the running client.

---

## Updating memory offsets / hook patterns after a client patch

When a Wizard101 patch breaks login or hooking, the byte signatures to refresh live in:

- `src/launcher.py` — `_LOGIN_PATTERN` (skyfall-specific auto-login command dispatcher;
  scanned with `_scan_wild`). **Not present in any wizwalker fork.**
- `libs/wizwalker/.../memory/handler.py` — `AUTOBOT_PATTERN` + `AUTOBOT_SIZE` (the code
  cave the hook handler anchors to; fails first, before any individual hook).
- `libs/wizwalker/.../memory/hooks.py` — `PlayerHook`, `ClientHook`, `RootWindowHook`,
  `RenderContextHook`, `QuestHook`, `MovementTeleportHook`.

**Source of current patterns:** `LaurenzLikeThat/wizwalker`, default branch `development`
(a fork of `Deimos-Wizard101/wizwalker`). When given a fork/PR to study:

- **Diff per-symbol, not whole-file.** Our fork has diverged heavily (extra features,
  hex-case, line-wrapping), so a raw `diff` is mostly noise. Compare the specific
  `pattern =` / `AUTOBOT_*` / `bytecode_generator` bodies.
- **Patterns are raw bytestrings fed to a regex engine.** In `rb"\x48\x8B\x01"`, `\x48`
  is a regex hex escape, `.` matches any one byte, `....` is four wildcard bytes. So a
  pattern can still *locate* a function even after surrounding bytes shift.
- **Two failure modes — check both:**
  1. *Pattern doesn't locate* → `pattern_scan` returns None → clean "Pattern … failed"
     error. The break is almost always a hardcoded **stack-displacement byte** (e.g.
     `\x24\x38` → wildcard `\x24.`, or `sub rsp,20` → `sub rsp,30`). Wildcard it.
  2. *Pattern locates but the client CRASHES on hook* (process dies, then SkyFall says
     "Client must be running"). The pattern matched but `bytecode_generator` restores a
     **wrong hardcoded original instruction** — usually a changed **base register**
     (e.g. RootWindowHook `[r13+D8]` → `[r15+D8]`: ModRM `\x85`/`\x8D` → `\x87`/`\x8F`).
     Diff the `bytecode_generator` bytes, not just the `pattern =` line.
- **Verify against LIVE client memory — don't trust the diff alone.** With the client
  running, read the `WizardGraphicalClient.exe` module (OpenProcess + ReadProcessMemory)
  and `re.finditer(pattern, data, re.DOTALL)`: the correct pattern matches **exactly
  once**. For crash-class bugs, also read the original bytes at the hook site and confirm
  they equal what `bytecode_generator` restores.

After porting, run `test.bat` and bump/build/release per the CalVer section.
