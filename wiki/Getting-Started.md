# Getting Started

## The script model

A SkyFall bot script is a `.lua` file. The engine runs it on a dedicated thread
and bridges every game operation so your Lua code reads as **synchronous** —
there is no `await`, no callbacks. A call like `client:waitfor_battle_finish()`
simply blocks until the battle is over.

Scripts can be stopped at any time. Blocking calls (`sleep`, every `waitfor_*`)
cooperate with the stop signal, so a stopped script unwinds cleanly.

## The preamble

Any script that calls a method on a client must first grab one:

```lua
local client = clients()[1]
```

`clients()` returns the hooked-client list; `[1]` is the primary client. Skip
the preamble only for scripts that exclusively use globals (`sleep`, `print`,
`sky.*`) and never touch a `client:` method.

For multiboxing, index further: `clients()[2]`, `clients()[3]`, … or iterate
with [`sky.multi.each`](Standard-Library).

## Globals vs. client methods

Two kinds of calls exist:

- **Globals** — no receiver. `sleep(secs)`, `clock()`, `clients()`, `print(...)`,
  `json.encode/decode`, and the whole `sky.*` standard library. See the
  [Standard Library](Standard-Library) page.
- **Client methods** — `client:method(...)`. These are the bulk of the API and
  always take the `client:` receiver. See [Client API](Client-API).

```lua
print("starting")              -- global
sleep(1)                       -- global
client:send_key("W", 0.5)      -- client method
```

## Waiting on the game

Prefer the `waitfor_*` family over hand-rolled `sleep` loops — they poll an
observable signal and respect an optional timeout (`window`, in seconds):

```lua
client:waitfor_freedom()           -- until idle (no load/dialog/combat)
client:waitfor_battle_start(30)    -- until combat, max 30s
client:waitfor_window(SOME_PATH)   -- until a UI window appears
```

When no helper fits, use the polling recipes from the stdlib rather than a raw
loop:

```lua
sky.repeat_until(function() return client:in_zone("Triton Avenue") end)
```

## UI window paths

Window-related methods (`click_window`, `window_text`, `waitfor_window`, …) take
a **path**: a Lua array of window names from the root down to the target.

```lua
local DECK = {"WorldView", "DeckConfiguration",
              "DeckConfigurationWindow", "ControlSprite",
              "DeckPage", "DeckName"}

client:waitfor_window(DECK)
print(client:window_text(DECK))
```

Use `client:dump_windows()` to print the live window tree when you need to find
a path.

## Linting a script

The bridge ships a linter that flags unknown client methods and `sky.*`
recipes before you run:

```
python -m src.lang.docgen --lint me/bots/questing.lua
```

## Running

```
python skyfall.py        # launch the bot UI, load and run scripts there
```
