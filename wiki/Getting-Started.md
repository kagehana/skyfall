# Getting Started

## The model

Scripts are `.lua` files. SkyFall runs them on a worker thread and bridges the engine's async API so it reads as synchronous — `client:waitfor_battle_finish()` blocks until the fight is actually over, no coroutines or callbacks on your end. Stopping a script interrupts the blocking calls (`sleep`, the `waitfor_*` family) cleanly.

## The one line you always need

```lua
local client = clients()[1]
```

`clients()` is the list of hooked game windows; index it for the wizard you want (`[2]`, `[3]`, … to multibox). Globals — `sleep`, `clock`, `print`, `json`, `sky.*` — don't need it; anything `client:` does.

## Two shapes of call

Globals stand alone and live on the [Standard Library](Standard-Library) page. Everything else is a method on a client, which is the whole [Client API](Client-API).

## Reach for waitfor, not sleep

There's a `waitfor_*` family that blocks on a real signal instead of a guessed duration, each taking an optional timeout in seconds:

```lua
client:waitfor_freedom()         -- idle: no load, dialog, or combat
client:waitfor_battle_start(30)  -- give up after 30s
client:waitfor_window(path)
```

When nothing fits, poll rather than sleeping blind:

```lua
sky.repeat_until(function() return client:in_zone("Triton Avenue") end)
```

## Window paths

The UI calls (`click_window`, `window_text`, `waitfor_window`, …) take a path: window names from the root down to the one you want.

```lua
local DECK = {"WorldView", "DeckConfiguration",
              "DeckConfigurationWindow", "ControlSprite",
              "DeckPage", "DeckName"}

client:click_window(DECK)
```

`client:dump_windows()` prints the live tree when you need to find one.

## Lint and run

```
python -m src.lang.docgen --lint me/bots/your_script.lua   # flags typo'd methods
python skyfall.py                                          # run it from the app
```
