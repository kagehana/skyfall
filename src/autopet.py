import asyncio
import time


from loguru import logger


from wizwalker import (
    XYZ,
    Client,
    Keycode,
)


from src.dance import (
    attempt_activate_dance_hook,
    attempt_deactivate_dance_hook,
)

from src.paths import *

from src.teleport import navmap_tp

from src.utils import (
    FriendBusyOrInstanceClosed,
    LoadingScreenNotFound,
    click_window_by_path,
    get_popup_title,
    get_window_from_path,
    is_visible_by_path,
    navigate_to_commons_from_ravenwood,
    navigate_to_ravenwood,
    post_keys,
    safe_wait_for_zone_change,
)


# click_window_by_path already enters client.mouse_handler internally, so these
# helpers deliberately do not wrap it again


async def _wait_visible(
    client: Client, path, interval: float = 0.1, timeout: float = None
):
    deadline = None if timeout is None else time.monotonic() + timeout
    while not await is_visible_by_path(client, path):
        if deadline is not None and time.monotonic() >= deadline:
            return False
        await asyncio.sleep(interval)
    return True


async def _wait_gone(client: Client, path, interval: float = 0.1):
    while await is_visible_by_path(client, path):
        await asyncio.sleep(interval)


async def _click(client: Client, path, after: float = 0.0):
    await click_window_by_path(client, path)
    if after:
        await asyncio.sleep(after)


async def _click_until_gone(client: Client, path, interval: float = 0.2):
    while await is_visible_by_path(client, path):
        await click_window_by_path(client, path)
        await asyncio.sleep(interval)


async def _wait_out_level_up(client: Client, ignore: bool, window_path, exit_path):
    if not ignore:
        await _wait_gone(client, window_path, 1.0)
    else:
        while await is_visible_by_path(client, window_path):
            if await is_visible_by_path(client, exit_path):
                await _click(client, exit_path, 0.2)


async def navigate_to_pavilion_from_commons(cl: Client):

    pavilion_XYZ = XYZ(8426.3779296875, -2165.6982421875, -27.913818359375)

    await navmap_tp(cl, pavilion_XYZ)

    await cl.wait_for_zone_change(name="WizardCity/WC_Hub")

    await asyncio.sleep(2.0)


async def navigate_to_dance_game(cl: Client):

    await cl.goto(x=-1738.7811279296875, y=-387.345458984375)

    await cl.goto(x=-4090.10888671875, y=-1186.3660888671875)

    await cl.goto(x=-4449.36669921875, y=-992.9967651367188)


async def nomnom(client: Client, ignore_pet_level_up: bool, only_play_dance_game: bool):

    finished_feeding = False

    dance_hook_activated = False

    while not finished_feeding:
        popup_title = await get_popup_title(client)

        while popup_title != "Dance Game":
            await asyncio.sleep(0.125)
            popup_title = await get_popup_title(client)

        while not await is_visible_by_path(client, pet_feed_window_visible_path):
            while popup_title == "Dance Game":
                await client.send_key(Keycode.X, 0.1)
                popup_title = await get_popup_title(client)
                await asyncio.sleep(0.125)

            popup_title = await get_popup_title(client)
            await asyncio.sleep(0.125)

        client.feeding_pet_status = True

        energy_cost_txt = await get_window_from_path(
            client.root_window, pet_feed_window_energy_cost_textbox_path
        )

        total_energy_txt = await get_window_from_path(
            client.root_window, pet_feed_window_your_energy_textbox_path
        )

        energy_cost = int((await energy_cost_txt.maybe_text())[8:])

        total_energy = int((await total_energy_txt.maybe_text())[8:].split("/", 1)[0])

        if total_energy >= energy_cost:
            if (
                only_play_dance_game
                or not await is_visible_by_path(client, skip_pet_game_button_path)
            ) and not dance_hook_activated:
                logger.debug(f"Client {client.title}: Activating dance game hook.")

                await attempt_activate_dance_hook(client, sleep_time=5.0)

                dance_hook_activated = True

            if (
                await is_visible_by_path(client, skip_pet_game_button_path)
                and not only_play_dance_game
            ):
                while await is_visible_by_path(client, pet_feed_window_visible_path):
                    if await is_visible_by_path(client, skip_pet_game_button_path):
                        await _click(client, skip_pet_game_button_path, 0.2)

                await _wait_visible(client, skipped_pet_game_rewards_window_path)

                if await is_visible_by_path(
                    client, skipped_pet_game_continue_and_feed_button_path
                ):
                    await click_window_by_path(
                        client, skipped_pet_game_continue_and_feed_button_path
                    )
                    await _wait_visible(
                        client, skipped_first_pet_snack_path, timeout=1.5
                    )

                if await is_visible_by_path(client, skipped_first_pet_snack_path):
                    await click_window_by_path(client, skipped_first_pet_snack_path)
                    await _wait_visible(
                        client,
                        skipped_pet_game_continue_and_feed_button_path,
                        timeout=0.6,
                    )

                    if await is_visible_by_path(
                        client, skipped_pet_game_continue_and_feed_button_path
                    ):
                        await _click(
                            client, skipped_pet_game_continue_and_feed_button_path, 1.0
                        )

                        if await is_visible_by_path(
                            client, skipped_pet_leveled_up_window_path
                        ):
                            await _wait_out_level_up(
                                client,
                                ignore_pet_level_up,
                                skipped_pet_leveled_up_window_path,
                                exit_skipped_pet_leveled_up_path,
                            )

                        await _wait_visible(client, skipped_finish_pet_button)

                        await _click_until_gone(client, skipped_finish_pet_button)

                        await _wait_gone(client, skipped_pet_game_rewards_window_path)

                else:
                    logger.info(f"Auto Pet - Client {client.title} is out of snacks.")

                    finished_feeding = True

                await asyncio.sleep(0.5)

            else:
                while await is_visible_by_path(client, pet_feed_window_visible_path):
                    await client.send_key(Keycode.X, 0.1)

                    if await is_visible_by_path(client, wizard_city_dance_game_path):
                        await _click(client, wizard_city_dance_game_path, 0.2)

                    if await is_visible_by_path(client, play_dance_game_button_path):
                        await _click(client, play_dance_game_button_path, 0.1)

                await dancedance(client)

                if await is_visible_by_path(client, won_pet_leveled_up_window_path):
                    await won_game_leveled_up(client, ignore_pet_level_up)

                if await is_visible_by_path(
                    client, won_pet_game_continue_and_feed_button_path
                ):
                    await click_window_by_path(
                        client, won_pet_game_continue_and_feed_button_path
                    )
                    await _wait_visible(client, won_first_pet_snack_path, timeout=1.5)

                if await is_visible_by_path(client, won_first_pet_snack_path):
                    await click_window_by_path(client, won_first_pet_snack_path)
                    await _wait_visible(
                        client, won_pet_game_continue_and_feed_button_path, timeout=0.6
                    )

                    if await is_visible_by_path(
                        client, won_pet_game_continue_and_feed_button_path
                    ):
                        await won_game_leveled_up(client, ignore_pet_level_up)

                        await _wait_visible(client, won_finish_pet_button)

                        await _click_until_gone(client, won_finish_pet_button)

                        await _wait_gone(client, won_pet_game_rewards_window_path)

                else:
                    logger.info(f"Auto Pet - Client {client.title} is out of snacks.")

                    finished_feeding = True

                await asyncio.sleep(0.5)

        else:
            logger.info(f"Auto Pet - Client {client.title} is out of energy.")

            finished_feeding = True

    while await is_visible_by_path(client, pet_feed_window_visible_path):
        if await is_visible_by_path(client, pet_feed_window_cancel_button_path):
            await _click(client, pet_feed_window_cancel_button_path, 0.2)

    if dance_hook_activated:
        logger.debug(f"Client {client.title}: Deactivating dance game hook.")

        await attempt_deactivate_dance_hook(client)

    client.feeding_pet_status = False

    while await get_popup_title(client) == "Dance Game":
        await asyncio.sleep(0.125)


async def dancedance(client: Client):

    while not await is_visible_by_path(client, dance_game_action_textbox_path):
        await asyncio.sleep(0.1)

    action_window = await get_window_from_path(
        client.root_window, dance_game_action_textbox_path
    )

    for _ in range(5):
        while await action_window.maybe_text() == "<center>Go!":
            await asyncio.sleep(0.125)

        while await action_window.maybe_text() != "<center>Go!":
            await asyncio.sleep(0.125)

        await asyncio.sleep(1.5)

        await post_keys(
            client, await client.hook_handler.read_current_dance_game_moves()
        )

    await asyncio.sleep(3)


async def won_game_leveled_up(client: Client, auto_pet_ignore_pet_level_up):

    await _click(client, won_pet_game_continue_and_feed_button_path, 1.0)

    if await is_visible_by_path(client, won_pet_leveled_up_window_path):
        await _wait_out_level_up(
            client,
            auto_pet_ignore_pet_level_up,
            won_pet_leveled_up_window_path,
            exit_won_pet_leveled_up_path,
        )


async def auto_pet(
    client: Client,
    ignore_pet_level_up: bool,
    only_play_dance_game: bool,
    questing: bool = False,
):

    client.feeding_pet_status = True

    started_at_pavilion = False

    if await client.zone_name() != "WizardCity/WC_Streets/Interiors/WC_PET_Park":
        await guarantee_teleport_mark(client)

        await asyncio.sleep(0.5)

        await navigate_to_ravenwood(client)

        await navigate_to_commons_from_ravenwood(client)

        await navigate_to_pavilion_from_commons(client)

        await navigate_to_dance_game(client)

    else:
        started_at_pavilion = True

        try:
            await client.teleport(
                XYZ(x=-4450.57958984375, y=-994.8973388671875, z=-8.041412353515625)
            )

        except ValueError:
            await asyncio.sleep(3.0)

            await client.teleport(
                XYZ(x=-4450.57958984375, y=-994.8973388671875, z=-8.041412353515625)
            )

    if questing:
        client.character_level = await client.stats.reference_level()

    while client.feeding_pet_status:
        await asyncio.sleep(0.1)

    await asyncio.sleep(1.0)

    if not started_at_pavilion:
        await client.send_key(Keycode.PAGE_UP, 0.1)

        while True:
            try:
                await safe_wait_for_zone_change(
                    client,
                    name="WizardCity/WC_Streets/Interiors/WC_PET_Park",
                    handle_hooks_if_needed=True,
                )

                break

            except LoadingScreenNotFound:
                logger.debug(
                    f"Client {client.title} failed to recall from pet pavilion."
                )

                pass

            except FriendBusyOrInstanceClosed:
                logger.debug(
                    f"Client {client.title} failed to recall from pet pavilion - "
                    "instance was closed."
                )

                break
