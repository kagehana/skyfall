import asyncio

import time

import unittest

from unittest.mock import AsyncMock, MagicMock


class TestLuaBridge(unittest.TestCase):
    def _bridge(self):

        from src.lang.bridge import LuaBridge

        return LuaBridge(asyncio.new_event_loop())

    def test_sync_function_registered(self):

        bridge = self._bridge()

        called = []

        bridge.register("ping", lambda: called.append(1), is_async=False)

        bridge._build_runtime().execute("ping()")

        self.assertEqual(called, [1])

    def test_sandbox_blocks_io(self):

        import lupa.lua55 as lua

        rt = self._bridge()._build_runtime()

        with self.assertRaises(lua.LuaError):
            rt.execute("io.write('x')")

    def test_sandbox_blocks_os(self):

        import lupa.lua55 as lua

        rt = self._bridge()._build_runtime()

        with self.assertRaises(lua.LuaError):
            rt.execute("os.exit()")

    def test_sandbox_blocks_require(self):

        import lupa.lua55 as lua

        rt = self._bridge()._build_runtime()

        with self.assertRaises(lua.LuaError):
            rt.execute("require('os')")

    def test_sleep_available(self):

        self._bridge()._build_runtime().execute("sleep(0.01)")

    def test_stop_interrupts_sleep(self):

        from src.lang.bridge import ScriptError

        bridge = self._bridge()

        bridge._stop.set()

        with self.assertRaises(ScriptError):
            bridge._build_runtime().execute("sleep(10)")

    def test_error_callback_fired(self):

        import tempfile, os

        bridge = self._bridge()

        errors = []

        bridge.on_error(errors.append)

        with tempfile.NamedTemporaryFile(mode="w", suffix=".lua", delete=False) as f:
            f.write("error('boom')")

            path = f.name

        try:
            bridge.load(path)

            time.sleep(0.3)

            self.assertTrue(any("boom" in e for e in errors))

        finally:
            os.unlink(path)

    def test_not_running_after_exit(self):

        import tempfile, os

        bridge = self._bridge()

        with tempfile.NamedTemporaryFile(mode="w", suffix=".lua", delete=False) as f:
            f.write("-- no-op")

            path = f.name

        try:
            bridge.load(path)

            time.sleep(0.2)

            self.assertFalse(bridge.running)

        finally:
            os.unlink(path)

    def test_clean_error_strips_prefix(self):

        from src.lang.bridge import _clean_error

        self.assertEqual(_clean_error('[string "..."]:42: bad call'), "42: bad call")

    def test_clean_error_passthrough(self):

        from src.lang.bridge import _clean_error

        self.assertEqual(_clean_error("plain error"), "plain error")


class TestCombatConfigParsing(unittest.TestCase):
    def p(self, text):

        from src.combat.config import parse_config

        return parse_config(text)

    def test_pass(self):

        self.assertTrue(self.p("pass").lines[0].moves[0].is_pass)

    def test_willcast(self):

        self.assertTrue(self.p("willcast").lines[0].moves[0].is_willcast)

    def test_named_spell_target(self):

        m = self.p("Feint @ enemy").lines[0].moves[0]

        self.assertEqual(m.spell, "Feint")

        self.assertEqual(m.target, "enemy")

    def test_enchant(self):

        m = self.p("Scarecrow[Colossal] @ enemy").lines[0].moves[0]

        self.assertEqual(m.enchant, "Colossal")

    def test_two_enchants(self):

        m = self.p("Feint[Potent][Sharpened] @ enemy").lines[0].moves[0]

        self.assertEqual(m.enchant, "Potent")

        self.assertEqual(m.enchant2, "Sharpened")

    def test_template_req(self):

        from src.combat.config import TemplateReq

        m = self.p("any<damage> @ enemy").lines[0].moves[0]

        self.assertIsInstance(m.spell, TemplateReq)

        self.assertIn("damage", m.spell.types)

    def test_template_multi_req(self):

        from src.combat.config import TemplateReq

        m = self.p("any<damage&aoe> @ aoe").lines[0].moves[0]

        self.assertIsInstance(m.spell, TemplateReq)

        self.assertIn("aoe", m.spell.types)

    def test_pipe_multiple_lines(self):

        self.assertEqual(len(self.p("Feint @ enemy | pass").lines), 2)

    def test_ampersand_chain(self):

        self.assertEqual(
            len(self.p("Feint @ enemy & Scarecrow @ enemy").lines[0].moves), 2
        )

    def test_round_specific(self):

        cfg = self.p("{1} Feint @ enemy | pass")

        self.assertIn(1, cfg.round_map)

        self.assertEqual(len(cfg.lines), 1)

    def test_target_self(self):

        self.assertEqual(self.p("Satyr @ self").lines[0].moves[0].target, "self")

    def test_target_boss(self):

        self.assertEqual(self.p("Feint @ boss").lines[0].moves[0].target, "boss")

    def test_target_nth_enemy(self):

        m = self.p("Feint @ enemy(2)").lines[0].moves[0]

        self.assertEqual(m.target_n, 2)

    def test_target_spell(self):

        self.assertEqual(
            self.p("Blade @ spell(any<blade>)").lines[0].moves[0].target, "spell"
        )

    def test_condition_parsed(self):

        m = self.p("?(self.health < 25%) Satyr @ self").lines[0].moves[0]

        c = m.condition

        self.assertIsNotNone(c)

        self.assertEqual(c.subject, "self")

        self.assertEqual(c.attr, "health")

        self.assertEqual(c.op, "<")

        self.assertEqual(c.value, 25.0)

        self.assertTrue(c.percent)

    def test_quoted_name(self):

        self.assertEqual(
            self.p('"Dark Tribute" @ self').lines[0].moves[0].spell, "Dark Tribute"
        )

    def test_multiline_string(self):

        self.assertEqual(len(self.p("A @ enemy |\nB @ enemy |\npass").lines), 3)

    def test_empty_segments_skipped(self):

        self.assertEqual(len(self.p("A @ enemy | | pass").lines), 2)


class TestDelegateCombatConfigs(unittest.TestCase):
    def test_no_markers(self):

        from src.factory import delegate_combat_configs

        r = delegate_combat_configs("pass", fallback_clients=3)

        self.assertEqual(len(r), 3)

        self.assertTrue(all(v == "pass" for v in r.values()))

    def test_per_client_markers(self):

        from src.factory import delegate_combat_configs

        r = delegate_combat_configs("### p1\nFeint @ enemy\n### p2\npass")

        self.assertIn(0, r)

        self.assertIn(1, r)

        self.assertIn("Feint", r[0])

        self.assertIn("pass", r[1])


class TestLuaMob(unittest.TestCase):
    def _call(self, coro):
        return asyncio.get_event_loop().run_until_complete(coro)

    def _table(self, val):
        return val  # passthrough; real bridge converts to Lua table

    def _xyz(self, x=1.0, y=2.0, z=3.0):
        m = MagicMock()
        m.x = x
        m.y = y
        m.z = z
        return m

    def _orient(self, pitch=0.1, roll=0.2, yaw=0.3):
        m = MagicMock()
        m.pitch = pitch
        m.roll = roll
        m.yaw = yaw
        return m

    def _make_entity(self, *, with_npc=False, npc_kw=None):
        e = MagicMock()
        e.object_name = AsyncMock(return_value="TestMob")
        e.display_name = AsyncMock(return_value="Test Mob")
        e.global_id_full = AsyncMock(return_value=111)
        e.perm_id = AsyncMock(return_value=222)
        e.mobile_id = AsyncMock(return_value=333)
        e.template_id_full = AsyncMock(return_value=444)
        e.debug_name = AsyncMock(return_value="dbg_name")
        e.zone_tag_id = AsyncMock(return_value=555)
        e.location = AsyncMock(return_value=self._xyz())
        e.orientation = AsyncMock(return_value=self._orient())
        e.scale = AsyncMock(return_value=1.5)
        e.speed_multiplier = AsyncMock(return_value=100)
        e.list_behavior_names = AsyncMock(
            return_value=["AnimationBehavior", "NPCBehavior"]
        )

        body = MagicMock()
        body.yaw = AsyncMock(return_value=0.9)
        body.pitch = AsyncMock(return_value=0.4)
        body.roll = AsyncMock(return_value=0.5)
        body.height = AsyncMock(return_value=2.2)
        e.actor_body = AsyncMock(return_value=body)

        if with_npc:
            kw = dict(
                boss=False,
                level=50,
                hp=1000,
                school="Fire",
                secondary="Balance",
                title_str="elite",
                intelligence=0.8,
                aggressive=3,
                turn_towards=True,
                hide_hp=False,
                shadow_pips=2,
                cyl=1.2,
            )
            if npc_kw:
                kw.update(npc_kw)

            npc = MagicMock()
            npc.boss_mob = AsyncMock(return_value=kw["boss"])
            npc.level = AsyncMock(return_value=kw["level"])
            npc.starting_health = AsyncMock(return_value=kw["hp"])
            npc.school_of_focus = AsyncMock(return_value=kw["school"])
            npc.secondary_school_of_focus = AsyncMock(return_value=kw["secondary"])

            title_mock = MagicMock()
            title_mock.__str__ = lambda s: (
                f"NpcBehaviorTemplateTitleType.{kw['title_str']}"
            )
            npc.mob_title = AsyncMock(return_value=title_mock)

            npc.intelligence = AsyncMock(return_value=kw["intelligence"])
            npc.aggressive_factor = AsyncMock(return_value=kw["aggressive"])
            npc.turn_towards_player = AsyncMock(return_value=kw["turn_towards"])
            npc.hide_current_hp = AsyncMock(return_value=kw["hide_hp"])
            npc.max_shadow_pips = AsyncMock(return_value=kw["shadow_pips"])
            npc.cylinder_scale_value = AsyncMock(return_value=kw["cyl"])

            behavior = MagicMock()
            behavior.read_type_name = AsyncMock(return_value="NPCBehavior")
            e.inactive_behaviors = AsyncMock(return_value=[behavior])
            e.fetch_npc_behavior_template = AsyncMock(return_value=npc)
        else:
            e.inactive_behaviors = AsyncMock(return_value=[])
            e.fetch_npc_behavior_template = AsyncMock(return_value=None)

        return e

    def _mob(self, entity=None, distance=10.0, client=None):
        from src.lang.client import LuaMob

        if entity is None:
            entity = self._make_entity()
        if client is None:
            client = MagicMock()
            client.teleport = AsyncMock()
        return LuaMob(entity, distance, self._call, client, self._table)

    # ── identity ─────────────────────────────────────────────────────────────

    def test_name(self):
        self.assertEqual(self._mob().name(), "TestMob")

    def test_display_name(self):
        self.assertEqual(self._mob().display_name(), "Test Mob")

    def test_global_id(self):
        self.assertEqual(self._mob().global_id(), 111)

    def test_perm_id(self):
        self.assertEqual(self._mob().perm_id(), 222)

    def test_mobile_id(self):
        self.assertEqual(self._mob().mobile_id(), 333)

    def test_template_id(self):
        self.assertEqual(self._mob().template_id(), 444)

    def test_debug_name(self):
        self.assertEqual(self._mob().debug_name(), "dbg_name")

    def test_zone_tag_id(self):
        self.assertEqual(self._mob().zone_tag_id(), 555)

    # ── position ─────────────────────────────────────────────────────────────

    def test_distance(self):
        self.assertAlmostEqual(self._mob(distance=42.5).distance(), 42.5)

    def test_x(self):
        self.assertAlmostEqual(self._mob().x(), 1.0)

    def test_y(self):
        self.assertAlmostEqual(self._mob().y(), 2.0)

    def test_z(self):
        self.assertAlmostEqual(self._mob().z(), 3.0)

    def test_location_table(self):
        loc = self._mob().location()
        self.assertEqual(loc[0], 1.0)
        self.assertEqual(loc[1], 2.0)
        self.assertEqual(loc[2], 3.0)

    def test_yaw_from_actor_body(self):
        self.assertAlmostEqual(self._mob().yaw(), 0.9)

    def test_pitch_from_actor_body(self):
        self.assertAlmostEqual(self._mob().pitch(), 0.4)

    def test_roll_from_actor_body(self):
        self.assertAlmostEqual(self._mob().roll(), 0.5)

    def test_height(self):
        self.assertAlmostEqual(self._mob().height(), 2.2)

    def test_yaw_falls_back_to_orientation(self):
        e = self._make_entity()
        e.actor_body = AsyncMock(return_value=None)
        self.assertAlmostEqual(self._mob(entity=e).yaw(), 0.3)

    def test_scale(self):
        self.assertAlmostEqual(self._mob().scale(), 1.5)

    def test_speed(self):
        self.assertEqual(self._mob().speed(), 100)

    def test_to_calls_teleport(self):
        client = MagicMock()
        client.teleport = AsyncMock()
        e = self._make_entity()
        self._mob(entity=e, client=client).to()
        client.teleport.assert_called_once()
        xyz_arg = client.teleport.call_args[0][0]
        self.assertAlmostEqual(xyz_arg.x, 1.0)
        self.assertAlmostEqual(xyz_arg.y, 2.0)
        self.assertAlmostEqual(xyz_arg.z, 3.0)

    # ── NPC template ──────────────────────────────────────────────────────────

    def test_is_boss_false_no_npc(self):
        self.assertFalse(self._mob().is_boss())

    def test_is_boss_false_with_npc(self):
        e = self._make_entity(with_npc=True, npc_kw={"boss": False})
        self.assertFalse(self._mob(entity=e).is_boss())

    def test_is_boss_true(self):
        e = self._make_entity(with_npc=True, npc_kw={"boss": True})
        self.assertTrue(self._mob(entity=e).is_boss())

    def test_level(self):
        e = self._make_entity(with_npc=True)
        self.assertEqual(self._mob(entity=e).level(), 50)

    def test_level_no_npc(self):
        self.assertEqual(self._mob().level(), 0)

    def test_starting_health(self):
        e = self._make_entity(with_npc=True)
        self.assertEqual(self._mob(entity=e).starting_health(), 1000)

    def test_school(self):
        e = self._make_entity(with_npc=True)
        self.assertEqual(self._mob(entity=e).school(), "Fire")

    def test_school_no_npc(self):
        self.assertEqual(self._mob().school(), "Unknown")

    def test_secondary_school(self):
        e = self._make_entity(with_npc=True)
        self.assertEqual(self._mob(entity=e).secondary_school(), "Balance")

    def test_title(self):
        e = self._make_entity(with_npc=True)
        self.assertEqual(self._mob(entity=e).title(), "elite")

    def test_title_no_npc(self):
        self.assertEqual(self._mob().title(), "normal")

    def test_intelligence(self):
        e = self._make_entity(with_npc=True)
        self.assertAlmostEqual(self._mob(entity=e).intelligence(), 0.8)

    def test_aggressive_factor(self):
        e = self._make_entity(with_npc=True)
        self.assertEqual(self._mob(entity=e).aggressive_factor(), 3)

    def test_turn_towards_player(self):
        e = self._make_entity(with_npc=True)
        self.assertTrue(self._mob(entity=e).turn_towards_player())

    def test_hide_hp(self):
        e = self._make_entity(with_npc=True)
        self.assertFalse(self._mob(entity=e).hide_hp())

    def test_max_shadow_pips(self):
        e = self._make_entity(with_npc=True)
        self.assertEqual(self._mob(entity=e).max_shadow_pips(), 2)

    def test_collision_radius(self):
        e = self._make_entity(with_npc=True)
        self.assertAlmostEqual(self._mob(entity=e).collision_radius(), 1.2)

    def test_collision_radius_no_npc(self):
        self.assertAlmostEqual(self._mob().collision_radius(), 0.0)

    # ── misc ─────────────────────────────────────────────────────────────────

    def test_behavior_names(self):
        names = self._mob().behavior_names()
        self.assertIn("NPCBehavior", names)


class TestLuaClientMobs(unittest.TestCase):
    def _call(self, coro):
        return asyncio.get_event_loop().run_until_complete(coro)

    def _table(self, val):
        return val

    def _pos(self, x=0.0, y=0.0, z=0.0):
        m = MagicMock()
        m.distance = MagicMock(side_effect=lambda other: abs(other.x - x))
        return m

    def _loc(self, x=0.0):
        m = MagicMock()
        m.x = x
        return m

    def _entity(self, obj_name="", disp_name="", x=0.0, gid=0, tid=0, is_boss=False):
        e = MagicMock()
        e.object_name = AsyncMock(return_value=obj_name)
        e.display_name = AsyncMock(return_value=disp_name)
        e.location = AsyncMock(return_value=self._loc(x))
        e.global_id_full = AsyncMock(return_value=gid)
        e.template_id_full = AsyncMock(return_value=tid)
        e.actor_body = AsyncMock(return_value=None)
        e.orientation = AsyncMock(return_value=MagicMock(yaw=0.0, pitch=0.0, roll=0.0))
        e.scale = AsyncMock(return_value=1.0)
        e.speed_multiplier = AsyncMock(return_value=0)
        e.perm_id = AsyncMock(return_value=0)
        e.mobile_id = AsyncMock(return_value=0)
        e.debug_name = AsyncMock(return_value="")
        e.zone_tag_id = AsyncMock(return_value=0)
        e.list_behavior_names = AsyncMock(return_value=[])

        if is_boss:
            npc = MagicMock()
            npc.boss_mob = AsyncMock(return_value=True)
            beh = MagicMock()
            beh.read_type_name = AsyncMock(return_value="NPCBehavior")
            e.inactive_behaviors = AsyncMock(return_value=[beh])
            e.fetch_npc_behavior_template = AsyncMock(return_value=npc)
        else:
            e.inactive_behaviors = AsyncMock(return_value=[])
            e.fetch_npc_behavior_template = AsyncMock(return_value=None)

        return e

    def _client(self, entities, pos_x=0.0):
        import threading
        from src.lang.client import LuaClient

        ww = MagicMock()
        ww.title = "p1"
        ww.body.position = AsyncMock(return_value=self._pos(x=pos_x))
        ww.get_base_entity_list = AsyncMock(return_value=entities)

        return LuaClient(ww, self._call, threading.Event(), self._table)

    # ── find_mob ─────────────────────────────────────────────────────────────

    def test_find_mob_by_object_name(self):
        e = self._entity(obj_name="Rattlebones", x=100)
        c = self._client([e])
        mob = c.find_mob("rattlebones")
        self.assertIsNotNone(mob)
        self.assertEqual(mob.name(), "Rattlebones")

    def test_find_mob_by_display_name(self):
        e = self._entity(obj_name="Mob_01", disp_name="Rattlebones", x=50)
        c = self._client([e])
        mob = c.find_mob("rattlebones")
        self.assertIsNotNone(mob)

    def test_find_mob_partial_match(self):
        e = self._entity(obj_name="RattlebonesElite", x=10)
        c = self._client([e])
        self.assertIsNotNone(c.find_mob("rattle"))

    def test_find_mob_no_match(self):
        e = self._entity(obj_name="Gobbler", x=10)
        c = self._client([e])
        self.assertIsNone(c.find_mob("rattlebones"))

    def test_find_mob_respects_max_dist(self):
        near = self._entity(obj_name="Rattlebones", x=50)
        far = self._entity(obj_name="Rattlebones", x=500)
        c = self._client([near, far])
        mob = c.find_mob("rattlebones", max_dist=100)
        self.assertIsNotNone(mob)
        self.assertAlmostEqual(mob.distance(), 50.0)

    def test_find_mob_returns_first(self):
        e1 = self._entity(obj_name="Rattlebones", x=200)
        e2 = self._entity(obj_name="Rattlebones", x=100)
        c = self._client([e1, e2])
        mob = c.find_mob("rattlebones")
        # first in entity list, not closest
        self.assertAlmostEqual(mob.distance(), 200.0)

    # ── find_mobs ────────────────────────────────────────────────────────────

    def test_find_mobs_returns_all_matches(self):
        entities = [
            self._entity(obj_name="Rattlebones", x=10),
            self._entity(obj_name="Gobbler", x=20),
            self._entity(disp_name="Rattlebones Elite", x=30),
        ]
        mobs = self._client(entities).find_mobs("rattlebones")
        self.assertEqual(len(mobs), 2)

    def test_find_mobs_empty_on_no_match(self):
        c = self._client([self._entity(obj_name="Gobbler", x=10)])
        self.assertEqual(len(c.find_mobs("rattlebones")), 0)

    def test_find_mobs_max_dist_filters(self):
        entities = [
            self._entity(obj_name="Rattlebones", x=50),
            self._entity(obj_name="Rattlebones", x=500),
        ]
        mobs = self._client(entities).find_mobs("rattlebones", max_dist=100)
        self.assertEqual(len(mobs), 1)

    # ── nearest_mob ───────────────────────────────────────────────────────────

    def test_nearest_mob_returns_closest(self):
        entities = [
            self._entity(obj_name="A", x=300),
            self._entity(obj_name="B", x=50),
            self._entity(obj_name="C", x=200),
        ]
        mob = self._client(entities).nearest_mob()
        self.assertAlmostEqual(mob.distance(), 50.0)

    def test_nearest_mob_none_when_empty(self):
        self.assertIsNone(self._client([]).nearest_mob())

    def test_nearest_mob_max_dist(self):
        entities = [
            self._entity(obj_name="A", x=500),
            self._entity(obj_name="B", x=800),
        ]
        self.assertIsNone(self._client(entities).nearest_mob(max_dist=100))

    # ── nearest_boss ──────────────────────────────────────────────────────────

    def test_nearest_boss_found(self):
        entities = [
            self._entity(obj_name="Minion", x=30, is_boss=False),
            self._entity(obj_name="BigBoss", x=200, is_boss=True),
        ]
        mob = self._client(entities).nearest_boss()
        self.assertIsNotNone(mob)
        self.assertEqual(mob.name(), "BigBoss")

    def test_nearest_boss_picks_closest(self):
        entities = [
            self._entity(obj_name="Boss1", x=300, is_boss=True),
            self._entity(obj_name="Boss2", x=100, is_boss=True),
        ]
        mob = self._client(entities).nearest_boss()
        self.assertAlmostEqual(mob.distance(), 100.0)

    def test_nearest_boss_none_when_no_bosses(self):
        entities = [self._entity(obj_name="Minion", x=10, is_boss=False)]
        self.assertIsNone(self._client(entities).nearest_boss())

    # ── mob_by_id ────────────────────────────────────────────────────────────

    def test_mob_by_id_found(self):
        e = self._entity(obj_name="Target", x=99, gid=777)
        mob = self._client([e]).mob_by_id(777)
        self.assertIsNotNone(mob)
        self.assertEqual(mob.global_id(), 777)

    def test_mob_by_id_not_found(self):
        e = self._entity(obj_name="Other", gid=111)
        self.assertIsNone(self._client([e]).mob_by_id(999))

    # ── mob_by_template ───────────────────────────────────────────────────────

    def test_mob_by_template_found(self):
        e = self._entity(obj_name="Templated", x=55, tid=4242)
        mob = self._client([e]).mob_by_template(4242)
        self.assertIsNotNone(mob)
        self.assertEqual(mob.template_id(), 4242)

    def test_mob_by_template_not_found(self):
        e = self._entity(tid=1)
        self.assertIsNone(self._client([e]).mob_by_template(9999))

    # ── has_mob ───────────────────────────────────────────────────────────────

    def test_has_mob_true(self):
        e = self._entity(obj_name="Rattlebones", x=10)
        self.assertTrue(self._client([e]).has_mob("rattle"))

    def test_has_mob_false(self):
        e = self._entity(obj_name="Gobbler", x=10)
        self.assertFalse(self._client([e]).has_mob("rattlebones"))

    # ── mobs_by_school ────────────────────────────────────────────────────────

    def _npc_entity(self, obj_name, school, title_str="normal", x=10.0):
        e = self._entity(obj_name=obj_name, x=x)
        npc = MagicMock()
        npc.school_of_focus = AsyncMock(return_value=school)
        title_m = MagicMock()
        title_m.__str__ = lambda s: f"NpcBehaviorTemplateTitleType.{title_str}"
        npc.mob_title = AsyncMock(return_value=title_m)
        beh = MagicMock()
        beh.read_type_name = AsyncMock(return_value="NPCBehavior")
        e.inactive_behaviors = AsyncMock(return_value=[beh])
        e.fetch_npc_behavior_template = AsyncMock(return_value=npc)
        return e

    def test_mobs_by_school_match(self):
        entities = [
            self._npc_entity("FireMob", "Fire", x=10),
            self._npc_entity("IceMob", "Ice", x=20),
            self._npc_entity("FireElite", "Fire", x=30),
        ]
        mobs = self._client(entities).mobs_by_school("fire")
        self.assertEqual(len(mobs), 2)

    def test_mobs_by_school_case_insensitive(self):
        e = self._npc_entity("FireMob", "Fire", x=10)
        mobs = self._client([e]).mobs_by_school("FIRE")
        self.assertEqual(len(mobs), 1)

    def test_mobs_by_school_no_match(self):
        e = self._npc_entity("IceMob", "Ice", x=10)
        self.assertEqual(len(self._client([e]).mobs_by_school("storm")), 0)

    def test_mobs_by_school_max_dist(self):
        entities = [
            self._npc_entity("FireClose", "Fire", x=50),
            self._npc_entity("FireFar", "Fire", x=500),
        ]
        mobs = self._client(entities).mobs_by_school("fire", max_dist=100)
        self.assertEqual(len(mobs), 1)

    # ── mobs_by_title ─────────────────────────────────────────────────────────

    def test_mobs_by_title_boss(self):
        entities = [
            self._npc_entity("BigBoss", "Fire", title_str="boss", x=10),
            self._npc_entity("Minion", "Fire", title_str="minion", x=20),
            self._npc_entity("EliteBoss", "Ice", title_str="boss", x=30),
        ]
        mobs = self._client(entities).mobs_by_title("boss")
        self.assertEqual(len(mobs), 2)

    def test_mobs_by_title_elite(self):
        e = self._npc_entity("Elite", "Storm", title_str="elite", x=10)
        mobs = self._client([e]).mobs_by_title("elite")
        self.assertEqual(len(mobs), 1)

    def test_mobs_by_title_no_match(self):
        e = self._npc_entity("Normal", "Myth", title_str="normal", x=10)
        self.assertEqual(len(self._client([e]).mobs_by_title("boss")), 0)

    # ── own position / stats ──────────────────────────────────────────────────

    def _stat_client(self, hp=80, max_hp=100, mp=40, max_mp=200):
        import threading
        from src.lang.client import LuaClient

        ww = MagicMock()
        ww.title = "p1"
        ww.stats.current_hitpoints = AsyncMock(return_value=hp)
        ww.stats.max_hitpoints = AsyncMock(return_value=max_hp)
        ww.stats.current_mana = AsyncMock(return_value=mp)
        ww.stats.max_mana = AsyncMock(return_value=max_mp)

        pos = MagicMock()
        pos.x, pos.y, pos.z = 10.0, 20.0, 30.0
        pos.distance = MagicMock(return_value=55.0)
        ww.body.position = AsyncMock(return_value=pos)
        ww.body.yaw = AsyncMock(return_value=1.57)
        ww.get_base_entity_list = AsyncMock(return_value=[])

        return LuaClient(ww, self._call, threading.Event(), self._table)

    def test_health_pct(self):
        self.assertAlmostEqual(self._stat_client(hp=80, max_hp=100).health_pct(), 80.0)

    def test_health_pct_zero_max(self):
        self.assertAlmostEqual(self._stat_client(hp=0, max_hp=0).health_pct(), 0.0)

    def test_mana_pct(self):
        self.assertAlmostEqual(self._stat_client(mp=40, max_mp=200).mana_pct(), 20.0)

    def test_client_x(self):
        self.assertAlmostEqual(self._stat_client().x(), 10.0)

    def test_client_y(self):
        self.assertAlmostEqual(self._stat_client().y(), 20.0)

    def test_client_z(self):
        self.assertAlmostEqual(self._stat_client().z(), 30.0)

    def test_client_position_table(self):
        pos = self._stat_client().position()
        self.assertEqual(pos, [10.0, 20.0, 30.0])

    def test_client_facing(self):
        self.assertAlmostEqual(self._stat_client().facing(), 1.57)

    def test_client_distance_to(self):
        self.assertAlmostEqual(self._stat_client().distance_to(0, 0, 0), 55.0)

    # ── waitfor_mob / waitfor_mob_gone ────────────────────────────────────────

    def test_waitfor_mob_returns_immediately_when_present(self):
        e = self._entity(obj_name="Rattlebones", x=10)
        # waitfor_mob filters via NPCBehavior + is_mob flag (offset 288).
        # _entity doesn't mock that surface by default, so wire it up here.
        beh = MagicMock()
        beh.read_value_from_offset = AsyncMock(return_value=True)
        e.search_behavior_by_name = AsyncMock(return_value=beh)
        # Should return without looping since mob is already there
        self._client([e]).waitfor_mob("rattlebones")

    def test_waitfor_mob_gone_returns_immediately_when_absent(self):
        e = self._entity(obj_name="Gobbler", x=10)
        self._client([e]).waitfor_mob_gone("rattlebones")

    def test_waitfor_mob_stop_signal_exits(self):
        import threading
        from src.lang.client import LuaClient

        ww = MagicMock()
        ww.title = "p1"
        pos = MagicMock()
        pos.distance = MagicMock(return_value=10.0)
        ww.body.position = AsyncMock(return_value=pos)
        ww.get_base_entity_list = AsyncMock(return_value=[])  # mob never appears

        stop = threading.Event()
        stop.set()  # pre-set so first iteration exits immediately

        c = LuaClient(ww, self._call, stop, self._table)
        c.waitfor_mob("anything")  # must not hang


class TestLuaClientDropsAndHttp(unittest.TestCase):
    def _make(self, latest_drops=""):
        import threading
        from src.lang.client import LuaClient

        ww = MagicMock()
        ww.title = "p1"
        ww.latest_drops = latest_drops

        call = lambda coro: (
            asyncio.get_event_loop().run_until_complete(coro)
            if asyncio.iscoroutine(coro)
            else coro
        )
        return LuaClient(ww, call, threading.Event(), lambda v: v)

    # ── recent_drops ──────────────────────────────────────────────────────────

    def test_recent_drops_empty(self):
        self.assertEqual(self._make().recent_drops(), [])

    def test_recent_drops_no_attribute(self):
        import threading
        from src.lang.client import LuaClient

        ww = MagicMock(spec=[])  # no latest_drops attribute
        ww.title = "p1"
        c = LuaClient(ww, lambda x: x, threading.Event(), lambda v: v)
        self.assertEqual(c.recent_drops(), [])

    def test_recent_drops_returns_all_when_under_limit(self):
        drops = "\n".join(["Item A", "Item B", "Item C"])
        self.assertEqual(
            self._make(drops).recent_drops(), ["Item A", "Item B", "Item C"]
        )

    def test_recent_drops_returns_last_25(self):
        items = [f"Item {i}" for i in range(30)]
        drops = "\n".join(items)
        result = self._make(drops).recent_drops()
        self.assertEqual(len(result), 25)
        self.assertEqual(result[0], "Item 5")
        self.assertEqual(result[-1], "Item 29")

    def test_recent_drops_custom_n(self):
        items = [f"Item {i}" for i in range(10)]
        drops = "\n".join(items)
        result = self._make(drops).recent_drops(3)
        self.assertEqual(len(result), 3)
        self.assertEqual(result[-1], "Item 9")

    def test_recent_drops_skips_empty_lines(self):
        drops = "Item A\n\nItem B\n"
        result = self._make(drops).recent_drops()
        self.assertEqual(result, ["Item A", "Item B"])

    # ── got_drop ──────────────────────────────────────────────────────────────

    def test_got_drop_true_exact(self):
        self.assertTrue(self._make("Robe of Apotheosis").got_drop("Robe of Apotheosis"))

    def test_got_drop_case_insensitive(self):
        self.assertTrue(self._make("Robe of Apotheosis").got_drop("robe of apotheosis"))

    def test_got_drop_partial_match(self):
        self.assertTrue(
            self._make("Robe of Apotheosis\nSome Jewel").got_drop("apotheosis")
        )

    def test_got_drop_false_no_match(self):
        self.assertFalse(self._make("Pet Snack\nReagent").got_drop("Robe"))

    def test_got_drop_false_empty(self):
        self.assertFalse(self._make().got_drop("anything"))

    def test_got_drop_matches_among_many(self):
        drops = "\n".join([f"Item {i}" for i in range(20)] + ["Jade Oni's Helm"])
        self.assertTrue(self._make(drops).got_drop("jade oni"))

    # ── http methods ──────────────────────────────────────────────────────────

    def _http_client(self):
        return self._make()

    def test_http_get_calls_requests(self):
        from unittest.mock import patch, MagicMock as MM

        resp = MM()
        resp.text = "ok"
        with patch("requests.get", return_value=resp) as mock_get:
            result = self._http_client().http_get("https://example.com")
            mock_get.assert_called_once_with(
                "https://example.com", headers={}, timeout=10
            )
            self.assertEqual(result, "ok")

    def test_http_get_passes_headers(self):
        from unittest.mock import patch, MagicMock as MM

        resp = MM()
        resp.text = ""
        headers = MagicMock()
        headers.items = MagicMock(return_value=[("Authorization", "Bearer tok")])
        with patch("requests.get", return_value=resp) as mock_get:
            self._http_client().http_get("https://example.com", headers)
            _, kwargs = mock_get.call_args
            self.assertEqual(kwargs["headers"]["Authorization"], "Bearer tok")

    def test_http_post_calls_requests(self):
        from unittest.mock import patch, MagicMock as MM

        resp = MM()
        resp.text = "created"
        with patch("requests.post", return_value=resp) as mock_post:
            result = self._http_client().http_post("https://example.com", '{"x":1}')
            mock_post.assert_called_once()
            args, kwargs = mock_post.call_args
            self.assertEqual(args[0], "https://example.com")
            self.assertEqual(kwargs["data"], b'{"x":1}')
            self.assertEqual(kwargs["timeout"], 10)
            self.assertEqual(result, "created")

    def test_http_post_default_content_type(self):
        from unittest.mock import patch, MagicMock as MM

        resp = MM()
        resp.text = ""
        with patch("requests.post", return_value=resp) as mock_post:
            self._http_client().http_post("https://example.com", "body")
            _, kwargs = mock_post.call_args
            self.assertEqual(kwargs["headers"]["Content-Type"], "application/json")

    def test_http_post_header_overrides_default(self):
        from unittest.mock import patch, MagicMock as MM

        resp = MM()
        resp.text = ""
        headers = MagicMock()
        headers.items = MagicMock(return_value=[("Content-Type", "text/plain")])
        with patch("requests.post", return_value=resp) as mock_post:
            self._http_client().http_post("https://example.com", "body", headers)
            _, kwargs = mock_post.call_args
            self.assertEqual(kwargs["headers"]["Content-Type"], "text/plain")

    def test_http_put_calls_requests(self):
        from unittest.mock import patch, MagicMock as MM

        resp = MM()
        resp.text = "updated"
        with patch("requests.put", return_value=resp) as mock_put:
            result = self._http_client().http_put("https://example.com", '{"y":2}')
            mock_put.assert_called_once()
            self.assertEqual(result, "updated")

    def test_http_put_default_content_type(self):
        from unittest.mock import patch, MagicMock as MM

        resp = MM()
        resp.text = ""
        with patch("requests.put", return_value=resp) as mock_put:
            self._http_client().http_put("https://example.com", "body")
            _, kwargs = mock_put.call_args
            self.assertEqual(kwargs["headers"]["Content-Type"], "application/json")

    def test_http_patch_calls_requests(self):
        from unittest.mock import patch, MagicMock as MM

        resp = MM()
        resp.text = "patched"
        with patch("requests.patch", return_value=resp) as mock_patch:
            result = self._http_client().http_patch("https://example.com", '{"z":3}')
            mock_patch.assert_called_once()
            self.assertEqual(result, "patched")

    def test_http_patch_default_content_type(self):
        from unittest.mock import patch, MagicMock as MM

        resp = MM()
        resp.text = ""
        with patch("requests.patch", return_value=resp) as mock_patch:
            self._http_client().http_patch("https://example.com", "body")
            _, kwargs = mock_patch.call_args
            self.assertEqual(kwargs["headers"]["Content-Type"], "application/json")

    def test_http_delete_calls_requests(self):
        from unittest.mock import patch, MagicMock as MM

        resp = MM()
        resp.text = "deleted"
        with patch("requests.delete", return_value=resp) as mock_delete:
            result = self._http_client().http_delete("https://example.com")
            mock_delete.assert_called_once_with(
                "https://example.com", headers={}, timeout=10
            )
            self.assertEqual(result, "deleted")

    def test_http_delete_passes_headers(self):
        from unittest.mock import patch, MagicMock as MM

        resp = MM()
        resp.text = ""
        headers = MagicMock()
        headers.items = MagicMock(return_value=[("X-Token", "abc")])
        with patch("requests.delete", return_value=resp) as mock_delete:
            self._http_client().http_delete("https://example.com", headers)
            _, kwargs = mock_delete.call_args
            self.assertEqual(kwargs["headers"]["X-Token"], "abc")


class TestEntityClient(unittest.TestCase):
    def _run(self, coro):

        return asyncio.get_event_loop().run_until_complete(coro)

    def _ec(self, hp, max_hp, mp=100, max_mp=100, potion=0.0):

        from src.nav.client import EntityClient

        c = MagicMock()

        c.stats.current_hitpoints = AsyncMock(return_value=hp)

        c.stats.max_hitpoints = AsyncMock(return_value=max_hp)

        c.stats.current_mana = AsyncMock(return_value=mp)

        c.stats.max_mana = AsyncMock(return_value=max_mp)

        c.stats.potion_charge = AsyncMock(return_value=potion)

        return EntityClient(c)

    def test_needs_health_true(self):

        self.assertTrue(self._run(self._ec(10, 100).needs_health(20)))

    def test_needs_health_false(self):

        self.assertFalse(self._run(self._ec(80, 100).needs_health(20)))

    def test_health_ratio(self):

        self.assertAlmostEqual(self._run(self._ec(50, 200).health_ratio()), 0.25)

    def test_needs_mana_true(self):

        self.assertTrue(self._run(self._ec(100, 100, 5, 100).needs_mana(10)))

    def test_needs_mana_false(self):

        self.assertFalse(self._run(self._ec(100, 100, 50, 100).needs_mana(10)))

    def test_has_potion_true(self):

        self.assertTrue(self._run(self._ec(100, 100, potion=2.0).has_potion()))

    def test_has_potion_false(self):

        self.assertFalse(self._run(self._ec(100, 100, potion=0.0).has_potion()))

    def test_health_ratio_zero_max(self):

        from src.nav.client import EntityClient

        c = MagicMock()

        c.stats.current_hitpoints = AsyncMock(return_value=0)

        c.stats.max_hitpoints = AsyncMock(return_value=0)

        ec = EntityClient(c)

        self.assertAlmostEqual(self._run(ec.health_ratio()), 1.0)


class _AsyncCM:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False


def _make_card(
    name,
    castable=True,
    enchanted=False,
    item=False,
    cloaked=False,
    display_name=None,
    template_id=None,
):
    c = MagicMock()
    c.name = AsyncMock(return_value=name)
    c.display_name = AsyncMock(return_value=display_name or name)
    c.is_castable = AsyncMock(return_value=castable)
    c.is_enchanted = AsyncMock(return_value=enchanted)
    c.is_enchanted_from_item_card = AsyncMock(return_value=False)
    c.is_item_card = AsyncMock(return_value=item)
    c.is_cloaked = AsyncMock(return_value=cloaked)
    c.cast = AsyncMock()
    c.discard = AsyncMock()
    c.get_spell_effects = AsyncMock(return_value=[])
    # Stable per-card template id so _hand_index_of can find it in a spell_list.
    c.template_id = AsyncMock(
        return_value=template_id if template_id is not None else id(c) & 0xFFFFFFFF
    )

    # Name-resolution chain used by handler._names_for → _card_names:
    #   card.get_graphical_spell() → .spell_template() → .name() / .display_name()
    # plus a langcode lookup on combat_handler.client.cache_handler so the
    # human-readable display name shows up alongside the template name.
    tpl = MagicMock()
    tpl.name = AsyncMock(return_value=name)
    tpl.display_name = AsyncMock(return_value=f"_langcode_{name}")
    gs = MagicMock()
    gs.spell_template = AsyncMock(return_value=tpl)
    c.get_graphical_spell = AsyncMock(return_value=gs)
    c.combat_handler = MagicMock()
    c.combat_handler.client = MagicMock()
    c.combat_handler.client.cache_handler = MagicMock()
    c.combat_handler.client.cache_handler.get_langcode_name = AsyncMock(
        return_value=display_name or name
    )
    return c


def _make_member(
    *,
    monster=False,
    player=False,
    boss=False,
    dead=False,
    stunned=False,
    name="Player",
    health=100,
    max_health=100,
    team_id=None,
    owner_id=None,
):
    m = MagicMock()
    m.is_monster = AsyncMock(return_value=monster)
    m.is_player = AsyncMock(return_value=player)
    m.is_boss = AsyncMock(return_value=boss)
    m.is_dead = AsyncMock(return_value=dead)
    m.is_stunned = AsyncMock(return_value=stunned)
    m.name = AsyncMock(return_value=name)
    m.health = AsyncMock(return_value=health)
    m.max_health = AsyncMock(return_value=max_health)
    m.mana = AsyncMock(return_value=50)
    m.max_mana = AsyncMock(return_value=100)
    if team_id is None:
        team_id = 2 if monster else 1
    if owner_id is None:
        owner_id = f"id_{name}_{id(m)}"
    part = MagicMock()
    part.team_id = AsyncMock(return_value=team_id)
    part.owner_id_full = AsyncMock(return_value=owner_id)
    m.get_participant = AsyncMock(return_value=part)
    return m


class TestNativeCombat(unittest.TestCase):
    def _run(self, coro):
        return asyncio.new_event_loop().run_until_complete(coro)

    def _handler(
        self,
        *,
        cards=None,
        members=None,
        config_str=None,
        stunned=False,
        in_battle=True,
    ):
        from src.combat.handler import NativeCombat

        client = MagicMock()
        client.mouse_handler = _AsyncCM()
        client.root_window.get_windows_with_name = AsyncMock(return_value=[])
        # NativeCombat acquires _active_combat at handle_combat entry now.
        # Without this, MagicMock auto-creates the attribute and trips the
        # ownership-wait loop in handle_combat.
        client._active_combat = None
        # The handler is now packet-based — casts go through send_combat_spell,
        # passes through send_combat_pass, flees through send_combat_flee.
        # Without these, awaiting an auto-MagicMock raises TypeError.
        client.send_combat_spell = AsyncMock()
        client.send_combat_pass = AsyncMock()
        client.send_combat_flee = AsyncMock()
        client.send_combat_enchant = AsyncMock()
        client.send_pet_willcast = AsyncMock()
        # combat_config sentinel: real clients may not have this attr at all.
        # Strip the auto-MagicMock so getattr(..., _UNSET) returns _UNSET.
        del client.combat_config

        h = NativeCombat(client)
        h._cast_time = 0  # don't sleep between packets in tests

        if config_str is not None:
            h.set_config_string(config_str)

        cards = cards or []
        if members is None:
            members = [_make_member(player=True, name="Me", health=100, max_health=100)]
        client_member = members[0] if members else _make_member(player=True)
        client_member.is_stunned = AsyncMock(return_value=stunned)

        h.get_cards = AsyncMock(return_value=cards)
        h.get_members = AsyncMock(return_value=members)
        h.get_client_member = AsyncMock(return_value=client_member)
        h.pass_button = AsyncMock()
        h.draw_button = AsyncMock()
        h.round_number = AsyncMock(return_value=1)
        return h

    def test_no_config_passes(self):
        h = self._handler()
        self._run(h.handle_round())
        h.client.send_combat_pass.assert_awaited()

    def test_stunned_passes_and_decrements_turn(self):
        h = self._handler(config_str="Feint @ enemy", stunned=True)
        self._run(h.handle_round())
        h.client.send_combat_pass.assert_awaited()
        self.assertEqual(h._turn_adjust, -1)

    def test_named_spell_exact_match_casts(self):
        feint = _make_card("Feint")
        enemy = _make_member(monster=True, name="Goblin")
        h = self._handler(
            cards=[feint],
            members=[_make_member(player=True), enemy],
            config_str="Feint @ enemy",
        )
        self._run(h.handle_round())
        h.client.send_combat_spell.assert_awaited()
        h.client.send_combat_pass.assert_not_awaited()

    def test_named_spell_substring_fallback_casts(self):
        # Config says "Mass" — no exact card, but "Mass Hit" matches via substring
        mass_hit = _make_card("Mass Hit")
        enemy = _make_member(monster=True)
        h = self._handler(
            cards=[mass_hit],
            members=[_make_member(player=True), enemy],
            config_str="Mass @ enemy",
        )
        self._run(h.handle_round())
        h.client.send_combat_spell.assert_awaited()

    def test_no_enemy_means_move_fails_not_cast(self):
        # enemy target with no enemies present must NOT cast (was casting on None=AOE before fix)
        feint = _make_card("Feint")
        h = self._handler(
            cards=[feint],
            members=[_make_member(player=True)],
            config_str="Feint @ enemy | pass",
        )
        self._run(h.handle_round())
        h.client.send_combat_spell.assert_not_awaited()
        h.client.send_combat_pass.assert_awaited()

    def test_priority_falls_through_to_pass(self):
        # No matching card for "NoSuchSpell" → falls through to bare "pass"
        enemy = _make_member(monster=True)
        h = self._handler(
            cards=[_make_card("Other")],
            members=[_make_member(player=True), enemy],
            config_str="NoSuchSpell @ enemy | pass",
        )
        self._run(h.handle_round())
        h.client.send_combat_pass.assert_awaited()

    def test_willcast_with_target_recognized(self):
        # "Willcast @ enemy" must parse as is_willcast (was being parsed as a spell named "Willcast").
        # _try_willcast iterates castable cards for one that is_item_card() or is_cloaked(),
        # then sends send_combat_spell at _NO_TARGET — no member subcircle.
        item_card = _make_card("Potion", item=True)
        enemy = _make_member(monster=True)
        h = self._handler(
            cards=[item_card],
            members=[_make_member(player=True), enemy],
            config_str="Willcast @ enemy",
        )
        self._run(h.handle_round())
        h.client.send_combat_spell.assert_awaited()
        # willcast decrements turn_adjust on success
        self.assertEqual(h._turn_adjust, -1)

    def test_aoe_target_resolves_to_falsy_when_no_enemies(self):
        # AOE used to resolve to None (which the click path treated as "no
        # member click"); the packet API now wants an enemy-team bitmask, so
        # _resolve_target returns False when there are no enemies — same
        # signal to "skip move", different value. Either falsy is fine.
        from src.combat.config import parse_config

        cfg = parse_config("any<damage> @ aoe").lines[0].moves[0]
        h = self._handler()
        target = self._run(h._resolve_target(cfg))
        self.assertFalse(target)

    def test_resolve_enemy_returns_false_when_empty(self):
        from src.combat.config import parse_config

        cfg = parse_config("Feint @ enemy").lines[0].moves[0]
        h = self._handler()  # no enemies in default member list
        target = self._run(h._resolve_target(cfg))
        self.assertIs(target, False)

    def test_resolve_self_returns_client_member(self):
        from src.combat.config import parse_config

        cfg = parse_config("Satyr @ self").lines[0].moves[0]
        h = self._handler()
        target = self._run(h._resolve_target(cfg))
        me = self._run(h.get_client_member())
        self.assertIs(target, me)

    def test_get_candidates_substring_fallback(self):
        from src.combat.config import MoveConfig

        h = self._handler(cards=[_make_card("Mass Assault"), _make_card("Wand Hit")])
        out = self._run(h._get_candidates(MoveConfig(spell="Mass")))
        self.assertEqual(len(out), 1)
        self.assertEqual(self._run(out[0].name()), "Mass Assault")

    def test_get_candidates_exact_match_preferred(self):
        from src.combat.config import MoveConfig

        h = self._handler(cards=[_make_card("Feint"), _make_card("Feint Treasure")])
        out = self._run(h._get_candidates(MoveConfig(spell="Feint")))
        self.assertEqual(len(out), 1)
        self.assertEqual(self._run(out[0].name()), "Feint")

    def test_card_count_falls_back_to_card_list(self):
        h = self._handler(cards=[_make_card("A"), _make_card("B")])
        # No CountText window → falls back to len(cards)
        hand, _total = self._run(h.get_card_counts())
        self.assertEqual(hand, 2)

    def test_card_count_parses_count_text(self):
        win = MagicMock()
        win.maybe_text = AsyncMock(return_value="header\n<center>4 of 28</center>")
        h = self._handler()
        h.client.root_window.get_windows_with_name = AsyncMock(return_value=[win])
        hand, total = self._run(h.get_card_counts())
        self.assertEqual(hand, 4)
        self.assertEqual(total, 28)

    def test_priority_iterates_until_success(self):
        # First two priorities should fail; third (pass) should succeed.
        h = self._handler(
            config_str="MissingA @ enemy | MissingB @ enemy | pass",
            members=[_make_member(player=True), _make_member(monster=True)],
        )
        self._run(h.handle_round())
        h.client.send_combat_pass.assert_awaited()

    def test_matches_card_by_display_name(self):
        # User playstyles use display names like "Super Dread", but card.name()
        # returns the internal template name "SuperDread". Must match either.
        super_dread = _make_card("SuperDread", display_name="Super Dread")
        enemy = _make_member(monster=True)
        h = self._handler(
            cards=[super_dread],
            members=[_make_member(player=True), enemy],
            config_str="Super Dread @ enemy",
        )
        self._run(h.handle_round())
        h.client.send_combat_spell.assert_awaited()

    def test_matches_card_by_display_name_substring(self):
        super_dread = _make_card("SuperDread", display_name="Super Dread")
        enemy = _make_member(monster=True)
        h = self._handler(
            cards=[super_dread],
            members=[_make_member(player=True), enemy],
            config_str="Dread @ enemy",
        )
        self._run(h.handle_round())
        h.client.send_combat_spell.assert_awaited()

    def test_enchant_applied_then_bare_cast(self):
        # Snack Attack[Epic]: handler sends send_combat_enchant, waits for the
        # enchant card to leave the hand, then sends send_combat_spell on the
        # now-enchanted card. We simulate the consume by mutating the hand
        # state inside the send_combat_enchant mock.
        snack = _make_card("SnackAttack", display_name="Snack Attack")
        epic = _make_card("Epic", display_name="Epic")
        fused = _make_card("EpicSnackAttack", display_name="Epic Snack Attack")
        enemy = _make_member(monster=True)

        cards_state = {"hand": [snack, epic]}
        h = self._handler(
            members=[_make_member(player=True), enemy],
            config_str="Snack Attack[Epic] @ enemy",
        )
        h.get_cards = AsyncMock(side_effect=lambda: list(cards_state["hand"]))

        async def _enchant_packet(e_idx, t_idx):
            # send_combat_enchant consumed Epic and rewrote Snack → fused.
            cards_state["hand"] = [fused]

        h.client.send_combat_enchant = AsyncMock(side_effect=_enchant_packet)

        self._run(h.handle_round())
        h.client.send_combat_enchant.assert_awaited()
        h.client.send_combat_spell.assert_awaited()

    def test_missing_enchant_falls_through_to_bare_cast(self):
        # "Snack Attack[Epic]" should still cast Snack Attack even if Epic
        # isn't in hand (was failing the entire move before).
        snack = _make_card("Snack Attack")
        enemy = _make_member(monster=True)
        h = self._handler(
            cards=[snack],
            members=[_make_member(player=True), enemy],
            config_str="Snack Attack[Epic] @ enemy",
        )
        self._run(h.handle_round())
        h.client.send_combat_enchant.assert_not_awaited()
        h.client.send_combat_spell.assert_awaited()

    def test_value_error_from_cast_triggers_retry(self):
        # send_combat_spell raising ValueError (e.g. transient memory read fail)
        # used to give up immediately. Now _cast_with_retry catches it and
        # retries once after re-finding the card and re-resolving the target.
        feint = _make_card("Feint")
        enemy = _make_member(monster=True)
        h = self._handler(
            cards=[feint],
            members=[_make_member(player=True), enemy],
            config_str="Feint @ enemy",
        )
        attempts = {"n": 0}

        async def _send(idx, sub):
            attempts["n"] += 1
            if attempts["n"] < 2:
                raise ValueError("transient memory read fail")

        h.client.send_combat_spell = AsyncMock(side_effect=_send)
        self._run(h.handle_round())
        self.assertEqual(h.client.send_combat_spell.await_count, 2)

    def test_live_config_swapped_mid_combat(self):
        # After construction, setting client.combat_config to a NEW CombatConfig
        # should be picked up on the next round (mid-combat playstyle change).
        from src.combat.config import parse_config

        feint = _make_card("Feint")
        enemy = _make_member(monster=True)
        h = self._handler(
            cards=[feint], members=[_make_member(player=True), enemy], config_str="pass"
        )
        # Swap config — the next handle_round must use it, not the original "pass"
        h.client.combat_config = parse_config("Feint @ enemy")
        self._run(h.handle_round())
        h.client.send_combat_spell.assert_awaited()

    def test_native_combat_registers_on_client(self):
        # Registration moved from __init__ to handle_combat acquisition.
        h = self._handler()
        self.assertIsNone(h.client._active_combat)

    def test_round_specific_overrides_general(self):
        feint = _make_card("Feint")
        h = self._handler(
            cards=[feint],
            members=[_make_member(player=True), _make_member(monster=True)],
            config_str="{1} Feint @ enemy | pass",
        )
        self._run(h.handle_round())
        h.client.send_combat_spell.assert_awaited()


class TestZoneGraph(unittest.TestCase):
    _map_path = None

    _gate_path = None

    @classmethod
    def setUpClass(cls):

        from pathlib import Path

        base = Path(__file__).parent.parent / "src" / "nav" / "data"

        cls._zones_path = base / "zones.txt"

    def _skip_if_missing(self, path):

        if not path.exists():
            self.skipTest(f"traversal data not found: {path}")

    def test_zone_graph_loads(self):

        self._skip_if_missing(self._zones_path)

        from src.nav.navigator import _load_zones

        g, _, _ = _load_zones(self._zones_path)

        self.assertGreater(len(g), 10)

    def test_gates_load(self):

        self._skip_if_missing(self._zones_path)

        from src.nav.navigator import _load_zones

        _, gates, _ = _load_zones(self._zones_path)

        self.assertGreater(len(gates), 10)

    def test_bfs_same_zone(self):

        from src.nav.navigator import _bfs_path

        g = {"A": ["B"], "B": []}

        self.assertEqual(_bfs_path(g, "A", "A"), ["A"])

    def test_bfs_adjacent(self):

        from src.nav.navigator import _bfs_path

        g = {"A": ["B"], "B": ["C"], "C": []}

        self.assertEqual(_bfs_path(g, "A", "B"), ["A", "B"])

    def test_bfs_two_hops(self):

        from src.nav.navigator import _bfs_path

        g = {"A": ["B"], "B": ["C"], "C": []}

        self.assertEqual(_bfs_path(g, "A", "C"), ["A", "B", "C"])

    def test_bfs_no_path(self):

        from src.nav.navigator import _bfs_path

        g = {"A": ["B"], "B": [], "C": []}

        self.assertIsNone(_bfs_path(g, "A", "C"))

    def test_bfs_undirected_reverse(self):

        from src.nav.navigator import _bfs_path

        g = {"A": ["B"], "B": [], "C": ["B"]}

        path = _bfs_path(g, "C", "A")

        self.assertIsNotNone(path)

        self.assertEqual(path[0], "C")

        self.assertEqual(path[-1], "A")


class TestLauncherMetadata(unittest.TestCase):
    def setUp(self):
        import tempfile, shutil
        from src import launcher

        self._launcher = launcher
        self._tmp = tempfile.mkdtemp(prefix="skyfall_meta_")
        self._orig_path = launcher._metadata_path
        from pathlib import Path as _P

        launcher._metadata_path = lambda: _P(self._tmp) / "account_metadata.json"
        self._cleanup_tmp = lambda: shutil.rmtree(self._tmp, ignore_errors=True)

    def tearDown(self):
        self._launcher._metadata_path = self._orig_path
        self._cleanup_tmp()

    def test_load_default_when_missing(self):
        m = self._launcher._load_meta()
        self.assertEqual(m["version"], 1)
        self.assertEqual(m["nicknames_order"], [])
        self.assertEqual(m["gid_map"], {})

    def test_save_and_reload(self):
        self._launcher._save_meta(
            {
                "version": 1,
                "nicknames_order": ["a", "b", "c"],
                "gid_map": {"a": 100, "b": 200},
            }
        )
        m = self._launcher._load_meta()
        self.assertEqual(m["nicknames_order"], ["a", "b", "c"])
        self.assertEqual(m["gid_map"], {"a": 100, "b": 200})

    def test_load_fills_missing_fields(self):
        # Hand-write a partial file (legacy / corrupt-ish)
        import json

        path = self._launcher._metadata_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"version": 1}))
        m = self._launcher._load_meta()
        self.assertEqual(m["nicknames_order"], [])
        self.assertEqual(m["gid_map"], {})

    def test_gid_round_trip(self):
        wl = self._launcher
        wl.update_player_gid("alice", 42)
        wl.update_player_gid("bob", 99)
        self.assertEqual(wl.get_player_gid("alice"), 42)
        self.assertEqual(wl.get_player_gid("bob"), 99)
        self.assertIsNone(wl.get_player_gid("nobody"))

    def test_gid_reverse_lookup(self):
        wl = self._launcher
        wl.update_player_gid("alice", 42)
        wl.update_player_gid("bob", 99)
        self.assertEqual(wl.get_nickname_by_gid(42), "alice")
        self.assertEqual(wl.get_nickname_by_gid(99), "bob")
        self.assertIsNone(wl.get_nickname_by_gid(1))

    def test_gid_overwrites(self):
        wl = self._launcher
        wl.update_player_gid("alice", 1)
        wl.update_player_gid("alice", 2)
        self.assertEqual(wl.get_player_gid("alice"), 2)
        self.assertIsNone(wl.get_nickname_by_gid(1))

    def test_reorder_accounts(self):
        wl = self._launcher
        wl._save_meta(
            {
                "version": 1,
                "nicknames_order": ["a", "b", "c"],
                "gid_map": {},
            }
        )
        wl.reorder_accounts(["c", "a", "b"])
        self.assertEqual(wl._load_meta()["nicknames_order"], ["c", "a", "b"])


class TestLauncherCredentials(unittest.TestCase):
    TEST_PREFIX = "__skyfall_test_"

    def setUp(self):
        from src import launcher

        self._launcher = launcher

    def tearDown(self):
        # Best-effort cleanup of any test creds left behind
        wl = self._launcher
        for nick in list(wl._cred_list()):
            if nick.startswith(self.TEST_PREFIX):
                try:
                    wl._cred_delete(nick)
                except Exception:
                    pass

    def _nick(self, suffix):
        return f"{self.TEST_PREFIX}{suffix}"

    def test_write_read_roundtrip(self):
        wl = self._launcher
        nick = self._nick("rt")
        wl._cred_write(nick, "alice", "p@ssw0rd!")
        u, p = wl._cred_read(nick)
        self.assertEqual(u, "alice")
        self.assertEqual(p, "p@ssw0rd!")

    def test_blob_is_raw_utf8(self):
        import ctypes, ctypes.wintypes as wt

        wl = self._launcher
        nick = self._nick("utf8")
        password = "naïve-π-密码"  # multi-byte utf-8
        wl._cred_write(nick, "u", password)

        adv = ctypes.WinDLL("advapi32", use_last_error=True)
        adv.CredReadW.argtypes = [
            wt.LPCWSTR,
            wt.DWORD,
            wt.DWORD,
            ctypes.POINTER(ctypes.POINTER(wl.CREDENTIALW)),
        ]
        adv.CredReadW.restype = wt.BOOL
        adv.CredFree.argtypes = [ctypes.c_void_p]

        pp = ctypes.POINTER(wl.CREDENTIALW)()
        ok = adv.CredReadW(f"SkyFall/account/{nick}", 1, 0, ctypes.byref(pp))
        self.assertTrue(ok)
        try:
            c = pp.contents
            size = c.CredentialBlobSize
            raw = bytes(
                ctypes.cast(
                    c.CredentialBlob,
                    ctypes.POINTER(ctypes.c_ubyte * size),
                ).contents
            )
            self.assertEqual(raw, password.encode("utf-8"))
        finally:
            adv.CredFree(pp)

    def test_has_account(self):
        wl = self._launcher
        nick = self._nick("has")
        self.assertFalse(wl._cred_has(nick))
        wl._cred_write(nick, "u", "p")
        self.assertTrue(wl._cred_has(nick))
        wl._cred_delete(nick)
        self.assertFalse(wl._cred_has(nick))

    def test_list_filters_to_prefix(self):
        import ctypes, ctypes.wintypes as wt

        wl = self._launcher
        nick = self._nick("list")
        wl._cred_write(nick, "u", "p")

        # Write an unrelated credential under a different target prefix
        OUTSIDE = "SkyFall_test_outside_target"
        cred = wl.CREDENTIALW()
        cred.Type = 1
        cred.TargetName = OUTSIDE
        cred.Persist = 2
        cred.UserName = "x"
        cred.CredentialBlobSize = 0
        cred.CredentialBlob = None
        adv = ctypes.WinDLL("advapi32", use_last_error=True)
        adv.CredWriteW.argtypes = [ctypes.POINTER(wl.CREDENTIALW), wt.DWORD]
        adv.CredWriteW.restype = wt.BOOL
        adv.CredDeleteW.argtypes = [wt.LPCWSTR, wt.DWORD, wt.DWORD]
        adv.CredDeleteW.restype = wt.BOOL
        adv.CredWriteW(ctypes.byref(cred), 0)
        try:
            listed = wl._cred_list()
            self.assertIn(nick, listed)
            self.assertNotIn(OUTSIDE, listed)
            for n in listed:
                self.assertFalse(n.startswith("SkyFall_test_outside"))
        finally:
            adv.CredDeleteW(OUTSIDE, 1, 0)

    def test_delete_account_clears_metadata_too(self):
        import tempfile, shutil
        from pathlib import Path as _P

        wl = self._launcher
        nick = self._nick("delmeta")

        tmp = tempfile.mkdtemp(prefix="skyfall_del_")
        orig = wl._metadata_path
        wl._metadata_path = lambda: _P(tmp) / "account_metadata.json"
        try:
            wl._cred_write(nick, "u", "p")
            wl._save_meta(
                {
                    "version": 1,
                    "nicknames_order": [nick, "other"],
                    "gid_map": {nick: 123, "other": 456},
                }
            )
            wl.delete_account(nick)
            m = wl._load_meta()
            self.assertNotIn(nick, m["nicknames_order"])
            self.assertNotIn(nick, m["gid_map"])
            self.assertIn("other", m["nicknames_order"])
            self.assertFalse(wl._cred_has(nick))
        finally:
            wl._metadata_path = orig
            shutil.rmtree(tmp, ignore_errors=True)

    def test_list_accounts_respects_metadata_order(self):
        import tempfile, shutil
        from pathlib import Path as _P

        wl = self._launcher
        a, b, c = self._nick("a"), self._nick("b"), self._nick("c")

        tmp = tempfile.mkdtemp(prefix="skyfall_ord_")
        orig = wl._metadata_path
        wl._metadata_path = lambda: _P(tmp) / "account_metadata.json"
        try:
            # Write in order a, b, c
            wl._cred_write(a, "u", "p")
            wl._cred_write(b, "u", "p")
            wl._cred_write(c, "u", "p")
            # But declare metadata order as c, a, b
            wl._save_meta(
                {
                    "version": 1,
                    "nicknames_order": [c, a, b],
                    "gid_map": {},
                }
            )
            listed = [n for n in wl.list_accounts() if n.startswith(self.TEST_PREFIX)]
            self.assertEqual(listed[:3], [c, a, b])
        finally:
            wl._metadata_path = orig
            shutil.rmtree(tmp, ignore_errors=True)
            for n in (a, b, c):
                try:
                    wl._cred_delete(n)
                except Exception:
                    pass


class TestLauncherInternals(unittest.TestCase):
    def test_login_pattern_tolerates_displacement_shift(self):
        # Regression: a client patch shifts the dispatcher's stack displacement
        # (the `lea rdx,[rbp-XX]` byte). The login pattern wildcards that byte
        # so the scan still locates the function regardless of which value the
        # build picks.
        from src.launcher import _LOGIN_PATTERN, _scan_wild

        self.assertIsNone(_LOGIN_PATTERN[9])  # displacement is wildcarded
        concrete = [b if b is not None else 0x00 for b in _LOGIN_PATTERN]

        for disp in (0xA7, 0x9F, 0x7B):
            body = bytes(concrete[:9]) + bytes([disp]) + bytes(concrete[10:])
            data = b"\x00\x00\x00" + body + b"\x00\x00"
            self.assertEqual(_scan_wild(data, _LOGIN_PATTERN), 3)

    def test_scan_wild_matches_with_wildcards(self):
        from src.launcher import _scan_wild

        data = b"\x11\x22\x48\x8b\x01\x33\x44\xff\x50\x70\x84"
        # Mirrors the real HOOK_PATTERN shape: wildcards around concrete bytes
        pattern = [None, None, 0x48, 0x8B, 0x01, None, None, 0xFF, 0x50, 0x70, 0x84]
        self.assertEqual(_scan_wild(data, pattern), 0)

    def test_scan_wild_returns_none_when_absent(self):
        from src.launcher import _scan_wild

        data = b"\x00" * 32
        self.assertIsNone(_scan_wild(data, [None, 0x48, 0x8B]))

    def test_scan_wild_skips_first_concrete_mismatches(self):
        from src.launcher import _scan_wild

        # Concrete byte is 0x48 at index 1 of pattern; data has it only at offset 5
        data = b"\x00\x99\x00\x00\x00\x00\x48\x8b\x01"
        pattern = [None, 0x48, 0x8B, 0x01]
        self.assertEqual(_scan_wild(data, pattern), 5)

    def test_string_struct_layout(self):
        import struct
        from src.launcher import _build_string_struct

        ss = _build_string_struct(0xCAFEBABE_DEADBEEF, 11)
        self.assertEqual(len(ss), 32)
        self.assertEqual(struct.unpack_from("<Q", ss, 0)[0], 0xCAFEBABE_DEADBEEF)
        self.assertEqual(struct.unpack_from("<Q", ss, 8)[0], 0)  # padding stays zero
        self.assertEqual(struct.unpack_from("<Q", ss, 16)[0], 11)  # length
        self.assertEqual(struct.unpack_from("<Q", ss, 24)[0], 11)  # capacity

    def test_login_bytecode_well_formed(self):
        import struct
        from src.launcher import _build_login_bytecode

        # block_addr and ret_addr must be within ±2 GB (rel32 range) — that's
        # what alloc_near guarantees in production. Use addresses 0x1000 apart.
        block_addr = 0x7FFF_0000_1000
        ret_addr = 0x7FFF_0000_2000
        flag_addr = 0x2_0000_0000_0000  # absolute moves, no range constraint
        ss_addr = 0x3_0000_0000_0000
        dat_addr = 0x4_0000_0000_0000
        func_addr = 0x5_0000_0000_0000
        orig = b"\xaa\xbb\xcc\xdd\xee\xff\x11"  # 7-byte original instr

        bc = _build_login_bytecode(
            block_addr,
            flag_addr,
            ss_addr,
            dat_addr,
            func_addr,
            orig,
            ret_addr,
        )

        # Header: push rax / mov rax, flag_addr / cmp byte [rax],1 / pop rax / jne rel32
        self.assertEqual(bc[0], 0x50)
        self.assertEqual(bc[1:3], b"\x48\xb8")
        self.assertEqual(struct.unpack_from("<Q", bc, 3)[0], flag_addr)
        self.assertEqual(bc[11:14], b"\x80\x38\x01")
        self.assertEqual(bc[14], 0x58)
        self.assertEqual(bc[15:17], b"\x0f\x85")

        # Verify jne offset lands on the original-instruction byte (after login body)
        skip_offset = struct.unpack_from("<i", bc, 17)[0]
        skip_target = 17 + 4 + skip_offset
        self.assertEqual(bc[skip_target : skip_target + 7], orig)

        # The 8-byte immediates we baked in should appear in the body
        self.assertIn(struct.pack("<Q", ss_addr), bytes(bc))
        self.assertIn(struct.pack("<Q", dat_addr), bytes(bc))
        self.assertIn(struct.pack("<Q", func_addr), bytes(bc))

        # Final 5 bytes: E9 + rel32 jump back to ret_addr
        self.assertEqual(bc[-5], 0xE9)
        rel = struct.unpack_from("<i", bc, len(bc) - 4)[0]
        jmp_from = block_addr + len(bc)  # rip after the jmp instruction
        self.assertEqual(jmp_from + rel, ret_addr)

    def test_login_bytecode_skip_branch_lands_on_orig(self):
        import struct
        from src.launcher import _build_login_bytecode

        orig = b"\x90" * 7
        bc = _build_login_bytecode(
            0x1000,
            0x2000,
            0x3000,
            0x4000,
            0x5000,
            orig,
            0x6000,
        )
        skip_offset = struct.unpack_from("<i", bc, 17)[0]
        skip_target = 17 + 4 + skip_offset
        # After skipping, next 7 bytes are the original instr, then the E9 jmp
        self.assertEqual(bc[skip_target : skip_target + 7], orig)
        self.assertEqual(bc[skip_target + 7], 0xE9)


if __name__ == "__main__":
    unittest.main()
