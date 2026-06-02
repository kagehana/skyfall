# Getting Started

## How a script runs

A script is just a `.lua` file. SkyFall runs it on its own thread and hides all the async plumbing, so you write everything as if it happens top to bottom, one line after the next. No `await`, no callbacks. When you call `client:waitfor_battle_finish()`, the script really does stop on that line until the fight ends, then keeps going.

You can stop a script whenever you want, and the blocking calls — `sleep` and anything that starts with `waitfor_` — know how to drop out cleanly when you do.

## Start with a client

Just about everything goes through a client, so the first line of nearly every script is:

```lua
local client = clients()[1]
```

`clients()` is the list of hooked game windows; `[1]` is your main wizard. Running more than one? They're `[2]`, `[3]`, and so on. The only scripts that skip this line are the ones that never touch a client — pure `print`/`sleep` stuff.

## Two kinds of calls

Some things are globals — you call them on their own:

```lua
sleep(1)
print("hello")
```

Everything else hangs off a client with a colon:

```lua
client:send_key("W", 0.5)
client:teleport(x, y, z)
```

The globals are over on the [Standard Library](Standard-Library) page. The client methods are the whole [Client API](Client-API).

## Waiting on the game

You'll wait a lot — for a fight to start, a zone to load, a window to pop up. Reach for `waitfor_*` before you reach for `sleep`. Those watch for the real thing and take an optional timeout in seconds:

```lua
client:waitfor_freedom()         -- until nothing's happening
client:waitfor_battle_start(30)  -- give it 30 seconds
client:waitfor_window(path)      -- until a window appears
```

A `sleep(2)` is a guess about how long something takes; a `waitfor` actually knows. When nothing fits what you're waiting on, poll for it instead of sleeping blind:

```lua
sky.repeat_until(function() return client:in_zone("Triton Avenue") end)
```

## Clicking around the UI

Anything that touches the game's interface — clicking a button, reading a label, waiting on a window — takes a **window path**: a list of window names from the top of the tree down to the one you want.

```lua
local DECK = {"WorldView", "DeckConfiguration",
              "DeckConfigurationWindow", "ControlSprite",
              "DeckPage", "DeckName"}

client:waitfor_window(DECK)
print(client:window_text(DECK))
```

Don't know the path? `client:dump_windows()` prints the live tree so you can dig it out.

## Lint before you run

There's a linter that catches misspelled methods and bad `sky.*` calls before you ever load the thing:

```
python -m src.lang.docgen --lint me/bots/your_script.lua
```

## Running

```
python skyfall.py
```

Then load and run your scripts from the app.
