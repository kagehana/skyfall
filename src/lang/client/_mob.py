from __future__ import annotations
from typing import Callable
from wizwalker import Client
from src.teleport import navmap_tp

from src.lang.client._main import _teleport_with_retry, _teleport_near  # noqa: E402


class LuaMob:
    def __init__(
        self,
        entity,
        distance: float,
        call: Callable,
        client: Client,
        table_from: Callable,
    ):

        self._e = entity

        self._dist = distance

        self._call = call

        self._client = client

        self._table = table_from

    # ── identity ──────────────────────────────────────────────────────────────

    def name(self) -> str:

        return self._call(self._e.object_name())

    def display_name(self) -> str:

        return self._call(self._e.display_name())

    def global_id(self) -> int:

        return self._call(self._e.global_id_full())

    def perm_id(self) -> int:

        return self._call(self._e.perm_id())

    def mobile_id(self) -> int:

        return self._call(self._e.mobile_id())

    def template_id(self) -> int:

        return self._call(self._e.template_id_full())

    def debug_name(self) -> str:

        return self._call(self._e.debug_name())

    def zone_tag_id(self) -> int:

        return self._call(self._e.zone_tag_id())

    # ── position / movement ───────────────────────────────────────────────────

    def distance(self) -> float:

        return self._dist

    def x(self) -> float:

        async def _():
            return (await self._e.location()).x

        return self._call(_())

    def y(self) -> float:

        async def _():
            return (await self._e.location()).y

        return self._call(_())

    def z(self) -> float:

        async def _():
            return (await self._e.location()).z

        return self._call(_())

    def location(self):

        async def _():
            loc = await self._e.location()
            return [loc.x, loc.y, loc.z]

        return self._table(self._call(_()))

    def yaw(self) -> float:

        async def _():
            try:
                body = await self._e.actor_body()
                if body:
                    return await body.yaw()
            except Exception:
                pass
            orient = await self._e.orientation()
            return orient.yaw if orient else 0.0

        return self._call(_())

    def pitch(self) -> float:

        async def _():
            try:
                body = await self._e.actor_body()
                if body:
                    return await body.pitch()
            except Exception:
                pass
            orient = await self._e.orientation()
            return orient.pitch if orient else 0.0

        return self._call(_())

    def roll(self) -> float:

        async def _():
            try:
                body = await self._e.actor_body()
                if body:
                    return await body.roll()
            except Exception:
                pass
            orient = await self._e.orientation()
            return orient.roll if orient else 0.0

        return self._call(_())

    def height(self) -> float:

        async def _():
            try:
                body = await self._e.actor_body()
                if body:
                    return await body.height()
            except Exception:
                pass
            return 0.0

        return self._call(_())

    def scale(self) -> float:

        return self._call(self._e.scale())

    def speed(self) -> int:

        return self._call(self._e.speed_multiplier())

    def to(self):

        async def _():
            loc = await self._e.location()
            await _teleport_with_retry(self._client, loc)

        self._call(_())

    def navigate_to(self):

        async def _():
            loc = await self._e.location()
            await navmap_tp(self._client, loc)

        self._call(_())

    def near_to(self, dist: float = 180.0, scan_radius: float = 1500.0):

        async def _():
            target = await self._e.location()
            await _teleport_near(self._client, target, dist, scan_radius)

        self._call(_())

    # ── NPC template data ─────────────────────────────────────────────────────

    async def _npc(self):
        try:
            return await self._e.fetch_npc_behavior_template()
        except Exception:
            return None

    def is_boss(self) -> bool:

        async def _():
            npc = await self._npc()
            if not npc:
                return False
            # templates can mark a boss via the boss_mob flag, the mob_title
            # enum (=3), or both. OR them so we catch either convention.
            if await npc.boss_mob():
                return True
            try:
                title = await npc.mob_title()
                return title is not None and getattr(title, "value", None) == 3
            except Exception:
                return False

        return self._call(_())

    def level(self) -> int:

        async def _():
            npc = await self._npc()
            return (await npc.level()) if npc else 0

        return self._call(_())

    def starting_health(self) -> int:

        async def _():
            npc = await self._npc()
            return (await npc.starting_health()) if npc else 0

        return self._call(_())

    def school(self) -> str:

        async def _():
            npc = await self._npc()
            if npc:
                try:
                    return await npc.school_of_focus()
                except Exception:
                    pass
            return "Unknown"

        return self._call(_())

    def title(self) -> str:

        async def _():
            npc = await self._npc()
            if npc:
                try:
                    t = await npc.mob_title()
                    return str(t).split(".")[-1].lower() if t is not None else "normal"
                except Exception:
                    pass
            return "normal"

        return self._call(_())

    def secondary_school(self) -> str:

        async def _():
            npc = await self._npc()
            if npc:
                try:
                    return await npc.secondary_school_of_focus()
                except Exception:
                    pass
            return "Unknown"

        return self._call(_())

    def intelligence(self) -> float:

        async def _():
            npc = await self._npc()
            return (await npc.intelligence()) if npc else 0.0

        return self._call(_())

    def aggressive_factor(self) -> int:

        async def _():
            npc = await self._npc()
            return (await npc.aggressive_factor()) if npc else 0

        return self._call(_())

    def turn_towards_player(self) -> bool:

        async def _():
            npc = await self._npc()
            return bool(npc and await npc.turn_towards_player())

        return self._call(_())

    def hide_hp(self) -> bool:

        async def _():
            npc = await self._npc()
            return bool(npc and await npc.hide_current_hp())

        return self._call(_())

    def max_shadow_pips(self) -> int:

        async def _():
            npc = await self._npc()
            return (await npc.max_shadow_pips()) if npc else 0

        return self._call(_())

    def collision_radius(self) -> float:

        async def _():
            npc = await self._npc()
            return (await npc.cylinder_scale_value()) if npc else 0.0

        return self._call(_())

    # ── misc ──────────────────────────────────────────────────────────────────

    def behavior_names(self):

        async def _():
            try:
                return await self._e.list_behavior_names()
            except Exception:
                return []

        return self._table(self._call(_()))
