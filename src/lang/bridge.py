from __future__ import annotations


import asyncio

import json

import re

import threading

import time

import traceback

from pathlib import Path

from typing import Any, Callable


import lupa.lua55 as lua


try:
    from loguru import logger as _logger
except Exception:  # loguru is a soft dep here - fall back to printing
    _logger = None


_SANDBOX = (
    "io=nil; os=nil; require=nil; dofile=nil; load=nil;"
    "loadfile=nil; package=nil; debug=nil"
)


def _attr_filter(obj, name, is_setting):
    if isinstance(name, bytes):
        try:
            name = name.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise AttributeError("sandbox: non-utf8 attribute name") from exc
    if not isinstance(name, str):
        raise AttributeError(f"sandbox: non-string attribute {name!r}")
    if name.startswith("_"):
        raise AttributeError(f"sandbox: access denied for {name!r}")
    return name


class ScriptError(Exception):
    pass


class _ScriptStopped(ScriptError):
    pass


class LuaBridge:
    def __init__(self, loop: asyncio.AbstractEventLoop):

        self._loop = loop

        self._stop = threading.Event()

        self._globals: dict[str, Any] = {}

        self._thread: threading.Thread | None = None

        self._error_callback: Callable[[str], None] | None = None

        self._current_rt: lua.LuaRuntime | None = None

        # source of the currently-running script, kept for error attribution
        # (we slice the offending line out by number when Lua errors fire)
        self._current_source: str = ""

        self._current_source_label: str = "<script>"

        # toggles the script switched on, keyed so re-enabling overwrites.
        # value = factory returning a teardown coro. leftovers run when the
        # script ends so a toggle it turned on doesn't outlive it
        self._toggle_cleanups: dict[Any, Callable[[], Any]] = {}

    def on_error(self, cb: Callable[[str], None]):

        self._error_callback = cb

    def register_toggle_cleanup(self, key: Any, factory: Callable[[], Any]):

        self._toggle_cleanups[key] = factory

    def unregister_toggle_cleanup(self, key: Any):

        self._toggle_cleanups.pop(key, None)

    def _run_toggle_cleanups(self):

        factories = list(self._toggle_cleanups.values())
        self._toggle_cleanups.clear()
        if not factories:
            return

        loop = self._loop
        for factory in factories:
            try:
                coro = factory()
            except Exception:
                continue
            if loop.is_closed() or not loop.is_running():
                # no live loop to await the teardown on (e.g. headless
                # tests) - close the coroutine so it isn't left pending
                close = getattr(coro, "close", None)
                if close is not None:
                    close()
                continue
            try:
                fut = asyncio.run_coroutine_threadsafe(coro, loop)
                fut.result(timeout=5)
            except Exception:
                pass

    def call_async(self, coro) -> Any:

        if self._stop.is_set():
            coro.close()
            raise _ScriptStopped("stopped")

        fut = asyncio.run_coroutine_threadsafe(coro, self._loop)

        return fut.result()

    def table_from(self, items) -> Any:

        return self._current_rt.table_from(items)

    def register(self, name: str, fn: Callable, *, is_async: bool = True):

        if is_async:

            def _wrap(*args):

                return self.call_async(fn(*args))

            self._globals[name] = _wrap

        else:
            self._globals[name] = fn

    def load(self, path: str | Path):

        p = Path(path)
        self.run(p.read_text(encoding="utf-8"), source_label=p.name)

    def run(self, source: str, *, source_label: str = "<script>"):

        self.stop()

        self._stop.clear()

        self._toggle_cleanups.clear()

        self._current_source = source

        self._current_source_label = source_label

        rt = self._build_runtime()

        def _run():

            try:
                rt.execute(source)

            except _ScriptStopped:
                # stop signal, user pressed kill. silent
                pass

            except ScriptError as e:
                # user-visible script error (e.g. waitfor_* timeout).
                # important: this except must come AFTER _ScriptStopped so
                # the stop signal stays silent
                msg = str(e)
                if _logger is not None:
                    _logger.error(f"[lua] {msg}")
                if self._error_callback:
                    self._error_callback(msg)

            except lua.LuaError as e:
                msg = self._format_lua_error(str(e))

                if _logger is not None:
                    _logger.error(f"[lua] {msg}")

                if self._error_callback:
                    self._error_callback(msg)

            except Exception as e:
                # anything else (a Python exception leaking out of a bridge
                # call, lupa internals, etc.) - surface it with a traceback
                # rather than silently dropping it
                msg = f"internal error: {e}\n{traceback.format_exc()}"

                if _logger is not None:
                    _logger.error(f"[lua] {msg}")

                if self._error_callback:
                    self._error_callback(msg)

            finally:
                # turn off any toggle the script switched on but didn't
                # switch back off itself, then restore console logging
                self._run_toggle_cleanups()
                from src.lang.client import resume_logs

                resume_logs()

        self._thread = threading.Thread(target=_run, daemon=True, name="lua")

        self._thread.start()

    def stop(self):

        self._stop.set()

        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=3.0)

    @property
    def running(self) -> bool:

        return self._thread is not None and self._thread.is_alive()

    def _format_lua_error(self, raw: str) -> str:
        m = _LUA_LOC_RE.search(raw)
        if not m:
            # not a location-prefixed error (e.g. raised via Python before
            # any Lua code ran) - pass through cleanly
            return raw.strip()

        line_no = int(m.group(1))
        message = m.group(2).strip()

        source_lines = self._current_source.splitlines()
        snippet = (
            source_lines[line_no - 1].strip()
            if 0 < line_no <= len(source_lines)
            else None
        )

        head = f"{self._current_source_label}:{line_no}: {message}"
        if snippet:
            return f"{head}\n    > {snippet}"
        return head

    def _build_runtime(self) -> lua.LuaRuntime:

        rt = lua.LuaRuntime(
            unpack_returned_tuples=True,
            register_eval=False,
            register_builtins=False,
            attribute_filter=_attr_filter,
        )

        rt.execute(_SANDBOX)

        self._current_rt = rt

        g = rt.globals()

        for name, fn in self._globals.items():
            g[name] = fn

        stop = self._stop

        def _sleep(secs: float):

            end = time.monotonic() + secs

            while time.monotonic() < end:
                if stop.is_set():
                    raise _ScriptStopped("stopped")

                time.sleep(min(0.05, end - time.monotonic()))

        g["sleep"] = _sleep

        # `clock()` gives scripts a wall-clock reference for measuring
        # elapsed time - `os.clock` is sandboxed off, so without this
        # there's no way for Lua code to time itself
        g["clock"] = time.monotonic

        json_tbl = rt.table_from({})
        json_tbl["encode"] = lambda v, pretty=False: _json_encode(v, pretty)
        json_tbl["decode"] = lambda s: _json_decode(rt, s)
        g["json"] = json_tbl

        # auto-load the standard library so every script can use `sky.*`
        # without an explicit require/import (none exists - `require` is
        # sandboxed off). errors here are non-fatal: the script runs
        # without stdlib if the file is missing or has a syntax issue, but
        # we log loudly so the developer notices
        stdlib_path = Path(__file__).parent / "stdlib.lua"
        try:
            stdlib_src = stdlib_path.read_text(encoding="utf-8")
            rt.execute(stdlib_src)
        except FileNotFoundError:
            if _logger is not None:
                _logger.warning(f"[lua] stdlib not found at {stdlib_path}")
        except lua.LuaError as e:
            if _logger is not None:
                _logger.error(f"[lua] stdlib failed to load: {e}")

        return rt


_LUA_LOC_RE = re.compile(r'\[string "[^"]*"\]:(\d+):\s*(.*)', re.DOTALL)


def _lua_to_py(v: Any) -> Any:
    if not lua.lua_type(v) == "table":
        return v
    d = dict(v)
    if not d:
        return []
    keys = list(d.keys())
    if all(isinstance(k, int) for k in keys):
        lo, hi = min(keys), max(keys)
        if lo == 1 and hi == len(keys):
            return [_lua_to_py(d[i]) for i in range(1, hi + 1)]
    return {str(k): _lua_to_py(val) for k, val in d.items()}


def _json_encode(v: Any, pretty: bool = False) -> str:
    return json.dumps(_lua_to_py(v), indent=2 if pretty else None, ensure_ascii=False)


def _py_to_lua(rt: lua.LuaRuntime, v: Any) -> Any:
    if isinstance(v, dict):
        t = rt.table_from({})
        for k, val in v.items():
            t[k] = _py_to_lua(rt, val)
        return t
    if isinstance(v, list):
        return rt.table_from([_py_to_lua(rt, x) for x in v])
    return v


def _json_decode(rt: lua.LuaRuntime, s: str) -> Any:
    return _py_to_lua(rt, json.loads(s))


def _clean_error(msg: str) -> str:

    if "]:" in msg:
        return msg.split("]:", 1)[-1].strip()

    return msg
