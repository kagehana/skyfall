from __future__ import annotations


import asyncio

import math

from dataclasses import dataclass

from pathlib import Path

from typing import Optional


from loguru import logger

from wizwalker import XYZ, Client

from wizwalker.constants import Keycode


_DATA = Path(__file__).parent / "data"

# upper bound on a single gate traversal. wait_for_zone_change() loops forever
# if the teleport onto a gate never triggers its transition (bad/stale gate
# coords, a gate that needs walking, etc.), which silently wedges to_zone() and
# anything that calls it. generous enough for any real load screen, short enough
# that a dead gate fails fast and surfaces as an exception the caller can handle
_GATE_TIMEOUT = 90.0


_HUBS = [
    "WizardCity/WC_Ravenwood_Teleporter",
    "WizardCity/WC_Ravenwood",
    "Krokotopia/KT_WorldTeleporter",
    "Krokotopia/KT_Hub",
    "Marleybone/Interiors/MB_WolfminsterAbbey",
    "Marleybone/MB_Hub",
    "DragonSpire/DS_Hub_Cathedral",
    "MooShu/Interiors/MS_Teleport_Chamber",
    "MooShu/MS_Hub",
    "Celestia/CL_Hub",
    "Wysteria/PA_Hub",
    "Grizzleheim/GH_MainHub",
    "Zafaria/ZF_Z00_Hub",
    "Avalon/AV_Z00_Hub",
    "Azteca/AZ_Z00_Zocalo",
    "Khrysalis/KR_Z00_Hub",
    "Polaris/PL_Z00_Walruskberg",
    "Mirage/MR_Z00_Hub",
    "Karamelle/KM_Z00_HUB",
    "Empyrea/EM_Z00_Aeriel_HUB",
    "Lemuria/LM_Z00_Hub",
]


_INTERACTIVE_WORLDS = {"Empyrea", "Karamelle", "Lemuria"}


_WORLD_LIST = [
    "WizardCity",
    "Krokotopia",
    "Marleybone",
    "MooShu",
    "DragonSpire",
    "Grizzleheim",
    "Celestia",
    "Wysteria",
    "Zafaria",
    "Avalon",
    "Azteca",
    "Khrysalis",
    "Polaris",
    "Arcanum",
    "Mirage",
    "Empyrea",
    "Karamelle",
    "Lemuria",
]

_ZONE_DOOR_OPTIONS = [
    "wbtnWizardCity",
    "wbtnKrokotopia",
    "wbtnMarleybone",
    "wbtnMooShu",
    "wbtnDragonSpire",
    "wbtnGrizzleheim",
    "wbtnCelestia",
    "wbtnWysteria",
    "wbtnZafaria",
    "wbtnAvalon",
    "wbtnAzteca",
    "wbtnKhrysalis",
    "wbtnPolaris",
    "wbtnArcanum",
    "wbtnMirage",
    "wbtnEmpyrea",
    "wbtnKaramelle",
    "wbtnLemuria",
]

_ZONE_DOOR_DISPLAY = [
    "Wizard City",
    "Krokotopia",
    "Marleybone",
    "MooShu",
    "Dragonspyre",
    "Grizzleheim",
    "Celestia",
    "Wysteria",
    "Zafaria",
    "Avalon",
    "Azteca",
    "Khrysalis",
    "Polaris",
    "Arcanum",
    "Mirage",
    "Empyrea",
    "Karamelle",
    "Lemuria",
]


@dataclass
class Gate:
    gate_type: str

    x: float

    y: float

    z: float

    from_zone: str

    to_zone: str


def _load_zones(
    path: Path,
) -> tuple[dict[str, list[str]], dict[tuple[str, str], Gate], dict[str, str]]:
    graph: dict[str, list[str]] = {}
    gates: dict[tuple[str, str], Gate] = {}
    entries: dict[str, str] = {}

    cur_world: Optional[str] = None

    for raw in path.read_text(encoding="utf-8").splitlines():
        s = raw.strip()

        if not s or s.startswith("#"):
            continue

        if s.startswith("WORLD"):
            cur_world = s.split("-", 1)[1].strip()
            continue

        if s == "END":
            cur_world = None
            continue

        if s.startswith("ENTRY;"):
            zone = s.split(";", 1)[1].strip()
            if cur_world is not None and zone:
                entries[cur_world] = zone
                graph.setdefault(zone, [])
            continue

        if s.startswith("GATE;"):
            parts = [p.strip() for p in s.split(";")]
            # GATE;gateType;x;y;z;from;to -> 7 parts
            if len(parts) < 7:
                continue
            _, gate_type, x, y, z, from_z, to_z = parts[:7]
            try:
                gates[(from_z, to_z)] = Gate(
                    gate_type, float(x), float(y), float(z), from_z, to_z
                )
            except ValueError:
                continue
            graph.setdefault(from_z, []).append(to_z)
            graph.setdefault(to_z, [])

    return graph, gates, entries


def _bfs_path(graph: dict[str, list[str]], start: str, end: str) -> list[str] | None:

    if start == end:
        return [start]

    adj: dict[str, set[str]] = {}

    for z, children in graph.items():
        adj.setdefault(z, set()).update(children)

        for c in children:
            adj.setdefault(c, set()).add(z)

    visited = {start}

    queue: list[list[str]] = [[start]]

    while queue:
        path = queue.pop(0)

        node = path[-1]

        for nb in adj.get(node, set()):
            if nb == end:
                return path + [nb]

            if nb not in visited:
                visited.add(nb)

                queue.append(path + [nb])

    return None


def _load_display_names(path: Path) -> dict[str, str]:

    out: dict[str, str] = {}

    for raw in path.read_text(encoding="utf-8").splitlines():
        s = raw.strip()

        if not s:
            continue

        parts = [p.strip() for p in s.split(";")]

        if len(parts) < 2:
            continue

        zone_path, display = parts[0], parts[1]

        if not zone_path or not display:
            continue

        out[display.lower()] = zone_path

    return out


def _load_per_world(path: Path) -> dict[str, list[list[str]]]:

    out: dict[str, list[list[str]]] = {}

    cur_world: Optional[str] = None

    cur_list: list[list[str]] = []

    for raw in path.read_text(encoding="utf-8").splitlines():
        s = raw.strip()

        if not s:
            continue

        if s.startswith("WORLD"):
            if cur_world is not None:
                out[cur_world] = cur_list

            cur_world = s.split("-", 1)[1].strip()

            cur_list = []

            continue

        if s == "END":
            if cur_world is not None:
                out[cur_world] = cur_list

                cur_world = None

                cur_list = []

            continue

        cur_list.append([p.strip() for p in s.split(";")])

    if cur_world is not None:
        out[cur_world] = cur_list

    return out


_graph_cache: Optional[dict[str, list[str]]] = None

_gates_cache: Optional[dict[tuple[str, str], Gate]] = None

_entries_cache: Optional[dict[str, str]] = None

_display_cache: Optional[dict[str, str]] = None

_iteleport_cache: Optional[dict[str, list[list[str]]]] = None

_unique_cache: Optional[dict[str, list[list[str]]]] = None


def _ensure_zones() -> None:
    global _graph_cache, _gates_cache, _entries_cache

    if _graph_cache is None or _gates_cache is None or _entries_cache is None:
        graph, gates, entries = _load_zones(_DATA / "zones.txt")
        _graph_cache = graph
        _gates_cache = gates
        _entries_cache = entries


def _graph() -> dict[str, list[str]]:
    _ensure_zones()
    return _graph_cache  # type: ignore[return-value]


def _gates() -> dict[tuple[str, str], Gate]:
    _ensure_zones()
    return _gates_cache  # type: ignore[return-value]


def _entries() -> dict[str, str]:
    _ensure_zones()
    return _entries_cache  # type: ignore[return-value]


def _displays() -> dict[str, str]:

    global _display_cache

    if _display_cache is None:
        _display_cache = _load_display_names(_DATA / "displayZones.txt")

    return _display_cache


def _iteleports() -> dict[str, list[list[str]]]:

    global _iteleport_cache

    if _iteleport_cache is None:
        _iteleport_cache = _load_per_world(_DATA / "interactiveTeleporters.txt")

    return _iteleport_cache


def _uniques() -> dict[str, list[list[str]]]:

    global _unique_cache

    if _unique_cache is None:
        _unique_cache = _load_per_world(_DATA / "uniqueObjectLocations.txt")

    return _unique_cache


def _world_of(zone: str) -> str:

    return zone.split("/", 1)[0]


async def _x_until_out_of_range(client: Client, gap: float = 0.4):

    while not await client.is_in_npc_range():
        await asyncio.sleep(0.05)

    while await client.is_in_npc_range():
        await asyncio.sleep(gap)

        await client.send_key(Keycode.X, 0.1)


async def _x_burst(client: Client, count: int = 5, gap: float = 0.1):

    for _ in range(count):
        await client.send_key(Keycode.X, gap)


async def _go_through_dialog(client: Client):

    while await client.is_in_dialog():
        await client.send_key(Keycode.SPACEBAR, 0.1)

    await asyncio.sleep(0.5)


async def _traverse_gate(client: Client, gate: Gate) -> None:

    tp = XYZ(gate.x, gate.y, gate.z)

    gt = gate.gate_type

    if gt == "standard":
        await client.teleport(tp)

        await client.wait_for_zone_change()

        return

    if gt == "dungeon":
        await client.teleport(tp)

        while not await client.is_in_npc_range():
            await asyncio.sleep(0.05)

        while await client.is_in_npc_range():
            await asyncio.sleep(0.8)

            await client.send_key(Keycode.X, 0.1)

            await client.send_key(Keycode.X, 0.1)

            await client.send_key(Keycode.X, 0.1)

        await client.wait_for_zone_change()

        return

    if gt == "dungeonExitConfirm":
        if await client.is_in_dialog():
            await _go_through_dialog(client)

        await client.teleport(tp)

        await client.mouse_handler.activate_mouseless()

        await asyncio.sleep(1)

        try:
            await client.mouse_handler.click_window_with_name("centerButton")

            await client.wait_for_zone_change()

        except ValueError:
            await asyncio.sleep(8)

        await client.mouse_handler.deactivate_mouseless()

        return

    if gt == "xNoWait":
        if await client.is_in_dialog():
            await _go_through_dialog(client)

        await client.teleport(tp)

        await _x_until_out_of_range(client)

        await client.wait_for_zone_change()

        return

    if gt == "xNoWaitMirageCaterwaulToCaravan":
        if await client.is_in_dialog():
            await _go_through_dialog(client)

        await client.teleport(tp)

        await asyncio.sleep(7)

        await _x_until_out_of_range(client)

        await client.wait_for_zone_change()

        return

    if gt == "xNoWaitPolaris":
        await client.teleport(tp)

        await asyncio.sleep(4)

        await _x_until_out_of_range(client)

        await client.wait_for_zone_change()

        return

    if gt == "xSkipRideKrok1":
        await client.teleport(XYZ(4521.9609375, 3189.564208984375, 25.792266845703125))

        await asyncio.sleep(1.5)

        await _x_until_out_of_range(client)

        await client.wait_for_zone_change()

        await _x_until_out_of_range(client)

        await client.wait_for_zone_change()

        return

    if gt == "xSkipRideKrok2":
        await client.teleport(
            XYZ(11749.1123046875, -189.94265747070312, 1219.797119140625)
        )

        await _x_until_out_of_range(client)

        await client.wait_for_zone_change()

        await _x_until_out_of_range(client)

        await client.wait_for_zone_change()

        return

    if gt == "xNoWaitSkipRideMarleyboneChelsea":
        await client.teleport(tp)

        await client.wait_for_zone_change()

        await _x_until_out_of_range(client)

        await client.wait_for_zone_change()

        return

    if gt == "xNoWaitSkipRideMarleyboneChelseaReturn":
        await client.teleport(tp)

        await client.wait_for_zone_change()

        await asyncio.sleep(0.3)

        await client.send_key(Keycode.X, 0.1)

        await client.wait_for_zone_change()

        return

    if gt == "xNoWaitSkipRideMarleyboneHyde":
        await client.teleport(tp)

        await client.wait_for_zone_change()

        await _x_until_out_of_range(client)

        await asyncio.sleep(4)

        return

    if gt == "xSkipRideMarleyboneIronworksReturn":
        await client.send_key(Keycode.PAGE_UP, 0.1)

        await client.wait_for_zone_change()

        return

    if gt == "xNoWaitSkipRideMarleyboneHydeReturn":
        await client.teleport(tp)

        await client.wait_for_zone_change()

        await _x_until_out_of_range(client)

        await client.wait_for_zone_change()

        return

    if gt == "dungeonSkipRideMarleyboneIronworks":
        await asyncio.sleep(1)

        await client.teleport(tp)

        await _x_until_out_of_range(client)

        await client.wait_for_zone_change()

        await _x_until_out_of_range(client)

        await client.wait_for_zone_change()

        return

    if gt == "xNoWaitKrokObelisk":
        await client.teleport(
            XYZ(-3287.2294921875, -2826.498779296875, -35.353118896484375)
        )

        while not await client.is_in_npc_range():
            await asyncio.sleep(0.05)

        while await client.is_in_npc_range():
            await asyncio.sleep(0.4)

            for _ in range(5):
                await client.send_key(Keycode.X, 0.1)

        await asyncio.sleep(0.5)

        await client.teleport(
            XYZ(-4532.013671875, -2590.87451171875, -35.353668212890625)
        )

        while not await client.is_in_npc_range():
            await asyncio.sleep(0.05)

        while await client.is_in_npc_range():
            await asyncio.sleep(0.4)

            for _ in range(5):
                await client.send_key(Keycode.X, 0.1)

        await asyncio.sleep(0.5)

        await client.teleport(
            XYZ(-4274.5419921875, -1374.5045166015625, -35.353607177734375)
        )

        while not await client.is_in_npc_range():
            await asyncio.sleep(0.05)

        await asyncio.sleep(0.5)

        while await client.is_in_npc_range():
            await asyncio.sleep(0.4)

            for _ in range(5):
                await client.send_key(Keycode.X, 0.1)

        await asyncio.sleep(20)

        await client.teleport(
            XYZ(-3364.827392578125, -1802.46630859375, -35.354522705078125)
        )

        await client.wait_for_zone_change()

        return

    if gt == "dungeonDragonSpireGrandChasm":
        await asyncio.sleep(1)

        await client.send_key(Keycode.PAGE_DOWN, 0.1)

        await client.teleport(tp)

        await asyncio.sleep(0.5)

        await _x_burst(client, 5)

        await client.wait_for_zone_change()

        await asyncio.sleep(0.3)

        await client.teleport(
            XYZ(1.292851448059082, 227.6787567138672, 24.999969482421875)
        )

        await asyncio.sleep(1)

        await _x_burst(client, 5)

        await asyncio.sleep(1)

        return

    if gt == "dungeonExitConfirmMana":
        for _ in range(3):
            await client.send_key(Keycode.PAGE_UP, 0.1)

        await client.wait_for_zone_change()

        return

    if gt == "xSkipRideDragonspireRoost":
        await client.send_key(Keycode.PAGE_DOWN)

        await client.teleport(tp)

        await _x_until_out_of_range(client)

        await client.wait_for_zone_change()

        for _ in range(5):
            await client.send_key(Keycode.SPACEBAR, 0.1)

        await asyncio.sleep(0.5)

        await _x_until_out_of_range(client)

        await client.wait_for_zone_change()

        for _ in range(5):
            await client.send_key(Keycode.SPACEBAR, 0.1)

        await asyncio.sleep(1.5)

        return

    if gt == "xNoWaitDragonSpireReturnToAcademy":
        await client.send_key(Keycode.PAGE_UP, 0.1)

        await client.wait_for_zone_change()

        return

    if gt == "dungeonExitConfirmCelestiaTemple":
        if await client.is_in_dialog():
            await _go_through_dialog(client)

        await asyncio.sleep(0.3)

        for _ in range(5):
            await client.send_key(Keycode.SPACEBAR, 0.1)

        await asyncio.sleep(1)

        await client.teleport(tp)

        await client.mouse_handler.activate_mouseless()

        await asyncio.sleep(1)

        try:
            await client.mouse_handler.click_window_with_name("centerButton")

        except ValueError:
            await asyncio.sleep(0.01)

        await client.mouse_handler.deactivate_mouseless()

        await client.wait_for_zone_change()

        return

    if gt == "khrysDungeon1":
        await client.teleport(tp)

        await asyncio.sleep(2)

        await _x_until_out_of_range(client)

        await client.wait_for_zone_change()

        await client.teleport(XYZ(1647.79248046875, 29.44374656677246, 6.103515625e-05))

        await client.wait_for_zone_change()

        await asyncio.sleep(2)

        return

    if gt == "khrysSerpentIsland":
        await client.teleport(tp)

        await client.wait_for_zone_change()

        await asyncio.sleep(2)

        await client.teleport(XYZ(1647.79248046875, 29.44374656677246, 6.103515625e-05))

        await asyncio.sleep(1)

        await _x_burst(client, 5)

        await asyncio.sleep(4)

        await client.teleport(XYZ(7662.78564453125, 7625.587890625, 1265.4591064453125))

        await asyncio.sleep(0.6)

        return

    await client.teleport(tp)

    await client.wait_for_zone_change()


async def _read_checkbox_text(window) -> str:

    return await window.read_wide_string_from_offset(616)


async def _navigate_world_door(client: Client, destination_world: str):

    while not await client.is_in_npc_range():
        await asyncio.sleep(0.05)

    while await client.is_in_npc_range():
        await client.send_key(Keycode.X, 0.1)

        await asyncio.sleep(0.4)

    await client.mouse_handler.activate_mouseless()

    try:
        option_window = await client.root_window.get_windows_with_name("optionWindow")

        if not option_window:
            return

        option_window = option_window[0]

        async def page_info():

            for ch in await option_window.children():
                if await ch.name() == "pageCount":
                    txt = await ch.maybe_text()

                    txt = txt[8:-9]

                    cur, mx = txt.split("/", 1)

                    return cur, mx

            return "1", "1"

        current_page, max_page = await page_info()

        while str(current_page) != "1":
            await client.mouse_handler.click_window_with_name("leftButton")

            await asyncio.sleep(0.2)

            current_page, _ = await page_info()

        try:
            world_index = _WORLD_LIST.index(destination_world)

        except ValueError:
            return

        spiral_name = _ZONE_DOOR_DISPLAY[world_index]

        found = False

        for _ in range(int(max_page)):
            for ch in await option_window.children():
                nm = await ch.name()

                if nm in ("opt0", "opt1", "opt2", "opt3"):
                    try:
                        text = await _read_checkbox_text(ch)

                    except Exception:
                        continue

                    if text == spiral_name:
                        await client.mouse_handler.click_window_with_name(
                            _ZONE_DOOR_OPTIONS[world_index]
                        )

                        await asyncio.sleep(0.4)

                        await client.mouse_handler.click_window_with_name(
                            "teleportButton"
                        )

                        await client.wait_for_zone_change()

                        await client.send_key(Keycode.W, 1.5)

                        found = True

                        break

            if found:
                break

            previous_page = current_page

            loop_count = 0

            while current_page == previous_page and loop_count < 30:
                loop_count += 1

                await client.mouse_handler.click_window_with_name("rightButton")

                current_page, _ = await page_info()

    finally:
        try:
            await client.mouse_handler.deactivate_mouseless()

        except Exception:
            pass


async def _interactive_teleport_click(client: Client, menu_button: int):

    while not await client.is_in_npc_range():
        await asyncio.sleep(0.05)

    while await client.is_in_npc_range():
        await client.send_key(Keycode.X, 0.1)

        await asyncio.sleep(0.4)

    await asyncio.sleep(0.4)

    await client.mouse_handler.activate_mouseless()

    try:
        actual = menu_button

        if menu_button > 4:
            page_num = int(math.ceil(menu_button / 4)) - 1

            for _ in range(page_num):
                await client.mouse_handler.click_window_with_name("rightButton")

                await asyncio.sleep(0.4)

            actual = menu_button - page_num * 4

        await client.mouse_handler.click_window_with_name(f"opt{actual - 1}")

        await asyncio.sleep(0.4)

        await client.mouse_handler.click_window_with_name("teleportButton")

        await client.wait_for_zone_change()

    finally:
        try:
            await client.mouse_handler.deactivate_mouseless()

        except Exception:
            pass


async def _try_interactive_teleport(
    client: Client, current_zone: str, destination_zone: str, world: str
) -> bool:

    rows = _iteleports().get(world, [])

    src_row: Optional[list[str]] = None

    dest_index: Optional[int] = None

    for row in rows:
        if len(row) < 5:
            continue

        if row[4] == current_zone and row[4] == destination_zone:
            return False

        if row[4] == current_zone:
            src_row = row

        elif row[4] == destination_zone:
            try:
                dest_index = int(row[0].split("_", 1)[1])

            except (ValueError, IndexError):
                continue

    if src_row is None or dest_index is None:
        return False

    try:
        await client.teleport(
            XYZ(float(src_row[1]), float(src_row[2]), float(src_row[3])),
            wait_on_inuse=True,
        )

    except TypeError:
        await client.teleport(
            XYZ(float(src_row[1]), float(src_row[2]), float(src_row[3]))
        )

    await asyncio.sleep(0.4)

    await _interactive_teleport_click(client, dest_index + 1)

    return True


async def _recall_to_hub(client: Client) -> str:

    current = await client.zone_name()

    while current not in _HUBS:
        await client.send_key(Keycode.END)

        await asyncio.sleep(0.6)

        new_zone = await client.zone_name()

        if new_zone == current:
            break

        current = new_zone

    await asyncio.sleep(3)

    return await client.zone_name()


async def _hop_to_world(client: Client, dest_world: str) -> None:

    current = await client.zone_name()

    current_world = _world_of(current)

    door_zone: Optional[str] = None

    door_xyz: Optional[tuple[float, float, float]] = None

    for row in _uniques().get(current_world, []):
        if row and row[0] == "ZONEDOOR" and len(row) >= 5:
            door_zone = row[4]

            try:
                door_xyz = (float(row[1]), float(row[2]), float(row[3]))

            except ValueError:
                door_xyz = None

            break

    if door_zone and door_zone != current:
        await _go_to_destination(client, door_zone)

    if door_xyz is not None:
        await client.teleport(XYZ(*door_xyz))

        await asyncio.sleep(2)

    await _navigate_world_door(client, dest_world)


async def _go_to_destination(client: Client, destination: str) -> None:

    graph = _graph()

    gates = _gates()

    # wait until the client is in a stable state before reading zone_name(),
    # otherwise we may plan a path off a stale/empty zone string and only
    # appear to "wake up" after the user triggers a zone change manually
    settle_deadline = 5.0
    settled = 0.0
    while settled < settle_deadline:
        try:
            if await client.is_loading():
                await asyncio.sleep(0.15)
                settled += 0.15
                continue
        except Exception:
            pass
        zn = await client.zone_name()
        if zn and zn.strip():
            break
        await asyncio.sleep(0.15)
        settled += 0.15

    for _ in range(30):
        current = await client.zone_name()

        if current.strip() == destination.strip():
            return

        current_world = _world_of(current)

        dest_world = _world_of(destination)

        if current_world != dest_world:
            await _hop_to_world(client, dest_world)

            continue

        if current not in graph:
            current = await _recall_to_hub(client)

            if current.strip() == destination.strip():
                return

        if current_world in _INTERACTIVE_WORLDS:
            if await _try_interactive_teleport(
                client, current, destination, current_world
            ):
                continue

        path = _bfs_path(graph, current, destination)

        if path is None:
            current = await _recall_to_hub(client)

            path = _bfs_path(graph, current, destination)

            if path is None:
                if current_world in _INTERACTIVE_WORLDS:
                    if await _try_interactive_teleport(
                        client, current, destination, current_world
                    ):
                        continue

                raise RuntimeError(
                    f"navigator: no path from {current!r} to {destination!r}"
                )

        progressed = False

        for i in range(len(path) - 1):
            here = await client.zone_name()

            if here.strip() == destination.strip():
                return

            if here != path[i]:
                break

            nxt = path[i + 1]

            gate = gates.get((here, nxt))

            if gate is None:
                if current_world in _INTERACTIVE_WORLDS:
                    if await _try_interactive_teleport(
                        client, here, nxt, current_world
                    ):
                        progressed = True

                        continue

                break

            logger.info(f"[navigator] {here} -> {nxt} via {gate.gate_type} gate")
            try:
                await asyncio.wait_for(
                    _traverse_gate(client, gate), timeout=_GATE_TIMEOUT
                )
            except asyncio.TimeoutError:
                raise RuntimeError(
                    f"navigator: gate {here!r} -> {nxt!r} timed out "
                    f"(no zone change after {_GATE_TIMEOUT:.0f}s)"
                )

            progressed = True

            new_zone = await client.zone_name()
            logger.debug(f"[navigator] arrived in {new_zone}")

            if current_world in _INTERACTIVE_WORLDS:
                await _try_interactive_teleport(
                    client, new_zone, destination, current_world
                )

                if (await client.zone_name()).strip() == destination.strip():
                    return

        if not progressed:
            raise RuntimeError(
                f"navigator: stuck at {await client.zone_name()!r} en route to {destination!r}"
            )

    final = await client.zone_name()

    if final.strip() != destination.strip():
        raise RuntimeError(
            f"navigator: gave up after 30 iterations at {final!r} (target {destination!r})"
        )


def _resolve_destination(destination: str) -> str:

    if "/" in destination:
        return destination

    key = destination.lower().strip()

    displays = _displays()

    if key in displays:
        return displays[key]

    for name, zone in displays.items():
        if key in name:
            return zone

    raise ValueError(f"navigator: unknown zone {destination!r}")


async def to_zone(clients: list[Client], destination: str) -> None:

    if not clients:
        return

    target = _resolve_destination(destination)

    await asyncio.gather(*(_go_to_destination(c, target) for c in clients))
