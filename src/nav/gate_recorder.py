from __future__ import annotations

import asyncio
from pathlib import Path

from loguru import logger


_ZONES_TXT = Path(__file__).parent / "data" / "zones.txt"
_POLL_INTERVAL = 0.4  # seconds between zone-name polls
_SETTLE_DELAY = 0.6  # wait after detecting transition before reading new zone


_CALIBRATION = Path(__file__).parent / "data" / "calibration.jsonl"


def _load_existing_gates(path: Path) -> set[tuple[str, str]]:
    pairs: set[tuple[str, str]] = set()
    if not path.exists():
        return pairs
    for line in path.read_text(encoding="utf-8").splitlines():
        parts = line.split(";")
        if parts[0] == "GATE" and len(parts) >= 7:
            pairs.add((parts[5], parts[6]))
    return pairs


def _load_trigger_coords(
    path: Path,
) -> dict[tuple[str, str], tuple[float, float, float]]:
    coords: dict[tuple[str, str], tuple[float, float, float]] = {}
    if not path.exists():
        return coords
    for line in path.read_text(encoding="utf-8").splitlines():
        parts = line.split(";")
        if parts[0] == "GATE" and len(parts) >= 7:
            try:
                coords[(parts[5], parts[6])] = (
                    float(parts[2]),
                    float(parts[3]),
                    float(parts[4]),
                )
            except ValueError:
                pass
    return coords


def _record_calibration(
    src: str,
    dst: str,
    trigger_xyz: tuple[float, float, float],
    actual_xyz: tuple[float, float, float],
) -> None:
    import json
    import datetime

    entry = {
        "src": src,
        "dst": dst,
        "trigger_xyz": list(trigger_xyz),
        "actual_xyz": list(actual_xyz),
        "ts": datetime.datetime.utcnow().isoformat(),
    }
    with _CALIBRATION.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")
    dx, dy, dz = (actual_xyz[i] - trigger_xyz[i] for i in range(3))
    logger.info(f"calibration: {src} → {dst}  offset=({dx:.1f}, {dy:.1f}, {dz:.1f})")


def _world_of(zone: str) -> str:
    return zone.split("/")[0] if "/" in zone else zone


def _ensure_world_header(path: Path, world: str) -> None:
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    if f"WORLD - {world}" not in text:
        with path.open("a", encoding="utf-8") as f:
            f.write(f"\nWORLD - {world}\n")
        logger.info(f"gate_recorder: added WORLD header for {world}")


def _append_gate(path: Path, src: str, x: float, y: float, z: float, dst: str) -> None:
    _ensure_world_header(path, _world_of(src))
    line = f"GATE;standard;{x};{y};{z};{src};{dst}\n"
    with path.open("a", encoding="utf-8") as f:
        f.write(line)
    logger.info(f"gate_recorder: wrote  {src} → {dst}  @ ({x:.1f}, {y:.1f}, {z:.1f})")


class GateRecorder:
    def __init__(self, client, zones_txt: Path = _ZONES_TXT):
        self._client = client
        self._path = zones_txt
        self._task: asyncio.Task | None = None
        self._running = False

    async def start(self) -> None:
        if self._task and not self._task.done():
            return
        self._running = True
        self._task = asyncio.create_task(self._loop(), name="gate_recorder")
        logger.info("gate_recorder: started — walk through gates to record them")

    async def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        logger.info("gate_recorder: stopped")

    @property
    def active(self) -> bool:
        return self._task is not None and not self._task.done()

    async def _loop(self) -> None:
        existing = _load_existing_gates(self._path)
        trigger_coords = _load_trigger_coords(self._path)
        prev_zone: str | None = None
        prev_x = prev_y = prev_z = 0.0

        while self._running:
            try:
                zone = await self._client.zone_name()
                if not zone:
                    await asyncio.sleep(_POLL_INTERVAL)
                    continue

                if prev_zone is None:
                    prev_zone = zone
                    try:
                        pos = await self._client.body.position()
                        prev_x, prev_y, prev_z = pos.x, pos.y, pos.z
                    except Exception:
                        pass
                    await asyncio.sleep(_POLL_INTERVAL)
                    continue

                if zone != prev_zone:
                    # zone change detected - prev_x/y/z is where the player
                    # was standing just before they crossed the gate
                    src, dst = prev_zone, zone
                    x, y, z = prev_x, prev_y, prev_z

                    pair = (src, dst)
                    if pair not in existing:
                        _append_gate(self._path, src, x, y, z, dst)
                        existing.add(pair)
                    else:
                        logger.debug(f"gate_recorder: skip duplicate {src} → {dst}")

                    # if a trigger-center coord exists for this pair, record calibration data
                    if pair in trigger_coords:
                        trig = trigger_coords[pair]
                        actual = (x, y, z)
                        if trig != actual:
                            _record_calibration(src, dst, trig, actual)

                    prev_zone = zone
                    # settle before reading position in the new zone
                    await asyncio.sleep(_SETTLE_DELAY)
                    try:
                        pos = await self._client.body.position()
                        prev_x, prev_y, prev_z = pos.x, pos.y, pos.z
                    except Exception:
                        pass
                else:
                    # same zone - update position continuously
                    try:
                        pos = await self._client.body.position()
                        prev_x, prev_y, prev_z = pos.x, pos.y, pos.z
                    except Exception:
                        pass

            except asyncio.CancelledError:
                return
            except Exception as exc:
                logger.debug(f"gate_recorder: poll error: {exc}")

            await asyncio.sleep(_POLL_INTERVAL)
