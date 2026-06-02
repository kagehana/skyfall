import asyncio

import math

import re

from time import perf_counter

from typing import List, Tuple


from loguru import logger

from wizwalker import XYZ, Client, Orient

from wizwalker.memory.memory_objects.camera_controller import CameraController


from src.inputs import param_input

from src.nav.client import EntityClient

from src.teleport import calculate_pitch, calculate_yaw

from src.utils import read_webpage


def _tokenize_camera_command(s: str) -> list[str]:

    return re.findall(r"\w+\([^)]*\)|\S+", s)


async def point_to_xyz(camera: CameraController, xyz: XYZ):

    camera_pos = await camera.position()

    yaw = calculate_yaw(camera_pos, xyz)

    pitch = calculate_pitch(camera_pos, xyz)

    await camera.write_yaw(yaw)

    await camera.write_pitch(pitch)


async def point_to_vague_entity(client: Client, entity_name: str):

    sprinter = EntityClient(client)

    entity = await sprinter.closest_vague(entity_name)

    entity_pos = await entity.location()

    await client.camera_freecam()

    camera = await client.game_client.free_camera_controller()

    await point_to_xyz(camera, entity_pos)


async def toggle_player_invis(client: Client, default_scale: float = 1.0):

    scale = await client.body.scale()

    if scale:
        await client.body.write_scale(0.0)

    else:
        await client.body.write_scale(default_scale)


async def glide_to(
    camera: CameraController,
    xyz_1: XYZ,
    xyz_2: XYZ,
    orientation: Orient,
    time: float,
    focus_xyz: XYZ = None,
):

    pitch, roll, yaw = orientation

    roll = await camera.roll()

    velocity = XYZ(
        (xyz_2.x - xyz_1.x) / time,
        (xyz_2.y - xyz_1.y) / time,
        (xyz_2.z - xyz_1.z) / time,
    )

    cur_xyz = xyz_1

    await camera.write_position(cur_xyz)

    start_time = perf_counter()

    prev_time = start_time

    while perf_counter() - start_time < time:
        now = perf_counter()

        dt = now - prev_time

        prev_time = now

        cur_xyz = XYZ(
            cur_xyz.x + (velocity.x * dt),
            cur_xyz.y + (velocity.y * dt),
            cur_xyz.z + (velocity.z * dt),
        )

        if focus_xyz:
            yaw = calculate_yaw(cur_xyz, focus_xyz)

            pitch = calculate_pitch(cur_xyz, focus_xyz)

            await camera.update_orientation(Orient(pitch, roll, yaw))

        else:
            await camera.update_orientation(Orient(pitch, roll, yaw))

        await camera.write_position(cur_xyz)

        await asyncio.sleep(0)


async def rotating_glide_to(
    camera: CameraController,
    xyz_1: XYZ,
    xyz_2: XYZ,
    time: float,
    degrees=Orient(0, 0, 0),
):

    rotation_velocity = Orient(
        math.radians(degrees.pitch) / time,
        math.radians(degrees.roll) / time,
        math.radians(degrees.yaw) / time,
    )

    pitch, roll, yaw = await camera.orientation()

    velocity = XYZ(
        (xyz_2.x - xyz_1.x) / time,
        (xyz_2.y - xyz_1.y) / time,
        (xyz_2.z - xyz_1.z) / time,
    )

    cur_xyz = xyz_1

    await camera.write_position(cur_xyz)

    start_time = perf_counter()

    prev_time = start_time

    while perf_counter() - start_time < time:
        now = perf_counter()

        dt = now - prev_time

        prev_time = now

        cur_xyz = XYZ(
            cur_xyz.x + (velocity.x * dt),
            cur_xyz.y + (velocity.y * dt),
            cur_xyz.z + (velocity.z * dt),
        )

        yaw += rotation_velocity.yaw * dt

        pitch += rotation_velocity.pitch * dt

        roll += rotation_velocity.roll * dt

        await camera.write_position(cur_xyz)

        await camera.update_orientation(Orient(pitch, roll, yaw))

        await asyncio.sleep(0)


async def orbit(
    camera: CameraController, xyz_1: XYZ, xyz_2: XYZ, degrees: float, time: float
):

    roll = await camera.roll()

    xy_radius = math.sqrt((xyz_2.x - xyz_1.x) ** 2 + (xyz_2.y - xyz_1.y) ** 2)

    angle_velocity = math.radians(degrees) / time

    cur_angle = math.atan2((xyz_2.y - xyz_1.y), (xyz_2.x - xyz_1.x))

    start_time = perf_counter()

    prev_time = start_time

    while perf_counter() - start_time < time:
        now = perf_counter()

        dt = now - prev_time

        prev_time = now

        cur_angle += angle_velocity * dt

        cur_xyz = XYZ(
            xyz_2.x - xy_radius * math.cos(cur_angle),
            xyz_2.y - xy_radius * math.sin(cur_angle),
            xyz_1.z,
        )

        await camera.write_position(cur_xyz)

        yaw = calculate_yaw(cur_xyz, xyz_2)

        pitch = calculate_pitch(cur_xyz, xyz_2)

        await camera.update_orientation(Orient(pitch, roll, yaw))

        await asyncio.sleep(0)


def _handle_index(input_list, i: int = 0, default=None):

    if len(input_list) <= i:
        return default

    return input_list[i]


async def _parse_location(
    split_command: list[str], camera: CameraController = None, client: Client = None
) -> Tuple[List[XYZ], List[Orient]]:

    split_command = [s.lower().replace(", ", "") for s in split_command.copy()]

    xyzs: List[XYZ] = []

    orientations: List[Orient] = []

    if camera:
        default_xyz = await camera.position()

        default_orientation = await camera.orientation()

    else:
        default_xyz = await client.body.position()

        default_orientation = await client.body.orientation()

    for arg in split_command:
        if "xyz" in arg:
            split_arg = arg.replace("xyz(", "").strip(")").split(",")

            xyzs.append(
                XYZ(
                    param_input(split_arg[0], default_xyz.x),
                    param_input(split_arg[1], default_xyz.y),
                    param_input(split_arg[2], default_xyz.z),
                )
            )

        elif "orient" in arg:
            split_arg = arg.replace("orient(", "").strip(")").split(",")

            orientations.append(
                Orient(
                    param_input(split_arg[0], default_orientation.pitch),
                    param_input(split_arg[1], default_orientation.roll),
                    param_input(split_arg[2], default_orientation.yaw),
                )
            )

    return (xyzs, orientations)


async def parse_camera_command(camera: CameraController, command_str: str):

    command_str = command_str.replace(", ", ",").replace("_", "")

    split_command = _tokenize_camera_command(command_str)

    if not split_command:
        return

    origin_pos = await camera.position()

    origin_orientation = await camera.orientation()

    xyzs, orientations = await _parse_location(split_command, camera)

    time = float(split_command[-1]) if split_command[-1].isdigit() else 0

    match split_command[0].lower():
        case "glideto":
            if len(xyzs) >= 2:
                logger.debug(
                    f"Gliding freecam from {origin_pos} to {_handle_index(xyzs)} while looking at {_handle_index(xyzs, 1)} over {time} seconds"
                )

            else:
                logger.debug(
                    f"Gliding freecam from {origin_pos} to {_handle_index(xyzs)} while orientated as {_handle_index(orientations)} over {time} seconds"
                )

            await glide_to(
                camera,
                origin_pos,
                _handle_index(xyzs),
                _handle_index(orientations, default=origin_orientation),
                time,
                _handle_index(xyzs, 1),
            )

        case "rotatingglideto":
            logger.debug(
                f"Gliding freecam from {origin_pos} to {_handle_index(xyzs)} while rotating {_handle_index(orientations)} degrees over {time} seconds"
            )

            await rotating_glide_to(
                camera,
                origin_pos,
                _handle_index(xyzs),
                time,
                _handle_index(orientations),
            )

        case "orbit":
            degrees = param_input(split_command[-2], 360)

            logger.debug(
                f"Orbiting freecam {degrees} degrees from {origin_pos} around {_handle_index(xyzs)} over {time} seconds"
            )

            await orbit(camera, origin_pos, _handle_index(xyzs), degrees, time)

        case "lookat":
            logger.debug(f"Pointing freecam at {_handle_index(xyzs)}")

            await point_to_xyz(camera, _handle_index(xyzs))

        case "setpos":
            logger.debug(f"Moving freecam to {_handle_index(xyzs)}")

            await camera.write_position(xyzs[0])

        case "setorient":
            await camera.update_orientation(_handle_index(orientations))

        case _:
            pass


async def execute_flythrough(
    client: Client, flythrough_data: str, line_seperator: str = "\n"
):

    flythrough_actions = flythrough_data.split(line_seperator)

    web_command_strs = {"webpage", "pull", "embed"}

    new_commands = []

    for command_str in flythrough_actions:
        tokens = _tokenize_camera_command(command_str)

        if tokens and tokens[0].lower() in web_command_strs:
            new_commands.extend(read_webpage(tokens[1]))

        else:
            new_commands.append(command_str)

    if not await client.game_client.is_freecam():
        await client.camera_freecam()

    camera = await client.game_client.free_camera_controller()

    for action in new_commands:
        await parse_camera_command(camera, action)
