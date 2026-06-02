from __future__ import annotations

import asyncio
import statistics

import wizwalker
from loguru import logger
from wizwalker import Keycode, XYZ
from wizwalker.client_handler import Client
from wizwalker.extensions.scripting import teleport_to_friend_from_list

from src import gui as sfgui
from src.teleport import navmap_tp


async def mass_key_press(
    foreground_client: Client,
    background_clients: list[Client],
    pressed_key_name: str,
    key,
    duration: float = 0.1,
    debug: bool = False,
):
    if debug and foreground_client:
        key_name = str(key).replace("Keycode.", "")
        logger.debug(
            f"{pressed_key_name} key pressed, sending {key_name} key press to all clients."
        )
    await asyncio.gather(
        *[p.send_key(key=key, seconds=duration) for p in background_clients]
    )
    if foreground_client:
        await foreground_client.send_key(key=key, seconds=duration)


async def sync_camera(client: Client, xyz: XYZ = None, yaw: float = None):
    if not xyz:
        xyz = await client.body.position()
    if not yaw:
        yaw = await client.body.yaw()
    xyz.z += 200
    camera = await client.game_client.free_camera_controller()
    await camera.write_position(xyz)
    await camera.write_yaw(yaw)


async def xyz_sync(
    foreground_client: Client,
    background_clients: list[Client],
    turn_after: bool = True,
    debug: bool = False,
):
    if not background_clients:
        return
    if foreground_client:
        xyz = await foreground_client.body.position()
        yaw = await foreground_client.body.yaw()
    else:
        first = background_clients[0]
        xyz = await first.body.position()
        yaw = await first.body.yaw()

    await asyncio.gather(*[p.teleport(xyz, yaw=yaw) for p in background_clients])
    if turn_after:
        await asyncio.gather(
            *[p.send_key(key=Keycode.A, seconds=0.1) for p in background_clients]
        )
        await asyncio.gather(
            *[p.send_key(key=Keycode.D, seconds=0.1) for p in background_clients]
        )
    await asyncio.sleep(0.3)


async def navmap_teleport(
    foreground_client: wizwalker.Client,
    background_clients: list[Client],
    mass_teleport: bool = False,
    debug: bool = False,
    xyz: XYZ = None,
):
    async def _single(client: Client, xyz: XYZ = None):
        if not xyz:
            xyz = await client.quest_position.position()
        await navmap_tp(client, xyz)

    clients_to_port: list[Client] = []
    if foreground_client:
        clients_to_port.append(foreground_client)
    if mass_teleport:
        clients_to_port.extend(background_clients)
        list_modes = statistics.multimode(
            [await c.quest_position.position() for c in clients_to_port]
        )
        zone_names = [await p.zone_name() for p in clients_to_port]
        if len(list_modes) == 1:
            xyz = list_modes[0]
        elif zone_names.count(zone_names[0]) == len(zone_names) and foreground_client:
            xyz = await foreground_client.quest_position.position()

    if not clients_to_port and background_clients:
        clients_to_port.append(background_clients[0])

    await asyncio.gather(*[_single(p, xyz) for p in clients_to_port])


async def friend_teleport_sync(clients: list[wizwalker.Client], debug: bool):
    for p in clients[1:]:
        async with p.mouse_handler:
            try:
                await teleport_to_friend_from_list(client=p, icon_list=1, icon_index=50)
            except Exception as e:
                logger.error(e)
                await asyncio.sleep(0)


async def kill_tool(debug: bool):
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    raise sfgui.ToolClosedException
