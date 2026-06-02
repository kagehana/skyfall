import asyncio

import re

from typing import List


from loguru import logger

from wizwalker import Client

from wizwalker.memory.memory_object import Primitive


from src.paths import (
    channel_one_chat_channel_path,
    channel_three_chat_channel_path,
    channel_two_chat_channel_path,
    chat_window_path,
    friend_chat_channel_path,
    group_chat_channel_path,
    guild_chat_channel_path,
    house_chat_channel_path,
    main_chat_channel_path,
    team_up_chat_channel_path,
)

from src.utils import get_window_from_path, is_visible_by_path


drop_types = [
    "PetSnack",
    "Reagent",
    "Housing",
    "Pet",
    "Shoes",
    "Seed",
    "Jewel",
    "Robe",
    "Hat",
    "Athame",
    "Weapon",
    "Deck",
    "Ring",
    "Amulet",
]


chat_channel_list = [
    main_chat_channel_path,
    group_chat_channel_path,
    house_chat_channel_path,
    friend_chat_channel_path,
    channel_one_chat_channel_path,
    channel_two_chat_channel_path,
    channel_three_chat_channel_path,
    guild_chat_channel_path,
    team_up_chat_channel_path,
]


async def get_chat(client: Client) -> str:

    if await is_visible_by_path(client, chat_window_path):
        chat_window = await get_window_from_path(client.root_window, chat_window_path)

        if chat_window:
            raw_chat_text = await chat_window.maybe_text()

            return raw_chat_text

        else:
            return ""

    else:
        return ""


async def get_current_active_chat_channel(client: Client) -> List[str]:

    for window_path in chat_channel_list:
        if await is_visible_by_path(client, window_path):
            channel_window = await get_window_from_path(client.root_window, window_path)

            if channel_window:
                if await channel_window.read_value_from_offset(872, Primitive.bool):
                    return window_path

    return None


def filter_drops(input_list: List[str]) -> List[str]:

    drops = []

    for raw_i in input_list.copy():
        if "Art_Chat_System.dds" in raw_i:
            i = re.findall("(?<=> <).*|$", raw_i)[0]

            if i:
                if ";" in i:
                    drop_type: str = re.findall("(?<=;).*?[^>]*|$", i)[0]

                if drop_type in drop_types:
                    raw_drop: str = re.findall(">.*?<|$", i)[0]

                    drop: str = re.findall("[^>]+[^<]+|$", raw_drop)[0]

                    drop = drop.replace(" ", "", 1)

                    drops.append(drop)

            elif ":" in raw_i.lower():
                drop: str = re.findall("(?<=:).*?[^<]*|$", raw_i)[0]

                drop = drop.replace(" ", "", 1)

                drops.append(drop)

    return drops


def find_new_stuff(old: str, new: str) -> str:

    found_idx = -1

    while True:
        found_idx = new.find(old)

        if found_idx >= 0:
            break

        old = old[1:]

        if len(old) == 0:
            break

    if found_idx < 0:
        return new

    return new[found_idx + len(old) :]


async def logging_loop(client: Client):

    chat_text = await get_chat(client)

    if chat_text:
        temp_drops = filter_drops(chat_text.split("\n"))

        client.latest_drops = "\n".join(temp_drops)

    current_channel = await get_current_active_chat_channel(client)

    while True:
        await asyncio.sleep(1)

        if await is_visible_by_path(client, chat_window_path):
            chat_text = await get_chat(client)

            temp_drops = filter_drops(chat_text.split("\n"))

            temp_channel = await get_current_active_chat_channel(client)

            if current_channel != temp_channel:
                client.latest_drops = "\n".join(temp_drops)

                current_channel = temp_channel

            else:
                new_drops = find_new_stuff(client.latest_drops, "\n".join(temp_drops))

                client.latest_drops = "\n".join(temp_drops)

                if new_drops:
                    new_drops_list = new_drops.split("\n")

                    if len(new_drops_list) > 1 and not new_drops_list[0]:
                        new_drops_list.pop(0)

                    [
                        logger.debug(f"{client.title} New Drop: {drop}")
                        for drop in new_drops_list
                    ]
