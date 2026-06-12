"""Native fishing engine.

Two pieces, both driven off a single :class:`Fisher` instance:

* ``apply_fishing_patches`` / ``restore_fishing_patches`` — the byte patches that
  strip the fishing minigame (skip cast/summon/struggle animations, make fish
  notice/bite instantly, zero the cast/summon timers). Same write-bytes /
  restore-bytes style as the client patches in ``src/launcher.py``; a pattern
  that fails to locate is logged and skipped, never fatal.
* :class:`Fisher` — the loop: refresh pond (banishing fish that don't match the
  config), cast, wait for a hooked fish, catch, sell the basket when full. Live
  stats are reported through an ``on_stats`` callback.

Byte patterns are patch-fragile; refresh them per the client-patch workflow in
CLAUDE.md if a future client update breaks fishing.
"""

from __future__ import annotations

import asyncio
from dataclasses import asdict, dataclass
from time import time
from typing import Callable, Optional

from loguru import logger

from wizwalker import Client, Keycode
from wizwalker.memory import MemoryReader
from wizwalker.memory.memory_objects.fish import FishStatusCode


# ─────────────────────────── config ────────────────────────────


@dataclass
class FishConfig:
    """A fishing target + behaviour profile, shared by the GUI and Lua paths."""

    chest: bool = False
    school: str = "Any"
    rank: int = 0
    template_id: int = 0
    size_min: float = 0.0
    size_max: float = 999.0
    amount: int = 0  # stop after N catches; 0 = unlimited

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict | None) -> "FishConfig":
        if not data:
            return cls()
        fields = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in data.items() if k in fields})

# ─────────────────────────── patches ───────────────────────────

# Direct write-byte patches: scan ``pattern``, then overwrite ``write`` bytes at
# ``offset``. ``.`` / ``..`` in a pattern are single-byte wildcards (the scanner
# treats patterns as DOTALL regex). This set tracks the current live client; if a
# future update breaks fishing, re-derive per the CLAUDE.md client-patch workflow.
FISHING_PATCH_SPECS: list[dict] = [
    {"name": "scare_fish", "pattern": rb"\xE8....\xEB.\x83\xF9\x04\x75.\xC7\x87", "write": b"\x90" * 5},
    {"name": "bobber_submersion_rng", "pattern": rb"\x7D\x37\xC7\x83........\xC7\x83", "write": b"\x90" * 2},
    {"name": "fish_notice_bobber_instant", "pattern": rb"\x0F\x82....\xC7\x83........\x8B\x93", "write": b"\x90" * 6},
    {"name": "instant_fish", "pattern": rb"\x74\x63\x48\x8B\xCF\xE8....\x0F", "write": b"\x90" * 2},
    {"name": "instant_fish_2", "pattern": rb"\x0F\x82....\xF3\x44\x0F\x10\x0D....\x41\x0F\x2F\xC1", "write": b"\x90" * 6},
    {"name": "instant_fish_3", "pattern": rb"\x0F\x86....\xF3\x41\x0F\x5C\xF2", "write": b"\x90" * 6},
    {"name": "instant_fish_4", "pattern": rb"\x0F\x86....\x44\x0F\x2F\x05", "write": b"\x90" * 6},
    {"name": "instant_fish_5", "pattern": rb"\x0F\x84....\x48\x8B\x8B....\x45\x32", "write": b"\x90" * 6},
    {"name": "instant_fish_6", "pattern": rb"\x0F\x84....\xF3\x0F\x10\x70\x6C\x0F\x28\xC6", "write": b"\x90" * 6},
    {"name": "instant_fish_7", "pattern": rb"\x0F\x86....\xF3\x0F\x10\x8B....\x0F\x28\xC1", "write": b"\x90" * 6},
    {"name": "instant_fish_8", "pattern": rb"\x0F\x86....\xF3\x0F\x10\x83....\xF3\x0F\x5C\x83", "write": b"\x90" * 6},
    {"name": "instant_fish_9", "pattern": rb"\x0F\x87....\xF2\x0F\x10\xB3....\xF2", "write": b"\x90" * 6},
    {"name": "skip_bobbing", "pattern": rb"\x0F\x82....\xF3\x0F\x11\x87", "write": b"\xE9\x79\x05\x00\x00\x90"},
    {"name": "skip_catch_animation", "pattern": rb"\x0F\x84....\x48..\x10\x02\x00\x00\xE8....\x84\xC0..\x48..\x78\x02\x00\x00\x00", "write": b"\xE9\x88\x00\x00\x00\x90"},
    {"name": "skip_struggle", "pattern": rb"\x0F\x82....\x44..\xE4\x02\x00\x00\x48..\xC8\x02\x00\x00", "write": b"\x90" * 6},
    {"name": "skip_summon_animation", "pattern": rb"\x8B\x54\x24.\x48\x8B\xCF\xE8....\x90\x48\x8B\x5E.\x48\x85\xDB\x74\x2E\xBF....\x8B\xC7\xF0\x0F\xC1\x43.\x83\xF8.\x75\x1D\x48\x8B\x03\x48\x8B\xCB\xFF\x50.\xF0\x0F\xC1\x7B.\x83\xFF.\x75\x0A\x48\x8B\x03\x48\x8B\xCB\xFF\x50.\x90\x48\x8B\x5C\x24.\x48\x8B\x74\x24.\x48\x83\xC4.\x5F\xC3", "write": b"\x90" * 5, "offset": 7},
    {"name": "zero_casting_timer", "pattern": rb"\x49\x8D.\xD0\x00\x00\x00\x48\x8B\x01\xBA\x14\x05\x00\x00\xFF\x50\x18", "write": b"\x00\x00\x00\x00", "offset": 11},
    {"name": "zero_summon_timer", "pattern": rb"\x48\x8D.\xA0\x00\x00\x00\x48\x8B\x01\xBA\x14\x05\x00\x00\xFF\x50\x18", "write": b"\x00\x00\x00\x00", "offset": 11},
]

# Relative-jump patches that splice computed bytes onto the original. The current
# client needs none, but the machinery stays for future patch sets.
_SPLICE_PATCH_SPECS: list[dict] = []

_MODULE = "WizardGraphicalClient.exe"


async def _scan(reader: MemoryReader, pattern: bytes):
    """Locate ``pattern`` in the client module, or return None if it doesn't
    match (the fork's ``pattern_scan`` raises rather than returning None). A miss
    just means that one patch is skipped — fishing still works, only with the
    matched patches' animations stripped."""
    from wizwalker.errors import PatternFailed, PatternMultipleResults

    try:
        return await reader.pattern_scan(pattern, return_multiple=False, module=_MODULE)
    except (PatternFailed, PatternMultipleResults):
        return None


async def apply_fishing_patches(client: Client) -> list[tuple[int, bytes]]:
    """Apply every fishing patch, returning ``(addr, old_bytes)`` for restore.

    Each patch is independent: an unmatched pattern (client drift) is logged and
    skipped instead of aborting the rest, so ``saved`` always reflects exactly
    what was written and can be fully restored."""
    reader = MemoryReader(client._pymem)
    saved: list[tuple[int, bytes]] = []
    missed: list[str] = []

    async def _direct(spec: dict):
        try:
            add = await _scan(reader, spec["pattern"])
            if add is None:
                missed.append(spec["name"])
                return
            add += spec.get("offset", 0)
            old = await reader.read_bytes(add, len(spec["write"]))
            await reader.write_bytes(add, spec["write"])
            saved.append((add, old))
        except Exception as e:
            logger.warning(f"[Fishing] patch {spec['name']} failed: {e}")

    async def _splice(spec: dict):
        try:
            add = await _scan(reader, spec["pattern"])
            if add is None:
                missed.append(spec["name"])
                return
            old = await reader.read_bytes(add, spec["read"])
            await reader.write_bytes(add, spec["build"](old))
            saved.append((add, old))
        except Exception as e:
            logger.warning(f"[Fishing] patch {spec['name']} failed: {e}")

    await asyncio.gather(
        *[_direct(s) for s in FISHING_PATCH_SPECS],
        *[_splice(s) for s in _SPLICE_PATCH_SPECS],
    )
    total = len(FISHING_PATCH_SPECS) + len(_SPLICE_PATCH_SPECS)
    logger.info(f"[Fishing] applied {len(saved)}/{total} patches")
    if missed:
        logger.warning(
            f"[Fishing] {len(missed)} patterns didn't match this client "
            f"(fishing still works, less optimised): {', '.join(missed)}"
        )
    return saved


async def restore_fishing_patches(client: Client, saved: list[tuple[int, bytes]]) -> None:
    if not saved:
        return
    reader = MemoryReader(client._pymem)
    restored = 0
    for addr, old in saved:
        try:
            await reader.write_bytes(addr, old)
            restored += 1
        except Exception as e:
            logger.error(f"[Fishing] failed to restore patch at 0x{addr:X}: {e}")
    logger.info(f"[Fishing] restored {restored}/{len(saved)} patches")


def fish_matches(
    cfg: FishConfig, *, is_chest: bool, school: str, rank: int, template_id: int, size: float
) -> bool:
    """Whether a fish satisfies the target config (the banish predicate)."""
    if is_chest != cfg.chest:
        return False
    if cfg.school != "Any" and school != cfg.school:
        return False
    if cfg.rank != 0 and rank != cfg.rank:
        return False
    if cfg.template_id != 0 and template_id != cfg.template_id:
        return False
    if size < cfg.size_min or size > cfg.size_max:
        return False
    return True


# ─────────────────────────── poll timings ───────────────────────
_POLL = 0.005
_AFTER_CLICK = 0.01
_RETRY = 0.01
_WINDOW_WAIT = 0.02
_GAME_STATE = 0.025


class Fisher:
    """Drives a fishing session on a single client; reports live stats."""

    def __init__(
        self,
        client: Client,
        config: FishConfig,
        on_stats: Optional[Callable[[dict], None]] = None,
        should_stop: Optional[Callable[[], bool]] = None,
    ):
        self._c = client
        self.config = config
        self._on_stats = on_stats
        self._should_stop = should_stop
        self._stop = False
        self._saved: list[tuple[int, bytes]] = []
        self.stats = {
            "running": False,
            "fish_caught": 0,
            "elapsed": 0.0,
            "sec_per_fish": 0.0,
            "pool_size": 0,
            "baskets_sold": 0,
            "energy_spent": 0,
            "recent": [],
        }
        self._start = 0.0
        self._energy_start: Optional[int] = None

    def stop(self) -> None:
        self._stop = True

    def _exit(self) -> bool:
        return self._stop or (self._should_stop is not None and self._should_stop())

    def _emit(self) -> None:
        if self._on_stats is not None:
            try:
                self._on_stats(dict(self.stats, recent=list(self.stats["recent"])))
            except Exception:
                logger.debug("[Fishing] on_stats callback failed", exc_info=True)

    # ── window helpers ──────────────────────────────────────────
    async def _window_exists(self, name: str, *, visible: bool = True) -> bool:
        w = await self._c.root_window.get_windows_with_name(name)
        if visible:
            return len(w) > 0 and await w[0].is_visible()
        return len(w) > 0

    async def _wait_for_window(self, name: str, *, timeout: float = 10, visible: bool = True):
        start = time()
        while not await self._window_exists(name, visible=visible) and not self._exit():
            if time() - start >= timeout:
                break
            await asyncio.sleep(_POLL)

    async def _wait_click_window(self, name: str, *, timeout: float = 10, visible: bool = True):
        await self._wait_for_window(name, timeout=timeout, visible=visible)
        await asyncio.sleep(_AFTER_CLICK)
        async with self._c.mouse_handler:
            await self._c.mouse_handler.click_window_with_name(name)

    async def _fetch_fish_list(self, fishing_manager):
        while not self._exit():
            try:
                return await fishing_manager.fish_list()
            except RuntimeError:
                await asyncio.sleep(_RETRY)
        return []

    async def _sell_basket(self):
        if self._exit():
            return
        await self._c.send_key(Keycode.V)
        while await self._window_exists("Trash") and not self._exit():
            while not await self._window_exists("centerButton") and not self._exit():
                try:
                    async with self._c.mouse_handler:
                        await self._c.mouse_handler.click_window_with_name("Trash")
                except ValueError:
                    await asyncio.sleep(_RETRY)
            if self._exit():
                break
            while await self._window_exists("centerButton") and not self._exit():
                try:
                    async with self._c.mouse_handler:
                        await self._c.mouse_handler.click_window_with_name("centerButton")
                except ValueError:
                    await asyncio.sleep(_RETRY)
        if not self._exit():
            await self._c.send_key(Keycode.V)
        self.stats["baskets_sold"] += 1

    async def _banish_config(self, fishing_manager) -> list:
        """Escape fish that don't match the config; return the kept ones.

        Each wizwalker read is a synchronous round-trip into the client, so we
        read only the fields the config actually filters on and bail at the
        first miss. The default 'any non-chest fish' costs a single ``is_chest``
        read per fish instead of six."""
        cfg = self.config
        need_school = cfg.school != "Any"
        need_rank = cfg.rank != 0
        need_id = cfg.template_id != 0
        need_size = cfg.size_min > 0.0 or cfg.size_max < 999.0
        kept = []
        for fish in await self._fetch_fish_list(fishing_manager):
            ok = (await fish.is_chest()) == cfg.chest
            if ok and (need_school or need_rank):
                template = await fish.template()
                if need_school and (await template.school_name()) != cfg.school:
                    ok = False
                if ok and need_rank and (await template.rank()) != cfg.rank:
                    ok = False
            if ok and need_id and (await fish.template_id()) != cfg.template_id:
                ok = False
            if ok and need_size:
                size = await fish.size()
                if size < cfg.size_min or size > cfg.size_max:
                    ok = False
            if ok:
                kept.append(fish)
            else:
                await fish.write_status_code(FishStatusCode.escaped)
        return kept

    async def _refresh_pond(self, fishing_manager) -> list:
        if self._exit():
            return []
        fish_list = await self._banish_config(fishing_manager)
        while len(fish_list) == 0 and not self._exit():
            fish_windows = await self._c.root_window.get_windows_with_name("FishingWindow")
            while len(fish_windows) == 0 and not self._exit():
                async with self._c.mouse_handler:
                    await self._c.mouse_handler.click_window_with_name("OpenFishingButton")
                fish_windows = await self._c.root_window.get_windows_with_name("FishingWindow")
                await asyncio.sleep(_WINDOW_WAIT)
            if self._exit():
                return fish_list
            sub = await fish_windows[0].get_child_by_name("FishingSubWindow")
            bottom = await sub.get_child_by_name("BottomFrame")
            icon2 = await bottom.get_child_by_name("Icon2")
            async with self._c.mouse_handler:
                await self._c.mouse_handler.click_window(icon2)
            while not self._exit():
                try:
                    if len(await self._fetch_fish_list(fishing_manager)) > 0:
                        break
                except RuntimeError:
                    await asyncio.sleep(_RETRY)
            if self._exit():
                return fish_list
            await asyncio.sleep(_AFTER_CLICK)
            fish_list = await self._banish_config(fishing_manager)
        return fish_list

    async def _read_energy(self) -> Optional[int]:
        try:
            return await self._c.current_energy()
        except Exception:
            return None

    def _record_catch(self, school: str, size: float, is_chest: bool):
        recent = self.stats["recent"]
        recent.insert(0, {"school": school, "size": round(size, 1), "chest": is_chest})
        del recent[12:]

    # ── lifecycle ───────────────────────────────────────────────
    async def run(self) -> None:
        cfg = self.config
        self._start = time()
        self._energy_start = await self._read_energy()
        self.stats["running"] = True
        self._emit()

        try:
            self._saved = await apply_fishing_patches(self._c)
            fishing_manager = await self._c.game_client.fishing_manager()

            while not self._exit():
                fish_list = await self._refresh_pond(fishing_manager)

                fish_windows = await self._c.root_window.get_windows_with_name("FishingWindow")
                while len(fish_windows) == 0 and not self._exit():
                    async with self._c.mouse_handler:
                        await self._c.mouse_handler.click_window_with_name("OpenFishingButton")
                    fish_windows = await self._c.root_window.get_windows_with_name("FishingWindow")
                if self._exit():
                    break

                sub = await fish_windows[0].get_child_by_name("FishingSubWindow")
                bottom = await sub.get_child_by_name("BottomFrame")
                icon1 = await bottom.get_child_by_name("Icon1")
                async with self._c.mouse_handler:
                    await self._c.mouse_handler.click_window(icon1)

                hooked = False
                caught_meta = None
                while not hooked and not self._exit():
                    if await self._window_exists("MessageBoxModalWindow"):
                        await self._wait_click_window("rightButton")
                        await self._sell_basket()
                        break
                    fish_list = await self._fetch_fish_list(fishing_manager)
                    for fish in fish_list:
                        try:
                            if await fish.status_code() == FishStatusCode.unknown2:
                                hooked = True
                                caught_meta = await self._catch_meta(fish)
                                break
                        except (RuntimeError, ValueError):
                            continue
                if self._exit():
                    break
                if not hooked:
                    continue

                await self._c.send_key(Keycode.SPACEBAR)

                if not await self._dismiss_caught_popup():
                    continue  # popup never showed (failed catch) — don't count it
                if self._exit():
                    break

                self.stats["fish_caught"] += 1
                if caught_meta is not None:
                    self._record_catch(*caught_meta)
                if self.stats["fish_caught"] % 100 == 0 and not cfg.chest:
                    await self._sell_basket()

                # energy reads walk the behavior list, so refresh it only
                # occasionally (and once more at teardown for the final value)
                if self.stats["fish_caught"] % 10 == 0:
                    await self._refresh_energy()
                self._update_stats(len(fish_list) - 1)
                self._emit()

                if cfg.amount and self.stats["fish_caught"] >= cfg.amount:
                    break
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("[Fishing] loop error")
        finally:
            await self._teardown()

    async def _catch_meta(self, fish):
        try:
            template = await fish.template()
            return (await template.school_name(), await fish.size(), await fish.is_chest())
        except Exception:
            return None

    async def _dismiss_caught_popup(self) -> bool:
        # wait up to 10s for the caught-fish window; a no-show means the catch
        # failed, so the caller re-casts without counting it
        timeout = time()
        while len(await self._c.root_window.get_windows_with_name("CaughtFishModalWindow")) == 0:
            if self._exit():
                return False
            if time() - timeout >= 10:
                return False
            await asyncio.sleep(_POLL)
        # spam space to clear it — more robust across client builds than
        # clicking the (sometimes disabled) exit button
        while len(await self._c.root_window.get_windows_with_name("CaughtFishModalWindow")) > 0:
            if self._exit():
                return True
            await self._c.send_key(Keycode.SPACEBAR)
            await asyncio.sleep(_GAME_STATE)
        return True

    async def _refresh_energy(self):
        now = await self._read_energy()
        if self._energy_start is not None and now is not None:
            self.stats["energy_spent"] = max(0, self._energy_start - now)

    def _update_stats(self, pool_size: int):
        caught = self.stats["fish_caught"]
        elapsed = time() - self._start
        self.stats["elapsed"] = elapsed
        self.stats["pool_size"] = max(0, pool_size)
        self.stats["sec_per_fish"] = (elapsed / caught) if caught else 0.0

    async def _teardown(self):
        try:
            await restore_fishing_patches(self._c, self._saved)
        except Exception as e:
            logger.error(f"[Fishing] patch restore error: {e}")
        self._saved = []
        energy_now = await self._read_energy()
        if self._energy_start is not None and energy_now is not None:
            self.stats["energy_spent"] = max(0, self._energy_start - energy_now)
        self.stats["running"] = False
        self._emit()
