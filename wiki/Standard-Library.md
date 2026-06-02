# Standard Library — globals & `sky.*`

These are available in **every** script without a `client:` receiver.

## Globals

<!-- AUTOGEN:globals START — generated from source; do not edit. Run: python -m src.lang.docgen --emit -->
| Global | Description |
|---|---|
| `clients()` | 1-indexed table of `LuaClient`, one per hooked Wizard101 client |
| `sleep(secs)` | Block for `secs` seconds, interruptible by the stop signal |
| `clock()` | Monotonic wall-clock seconds, for timing inside a script |
| `print(...)` | Print a line to the script console |
| `json.encode(v[, pretty])` | Encode a Lua value to a JSON string |
| `json.decode(s)` | Decode a JSON string to a Lua value |
| `pause_logs()` | Pause SkyFall's log output |
| `resume_logs()` | Resume SkyFall's log output |
<!-- AUTOGEN:globals END -->

### `json`

```lua
local s = json.encode({ a = 1, b = {2, 3} })   -- compact
local pretty = json.encode(t, true)            -- indented
local t = json.decode('{"hp": 100}')
```

### `clock` / `sleep`

`clock()` is a monotonic timer in seconds — use it to measure elapsed time.
`sleep(secs)` blocks but stays interruptible by the stop signal.

```lua
local t0 = clock()
client:waitfor_battle_finish()
print(string.format("fight took %.1fs", clock() - t0))
```

## `sky.*` recipes

The `sky` table holds pure helpers, flow control, and multi-client
orchestration — anything that doesn't belong to a single client. Source:
`src/lang/stdlib.lua` in the repo.

<!-- AUTOGEN:stdlib START — generated from source; do not edit. Run: python -m src.lang.docgen --emit -->
| Recipe | Description |
|---|---|
| `sky.flow.retry(times, fn)` | Run `fn(attempt)` and re-run on error up to `times` total attempts. Returns the value of `fn` on success, or raises after exhaustion. The 0.5s sleep happens *between* attempts only — not after the last. |
| `sky.flow.with_timeout(secs, fn)` | Run a polling body with a wall-clock deadline. `fn` receives a context table with `elapsed()`, `remaining()`, and `expired()` so it can decide when to bail. `fn` should poll cooperatively — Lua coroutines aren't pre-emptive, so this can't interrupt a runaway loop. For true async cancellation use `window=` on the engine's waitfor_* methods. |
| `sky.flow.repeat_until(predicate, opts)` | Call `predicate(i)` repeatedly until truthy. Returns the iteration count when it succeeded. `opts.max` caps iterations; `opts.sleep` is the per-loop pause (default 0.25s). |
| `sky.flow.times(n, fn, opts)` | Run `fn(i)` for i=1..n. Errors in individual iterations are logged but don't abort the loop unless `opts.strict`. |
| `sky.debug.dump(t)` | Pretty-print a table as a string (one level deep). For per-client snapshots use `client:log_state(label)`. |
| `sky.debug.log(msg)` | Untargeted log line — for client-tagged logs use `client:log(msg)`. |
| `sky.multi.each(client_list, fn, opts)` | Sequentially apply `fn(c, i)` to each client. Errors are logged but don't abort the loop unless `opts.strict`. |
| `sky.multi.mass_key(client_list, key)` | Send the same key to every client. Sequential (not pre-empted); for true synchronized actions use the engine's mass hotkeys. |
| `sky.multi.any(client_list, fn)` | Run `fn(c, i)` on every client and stop the first time `fn` returns truthy. Returns (client, iteration_value) or (nil, nil) if no match. |

**Top-level aliases:** `sky.retry` → `sky.flow.retry`, `sky.repeat_until` → `sky.flow.repeat_until`, `sky.times` → `sky.flow.times`, `sky.with_timeout` → `sky.flow.with_timeout`, `sky.dump` → `sky.debug.dump`, `sky.log` → `sky.debug.log`, `sky.each` → `sky.multi.each`, `sky.mass_key` → `sky.multi.mass_key`, `sky.pause_logs` → `pause_logs`, `sky.resume_logs` → `resume_logs`
<!-- AUTOGEN:stdlib END -->

### Examples

```lua
-- retry a flaky action up to 5 times
sky.retry(5, function() client:friend_tp("Alric") end)

-- poll until a condition holds, capped at 40 iterations
sky.repeat_until(function() return client:in_zone("Triton Avenue") end,
                 { max = 40, sleep = 0.5 })

-- run the same routine on every client
sky.each(clients(), function(c) c:use_potion() end)

-- send a key to all clients at once
sky.mass_key(clients(), "W")
```

---

## Regenerating the reference tables

Every `<!-- AUTOGEN:… -->` block in this wiki — the method tables on the API
pages and the two tables above — is generated from source:

```
python -m src.lang.docgen --emit
```

- **Signatures and the method set** come live from `src/lang/client/` via
  introspection, so they can't drift.
- **Descriptions and grouping** live in `src/lang/wiki_meta.py`.

Add a method? Add a one-line row to `wiki_meta.py` and re-run `--emit`. A method
present in source but missing from `wiki_meta.py` shows up under
*Uncategorized → undocumented*; a stale entry in `wiki_meta.py` prints a
warning. Prose outside the AUTOGEN blocks is never touched.
