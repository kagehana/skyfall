# Combat Playstyles

You don't script fights move by move. Instead you hand the combat engine a **playstyle** — a ranked list of what you'd like to do — and every round it goes down the list and casts the first thing it can pull off. You pass it to `client:load_playstyle(...)`.

```lua
client:load_playstyle [[
    Feint @ enemy |
    any<damage>[Colossal] @ enemy |
    ?(self.health < 25%) Satyr @ self |
    pass
]]
```

Lines split on `|`; whitespace around them is ignored, so format it however reads best.

## Moves

| What you write | What it means |
|---|---|
| `SpellName @ target` | cast a spell by name |
| `SpellName[Enchant] @ target` | enchant it first, then cast |
| `any<req> @ target` | cast *any* card that matches the requirement |
| `any<req1&req2> @ target` | …matching more than one |
| `pass` | do nothing this turn |
| `willcast` | let the pet cast its may-cast |
| `petcast SpellName @ target` | ask the pet for a specific may-cast |

### Doing several things in one turn

Chain with `&` and they fire left to right:

```
Feint @ enemy & Sharpen @ spell(any<blade>) & Storm Lord @ aoe
```

### Pinning a move to a round

Put `{n}` in front and the line only applies on round *n* — handy for opening turns:

```
{1} Tower Shield @ self |
{2} Stun Block @ self |
any<damage>[Colossal] @ enemy
```

## Targets

| Target | Who it hits |
|---|---|
| `self` | you |
| `enemy` | the first enemy |
| `enemy(N)` | the Nth enemy (counting from 1) |
| `boss` | the boss |
| `ally` | a teammate |
| `aoe` | every enemy at once |
| `enemies` / `allies` | the whole enemy / friendly side |
| `spell(any<req>)` | a card already on the board — e.g. to enchant a blade you've cast |
| `select(...)` | a target you've picked explicitly |

## Requirements

These are what goes inside `any<...>` (and `spell(any<...>)`):

`damage`, `heal`, `blade`, `trap`, `ward`, `charm`, `aura`, `global`, `prism`, `pierce`, `dispel`, `dot`, `hot`, `mod_damage`, `aoe`, and the combined `damage&aoe`.

```
any<blade> @ self |
any<damage&aoe> @ aoe |
any<heal> @ ally
```

## Conditions

Gate any line behind `?(...)`. The check is `subject.attr OP value`, where `subject` is `self`, `enemy`, `boss`, or `ally`; `attr` is `health` or `mana`; `OP` is `< <= > >= == !=`; and a trailing `%` means 'as a percentage of max.'

```
?(self.health < 25%) Satyr @ self |
?(enemy.health > 100000) Feint @ enemy |
?(self.mana < 50) pass
```

## Free actions

A few directives don't burn your turn — the engine does them and keeps reading down the list. They can stand on their own line or sit behind a condition.

| Directive | What it does |
|---|---|
| `focus: <school>` (or `setfocus <school>`) | switch your focus school mid-fight |
| `pip: <school>` (or `setpip <school>`) | spend loose pips into a school via the pip panel |
| `draw(n)` | draw treasure cards |

A top-level `focus = <school>` or `pip = <school>` sets the default for the whole playstyle when it loads.

## A few habits worth keeping

- End every playstyle with `pass`, so there's always something legal to fall back on.
- Put setup first — feints, blades, shields — and your finishers lower down. First match wins, so order is your priority.
- Pick a playstyle *before* the fight using what you can see ([Combatant API](Combatant-API)), and adapt *during* it with `?(...)` conditions.
