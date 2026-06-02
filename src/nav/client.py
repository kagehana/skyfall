from __future__ import annotations


from typing import Callable, Optional, Set


from wizwalker import Client, MemoryReadError

from wizwalker.constants import Primitive

from wizwalker.memory import DynamicClientObject


async def is_mob(entity) -> bool:

    try:
        b = await entity.search_behavior_by_name("NPCBehavior")

        if b is None:
            return False

        return bool(await b.read_value_from_offset(288, Primitive.bool))

    except (ValueError, MemoryReadError):
        return False


class EntityClient:
    def __init__(self, client: Client):

        self.client = client

    async def entities(
        self, excluded: Set[int] | None = None
    ) -> list[DynamicClientObject]:

        base = await self.client.get_base_entity_list()

        if not excluded:
            return base

        out = []

        for e in base:
            if await e.global_id_full() not in excluded:
                out.append(e)

        return out

    async def entities_named(self, name: str, excluded: Set[int] | None = None):

        base = await self.client.get_base_entities_with_name(name)

        return await self._filter_excluded(base, excluded)

    async def entities_vague(self, name: str, excluded: Set[int] | None = None):

        needle = name.lower()

        async def pred(e):

            if t := await e.object_template():
                return needle in (await t.object_name()).lower()

            return False

        return await self.entities_pred(pred, excluded)

    async def entities_pred(self, pred: Callable, excluded: Set[int] | None = None):

        out = []

        for e in await self.entities(excluded):
            try:
                if await pred(e):
                    out.append(e)

            except (ValueError, MemoryReadError):
                continue

        return out

    async def entities_with_behaviors(
        self, behavior_names: list[str], excluded: Set[int] | None = None
    ):

        out = []

        for e in await self.entities(excluded):
            try:
                active = [
                    await b.read_type_name() for b in await e.inactive_behaviors()
                ]

                if all(b in active for b in behavior_names):
                    out.append(e)

            except (ValueError, MemoryReadError):
                continue

        return out

    async def mobs(self, excluded: Set[int] | None = None):

        return await self.entities_pred(is_mob, excluded)

    async def health_wisps(self, excluded: Set[int] | None = None):

        return await self.entities_vague("WispHealth", excluded)

    async def mana_wisps(self, excluded: Set[int] | None = None):

        return await self.entities_vague("WispMana", excluded)

    async def gold_wisps(self, excluded: Set[int] | None = None):

        return await self.entities_vague("WispGold", excluded)

    async def closest(
        self, entities: list, only_safe: bool = False, safe_dist: float = 2000
    ) -> Optional[DynamicClientObject]:

        if only_safe:
            entities = await self.safe_entities(entities, safe_dist)

        if not entities:
            return None

        self_pos = await self.client.body.position()

        best, best_dist = None, float("inf")

        for e in entities:
            try:
                d = self_pos.distance(await e.location())

                if d < best_dist:
                    best_dist, best = d, e

            except Exception:
                continue

        return best

    async def closest_mob(self, excluded: Set[int] | None = None):

        return await self.closest(await self.mobs(excluded))

    async def closest_health_wisp(
        self, only_safe: bool = False, excluded: Set[int] | None = None
    ):

        return await self.closest(await self.health_wisps(excluded), only_safe)

    async def closest_mana_wisp(
        self, only_safe: bool = False, excluded: Set[int] | None = None
    ):

        return await self.closest(await self.mana_wisps(excluded), only_safe)

    async def closest_named(
        self, name: str, only_safe: bool = False, excluded: Set[int] | None = None
    ):

        return await self.closest(await self.entities_named(name, excluded), only_safe)

    async def closest_vague(
        self, name: str, only_safe: bool = False, excluded: Set[int] | None = None
    ):

        return await self.closest(await self.entities_vague(name, excluded), only_safe)

    async def tp_to(self, entity: DynamicClientObject) -> bool:

        if entity is None:
            return False

        try:
            await self.client.teleport(await entity.location())

            return True

        except (ValueError, MemoryReadError):
            return False

    async def tp_to_closest_mob(self, excluded: Set[int] | None = None) -> bool:

        return await self.tp_to(await self.closest_mob(excluded))

    async def tp_to_closest_health_wisp(
        self, only_safe: bool = False, excluded: Set[int] | None = None
    ) -> bool:

        return await self.tp_to(await self.closest_health_wisp(only_safe, excluded))

    async def tp_to_closest_mana_wisp(
        self, only_safe: bool = False, excluded: Set[int] | None = None
    ) -> bool:

        return await self.tp_to(await self.closest_mana_wisp(only_safe, excluded))

    async def health_ratio(self) -> float:

        hp = await self.client.stats.current_hitpoints()

        mx = await self.client.stats.max_hitpoints()

        return hp / mx if mx else 1.0

    async def mana_ratio(self) -> float:

        mp = await self.client.stats.current_mana()

        mx = await self.client.stats.max_mana()

        return mp / mx if mx else 1.0

    async def needs_health(self, pct: int = 20) -> bool:

        return await self.health_ratio() * 100 <= pct

    async def needs_mana(self, pct: int = 10) -> bool:

        return await self.mana_ratio() * 100 <= pct

    async def has_potion(self) -> bool:

        return await self.client.stats.potion_charge() >= 1.0

    async def use_potion(self) -> bool:

        if not await self.has_potion():
            return False

        async with self.client.mouse_handler:
            try:
                await self.client.mouse_handler.click_window_with_name("btnPotions")

                return True

            except ValueError:
                return False

    async def use_potion_if_needed(
        self, health_pct: int = 20, mana_pct: int = 10
    ) -> bool:

        if await self.needs_health(health_pct) or await self.needs_mana(mana_pct):
            return await self.use_potion()

        return True

    async def _filter_excluded(self, entities: list, excluded: Set[int] | None):

        if not excluded:
            return entities

        out = []

        for e in entities:
            if await e.global_id_full() not in excluded:
                out.append(e)

        return out

    async def safe_entities(self, entities: list, safe_dist: float = 2000) -> list:

        mob_positions = [await m.location() for m in await self.mobs()]

        safe = []

        for e in entities:
            try:
                pos = await e.location()

                if all(pos.distance(mp) >= safe_dist for mp in mob_positions):
                    safe.append(e)

            except Exception:
                continue

        return safe
