import asyncio

import math

import struct

from copy import copy

from io import BytesIO

from typing import Tuple, Union


from wizwalker import XYZ, Client, Keycode

from wizwalker.file_readers.wad import Wad


from src.utils import is_free, wait_until


type_format_dict = {
    "char": "<c",
    "signed char": "<b",
    "unsigned char": "<B",
    "bool": "?",
    "short": "<h",
    "unsigned short": "<H",
    "int": "<i",
    "unsigned int": "<I",
    "long": "<l",
    "unsigned long": "<L",
    "long long": "<q",
    "unsigned long long": "<Q",
    "float": "<f",
    "double": "<d",
}


class TypedBytes(BytesIO):
    def split(self, index: int) -> Tuple["TypedBytes", "TypedBytes"]:

        self.seek(0)

        buffer = self.read(index)

        return type(self)(buffer), type(self)(self.read())

    def read_typed(self, type_name: str):

        type_format = type_format_dict[type_name]

        size = struct.calcsize(type_format)

        data = self.read(size)

        return struct.unpack(type_format, data)[0]


def parse_nav_data(file_data: Union[bytes, TypedBytes]):

    if isinstance(file_data, bytes):
        file_data = TypedBytes(file_data)

    file_data.read_typed("short")

    vertex_max = file_data.read_typed("short")

    file_data.read_typed("short")

    vertices = []

    idx = 0

    while idx <= vertex_max - 1:
        x = file_data.read_typed("float")

        y = file_data.read_typed("float")

        z = file_data.read_typed("float")

        vertices.append(XYZ(x, y, z))

        vertex_index = file_data.read_typed("short")

        if vertex_index != idx:
            vertices.pop()

            vertex_max -= 1

        else:
            idx += 1

    edge_count = file_data.read_typed("int")

    edges = []

    for idx in range(edge_count):
        start = file_data.read_typed("short")

        stop = file_data.read_typed("short")

        edges.append((start, stop))

    return vertices, edges


def get_neighbors(vertex: XYZ, vertices: list[XYZ], edges: list[(int, int)]):

    vert_idx = -1

    for v in vertices:
        vert_idx += 1

        if v == vertex:
            break

    if vert_idx == -1:
        return []

    result = []

    for edge in edges:
        if edge[0] == vert_idx:
            result.append(vertices[edge[1]])

    return result


def calc_PointOn3DLine(xyz_1: XYZ, xyz_2: XYZ, additional_distance):

    distance = calc_Distance(xyz_1, xyz_2)

    if distance < 1.0:
        return xyz_1

    else:
        n = (distance - additional_distance) / distance

        return XYZ(
            x=((xyz_2.x - xyz_1.x) * n) + xyz_1.x,
            y=((xyz_2.y - xyz_1.y) * n) + xyz_1.y,
            z=((xyz_2.z - xyz_1.z) * n) + xyz_1.z,
        )


def are_xyzs_within_threshold(xyz_1: XYZ, xyz_2: XYZ, threshold: int = 200):

    threshold_check = [
        abs(abs(xyz_1.x) - abs(xyz_2.x)) < threshold,
        abs(abs(xyz_1.y) - abs(xyz_2.y)) < threshold,
        abs(abs(xyz_1.z) - abs(xyz_2.z)) < threshold,
    ]

    return all(threshold_check)


def calc_squareDistance(xyz_1: XYZ, xyz_2: XYZ):

    return (
        (pow(xyz_1.x - xyz_2.x, 2.0))
        + (pow(xyz_1.y - xyz_2.y, 2.0))
        + (pow(xyz_1.z - xyz_2.z, 2.0))
    )


def calc_Distance(xyz_1: XYZ, xyz_2: XYZ):

    return math.sqrt(calc_squareDistance(xyz_1, xyz_2))


async def calc_FrontalVector(
    client: Client,
    xyz: XYZ = None,
    yaw: float = None,
    speed_constant: int = 580,
    speed_adjusted: bool = True,
    length_adjusted: bool = True,
):

    if speed_adjusted:
        current_speed = await client.client_object.speed_multiplier()

    else:
        current_speed = 0

    if not xyz:
        xyz = await client.body.position()

    if not yaw:
        yaw = await client.body.yaw()

    else:
        yaw = yaw

    additional_distance = speed_constant * ((current_speed / 100) + 1)

    frontal_x = xyz.x - (additional_distance * math.sin(yaw))

    frontal_y = xyz.y - (additional_distance * math.cos(yaw))

    frontal_xyz = XYZ(x=frontal_x, y=frontal_y, z=xyz.z)

    if length_adjusted:
        distance = calc_Distance(xyz, frontal_xyz)

        final_xyz = calc_PointOn3DLine(
            xyz_1=xyz,
            xyz_2=frontal_xyz,
            additional_distance=(additional_distance - distance),
        )

    else:
        final_xyz = frontal_xyz

    return final_xyz


async def load_wad(path: str):

    if path is not None:
        return Wad.from_game_data(path.replace("/", "-"))


async def teleport_move_adjust(client: Client, xyz: XYZ, delay: float = 0.7):

    if await is_free(client):
        try:
            await client.teleport(
                xyz, wait_on_inuse=True, purge_on_after_unuser_fixer=True
            )

        except Exception:
            pass

        await asyncio.sleep(delay)

        await client.send_key(Keycode.A, 0.05)

        await client.send_key(Keycode.D, 0.05)

    else:
        await asyncio.sleep(0.5)


def rotate_point(origin_xyz: XYZ, point_xyz: XYZ, theta):

    radians = math.radians(theta)

    cos = math.cos(radians)

    sin = math.sin(radians)

    y_diff = point_xyz.y - origin_xyz.y

    x_diff = point_xyz.x - origin_xyz.x

    x = cos * x_diff - sin * y_diff + origin_xyz.x

    y = sin * x_diff + cos * y_diff + origin_xyz.y

    return XYZ(x=x, y=y, z=point_xyz.z)


async def auto_adjusting_teleport(client: Client, quest_position: XYZ = None):

    original_zone_name = await client.zone_name()

    original_position = await client.body.position()

    if not quest_position:
        quest_position = await client.quest_position.position()

    adjusted_position = quest_position

    mod_amount = 50

    current_angle = 0

    if await is_free(client):
        await teleport_move_adjust(client, quest_position)

    else:
        return

    while (
        are_xyzs_within_threshold((await client.body.position()), original_position, 50)
        and await client.zone_name() == original_zone_name
    ):
        if not await is_free(client):
            return

        elif not are_xyzs_within_threshold(original_position, quest_position, 1):
            adjusted_position = calc_PointOn3DLine(
                original_position, quest_position, mod_amount
            )

            rotated_position = rotate_point(
                quest_position, adjusted_position, current_angle
            )

            if await is_free(client):
                await teleport_move_adjust(client, rotated_position)

            else:
                return

            mod_amount += 100

            current_angle += 92

        else:
            break


async def fallback_spiral_tp(client: Client, xyz: XYZ):

    await auto_adjusting_teleport(client, xyz)


async def navmap_tp(client: Client, xyz: XYZ = None, leader_client: Client = None):

    if not await is_free(client):
        return

    starting_zone = await client.zone_name()

    starting_xyz = await client.body.position()

    target_xyz = xyz if xyz is not None else await client.quest_position.position()

    def check_sigma(a: XYZ, b: XYZ, sigma=5.0):

        return calc_Distance(a, b) <= sigma

    async def moved_from_start():

        return not check_sigma(await client.body.position(), starting_xyz)

    async def check_success():

        return await wait_until(moved_from_start, timeout=1.0)

    async def finished_tp():

        return (
            await check_success()
            or not await is_free(client)
            or await client.zone_name() != starting_zone
        )

    if check_sigma(starting_xyz, target_xyz):
        return

    await client.teleport(target_xyz)

    if await finished_tp():
        return

    try:
        wad = await load_wad(starting_zone)

        nav_file = await wad.get_file("zone.nav")

        vertices, edges = parse_nav_data(nav_file)

    except Exception:
        await fallback_spiral_tp(client, target_xyz)

        return

    closest_vertex = vertices[0]

    lowest_distance = calc_Distance(closest_vertex, target_xyz)

    for i in range(1, len(vertices)):
        vertex = vertices[i]

        vert_dist = calc_Distance(vertex, target_xyz)

        if vert_dist < lowest_distance:
            closest_vertex = vertex

            lowest_distance = vert_dist

    max_depth = 3

    queue = [[closest_vertex]]

    relevant = set()

    while len(queue) > 0:
        path = queue.pop()

        v = path[-1]

        relevant.add(v)

        for neighbor in get_neighbors(v, vertices, edges):
            if neighbor in relevant or len(path) + 1 > max_depth:
                continue

            new_path = list(path)

            new_path.append(neighbor)

            queue.append(new_path)

    avg_xyz = XYZ(0, 0, 0)

    for v in relevant:
        avg_xyz.x += v.x

        avg_xyz.y += v.y

        avg_xyz.z += v.z

    avg_xyz = XYZ(
        avg_xyz.x / len(relevant), avg_xyz.y / len(relevant), avg_xyz.z / len(relevant)
    )

    av = XYZ(
        target_xyz.x - avg_xyz.x, target_xyz.y - avg_xyz.y, avg_xyz.z - target_xyz.z
    )

    ap2 = XYZ(avg_xyz.x + av.x / 2, avg_xyz.y + av.y / 2, avg_xyz.z + av.z / 2)

    await client.teleport(ap2)

    if await check_success():
        if await is_free(client) and await client.zone_name() == starting_zone:
            await client.goto(target_xyz.x, target_xyz.y)

        return

    await client.teleport(avg_xyz)

    if await check_success():
        if await is_free(client) and await client.zone_name() == starting_zone:
            await client.goto(target_xyz.x, target_xyz.y)

        return

    await fallback_spiral_tp(client, target_xyz)


def calc_chunks(points: list[XYZ], entity_distance: float = 3147.0) -> list[XYZ]:

    min_pos = XYZ(0, 0, 0)

    max_pos = XYZ(0, 0, 0)

    for point in points:
        if point.x < min_pos.x:
            min_pos.x = point.x

        if point.y < min_pos.y:
            min_pos.y = point.x

        if point.x > max_pos.x:
            max_pos.x = point.x

        if point.y > max_pos.y:
            max_pos.y = point.y

    side_length = math.sqrt(2) * entity_distance

    half_side_length = side_length / 2

    min_pos.x += half_side_length

    min_pos.y += half_side_length

    max_pos.x -= half_side_length

    max_pos.y -= half_side_length

    def point_in_rect(top_left: XYZ, bottom_right: XYZ, point: XYZ) -> bool:

        return (
            point.x >= top_left.x
            and point.x < bottom_right.x
            and point.y >= top_left.y
            and point.y < bottom_right.y
        )

    current_point = XYZ(min_pos.x - side_length, min_pos.y, 0)

    chunk_points = []

    leftover_points = set(points)

    while True:
        current_point.x += side_length

        if current_point.x - half_side_length > max_pos.x:
            current_point.x = min_pos.x

            current_point.y += side_length

            if current_point.y - half_side_length > max_pos.y:
                break

        square_top_left = XYZ(
            current_point.x - half_side_length, current_point.y - half_side_length, 0
        )

        square_bottom_right = XYZ(
            current_point.x + half_side_length, current_point.y + half_side_length, 0
        )

        contained_points = set([])

        for p in leftover_points:
            if point_in_rect(square_top_left, square_bottom_right, p):
                contained_points.add(p)

        leftover_points = leftover_points - contained_points

        if len(contained_points) > 0:
            chunk_points.append(copy(current_point))

    return chunk_points


def calculate_yaw(xyz_1: XYZ, xyz_2: XYZ) -> float:

    dx = xyz_1.x - xyz_2.x

    dy = xyz_1.y - xyz_2.y

    return math.atan2(dx, dy)


def calculate_pitch(xyz_1: XYZ, xyz_2: XYZ) -> float:

    x = xyz_2.x - xyz_1.x

    y = xyz_2.y - xyz_1.y

    z = xyz_2.z - xyz_1.z

    return -math.atan2(z, math.sqrt(x**2 + y**2))
