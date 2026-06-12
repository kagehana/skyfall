import asyncio
import ctypes
import datetime
import os
import queue
import re
import subprocess
import sys
import threading
import time
import traceback

import pyperclip
import wizwalker
from src import launcher as wizlaunch
from loguru import logger
from pypresence import AioPresence
from wizwalker import XYZ, HotkeyListener, Keycode, ModifierKeys, Orient, utils
from wizwalker.client_handler import Client, ClientHandler
from wizwalker.memory.memory_objects.camera_controller import (
    DynamicCameraController,
    ElasticCameraController,
)
from wizwalker.memory.memory_objects.window import Window
from wizwalker.utils import get_all_wizard_handles

from src import gui as sfgui
from src.autopet import nomnom
from src.camera import execute_flythrough
from src.factory import (
    default_config,
    delegate_combat_configs,
)
from src.drops import logging_loop
from src.fishing import FishConfig, Fisher
from src.gui import GUIKeys
from src.inputs import param_input, trunc
from src.paths import advance_dialog_path, play_button_path
from src.questing import Quester
from src.settings import SkyFallSettings
from src.combat import handler as combat_handler
from src.combat.handler import NativeCombat
from src.lang.bridge import LuaBridge
from src.nav.navigator import to_zone
from src.sigil import Sigil
from src.nav.client import EntityClient
from src.viewer import total_stats
from src.combat.snapshot import build_snapshot as build_combat_snapshot
from src.teleport import calc_Distance
from src.utils import (
    auto_potions,
    auto_potions_force_buy,
    collect_wisps_with_limit,
    get_window_from_path,
    is_free,
    is_visible_by_path,
    override_wiz_install_using_handle,
    to_world,
    try_task_coro,
)
from src.screen import get_camera_state, project_point

cMessageBox = ctypes.windll.user32.MessageBoxW

# persists across UI-tree dumps. key is (process_id, vtable) - vtables are
# stable for the lifetime of the game process, and Wizard101 reuses a small
# set of window types, so the second-and-subsequent dump skips the
# maybe_read_type_name reads entirely
_UI_TYPE_CACHE: dict[tuple[int, int], str] = {}

# vtables whose instances have only ever returned no text. skipping
# maybe_text() for these saves a read per node, and most nodes are textless
# containers. promoted after many samples, demoted the moment we see real text,
# so an occasionally-texty window class self-corrects
_UI_NOTEXT_VTABLES: dict[int, set[int]] = {}  # pid -> set of vtables
_UI_VTABLE_SEEN: dict[tuple[int, int], int] = {}  # (pid, vtable) -> sample count
_NOTEXT_PROMOTE_AFTER = 8

# short-TTL cache of the last completed dump per pid. repeated quick opens of
# the popup (peek, close, peek again) reuse the prior result rather than
# re-walking memory. TTL is small so the data stays plausible during play.
_UI_TREE_CACHE: dict[int, tuple[float, list]] = {}  # pid -> (ts, rows)
_UI_TREE_TTL = 2.5

tool_version: str = "3.13.0"
tool_name: str = "SkyFall"
tool_author: str = "SkyFall-Wizard101"

speed_multiplier = 5.0
use_potions = True
rpc_status = True
drop_status = True
anti_afk_status = True
gui_on_top = True
gui_langcode = "en"
gui_font = "Segoe UI"
gui_font_size = 9
use_team_up = False
team_up_type = "questing"
team_up_size = "2"
buy_potions = True
client_to_follow = None
client_to_boost = None
# window titles (e.g. ["p2"]) excluded from the questing loop entirely:
# neither spawns its own Quester nor appears in the leader's self.clients.
# Set via Settings → Questing → "Exclude from Questing" checkbox row
quest_excluded_clients: list[str] = []
questing_friend_tp = False
gear_switching_in_solo_zones = False
hitter_client = None
kill_minions_first = False
automatic_team_based_combat = False
discard_duplicate_cards = True
ignore_pet_level_up = False
only_play_dance_game = False

settings = SkyFallSettings()
settings.migrate_theme_from_settings()


theme_dict = settings.get_theme()


_json_settings = settings.get_settings()
speed_multiplier = _json_settings.get("speed_multiplier", speed_multiplier)
use_potions = _json_settings.get("use_potions", use_potions)
rpc_status = _json_settings.get("rich_presence", rpc_status)
drop_status = _json_settings.get("drop_logging", drop_status)
anti_afk_status = _json_settings.get("use_anti_afk", anti_afk_status)
buy_potions = _json_settings.get("buy_potions", buy_potions)
gui_on_top = _json_settings.get("on_top", gui_on_top)
gui_langcode = _json_settings.get("locale", gui_langcode)
gui_font = _json_settings.get("font", gui_font)
gui_font_size = _json_settings.get("font_size", gui_font_size)
use_team_up = _json_settings.get("use_team_up", use_team_up)
team_up_type = _json_settings.get("team_up_type", team_up_type)
team_up_size = _json_settings.get("team_up_size", team_up_size)
client_to_follow = _json_settings.get("client_to_follow", client_to_follow)
client_to_boost = _json_settings.get("client_to_boost", client_to_boost)
quest_excluded_clients = list(
    _json_settings.get("quest_excluded_clients", quest_excluded_clients) or []
)
questing_friend_tp = _json_settings.get("friend_teleport", questing_friend_tp)
gear_switching_in_solo_zones = _json_settings.get(
    "gear_switching_in_solo_zones", gear_switching_in_solo_zones
)
hitter_client = _json_settings.get("hitter_client", hitter_client)
ignore_pet_level_up = _json_settings.get("ignore_pet_level_up", ignore_pet_level_up)
only_play_dance_game = _json_settings.get("only_play_dance_game", only_play_dance_game)
kill_minions_first = _json_settings.get("kill_minions_first", kill_minions_first)
automatic_team_based_combat = _json_settings.get(
    "automatic_team_based_combat", automatic_team_based_combat
)
discard_duplicate_cards = _json_settings.get(
    "discard_duplicate_cards", discard_duplicate_cards
)
combat_handler._VERBOSE_LOG = bool(_json_settings.get("verbose_combat_logs", False))

speed_status = False
combat_status = False
dialogue_status = False
sigil_status = False
freecam_status = False
hotkey_status = False
questing_status = False
auto_pet_status = False
auto_potion_status = False
side_quest_status = False
tool_status = True
original_client_locations = dict()
_reboot_requested = False


def _relaunch_skyfall():
    argv = sys.argv if hasattr(sys, "_MEIPASS") else [sys.executable, *sys.argv]
    subprocess.Popen(argv)


hotkeys_blocked = False

sigil_leader_pid: int = None
questing_leader_pid: int = None

questing_task: asyncio.Task = None
auto_pet_task: asyncio.Task = None
sigil_task: asyncio.Task = None
dialogue_task: asyncio.Task = None
combat_task: asyncio.Task = None
tp_task: asyncio.Task = None
speed_task: asyncio.Task = None
fishing_task: asyncio.Task = None

# single shared fishing target/profile, edited from the Fishing tab via
# SetFishConfig and read when fishing starts. the running Fisher holds the same
# object so chest/school/size edits apply live
fish_config = FishConfig()
pet_task: asyncio.Task = None

bot_task: asyncio.Task = None
# per-slot bot tasks/bridges, keyed by slot_id sent from the GUI. the
# legacy ``bot_task`` / ``bridge`` globals above stay around for back-
# compat with older command sites that don't pass a slot_id (they map to
# slot 0); the dicts below are the source of truth for concurrent runs
bot_tasks: dict = {}
bot_bridges: dict = {}
flythrough_task: asyncio.Task = None
highlight_task: asyncio.Task = None
entity_stream_task: asyncio.Task = None
ui_dump_task: asyncio.Task = None
gates_stream_task: asyncio.Task = None
esp_task: asyncio.Task = None


def generate_timestamp() -> str:
    stamp = str(datetime.datetime.now()).split(".")[0]
    return stamp.replace("/", "-").replace(":", "-")


from src.hotkeys import (
    friend_teleport_sync,
    kill_tool,
    mass_key_press,
    navmap_teleport,
    sync_camera,
    xyz_sync,
)


async def tool_finish():
    if not walker or len(walker.clients) == 0:
        return

    # cosmetic restore (camera/speed/scale) touches client memory. a client
    # kicked for inactivity keeps its process alive (is_running() stays True)
    # but its hooks point at unloaded state, so these reads hang instead of
    # raising and wedge shutdown forever. bound each one with a timeout
    async def _restore(p):
        try:
            await p.mouse_handler.release_mouse(post_button_up=True)
        except Exception:
            pass
        try:
            original_speed = client_speeds.get(p.process_id)
            if original_speed is not None:
                await p.client_object.write_speed_multiplier(original_speed)
            p.title = "Wizard101"

            if await p.game_client.is_freecam():
                await p.camera_elastic()
            else:
                camera: ElasticCameraController = (
                    await p.game_client.elastic_camera_controller()
                )
                client_object = await p.body.parent_client_object()
                await camera.write_attached_client_object(client_object)
                await camera.write_check_collisions(True)
                await camera.write_distance_target(300.0)
                await camera.write_distance(300.0)
                await camera.write_min_distance(150.0)
                await camera.write_max_distance(450.0)
                await camera.write_zoom_resolution(150.0)
            await p.body.write_scale(1.0)
        except Exception:
            pass

    for p in [p for p in walker.clients if p.is_running()]:
        try:
            await asyncio.wait_for(_restore(p), timeout=5.0)
        except asyncio.TimeoutError:
            logger.warning(f"timed out restoring client '{p.title}', skipping.")
    try:
        await asyncio.wait_for(listener.clear(), timeout=5.0)
    except asyncio.TimeoutError:
        pass
    for p in walker.clients:
        try:
            await asyncio.wait_for(p.close(), timeout=10.0)
        except asyncio.TimeoutError:
            logger.warning(f"timed out closing client '{p.title}', skipping.")
        except Exception:
            pass

    await asyncio.sleep(0)
    global tool_status
    tool_status = False


def _make_bridge(loop, walker) -> "LuaBridge":
    from src.lang.client import LuaClient, pause_logs, resume_logs

    bridge = LuaBridge(loop)

    def _clients():
        return bridge.table_from(
            [
                LuaClient(c, bridge.call_async, bridge._stop, bridge.table_from, bridge)
                for c in walker.clients
            ]
        )

    bridge.register("clients", _clients, is_async=False)
    bridge.register("pause_logs", pause_logs, is_async=False)
    bridge.register("resume_logs", resume_logs, is_async=False)
    return bridge


@logger.catch()
async def main():
    global tool_status
    global original_client_locations
    global listener
    listener = HotkeyListener()
    foreground_client: Client = None
    background_clients = []
    foreground_ref = [None]
    bridge: LuaBridge = None
    await asyncio.sleep(0)
    listener.start()

    async def x_press_hotkey():
        await mass_key_press(
            foreground_client,
            background_clients,
            "X Press",
            Keycode.X,
            duration=0.1,
            debug=True,
        )

    async def xyz_sync_hotkey():
        await xyz_sync(
            foreground_client, background_clients, turn_after=True, debug=True
        )

    async def navmap_teleport_hotkey():
        if not freecam_status:
            await navmap_teleport(
                foreground_client, background_clients, mass_teleport=False, debug=True
            )

    async def mass_navmap_teleport_hotkey():
        if not freecam_status:
            await navmap_teleport(
                foreground_client, background_clients, mass_teleport=True, debug=True
            )

    def _toggle_targets(target):
        if target in (None, "All", "all"):
            return list(walker.clients)
        return [c for c in walker.clients if c.title == target]

    def _resolve_states(targets, attr, target):
        if target in (None, "All", "all"):
            on = not any(getattr(c, attr, False) for c in targets)
            return {c: on for c in targets}
        return {c: not getattr(c, attr, False) for c in targets}

    def _push_toggle_status(tag, enabled, client_title=None):
        state = "Enabled" if enabled else "Disabled"
        data = (tag, state, client_title) if client_title else (tag, state)
        gui_send_queue.put(sfgui.GUICommand(sfgui.GUICommandType.UpdateWindow, data))

    def _sync_shared_task(task, attr, loop_fn, deactivate_mouseless=True):
        if any(getattr(c, attr, False) for c in walker.clients):
            if task is None or task.cancelled():
                return asyncio.create_task(
                    try_task_coro(loop_fn, walker.clients, deactivate_mouseless)
                )
            return task
        if task is not None and not task.cancelled():
            task.cancel()
        return None

    async def toggle_speed_hotkey(target=None):
        global speed_task

        if freecam_status:
            return
        targets = _toggle_targets(target)
        if not targets:
            return

        for client, on in _resolve_states(targets, "speed_status", target).items():
            client.speed_status = on
            if not on and client.is_running():
                original = client_speeds.get(client.process_id)
                if original is not None:
                    try:
                        await client.client_object.write_speed_multiplier(original)
                    except wizwalker.errors.ClientClosedError:
                        pass
            _push_toggle_status("SpeedhackStatus", on, client.title)

        if any(getattr(c, "speed_status", False) for c in walker.clients):
            if speed_task is None or speed_task.cancelled():
                speed_task = asyncio.create_task(
                    try_task_coro(speed_switching, walker.clients)
                )
        elif speed_task is not None and not speed_task.cancelled():
            speed_task.cancel()
            speed_task = None

    async def friend_teleport_sync_hotkey():
        if not freecam_status:
            await friend_teleport_sync(walker.clients, debug=True)

    async def kill_tool_hotkey():

        if walker.clients != 0:
            gui_send_queue.put(sfgui.GUICommand(sfgui.GUICommandType.CloseFromBackend))

    async def toggle_combat_hotkey(debug: bool = True, target=None):
        global combat_task

        if freecam_status:
            return
        targets = _toggle_targets(target)
        if not targets:
            return

        # a client is "on" if the toggle is set or a lua script drives its
        # combat (enable_combat spawns _lua_combat_task without touching
        # combat_status), so the toggle still turns script combat off.
        # combat_config alone isn't a signal - SetPlaystyles pre-loads it, so
        # treating that as "armed" would clear the fresh playstyle
        def _combat_on(c):
            lt = getattr(c, "_lua_combat_task", None)
            return bool(getattr(c, "combat_status", False)) or (
                lt is not None and not lt.done()
            )

        if target in (None, "All", "all"):
            new = not any(_combat_on(c) for c in targets)
            states = {c: new for c in targets}
        else:
            states = {c: not _combat_on(c) for c in targets}

        for client, on in states.items():
            client.combat_status = on
            if on:
                # sticky lock removed: combat is packet-based (no clicks),
                # so the W101 window stays focusable while auto-combat is on
                _push_toggle_status("CombatStatus", True, client.title)
            else:
                try:
                    client.mouse_handler.unlock_window_input()
                except Exception:
                    pass
                # tear down the per-client Lua watcher if a script spawned one,
                # clearing the combat_config it relies on (only when a watcher
                # actually existed, to avoid wiping a SetPlaystyles preload)
                lua_task = getattr(client, "_lua_combat_task", None)
                if lua_task is not None and not lua_task.done():
                    try:
                        lua_task.cancel()
                    except Exception:
                        pass
                    client.combat_config = None
                client._lua_combat_task = None
                # Also cancel any Lua/bot-driven NativeCombat; combat_task only
                # owns the standalone combat_loop, so wait_battle()/Quester
                # combat won't see its cancel() - cancel_combat() exits cleanly
                # at the next handle_combat tick
                active = getattr(client, "_active_combat", None)
                if active is not None:
                    try:
                        active.cancel_combat()
                    except Exception:
                        pass
                _push_toggle_status("CombatStatus", False, client.title)

        script_combat = any(
            getattr(c, "_lua_combat_task", None) is not None
            and not c._lua_combat_task.done()
            for c in walker.clients
        )
        if (
            any(getattr(c, "combat_status", False) for c in walker.clients)
            or script_combat
        ):
            if combat_task is None or combat_task.cancelled():
                combat_task = asyncio.create_task(
                    try_task_coro(combat_loop, walker.clients, True)
                )
        elif combat_task is not None and not combat_task.cancelled():
            combat_task.cancel()
            combat_task = None

    async def toggle_dialogue_hotkey(target=None):
        global dialogue_task

        if freecam_status:
            return
        targets = _toggle_targets(target)
        if not targets:
            return

        # enable_dialog() in Lua spawns a per-client _lua_dialog_task without
        # creating the standalone dialogue_task; treat that as "on" so the
        # toggle also turns script-driven dialog off
        def _dialogue_on(c):
            lt = getattr(c, "_lua_dialog_task", None)
            return bool(getattr(c, "dialogue_status", False)) or (
                lt is not None and not lt.done()
            )

        if target in (None, "All", "all"):
            new = not any(_dialogue_on(c) for c in targets)
            states = {c: new for c in targets}
        else:
            states = {c: not _dialogue_on(c) for c in targets}

        for client, on in states.items():
            client.dialogue_status = on
            if not on:
                lua_task = getattr(client, "_lua_dialog_task", None)
                if lua_task is not None and not lua_task.done():
                    try:
                        lua_task.cancel()
                    except Exception:
                        pass
                client._lua_dialog_task = None
            _push_toggle_status("DialogueStatus", on, client.title)

        script_dialog = any(
            getattr(c, "_lua_dialog_task", None) is not None
            and not c._lua_dialog_task.done()
            for c in walker.clients
        )
        if (
            any(getattr(c, "dialogue_status", False) for c in walker.clients)
            or script_dialog
        ):
            if dialogue_task is None or dialogue_task.cancelled():
                dialogue_task = asyncio.create_task(
                    try_task_coro(dialogue_loop, walker.clients, True)
                )
        elif dialogue_task is not None and not dialogue_task.cancelled():
            dialogue_task.cancel()
            dialogue_task = None

    async def toggle_sigil_hotkey(target=None):
        global sigil_task
        global questing_status
        global questing_task
        global auto_pet_task
        global auto_pet_status

        if freecam_status:
            return
        targets = _toggle_targets(target)
        if not targets:
            return

        for client, on in _resolve_states(targets, "sigil_status", target).items():
            client.sigil_status = on
            if on:
                # sigil is mutually exclusive with questing / auto-pet per client
                if getattr(client, "questing_status", False):
                    client.questing_status = False
                    _push_toggle_status("QuestingStatus", False, client.title)
                if getattr(client, "auto_pet_status", False):
                    client.auto_pet_status = False
                    _push_toggle_status("Auto PetStatus", False, client.title)
            _push_toggle_status("SigilStatus", on, client.title)

        sigil_task = _sync_shared_task(sigil_task, "sigil_status", sigil_loop)
        questing_task = _sync_shared_task(
            questing_task, "questing_status", questing_loop
        )
        questing_status = any(
            getattr(c, "questing_status", False) for c in walker.clients
        )
        auto_pet_task = _sync_shared_task(
            auto_pet_task, "auto_pet_status", auto_pet_loop
        )
        auto_pet_status = any(
            getattr(c, "auto_pet_status", False) for c in walker.clients
        )

    async def toggle_freecam_hotkey(debug: bool = True, target=None):
        global freecam_status
        # freecam flies a single camera, so it acts on one client: the chosen
        # target from the selector, falling back to the foreground window
        cam_client = None
        if target not in (None, "All", "all"):
            cam_client = next((c for c in walker.clients if c.title == target), None)
        if cam_client is None:
            cam_client = foreground_client
        if cam_client:
            if await is_free(cam_client):
                if await cam_client.game_client.is_freecam():
                    await cam_client.camera_elastic()
                    freecam_status = False
                    gui_send_queue.put(
                        sfgui.GUICommand(
                            sfgui.GUICommandType.UpdateWindow,
                            ("FreecamStatus", "Disabled", cam_client.title),
                        )
                    )

                else:
                    freecam_status = True
                    await sync_camera(cam_client)
                    await cam_client.camera_freecam()
                    gui_send_queue.put(
                        sfgui.GUICommand(
                            sfgui.GUICommandType.UpdateWindow,
                            ("FreecamStatus", "Enabled", cam_client.title),
                        )
                    )

    async def tp_to_freecam_hotkey():
        if foreground_client:
            if await foreground_client.game_client.is_freecam():
                camera = await foreground_client.game_client.free_camera_controller()
                camera_pos = await camera.position()
                await toggle_freecam_hotkey(False)
                await foreground_client.teleport(
                    camera_pos, wait_on_inuse=True, purge_on_after_unuser_fixer=True
                )

    async def toggle_questing_hotkey(target=None):
        global sigil_task
        global questing_task
        global questing_status
        global sigil_status

        if freecam_status:
            return
        targets = _toggle_targets(target)
        if not targets:
            return

        for client, on in _resolve_states(targets, "questing_status", target).items():
            client.questing_status = on
            if on and getattr(client, "sigil_status", False):
                # questing is mutually exclusive with sigil per client
                client.sigil_status = False
                _push_toggle_status("SigilStatus", False, client.title)
            _push_toggle_status("QuestingStatus", on, client.title)

        questing_task = _sync_shared_task(
            questing_task, "questing_status", questing_loop
        )
        questing_status = any(
            getattr(c, "questing_status", False) for c in walker.clients
        )
        sigil_task = _sync_shared_task(sigil_task, "sigil_status", sigil_loop)
        sigil_status = any(getattr(c, "sigil_status", False) for c in walker.clients)

    async def toggle_auto_pet_hotkey(target=None):
        global auto_pet_task
        global auto_pet_status

        if freecam_status:
            return
        targets = _toggle_targets(target)
        if not targets:
            return

        for client, on in _resolve_states(targets, "auto_pet_status", target).items():
            client.auto_pet_status = on
            _push_toggle_status("Auto PetStatus", on, client.title)

        auto_pet_task = _sync_shared_task(
            auto_pet_task, "auto_pet_status", auto_pet_loop
        )
        auto_pet_status = any(
            getattr(c, "auto_pet_status", False) for c in walker.clients
        )

    async def toggle_auto_potion_hotkey(target=None):
        global auto_potion_status

        if freecam_status:
            return
        targets = _toggle_targets(target)
        if not targets:
            return

        for client, on in _resolve_states(
            targets, "auto_potion_status", target
        ).items():
            client.auto_potion_status = on
            _push_toggle_status("Auto PotionStatus", on, client.title)

        auto_potion_status = any(
            getattr(c, "auto_potion_status", False) for c in walker.clients
        )

    def _push_fishing_stats(stats):
        gui_send_queue.put(
            sfgui.GUICommand(sfgui.GUICommandType.UpdateWindow, ("fishing", stats))
        )

    async def toggle_fishing_hotkey(target=None):
        # fishing is primary-client only: one config, one pond. ignore the
        # per-client target the toggle framework passes and always drive the
        # first hooked client.
        global fishing_task

        if freecam_status or not walker.clients:
            return
        client = walker.clients[0]
        # base the decision on whether a session is actually live (task alive or
        # a Lua-driven fisher running), not just the status flag - so if the loop
        # ever ends on its own, one click restarts it instead of toggling a ghost
        existing = getattr(client, "_fisher", None)
        running = (fishing_task is not None and not fishing_task.done()) or (
            existing is not None and existing.stats.get("running")
        )
        on = not running
        client.fishing_status = on
        _push_toggle_status("FishingStatus", on, client.title)

        if on:
            fisher = Fisher(
                client,
                fish_config,
                on_stats=_push_fishing_stats,
                should_stop=lambda: not getattr(client, "fishing_status", False),
            )
            client._fisher = fisher
            fishing_task = asyncio.create_task(fisher.run())
        elif existing is not None:
            existing.stop()  # loop exits and restores patches in its finally

    def _make_hotkey_callback(action_id):
        async def _callback():
            gui_send_queue.put(
                sfgui.GUICommand(sfgui.GUICommandType.InvokeAction, action_id)
            )

        return _callback

    _kill_tool_callback = kill_tool_hotkey

    _active_bindings = {}

    _FREECAM_ACTIONS = {"toggle_freecam", "freecam_tp"}

    async def enable_hotkeys(exclude_freecam: bool = False, debug: bool = False):
        global hotkey_status
        if not hotkey_status:
            hotkeys = settings.get_hotkeys()
            for action_id, binding in hotkeys.items():
                if binding is None:
                    continue
                if action_id == "kill_tool":
                    continue
                if exclude_freecam and action_id in _FREECAM_ACTIONS:
                    continue
                mods = ModifierKeys.NOREPEAT
                for m in binding.get("modifiers", []):
                    mods |= ModifierKeys[m]
                try:
                    await listener.add_hotkey(
                        Keycode[binding["key"]],
                        _make_hotkey_callback(action_id),
                        modifiers=mods,
                    )
                    _active_bindings[action_id] = binding
                except Exception as e:
                    logger.debug(f"failed to register hotkey for {action_id}: {e}")
            hotkey_status = True

    async def disable_hotkeys(
        exclude_freecam: bool = False, debug: bool = False, exclude_kill: bool = True
    ):
        global hotkey_status
        if hotkey_status:
            for action_id, binding in list(_active_bindings.items()):
                if exclude_kill and action_id == "kill_tool":
                    continue
                if exclude_freecam and action_id in _FREECAM_ACTIONS:
                    continue
                mods = ModifierKeys.NOREPEAT
                for m in binding.get("modifiers", []):
                    mods |= ModifierKeys[m]
                try:
                    await listener.remove_hotkey(
                        Keycode[binding["key"]], modifiers=mods
                    )
                    del _active_bindings[action_id]
                except Exception as e:
                    logger.debug(f"failed to remove hotkey for {action_id}: {e}")
            hotkey_status = False

    def get_foreground_client():
        if not walker.clients:
            return None
        foreground = [c for c in walker.clients if c.is_foreground]
        if len(foreground) > 0:
            return foreground[0]
        if not foreground_client:
            return walker.clients[0]
        return foreground_client

    def get_background_clients():
        return [c for c in walker.clients if not c.is_foreground]

    async def foreground_client_switching():
        await asyncio.sleep(2)

        while True:
            await asyncio.sleep(0.1)
            foreground_client_list = [c for c in walker.clients if c.is_foreground]
            if foreground_client_list:
                await enable_hotkeys(debug=True)
            else:
                await disable_hotkeys(debug=True)

    async def assign_foreground_clients():

        nonlocal foreground_client
        nonlocal background_clients
        while True:
            foreground_client = get_foreground_client()
            foreground_ref[0] = foreground_client
            background_clients = get_background_clients()
            await asyncio.sleep(0.1)

    async def speed_switching():

        while True:
            await asyncio.sleep(0.1)

            if not freecam_status:
                await asyncio.sleep(0.2)
                for c in walker.clients:
                    if not c.is_running() or not getattr(c, "speed_status", False):
                        continue
                    mult = client_speed_targets.get(c.process_id, speed_multiplier)
                    modified_speed = (int(mult) - 1) * 100
                    try:
                        if await c.client_object.speed_multiplier() != modified_speed:
                            await c.client_object.write_speed_multiplier(modified_speed)
                    except wizwalker.errors.ClientClosedError:
                        continue

    async def is_client_in_combat_loop():
        async def async_in_combat(client: Client):

            while True:
                if not freecam_status:
                    try:
                        client.in_combat = await client.in_battle()
                    except Exception:
                        if not client.is_running():
                            return
                await asyncio.sleep(0.1)

        await asyncio.gather(*[async_in_combat(p) for p in walker.clients])

    async def combat_loop():
        logger.catch()

        async def async_combat(client: Client):
            while True:
                await asyncio.sleep(1)
                if not freecam_status:
                    # per-client gate: the shared loop stays alive while any
                    # client has combat on, so skip clients toggled off. the
                    # wait is abortable so toggling off mid-idle takes effect
                    # without first handling one more battle
                    if not getattr(client, "combat_status", False):
                        continue
                    while not await client.in_battle():
                        if not getattr(client, "combat_status", False):
                            break
                        await asyncio.sleep(1)

                    if (
                        getattr(client, "combat_status", False)
                        and await client.in_battle()
                    ):
                        # only auto-handle combat when a playstyle is loaded
                        if not getattr(client, "combat_config", None):
                            await asyncio.sleep(1)
                            continue

                        # don't double-handle. if a bot script is already
                        # driving a NativeCombat for this client (via
                        # waitfor_battle_finish), let it run - racing two
                        # handlers makes them stomp on each other's packets
                        if getattr(client, "_active_combat", None) is not None:
                            await asyncio.sleep(0.5)
                            continue

                        logger.debug(
                            f"client {client.title} in combat, handling combat."
                        )

                        battle = NativeCombat(
                            client, client.combat_config, cast_time=0.25
                        )

                        try:
                            await battle.wait_for_combat()
                        finally:
                            try:
                                await client.mouse_handler.release_mouse()
                            except Exception:
                                pass
                            try:
                                from wizwalker import Keycode

                                await client.send_key(Keycode.ESCAPE)
                            except Exception:
                                pass

        await asyncio.gather(*[async_combat(p) for p in walker.clients])

    async def dialogue_loop():

        async def async_dialogue(client: Client):
            while True:
                if not freecam_status and getattr(client, "dialogue_status", False):
                    if await is_visible_by_path(client, advance_dialog_path):
                        await client.send_key(key=Keycode.SPACEBAR)
                await asyncio.sleep(0.1)

        await asyncio.gather(*[async_dialogue(p) for p in walker.clients])

    async def questing_loop():

        async def async_questing(client: Client):
            client.character_level = await client.stats.reference_level()

            while True:
                await asyncio.sleep(1)

                if client in walker.clients and client.questing_status:
                    # quest_excluded=True hides a client from the Quester
                    # entirely - the leader won't drag it to sigils/team-ups/
                    # refills and it gets no Quester of its own. lets one wizard
                    # quest while a second just sits and auto-passes
                    active_clients = [
                        c
                        for c in walker.clients
                        if not getattr(c, "quest_excluded", False)
                    ]
                    if client not in active_clients:
                        continue
                    if questing_leader_pid is not None and len(active_clients) > 1:
                        if client.process_id == questing_leader_pid:
                            logger.debug(
                                f"client {client.title} - handling questing for all clients."
                            )
                            questing = Quester(
                                client, active_clients, questing_leader_pid
                            )
                            await questing.auto_quest_leader(
                                questing_friend_tp,
                                gear_switching_in_solo_zones,
                                hitter_client,
                                ignore_pet_level_up,
                                only_play_dance_game,
                            )
                    else:
                        logger.debug(f"client {client.title} - handling questing.")
                        questing = Quester(client, active_clients, None)
                        await questing.auto_quest(
                            ignore_pet_level_up, only_play_dance_game
                        )

        await asyncio.gather(*[async_questing(p) for p in walker.clients])

    async def anti_afk_questing_loop():
        async def async_afk_questing(client: Client):
            while True:
                global questing_task

                await asyncio.sleep(0.1)
                if not freecam_status:
                    try:
                        client_xyz = await client.body.position()
                        await asyncio.sleep(120)
                        client_xyz_2 = await client.body.position()
                        distance_moved = calc_Distance(client_xyz, client_xyz_2)
                        if (
                            distance_moved < 5.0
                            and not await client.in_battle()
                            and not client.feeding_pet_status
                            and not client.entity_detect_combat_status
                        ):
                            client_in_solo_zone = False
                            for p in walker.clients:
                                if p.in_solo_zone:
                                    client_in_solo_zone = True

                            if (
                                questing_task is not None
                                and not questing_task.cancelled()
                                and not client_in_solo_zone
                            ):
                                logger.debug(
                                    "questing appears to have halted - restarting."
                                )
                                questing_task.cancel()
                                questing_task = None
                                await asyncio.sleep(1.0)

                                if questing_task is None:
                                    questing_task = asyncio.create_task(
                                        try_task_coro(
                                            questing_loop, walker.clients, True
                                        )
                                    )
                    except Exception:
                        if not client.is_running():
                            return

        await asyncio.gather(*[async_afk_questing(p) for p in walker.clients])

    async def auto_pet_loop():

        async def async_auto_pet(client: Client):
            while True:
                await asyncio.sleep(1)

                if client in walker.clients and client.auto_pet_status:
                    await nomnom(
                        client,
                        ignore_pet_level_up=ignore_pet_level_up,
                        only_play_dance_game=only_play_dance_game,
                    )

        await asyncio.gather(*[async_auto_pet(p) for p in walker.clients])

    async def nearest_duel_circle_distance_and_xyz(sprinter: EntityClient):
        min_distance = None
        circle_xyz = None

        try:
            entities = await sprinter.entities()
        except ValueError:
            return None, None

        for entity in entities:
            try:
                entity_name = await entity.object_name()
            except wizwalker.MemoryReadError:
                entity_name = ""

            if entity_name == "Duel Circle":
                entity_pos = await entity.location()
                distance = calc_Distance(
                    entity_pos, await sprinter.client.body.position()
                )

                if min_distance is None:
                    min_distance = distance
                    circle_xyz = entity_pos
                elif distance < min_distance:
                    min_distance = distance
                    circle_xyz = entity_pos

        return min_distance, circle_xyz

    async def is_duel_circle_joinable(p: Client):
        sprinter = EntityClient(p)
        await asyncio.sleep(7)

        distance, duel_circle_xyz = await nearest_duel_circle_distance_and_xyz(sprinter)

        if distance is not None:
            if not (590 < distance < 610):
                logger.debug(
                    "bad teleport.  returning " + p.title + " to safe location."
                )
                if p.original_location_before_combat is not None:
                    await p.teleport(p.original_location_before_combat)
                    p.original_location_before_combat = None
                else:
                    position = await p.body.position()
                    await p.teleport(XYZ(position.x, position.y, position.z - 350))

                p.entity_detect_combat_status = False

                return False

            return True
        else:
            return False

    async def entity_detect_combat_loop():
        async def detect_combat(p: Client):
            global original_client_locations
            sprinter = EntityClient(p)

            other_clients = []
            for c in walker.clients:
                if c != p:
                    other_clients.append(c)

            safe_distance = 620
            while True:
                await asyncio.sleep(0.5)

                if p.questing_status:
                    if p.just_entered_combat is not None:
                        if time.time() >= (p.just_entered_combat + 7):
                            if await p.in_battle():
                                p.just_entered_combat = None

                            else:
                                if p.client_being_helped is not None:
                                    is_circle_joinable = await is_duel_circle_joinable(
                                        p
                                    )

                                    if not is_circle_joinable:
                                        p.client_being_helped.duel_circle_joinable = (
                                            False
                                        )
                                        logger.debug(
                                            "client "
                                            + p.client_being_helped.title
                                            + " - "
                                            + "duel circle not joinable - teleports halted."
                                        )
                                        p.client_being_helped = None

                    if p.just_entered_combat is None:
                        if True:
                            (
                                distance,
                                duel_circle_xyz,
                            ) = await nearest_duel_circle_distance_and_xyz(sprinter)

                            if distance is None:
                                if p.entity_detect_combat_status:
                                    p.just_left_combat = True
                                else:
                                    p.entity_detect_combat_status = False

                            elif distance < safe_distance:
                                p.entity_detect_combat_status = True

                                all_fighting_clients = [p]

                                if p.duel_circle_joinable and not p.in_solo_zone:
                                    p.helper_clients = []
                                    none_in_solo_zone = True
                                    all_already_in_battle = False
                                    for c in other_clients:
                                        client_is_hitter_client = False
                                        if hitter_client is not None:
                                            if hitter_client in c.title:
                                                client_is_hitter_client = True
                                                all_already_in_battle = True
                                                for cl in walker.clients:
                                                    if hitter_client not in cl.title:
                                                        if not cl.entity_detect_combat_status:
                                                            all_already_in_battle = (
                                                                False
                                                            )

                                                        if cl.in_solo_zone:
                                                            none_in_solo_zone = False

                                        if (
                                            client_is_hitter_client
                                            and all_already_in_battle
                                            and none_in_solo_zone
                                        ) or not client_is_hitter_client:
                                            if (
                                                await is_free(c)
                                                and not c.entity_detect_combat_status
                                                and not c.invincible_combat_timer
                                                and c.just_entered_combat is None
                                            ):
                                                if hitter_client is not None:
                                                    if (
                                                        all_already_in_battle
                                                        and hitter_client in c.title
                                                    ):
                                                        await asyncio.sleep(1.0)

                                                if (
                                                    await c.zone_name()
                                                    == await p.zone_name()
                                                ):
                                                    if not c.entity_detect_combat_status:
                                                        c.entity_detect_combat_status = True
                                                        c.just_entered_combat = (
                                                            time.time()
                                                        )
                                                        c.original_location_before_combat = await c.body.position()
                                                        original_client_locations.update(
                                                            {
                                                                c.process_id: await c.body.position()
                                                            }
                                                        )
                                                        c.client_being_helped = p
                                                        if c not in p.helper_clients:
                                                            p.helper_clients.append(c)
                                                            all_fighting_clients.append(
                                                                c
                                                            )

                                                        logger.debug(
                                                            "combat detected from client "
                                                            + p.title
                                                            + " - teleporting client "
                                                            + c.title
                                                        )
                                                        try:
                                                            await c.teleport(
                                                                duel_circle_xyz
                                                            )

                                                        except ValueError:
                                                            c.just_entered_combat = None
                                                            pass

                            else:
                                if p.entity_detect_combat_status:
                                    p.just_left_combat = True
                                else:
                                    p.entity_detect_combat_status = False

                            if p.just_left_combat and await is_free(p):
                                p.just_left_combat = False

                                await collect_wisps_with_limit(p, limit=2)
                                await asyncio.sleep(0.3)

                                if p.process_id in original_client_locations:
                                    logger.debug(
                                        "client "
                                        + p.title
                                        + " - "
                                        + "returning to safe location. "
                                    )

                                    try:
                                        await p.teleport(
                                            original_client_locations.get(p.process_id)
                                        )
                                        original_client_locations.pop(p.process_id)
                                    except ValueError:
                                        print(traceback.print_exc())
                                        p.original_location_before_combat = None

                                logger.debug(
                                    "client "
                                    + p.title
                                    + " - "
                                    + "battle teleports off while invulnerable"
                                )
                                p.invincible_combat_timer = True
                                p.entity_detect_combat_status = False
                                p.duel_circle_joinable = True
                                p.client_being_helped = None

                                await asyncio.sleep(6.5)
                                logger.debug(
                                    "client "
                                    + p.title
                                    + " - "
                                    + "battle teleports re-enabled"
                                )
                                p.invincible_combat_timer = False

        await asyncio.gather(*[detect_combat(p) for p in walker.clients])

    async def sigil_loop():

        async def async_sigil(client: Client):
            while True:
                await asyncio.sleep(1)
                if (
                    client in walker.clients
                    and client.sigil_status
                    and not freecam_status
                ):
                    sigil = Sigil(client, walker.clients, sigil_leader_pid)
                    await sigil.wait_for_sigil()

        await asyncio.gather(*[async_sigil(p) for p in walker.clients])

    async def anti_afk_loop():

        if not anti_afk_status:
            return

        async def async_anti_afk(client: Client):

            while True:
                global questing_task

                await asyncio.sleep(0.1)
                if not freecam_status:
                    try:
                        client_xyz = await client.body.position()
                        await asyncio.sleep(240)
                        client_xyz_2 = await client.body.position()
                        distance_moved = calc_Distance(client_xyz, client_xyz_2)
                        if (
                            distance_moved < 5.0
                            and not await client.in_battle()
                            and not client.feeding_pet_status
                            and not client.entity_detect_combat_status
                        ):
                            logger.trace(f"Anti-AFK nudge for {client.title}.")
                            await client.send_key(key=Keycode.A)
                            await asyncio.sleep(0.1)
                            await client.send_key(key=Keycode.D)
                    except Exception:
                        if not client.is_running():
                            return

        await asyncio.gather(*[async_anti_afk(p) for p in walker.clients])

    launched_account_map: dict[int, str] = {}
    initial_setup_complete = False

    released_handles: set[int] = set()

    _hooking_in_progress: set[int] = set()

    def _mask_uid(uid) -> str:
        s = str(uid)
        return "****" if len(s) <= 4 else "*" * (len(s) - 4) + s[-4:]

    def _kill_process_by_handle(handle):
        try:
            pid = utils.get_pid_from_handle(handle)
            if pid:
                PROCESS_TERMINATE = 0x0001
                h_proc = ctypes.windll.kernel32.OpenProcess(
                    PROCESS_TERMINATE, False, pid
                )
                if h_proc:
                    ctypes.windll.kernel32.TerminateProcess(h_proc, 1)
                    ctypes.windll.kernel32.CloseHandle(h_proc)
        except Exception as e:
            logger.error(f"failed to kill process for handle {handle}: {e}")

    def _build_hooked_clients_info():

        all_handles = set(get_all_wizard_handles())
        stale = [h for h in launched_account_map if h not in all_handles]
        for h in stale:
            launched_account_map.pop(h)
            _hooking_in_progress.discard(h)

        hooked = []
        managed_accounts = set(launched_account_map.values())
        for c in walker.clients:
            nick = launched_account_map.get(c.window_handle)
            hooked.append(
                {"title": c.title, "handle": c.window_handle, "account_nick": nick}
            )

            if not nick:
                gid = getattr(c, "player_gid", None)
                if gid:
                    vault_nick = wizlaunch.get_nickname_by_gid(gid)
                    if vault_nick:
                        managed_accounts.add(vault_nick)

        managed = set(walker._managed_handles)
        unmanaged = sorted(all_handles - managed)
        return {
            "hooked": hooked,
            "unmanaged": unmanaged,
            "managed_accounts": sorted(managed_accounts),
            "hooking": sorted(_hooking_in_progress),
        }

    def _send_hooked_clients_update():
        gui_send_queue.put(
            sfgui.GUICommand(
                sfgui.GUICommandType.UpdateHookedClients, _build_hooked_clients_info()
            )
        )

    def _resync_toggle_status():
        for c in walker.clients:
            _push_toggle_status(
                "CombatStatus", getattr(c, "combat_status", False), c.title
            )
            _push_toggle_status(
                "SigilStatus", getattr(c, "sigil_status", False), c.title
            )
            _push_toggle_status(
                "QuestingStatus", getattr(c, "questing_status", False), c.title
            )
            _push_toggle_status(
                "Auto PetStatus", getattr(c, "auto_pet_status", False), c.title
            )
            _push_toggle_status(
                "Auto PotionStatus", getattr(c, "auto_potion_status", False), c.title
            )
            _push_toggle_status(
                "DialogueStatus", getattr(c, "dialogue_status", False), c.title
            )
            _push_toggle_status(
                "SpeedhackStatus", getattr(c, "speed_status", False), c.title
            )
            _push_toggle_status(
                "FishingStatus", getattr(c, "fishing_status", False), c.title
            )

    def _renumber_clients():
        changed = False
        for i, c in enumerate(walker.clients, start=1):
            new_title = f"p{i}"
            if c.title != new_title:
                c.title = new_title
                changed = True
        if changed:
            _send_hooked_clients_update()

    async def _init_client_attrs(client):
        client_speeds[client.process_id] = await client.client_object.speed_multiplier()
        client_speed_targets.setdefault(client.process_id, speed_multiplier)
        client.combat_status = False
        client.questing_status = False
        client.sigil_status = False
        client.auto_pet_status = False
        client.auto_potion_status = False
        client.dialogue_status = False
        client.speed_status = False
        client.fishing_status = False
        client.feeding_pet_status = False
        client.use_team_up = use_team_up
        client.team_up_type = team_up_type
        client.team_up_size = team_up_size
        client.dance_hook_status = False
        client.entity_detect_combat_status = False
        client.invincible_combat_timer = False
        client.just_entered_combat = None
        client.just_left_combat = False
        client.helper_clients = []
        client.client_being_helped = None
        client.original_location_before_combat = None
        client.duel_circle_joinable = True
        client.in_solo_zone = False
        client.wizard_name = None
        client.character_level = await client.stats.reference_level()
        client.discard_duplicate_cards = discard_duplicate_cards
        client.kill_minions_first = kill_minions_first
        client.automatic_team_based_combat = automatic_team_based_combat
        client.latest_drops = ""
        # no implicit default - combat passes every round until a script
        # calls load_playstyle(...). avoids surprise spellcasting when the
        # user only loaded the bot for navigation/dialog/etc
        client.combat_config = None
        client.use_potions = use_potions
        client.buy_potions = buy_potions
        client.client_to_follow = client_to_follow

        try:
            uid = await client.game_client.user_id()
            logger.debug(
                f"[gid] _init_client_attrs '{client.title}': user_id={_mask_uid(uid)}"
            )
            if uid and uid != 0:
                client.player_gid = uid
                vault_nick = wizlaunch.get_nickname_by_gid(uid)
                if vault_nick and client.window_handle not in launched_account_map:
                    launched_account_map[client.window_handle] = vault_nick
                nick = launched_account_map.get(client.window_handle)
                if nick:
                    wizlaunch.update_player_gid(nick, uid)
                    logger.debug(
                        f"[gid] saved user_id {_mask_uid(uid)} for vault account '{nick}'"
                    )
            else:
                client.player_gid = None
                logger.debug(
                    f"[gid] _init_client_attrs '{client.title}': user_id is 0, deferring"
                )
        except Exception as e:
            client.player_gid = None
            logger.debug(f"[gid] _init_client_attrs '{client.title}': exception {e}")

        if client_to_follow and client_to_follow in client.title:
            global sigil_leader_pid
            sigil_leader_pid = client.process_id
        if client_to_boost and client_to_boost in client.title:
            global questing_leader_pid
            questing_leader_pid = client.process_id

        # Honor the Settings → Questing "Exclude from Questing" checkboxes
        # at hook time. live updates are applied by the UpdateSettings
        # handler below
        client.quest_excluded = client.title in quest_excluded_clients

    async def handle_gui():
        nonlocal bridge

        async def handle_coord_error(error: wizwalker.errors.MemoryReadError):
            if await is_visible_by_path(foreground_client, play_button_path):
                return
            if await foreground_client.is_loading():
                return
            if await foreground_client.zone_name() is None:
                return
            raise wizwalker.errors.MemoryReadError(
                f"{error} (Occurred in zone: {current_zone})"
            ) from error

        async def _highlight_entity_loop(client, entity_info):
            ex, ey, ez, entity_height = entity_info
            half_w = entity_height * 0.3
            try:
                while True:
                    try:
                        cam = await get_camera_state(client)
                        if cam is not None:
                            feet = project_point(cam, ex, ey, ez)
                            head = project_point(cam, ex, ey, ez + entity_height)
                            if feet is not None and head is not None:
                                rx = cam["right_x"]
                                ry = cam["right_y"]
                                center_mid = project_point(
                                    cam, ex, ey, ez + entity_height * 0.5
                                )
                                side = project_point(
                                    cam,
                                    ex + rx * half_w,
                                    ey + ry * half_w,
                                    ez + entity_height * 0.5,
                                )
                                if center_mid is not None and side is not None:
                                    screen_hw = abs(side[0] - center_mid[0])
                                else:
                                    screen_hw = abs(head[1] - feet[1]) * 0.3
                                screen_hw = max(screen_hw, 10)
                                x1 = (
                                    int(center_mid[0] - screen_hw)
                                    if center_mid
                                    else int(feet[0] - screen_hw)
                                )
                                x2 = (
                                    int(center_mid[0] + screen_hw)
                                    if center_mid
                                    else int(feet[0] + screen_hw)
                                )
                                y1 = min(head[1], feet[1])
                                y2 = max(head[1], feet[1])
                                gui_send_queue.put(
                                    sfgui.GUICommand(
                                        sfgui.GUICommandType.UpdateHighlightBox,
                                        (client.window_handle, x1, y1, x2, y2),
                                    )
                                )
                            elif feet is not None:
                                gui_send_queue.put(
                                    sfgui.GUICommand(
                                        sfgui.GUICommandType.UpdateHighlightBox,
                                        (
                                            client.window_handle,
                                            feet[0] - 30,
                                            feet[1] - 60,
                                            feet[0] + 30,
                                            feet[1],
                                        ),
                                    )
                                )
                            else:
                                gui_send_queue.put(
                                    sfgui.GUICommand(
                                        sfgui.GUICommandType.UpdateHighlightBox, None
                                    )
                                )
                        else:
                            gui_send_queue.put(
                                sfgui.GUICommand(
                                    sfgui.GUICommandType.UpdateHighlightBox, None
                                )
                            )
                    except wizwalker.errors.MemoryReadError:
                        pass
                    except Exception as e:
                        logger.debug(f"highlight loop error: {e}")
                    await asyncio.sleep(0.033)
            except asyncio.CancelledError:
                gui_send_queue.put(
                    sfgui.GUICommand(sfgui.GUICommandType.UpdateHighlightBox, None)
                )
                return

        async def _highlight_ui_window_loop(client, name_path):
            try:
                while True:
                    try:
                        window = await get_window_from_path(
                            client.root_window, name_path
                        )
                        if window and window is not False:
                            rect = await window.scale_to_client()
                            gui_send_queue.put(
                                sfgui.GUICommand(
                                    sfgui.GUICommandType.UpdateHighlightBox,
                                    (
                                        client.window_handle,
                                        rect.x1,
                                        rect.y1,
                                        rect.x2,
                                        rect.y2,
                                    ),
                                )
                            )
                        else:
                            gui_send_queue.put(
                                sfgui.GUICommand(
                                    sfgui.GUICommandType.UpdateHighlightBox, None
                                )
                            )
                    except wizwalker.errors.MemoryReadError:
                        pass
                    except Exception as e:
                        logger.debug(f"ui highlight loop error: {e}")
                    await asyncio.sleep(0.033)
            except asyncio.CancelledError:
                gui_send_queue.put(
                    sfgui.GUICommand(sfgui.GUICommandType.UpdateHighlightBox, None)
                )
                return

        async def _entity_stream_loop(client):
            try:
                while True:
                    try:
                        sprinter = EntityClient(client)
                        entities = await sprinter.entities()
                        player_pos = await client.body.position()
                        entity_data = []
                        for entity in entities:
                            entity_pos = await entity.location()
                            entity_name = await entity.object_name()
                            gid = await entity.global_id_full()
                            entity_height = 170.0
                            try:
                                body = await entity.actor_body()
                                if body is not None:
                                    h = await body.height()
                                    s = await body.scale()
                                    if h > 0:
                                        entity_height = h * s
                            except Exception:
                                pass
                            dx = entity_pos.x - player_pos.x
                            dy = entity_pos.y - player_pos.y
                            dz = entity_pos.z - player_pos.z
                            distance = (dx * dx + dy * dy + dz * dz) ** 0.5
                            display = f"{entity_name} (dist: {trunc(distance, 1)}) - XYZ({trunc(entity_pos.x, 3)}, {trunc(entity_pos.y, 3)}, {trunc(entity_pos.z, 3)})"
                            entity_data.append(
                                {
                                    "name": entity_name,
                                    "x": entity_pos.x,
                                    "y": entity_pos.y,
                                    "z": entity_pos.z,
                                    "height": entity_height,
                                    "gid": 0 if entity_name == "Player Object" else gid,
                                    "distance": distance,
                                    "display": display,
                                }
                            )
                        entity_data.sort(key=lambda e: e["distance"])
                        gui_send_queue.put(
                            sfgui.GUICommand(
                                sfgui.GUICommandType.UpdateEntityListData, entity_data
                            )
                        )
                    except wizwalker.errors.MemoryReadError:
                        pass
                    except Exception as e:
                        logger.debug(f"entity stream error: {e}")
                    await asyncio.sleep(1.0)
            except asyncio.CancelledError:
                return

        async def _gates_stream_loop(client):
            from src.nav.scraper import enumerate_zone_gates

            try:
                while True:
                    try:
                        gates = await enumerate_zone_gates(client)
                        gui_send_queue.put(
                            sfgui.GUICommand(
                                sfgui.GUICommandType.UpdateGatesListData, gates
                            )
                        )
                    except wizwalker.errors.MemoryReadError:
                        pass
                    except Exception as e:
                        logger.debug(f"gates stream error: {e}")
                    await asyncio.sleep(2.0)
            except asyncio.CancelledError:
                return

        async def _esp_loop(client):
            entity_objects = []  # list of {entity, name, height, x, y, z, distance}

            async def _fetch_full():
                while True:
                    # entity list rebuild - clear on any failure so stale boxes disappear
                    try:
                        sprinter = EntityClient(client)
                        entities = await sprinter.entities()
                        player_pos = await client.body.position()
                        new_objects = []
                        for entity in entities:
                            try:
                                name = await entity.object_name()
                                height = 170.0
                                try:
                                    body = await entity.actor_body()
                                    if body is not None:
                                        h = await body.height()
                                        s = await body.scale()
                                        if h > 0:
                                            height = h * s
                                except Exception:
                                    pass
                                pos = await entity.location()
                                dx = pos.x - player_pos.x
                                dy = pos.y - player_pos.y
                                dz = pos.z - player_pos.z
                                new_objects.append(
                                    {
                                        "entity": entity,
                                        "name": name,
                                        "height": height,
                                        "x": pos.x,
                                        "y": pos.y,
                                        "z": pos.z,
                                        "distance": (dx * dx + dy * dy + dz * dz)
                                        ** 0.5,
                                    }
                                )
                            except Exception:
                                pass
                        entity_objects.clear()
                        entity_objects.extend(new_objects)
                    except Exception as e:
                        logger.debug(f"esp fetch error: {e}")
                        entity_objects.clear()

                    await asyncio.sleep(2.0)

            fetch_task = asyncio.create_task(_fetch_full())
            try:
                while True:
                    try:
                        if entity_objects:
                            snapshot = list(entity_objects)

                            # concurrent entity position reads + consistent camera state
                            positions, cam = await asyncio.gather(
                                asyncio.gather(
                                    *[e["entity"].location() for e in snapshot],
                                    return_exceptions=True,
                                ),
                                get_camera_state(client),
                            )

                            if cam is None:
                                await asyncio.sleep(0.033)
                                continue

                            for e, pos in zip(snapshot, positions):
                                if not isinstance(pos, Exception):
                                    e["x"], e["y"], e["z"] = pos.x, pos.y, pos.z

                            rx = cam["right_x"]
                            ry = cam["right_y"]
                            boxes = []
                            for e in snapshot:
                                ex, ey, ez = e["x"], e["y"], e["z"]
                                eh = e["height"]
                                feet = project_point(cam, ex, ey, ez)
                                head = project_point(cam, ex, ey, ez + eh)
                                if feet is None and head is None:
                                    continue
                                if feet and head:
                                    half_w = eh * 0.3
                                    center_mid = project_point(
                                        cam, ex, ey, ez + eh * 0.5
                                    )
                                    side = project_point(
                                        cam,
                                        ex + rx * half_w,
                                        ey + ry * half_w,
                                        ez + eh * 0.5,
                                    )
                                    if center_mid and side:
                                        screen_hw = max(
                                            abs(side[0] - center_mid[0]), 10
                                        )
                                    else:
                                        screen_hw = max(
                                            abs(head[1] - feet[1]) * 0.3, 10
                                        )
                                    cx = center_mid[0] if center_mid else feet[0]
                                    x1 = int(cx - screen_hw)
                                    x2 = int(cx + screen_hw)
                                    y1 = min(head[1], feet[1])
                                    y2 = max(head[1], feet[1])
                                else:
                                    x1 = feet[0] - 30
                                    x2 = feet[0] + 30
                                    y1 = feet[1] - 60
                                    y2 = feet[1]
                                boxes.append((x1, y1, x2, y2, e["name"], e["distance"]))
                            gui_send_queue.put(
                                sfgui.GUICommand(
                                    sfgui.GUICommandType.UpdateEspBoxes,
                                    (client.window_handle, boxes),
                                )
                            )
                    except wizwalker.errors.MemoryReadError:
                        pass
                    except Exception as e:
                        logger.debug(f"esp loop error: {e}")
                    await asyncio.sleep(0.033)
            except asyncio.CancelledError:
                fetch_task.cancel()
                gui_send_queue.put(
                    sfgui.GUICommand(sfgui.GUICommandType.UpdateEspBoxes, None)
                )
                return

        global gui_send_queue
        global bot_task
        global flythrough_task
        global gui_thread
        global recv_queue
        global combat_task
        global dialogue_task
        global sigil_task
        global questing_task
        global speed_task
        global auto_pet_task
        global highlight_task
        global entity_stream_task
        global ui_dump_task
        global gates_stream_task
        global esp_task
        enemy_stats = []
        current_pos = None
        current_rotation = None

        paused_task_names = None
        previous_client_count = None

        last_known_handle_count = 0

        def _reap_dead_clients():
            nonlocal paused_task_names, previous_client_count
            global combat_task, dialogue_task, sigil_task, questing_task
            global speed_task, bot_task, auto_pet_task
            count_before = len(walker.clients)
            dead = walker.remove_dead_clients()
            if dead:
                for c in dead:
                    if c.window_handle in walker._managed_handles:
                        walker._managed_handles.remove(c.window_handle)
                    launched_account_map.pop(c.window_handle, None)
                    _hooking_in_progress.discard(c.window_handle)
                    logger.info(f"client '{c.title}' disconnected.")
                _send_hooked_clients_update()

                active_tasks = set()
                task_vars = {
                    "combat": combat_task,
                    "dialogue": dialogue_task,
                    "sigil": sigil_task,
                    "questing": questing_task,
                    "speed": speed_task,
                    "bot": bot_task,
                    "auto_pet": auto_pet_task,
                }
                for name, task in task_vars.items():
                    if task is not None and not task.cancelled():
                        active_tasks.add(name)
                        task.cancel()
                # also tear down any bot in the multi-slot dicts -
                # the legacy ``bot_task`` global only tracks slot 0,
                # so without this, slots 1+ keep running against
                # clients that just disappeared
                had_extra_slots = bool(bot_bridges) or bool(bot_tasks)
                for _b in list(bot_bridges.values()):
                    try:
                        _b.stop()
                    except Exception:
                        pass
                for _t in list(bot_tasks.values()):
                    if _t is not None and not _t.cancelled():
                        _t.cancel()
                bot_bridges.clear()
                bot_tasks.clear()
                if had_extra_slots:
                    # surface "bot" in active_tasks even if the
                    # legacy slot-0 global wasn't holding a task,
                    # so the "paused tasks" bookkeeping records
                    # that something stopped
                    active_tasks.add("bot")

                if "combat" in active_tasks:
                    combat_task = None
                if "dialogue" in active_tasks:
                    dialogue_task = None
                if "sigil" in active_tasks:
                    sigil_task = None
                if "questing" in active_tasks:
                    questing_task = None
                if "speed" in active_tasks:
                    speed_task = None
                if "bot" in active_tasks:
                    bot_task = None
                if "auto_pet" in active_tasks:
                    auto_pet_task = None

                for c in walker.clients:
                    c.combat_status = False
                    c.sigil_status = False
                    c.questing_status = False
                    c.auto_pet_status = False
                    c.dialogue_status = False
                    c.speed_status = False
                    c.feeding_pet_status = False
                    c.entity_detect_combat_status = False
                    # mirror the toggle-off cancel for Lua-driven combat
                    active = getattr(c, "_active_combat", None)
                    if active is not None:
                        try:
                            active.cancel_combat()
                        except Exception:
                            pass

                # promote remaining clients (p2→p1, …) so titles stay
                # contiguous and the GUI selector matches real clients
                # after the flag reset above, so the resync reflects the
                # paused (all-off) state
                _renumber_clients()
                _resync_toggle_status()

                if active_tasks:
                    previous_client_count = count_before
                    paused_task_names = active_tasks
                    logger.info(
                        f"client(s) disconnected. bot tasks paused. waiting for client count to be restored ({len(walker.clients)}/{previous_client_count})."
                    )
                    if "bot" in active_tasks:
                        logger.warning(
                            "bot script was interrupted and cannot be auto-resumed. please restart it manually."
                        )

                if not walker.clients:
                    gui_send_queue.put(
                        sfgui.GUICommand(
                            sfgui.GUICommandType.UpdateWindow,
                            ("Title", "Client: None"),
                        )
                    )
                    gui_send_queue.put(
                        sfgui.GUICommand(
                            sfgui.GUICommandType.UpdateWindow,
                            ("Zone", "Zone: "),
                        )
                    )
                    gui_send_queue.put(
                        sfgui.GUICommand(
                            sfgui.GUICommandType.UpdateWindow,
                            ("xyz", "Position (XYZ): "),
                        )
                    )
                    gui_send_queue.put(
                        sfgui.GUICommand(
                            sfgui.GUICommandType.UpdateWindow,
                            ("pry", "Orientation (PRY): "),
                        )
                    )

        while True:
            _reap_dead_clients()
            if walker.clients and foreground_client:
                try:
                    current_zone = await foreground_client.zone_name()
                    if current_zone and not await foreground_client.is_loading():
                        if await foreground_client.game_client.is_freecam():
                            camera = await foreground_client.game_client.free_camera_controller()
                            current_pos = await camera.position()
                            current_rotation: Orient = await camera.orientation()
                            current_pos.x = trunc(current_pos.x, 3)
                            current_pos.y = trunc(current_pos.y, 3)
                            current_pos.z = trunc(current_pos.z, 3)
                            current_rotation.yaw = trunc(current_rotation.yaw, 3)
                            current_rotation.pitch = trunc(current_rotation.pitch, 3)
                            current_rotation.roll = trunc(current_rotation.roll, 3)
                        else:
                            if parent := await foreground_client.client_object.parent():
                                if await parent.object_name() == "Player Object":
                                    children = await parent.children()
                                    for pet_object in children:
                                        current_pos = await pet_object.location()
                                        current_rotation = (
                                            await pet_object.orientation()
                                        )
                                else:
                                    current_pos: XYZ = (
                                        await foreground_client.body.position()
                                    )
                                    current_rotation: Orient = (
                                        await foreground_client.body.orientation()
                                    )
                                    current_pos.x = trunc(current_pos.x, 3)
                                    current_pos.y = trunc(current_pos.y, 3)
                                    current_pos.z = trunc(current_pos.z, 3)
                                    current_rotation.yaw = trunc(
                                        current_rotation.yaw, 3
                                    )
                                    current_rotation.pitch = trunc(
                                        current_rotation.pitch, 3
                                    )
                                    current_rotation.roll = trunc(
                                        current_rotation.roll, 3
                                    )
                    else:
                        current_pos: XYZ = XYZ(0, 0, 0)
                        current_rotation: Orient = Orient(0, 0, 0)

                    gui_send_queue.put(
                        sfgui.GUICommand(
                            sfgui.GUICommandType.UpdateWindow,
                            ("Title", f"Client: {foreground_client.title}"),
                        )
                    )
                    gui_send_queue.put(
                        sfgui.GUICommand(
                            sfgui.GUICommandType.UpdateWindow,
                            ("Zone", f"Zone: {current_zone}"),
                        )
                    )
                    gui_send_queue.put(
                        sfgui.GUICommand(
                            sfgui.GUICommandType.UpdateWindow,
                            (
                                "xyz",
                                f"Position (XYZ): {current_pos.x}, {current_pos.y}, {current_pos.z}",
                            ),
                        )
                    )
                    gui_send_queue.put(
                        sfgui.GUICommand(
                            sfgui.GUICommandType.UpdateWindow,
                            (
                                "pry",
                                f"Orientation (PRY): {current_rotation.pitch}, {current_rotation.roll}, {current_rotation.yaw}",
                            ),
                        )
                    )
                except Exception:
                    _reap_dead_clients()
                    await asyncio.sleep(0.5)
            elif not walker.clients:
                await asyncio.sleep(0.1)

            if initial_setup_complete and walker.clients:
                for c in walker.clients:
                    if getattr(c, "player_gid", None) is None:
                        try:
                            uid = await c.game_client.user_id()
                            if uid and uid != 0:
                                logger.debug(
                                    f"[gid] retry resolved '{c.title}': user_id={_mask_uid(uid)}"
                                )
                                c.player_gid = uid
                                vault_nick = wizlaunch.get_nickname_by_gid(uid)
                                if (
                                    vault_nick
                                    and c.window_handle not in launched_account_map
                                ):
                                    launched_account_map[c.window_handle] = vault_nick
                                    _send_hooked_clients_update()
                                nick = launched_account_map.get(c.window_handle)
                                if nick:
                                    wizlaunch.update_player_gid(nick, uid)
                                    logger.debug(
                                        f"[gid] retry saved user_id {_mask_uid(uid)} for '{nick}'"
                                    )
                                    _send_hooked_clients_update()
                            else:
                                logger.debug(
                                    f"[gid] retry '{c.title}': user_id still 0"
                                )
                        except Exception as e:
                            logger.debug(f"[gid] retry '{c.title}': exception {e}")

            if initial_setup_complete and not paused_task_names:
                all_handles = set(get_all_wizard_handles())
                managed = set(walker._managed_handles)
                unmanaged = all_handles - managed - released_handles

                hooked_any = False
                launch_order = [h for h in launched_account_map if h in unmanaged]
                for handle in launch_order:
                    walker._managed_handles.append(handle)
                    nc = walker.client_cls(handle)
                    walker.clients.append(nc)
                    existing_nums = set()
                    for c in walker.clients:
                        if c.title.startswith("p") and c.title[1:].isdigit():
                            existing_nums.add(int(c.title[1:]))
                    num = 1
                    while num in existing_nums:
                        num += 1
                    nc.title = f"p{num}"
                    _hooking_in_progress.add(handle)
                    _send_hooked_clients_update()
                    try:
                        await nc.activate_hooks()
                        await _init_client_attrs(nc)
                        logger.info(
                            f"auto-hooked vault-launched client '{nc.title}' ({launched_account_map[handle]})."
                        )
                        hooked_any = True
                    except wizwalker.errors.HookAlreadyActivated:
                        await _init_client_attrs(nc)
                        logger.info(
                            f"auto-hooked vault-launched client '{nc.title}' ({launched_account_map[handle]}, already hooked)."
                        )
                        hooked_any = True
                    except Exception as e:
                        logger.error(
                            f"failed to auto-hook vault-launched client (handle {handle}): {e}"
                        )
                        walker._managed_handles.remove(handle)
                        walker.clients.remove(nc)
                    finally:
                        _hooking_in_progress.discard(handle)

                if hooked_any:
                    _send_hooked_clients_update()
                    last_known_handle_count = len(get_all_wizard_handles())
                    _restart_always_on_tasks()
                    _restart_active_toggle_tasks()
                    _renumber_clients()
                    _resync_toggle_status()
                else:
                    current_handle_count = len(all_handles)
                    if current_handle_count != last_known_handle_count:
                        last_known_handle_count = current_handle_count
                        _send_hooked_clients_update()

            if paused_task_names and len(walker.clients) < previous_client_count:
                new_clients = walker.get_new_clients()
                if new_clients:
                    existing_nums = set()
                    for c in walker.clients:
                        if c.title.startswith("p") and c.title[1:].isdigit():
                            existing_nums.add(int(c.title[1:]))

                    for nc in new_clients:
                        num = 1
                        while num in existing_nums:
                            num += 1
                        nc.title = f"p{num}"
                        existing_nums.add(num)

                    for nc in new_clients:
                        _hooking_in_progress.add(nc.window_handle)
                        _send_hooked_clients_update()
                        try:
                            await nc.activate_hooks()
                        except wizwalker.errors.HookAlreadyActivated:
                            logger.debug(
                                f"client '{nc.title}' already hooked, skipping."
                            )
                        except Exception as e:
                            logger.error(f"failed to hook client '{nc.title}': {e}")
                        finally:
                            _hooking_in_progress.discard(nc.window_handle)
                        await _init_client_attrs(nc)
                        logger.info(f"new client '{nc.title}' hooked.")
                    _send_hooked_clients_update()

                    if len(walker.clients) >= previous_client_count:
                        resumable = paused_task_names - {"bot"}
                        for name in resumable:
                            if name == "combat":
                                for c in walker.clients:
                                    c.combat_status = True
                                combat_task = asyncio.create_task(
                                    try_task_coro(combat_loop, walker.clients, True)
                                )
                            elif name == "dialogue":
                                for c in walker.clients:
                                    c.dialogue_status = True
                                dialogue_task = asyncio.create_task(
                                    try_task_coro(dialogue_loop, walker.clients, True)
                                )
                            elif name == "sigil":
                                for c in walker.clients:
                                    c.sigil_status = True
                                sigil_task = asyncio.create_task(
                                    try_task_coro(sigil_loop, walker.clients, True)
                                )
                            elif name == "questing":
                                for c in walker.clients:
                                    c.questing_status = True
                                questing_task = asyncio.create_task(
                                    try_task_coro(questing_loop, walker.clients, True)
                                )
                            elif name == "speed":
                                for c in walker.clients:
                                    c.speed_status = True
                                speed_task = asyncio.create_task(
                                    try_task_coro(speed_switching, walker.clients)
                                )
                            elif name == "auto_pet":
                                for c in walker.clients:
                                    c.auto_pet_status = True
                                    c.feeding_pet_status = True
                                auto_pet_task = asyncio.create_task(
                                    try_task_coro(auto_pet_loop, walker.clients, True)
                                )

                        previous_client_count = None
                        paused_task_names = None
                        _restart_always_on_tasks()
                        _renumber_clients()
                        _resync_toggle_status()
                        logger.info("client count restored. resuming bot tasks.")

            try:
                while True:
                    com = recv_queue.get_nowait()
                    match com.com_type:
                        case sfgui.GUICommandType.Close:
                            if len(walker.clients) != 0:
                                raise sfgui.ToolClosedException
                            os._exit(0)
                        case sfgui.GUICommandType.AttemptedClose:
                            if not walker.clients:
                                os._exit(0)
                            raise sfgui.ToolClosedException
                        case sfgui.GUICommandType.Reboot:
                            global _reboot_requested
                            _handles = [
                                c.window_handle
                                for c in walker.clients
                                if c.is_running()
                            ]
                            if _handles:
                                with open(".skyfall_rehook", "w") as _f:
                                    _f.write("\n".join(str(h) for h in _handles))
                            _reboot_requested = True
                            raise sfgui.ToolClosedException
                        case sfgui.GUICommandType.ToggleOption:
                            if not walker.clients:
                                continue
                            # ToggleOption carries either a bare GUIKeys string
                            # (legacy / "All") or a (key, target) tuple from the
                            # per-client target selector. none target = all.
                            if isinstance(com.data, tuple):
                                _toggle_key, _toggle_target = com.data
                            else:
                                _toggle_key, _toggle_target = com.data, None
                            match _toggle_key:
                                case GUIKeys.toggle_speedhack:
                                    await toggle_speed_hotkey(_toggle_target)
                                case GUIKeys.toggle_combat:
                                    await toggle_combat_hotkey(target=_toggle_target)
                                case GUIKeys.toggle_dialogue:
                                    await toggle_dialogue_hotkey(_toggle_target)
                                case GUIKeys.toggle_sigil:
                                    await toggle_sigil_hotkey(_toggle_target)
                                case GUIKeys.toggle_questing:
                                    await toggle_questing_hotkey(_toggle_target)
                                case GUIKeys.toggle_auto_pet:
                                    await toggle_auto_pet_hotkey(_toggle_target)
                                case GUIKeys.toggle_auto_potion:
                                    await toggle_auto_potion_hotkey(_toggle_target)
                                case GUIKeys.toggle_fishing:
                                    await toggle_fishing_hotkey(_toggle_target)
                                case GUIKeys.toggle_freecam:
                                    await toggle_freecam_hotkey(target=_toggle_target)

                                case GUIKeys.toggle_camera_collision:
                                    if foreground_client:
                                        camera: ElasticCameraController = await foreground_client.game_client.elastic_camera_controller()
                                        collision_status = (
                                            await camera.check_collisions()
                                        )
                                        collision_status ^= True
                                        logger.debug(
                                            f"camera collisions {bool_to_string(collision_status)}"
                                        )
                                        await camera.write_check_collisions(
                                            collision_status
                                        )
                                case GUIKeys.toggle_show_expanded_logs:
                                    gui_send_queue.put(
                                        sfgui.GUICommand(
                                            sfgui.GUICommandType.UpdateConsole
                                        )
                                    )
                                case _:
                                    logger.debug(
                                        f"unknown window toggle: {_toggle_key}"
                                    )
                        case sfgui.GUICommandType.SetFishConfig:
                            global fish_config
                            fish_config = FishConfig.from_dict(com.data)
                            # apply live to an in-flight session
                            for c in walker.clients:
                                fisher = getattr(c, "_fisher", None)
                                if fisher is not None:
                                    fisher.config = fish_config
                        case sfgui.GUICommandType.SetCombatVerboseLogs:
                            combat_handler._VERBOSE_LOG = bool(com.data)
                            settings.set_setting(
                                "verbose_combat_logs", combat_handler._VERBOSE_LOG
                            )
                            logger.debug(
                                "Console: combat debug logging "
                                + (
                                    "enabled."
                                    if combat_handler._VERBOSE_LOG
                                    else "disabled."
                                )
                            )
                        case sfgui.GUICommandType.Copy:
                            if not walker.clients:
                                continue
                            match com.data:
                                case GUIKeys.copy_zone:
                                    pyperclip.copy(current_zone)
                                case GUIKeys.copy_position:
                                    pyperclip.copy(
                                        f"{current_pos.x}, {current_pos.y}, {current_pos.z}"
                                    )
                                case GUIKeys.copy_rotation:
                                    pyperclip.copy(
                                        f"Orient({current_rotation.pitch}, {current_rotation.roll}, {current_rotation.yaw})"
                                    )
                                case GUIKeys.copy_entity_list:
                                    if foreground_client:
                                        gui_send_queue.put(
                                            sfgui.GUICommand(
                                                sfgui.GUICommandType.ShowEntityListPopup
                                            )
                                        )
                                case GUIKeys.copy_gates_list:
                                    if foreground_client:
                                        gui_send_queue.put(
                                            sfgui.GUICommand(
                                                sfgui.GUICommandType.ShowGatesListPopup
                                            )
                                        )
                                case GUIKeys.copy_camera_position:
                                    if foreground_client:
                                        camera = await foreground_client.game_client.selected_camera_controller()
                                        camera_pos = await camera.position()
                                        pyperclip.copy(
                                            f"XYZ({camera_pos.x}, {camera_pos.y}, {camera_pos.z})"
                                        )
                                case GUIKeys.copy_camera_rotation:
                                    if foreground_client:
                                        camera = await foreground_client.game_client.selected_camera_controller()
                                        (
                                            camera_pitch,
                                            camera_roll,
                                            camera_yaw,
                                        ) = await camera.orientation()
                                        pyperclip.copy(
                                            f"Orient({camera_pitch}, {camera_roll}, {camera_pitch})"
                                        )
                                case GUIKeys.copy_ui_tree:
                                    if foreground_client:
                                        foreground: Client = foreground_client
                                        from wizwalker.constants import (
                                            Primitive,
                                        )

                                        # cancel any in-flight dump first so a
                                        # rapid re-trigger doesn't stack walks
                                        if (
                                            ui_dump_task is not None
                                            and not ui_dump_task.done()
                                        ):
                                            ui_dump_task.cancel()

                                        pid = foreground.process_id
                                        notext = _UI_NOTEXT_VTABLES.setdefault(
                                            pid, set()
                                        )

                                        # open the popup IMMEDIATELY (empty) so
                                        # the UI feels responsive while the
                                        # walk (or cache replay) runs
                                        gui_send_queue.put(
                                            sfgui.GUICommand(
                                                sfgui.GUICommandType.ShowUITreePopup
                                            )
                                        )

                                        # run the dump as a task so closing the
                                        # popup mid-walk can cancel it
                                        # (CancelUITreeDump handler below)
                                        async def _do_dump():
                                            try:
                                                now = time.monotonic()
                                                cached_entry = _UI_TREE_CACHE.get(pid)
                                                if (
                                                    cached_entry
                                                    and now - cached_entry[0]
                                                    < _UI_TREE_TTL
                                                ):
                                                    rows = cached_entry[1]
                                                else:

                                                    async def _read_vtable(window):
                                                        try:
                                                            return await window.read_value_from_offset(
                                                                0, Primitive.int64
                                                            )
                                                        except Exception:
                                                            return 0

                                                    async def _type_name_for(
                                                        vtable, window
                                                    ):
                                                        if not vtable:
                                                            return ""
                                                        key = (pid, vtable)
                                                        cached = _UI_TYPE_CACHE.get(key)
                                                        if cached is not None:
                                                            return cached
                                                        try:
                                                            name = await window.maybe_read_type_name()
                                                        except Exception:
                                                            name = ""
                                                        _UI_TYPE_CACHE[key] = name
                                                        return name

                                                    async def _maybe_text_for(
                                                        vtable, window
                                                    ):
                                                        if (
                                                            vtable
                                                            and vtable in notext
                                                            and (vtable & 0xF)
                                                        ):
                                                            return None
                                                        try:
                                                            return await window.maybe_text()
                                                        except Exception:
                                                            return None

                                                    async def _children(window):
                                                        try:
                                                            return (
                                                                await window.children()
                                                            )
                                                        except Exception:
                                                            return []

                                                    async def collect_node(
                                                        window: Window,
                                                        depth: int,
                                                        parent_path: list[str],
                                                    ):
                                                        vtable = await _read_vtable(
                                                            window
                                                        )
                                                        (
                                                            name,
                                                            type_name,
                                                            text,
                                                            children,
                                                        ) = await asyncio.gather(
                                                            window.name(),
                                                            _type_name_for(
                                                                vtable, window
                                                            ),
                                                            _maybe_text_for(
                                                                vtable, window
                                                            ),
                                                            _children(window),
                                                        )

                                                        path = (
                                                            parent_path + [name]
                                                            if depth > 0
                                                            else []
                                                        )
                                                        display = (
                                                            f"[{name}] {type_name}"
                                                        )
                                                        row = (
                                                            depth,
                                                            display,
                                                            path,
                                                            text,
                                                            vtable,
                                                        )

                                                        if not children:
                                                            return [row]

                                                        child_path = (
                                                            parent_path + [name]
                                                            if depth > 0
                                                            else []
                                                        )
                                                        child_results = (
                                                            await asyncio.gather(
                                                                *(
                                                                    collect_node(
                                                                        c,
                                                                        depth + 1,
                                                                        child_path,
                                                                    )
                                                                    for c in children
                                                                )
                                                            )
                                                        )
                                                        out = [row]
                                                        for sub in child_results:
                                                            out.extend(sub)
                                                        return out

                                                    walked = await collect_node(
                                                        foreground.root_window, 0, []
                                                    )

                                                    for _, _, _, text, vtable in walked:
                                                        if not vtable:
                                                            continue
                                                        key = (pid, vtable)
                                                        if text is not None:
                                                            notext.discard(vtable)
                                                            _UI_VTABLE_SEEN.pop(
                                                                key, None
                                                            )
                                                            continue
                                                        seen = (
                                                            _UI_VTABLE_SEEN.get(key, 0)
                                                            + 1
                                                        )
                                                        _UI_VTABLE_SEEN[key] = seen
                                                        if (
                                                            seen
                                                            >= _NOTEXT_PROMOTE_AFTER
                                                        ):
                                                            notext.add(vtable)

                                                    rows = [
                                                        (d, disp, p, t)
                                                        for d, disp, p, t, _ in walked
                                                    ]
                                                    _UI_TREE_CACHE[pid] = (now, rows)

                                                _BATCH = 100
                                                for i in range(0, len(rows), _BATCH):
                                                    gui_send_queue.put(
                                                        sfgui.GUICommand(
                                                            sfgui.GUICommandType.UITreeAppendRows,
                                                            rows[i : i + _BATCH],
                                                        )
                                                    )
                                                    await asyncio.sleep(0)

                                                gui_send_queue.put(
                                                    sfgui.GUICommand(
                                                        sfgui.GUICommandType.UITreeDone
                                                    )
                                                )

                                                ui_tree = (
                                                    "\n".join(
                                                        f"{'-' * d} {disp}"
                                                        for d, disp, _, _ in rows
                                                    )
                                                    + "\n"
                                                    if rows
                                                    else ""
                                                )
                                                if ui_tree:
                                                    logger.debug(
                                                        f"copied ui tree for client {foreground.title}"
                                                    )
                                                    pyperclip.copy(ui_tree)
                                                    logger.success(
                                                        "available ui paths:"
                                                    )
                                                else:
                                                    logger.error(
                                                        "failed to load ui tree. please try again."
                                                    )
                                            except asyncio.CancelledError:
                                                logger.debug(
                                                    "ui tree dump cancelled (popup closed)"
                                                )
                                                return

                                        ui_dump_task = asyncio.create_task(_do_dump())
                                case GUIKeys.copy_stats:
                                    if enemy_stats:
                                        pyperclip.copy("\n".join(enemy_stats))
                                    else:
                                        logger.info(
                                            "no stats are loaded. select an enemy index corresponding to its position on the duel circle, then click the copy button."
                                        )

                                case GUIKeys.copy_logs:
                                    gui_send_queue.put(
                                        sfgui.GUICommand(
                                            sfgui.GUICommandType.CopyConsole, None
                                        )
                                    )
                                case _:
                                    logger.debug(f"unknown copy value: {com.data}")
                        case sfgui.GUICommandType.ScanGame:
                            if not foreground_client:
                                logger.warning("scan_game: no foreground client")
                                continue
                            try:
                                from src.nav.scraper import scan_game

                                await scan_game(foreground_client)
                            except Exception:
                                logger.exception("scraper: scan_game crashed")
                        case sfgui.GUICommandType.EnumerateZoneGates:
                            if not foreground_client:
                                logger.warning("gates: no foreground client")
                                continue
                            try:
                                from src.nav.scraper import enumerate_zone_gates

                                await enumerate_zone_gates(foreground_client)
                            except Exception:
                                logger.exception(
                                    "scraper: enumerate_zone_gates crashed"
                                )
                        case sfgui.GUICommandType.ProcessCurrentZone:
                            if not foreground_client:
                                logger.warning("process: no foreground client")
                                continue
                            try:
                                from src.nav.scraper import process_current_zone

                                await process_current_zone(foreground_client)
                            except Exception:
                                logger.exception(
                                    "scraper: process_current_zone crashed"
                                )
                        case sfgui.GUICommandType.EnumerateInteractiveTeleporters:
                            if not foreground_client:
                                logger.warning("itp: no foreground client")
                                continue
                            try:
                                from src.nav.scraper import (
                                    enumerate_interactive_teleporters,
                                )

                                await enumerate_interactive_teleporters(
                                    foreground_client
                                )
                            except Exception:
                                logger.exception(
                                    "scraper: enumerate_interactive_teleporters crashed"
                                )
                        case sfgui.GUICommandType.SanitySweepZones:
                            try:
                                from src.nav.scraper import sanity_sweep_zones_txt

                                sanity_sweep_zones_txt()
                            except Exception:
                                logger.exception(
                                    "scraper: sanity_sweep_zones_txt crashed"
                                )
                        case sfgui.GUICommandType.ProbeYawOffset:
                            if not foreground_client:
                                logger.warning("probe_yaw_offset: no foreground client")
                                continue
                            try:
                                from src.nav.scraper import probe_yaw_offset

                                await probe_yaw_offset(foreground_client)
                            except Exception:
                                logger.exception("scraper: probe_yaw_offset crashed")
                        case sfgui.GUICommandType.VerifyYaw:
                            if not foreground_client:
                                logger.warning("verify_yaw: no foreground client")
                                continue
                            try:
                                from src.nav.scraper import verify_yaw

                                await verify_yaw(foreground_client)
                            except Exception:
                                logger.exception("scraper: verify_yaw crashed")
                        case sfgui.GUICommandType.WalkThroughGate:
                            if not foreground_client:
                                logger.warning(
                                    "walk_through_gate: no foreground client"
                                )
                                continue
                            name = com.data if isinstance(com.data, str) else ""
                            if not name:
                                logger.warning("walk_through_gate: empty name")
                                continue
                            try:
                                from src.nav.scraper import walk_through_gate

                                await walk_through_gate(foreground_client, name)
                            except Exception:
                                logger.exception("scraper: walk_through_gate crashed")
                        case sfgui.GUICommandType.CorrelateCalibration:
                            try:
                                from src.nav.scraper import correlate_calibration

                                await correlate_calibration()
                            except Exception:
                                logger.exception(
                                    "scraper: correlate_calibration crashed"
                                )
                        case sfgui.GUICommandType.ApplyCalibrationFixes:
                            try:
                                from src.nav.scraper import apply_calibration_fixes

                                stats = apply_calibration_fixes()
                                logger.info(
                                    f"scraper: apply_calibration_fixes -> {stats}"
                                )
                            except Exception:
                                logger.exception(
                                    "scraper: apply_calibration_fixes crashed"
                                )
                        case sfgui.GUICommandType.ToggleGateRecorder:
                            if not foreground_client:
                                logger.warning(
                                    "gate_recorder: no foreground client selected"
                                )
                                continue
                            from src.nav.gate_recorder import GateRecorder

                            if not hasattr(main, "_gate_recorder"):
                                main._gate_recorder = None
                            enable = com.data
                            if enable:
                                if (
                                    main._gate_recorder is None
                                    or not main._gate_recorder.active
                                ):
                                    main._gate_recorder = GateRecorder(
                                        foreground_client
                                    )
                                    await main._gate_recorder.start()
                            else:
                                if main._gate_recorder is not None:
                                    await main._gate_recorder.stop()
                                    main._gate_recorder = None
                        case sfgui.GUICommandType.Teleport:
                            if not walker.clients:
                                continue
                            match com.data:
                                case GUIKeys.hotkey_quest_tp:
                                    await navmap_teleport_hotkey()
                                case GUIKeys.mass_hotkey_mass_tp:
                                    await mass_navmap_teleport_hotkey()
                                case GUIKeys.hotkey_freecam_tp:
                                    await tp_to_freecam_hotkey()
                                case _:
                                    logger.debug(f"unknown teleport type: {com.data}")
                        case sfgui.GUICommandType.CustomTeleport:
                            if not walker.clients:
                                continue
                            if foreground_client:
                                mass = bool(com.data.get("mass"))

                                x_input = param_input(com.data["X"], current_pos.x)
                                y_input = param_input(com.data["Y"], current_pos.y)
                                z_input = param_input(com.data["Z"], current_pos.z)
                                yaw_input = param_input(
                                    com.data["Yaw"], current_rotation.yaw
                                )
                                custom_xyz = XYZ(x=x_input, y=y_input, z=z_input)
                                logger.debug(
                                    f"teleporting client {foreground_client.title} to {custom_xyz}, yaw= {yaw_input}"
                                )
                                await foreground_client.teleport(custom_xyz)
                                await foreground_client.body.write_yaw(yaw_input)

                                if mass and background_clients:

                                    async def _bg_custom_tp(c):
                                        pos = await c.body.position()
                                        rot = await c.body.orientation()
                                        bx = param_input(com.data["X"], pos.x)
                                        by = param_input(com.data["Y"], pos.y)
                                        bz = param_input(com.data["Z"], pos.z)
                                        byaw = param_input(com.data["Yaw"], rot.yaw)
                                        await c.teleport(XYZ(x=bx, y=by, z=bz))
                                        await c.body.write_yaw(byaw)

                                    await asyncio.gather(
                                        *[_bg_custom_tp(c) for c in background_clients]
                                    )
                        case sfgui.GUICommandType.EntityTeleport:
                            if not walker.clients:
                                continue
                            if foreground_client:
                                gid_str = (
                                    com.data.get("gid", "")
                                    if isinstance(com.data, dict)
                                    else ""
                                )
                                name_str = (
                                    com.data.get("name", "")
                                    if isinstance(com.data, dict)
                                    else str(com.data)
                                )
                                mass = (
                                    bool(com.data.get("mass"))
                                    if isinstance(com.data, dict)
                                    else False
                                )
                                targets = [foreground_client]
                                if mass:
                                    targets.extend(background_clients)

                                async def _entity_tp(c):
                                    sprinter = EntityClient(c)
                                    target_entity = None
                                    if gid_str:
                                        try:
                                            target_gid = int(gid_str)
                                            entities = await sprinter.entities()
                                            for entity in entities:
                                                if (
                                                    await entity.global_id_full()
                                                    == target_gid
                                                ):
                                                    target_entity = entity
                                                    break
                                        except (ValueError, TypeError):
                                            logger.error(f"invalid gid: {gid_str}")
                                    if target_entity is None and name_str:
                                        entities = await sprinter.entities_vague(
                                            name_str
                                        )
                                        if entities:
                                            target_entity = await sprinter.closest(
                                                entities
                                            )
                                    if target_entity:
                                        entity_pos = await target_entity.location()
                                        await c.teleport(entity_pos)

                                await asyncio.gather(*[_entity_tp(c) for c in targets])
                        case sfgui.GUICommandType.EntityTeleportNear:
                            if not walker.clients:
                                continue
                            if foreground_client:
                                from src.lang.client import _teleport_near

                                sprinter = EntityClient(foreground_client)
                                gid_str = (
                                    com.data.get("gid", "")
                                    if isinstance(com.data, dict)
                                    else ""
                                )
                                target_entity = None
                                if gid_str:
                                    try:
                                        target_gid = int(gid_str)
                                        entities = await sprinter.entities()
                                        for entity in entities:
                                            if (
                                                await entity.global_id_full()
                                                == target_gid
                                            ):
                                                target_entity = entity
                                                break
                                    except (ValueError, TypeError):
                                        logger.error(f"invalid gid: {gid_str}")
                                if target_entity:
                                    entity_pos = await target_entity.location()
                                    await _teleport_near(
                                        foreground_client, entity_pos, 150.0, 1500.0
                                    )
                        case sfgui.GUICommandType.SelectEnemy:
                            if not walker.clients:
                                gui_send_queue.put(
                                    sfgui.GUICommand(
                                        sfgui.GUICommandType.UpdateWindowValues,
                                        ("EnemyInput", []),
                                    )
                                )
                                gui_send_queue.put(
                                    sfgui.GUICommand(
                                        sfgui.GUICommandType.UpdateWindowValues,
                                        ("AllyInput", []),
                                    )
                                )
                                continue
                            if (
                                foreground_client
                                and await foreground_client.in_battle()
                            ):
                                (
                                    ally_index,
                                    enemy_index,
                                    base_damage,
                                    school_id,
                                    crit_status,
                                    force_school_status,
                                    swapped,
                                    view_side,
                                ) = com.data
                                if not base_damage:
                                    base_damage = None
                                else:
                                    base_damage = int(base_damage)
                                view_target = view_side == "enemy"
                                result = await total_stats(
                                    foreground_client,
                                    ally_index,
                                    enemy_index,
                                    base_damage,
                                    school_id,
                                    crit_status,
                                    force_school_status,
                                    swapped=swapped,
                                    view_target=view_target,
                                )
                                if result is None:
                                    continue
                                (
                                    stat_lines,
                                    ally_names,
                                    enemy_names,
                                    ally_i,
                                    enemy_i,
                                    school_name,
                                    slot_info,
                                ) = result
                                gui_send_queue.put(
                                    sfgui.GUICommand(
                                        sfgui.GUICommandType.UpdateWindow,
                                        ("stat_viewer", stat_lines),
                                    )
                                )
                                gui_send_queue.put(
                                    sfgui.GUICommand(
                                        sfgui.GUICommandType.UpdateWindowValues,
                                        ("EnemyInput", enemy_names),
                                    )
                                )
                                gui_send_queue.put(
                                    sfgui.GUICommand(
                                        sfgui.GUICommandType.UpdateWindowValues,
                                        ("AllyInput", ally_names),
                                    )
                                )
                                if enemy_i < len(enemy_names):
                                    gui_send_queue.put(
                                        sfgui.GUICommand(
                                            sfgui.GUICommandType.UpdateWindow,
                                            ("EnemyInput", enemy_names[enemy_i]),
                                        )
                                    )
                                if ally_i < len(ally_names):
                                    gui_send_queue.put(
                                        sfgui.GUICommand(
                                            sfgui.GUICommandType.UpdateWindow,
                                            ("AllyInput", ally_names[ally_i]),
                                        )
                                    )

                                gui_send_queue.put(
                                    sfgui.GUICommand(
                                        sfgui.GUICommandType.UpdateWindow,
                                        ("calc_school", school_name),
                                    )
                                )
                                gui_send_queue.put(
                                    sfgui.GUICommand(
                                        sfgui.GUICommandType.UpdateWindow,
                                        ("slot_info", slot_info),
                                    )
                                )
                            else:
                                gui_send_queue.put(
                                    sfgui.GUICommand(
                                        sfgui.GUICommandType.UpdateWindowValues,
                                        ("EnemyInput", []),
                                    )
                                )
                                gui_send_queue.put(
                                    sfgui.GUICommand(
                                        sfgui.GUICommandType.UpdateWindowValues,
                                        ("AllyInput", []),
                                    )
                                )
                        case sfgui.GUICommandType.LiveCombatRefresh:
                            # build a combat snapshot for the foreground client
                            # and push it to the Stats tab. always responds
                            # (even with empty combatants) so the GUI knows
                            # the request was serviced
                            try:
                                snap = await build_combat_snapshot(foreground_client)
                            except Exception:
                                logger.error(
                                    "LiveCombatRefresh: snapshot build failed",
                                    exc_info=True,
                                )
                                snap = {
                                    "in_combat": False,
                                    "client_title": "",
                                    "combatants": [],
                                }
                            gui_send_queue.put(
                                sfgui.GUICommand(
                                    sfgui.GUICommandType.UpdateWindow,
                                    ("live_combat", snap),
                                )
                            )
                        case sfgui.GUICommandType.XYZSync:
                            if not walker.clients:
                                continue
                            await xyz_sync_hotkey()
                        case sfgui.GUICommandType.XPress:
                            if not walker.clients:
                                continue
                            await x_press_hotkey()
                        case sfgui.GUICommandType.FriendTeleport:
                            if not walker.clients:
                                continue
                            await friend_teleport_sync_hotkey()

                        case sfgui.GUICommandType.RebindHotkey:
                            action_id, new_key, new_mods = com.data

                            old_binding = _active_bindings.get(action_id)
                            if old_binding:
                                old_mods = ModifierKeys.NOREPEAT
                                for m in old_binding.get("modifiers", []):
                                    old_mods |= ModifierKeys[m]
                                try:
                                    await listener.remove_hotkey(
                                        Keycode[old_binding["key"]], modifiers=old_mods
                                    )
                                except Exception:
                                    pass
                                del _active_bindings[action_id]

                            if new_key:
                                callback = (
                                    _kill_tool_callback
                                    if action_id == "kill_tool"
                                    else _make_hotkey_callback(action_id)
                                )
                                if hotkey_status or action_id == "kill_tool":
                                    mods = ModifierKeys.NOREPEAT
                                    for m in new_mods:
                                        mods |= ModifierKeys[m]
                                    try:
                                        await listener.add_hotkey(
                                            Keycode[new_key], callback, modifiers=mods
                                        )
                                        _active_bindings[action_id] = {
                                            "key": new_key,
                                            "modifiers": new_mods,
                                        }
                                    except Exception as e:
                                        logger.debug(
                                            f"failed to register rebound hotkey for {action_id}: {e}"
                                        )
                            else:
                                pass
                            logger.debug(
                                f"hotkey rebound: {action_id} -> {new_key} {new_mods}"
                            )
                        case sfgui.GUICommandType.AnchorCam:
                            if not walker.clients:
                                continue
                            if foreground_client:
                                if freecam_status:
                                    await toggle_freecam_hotkey()
                                camera = await foreground_client.game_client.elastic_camera_controller()
                                sprinter = EntityClient(foreground_client)
                                gid_str = (
                                    com.data.get("gid", "")
                                    if isinstance(com.data, dict)
                                    else ""
                                )
                                name_str = (
                                    com.data.get("name", "")
                                    if isinstance(com.data, dict)
                                    else str(com.data)
                                )
                                target_entity = None
                                if gid_str:
                                    try:
                                        target_gid = int(gid_str)
                                        entities = await sprinter.entities()
                                        for entity in entities:
                                            if (
                                                await entity.global_id_full()
                                                == target_gid
                                            ):
                                                target_entity = entity
                                                break
                                    except (ValueError, TypeError):
                                        logger.error(f"invalid gid: {gid_str}")
                                if target_entity is None and name_str:
                                    entities = await sprinter.entities_vague(name_str)
                                    if entities:
                                        target_entity = await sprinter.closest(entities)
                                if target_entity:
                                    entity_name = await target_entity.object_name()
                                    logger.debug(
                                        f"anchoring camera to entity {entity_name}"
                                    )
                                    await camera.write_attached_client_object(
                                        target_entity
                                    )

                        case sfgui.GUICommandType.SetCamPosition:
                            if not walker.clients:
                                continue
                            if foreground_client:
                                if not freecam_status:
                                    await toggle_freecam_hotkey()
                                camera: DynamicCameraController = await foreground_client.game_client.selected_camera_controller()
                                camera_pos: XYZ = await camera.position()
                                (
                                    camera_pitch,
                                    camera_roll,
                                    camera_yaw,
                                ) = await camera.orientation()
                                x_input = param_input(com.data["X"], camera_pos.x)
                                y_input = param_input(com.data["Y"], camera_pos.y)
                                z_input = param_input(com.data["Z"], camera_pos.z)
                                yaw_input = param_input(com.data["Yaw"], camera_yaw)
                                roll_input = param_input(com.data["Roll"], camera_roll)
                                pitch_input = param_input(
                                    com.data["Pitch"], camera_pitch
                                )
                                input_pos = XYZ(x_input, y_input, z_input)
                                logger.debug(
                                    f"teleporting camera to {input_pos}, yaw={yaw_input}, roll={roll_input}, pitch={pitch_input}"
                                )
                                await camera.write_position(input_pos)
                                await camera.update_orientation(
                                    Orient(pitch_input, roll_input, yaw_input)
                                )
                        case sfgui.GUICommandType.SetCamDistance:
                            if not walker.clients:
                                continue
                            if foreground_client:
                                camera = await foreground_client.game_client.elastic_camera_controller()
                                current_zoom = await camera.distance()
                                current_min = await camera.min_distance()
                                current_max = await camera.max_distance()
                                distance_input = param_input(
                                    com.data["Distance"], current_zoom
                                )
                                min_input = param_input(com.data["Min"], current_min)
                                max_input = param_input(com.data["Max"], current_max)
                                logger.debug(
                                    f"setting camera distance to {distance_input}, min={min_input}, max={max_input}"
                                )
                                if com.data["Distance"]:
                                    await camera.write_distance_target(distance_input)
                                    await camera.write_distance(distance_input)
                                if com.data["Min"]:
                                    await camera.write_min_distance(min_input)
                                    await camera.write_zoom_resolution(min_input)
                                if com.data["Max"]:
                                    await camera.write_max_distance(max_input)
                        case sfgui.GUICommandType.PopulateCamera:
                            if not walker.clients:
                                continue
                            if foreground_client:
                                camera = await foreground_client.game_client.selected_camera_controller()
                                camera_pos = await camera.position()
                                (
                                    camera_pitch,
                                    camera_roll,
                                    camera_yaw,
                                ) = await camera.orientation()
                                elastic_camera = await foreground_client.game_client.elastic_camera_controller()
                                current_zoom = await elastic_camera.distance()
                                current_min = await elastic_camera.min_distance()
                                current_max = await elastic_camera.max_distance()
                                gui_send_queue.put(
                                    sfgui.GUICommand(
                                        sfgui.GUICommandType.UpdateWindow,
                                        ("CamXInput", f"{camera_pos.x:.2f}"),
                                    )
                                )
                                gui_send_queue.put(
                                    sfgui.GUICommand(
                                        sfgui.GUICommandType.UpdateWindow,
                                        ("CamYInput", f"{camera_pos.y:.2f}"),
                                    )
                                )
                                gui_send_queue.put(
                                    sfgui.GUICommand(
                                        sfgui.GUICommandType.UpdateWindow,
                                        ("CamZInput", f"{camera_pos.z:.2f}"),
                                    )
                                )
                                gui_send_queue.put(
                                    sfgui.GUICommand(
                                        sfgui.GUICommandType.UpdateWindow,
                                        ("CamYawInput", f"{camera_yaw:.2f}"),
                                    )
                                )
                                gui_send_queue.put(
                                    sfgui.GUICommand(
                                        sfgui.GUICommandType.UpdateWindow,
                                        ("CamRollInput", f"{camera_roll:.2f}"),
                                    )
                                )
                                gui_send_queue.put(
                                    sfgui.GUICommand(
                                        sfgui.GUICommandType.UpdateWindow,
                                        ("CamPitchInput", f"{camera_pitch:.2f}"),
                                    )
                                )
                                gui_send_queue.put(
                                    sfgui.GUICommand(
                                        sfgui.GUICommandType.UpdateWindow,
                                        ("CamEntityInput", "Player Object"),
                                    )
                                )
                                gui_send_queue.put(
                                    sfgui.GUICommand(
                                        sfgui.GUICommandType.UpdateWindow,
                                        ("CamDistanceInput", f"{current_zoom:.2f}"),
                                    )
                                )
                                gui_send_queue.put(
                                    sfgui.GUICommand(
                                        sfgui.GUICommandType.UpdateWindow,
                                        ("CamMinInput", f"{current_min:.2f}"),
                                    )
                                )
                                gui_send_queue.put(
                                    sfgui.GUICommand(
                                        sfgui.GUICommandType.UpdateWindow,
                                        ("CamMaxInput", f"{current_max:.2f}"),
                                    )
                                )
                                logger.debug(
                                    "populated camera fields with current values."
                                )
                        case sfgui.GUICommandType.PopulatePlayerGID:
                            if not walker.clients:
                                continue
                            if foreground_client:
                                gid = await foreground_client.game_client.player_gid()
                                gui_send_queue.put(
                                    sfgui.GUICommand(
                                        sfgui.GUICommandType.UpdateWindow,
                                        ("CamEntityGIDInput", str(gid)),
                                    )
                                )
                        case sfgui.GUICommandType.GoToZone:
                            if not walker.clients:
                                continue
                            if foreground_client:
                                clients = [foreground_client]
                                if com.data[0]:
                                    for c in background_clients:
                                        clients.append(c)
                                try:
                                    await to_zone(clients, com.data[1])
                                    logger.debug(
                                        "reached destination zone: "
                                        + await foreground_client.zone_name()
                                    )
                                except Exception:
                                    logger.error(
                                        "failed to go to zone.  it may be spelled incorrectly, or may not be supported."
                                    )
                        case sfgui.GUICommandType.GoToWorld:
                            if not walker.clients:
                                continue
                            if foreground_client:
                                clients = [foreground_client]
                                if com.data[0]:
                                    for c in background_clients:
                                        clients.append(c)
                                await to_world(clients, com.data[1])
                        case sfgui.GUICommandType.GoToBazaar:
                            if not walker.clients:
                                continue
                            if foreground_client:
                                clients = [foreground_client]
                                if com.data:
                                    for c in background_clients:
                                        clients.append(c)
                                try:
                                    await to_zone(
                                        clients,
                                        "WizardCity/WC_Streets/Interiors/WC_OldeTown_AuctionHouse",
                                    )
                                    logger.debug(
                                        "reached destination zone: "
                                        + await foreground_client.zone_name()
                                    )
                                except Exception:
                                    logger.error(
                                        "failed to go to zone.  it may be spelled incorrectly, or may not be supported."
                                    )
                        case sfgui.GUICommandType.RefillPotions:
                            if not walker.clients:
                                continue
                            if foreground_client:
                                clients = [foreground_client]
                                if com.data:
                                    for c in background_clients:
                                        clients.append(c)
                                await asyncio.gather(
                                    *[
                                        auto_potions_force_buy(client, True)
                                        for client in clients
                                    ]
                                )
                        case sfgui.GUICommandType.ExecuteFlythrough:
                            if not walker.clients:
                                continue

                            async def _flythrough():
                                try:
                                    await execute_flythrough(
                                        foreground_client, com.data
                                    )
                                    await foreground_client.camera_elastic()
                                finally:
                                    gui_send_queue.put(
                                        sfgui.GUICommand(
                                            sfgui.GUICommandType.UpdateWindow,
                                            ("FlythroughStatus", "Disabled"),
                                        )
                                    )

                            if foreground_client:
                                flythrough_task = asyncio.create_task(_flythrough())
                                gui_send_queue.put(
                                    sfgui.GUICommand(
                                        sfgui.GUICommandType.UpdateWindow,
                                        ("FlythroughStatus", "Enabled"),
                                    )
                                )
                        case sfgui.GUICommandType.KillFlythrough:
                            if not walker.clients:
                                continue
                            if (
                                flythrough_task is not None
                                and not flythrough_task.cancelled()
                            ):
                                flythrough_task.cancel()
                                flythrough_task = None
                                await asyncio.sleep(0)
                                await foreground_client.camera_elastic()
                            gui_send_queue.put(
                                sfgui.GUICommand(
                                    sfgui.GUICommandType.UpdateWindow,
                                    ("FlythroughStatus", "Disabled"),
                                )
                            )
                        case sfgui.GUICommandType.HighlightEntity:
                            if highlight_task and not highlight_task.done():
                                highlight_task.cancel()
                            if foreground_client and com.data:
                                highlight_task = asyncio.create_task(
                                    _highlight_entity_loop(foreground_client, com.data)
                                )

                        case sfgui.GUICommandType.HighlightUIWindow:
                            if highlight_task and not highlight_task.done():
                                highlight_task.cancel()
                            if foreground_client and com.data:
                                highlight_task = asyncio.create_task(
                                    _highlight_ui_window_loop(
                                        foreground_client, com.data
                                    )
                                )

                        case sfgui.GUICommandType.CancelUITreeDump:
                            if ui_dump_task and not ui_dump_task.done():
                                ui_dump_task.cancel()

                        case sfgui.GUICommandType.ClearHighlight:
                            if highlight_task and not highlight_task.done():
                                highlight_task.cancel()
                                highlight_task = None
                            gui_send_queue.put(
                                sfgui.GUICommand(
                                    sfgui.GUICommandType.UpdateHighlightBox, None
                                )
                            )

                        case sfgui.GUICommandType.StartEntityStream:
                            if entity_stream_task and not entity_stream_task.done():
                                entity_stream_task.cancel()
                            if foreground_client:
                                entity_stream_task = asyncio.create_task(
                                    _entity_stream_loop(foreground_client)
                                )

                        case sfgui.GUICommandType.StopEntityStream:
                            if entity_stream_task and not entity_stream_task.done():
                                entity_stream_task.cancel()
                                entity_stream_task = None

                        case sfgui.GUICommandType.StartGatesStream:
                            if gates_stream_task and not gates_stream_task.done():
                                gates_stream_task.cancel()
                            if foreground_client:
                                gates_stream_task = asyncio.create_task(
                                    _gates_stream_loop(foreground_client)
                                )

                        case sfgui.GUICommandType.StopGatesStream:
                            if gates_stream_task and not gates_stream_task.done():
                                gates_stream_task.cancel()
                                gates_stream_task = None

                        case sfgui.GUICommandType.ToggleEsp:
                            if esp_task and not esp_task.done():
                                esp_task.cancel()
                                esp_task = None
                                gui_send_queue.put(
                                    sfgui.GUICommand(
                                        sfgui.GUICommandType.UpdateWindow,
                                        ("EspStatus", "Disabled"),
                                    )
                                )
                            elif foreground_client:
                                esp_task = asyncio.create_task(
                                    _esp_loop(foreground_client)
                                )
                                gui_send_queue.put(
                                    sfgui.GUICommand(
                                        sfgui.GUICommandType.UpdateWindow,
                                        ("EspStatus", "Enabled"),
                                    )
                                )

                        case sfgui.GUICommandType.ExecuteBot:
                            if not walker.clients:
                                continue

                            # accept both the new (slot_id, text) tuple and
                            # the legacy plain-text payload (slot 0)
                            if isinstance(com.data, tuple) and len(com.data) == 2:
                                slot_id, script_text = com.data
                            else:
                                slot_id, script_text = 0, com.data

                            # stop the previous run on this slot only -
                            # other slots keep running
                            old_bridge = bot_bridges.pop(slot_id, None)
                            if old_bridge is not None:
                                try:
                                    old_bridge.stop()
                                except Exception:
                                    pass
                            old_task = bot_tasks.pop(slot_id, None)
                            if old_task is not None and not old_task.cancelled():
                                old_task.cancel()

                            new_bridge = _make_bridge(
                                asyncio.get_event_loop(),
                                walker,
                            )
                            new_bridge.on_error(
                                lambda msg, sid=slot_id: logger.error(
                                    f"[lua slot {sid}] {msg}"
                                )
                            )

                            # pre-flight lint. errors are logged but do not
                            # block execution - scripts in this engine have
                            # often been crafted iteratively and rejecting
                            # them outright would be surprising. the bot tab
                            # surfaces the same diagnostics in the log pane
                            try:
                                from src.lang.docgen import (
                                    lint_script,
                                    format_issues,
                                )

                                issues = lint_script(script_text)
                                if issues:
                                    logger.info(
                                        f"[lua slot {slot_id}] " + format_issues(issues)
                                    )
                            except Exception as exc:
                                logger.debug(
                                    f"[lua slot {slot_id}] lint skipped: {exc}"
                                )

                            new_bridge.run(script_text)

                            async def _watch_slot(b=new_bridge):
                                while b.running:
                                    await asyncio.sleep(0.5)

                            def _on_slot_done(sid=slot_id, my_task=None):
                                # my_task is the task this callback is for,
                                # bound below since it doesn't exist yet at
                                # def time. identity check so we don't clean up
                                # after a newer run that took over the slot
                                def _cb(_t):
                                    if bot_tasks.get(sid) is not my_task:
                                        # either KillBot already popped us
                                        # (and emitted Disabled itself), or
                                        # a quick Restart raced ahead. don't
                                        # touch dicts or status
                                        return
                                    bot_bridges.pop(sid, None)
                                    bot_tasks.pop(sid, None)
                                    # deliberately don't unlock_window_input()
                                    # on every client here - with concurrent
                                    # slots that could yank the mouse lock from
                                    # another live bot mid-click. wizwalker's
                                    # context managers release on cancellation
                                    gui_send_queue.put(
                                        sfgui.GUICommand(
                                            sfgui.GUICommandType.UpdateWindow,
                                            ("BotSlotStatus", (sid, "Disabled")),
                                        )
                                    )
                                    if not bot_tasks:
                                        gui_send_queue.put(
                                            sfgui.GUICommand(
                                                sfgui.GUICommandType.UpdateWindow,
                                                ("BotStatus", "Disabled"),
                                            )
                                        )

                                return _cb

                            new_task = asyncio.create_task(_watch_slot())
                            # register first so the callback's identity
                            # check can see itself in the dict
                            bot_bridges[slot_id] = new_bridge
                            bot_tasks[slot_id] = new_task
                            new_task.add_done_callback(
                                _on_slot_done(sid=slot_id, my_task=new_task)
                            )

                            # keep the slot-0 globals pointing at the most
                            # recent slot-0 bot so legacy code paths still
                            # see a valid handle
                            if slot_id == 0:
                                bridge = new_bridge
                                bot_task = new_task

                            gui_send_queue.put(
                                sfgui.GUICommand(
                                    sfgui.GUICommandType.UpdateWindow,
                                    ("BotSlotStatus", (slot_id, "Enabled")),
                                )
                            )
                            # aggregate "any bot running" - flips True only on
                            # the first slot starting from idle, so anything
                            # still watching the legacy tag doesn't toggle on
                            # every per-slot start
                            if len(bot_tasks) == 1:
                                gui_send_queue.put(
                                    sfgui.GUICommand(
                                        sfgui.GUICommandType.UpdateWindow,
                                        ("BotStatus", "Enabled"),
                                    )
                                )
                        case sfgui.GUICommandType.KillBot:
                            if not walker.clients:
                                continue
                            # com.data is a slot_id (new form) or None
                            # (legacy "kill the only bot" form → slot 0)
                            slot_id = com.data if com.data is not None else 0

                            had_entry = slot_id in bot_tasks
                            b = bot_bridges.pop(slot_id, None)
                            if b is not None:
                                try:
                                    b.stop()
                                except Exception:
                                    pass
                            t = bot_tasks.pop(slot_id, None)
                            if t is not None and not t.cancelled():
                                t.cancel()
                                logger.debug(f"bot killed (slot {slot_id})")

                            if slot_id == 0:
                                bridge = None
                                bot_task = None

                            # emit Disabled immediately so the GUI flips
                            # off without waiting for the watch task's
                            # done callback (which will short-circuit on
                            # the identity check since we just popped)
                            if had_entry:
                                gui_send_queue.put(
                                    sfgui.GUICommand(
                                        sfgui.GUICommandType.UpdateWindow,
                                        ("BotSlotStatus", (slot_id, "Disabled")),
                                    )
                                )
                                if not bot_tasks:
                                    gui_send_queue.put(
                                        sfgui.GUICommand(
                                            sfgui.GUICommandType.UpdateWindow,
                                            ("BotStatus", "Disabled"),
                                        )
                                    )

                            # if the bot was mid-combat, the asyncio cancel
                            # raises inside the bridge call but the bridge
                            # swallows it. force-exit any live NativeCombat
                            # the bot spawned so combat actually stops
                            for c in walker.clients:
                                active = getattr(c, "_active_combat", None)
                                if active is not None:
                                    try:
                                        active.cancel_combat()
                                    except Exception:
                                        pass
                        case sfgui.GUICommandType.SetPlaystyles:
                            if not walker.clients:
                                continue
                            combat_configs = delegate_combat_configs(
                                str(com.data), len(walker.clients)
                            )
                            for i, client in enumerate(walker.clients):
                                client.combat_config = combat_configs.get(
                                    i, default_config
                                )
                            await toggle_combat_hotkey(False)
                            await toggle_combat_hotkey(False)
                        case sfgui.GUICommandType.SetScale:
                            if not walker.clients:
                                continue
                            desired_scale = param_input(com.data, 1.0)
                            await asyncio.gather(
                                *[
                                    client.body.write_scale(desired_scale)
                                    for client in walker.clients
                                ]
                            )

                        case sfgui.GUICommandType.LoadAccounts:
                            gui_send_queue.put(
                                sfgui.GUICommand(
                                    sfgui.GUICommandType.UpdateAccountList,
                                    wizlaunch.list_accounts(),
                                )
                            )

                        case sfgui.GUICommandType.SaveAccount:
                            try:
                                if isinstance(com.data, tuple) and len(com.data) == 3:
                                    nickname, _user, _pwd = com.data
                                    await asyncio.to_thread(
                                        wizlaunch.save_account, nickname, _user, _pwd
                                    )
                                else:
                                    nickname = com.data
                                    await asyncio.to_thread(
                                        wizlaunch.prompt_save_account, nickname
                                    )
                                logger.info(f"account '{nickname}' saved.")
                            except RuntimeError as e:
                                logger.info(f"account save cancelled or failed: {e}")
                            gui_send_queue.put(
                                sfgui.GUICommand(
                                    sfgui.GUICommandType.UpdateAccountList,
                                    wizlaunch.list_accounts(),
                                )
                            )

                        case sfgui.GUICommandType.DeleteAccount:
                            wizlaunch.delete_account(com.data)
                            logger.info(f"account '{com.data}' removed.")
                            gui_send_queue.put(
                                sfgui.GUICommand(
                                    sfgui.GUICommandType.UpdateAccountList,
                                    wizlaunch.list_accounts(),
                                )
                            )

                        case sfgui.GUICommandType.LaunchInstance:
                            nicknames, game_path = com.data
                            if not game_path:
                                game_path = str(utils.get_wiz_install())
                            else:
                                utils.override_wiz_install_location(game_path)

                            already_managed = set(launched_account_map.values())
                            for c in walker.clients:
                                gid = getattr(c, "player_gid", None)
                                if gid:
                                    vault_nick = wizlaunch.get_nickname_by_gid(gid)
                                    if vault_nick:
                                        already_managed.add(vault_nick)
                            nicknames = [
                                n for n in nicknames if n not in already_managed
                            ]
                            if not nicknames:
                                logger.info(
                                    "all selected accounts are already launched and hooked."
                                )
                            else:
                                logger.info(
                                    f"launching {len(nicknames)} instance(s)..."
                                )

                            released_handles.clear()
                            gui_send_queue.put(
                                sfgui.GUICommand(
                                    sfgui.GUICommandType.ClearLaunchCheckboxes
                                )
                            )
                            try:
                                results = await asyncio.to_thread(
                                    wizlaunch.launch_instances, nicknames, game_path
                                )
                                for nickname, handle in results.items():
                                    launched_account_map[handle] = nickname
                                    logger.info(f"launched and logged in '{nickname}'.")
                            except Exception as e:
                                logger.error(f"error launching instances: {e}")

                        case sfgui.GUICommandType.ReorderAccounts:
                            wizlaunch.reorder_accounts(com.data)

                        case sfgui.GUICommandType.ReorderClients:
                            handles = com.data
                            client_map = {c.window_handle: c for c in walker.clients}
                            new_order = [
                                client_map[h] for h in handles if h in client_map
                            ]
                            remaining = [
                                c
                                for c in walker.clients
                                if c.window_handle not in set(handles)
                            ]
                            walker.clients[:] = new_order + remaining
                            for i, c in enumerate(walker.clients):
                                c.title = f"p{i + 1}"
                            _send_hooked_clients_update()
                            _resync_toggle_status()

                        case sfgui.GUICommandType.UnhookClient:
                            handle = com.data
                            for c in walker.clients[:]:
                                if c.window_handle == handle:
                                    try:
                                        c.title = "Wizard101"
                                        await c.close()
                                    except Exception:
                                        pass
                                    if c.window_handle in walker._managed_handles:
                                        walker._managed_handles.remove(c.window_handle)
                                    walker.clients.remove(c)
                                    released_handles.add(handle)
                                    logger.info(f"unhooked client (handle {handle}).")
                                    break
                            _send_hooked_clients_update()
                            if walker.clients:
                                _restart_always_on_tasks()
                                _restart_active_toggle_tasks()
                            # promote remaining clients (p2→p1, …); after the
                            # task restart so the status resync is final
                            _renumber_clients()
                            _resync_toggle_status()

                        case sfgui.GUICommandType.HookClient:
                            handle = com.data

                            released_handles.discard(handle)

                            if handle in walker._managed_handles:
                                logger.debug(
                                    f"handle {handle} already managed, skipping."
                                )
                                _send_hooked_clients_update()
                                continue
                            all_handles = get_all_wizard_handles()
                            if handle not in all_handles:
                                logger.error(f"handle {handle} no longer exists.")
                                _send_hooked_clients_update()
                                continue

                            walker._managed_handles.append(handle)
                            nc = walker.client_cls(handle)
                            walker.clients.append(nc)
                            existing_nums = set()
                            for c in walker.clients:
                                if c.title.startswith("p") and c.title[1:].isdigit():
                                    existing_nums.add(int(c.title[1:]))
                            num = 1
                            while num in existing_nums:
                                num += 1
                            nc.title = f"p{num}"
                            _hooking_in_progress.add(handle)
                            _send_hooked_clients_update()
                            try:
                                await nc.activate_hooks()
                                await _init_client_attrs(nc)
                                logger.info(
                                    f"manually hooked client '{nc.title}' (handle {handle})."
                                )
                            except wizwalker.errors.HookAlreadyActivated:
                                await _init_client_attrs(nc)
                                logger.info(
                                    f"manually hooked client '{nc.title}' (handle {handle}, already hooked)."
                                )
                            except Exception as e:
                                logger.error(
                                    f"failed to hook client (handle {handle}): {e}"
                                )
                                walker._managed_handles.remove(handle)
                                walker.clients.remove(nc)
                                _hooking_in_progress.discard(handle)
                                _send_hooked_clients_update()
                                continue
                            _hooking_in_progress.discard(handle)
                            _send_hooked_clients_update()
                            _restart_always_on_tasks()
                            _restart_active_toggle_tasks()
                            _renumber_clients()
                            _resync_toggle_status()

                        case sfgui.GUICommandType.KillClient:
                            handle = com.data

                            for c in walker.clients[:]:
                                if c.window_handle == handle:
                                    try:
                                        c.title = "Wizard101"
                                        await c.close()
                                    except Exception:
                                        pass
                                    if c.window_handle in walker._managed_handles:
                                        walker._managed_handles.remove(c.window_handle)
                                    walker.clients.remove(c)
                                    launched_account_map.pop(handle, None)
                                    break

                            _kill_process_by_handle(handle)
                            released_handles.discard(handle)
                            logger.info(f"killed client (handle {handle}).")
                            _send_hooked_clients_update()
                            if walker.clients:
                                _restart_always_on_tasks()
                                _restart_active_toggle_tasks()
                            _renumber_clients()
                            _resync_toggle_status()

                        case sfgui.GUICommandType.RelaunchClient:
                            handle, nickname = com.data

                            for c in walker.clients[:]:
                                if c.window_handle == handle:
                                    try:
                                        c.title = "Wizard101"
                                        await c.close()
                                    except Exception:
                                        pass
                                    if c.window_handle in walker._managed_handles:
                                        walker._managed_handles.remove(c.window_handle)
                                    walker.clients.remove(c)
                                    launched_account_map.pop(handle, None)
                                    break

                            _kill_process_by_handle(handle)
                            released_handles.discard(handle)
                            logger.info(
                                f"killed client for relaunch (handle {handle}, account '{nickname}')."
                            )
                            _send_hooked_clients_update()

                            try:
                                game_path = str(utils.get_wiz_install())
                                await asyncio.sleep(1)
                                new_handle = await asyncio.to_thread(
                                    wizlaunch.launch_instance, nickname, game_path
                                )
                                launched_account_map[new_handle] = nickname
                                logger.info(f"relaunched and logged in '{nickname}'.")
                                _send_hooked_clients_update()
                            except Exception as e:
                                logger.error(f"error relaunching '{nickname}': {e}")
                            if walker.clients:
                                _restart_always_on_tasks()
                                _restart_active_toggle_tasks()

                        case sfgui.GUICommandType.UpdateSettings:
                            global \
                                speed_multiplier, \
                                use_potions, \
                                rpc_status, \
                                drop_status, \
                                anti_afk_status
                            global \
                                buy_potions, \
                                use_team_up, \
                                team_up_type, \
                                team_up_size, \
                                client_to_follow, \
                                client_to_boost
                            global \
                                questing_friend_tp, \
                                gear_switching_in_solo_zones, \
                                hitter_client
                            global ignore_pet_level_up, only_play_dance_game
                            global quest_excluded_clients
                            # questing_task is already declared global higher
                            # up in this handler - re-declaring it here after
                            # the earlier read at the active_tasks dict would
                            # be a SyntaxError ("used prior to global decl")
                            global \
                                kill_minions_first, \
                                automatic_team_based_combat, \
                                discard_duplicate_cards
                            settings_dict = com.data
                            # per-client speed multiplier: the spinbox tags its
                            # value with the selected target. no target (or
                            # "all") updates the global default and every client
                            _speed_target = (
                                settings_dict.pop("_speed_target", None)
                                if isinstance(settings_dict, dict)
                                else None
                            )
                            for key, value in settings_dict.items():
                                match key:
                                    case "speed_multiplier":
                                        if _speed_target in (None, "All", "all"):
                                            speed_multiplier = value
                                            for _c in walker.clients:
                                                client_speed_targets[_c.process_id] = (
                                                    value
                                                )
                                        else:
                                            for _c in walker.clients:
                                                if _c.title == _speed_target:
                                                    client_speed_targets[
                                                        _c.process_id
                                                    ] = value
                                    case "use_potions":
                                        use_potions = value
                                    case "rich_presence":
                                        rpc_status = value
                                    case "drop_logging":
                                        drop_status = value
                                    case "use_anti_afk":
                                        anti_afk_status = value
                                    case "buy_potions":
                                        buy_potions = value
                                    case "use_team_up":
                                        use_team_up = value
                                        for _c in walker.clients:
                                            _c.use_team_up = value
                                    case "team_up_type":
                                        team_up_type = value
                                        for _c in walker.clients:
                                            _c.team_up_type = value
                                    case "team_up_size":
                                        team_up_size = value
                                        for _c in walker.clients:
                                            _c.team_up_size = value
                                    case "client_to_follow":
                                        client_to_follow = value
                                        global sigil_leader_pid
                                        sigil_leader_pid = None
                                        if value:
                                            for _c in walker.clients:
                                                _c.client_to_follow = value
                                                if value in _c.title:
                                                    sigil_leader_pid = _c.process_id
                                        else:
                                            for _c in walker.clients:
                                                _c.client_to_follow = None
                                    case "client_to_boost":
                                        client_to_boost = value
                                    case "quest_excluded_clients":
                                        # live-apply: rewrite the per-client
                                        # quest_excluded flag without requiring
                                        # a restart. the questing_loop reads
                                        # client.quest_excluded each tick.
                                        quest_excluded_clients = list(value or [])
                                        for _c in walker.clients:
                                            _c.quest_excluded = (
                                                _c.title in quest_excluded_clients
                                            )
                                        # the exclusion filter only re-checks at
                                        # the top of async_questing's loop, but
                                        # auto_quest never returns once in-loop.
                                        # cancel + respawn so it applies now
                                        if (
                                            questing_status
                                            and questing_task is not None
                                        ):
                                            try:
                                                questing_task.cancel()
                                            except Exception:
                                                pass
                                            questing_task = asyncio.create_task(
                                                try_task_coro(
                                                    questing_loop,
                                                    walker.clients,
                                                    True,
                                                )
                                            )
                                    case "friend_teleport":
                                        questing_friend_tp = value
                                    case "gear_switching_in_solo_zones":
                                        gear_switching_in_solo_zones = value
                                    case "hitter_client":
                                        hitter_client = value
                                    case "ignore_pet_level_up":
                                        ignore_pet_level_up = value
                                    case "only_play_dance_game":
                                        only_play_dance_game = value
                                    case "kill_minions_first":
                                        kill_minions_first = value
                                    case "automatic_team_based_combat":
                                        automatic_team_based_combat = value
                                    case "discard_duplicate_cards":
                                        discard_duplicate_cards = value
                                    case "verbose_combat_logs":
                                        combat_handler._VERBOSE_LOG = bool(value)
                            logger.debug(
                                f"settings updated: {list(settings_dict.keys())}"
                            )

            except queue.Empty:
                pass

            await asyncio.sleep(0.1)

    async def potion_usage_loop():

        async def async_potion(client: Client):
            if use_potions:
                while True:
                    await asyncio.sleep(1)
                    try:
                        if (
                            client.auto_potion_status
                            and await is_free(client)
                            and not any(
                                [
                                    freecam_status,
                                    client.sigil_status,
                                    client.questing_status,
                                ]
                            )
                        ):
                            await auto_potions(client, buy=False)
                    except Exception:
                        if not client.is_running():
                            return

        await asyncio.gather(*[async_potion(p) for p in walker.clients])

    async def rpc_loop():
        if not rpc_status:
            return

        async def _close_rpc(rpc):
            try:
                if hasattr(rpc, "sock_writer") and rpc.sock_writer:
                    rpc.sock_writer.close()
                    await rpc.sock_writer.wait_closed()
            except Exception:
                pass
            try:
                await rpc.close()
            except Exception:
                pass

        rpc = None
        client: Client = None
        while True:
            if rpc is None:
                try:
                    rpc = AioPresence(1000159655357587566)
                    await rpc.connect()
                except Exception as e:
                    logger.debug(f"discord rpc connection failed: {e}")
                    await _close_rpc(rpc)
                    rpc = None
                    await asyncio.sleep(15)
                    continue

            await asyncio.sleep(1)

            if not walker.clients:
                if rpc is not None:
                    try:
                        await rpc.clear()
                    except Exception:
                        pass
                    await _close_rpc(rpc)
                    rpc = None
                client = None
                continue

            client = walker.clients[0]
            for c in walker.clients:
                if c.is_foreground:
                    client = c
                    break

            if client not in walker.clients:
                client = walker.clients[0]

            try:
                zone_name = await client.zone_name()
            except Exception:
                client = None
                continue

            if zone_name:
                zone_list = zone_name.split("/")
                if len(zone_list):
                    status_str = zone_list[0]
                else:
                    status_str = zone_name

                if len(zone_list) > 1:
                    if "Housing_" in zone_name:
                        status_str = status_str.replace("Housing_", "")
                        end_zone_list = zone_list[-1].split("_")
                        end_zone = f" - {end_zone_list[-1]}"

                    elif "Housing" in zone_name:
                        end_zone_list = zone_list[-1].split("_")

                        if "School" in zone_list:
                            status_str = end_zone_list[0] + "House"

                        else:
                            status_str = zone_list[1]

                        end_zone = f" - {end_zone_list[-1]}"

                    else:
                        end_zone = None

                    if not end_zone:
                        area_list: list[str] = zone_list[-1].split("_")
                        del area_list[0]

                        for a in area_list.copy():
                            if any([s.isdigit() for s in a]):
                                area_list.remove(a)

                        seperator = " "
                        area = seperator.join(area_list)
                        zone_word_list = re.findall("[A-Z][^A-Z]*", area)
                        if zone_word_list:
                            end_zone = f" - {seperator.join(zone_word_list)}"

                        else:
                            end_zone = ""

            else:
                end_zone = ""

            status_str = status_str.replace("DragonSpire", "Dragonspyre")
            status_list = status_str.split("_")
            if len(status_list[0]) <= 3:
                del status_list[0]

            seperator = " "
            status_str = seperator.join(status_list)

            status_list = re.findall("[A-Z][^A-Z]*", status_str)
            status_str = seperator.join(status_list)

            if "ext" in end_zone.lower():
                end_zone = " - Outside"

            elif "int" in end_zone.lower():
                end_zone = " - Inside"

            try:
                in_battle = await client.in_battle()
            except Exception:
                client = None
                continue

            if in_battle:
                task_str = "Fighting "

            elif questing_status:
                task_str = "Questing "

            elif sigil_status:
                task_str = "Farming "

            else:
                task_str = ""

            if not any([c.is_foreground for c in walker.clients]):
                details_pane = "Idle"

            else:
                details_pane = "Active"

            try:
                await rpc.update(
                    state=f"{task_str}In {status_str}{end_zone}", details=details_pane
                )

            except Exception:
                await _close_rpc(rpc)
                rpc = None

    async def drop_logging_loop():

        async def _safe_logging(client):
            try:
                await logging_loop(client)
            except Exception:
                if not client.is_running():
                    return

        await asyncio.gather(*[_safe_logging(p) for p in walker.clients])

    async def zone_check_loop():
        zone_blacklist = ["Raids", "Battlegrounds"]

        explicit_zone_blacklist = [
            "WizardCity/WC_Duel_Arena_New",
            "WizardCity/KT_Duel_Arena",
            "WizardCity/MB_Arena",
            "WizardCity/MS_Arena",
            "WizardCity/DS_Arena",
            "WizardCity/CL_Arena",
            "WizardCity/ZF_Arena",
            "WizardCity/AV_Arena",
            "WizardCity/AZ_Arena",
            "WizardCity/PA_Arena",
            "WizardCity/GH_Arena",
            "WizardCity/LM_Arena",
        ]

        async def async_zone_check(client: Client):
            while True:
                await asyncio.sleep(0.25)
                try:
                    zone_name = await client.zone_name()
                except Exception:
                    if not client.is_running():
                        return
                    continue
                if zone_name in explicit_zone_blacklist:
                    logger.critical(
                        f"client {client.title} entered area with known anticheat, killing {tool_name}."
                    )
                    await kill_tool(False)
                if zone_name and "/" in zone_name:
                    split_zone_name = zone_name.split("/")

                    if any([i in split_zone_name[0] for i in zone_blacklist]):
                        logger.critical(
                            f"client {client.title} entered area with known anticheat, killing {tool_name}."
                        )
                        await kill_tool(False)

        await asyncio.gather(*[async_zone_check(p) for p in walker.clients])

    async def mouse_release_loop():
        from wizwalker.memory.hooks import MouselessCursorMoveHook

        async def watch(client: Client):
            while True:
                await asyncio.sleep(1.0)
                try:
                    mh = client.mouse_handler
                    if mh._ref_count <= 0 and client.hook_handler._check_if_hook_active(
                        MouselessCursorMoveHook
                    ):
                        logger.debug(
                            f"mouse_release_loop: orphaned hook on "
                            f"{client.title}, releasing"
                        )
                        await mh.release_mouse()
                except Exception:
                    pass

        await asyncio.gather(*[watch(p) for p in walker.clients])

    await asyncio.sleep(0)
    global walker
    walker = ClientHandler()

    global gui_task
    gui_task = asyncio.create_task(handle_gui())
    await asyncio.sleep(2)

    async def hooking_logic():
        await asyncio.sleep(0.1)
        if not get_all_wizard_handles():
            logger.info("waiting for a wizard101 client to be opened...")
            while not get_all_wizard_handles():
                await asyncio.sleep(1)
        override_wiz_install_using_handle()
        logger.info("wizard101 client(s) detected. hook clients from the launcher tab.")

    async def _race_gui(coro):
        inner = asyncio.ensure_future(coro)
        done, _pending = await asyncio.wait(
            {inner, gui_task}, return_when=asyncio.FIRST_COMPLETED
        )
        if gui_task in done and not inner.done():
            inner.cancel()
            try:
                await inner
            except (asyncio.CancelledError, Exception):
                pass
            exc = gui_task.exception()
            if exc is not None:
                raise exc
        return await inner

    try:
        await _race_gui(hooking_logic())
    except sfgui.ToolClosedException:
        pass

    if gui_task.done():
        await tool_finish()
        if _reboot_requested:
            _relaunch_skyfall()
        try:
            gui_send_queue.put(sfgui.GUICommand(sfgui.GUICommandType.Close))
        except Exception:
            pass
        return
    logger.info("waiting for you to hook a client...")
    global client_speeds
    global client_speed_targets
    client_speeds = {}
    client_speed_targets = {}
    _send_hooked_clients_update()
    initial_setup_complete = True

    _kill_binding = settings.get_hotkeys().get("kill_tool")
    if _kill_binding:
        _kill_mods = ModifierKeys.NOREPEAT
        for _m in _kill_binding.get("modifiers", []):
            _kill_mods |= ModifierKeys[_m]
        try:
            await listener.remove_hotkey(
                Keycode[_kill_binding["key"]], modifiers=_kill_mods
            )
        except Exception:
            pass
        try:
            await listener.add_hotkey(
                Keycode[_kill_binding["key"]], kill_tool_hotkey, modifiers=_kill_mods
            )
            _active_bindings["kill_tool"] = _kill_binding
        except Exception as e:
            logger.debug(f"failed to register kill_tool hotkey: {e}")
    await enable_hotkeys()

    tool_status = True
    exc = None

    async def tool_active():
        while tool_status:
            await asyncio.sleep(0.1)

    all_tasks = {}

    SNAPSHOT_TASK_NAMES = [
        "anti_afk_loop",
        "is_client_in_combat_loop",
        "entity_detect_combat_loop",
        "potion_usage_loop",
        "drop_logging_loop",
        "zone_check_loop",
        "anti_afk_questing_loop",
        "mouse_release_loop",
    ]
    SNAPSHOT_TASK_FUNCS = {
        "anti_afk_loop": anti_afk_loop,
        "is_client_in_combat_loop": is_client_in_combat_loop,
        "entity_detect_combat_loop": entity_detect_combat_loop,
        "potion_usage_loop": potion_usage_loop,
        "drop_logging_loop": drop_logging_loop,
        "zone_check_loop": zone_check_loop,
        "anti_afk_questing_loop": anti_afk_questing_loop,
        "mouse_release_loop": mouse_release_loop,
    }

    def _restart_always_on_tasks():
        for name in SNAPSHOT_TASK_NAMES:
            old = all_tasks.get(name)
            if old is not None and not old.cancelled():
                old.cancel()
            all_tasks[name] = asyncio.create_task(SNAPSHOT_TASK_FUNCS[name]())

    def _restart_active_toggle_tasks():
        global \
            combat_task, \
            dialogue_task, \
            sigil_task, \
            questing_task, \
            speed_task, \
            auto_pet_task

        if combat_task is not None and not combat_task.cancelled():
            combat_task.cancel()
            for c in walker.clients:
                c.combat_status = True
            combat_task = asyncio.create_task(
                try_task_coro(combat_loop, walker.clients, True)
            )

        if dialogue_task is not None and not dialogue_task.cancelled():
            dialogue_task.cancel()
            for c in walker.clients:
                c.dialogue_status = True
            dialogue_task = asyncio.create_task(
                try_task_coro(dialogue_loop, walker.clients, True)
            )

        if sigil_task is not None and not sigil_task.cancelled():
            sigil_task.cancel()
            for c in walker.clients:
                c.sigil_status = True
            sigil_task = asyncio.create_task(
                try_task_coro(sigil_loop, walker.clients, True)
            )

        if questing_task is not None and not questing_task.cancelled():
            questing_task.cancel()
            for c in walker.clients:
                c.questing_status = True
            questing_task = asyncio.create_task(
                try_task_coro(questing_loop, walker.clients, True)
            )

        if speed_task is not None and not speed_task.cancelled():
            speed_task.cancel()
            for c in walker.clients:
                c.speed_status = True
            speed_task = asyncio.create_task(
                try_task_coro(speed_switching, walker.clients)
            )

        if auto_pet_task is not None and not auto_pet_task.cancelled():
            auto_pet_task.cancel()
            for c in walker.clients:
                c.auto_pet_status = True
                c.feeding_pet_status = True
            auto_pet_task = asyncio.create_task(
                try_task_coro(auto_pet_loop, walker.clients, True)
            )

    _rehook_file = ".skyfall_rehook"
    if os.path.exists(_rehook_file):
        try:
            with open(_rehook_file) as _f:
                _rehook_handles = [
                    int(h.strip()) for h in _f.read().splitlines() if h.strip()
                ]
            os.remove(_rehook_file)
            _existing_nums: set[int] = set()
            for c in walker.clients:
                if c.title.startswith("p") and c.title[1:].isdigit():
                    _existing_nums.add(int(c.title[1:]))
            for _h in _rehook_handles:
                _nc = None
                try:
                    _nc = walker.client_cls(_h)
                    walker._managed_handles.append(_h)
                    walker.clients.append(_nc)
                    _num = 1
                    while _num in _existing_nums:
                        _num += 1
                    _nc.title = f"p{_num}"
                    _existing_nums.add(_num)
                    _hooking_in_progress.add(_h)
                    _send_hooked_clients_update()
                    await _nc.activate_hooks()
                    await _init_client_attrs(_nc)
                    logger.info(f"re-hooked client '{_nc.title}' after reboot.")
                except Exception as _e:
                    logger.error(f"failed to re-hook handle {_h} after reboot: {_e}")
                    if _nc is not None:
                        try:
                            walker.clients.remove(_nc)
                        except ValueError:
                            pass
                        try:
                            walker._managed_handles.remove(_h)
                        except ValueError:
                            pass
                finally:
                    _hooking_in_progress.discard(_h)
            if walker.clients:
                _send_hooked_clients_update()
        except Exception as _e:
            logger.error(f"reboot rehook failed: {_e}")

    try:
        all_tasks["foreground_client_switching"] = asyncio.create_task(
            foreground_client_switching()
        )
        all_tasks["assign_foreground_clients"] = asyncio.create_task(
            assign_foreground_clients()
        )
        all_tasks["anti_afk_loop"] = asyncio.create_task(anti_afk_loop())
        all_tasks["is_client_in_combat_loop"] = asyncio.create_task(
            is_client_in_combat_loop()
        )
        all_tasks["entity_detect_combat_loop"] = asyncio.create_task(
            entity_detect_combat_loop()
        )
        all_tasks["potion_usage_loop"] = asyncio.create_task(potion_usage_loop())
        all_tasks["rpc_loop"] = asyncio.create_task(rpc_loop())
        all_tasks["drop_logging_loop"] = asyncio.create_task(drop_logging_loop())
        all_tasks["zone_check_loop"] = asyncio.create_task(zone_check_loop())
        all_tasks["anti_afk_questing_loop"] = asyncio.create_task(
            anti_afk_questing_loop()
        )
        all_tasks["tool_active"] = asyncio.create_task(tool_active())
        all_tasks["gui"] = gui_task

        while True:
            pending = [t for t in all_tasks.values() if t is not None and not t.done()]
            if not pending:
                break
            done, _ = await asyncio.wait(pending, return_when=asyncio.FIRST_EXCEPTION)

            should_exit = False
            for t in done:
                exc = t.exception()
                if exc is None:
                    continue
                elif isinstance(exc, sfgui.ToolClosedException):
                    logger.info("tool close triggered by user.")
                    should_exit = True
                elif t == all_tasks.get("gui"):
                    logger.opt(exception=exc).error("GUI task crashed")
                    should_exit = True
                else:
                    task_name = next((k for k, v in all_tasks.items() if v is t), "?")
                    logger.opt(exception=exc).warning(f"Task '{task_name}' ended")
            if should_exit:
                break

    finally:
        for task in all_tasks.values():
            if task is not None and not task.cancelled():
                task.cancel()

        for task in [
            combat_task,
            dialogue_task,
            sigil_task,
            questing_task,
            speed_task,
            auto_pet_task,
            bot_task,
        ]:
            if task is not None and not task.cancelled():
                task.cancel()

        await tool_finish()

        if _reboot_requested:
            _relaunch_skyfall()

        try:
            gui_send_queue.put(sfgui.GUICommand(sfgui.GUICommandType.Close))
        except Exception:
            pass


def bool_to_string(input: bool):
    if input:
        return "Enabled"

    else:
        return "Disabled"


if __name__ == "__main__":
    import src.lang.client as _lang_client

    def _make_sink_filter(level_check):
        def _f(record):
            return not _lang_client._log_paused and level_check(record)

        return _f

    logger.remove()
    for _fmt, _flt in [
        ("<dim>{message}</dim>", lambda r: r["level"].no < 30),
        ("<yellow>{message}</yellow>", lambda r: r["level"].no == 30),
        ("<red>{message}</red>", lambda r: r["level"].no >= 40),
    ]:
        logger.add(
            sys.stderr,
            format=f"[skyfall://] {_fmt}",
            level="INFO",
            filter=_make_sink_filter(_flt),
            colorize=True,
        )

    os.system("cls" if os.name == "nt" else "clear")

    if os.name == "nt":
        os.system("title skyfall")
    else:
        sys.stdout.write("\x1b]2;skyfall\x07")

    print(r"""

                               ,...         ,,    ,,
       `7MM                  .d' ""       `7MM  `7MM
         MM                  dM`            MM    MM
,pP"Ybd  MM  ,MP'`7M'   `MF'mMMmm ,6"Yb.    MM    MM
8I   `"  MM ;Y     VA   ,V   MM  8)   MM    MM    MM
`YMMMa.  MM;Mm      VA ,V    MM   ,pm9MM    MM    MM
L.   I8  MM `Mb.     VVV     MM  8M   MM    MM    MM
M9mmmP'.JMML. YA.    ,V    .JMML.`Moo9^Yo..JMML..JMML.
                    ,V
                 OOb"
""")

    current_log = logger.add(
        f"logs/{tool_name} - {generate_timestamp()}.log",
        encoding="utf-8",
        enqueue=True,
        backtrace=True,
    )

    gui_send_queue = queue.Queue()
    recv_queue = queue.Queue()

    backend_thread = threading.Thread(target=lambda: asyncio.run(main()), daemon=True)
    backend_thread.start()

    sfgui.manage_gui(
        recv_queue,
        gui_send_queue,
        theme_dict,
        tool_name,
        tool_version,
        gui_on_top,
        gui_langcode,
        gui_font,
        gui_font_size,
        tool_author,
        settings=settings,
    )

    logger.remove(current_log)
