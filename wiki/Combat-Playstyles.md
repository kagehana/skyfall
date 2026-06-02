# Combat Playstyles

Combat is driven by a **playstyle**: a pipe-separated priority list you hand to
`client:load_playstyle(...)`. Each round, the native engine scans the lines
top-to-bottom and casts the first move it can satisfy with the current hand and
pips.

```lua
client:load_playstyle [[
    Feint @ enemy |
    any<damage>[Colossal] @ enemy |
    ?(self.health < 25%) Satyr @ self |
    pass
]]
```

Pass it as a Lua multiline string (`[[ … ]]`). Lines are separated by `|`;
whitespace and newlines around each line are ignored.

## Moves

| Form | Meaning |
|---|---|
| `SpellName @ target` | Cast a named spell |
| `SpellName[Enchant] @ target` | Cast with an enchant applied first |
| `any<req> @ target` | Template — cast any card matching the requirement |
| `any<req1&req2> @ target` | Template with multiple requirements |
| `pass` | Skip the turn |
| `willcast` | Cast the pet's may-cast card |
| `petcast SpellName @ target` | Queue a specific pet may-cast |

### Chaining with `&`

Cast several spells in one turn, left to right:

```
Feint @ enemy & Sharpen @ spell(any<blade>) & Storm Lord @ aoe
```

### Round-specific moves

Prefix with `{n}` to apply a line only on round *n*:

```
{1} Tower Shield @ self |
{2} Stun Block @ self |
any<damage>[Colossal] @ enemy
```

## Targets

| Target | Selects |
|---|---|
| `self` | yourself |
| `enemy` | the default/first enemy |
| `enemy(N)` | the N-th enemy (1-indexed) |
| `boss` | the boss in the fight |
| `ally` | a teammate |
| `aoe` | all enemies (multi-target) |
| `enemies` / `allies` | the whole enemy / friendly team |
| `spell(any<req>)` | a card already in play matching the requirement (e.g. enchant a blade) |
| `select(...)` | an explicitly selected target |

## Requirements (for `any<…>` and `spell(any<…>)`)

`damage`, `heal`, `blade`, `trap`, `ward`, `charm`, `aura`, `global`, `prism`,
`pierce`, `dispel`, `dot` (`damage_over_time`), `hot` (`heal_over_time`),
`mod_damage` (a damage enchant), `aoe`, and the compound `damage&aoe`.

```
any<blade> @ self |
any<damage&aoe> @ aoe |
any<heal> @ ally
```

## Conditions

Gate a line with `?(…)`. The expression is `subject.attr OP value`, where
`subject` is `self`, `enemy`, `boss`, or `ally`; `attr` is `health` or `mana`;
`OP` is one of `<  <=  >  >=  ==  !=`; and a trailing `%` compares against the
max (percentage).

```
?(self.health < 25%) Satyr @ self |
?(enemy.health > 100000) Feint @ enemy |
?(self.mana < 50) pass
```

## Free actions

These don't consume the turn — the engine applies them and keeps scanning the
list. They can be conditional or appear as their own line.

| Directive | Effect |
|---|---|
| `focus: <school>` (or `setfocus <school>`) | Swap the focus school mid-fight |
| `pip: <school>` (or `setpip <school>`) | Assign unspent pips to a school via the pip panel |
| `draw(n)` | Draw treasure cards |

A top-level `focus = <school>` / `pip = <school>` line sets the config-wide
default applied when the playstyle activates.

## Tips

- End every playstyle with `pass` so the engine always has a legal fallback.
- Put setup (`Feint`, blades, shields) above your finishers — first match wins.
- Use [`LuaCombatant`](Combatant-API) reads to pick a playstyle *before* the
  fight, and `?(…)` conditions to adapt *within* it.
