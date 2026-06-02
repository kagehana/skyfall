# Combatant API — `LuaCombatant`

A `LuaCombatant` is a participant in the **active battle** — distinct from a
[`LuaMob`](Mob-API) (a world entity). You get them from the combat lists:

```lua
local client = clients()[1]

for _, e in ipairs(client:enemies()) do
    print(e:name(), e:health() .. "/" .. e:max_health(), e:school())
end

local me = client:allies()[1]
print("pips:", me:pips(), "power:", me:power_pips())
```

These are most useful for **conditional playstyles** and diagnostics — reading
HP, pips, school, and status effects to decide what to cast.

```lua
local boss = nil
for _, e in ipairs(client:enemies()) do
    if e:is_boss() then boss = e end
end
if boss and boss:health() > 50000 then
    client:load_playstyle("Feint @ enemy | Scarecrow[Colossal] @ enemy | pass")
end
```

Most fields beyond vitals/pips (shadow, archmastery, polymorph, round-state
flags) mirror the raw combat-participant memory and are there for advanced
scripts; the everyday set is **vitals, pips, school, and the `is_*` checks**.

---

## Full method reference

<!-- AUTOGEN:LuaCombatant START — generated from source; do not edit. Run: python -m src.lang.docgen --emit -->
#### Identity

| Method | Signature | Description |
|---|---|---|
| `name` | `() -> str` | Combatant name |
| `owner_id` | `() -> int` | Owning object id |
| `template_id` | `() -> int` | Template id |
| `zone_id` | `() -> int` | Zone id |
| `team_id` | `() -> int` | Current team id |
| `original_team` | `() -> int` | Team id at battle start |
| `side` | `() -> str` | Team side as a string |

#### Vitals & resources

| Method | Signature | Description |
|---|---|---|
| `health` | `() -> int` | Current health |
| `max_health` | `() -> int` | Maximum health |
| `mana` | `() -> int` | Current mana |
| `max_mana` | `() -> int` | Maximum mana |
| `level` | `() -> int` | Combatant level |
| `mob_level` | `() -> int` | Underlying mob level |
| `pips` | `() -> int` | Normal pip count |
| `power_pips` | `() -> int` | Power pip count |
| `shadow_pips` | `() -> int` | Shadow pip count |
| `pips_suspended` | `() -> bool` | True if pip gain is suspended |

#### Classification

| Method | Signature | Description |
|---|---|---|
| `is_boss` | `() -> bool` | True if a boss |
| `is_player` | `() -> bool` | True if a player wizard |
| `is_monster` | `() -> bool` | True if a monster/NPC |
| `is_minion` | `() -> bool` | True if a summoned minion |
| `is_dead` | `() -> bool` | True if defeated |
| `is_stunned` | `() -> bool` | True if stunned |
| `is_accompany_npc` | `() -> bool` | True if an accompanying henchman NPC |

#### Combat stats

| Method | Signature | Description |
|---|---|---|
| `school` | `() -> str` | Primary magic school name |
| `stat_damage` | `() -> float` | Outgoing damage stat |
| `stat_resist` | `() -> float` | Damage resist stat |
| `stat_pierce` | `() -> float` | Armor-pierce stat |
| `base_spell_damage` | `() -> int` | Base flat spell damage |
| `accuracy_bonus` | `() -> float` | Accuracy bonus |
| `max_hand_size` | `() -> int` | Maximum cards in hand |
| `deck_fullness` | `() -> float` | Fraction of the deck remaining |

#### Archmastery

| Method | Signature | Description |
|---|---|---|
| `archmastery_points` | `() -> float` | Current archmastery points |
| `max_archmastery_points` | `() -> float` | Archmastery points needed per pip |
| `archmastery_school` | `() -> int` | Archmastery school id |
| `archmastery_flags` | `() -> int` | Archmastery flag bits |

#### Shadow

| Method | Signature | Description |
|---|---|---|
| `shadow_creature_level` | `() -> int` | Current shadow-creature level |
| `past_shadow_creature_level` | `() -> int` | Previous shadow-creature level |
| `shadow_creature_level_count` | `() -> int` | Shadow-creature level counter |
| `rounds_since_shadow_pip` | `() -> int` | Rounds since the last shadow pip |
| `shadow_pip_rate_threshold` | `() -> float` | Shadow pip rate threshold |
| `shadow_spells_disabled` | `() -> bool` | True if shadow spells are disabled |
| `shadow_pact_target` | `() -> int` | Shadow-pact target id |

#### Status effects

| Method | Signature | Description |
|---|---|---|
| `mindcontrolled` | `() -> bool` | True if mind-controlled |
| `confused` | `() -> bool` | True if confused |
| `confused_target` | `() -> bool` | True if the chosen target is randomized by confusion |
| `confusion_trigger` | `() -> int` | Confusion trigger value |
| `untargetable` | `() -> bool` | True if currently untargetable |
| `untargetable_rounds` | `() -> int` | Rounds remaining untargetable |
| `restricted_target` | `() -> bool` | True if targeting is restricted |
| `hide_current_hp` | `() -> bool` | True if HP is hidden |
| `backlash` | `() -> int` | Current backlash counter |
| `past_backlash` | `() -> int` | Previous backlash counter |

#### Round & turn state

| Method | Signature | Description |
|---|---|---|
| `auto_pass` | `() -> bool` | True if set to auto-pass this round |
| `vanish` | `() -> bool` | True if vanished this round |
| `my_team_turn` | `() -> bool` | True if it is this combatant's team's turn |
| `exit_combat` | `() -> bool` | True if flagged to leave combat |
| `rounds_dead` | `() -> int` | Rounds spent dead |
| `clue` | `() -> int` | Clue value (planning hint) |
| `aura_turn_length` | `() -> int` | Remaining aura turns |
| `planning_phase_pip_aquired_type` | `() -> int` | Pip type acquired during planning |

#### Polymorph

| Method | Signature | Description |
|---|---|---|
| `polymorph_turn_length` | `() -> int` | Remaining polymorph turns |
| `polymorph_spell_template_id` | `() -> int` | Polymorph spell template id |

#### Position in circle

| Method | Signature | Description |
|---|---|---|
| `rotation` | `() -> float` | Rotation around the combat circle |
| `radius` | `() -> float` | Radius from circle center |
| `subcircle` | `() -> int` | Subcircle index |
| `minion_sub_circle` | `() -> int` | Minion subcircle index |

#### Flags & PvP

| Method | Signature | Description |
|---|---|---|
| `pvp` | `() -> bool` | True if a PvP match |
| `raid` | `() -> bool` | True if a raid battle |
| `combat_trigger_ids` | `() -> int` | Combat trigger id bits |
| `pet_combat_trigger` | `() -> int` | Pet combat trigger value |
| `pet_combat_trigger_target` | `() -> int` | Pet combat trigger target |
| `stunned_display` | `() -> bool` | Stun display flag |
| `mindcontrolled_display` | `() -> bool` | Mind-control display flag |
| `confusion_display` | `() -> bool` | Confusion display flag |
| `hide_pvp_enemy_chat` | `() -> bool` | Hide-PvP-enemy-chat flag |
| `ignore_spells_pvp_only_flag` | `() -> bool` | Ignore PvP-only spells flag |
| `ignore_spells_pve_only_flag` | `() -> bool` | Ignore PvE-only spells flag |
| `saved_primary_magic_school_id` | `() -> int` | Saved primary school id (pre-polymorph) |
| `player_time_updated` | `() -> bool` | Player-timer updated flag |
| `player_time_eliminated` | `() -> bool` | Player eliminated on timer flag |
| `player_time_warning` | `() -> bool` | Player timer warning flag |
<!-- AUTOGEN:LuaCombatant END -->
