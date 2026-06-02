-- SkyFall standard library — auto-loaded into every script before user code.
--
-- The `sky` global is reserved for things that DON'T live naturally on a
-- single client:
--   * pure helpers (flow control, table utilities, table dump)
--   * multi-client orchestration
--   * game-level / world-level helpers
--   * preset builders (playstyles, etc.)
--
-- Anything that operates on a single client is a method on `LuaClient`
-- itself — e.g. `client:farm_dungeon(opts)`, `client:enter_sigil(x,y,z)`.
-- See API.md or `src/lang/client.py` for the full method surface.

sky = {}
sky.flow      = {}
sky.debug     = {}
sky.multi     = {}

-- ── flow control (pure) ────────────────────────────────────────────────────

-- Run `fn(attempt)` and re-run on error up to `times` total attempts.
-- Returns the value of `fn` on success, or raises after exhaustion. The
-- 0.5s sleep happens *between* attempts only — not after the last.
function sky.flow.retry(times, fn)
    local last_err
    for i = 1, times do
        local ok, result = pcall(fn, i)
        if ok then return result end
        last_err = result
        if i < times then sleep(0.5) end
    end
    error('retry exhausted after ' .. times .. ' attempts: ' .. tostring(last_err))
end

-- Run a polling body with a wall-clock deadline. `fn` receives a context
-- table with `elapsed()`, `remaining()`, and `expired()` so it can decide
-- when to bail. `fn` should poll cooperatively — Lua coroutines aren't
-- pre-emptive, so this can't interrupt a runaway loop. For true async
-- cancellation use `window=` on the engine's waitfor_* methods.
function sky.flow.with_timeout(secs, fn)
    local start    = clock()
    local deadline = start + secs
    local ctx = {
        elapsed   = function() return clock() - start end,
        remaining = function() return deadline - clock() end,
        expired   = function() return clock() >= deadline end,
    }
    local result = fn(ctx)
    if ctx.expired() and result == nil then
        error(string.format('with_timeout: body did not return within %.1fs', secs))
    end
    return result
end

-- Call `predicate(i)` repeatedly until truthy. Returns the iteration
-- count when it succeeded. `opts.max` caps iterations; `opts.sleep` is
-- the per-loop pause (default 0.25s).
function sky.flow.repeat_until(predicate, opts)
    opts = opts or {}
    local max   = opts.max or math.huge
    local pause = opts.sleep or 0.25
    local i = 0
    while i < max do
        i = i + 1
        if predicate(i) then return i end
        sleep(pause)
    end
    error('repeat_until: predicate never became true after ' .. tostring(max) .. ' iterations')
end

-- Run `fn(i)` for i=1..n. Errors in individual iterations are logged but
-- don't abort the loop unless `opts.strict`.
function sky.flow.times(n, fn, opts)
    opts = opts or {}
    for i = 1, n do
        local ok, err = pcall(fn, i)
        if not ok then
            if opts.strict then error(err) end
            sky.debug.log('iter ' .. i .. ' failed: ' .. tostring(err))
        end
    end
end

-- ── debug (pure / global) ──────────────────────────────────────────────────

-- Pretty-print a table as a string (one level deep). For per-client
-- snapshots use `client:log_state(label)`.
function sky.debug.dump(t)
    if type(t) ~= 'table' then return tostring(t) end
    local parts = {}
    for k, v in pairs(t) do
        local key = type(k) == 'string' and k or '[' .. tostring(k) .. ']'
        if type(v) == 'table' then
            parts[#parts + 1] = key .. ' = {...}'
        else
            parts[#parts + 1] = key .. ' = ' .. tostring(v)
        end
    end
    return '{ ' .. table.concat(parts, ', ') .. ' }'
end

-- Untargeted log line — for client-tagged logs use `client:log(msg)`.
function sky.debug.log(msg)
    print('[sky] ' .. tostring(msg))
end

-- Playstyle presets intentionally omitted: Wizard101 combat is too
-- school-, level-, and deck-specific for a generic "boss" or "farm"
-- preset to be useful. Write the priority list literally in your script,
-- or build helpers in your own file. See API.md for the playstyle DSL.

-- ── multi-client ───────────────────────────────────────────────────────────

-- Sequentially apply `fn(c, i)` to each client. Errors are logged but
-- don't abort the loop unless `opts.strict`.
function sky.multi.each(client_list, fn, opts)
    opts = opts or {}
    for i = 1, #client_list do
        local c = client_list[i]
        local ok, err = pcall(fn, c, i)
        if not ok then
            if opts.strict then error(err) end
            c:log('multi.each: ' .. tostring(err))
        end
    end
end

-- Send the same key to every client. Sequential (not pre-empted); for
-- true synchronized actions use the engine's mass hotkeys.
function sky.multi.mass_key(client_list, key)
    sky.multi.each(client_list, function(c) c:send_key(key) end)
end

-- Run `fn(c, i)` on every client and stop the first time `fn` returns
-- truthy. Returns (client, iteration_value) or (nil, nil) if no match.
function sky.multi.any(client_list, fn)
    for i = 1, #client_list do
        local c = client_list[i]
        local v = fn(c, i)
        if v then return c, v end
    end
    return nil, nil
end

-- ── top-level aliases ──────────────────────────────────────────────────────
-- Most common ones, one identifier deep.

sky.retry        = sky.flow.retry
sky.repeat_until = sky.flow.repeat_until
sky.times        = sky.flow.times
sky.with_timeout = sky.flow.with_timeout
sky.dump         = sky.debug.dump
sky.log          = sky.debug.log
sky.each         = sky.multi.each
sky.mass_key     = sky.multi.mass_key
sky.pause_logs   = pause_logs
sky.resume_logs  = resume_logs
