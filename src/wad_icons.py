from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Optional

from loguru import logger
from wizwalker.file_readers.wad import Wad
from wizwalker.memory.memory_objects.game_object_template import (
    WizGameObjectTemplate,
)


# WADs always checked first. root.wad holds the vast majority of UI icons
# (~2800 DDS files); _Shared-WorldData.wad covers shared cross-world assets.
_PRIORITY_WADS = ("Root", "_Shared-WorldData")


# per-process caches. WADs are heavy to open, the bytes are immutable for
# the run of the game, and a missing path doesn't become present mid-run
_open_wads: dict[str, Wad | None] = {}
_bytes_cache: dict[str, bytes | None] = {}
_wad_open_lock = asyncio.Lock()

# background index: ``path → wad_name`` for every file in every wad
# ``none`` until the build task has produced something; the task fills it
# incrementally so partially-completed indexes are usable. done-state is
# tracked by ``_index_complete``
_path_to_wad: dict[str, str] = {}
_index_complete = False
_index_task: asyncio.Task | None = None
_index_lock = asyncio.Lock()


async def _get_wad(name: str) -> Wad | None:
    async with _wad_open_lock:
        if name in _open_wads:
            return _open_wads[name]
        try:
            w = Wad.from_game_data(name)
            await w.open()
            _open_wads[name] = w
            return w
        except Exception:
            _open_wads[name] = None
            return None


def _parse_virtual_path(raw: str) -> tuple[Optional[str], str]:
    if not raw or not raw.startswith("|"):
        return None, raw
    parts = raw.lstrip("|").split("|")
    # first component with a slash is the file path; everything before
    # forms the wad name
    for i, p in enumerate(parts):
        if "/" in p:
            wad_name = "-".join(parts[:i])
            file_path = "|".join(parts[i:])  # pipes within the file part stay
            return wad_name or None, file_path
    # no slash found - odd shape, hand the whole thing back as a path
    return None, raw


def _install_dir() -> Optional[Path]:
    try:
        from wizwalker.utils import get_wiz_install

        return get_wiz_install() / "Data" / "GameData"
    except Exception as exc:
        logger.debug(f"[wad_icons] couldn't locate install: {exc}")
        return None


async def _build_full_index() -> None:
    global _index_complete
    install = _install_dir()
    if install is None:
        _index_complete = True
        return

    all_names = sorted(p.stem for p in install.glob("*.wad"))
    # priority first so duplicate paths in lower-priority wads don't
    # overwrite them. (Most paths are unique, but ``GUI/...`` icons can
    # sometimes appear in both Root and a world wad.)
    ordered: list[str] = []
    seen: set[str] = set()
    for n in (*_PRIORITY_WADS, *all_names):
        if n not in seen:
            ordered.append(n)
            seen.add(n)

    logger.info(f"[wad_icons] indexing {len(ordered)} wads in background...")
    indexed = 0
    skipped = 0
    for wad_name in ordered:
        wad = await _get_wad(wad_name)
        if wad is None:
            skipped += 1
            continue
        try:
            names = await wad.names()
        except Exception as exc:
            logger.debug(f"[wad_icons] couldn't list {wad_name}: {exc}")
            skipped += 1
            continue
        for n in names:
            # first wad to claim a path keeps it (priority wins)
            if n not in _path_to_wad:
                _path_to_wad[n] = wad_name
        indexed += 1
        # yield to the event loop between wads so we don't block other
        # async work (combat handler, snapshot, etc.) for the full scan
        # duration
        await asyncio.sleep(0)

    _index_complete = True
    logger.info(
        f"[wad_icons] index complete: {len(_path_to_wad)} paths across "
        f"{indexed} wads ({skipped} skipped)"
    )


async def _ensure_index_started() -> None:
    global _index_task
    async with _index_lock:
        if _index_task is None:
            _index_task = asyncio.create_task(_build_full_index())


async def _read_icon_path(path: str) -> bytes | None:
    if not path:
        return None
    if path in _bytes_cache:
        return _bytes_cache[path]

    parsed_wad, file_path = _parse_virtual_path(path)

    # 1. directly try the wad the path encodes, if any.
    if parsed_wad:
        wad = await _get_wad(parsed_wad)
        if wad is not None:
            try:
                data = await wad.get_file(file_path)
                _bytes_cache[path] = data
                return data
            except Exception:
                pass

    # 2. priority pass against the bare file path.
    for wad_name in _PRIORITY_WADS:
        if wad_name == parsed_wad:
            continue  # already tried above
        wad = await _get_wad(wad_name)
        if wad is None:
            continue
        try:
            data = await wad.get_file(file_path)
            _bytes_cache[path] = data
            return data
        except Exception:
            continue

    # 3. background index. start it if not yet running.
    if not _index_complete:
        await _ensure_index_started()

    indexed_wad = _path_to_wad.get(file_path)
    if (
        indexed_wad is not None
        and indexed_wad != parsed_wad
        and indexed_wad not in _PRIORITY_WADS
    ):
        wad = await _get_wad(indexed_wad)
        if wad is not None:
            try:
                data = await wad.get_file(file_path)
                _bytes_cache[path] = data
                return data
            except Exception:
                pass

    if _index_complete:
        _bytes_cache[path] = None
    return None


async def icon_path_for_entity(entity) -> Optional[str]:
    try:
        core = await entity.object_template()
        if core is None:
            return None
        tmpl = WizGameObjectTemplate(core.hook_handler, await core.read_base_address())
        path = await tmpl.icon()
        return path or None
    except Exception:
        return None


async def fetch_entity_icon_bytes(entity) -> Optional[bytes]:
    path = await icon_path_for_entity(entity)
    if not path:
        return None
    return await _read_icon_path(path)


async def fetch_icon_bytes_by_path(path: str) -> Optional[bytes]:
    return await _read_icon_path(path)


def clear_caches() -> None:
    global _index_task, _index_complete
    _open_wads.clear()
    _bytes_cache.clear()
    _path_to_wad.clear()
    if _index_task is not None and not _index_task.done():
        _index_task.cancel()
    _index_task = None
    _index_complete = False
