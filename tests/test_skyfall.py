import asyncio

import time

import unittest

from unittest.mock import AsyncMock, MagicMock, patch


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

    def test_sandbox_blocks_python_eval(self):

        import lupa.lua55 as lua

        rt = self._bridge()._build_runtime()

        with self.assertRaises(lua.LuaError):
            rt.execute("python.eval('1')")

    def test_sandbox_blocks_python_builtins(self):

        import lupa.lua55 as lua

        rt = self._bridge()._build_runtime()

        with self.assertRaises(lua.LuaError):
            rt.execute("python.builtins.__import__('os')")

    def test_sandbox_blocks_dunder_walk_on_registered_callable(self):

        import lupa.lua55 as lua

        bridge = self._bridge()

        def harmless():
            return 1

        bridge.register("harmless", harmless, is_async=False)
        rt = bridge._build_runtime()

        for expr in (
            "return harmless.__globals__",
            "return harmless.__class__",
            "return harmless.__init__",
        ):
            with self.assertRaises((lua.LuaError, AttributeError), msg=expr):
                rt.execute(expr)

    def test_sandbox_blocks_dunder_walk_on_registered_object(self):

        import lupa.lua55 as lua

        bridge = self._bridge()

        class Holder:
            def public(self):
                return 1

        bridge.register("holder", Holder(), is_async=False)
        rt = bridge._build_runtime()

        with self.assertRaises((lua.LuaError, AttributeError)):
            rt.execute("return holder.__class__")

        # public access still works
        self.assertEqual(rt.execute("return holder:public()"), 1)

    def test_sleep_available(self):

        self._bridge()._build_runtime().execute("sleep(0.01)")

    def test_stop_interrupts_sleep(self):

        from src.lang.bridge import ScriptError

        bridge = self._bridge()

        bridge._stop.set()

        with self.assertRaises(ScriptError):
            bridge._build_runtime().execute("sleep(10)")

    def test_error_callback_fired(self):

        import tempfile
        import os

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

        import tempfile
        import os

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

    def test_toggle_cleanup_runs_when_script_ends(self):
        # A toggle the script switched on is torn down when the script ends.
        import threading
        from src.lang.bridge import LuaBridge

        loop = asyncio.new_event_loop()
        t = threading.Thread(target=loop.run_forever, daemon=True)
        t.start()
        try:
            bridge = LuaBridge(loop)
            ran = []

            def arm():
                async def _teardown():
                    ran.append("torn-down")

                bridge.register_toggle_cleanup("combat", _teardown)

            bridge.register("arm", arm, is_async=False)
            bridge.run("arm()")

            for _ in range(200):
                if not bridge.running:
                    break
                time.sleep(0.02)

            self.assertFalse(bridge.running)
            self.assertEqual(ran, ["torn-down"])
        finally:
            loop.call_soon_threadsafe(loop.stop)

    def test_toggle_cleanup_skipped_when_script_disables_it(self):
        # A toggle the script switched on and back off again is NOT torn down
        # a second time at script end.
        import threading
        from src.lang.bridge import LuaBridge

        loop = asyncio.new_event_loop()
        t = threading.Thread(target=loop.run_forever, daemon=True)
        t.start()
        try:
            bridge = LuaBridge(loop)
            ran = []

            def arm():
                async def _teardown():
                    ran.append("torn-down")

                bridge.register_toggle_cleanup("combat", _teardown)

            def disarm():
                bridge.unregister_toggle_cleanup("combat")

            bridge.register("arm", arm, is_async=False)
            bridge.register("disarm", disarm, is_async=False)
            bridge.run("arm(); disarm()")

            for _ in range(200):
                if not bridge.running:
                    break
                time.sleep(0.02)

            self.assertFalse(bridge.running)
            self.assertEqual(ran, [])
        finally:
            loop.call_soon_threadsafe(loop.stop)

    def test_clean_error_strips_prefix(self):

        from src.lang.bridge import _clean_error

        self.assertEqual(_clean_error('[string "..."]:42: bad call'), "42: bad call")

    def test_clean_error_passthrough(self):

        from src.lang.bridge import _clean_error

        self.assertEqual(_clean_error("plain error"), "plain error")


class TestScriptToggleTeardown(unittest.TestCase):
    def _client(self):
        import threading
        from unittest.mock import MagicMock
        from src.lang.client import LuaClient

        calls = {"register": [], "unregister": []}

        class FakeBridge:
            def register_toggle_cleanup(self, key, factory):
                calls["register"].append((key, factory))

            def unregister_toggle_cleanup(self, key):
                calls["unregister"].append(key)

        ww = MagicMock()
        ww.title = "p1"
        ww._active_combat = None
        ww._playstyle_config = "ps"
        ww._lua_combat_task = None
        ww._lua_dialog_task = None

        # Close the spawn coroutine without running it (no live loop here).
        def call(coro):
            close = getattr(coro, "close", None)
            if close is not None:
                close()
            return None

        c = LuaClient(ww, call, threading.Event(), lambda v: v, FakeBridge())
        return c, calls

    def test_enable_combat_arms_teardown(self):
        c, calls = self._client()
        c.enable_combat()
        self.assertEqual(len(calls["register"]), 1)
        key, factory = calls["register"][0]
        self.assertEqual(key, (id(c._c), "combat"))
        coro = factory()
        self.assertTrue(asyncio.iscoroutine(coro))
        coro.close()

    def test_disable_combat_disarms_teardown(self):
        c, calls = self._client()
        c.disable_combat()
        self.assertIn((id(c._c), "combat"), calls["unregister"])

    def test_enable_dialog_arms_teardown(self):
        c, calls = self._client()
        c.enable_dialog()
        self.assertEqual(len(calls["register"]), 1)
        key, factory = calls["register"][0]
        self.assertEqual(key, (id(c._c), "dialog"))
        factory().close()

    def test_disable_dialog_disarms_teardown(self):
        c, calls = self._client()
        c.disable_dialog()
        self.assertIn((id(c._c), "dialog"), calls["unregister"])

    def test_no_bridge_is_a_noop(self):
        # Constructed without a bridge (unit tests / standalone): no crash.
        import threading
        from unittest.mock import MagicMock
        from src.lang.client import LuaClient

        ww = MagicMock()
        ww.title = "p1"
        ww._active_combat = None
        ww._playstyle_config = "ps"
        ww._lua_combat_task = None
        ww._lua_dialog_task = None
        c = LuaClient(
            ww,
            lambda coro: getattr(coro, "close", lambda: None)(),
            threading.Event(),
            lambda v: v,
        )
        c.enable_combat()
        c.disable_combat()
        c.enable_dialog()
        c.disable_dialog()


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

    def test_petcast_quoted(self):
        m = self.p('petcast "Bat Cat" @ enemy').lines[0].moves[0]
        self.assertEqual(m.petcast_spell, "Bat Cat")
        self.assertEqual(m.target, "enemy")

    def test_petcast_unquoted(self):
        m = self.p("petcast Batcat @ enemy").lines[0].moves[0]
        self.assertEqual(m.petcast_spell, "Batcat")
        self.assertEqual(m.target, "enemy")

    def test_petcast_default_target(self):
        m = self.p("petcast Batcat").lines[0].moves[0]
        self.assertEqual(m.petcast_spell, "Batcat")
        self.assertEqual(m.target, "enemy")

    def test_petcast_self_target(self):
        m = self.p("petcast Sprite @ self").lines[0].moves[0]
        self.assertEqual(m.petcast_spell, "Sprite")
        self.assertEqual(m.target, "self")

    def test_petcast_conditional(self):
        m = self.p("?(self.health < 50%) petcast Sprite @ self").lines[0].moves[0]
        self.assertEqual(m.petcast_spell, "Sprite")
        self.assertIsNotNone(m.condition)

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

    def test_focus_directive_colon(self):
        cfg = self.p("focus: storm | Feint @ enemy | pass")
        self.assertEqual(cfg.focus_school, "storm")
        # The directive does not count as a priority line.
        self.assertEqual(len(cfg.lines), 2)

    def test_focus_directive_equals_caseinsensitive(self):
        cfg = self.p("FOCUS = Fire | pass")
        self.assertEqual(cfg.focus_school, "fire")
        self.assertEqual(len(cfg.lines), 1)

    def test_focus_directive_absent(self):
        cfg = self.p("Feint @ enemy")
        self.assertIsNone(cfg.focus_school)

    def test_focus_move_conditional(self):
        # `?(...) focus: <school>` parses as a move, not the static directive.
        cfg = self.p("?(round == 1) focus: storm | Feint @ enemy")
        self.assertIsNone(cfg.focus_school)  # static unchanged
        self.assertEqual(len(cfg.lines), 2)
        focus_move = cfg.lines[0].moves[0]
        self.assertEqual(focus_move.set_focus, "storm")
        self.assertIsNotNone(focus_move.condition)

    def test_focus_move_in_ampersand_chain(self):
        line = self.p("setfocus fire & Tempest[Colossal] @ enemy").lines[0]
        self.assertEqual(len(line.moves), 2)
        self.assertEqual(line.moves[0].set_focus, "fire")
        self.assertEqual(line.moves[1].spell, "Tempest")
        self.assertEqual(line.moves[1].enchant, "Colossal")

    def test_focus_move_whitespace_separator(self):
        # `focus storm` (no colon/equals) should still parse as a focus move
        # when used with a condition (so the static-directive branch is skipped).
        m = self.p("?(round >= 2) focus storm").lines[0].moves[0]
        self.assertEqual(m.set_focus, "storm")

    def test_focus_move_rejects_no_separator(self):
        # `focusstorm` should NOT be parsed as a focus move.
        m = self.p("?(round == 1) focusstorm").lines[0].moves[0]
        self.assertIsNone(m.set_focus)

    def test_condition_with_lt_does_not_eat_pipes(self):
        # Regression: pre-existing bug where `<` in a condition pinned
        # bracket depth, silently collapsing multi-line playstyles into one.
        cfg = self.p("?(self.health < 25%) Satyr @ self | pass")
        self.assertEqual(len(cfg.lines), 2)
        self.assertEqual(cfg.lines[0].moves[0].spell, "Satyr")
        self.assertTrue(cfg.lines[1].moves[0].is_pass)

    def test_condition_with_gt_does_not_eat_ampersands(self):
        # Same regression on the & axis.
        line = self.p("?(self.health > 50) Feint @ enemy & Satyr @ self").lines[0]
        self.assertEqual(len(line.moves), 2)
        self.assertEqual(line.moves[0].spell, "Feint")
        self.assertEqual(line.moves[1].spell, "Satyr")

    def test_dynamic_focus_with_condition_and_pipes(self):
        cfg = self.p("?(self.health < 50%) focus: life | Satyr @ self | pass")
        self.assertEqual(len(cfg.lines), 3)
        self.assertEqual(cfg.lines[0].moves[0].set_focus, "life")
        self.assertIsNotNone(cfg.lines[0].moves[0].condition)
        self.assertEqual(cfg.lines[1].moves[0].spell, "Satyr")
        self.assertTrue(cfg.lines[2].moves[0].is_pass)

    def test_static_focus_position_independent(self):
        # The static directive can appear anywhere in the pipe stream.
        for text in (
            "focus: storm | Feint @ enemy | pass",
            "Feint @ enemy | focus: storm | pass",
            "Feint @ enemy | pass | focus: storm",
        ):
            cfg = self.p(text)
            self.assertEqual(cfg.focus_school, "storm", text)
            self.assertEqual(len(cfg.lines), 2, text)

    def test_static_focus_last_wins(self):
        # When multiple static directives appear, the latest one wins.
        cfg = self.p("focus: fire | focus: ice | pass")
        self.assertEqual(cfg.focus_school, "ice")

    def test_focus_move_in_round_block(self):
        # {N} round-specific lines should also accept focus moves.
        cfg = self.p("{1} focus: storm | Feint @ enemy")
        self.assertIn(1, cfg.round_map)
        self.assertEqual(cfg.round_map[1][0].moves[0].set_focus, "storm")

    def test_pip_directive_static(self):
        cfg = self.p("pip: storm | Feint @ enemy | pass")
        self.assertEqual(cfg.pip_school, "storm")
        self.assertEqual(len(cfg.lines), 2)

    def test_pip_directive_setpip_alias(self):
        cfg = self.p("setpip: fire | pass")
        self.assertEqual(cfg.pip_school, "fire")

    def test_pip_move_conditional(self):
        cfg = self.p("?(round == 1) pip: storm | Feint @ enemy")
        self.assertIsNone(cfg.pip_school)  # static unchanged
        self.assertEqual(len(cfg.lines), 2)
        self.assertEqual(cfg.lines[0].moves[0].set_pip, "storm")
        self.assertIsNotNone(cfg.lines[0].moves[0].condition)

    def test_pip_move_chain(self):
        line = self.p("setpip storm & Tempest @ enemy").lines[0]
        self.assertEqual(line.moves[0].set_pip, "storm")
        self.assertEqual(line.moves[1].spell, "Tempest")

    def test_pip_and_focus_coexist(self):
        cfg = self.p("focus: storm | pip: fire | pass")
        self.assertEqual(cfg.focus_school, "storm")
        self.assertEqual(cfg.pip_school, "fire")
        self.assertEqual(len(cfg.lines), 1)

    def test_school_names_resolve_in_wizwalker(self):
        # Every school the Lua API advertises must round-trip through
        # wizwalker's school_id_to_names map — otherwise set_focus_school
        # and the dynamic focus move would silently log-and-skip.
        from wizwalker.memory.memory_objects.conditionals import (
            school_id_to_names,
        )

        lowered = {k.lower() for k in school_id_to_names}
        for school in (
            "fire",
            "ice",
            "storm",
            "myth",
            "life",
            "death",
            "balance",
            "shadow",
        ):
            self.assertIn(school, lowered, f"missing: {school}")

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


class TestLuaTableConfig(unittest.TestCase):
    def p(self, tbl):
        from src.combat.config import parse_lua_table

        return parse_lua_table(tbl)

    def test_focus_key_only(self):
        cfg = self.p({"focus": "ice"})
        self.assertEqual(cfg.focus_school, "ice")
        self.assertEqual(cfg.lines, [])

    def test_focus_key_with_lines(self):
        # Plain dict stands in for a Lua table — both expose .items().
        cfg = self.p({"focus": "Storm", 1: "Feint @ enemy", 2: "pass"})
        self.assertEqual(cfg.focus_school, "storm")  # lowercased
        # Two string-valued numeric keys → two priority lines.
        self.assertEqual(len(cfg.lines), 2)

    def test_focus_key_case_insensitive(self):
        cfg = self.p({"FOCUS": "fire"})
        self.assertEqual(cfg.focus_school, "fire")

    def test_focus_key_empty_string_ignored(self):
        # Empty / whitespace-only focus shouldn't become a focus_school value.
        cfg = self.p({"focus": "   "})
        self.assertIsNone(cfg.focus_school)

    def test_pip_key(self):
        cfg = self.p({"pip": "Storm", 1: "Feint @ enemy"})
        self.assertEqual(cfg.pip_school, "storm")
        self.assertEqual(len(cfg.lines), 1)

    def test_pip_key_empty_string_ignored(self):
        cfg = self.p({"pip": ""})
        self.assertIsNone(cfg.pip_school)


class TestLuaClientSchoolValidation(unittest.TestCase):
    def _client(self):
        from src.lang.client import LuaClient

        # _call should NOT be invoked for the invalid-input cases below.
        # If it is, the test will fail with a clear assertion message.
        call = MagicMock(side_effect=AssertionError("_call must not run"))
        return LuaClient(
            client=MagicMock(),
            call=call,
            stop=MagicMock(),
            table_from=lambda v: v,
        )

    def test_set_focus_school_rejects_unknown(self):
        from src.lang.bridge import ScriptError

        c = self._client()
        with self.assertRaises(ScriptError):
            c.set_focus_school("plaid")

    def test_set_pip_school_rejects_unknown(self):
        from src.lang.bridge import ScriptError

        c = self._client()
        with self.assertRaises(ScriptError):
            c.set_pip_school("plaid")

    def test_set_pip_school_rejects_shadow(self):
        # SchoolPipPanel only has the 7 base schools — shadow isn't there.
        from src.lang.bridge import ScriptError

        c = self._client()
        with self.assertRaises(ScriptError):
            c.set_pip_school("shadow")

    def test_set_focus_school_accepts_canonical_schools(self):
        # Doesn't reach _call because we never actually run combat; we
        # just want to know the name passes validation. Swap _call to a
        # no-op for this test.
        from src.lang.client import LuaClient

        c = LuaClient(
            client=MagicMock(),
            call=lambda *_args, **_kw: None,
            stop=MagicMock(),
            table_from=lambda v: v,
        )
        # Should not raise for any of these.
        for s in ("fire", "Ice", "STORM", "myth", "life", "death", "balance", "shadow"):
            c.set_focus_school(s)


class TestLuaClientInteract(unittest.TestCase):
    def _client(self):
        from src.lang.client import LuaClient

        c = MagicMock()
        c.send_key = AsyncMock()
        lc = LuaClient(
            client=c,
            call=lambda coro: asyncio.get_event_loop().run_until_complete(coro),
            stop=MagicMock(),
            table_from=lambda v: v,
        )
        lc._stop.is_set = MagicMock(return_value=False)
        return lc, c

    def test_presses_x_and_awaits_dialog(self):
        from wizwalker import Keycode
        from src.paths import npc_range_path, advance_dialog_path

        lc, c = self._client()

        async def visible(_client, path):
            return path in (npc_range_path, advance_dialog_path)

        async def free(_client):
            return True

        with (
            patch("src.lang.client._main.is_visible_by_path", new=visible),
            patch("src.lang.client._main.is_free", new=free),
        ):
            result = lc.interact(window=2)

        self.assertTrue(result)
        c.send_key.assert_awaited_once_with(Keycode.X, 0.1)

    def test_blocks_until_dialog_clears(self):
        # await_dialog (default) must hold the thread until the client is free
        # again — not return the instant the dialog box appears.
        from src.paths import npc_range_path, advance_dialog_path

        lc, c = self._client()

        async def visible(_client, path):
            return path in (npc_range_path, advance_dialog_path)

        polls = {"n": 0}

        async def free(_client):
            polls["n"] += 1
            return polls["n"] >= 3  # busy for the first two polls, then free

        with (
            patch("src.lang.client._main.is_visible_by_path", new=visible),
            patch("src.lang.client._main.is_free", new=free),
        ):
            result = lc.interact(window=2)

        self.assertTrue(result)
        self.assertGreaterEqual(polls["n"], 3)  # kept polling until free

    def test_returns_false_and_skips_x_when_no_popup(self):
        lc, c = self._client()

        async def invisible(_client, _path):
            return False

        with patch("src.lang.client._main.is_visible_by_path", new=invisible):
            result = lc.interact(window=0.15)

        self.assertFalse(result)
        c.send_key.assert_not_awaited()


class TestLuaClientQuestInZone(unittest.TestCase):
    def _client(self):
        from src.lang.client import LuaClient

        lc = LuaClient(
            client=MagicMock(),
            call=lambda coro: asyncio.get_event_loop().run_until_complete(coro),
            stop=MagicMock(),
            table_from=lambda v: v,
        )
        lc._stop.is_set = MagicMock(return_value=False)
        return lc

    def test_true_returns_immediately(self):
        lc = self._client()

        async def dz(_c):
            return "Grizzleheim/Interiors/GH_RedClaw_T1"

        with patch("src.lang.client._main.quest_destination_zone_of", new=dz):
            self.assertTrue(lc.quest_in_zone("Grizzleheim/Interiors"))

    def test_transient_empty_then_recovers(self):
        lc = self._client()
        reads = {"n": 0}

        async def dz(_c):
            reads["n"] += 1
            return "" if reads["n"] == 1 else "Grizzleheim/Interiors/GH_RedClaw_T1"

        with patch("src.lang.client._main.quest_destination_zone_of", new=dz):
            self.assertTrue(lc.quest_in_zone("Grizzleheim/Interiors", 0.5))
        self.assertGreaterEqual(reads["n"], 2)  # re-checked after the empty read

    def test_persistent_out_of_zone_returns_false(self):
        lc = self._client()

        async def dz(_c):
            return ""

        with patch("src.lang.client._main.quest_destination_zone_of", new=dz):
            self.assertFalse(lc.quest_in_zone("Grizzleheim/Interiors", 0.2))


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

    def _entity(
        self, obj_name="", disp_name="", x=0.0, gid=0, tid=0, is_boss=False, is_mob=True
    ):
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

        # waitfor_mob filters via search_behavior_by_name("NPCBehavior") +
        # is_mob byte at offset 288. Make every test entity qualify by default
        # so old tests keep working; pass is_mob=False to simulate scenery.
        if is_mob:
            beh_inst = MagicMock()
            beh_inst.read_value_from_offset = AsyncMock(return_value=True)
            e.search_behavior_by_name = AsyncMock(return_value=beh_inst)
        else:
            e.search_behavior_by_name = AsyncMock(return_value=None)

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

        def call(coro):
            return (
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


_NEXT_CARD_ADDR = [0x10000]


def _make_card(
    name, castable=True, enchanted=False, item=False, cloaked=False, display_name=None
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
    # Packet-based combat looks up hand_index by spell_window.base_address
    # (legacy fallback path) and by template_id (post-enchant re-resolution
    # in _enchant_and_cast). Give every mock card both, deterministically.
    spell_window = MagicMock()
    spell_window.base_address = _NEXT_CARD_ADDR[0]
    c.template_id = AsyncMock(return_value=_NEXT_CARD_ADDR[0])
    _NEXT_CARD_ADDR[0] += 0x100
    c._spell_window = spell_window
    # get_graphical_spell chain used by _card_names fast path (avoids 2s timeout).
    _tpl = MagicMock()
    _tpl.name = AsyncMock(return_value=name)
    _tpl.display_name = AsyncMock(return_value=display_name or name)
    _gs = MagicMock()
    _gs.spell_template = AsyncMock(return_value=_tpl)
    c.get_graphical_spell = AsyncMock(return_value=_gs)
    # cache_handler.get_langcode_name resolves a lang code → display string.
    # In tests the "code" is already the display name, so pass it through.
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
    # Subcircle index used by packet API. 4–7 = enemy team, 0–3 = ally team.
    part.subcircle = AsyncMock(return_value=4 if monster else 0)
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
        # NativeCombat acquires _active_combat at handle_combat entry now;
        # MagicMock would otherwise auto-create the attribute and trip the
        # ownership-wait loop. Explicit None makes the gate fall through.
        client._active_combat = None

        h = NativeCombat(client, cast_time=0)

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

        # Packet shims — translate client.send_combat_* into the per-card
        # mocks the existing tests assert against (card.cast / card.discard).
        async def _send_spell(hand_index, target):
            current = await h.get_cards()
            if 0 <= int(hand_index) < len(current):
                card = current[int(hand_index)]
                # Best-effort target reconstruction for cast() shim.
                tgt = None
                if 0 < int(target) < 16:
                    for m in await h.get_members():
                        try:
                            part = await m.get_participant()
                            if await part.subcircle() == int(target):
                                tgt = m
                                break
                        except Exception:
                            pass
                await card.cast(tgt, sleep_time=0)

        async def _send_enchant(enchant_index, target_index):
            current = await h.get_cards()
            if 0 <= int(enchant_index) < len(current) and 0 <= int(target_index) < len(
                current
            ):
                enchant = current[int(enchant_index)]
                target_card = current[int(target_index)]
                await enchant.cast(target_card, sleep_time=0)

        async def _send_discard(hand_index):
            current = await h.get_cards()
            if 0 <= int(hand_index) < len(current):
                await current[int(hand_index)].discard()

        async def _send_pass():
            await h.pass_button()

        async def _send_draw():
            await h.draw_button()

        client.send_combat_spell = AsyncMock(side_effect=_send_spell)
        client.send_combat_pass = AsyncMock(side_effect=_send_pass)
        client.send_combat_flee = AsyncMock()
        client.send_combat_enchant = AsyncMock(side_effect=_send_enchant)
        client.send_combat_discard = AsyncMock(side_effect=_send_discard)
        client.send_combat_draw = AsyncMock(side_effect=_send_draw)
        client.send_combat_fusion = AsyncMock()
        client.send_pet_willcast = AsyncMock()
        return h

    def test_no_config_passes(self):
        h = self._handler()
        self._run(h.handle_round())
        h.pass_button.assert_awaited()

    def test_stunned_passes_and_decrements_turn(self):
        h = self._handler(config_str="Feint @ enemy", stunned=True)
        self._run(h.handle_round())
        h.pass_button.assert_awaited()
        self.assertEqual(h._turn_adjust, -1)

    def test_named_spell_exact_match_casts(self):
        feint = _make_card("Feint")
        enemy = _make_member(monster=True, name="Goblin")
        h = self._handler(
            cards=[feint],
            members=[_make_member(player=True), enemy],
            config_str="Feint @ enemy",
        )

        # Simulate cast consuming the card so fizzle-detection sees count drop
        async def _cast(*a, **kw):
            h.get_cards.return_value = []

        feint.cast = AsyncMock(side_effect=_cast)
        self._run(h.handle_round())
        feint.cast.assert_awaited()
        h.pass_button.assert_not_awaited()

    def test_named_spell_substring_fallback_casts(self):
        # Config says "Mass" — no exact card, but "Mass Hit" matches via substring
        mass_hit = _make_card("Mass Hit")
        enemy = _make_member(monster=True)
        h = self._handler(
            cards=[mass_hit],
            members=[_make_member(player=True), enemy],
            config_str="Mass @ enemy",
        )

        async def _cast(*a, **kw):
            h.get_cards.return_value = []

        mass_hit.cast = AsyncMock(side_effect=_cast)
        self._run(h.handle_round())
        mass_hit.cast.assert_awaited()

    def test_no_enemy_means_move_fails_not_cast(self):
        # enemy target with no enemies present must NOT cast (was casting on None=AOE before fix)
        feint = _make_card("Feint")
        h = self._handler(
            cards=[feint],
            members=[_make_member(player=True)],
            config_str="Feint @ enemy | pass",
        )
        self._run(h.handle_round())
        feint.cast.assert_not_awaited()
        h.pass_button.assert_awaited()

    def test_priority_falls_through_to_pass(self):
        # No matching card for "NoSuchSpell" → falls through to bare "pass"
        enemy = _make_member(monster=True)
        h = self._handler(
            cards=[_make_card("Other")],
            members=[_make_member(player=True), enemy],
            config_str="NoSuchSpell @ enemy | pass",
        )
        self._run(h.handle_round())
        h.pass_button.assert_awaited()

    def test_willcast_with_target_recognized(self):
        # "Willcast @ enemy" must parse as is_willcast (was being parsed as a spell named "Willcast")
        item_card = _make_card("Potion", item=True)
        enemy = _make_member(monster=True)
        h = self._handler(
            cards=[item_card],
            members=[_make_member(player=True), enemy],
            config_str="Willcast @ enemy",
        )
        self._run(h.handle_round())
        item_card.cast.assert_awaited()
        # willcast decrements turn_adjust on success
        self.assertEqual(h._turn_adjust, -1)

    def test_aoe_target_resolves_to_enemy_list_for_bitmask(self):
        # aoe target must yield a pure-enemy list so _subcircle_of returns
        # the AOE bitmask. Empty enemy list still falls through to False.
        from src.combat.config import parse_config

        cfg = parse_config("any<damage> @ aoe").lines[0].moves[0]
        enemy = _make_member(monster=True)
        h = self._handler(members=[_make_member(player=True), enemy])
        target = self._run(h._resolve_target(cfg))
        self.assertEqual(target, [enemy])

    def test_resolve_enemy_returns_false_when_empty(self):
        from src.combat.config import parse_config

        cfg = parse_config("Feint @ enemy").lines[0].moves[0]
        h = self._handler()  # no enemies in default member list
        target = self._run(h._resolve_target(cfg))
        self.assertIs(target, False)

    def test_resolve_self_returns_client_member(self):
        from src.combat.config import parse_config

        cfg = parse_config("Satyr @ self").lines[0].moves[0]
        client_member = _make_member(player=True, name="Me")
        h = self._handler(members=[client_member])
        target = self._run(h._resolve_target(cfg))
        # @ self must resolve to the caster's own member so _subcircle_of
        # encodes the caster's subcircle bit — returning None sends raw 0
        # ("no target"), which the server rejects (enchant applies, cast drops).
        self.assertIs(target, client_member)

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

    def test_get_candidates_uses_visible_hand_when_castable_state_lags(self):
        from src.combat.config import MoveConfig

        dark_pact = _make_card("Dark Pact", display_name="Dark Tribute")
        h = self._handler(cards=[dark_pact])
        h.get_castable_cards = AsyncMock(return_value=[])

        with patch("src.combat.handler.asyncio.sleep", new=AsyncMock()):
            out = self._run(h._get_candidates(MoveConfig(spell="Dark Tribute")))

        self.assertEqual(out, [dark_pact])

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
        h.pass_button.assert_awaited()

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

        async def _cast(*a, **kw):
            h.get_cards.return_value = []

        super_dread.cast = AsyncMock(side_effect=_cast)
        self._run(h.handle_round())
        super_dread.cast.assert_awaited()

    def test_matches_card_by_display_name_substring(self):
        super_dread = _make_card("SuperDread", display_name="Super Dread")
        enemy = _make_member(monster=True)
        h = self._handler(
            cards=[super_dread],
            members=[_make_member(player=True), enemy],
            config_str="Dread @ enemy",
        )

        async def _cast(*a, **kw):
            h.get_cards.return_value = []

        super_dread.cast = AsyncMock(side_effect=_cast)
        self._run(h.handle_round())
        super_dread.cast.assert_awaited()

    def test_enchant_applied_then_bare_cast(self):
        # Snack Attack[Epic]: enchant is in hand → enchant is applied, then the
        # spell card (still in hand, now enchanted) is cast on the enemy. This
        # covers the case where the target keeps its template_id after the
        # enchant (post-enchant re-resolution finds it by tid). The companion
        # test below covers the case where the tid *changes*.
        snack = _make_card("SnackAttack", display_name="Snack Attack")
        epic = _make_card("Epic", display_name="Epic")
        enemy = _make_member(monster=True)

        cards_state = {"hand": [snack, epic]}
        h = self._handler(
            members=[_make_member(player=True), enemy],
            config_str="Snack Attack[Epic] @ enemy",
        )
        h.get_cards = AsyncMock(side_effect=lambda: list(cards_state["hand"]))

        async def _enchant_cast(target_card, **kw):
            # Enchant card consumed; target card stays in hand.
            cards_state["hand"] = [snack]

        epic.cast = AsyncMock(side_effect=_enchant_cast)

        async def _final_cast(*a, **kw):
            cards_state["hand"] = []

        snack.cast = AsyncMock(side_effect=_final_cast)

        self._run(h.handle_round())
        epic.cast.assert_awaited()  # enchant was applied
        snack.cast.assert_awaited()  # enchanted spell cast on enemy

    def test_enchant_changing_tid_still_casts_same_round(self):
        # Regression: applying an enchant rewrites the target's template_id
        # to its enchanted variant. _enchant_and_cast must not resolve the
        # post-enchant cast slot by the pre-enchant tid — doing so "loses" the
        # card, skips the cast, and defers it a whole round (observed live:
        # "sharpens round 1, casts round 2"). It now re-finds the enchanted
        # card from a fresh hand and casts it the SAME round.
        snack = _make_card("SnackAttack", display_name="Snack Attack")
        epic = _make_card("Epic", display_name="Epic")
        enchanted = _make_card(
            "SnackAttack", display_name="Snack Attack", enchanted=True
        )  # distinct template_id — the enchanted variant
        enemy = _make_member(monster=True)

        # Hand starts [snack(0), epic(1)]; the enchant consumes epic and
        # rewrites snack into `enchanted` (new tid) at slot 0.
        cards_state = {"hand": [snack, epic]}
        h = self._handler(
            members=[_make_member(player=True), enemy],
            config_str="Snack Attack[Epic] @ enemy",
        )
        h.get_cards = AsyncMock(side_effect=lambda: list(cards_state["hand"]))

        async def _apply_enchant(target_card, **kw):
            cards_state["hand"] = [enchanted]

        epic.cast = AsyncMock(side_effect=_apply_enchant)

        async def _final_cast(*a, **kw):
            cards_state["hand"] = []

        enchanted.cast = AsyncMock(side_effect=_final_cast)

        self._run(h.handle_round())
        epic.cast.assert_awaited()  # enchant applied
        enchanted.cast.assert_awaited()  # enchanted card cast the SAME round
        snack.cast.assert_not_awaited()  # pre-enchant object isn't what fires

    def test_enchant_cast_polls_through_mirror_lag(self):
        # "Sometimes it enchants but doesn't cast": right after the enchant the
        # hand mirror can lag, so the first re-find reads an empty hand. The
        # cast must POLL and fire once the mirror repopulates — not drop the
        # cast on the first miss.
        snack = _make_card("SnackAttack", display_name="Snack Attack")
        epic = _make_card("Epic", display_name="Epic")
        enchanted = _make_card(
            "SnackAttack", display_name="Snack Attack", enchanted=True
        )
        enemy = _make_member(monster=True)

        state = {"enchanted": False, "post_reads": 0}

        def _get_cards():
            if not state["enchanted"]:
                return [snack, epic]
            state["post_reads"] += 1
            # First read after the enchant is empty (mirror still repopulating);
            # the enchanted card shows up on the next read.
            return [] if state["post_reads"] <= 1 else [enchanted]

        h = self._handler(
            members=[_make_member(player=True), enemy],
            config_str="Snack Attack[Epic] @ enemy",
        )
        h.get_cards = AsyncMock(side_effect=_get_cards)

        async def _apply_enchant(target_card, **kw):
            state["enchanted"] = True

        epic.cast = AsyncMock(side_effect=_apply_enchant)
        enchanted.cast = AsyncMock()

        self._run(h.handle_round())
        epic.cast.assert_awaited()  # enchant applied
        enchanted.cast.assert_awaited()  # cast fired after the lag cleared
        snack.cast.assert_not_awaited()

    def test_enchant_then_vanished_card_falls_through_not_stall(self):
        # Anti-stall regression: if the target card is gone from hand after
        # the enchant (couldn't be re-found), _enchant_and_cast must report
        # failure so the round falls through to the next priority line. The
        # old code guessed a slot and reported success — but a wrong index is
        # silently rejected by the server, the turn never commits, and the
        # combat loop hangs forever in wait_until_next_round ("handling
        # combat… but doesn't do anything"). Here the fall-through line (Feint)
        # must cast so the round still advances.
        snack = _make_card("SnackAttack", display_name="Snack Attack")
        epic = _make_card("Epic", display_name="Epic")
        feint = _make_card("Feint")
        enemy = _make_member(monster=True)

        cards_state = {"hand": [snack, epic, feint]}
        h = self._handler(
            members=[_make_member(player=True), enemy],
            config_str="Snack Attack[Epic] @ enemy | Feint @ enemy",
        )
        h.get_cards = AsyncMock(side_effect=lambda: list(cards_state["hand"]))

        async def _apply_enchant(target_card, **kw):
            # Enchant consumed AND the target card vanished (e.g. fizzled
            # read / shuffled out) — only Feint remains.
            cards_state["hand"] = [feint]

        epic.cast = AsyncMock(side_effect=_apply_enchant)

        async def _feint_cast(*a, **kw):
            cards_state["hand"] = []

        feint.cast = AsyncMock(side_effect=_feint_cast)

        self._run(h.handle_round())
        epic.cast.assert_awaited()  # enchant was applied
        snack.cast.assert_not_awaited()  # enchant move did NOT falsely cast
        feint.cast.assert_awaited()  # round fell through and advanced

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

        async def _cast(*a, **kw):
            h.get_cards.return_value = []

        snack.cast = AsyncMock(side_effect=_cast)
        self._run(h.handle_round())
        snack.cast.assert_awaited()

    def test_value_error_from_cast_triggers_retry(self):
        # cast raising ValueError (e.g. health window not found) used to give up
        # immediately. Now it cancels the partial selection and retries.
        feint = _make_card("Feint")
        enemy = _make_member(monster=True)
        h = self._handler(
            cards=[feint],
            members=[_make_member(player=True), enemy],
            config_str="Feint @ enemy",
        )
        h.client.mouse_handler = MagicMock()
        h.client.mouse_handler.__aenter__ = AsyncMock(
            return_value=h.client.mouse_handler
        )
        h.client.mouse_handler.__aexit__ = AsyncMock(return_value=False)
        h.client.mouse_handler.click_window = AsyncMock()
        # First cast raises; second succeeds (consumes card)
        attempts = {"n": 0}

        async def _cast(*a, **kw):
            attempts["n"] += 1
            if attempts["n"] < 2:
                raise ValueError("no health window")
            h.get_cards.return_value = []

        feint.cast = AsyncMock(side_effect=_cast)
        self._run(h.handle_round())
        self.assertEqual(feint.cast.await_count, 2)

    def test_cast_succeeds_without_count_drop(self):
        # With packet-based planning, the server queues actions at phase end —
        # the hand UI does NOT update during planning.  A successful
        # send_combat_spell (no exception raised) is enough to declare success.
        feint = _make_card("Feint")
        enemy = _make_member(monster=True)
        h = self._handler(
            cards=[feint],
            members=[_make_member(player=True), enemy],
            config_str="Feint @ enemy",
        )
        self._run(h.handle_round())
        self.assertEqual(feint.cast.await_count, 1)
        h.pass_button.assert_not_awaited()

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

        async def _cast(*a, **kw):
            h.get_cards.return_value = []

        feint.cast = AsyncMock(side_effect=_cast)
        self._run(h.handle_round())
        feint.cast.assert_awaited()

    def test_native_combat_registers_on_client(self):
        # Registration moved from __init__ to handle_combat acquisition so
        # two concurrently-spawned handlers don't stomp each other (the
        # second overwriting the first as "active" while the first kept
        # running and sending duplicate packets). After handle_combat
        # finishes the slot is released again.
        from wizwalker.memory import DuelPhase

        h = self._handler()
        self.assertIsNone(h.client._active_combat)

        # Drive a single-iteration handle_combat to verify acquire+release.
        in_combat_calls = [0]

        async def _in_combat():
            in_combat_calls[0] += 1
            # On the first iteration, snapshot ownership for the assertion.
            if in_combat_calls[0] == 1:
                self.assertIs(h.client._active_combat, h)
            return in_combat_calls[0] == 1

        h.in_combat = AsyncMock(side_effect=_in_combat)
        h.wait_for_planning_phase = AsyncMock()
        h.wait_until_next_round = AsyncMock()
        h.round_number = AsyncMock(return_value=1)
        h.handle_round = AsyncMock()
        h.client.duel.duel_phase = AsyncMock(return_value=DuelPhase.planning)

        self._run(h.handle_combat())
        # Ownership released after exit.
        self.assertIsNone(h.client._active_combat)

    def test_round_specific_overrides_general(self):
        feint = _make_card("Feint")
        h = self._handler(
            cards=[feint],
            members=[_make_member(player=True), _make_member(monster=True)],
            config_str="{1} Feint @ enemy | pass",
        )

        async def _cast(*a, **kw):
            h.get_cards.return_value = []

        feint.cast = AsyncMock(side_effect=_cast)
        self._run(h.handle_round())
        feint.cast.assert_awaited()

    def test_hand_index_uses_participant_spell_list(self):
        from src.combat.handler import _hand_index_of

        # Build a fake participant chain whose spell_list places the wanted
        # template at index 2, while castable_cards (fallback) puts it at 0.
        h = self._handler()
        wanted_tid = 9001

        my_part = MagicMock()
        my_part.owner_id_full = AsyncMock(return_value="me")
        hand_obj = MagicMock()
        my_part.hand = AsyncMock(return_value=hand_obj)

        def _spell(tid):
            s = MagicMock()
            s.template_id = AsyncMock(return_value=tid)
            return s

        hand_obj.spell_list = AsyncMock(
            return_value=[_spell(1), _spell(2), _spell(wanted_tid), _spell(4)]
        )

        h.client.client_object.global_id_full = AsyncMock(return_value="me")
        h.client.duel.participant_list = AsyncMock(return_value=[my_part])

        # Card with the wanted template id; intentionally not present in
        # castable_cards so we know the participant path was used.
        card = _make_card("Whatever")
        card.template_id = AsyncMock(return_value=wanted_tid)

        idx = self._run(_hand_index_of(h, card))
        self.assertEqual(idx, 2)

    def test_hand_index_falls_back_when_participant_chain_missing(self):
        from src.combat.handler import _hand_index_of

        feint = _make_card("Feint")
        h = self._handler(cards=[_make_card("Other"), feint])
        # Make duel chain explicitly unavailable
        h.client.duel = MagicMock(side_effect=AttributeError)

        idx = self._run(_hand_index_of(h, feint))
        self.assertEqual(idx, 1)

    def test_cached_client_member_is_refreshed_when_invalidated(self):
        h = self._handler()

        stale_window = object()
        fresh_window = object()

        stale_member = MagicMock()
        stale_member.get_participant = AsyncMock(side_effect=RuntimeError("stale"))
        stale_member.is_client = AsyncMock(return_value=False)

        fresh_part = MagicMock()
        fresh_part.owner_id_full = AsyncMock(return_value="me")
        fresh_member = MagicMock()
        fresh_member.get_participant = AsyncMock(return_value=fresh_part)
        fresh_member.is_client = AsyncMock(return_value=True)

        h._member_windows = [stale_window]
        h._client_member_idx = 0
        h.get_members = type(h).get_members.__get__(h, type(h))
        h.client.root_window.get_windows_with_name = AsyncMock(
            return_value=[fresh_window]
        )

        def _member_factory(handler, window):
            return fresh_member if window is fresh_window else stale_member

        with patch("src.combat.handler.CombatMember", side_effect=_member_factory):
            member = self._run(type(h).get_client_member(h))

        self.assertIs(member, fresh_member)
        self.assertEqual(h._member_windows, [fresh_window])
        self.assertEqual(h._client_member_idx, 0)

    def test_get_enemies_refreshes_after_invalidated_member(self):
        from wizwalker.errors import MemoryInvalidated

        h = self._handler()
        stale = MagicMock()
        stale.is_dead = AsyncMock(side_effect=MemoryInvalidated())
        enemy = _make_member(monster=True, name="Goblin")

        h.get_members = AsyncMock(
            side_effect=[
                [stale],
                [_make_member(player=True, name="Me"), enemy],
            ]
        )

        enemies = self._run(h.get_enemies())

        self.assertEqual(enemies, [enemy])
        self.assertEqual(h.get_members.await_count, 2)

    def test_petcast_sends_willcast_packet(self):
        # petcast "Batcat" @ enemy must call send_pet_willcast with the spell
        # name and the enemy's subcircle bitmask.
        enemy = _make_member(monster=True)
        h = self._handler(
            members=[_make_member(player=True), enemy],
            config_str='petcast "Batcat" @ enemy',
        )
        self._run(h.handle_round())
        h.client.send_pet_willcast.assert_awaited_once()
        args = h.client.send_pet_willcast.call_args
        self.assertEqual(args[0][0], "Batcat")

    def test_petcast_no_enemy_does_not_send(self):
        # petcast with no valid enemy target must fail gracefully without
        # calling send_pet_willcast.
        h = self._handler(
            members=[_make_member(player=True)],
            config_str='petcast "Batcat" @ enemy',
        )
        self._run(h.handle_round())
        h.client.send_pet_willcast.assert_not_awaited()

    def test_petcast_conditional_skipped_when_false(self):
        # A conditional petcast must not fire when the condition is false.
        player = _make_member(player=True, health=80, max_health=100)
        h = self._handler(
            members=[player, _make_member(monster=True)],
            config_str="?(self.health < 50%) petcast Sprite @ self",
        )
        self._run(h.handle_round())
        h.client.send_pet_willcast.assert_not_awaited()

    # ── resilience: uncaught exceptions must never abort the combat loop ─────

    def test_gather_exception_sends_pass(self):
        # round_number() raising inside the _handle_round_inner gather must
        # send a pass rather than propagating out of handle_round().
        h = self._handler(config_str="Feint @ enemy")
        h.round_number = AsyncMock(side_effect=RuntimeError("mem read failed"))
        self._run(h.handle_round())
        h.pass_button.assert_awaited()

    def test_get_client_member_exception_sends_pass(self):
        # get_client_member() raising inside the gather must also send a pass.
        h = self._handler(config_str="Feint @ enemy")
        h.get_client_member = AsyncMock(side_effect=ValueError("no member"))
        self._run(h.handle_round())
        h.pass_button.assert_awaited()

    def test_is_stunned_exception_not_treated_as_stunned(self):
        # If is_stunned() raises, the round must continue normally (not pass).
        feint = _make_card("Feint")
        enemy = _make_member(monster=True)
        player = _make_member(player=True)
        player.is_stunned = AsyncMock(side_effect=RuntimeError("stun read failed"))
        h = self._handler(
            cards=[feint],
            members=[player, enemy],
            config_str="Feint @ enemy",
        )

        async def _cast(*a, **kw):
            h.get_cards.return_value = []

        feint.cast = AsyncMock(side_effect=_cast)
        self._run(h.handle_round())
        feint.cast.assert_awaited()

    def test_handle_round_exception_in_handle_combat_sends_pass(self):
        # handle_round() raising inside handle_combat must send a pass and
        # allow the loop to continue rather than aborting the session.
        from wizwalker.memory import DuelPhase

        h = self._handler()
        in_combat_calls = [0]

        async def _in_combat():
            in_combat_calls[0] += 1
            return in_combat_calls[0] == 1

        h.in_combat = AsyncMock(side_effect=_in_combat)
        h.wait_for_planning_phase = AsyncMock()
        h.wait_until_next_round = AsyncMock()
        h.round_number = AsyncMock(return_value=1)
        h.handle_round = AsyncMock(side_effect=RuntimeError("unexpected boom"))
        h.client.duel.duel_phase = AsyncMock(return_value=DuelPhase.planning)

        self._run(h.handle_combat())
        h.pass_button.assert_awaited()

    def test_wait_until_next_round_survives_round_number_exception(self):
        # If round_number() keeps raising, wait_until_next_round must keep
        # polling rather than propagating the exception.
        h = self._handler()
        h.in_combat = AsyncMock(return_value=True)
        calls = [0]

        async def _round_number():
            calls[0] += 1
            if calls[0] < 3:
                raise RuntimeError("transient read error")
            return 2

        h.round_number = AsyncMock(side_effect=_round_number)
        self._run(h.wait_until_next_round(1, sleep_time=0))
        self.assertEqual(calls[0], 3)

    def test_round_number_exception_in_handle_combat_retries(self):
        # If round_number() raises at the handle_combat level, the loop must
        # skip that iteration and try again rather than crashing.
        from wizwalker.memory import DuelPhase

        h = self._handler()
        in_combat_calls = [0]

        async def _in_combat():
            in_combat_calls[0] += 1
            return in_combat_calls[0] <= 2

        h.in_combat = AsyncMock(side_effect=_in_combat)
        h.wait_for_planning_phase = AsyncMock()
        h.wait_until_next_round = AsyncMock()
        rn_calls = [0]

        async def _round_number():
            rn_calls[0] += 1
            if rn_calls[0] == 1:
                raise RuntimeError("first call fails")
            return 1

        h.round_number = AsyncMock(side_effect=_round_number)
        h.handle_round = AsyncMock()
        h.client.duel.duel_phase = AsyncMock(return_value=DuelPhase.planning)
        # Patch asyncio.sleep so the retry doesn't add 0.5 s to the test run.
        import unittest.mock

        with unittest.mock.patch("src.combat.handler.asyncio.sleep", new=AsyncMock()):
            self._run(h.handle_combat())
        # handle_round called once (the second iteration, after the retry)
        h.handle_round.assert_awaited_once()

    # ── end resilience tests ─────────────────────────────────────────────────

    def test_find_castable_from_match(self):
        feint = _make_card("Feint")
        trap = _make_card("Trap")
        h = self._handler()
        result = self._run(h._find_castable_from("feint", [feint, trap]))
        self.assertIs(result, feint)

    def test_find_castable_from_substring(self):
        mass_assault = _make_card("Mass Assault")
        h = self._handler()
        result = self._run(h._find_castable_from("mass", [mass_assault]))
        self.assertIs(result, mass_assault)

    def test_find_castable_from_display_name(self):
        card = _make_card("SuperDread", display_name="Super Dread")
        h = self._handler()
        result = self._run(h._find_castable_from("super dread", [card]))
        self.assertIs(result, card)

    def test_find_castable_from_no_match(self):
        feint = _make_card("Feint")
        h = self._handler()
        result = self._run(h._find_castable_from("Colossal", [feint]))
        self.assertIsNone(result)

    def test_discard_move_calls_discard(self):
        feint = _make_card("Feint")
        h = self._handler(cards=[feint], config_str="discard")
        self._run(h.handle_round())
        feint.discard.assert_awaited()

    def test_discard_move_empty_hand_falls_through_to_pass(self):
        h = self._handler(cards=[], config_str="discard")
        self._run(h.handle_round())
        h.pass_button.assert_awaited()

    def test_two_enchants_both_applied(self):
        # "Feint[Potent][Sharpened] @ enemy" — both enchants must be sent
        # before the spell is cast. Verify both enchant packets fire.
        potent = _make_card("Potent")
        sharpened = _make_card("Sharpened")
        feint = _make_card("Feint")
        enemy = _make_member(monster=True)

        # Packet-order hand: [potent(0), sharpened(1), feint(2)]
        cards_state = {"hand": [potent, sharpened, feint]}
        h = self._handler(
            members=[_make_member(player=True), enemy],
            config_str="Feint[Potent][Sharpened] @ enemy",
        )
        h.get_cards = AsyncMock(side_effect=lambda: list(cards_state["hand"]))

        enchant_calls = []

        async def _enchant(enchant_idx, target_idx):
            current = list(cards_state["hand"])
            enchant_calls.append((enchant_idx, target_idx))
            # consume the enchant card so the hand shrinks
            enc = current[int(enchant_idx)]
            cards_state["hand"] = [c for c in current if c is not enc]

        h.client.send_combat_enchant = AsyncMock(side_effect=_enchant)

        async def _cast_spell(hand_idx, sub):
            cards_state["hand"] = []

        h.client.send_combat_spell = AsyncMock(side_effect=_cast_spell)

        self._run(h.handle_round())
        self.assertEqual(len(enchant_calls), 2, "expected two enchant packets")
        h.client.send_combat_spell.assert_awaited_once()

    def test_enchant_card_not_chosen_as_base_spell(self):
        # "Blade[Sharpen] @ enemy": the base "Blade" substring also matches
        # the "Sharpened Blade" enchant card, but the enchant and the base are
        # always different cards. The enchant must be applied to the real
        # blade, never to itself.
        sharpened = _make_card("Sharpened Blade")
        balanceblade = _make_card("Balanceblade")
        enemy = _make_member(monster=True)

        # Packet-order hand: [sharpened(0), balanceblade(1)] — the enchant card
        # sorts first, which is exactly the case that used to misfire.
        cards_state = {"hand": [sharpened, balanceblade]}
        h = self._handler(
            members=[_make_member(player=True), enemy],
            config_str="Blade[Sharpen] @ enemy",
        )
        h.get_cards = AsyncMock(side_effect=lambda: list(cards_state["hand"]))

        enchant_calls = []

        async def _enchant(enchant_idx, target_idx):
            current = list(cards_state["hand"])
            enchant_calls.append((int(enchant_idx), int(target_idx)))
            enc = current[int(enchant_idx)]
            cards_state["hand"] = [c for c in current if c is not enc]

        h.client.send_combat_enchant = AsyncMock(side_effect=_enchant)

        cast_calls = []

        async def _cast_spell(hand_idx, sub):
            current = list(cards_state["hand"])
            if 0 <= int(hand_idx) < len(current):
                cast_calls.append(current[int(hand_idx)])
            cards_state["hand"] = []

        h.client.send_combat_spell = AsyncMock(side_effect=_cast_spell)

        self._run(h.handle_round())

        # Exactly one enchant, and it targeted the real blade (idx 1), not the
        # Sharpened Blade enchant card itself (idx 0).
        self.assertEqual(len(enchant_calls), 1, "expected one enchant packet")
        enchant_idx, target_idx = enchant_calls[0]
        self.assertEqual(
            enchant_idx, 0, "enchant card should be Sharpened Blade (idx 0)"
        )
        self.assertEqual(
            target_idx, 1, "enchant must target Balanceblade (idx 1), not itself"
        )
        # …and the real blade is what got cast.
        self.assertEqual(len(cast_calls), 1)
        self.assertIs(cast_calls[0], balanceblade)

    # ── focus-school writes ───────────────────────────────────────────────
    def _focus_handler(self):
        me = _make_member(player=True, name="Me")
        # Replace get_participant to a fresh mock that records focus writes.
        part = MagicMock()
        part.write_primary_magic_school_id = AsyncMock()
        me.get_participant = AsyncMock(return_value=part)
        h = self._handler(members=[me])
        return h, part

    def test_write_focus_school_writes_correct_id(self):
        from wizwalker.memory.memory_objects.conditionals import (
            school_id_to_names,
        )

        h, part = self._focus_handler()
        ok = self._run(h._write_focus_school("storm"))
        self.assertTrue(ok)
        part.write_primary_magic_school_id.assert_awaited_once_with(
            school_id_to_names["Storm"]
        )

    def test_write_focus_school_case_insensitive(self):
        h, part = self._focus_handler()
        ok = self._run(h._write_focus_school("FIRE"))
        self.assertTrue(ok)
        part.write_primary_magic_school_id.assert_awaited_once()

    def test_write_focus_school_unknown_returns_false(self):
        h, part = self._focus_handler()
        ok = self._run(h._write_focus_school("plaid"))
        self.assertFalse(ok)
        part.write_primary_magic_school_id.assert_not_awaited()

    def test_apply_focus_school_static_is_idempotent_per_config(self):
        # Setting config.focus_school triggers exactly one write per
        # distinct config identity. Calling _apply_focus_school again with
        # the same config object must not re-write.
        from src.combat.config import CombatConfig

        h, part = self._focus_handler()
        cfg = CombatConfig(focus_school="ice")
        h._config = cfg
        self._run(h._apply_focus_school())
        self._run(h._apply_focus_school())
        self._run(h._apply_focus_school())
        part.write_primary_magic_school_id.assert_awaited_once()

    def test_apply_focus_school_reapplies_on_new_config(self):
        # Swapping to a new CombatConfig (even with the same school) clears
        # the tracker and triggers a fresh write.
        from src.combat.config import CombatConfig

        h, part = self._focus_handler()
        h._config = CombatConfig(focus_school="ice")
        self._run(h._apply_focus_school())
        # Simulate a config swap (new identity).
        h._config = CombatConfig(focus_school="ice")
        h._applied_focus_for = None
        self._run(h._apply_focus_school())
        self.assertEqual(part.write_primary_magic_school_id.await_count, 2)

    def test_exec_move_focus_writes_and_succeeds(self):
        from src.combat.config import MoveConfig

        h, part = self._focus_handler()
        move = MoveConfig(set_focus="life")
        ok, willcasted = self._run(h._exec_move(move))
        self.assertTrue(ok)
        self.assertFalse(willcasted)
        part.write_primary_magic_school_id.assert_awaited_once()


class TestZoneGraph(unittest.TestCase):
    _map_path = None

    _gate_path = None

    @classmethod
    def setUpClass(cls):

        from pathlib import Path

        base = Path(__file__).parent / "src" / "nav" / "data"

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

    def test_entries_load(self):

        self._skip_if_missing(self._zones_path)

        from src.nav.navigator import _load_zones

        _, _, entries = _load_zones(self._zones_path)

        self.assertIn("WizardCity", entries)
        self.assertEqual(entries["WizardCity"], "WizardCity/WC_Ravenwood_Teleporter")

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
        import tempfile
        import shutil
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
        import ctypes
        import ctypes.wintypes as wt

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
        import ctypes
        import ctypes.wintypes as wt

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
        import tempfile
        import shutil
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
        import tempfile
        import shutil
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
    def test_scan_exact_finds_pattern(self):
        from src.launcher import _scan_exact

        data = b"\x00\x00\xaa\xbb\xcc\xdd\x00"
        self.assertEqual(_scan_exact(data, b"\xaa\xbb\xcc\xdd"), 2)
        self.assertIsNone(_scan_exact(data, b"\xff\xee"))

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


def _make_item(
    name="TestSword",
    debug_name="TestSword_T",
    template_id=0xABCD,
    global_id=0x1234,
    perm_id=0x5678,
    object_type=None,
    school="Fire",
    description="A fiery blade",
    icon="sword.png",
    adjective_list="",
):
    item = MagicMock()
    item.debug_name = AsyncMock(return_value=debug_name)
    item.global_id_full = AsyncMock(return_value=global_id)
    item.perm_id = AsyncMock(return_value=perm_id)
    item.template_id_full = AsyncMock(return_value=template_id)

    tmpl = MagicMock()
    tmpl.object_name = AsyncMock(return_value=name)
    tmpl.read_base_address = AsyncMock(return_value=0xDEAD)
    tmpl.hook_handler = MagicMock()

    if object_type is None:
        from unittest.mock import MagicMock as MM

        ot = MM()
        ot.__str__ = lambda s: "ObjectType.equipment"
        tmpl.object_type = AsyncMock(return_value=ot)
    else:
        tmpl.object_type = AsyncMock(return_value=object_type)

    tmpl.primary_school_name = AsyncMock(return_value=school)
    tmpl.description = AsyncMock(return_value=description)
    tmpl.icon = AsyncMock(return_value=icon)
    tmpl.adjective_list = AsyncMock(return_value=adjective_list)

    core_tmpl = MagicMock()
    core_tmpl.read_base_address = AsyncMock(return_value=0xDEAD)
    core_tmpl.hook_handler = MagicMock()
    item.object_template = AsyncMock(return_value=core_tmpl)

    return item, tmpl


class TestLuaItem(unittest.TestCase):
    def _run(self, coro):
        return asyncio.new_event_loop().run_until_complete(coro)

    def _lua_item(self, **kw):
        from src.lang.client import LuaItem

        item, tmpl = _make_item(**kw)
        loop = asyncio.new_event_loop()

        def call(coro):
            return loop.run_until_complete(coro)

        def table_from(seq):
            return list(seq) if not isinstance(seq, dict) else seq

        with (
            patch(
                "wizwalker.memory.memory_objects.game_object_template.WizGameObjectTemplate.__init__",
                return_value=None,
            ),
            patch(
                "src.lang.client.WizGameObjectTemplate",
                return_value=tmpl,
            ),
        ):
            lua_item = LuaItem(item, call, table_from)
            return lua_item, item, tmpl

    def test_debug_name(self):
        lua_item, item, _ = self._lua_item(debug_name="MyItem_T")
        self.assertEqual(lua_item.debug_name(), "MyItem_T")

    def test_template_id(self):
        lua_item, _, _ = self._lua_item(template_id=0xBEEF)
        self.assertEqual(lua_item.template_id(), 0xBEEF)

    def test_global_id(self):
        lua_item, _, _ = self._lua_item(global_id=0x9999)
        self.assertEqual(lua_item.global_id(), 0x9999)

    def test_perm_id(self):
        lua_item, _, _ = self._lua_item(perm_id=0x4444)
        self.assertEqual(lua_item.perm_id(), 0x4444)

    def test_school(self):
        from src.lang.client import LuaItem

        item, tmpl = _make_item(school="Storm")
        loop = asyncio.new_event_loop()
        lua_item = LuaItem(item, loop.run_until_complete, list)
        with patch("src.lang.client._main.WizGameObjectTemplate", return_value=tmpl):
            self.assertEqual(lua_item.school(), "Storm")

    def test_description(self):
        from src.lang.client import LuaItem

        item, tmpl = _make_item(description="Desc text")
        loop = asyncio.new_event_loop()
        lua_item = LuaItem(item, loop.run_until_complete, list)
        with patch("src.lang.client._main.WizGameObjectTemplate", return_value=tmpl):
            self.assertEqual(lua_item.description(), "Desc text")

    def test_icon(self):
        from src.lang.client import LuaItem

        item, tmpl = _make_item(icon="fire_hat.png")
        loop = asyncio.new_event_loop()
        lua_item = LuaItem(item, loop.run_until_complete, list)
        with patch("src.lang.client._main.WizGameObjectTemplate", return_value=tmpl):
            self.assertEqual(lua_item.icon(), "fire_hat.png")

    def test_not_equipped_by_default(self):
        from src.lang.client import LuaItem

        item, tmpl = _make_item()
        loop = asyncio.new_event_loop()
        lua_item = LuaItem(item, loop.run_until_complete, list)
        self.assertFalse(lua_item.is_equipped())

    def test_equipped_flag(self):
        from src.lang.client import LuaItem

        item, _ = _make_item()
        loop = asyncio.new_event_loop()
        lua_item = LuaItem(item, loop.run_until_complete, list, equipped=True)
        self.assertTrue(lua_item.is_equipped())

    def test_info_returns_dict_with_keys(self):
        from src.lang.client import LuaItem

        item, tmpl = _make_item(name="Hat", debug_name="Hat_T", school="Ice")
        loop = asyncio.new_event_loop()

        def call(coro):
            return loop.run_until_complete(coro)

        with patch("src.lang.client._main.WizGameObjectTemplate", return_value=tmpl):
            lua_item = LuaItem(item, call, lambda x: x)
            result = lua_item.info()

        self.assertIn("name", result)
        self.assertIn("debug_name", result)
        self.assertIn("template_id", result)
        self.assertIn("school", result)
        self.assertIn("is_equipped", result)
        self.assertEqual(result["school"], "Ice")
        self.assertFalse(result["is_equipped"])


class TestLuaClientInventory(unittest.TestCase):
    def _run(self, coro):
        return asyncio.new_event_loop().run_until_complete(coro)

    def _make_client(self, backpack_items=None, equipped_items=None):
        from src.lang.client import LuaClient
        import threading

        loop = asyncio.new_event_loop()
        stop = threading.Event()

        def call(coro):
            return loop.run_until_complete(coro)

        def table_from(seq):
            return list(seq) if not isinstance(seq, dict) else seq

        c = MagicMock()

        inv_behavior = MagicMock()
        inv_behavior.item_list = AsyncMock(return_value=backpack_items or [])
        inv_behavior.num_items_allowed = AsyncMock(return_value=150)

        eq_behavior = MagicMock()
        eq_behavior.item_list = AsyncMock(return_value=equipped_items or [])

        c.client_object.try_get_inventory_behavior = AsyncMock(
            return_value=inv_behavior
        )
        c.client_object.try_get_equipment_behavior = AsyncMock(return_value=eq_behavior)

        client = LuaClient(c, call, stop, table_from)
        return client

    def _raw_item(self, name="Sword", debug_name="Sword_T"):
        item, tmpl = _make_item(name=name, debug_name=debug_name)
        return item, tmpl

    def test_backpack_empty(self):
        client = self._make_client()
        result = client.backpack()
        self.assertEqual(list(result), [])

    def test_backpack_returns_lua_items(self):
        from src.lang.client import LuaItem

        item, tmpl = self._raw_item("Sword", "Sword_T")
        with patch("src.lang.client._main.WizGameObjectTemplate", return_value=tmpl):
            client = self._make_client(backpack_items=[item])
            result = client.backpack()
        self.assertEqual(len(list(result)), 1)
        self.assertIsInstance(list(result)[0], LuaItem)

    def test_equipped_returns_equipped_flag(self):
        from src.lang.client import LuaItem

        item, tmpl = self._raw_item("Hat", "Hat_T")
        with patch("src.lang.client._main.WizGameObjectTemplate", return_value=tmpl):
            client = self._make_client(equipped_items=[item])
            result = client.equipped()
        items = list(result)
        self.assertEqual(len(items), 1)
        self.assertTrue(items[0].is_equipped())

    def test_has_item_true_by_debug_name(self):
        item, tmpl = self._raw_item(debug_name="WizardRobe_T")
        with patch("src.lang.client._main.WizGameObjectTemplate", return_value=tmpl):
            client = self._make_client(backpack_items=[item])
            self.assertTrue(client.has_item("robe"))

    def test_has_item_false(self):
        item, tmpl = self._raw_item(debug_name="WizardRobe_T")
        with patch("src.lang.client._main.WizGameObjectTemplate", return_value=tmpl):
            client = self._make_client(backpack_items=[item])
            self.assertFalse(client.has_item("hat"))

    def test_item_count_multiple(self):
        item1, tmpl1 = self._raw_item(debug_name="Potion_T")
        item2, tmpl2 = self._raw_item(debug_name="Potion_T")
        item3, tmpl3 = self._raw_item(debug_name="Robe_T")
        with patch(
            "src.lang.client._main.WizGameObjectTemplate",
            side_effect=[tmpl1, tmpl2, tmpl3],
        ):
            client = self._make_client(backpack_items=[item1, item2, item3])
            self.assertEqual(client.item_count("potion"), 2)

    def test_find_item_returns_none_when_missing(self):
        item, tmpl = self._raw_item(debug_name="Hat_T")
        with patch("src.lang.client._main.WizGameObjectTemplate", return_value=tmpl):
            client = self._make_client(backpack_items=[item])
            self.assertIsNone(client.find_item("robe"))

    def test_find_equipped_returns_none_when_missing(self):
        item, tmpl = self._raw_item(debug_name="Hat_T")
        with patch("src.lang.client._main.WizGameObjectTemplate", return_value=tmpl):
            client = self._make_client(equipped_items=[item])
            self.assertIsNone(client.find_equipped("robe"))


class TestWaitForTimeouts(unittest.TestCase):
    def _client(self, **overrides):
        from src.lang.client import LuaClient

        raw = MagicMock()
        # Defaults that keep predicates "false forever" so the wait loops.
        raw.zone_name = AsyncMock(return_value="ZoneA")
        raw.in_battle = AsyncMock(return_value=False)
        raw.body = MagicMock()
        raw.body.position = AsyncMock(return_value=MagicMock(distance=lambda _: 999.0))
        raw.body.yaw = AsyncMock(return_value=0.0)
        raw.get_base_entity_list = AsyncMock(return_value=[])
        for k, v in overrides.items():
            setattr(raw, k, v)

        def _call(coro):
            return asyncio.get_event_loop().run_until_complete(coro)

        import threading as _t

        return LuaClient(raw, _call, _t.Event(), lambda items: list(items))

    def _run(self, coro):
        return asyncio.get_event_loop().run_until_complete(coro)

    def test_waitfor_freedom_timeout_raises(self):
        from src.lang.bridge import ScriptError

        # is_free is awaited via src.utils.is_free; patch it to always be False.
        with patch("src.lang.client._main.is_free", AsyncMock(return_value=False)):
            c = self._client()
            with self.assertRaises(ScriptError) as cm:
                c.waitfor_freedom(window=0.05)
            self.assertIn("freedom", str(cm.exception))

    def test_waitfor_battle_start_timeout_raises(self):
        from src.lang.bridge import ScriptError

        c = self._client()
        with self.assertRaises(ScriptError) as cm:
            c.waitfor_battle_start(window=0.05)
        self.assertIn("battle_start", str(cm.exception))

    def test_waitfor_zone_timeout_raises(self):
        from src.lang.bridge import ScriptError

        c = self._client()
        with self.assertRaises(ScriptError) as cm:
            c.waitfor_zone("NonexistentZone", window=0.05)
        self.assertIn("zone", str(cm.exception))

    def test_waitfor_zone_change_timeout_raises(self):
        from src.lang.bridge import ScriptError

        c = self._client()  # zone stays "ZoneA"
        # First call seeds the baseline as ZoneA; with zone never flipping,
        # this is a clean timeout case.
        with self.assertRaises(ScriptError):
            c.waitfor_zone_change(window=0.05)

    def test_waitfor_mob_timeout_raises(self):
        from src.lang.bridge import ScriptError

        c = self._client()
        with self.assertRaises(ScriptError) as cm:
            c.waitfor_mob("nothing", window=0.05)
        self.assertIn("mob", str(cm.exception))

    def test_window_zero_means_no_timeout(self):
        from src.lang.client import _resolve_window

        # The helper is the contract here.
        self.assertIsNone(_resolve_window("freedom", 0))
        self.assertIsNone(_resolve_window("zone", -1))
        # None → method default.
        self.assertEqual(_resolve_window("freedom", None), 60.0)
        # Positive → that exact number.
        self.assertEqual(_resolve_window("zone", 7.5), 7.5)


class TestZoneBaseline(unittest.TestCase):
    def _client(self, zone_value="ZoneA"):
        from src.lang.client import LuaClient

        raw = MagicMock()
        raw.zone_name = AsyncMock(return_value=zone_value)

        def _call(coro):
            return asyncio.get_event_loop().run_until_complete(coro)

        import threading as _t

        return LuaClient(raw, _call, _t.Event(), lambda items: list(items))

    def test_zone_read_updates_baseline(self):
        c = self._client("ZoneA")
        self.assertIsNone(c._last_seen_zone)
        c.zone()
        self.assertEqual(c._last_seen_zone, "ZoneA")

    def test_waitfor_zone_change_returns_immediately_when_baseline_stale(self):
        c = self._client("ZoneB")
        c._last_seen_zone = "ZoneA"  # simulate prior acknowledgement
        result = c.waitfor_zone_change(window=5.0)
        self.assertTrue(result)
        self.assertEqual(c._last_seen_zone, "ZoneB")


class TestErrorFormatting(unittest.TestCase):
    def test_format_lua_error_inserts_source_label_and_snippet(self):
        from src.lang.bridge import LuaBridge

        b = LuaBridge(asyncio.new_event_loop())
        b._current_source_label = "myscript.lua"
        b._current_source = "line1\nerror('boom')\nline3"
        formatted = b._format_lua_error('[string "..."]:2: boom')
        self.assertIn("myscript.lua:2:", formatted)
        self.assertIn("boom", formatted)
        self.assertIn("error('boom')", formatted)

    def test_format_lua_error_handles_no_location(self):
        from src.lang.bridge import LuaBridge

        b = LuaBridge(asyncio.new_event_loop())
        b._current_source = "x = 1"
        self.assertEqual(b._format_lua_error("naked error"), "naked error")


class TestStdlibLoads(unittest.TestCase):
    def _run_and_wait(self, script: str, timeout: float = 5.0):
        from src.lang.bridge import LuaBridge

        b = LuaBridge(asyncio.new_event_loop())
        errors: list[str] = []
        b.on_error(errors.append)
        b.run(script)
        deadline = time.time() + timeout
        while b.running and time.time() < deadline:
            time.sleep(0.02)
        if b.running:  # script hung — kill it so the test process can exit
            b.stop()
            self.fail("script did not finish within timeout")
        return errors

    def test_stdlib_defines_sky(self):
        # `sky` exists and holds pure helpers — single-client recipes live
        # on LuaClient now (e.g. `client:farm_dungeon`).
        errors = self._run_and_wait(
            "assert(sky ~= nil); assert(sky.flow.retry ~= nil); "
            "assert(sky.multi.each ~= nil); assert(sky.dump ~= nil)"
        )
        self.assertEqual(errors, [])

    def test_no_playstyle_presets_in_sky(self):
        # Wizard101 combat is too diverse for generic presets to be
        # useful. If someone re-adds them by accident, this fails.
        errors = self._run_and_wait(
            'assert(sky.playstyle == nil, "no playstyle namespace in sky")'
        )
        self.assertEqual(errors, [])

    def test_stdlib_aliases_present(self):
        errors = self._run_and_wait(
            "assert(sky.log ~= nil); assert(sky.dump ~= nil); assert(sky.retry ~= nil)"
        )
        self.assertEqual(errors, [])

    def test_stdlib_recipes_callable(self):
        errors = self._run_and_wait("""
            local count = 0
            local result = sky.flow.retry(3, function()
                count = count + 1
                if count < 2 then error('first attempt fails') end
                return 'ok'
            end)
            assert(result == 'ok', 'expected ok, got ' .. tostring(result))
            assert(count == 2, 'expected 2 attempts')
        """)
        self.assertEqual(errors, [])

    def test_clock_global_available(self):
        # `clock()` is required for sky.flow.with_timeout and any user
        # timing — verify it's wired in.
        errors = self._run_and_wait("""
            local a = clock()
            sleep(0.05)
            local b = clock()
            assert(b > a, 'clock did not advance: a=' .. a .. ' b=' .. b)
        """)
        self.assertEqual(errors, [])


class TestErrorPropagation(unittest.TestCase):
    def _run_and_wait(self, script: str, register=None, timeout: float = 3.0):
        from src.lang.bridge import LuaBridge

        b = LuaBridge(asyncio.new_event_loop())
        errors: list[str] = []
        b.on_error(errors.append)
        if register:
            for name, (fn, is_async) in register.items():
                b.register(name, fn, is_async=is_async)
        b.run(script)
        deadline = time.time() + timeout
        while b.running and time.time() < deadline:
            time.sleep(0.02)
        if b.running:
            b.stop()
            self.fail("script did not finish within timeout")
        return errors

    def test_script_error_surfaces_through_callback(self):
        from src.lang.bridge import ScriptError

        def boom():
            raise ScriptError("timeout-like failure")

        errors = self._run_and_wait(
            "boom()",
            register={"boom": (boom, False)},
        )
        self.assertTrue(
            any("timeout-like failure" in e for e in errors),
            f"expected error to surface, got {errors!r}",
        )

    def test_stop_signal_is_silent(self):
        # Pressing kill should not look like a script error.
        from src.lang.bridge import LuaBridge

        b = LuaBridge(asyncio.new_event_loop())
        errors: list[str] = []
        b.on_error(errors.append)
        b.run("sleep(10)")
        time.sleep(0.1)
        b.stop()
        time.sleep(0.2)
        self.assertEqual(errors, [], "stop signal must not produce an error")


class TestLinter(unittest.TestCase):
    def test_flags_unknown_client_method(self):
        from src.lang.docgen import lint_script

        issues = lint_script("local c = clients()[1]\nc:zone_name()")
        self.assertTrue(
            any(i.severity == "error" and "zone_name" in i.message for i in issues)
        )

    def test_suggests_real_method(self):
        # Strong assertion: the linter should *propose* the real method
        # name. Asserting plain substring is too weak (`zone` is already
        # part of the typo `zone_name`).
        from src.lang.docgen import lint_script

        issues = lint_script("c:zone_name()")
        errors = [i for i in issues if i.severity == "error"]
        self.assertTrue(
            any("did you mean 'zone'" in i.message for i in errors),
            f"expected 'did you mean zone' suggestion, got {[e.message for e in errors]!r}",
        )

    def test_typo_waitfor_method_is_flagged(self):
        # Critical regression test: the old linter exempted everything
        # starting with `waitfor_` from method checking, so typos like
        # `waitfor_zomg` slipped through.
        from src.lang.docgen import lint_script

        issues = lint_script("c:waitfor_zomg()")
        self.assertTrue(
            any(i.severity == "error" and "waitfor_zomg" in i.message for i in issues),
            f"typo'd waitfor should be flagged, got {[i.message for i in issues]!r}",
        )

    def test_local_assigned_receiver_detected(self):
        # Receivers from `local NAME = clients()[N]` should be checked
        # alongside the conventional `client`/`c`/`p1-p4` names.
        from src.lang.docgen import lint_script

        issues = lint_script("local wiz = clients()[1]\nwiz:nonsense_method()")
        self.assertTrue(
            any(
                i.severity == "error" and "nonsense_method" in i.message for i in issues
            ),
        )

    def test_clean_script_no_errors(self):
        from src.lang.docgen import lint_script

        issues = lint_script("local c = clients()[1]\nc:teleport(1, 2, 3)\nc:zone()")
        self.assertEqual([i for i in issues if i.severity == "error"], [])

    def test_flags_unknown_sky_recipe(self):
        from src.lang.docgen import lint_script

        issues = lint_script("sky.nonexistent_thing(c)")
        self.assertTrue(
            any(
                i.severity == "error" and "nonexistent_thing" in i.message
                for i in issues
            )
        )

    def test_real_sky_recipe_no_error(self):
        from src.lang.docgen import lint_script

        # sky.flow.retry survived the move — it's a pure helper.
        issues = lint_script("sky.flow.retry(3, function() end)")
        self.assertEqual([i for i in issues if i.severity == "error"], [])

    def test_comments_dont_trip_linter(self):
        from src.lang.docgen import lint_script

        issues = lint_script("-- c:zone_name() in a comment\nc:zone()")
        self.assertEqual([i for i in issues if i.severity == "error"], [])

    def test_default_timeout_no_lint(self):
        # No-arg waitfor_* relies on documented defaults — not a lint concern.
        from src.lang.docgen import lint_script

        issues = lint_script("c:waitfor_zone_change()")
        self.assertEqual(issues, [])


class TestClientRecipes(unittest.TestCase):
    def _client(self, **state):
        from src.lang.client import LuaClient

        raw = MagicMock()
        raw.title = "p1"
        # Sensible defaults.
        raw.stats = MagicMock()
        raw.stats.current_hitpoints = AsyncMock(return_value=state.get("hp", 1000))
        raw.stats.max_hitpoints = AsyncMock(return_value=state.get("max_hp", 1000))
        raw.stats.current_mana = AsyncMock(return_value=state.get("mana", 100))
        raw.stats.max_mana = AsyncMock(return_value=state.get("max_mana", 100))
        raw.stats.potion_charge = AsyncMock(return_value=state.get("potions", 2.0))
        raw.body = MagicMock()
        raw.body.position = AsyncMock(
            return_value=MagicMock(distance=lambda _: state.get("dist", 0.0))
        )

        def _call(coro):
            return asyncio.get_event_loop().run_until_complete(coro)

        import threading as _t

        return LuaClient(raw, _call, _t.Event(), lambda items: list(items))

    def test_at_position_within_tolerance(self):
        c = self._client(dist=50.0)
        self.assertTrue(c.at_position(1, 2, 3, tolerance=75.0))

    def test_at_position_outside_tolerance(self):
        c = self._client(dist=200.0)
        self.assertFalse(c.at_position(1, 2, 3, tolerance=75.0))

    def test_is_full_hp_true(self):
        c = self._client(hp=1000, max_hp=1000)
        self.assertTrue(c.is_full_hp())

    def test_is_full_hp_false(self):
        c = self._client(hp=500, max_hp=1000)
        self.assertFalse(c.is_full_hp())

    def test_in_danger(self):
        c = self._client(hp=100, max_hp=1000)  # 10%
        self.assertTrue(c.in_danger(25.0))
        self.assertFalse(c.in_danger(5.0))

    def test_ensure_health_no_action_when_healthy(self):
        c = self._client(hp=900, max_hp=1000)
        self.assertFalse(c.ensure_health(50.0))

    def test_ensure_health_no_potions_returns_false(self):
        c = self._client(hp=200, max_hp=1000, potions=0.0)
        self.assertFalse(c.ensure_health(50.0))

    def test_farm_dungeon_requires_enter(self):
        from src.lang.bridge import ScriptError

        c = self._client()
        # Pass opts as a plain dict — _opt handles both.
        with self.assertRaises(ScriptError) as cm:
            c.farm_dungeon({"playstyle": "pass", "max_runs": 1})
        self.assertIn("enter", str(cm.exception))

    def test_farm_dungeon_requires_playstyle(self):
        from src.lang.bridge import ScriptError

        c = self._client()
        with self.assertRaises(ScriptError) as cm:
            c.farm_dungeon({"enter": lambda: None, "max_runs": 1})
        self.assertIn("playstyle", str(cm.exception))

    def test_farm_dungeon_requires_stop_condition(self):
        from src.lang.bridge import ScriptError

        c = self._client()
        with self.assertRaises(ScriptError) as cm:
            c.farm_dungeon({"enter": lambda: None, "playstyle": "pass"})
        self.assertIn("until_drop", str(cm.exception))

    def test_has_drops_all_present(self):
        c = self._client()
        c.got_drop = lambda n: n in {"horns", "claws"}
        self.assertTrue(c.has_drops(["horns", "claws"]))

    def test_has_drops_missing_one(self):
        c = self._client()
        c.got_drop = lambda n: n in {"horns"}
        self.assertFalse(c.has_drops(["horns", "claws"]))

    def test_has_drops_accepts_bare_string(self):
        # Regression: a single string used to be iterated character-by-
        # character ('h','o','r','n','s'), so this returned False even
        # when 'horns' was in the buffer.
        c = self._client()
        c.got_drop = lambda n: n == "horns"
        self.assertTrue(c.has_drops("horns"))
        self.assertFalse(c.has_drops("wand"))

    def test_has_drops_none_is_vacuously_true(self):
        c = self._client()
        self.assertTrue(c.has_drops(None))

    def test_farm_dungeon_raises_on_gate_failure(self):
        # Critical: if go_through_gate returns False (the engine has
        # exhausted its own retries), the recipe must NOT silently loop.
        # Looping would call `enter` again from inside the dungeon — and
        # `enter` typically teleports to outside-zone coords, which is
        # meaningless from inside, lands on a mob, etc.
        from src.lang.bridge import ScriptError

        c = self._client()
        c.got_drop = lambda n: False
        c.load_playstyle = MagicMock()
        c.waitfor_battle_start = MagicMock()
        c.waitfor_battle_finish = MagicMock()
        c.waitfor_freedom = MagicMock()
        c.go_through_gate = MagicMock(return_value=False)  # engine fails
        called_enter = [0]
        opts = {
            "until_drop": "horns",
            "playstyle": "pass",
            "enter": lambda: called_enter.__setitem__(0, called_enter[0] + 1),
            "exit_gate": "Start",
        }
        with self.assertRaises(ScriptError) as cm:
            c.farm_dungeon(opts)
        self.assertIn("Start", str(cm.exception))
        # The recipe must NOT have re-entered the dungeon after the failure.
        self.assertEqual(
            called_enter[0], 1, "enter() must not be called again after a gate failure"
        )

    def test_wait_until_healed_error_not_prefixed_waitfor(self):
        # Regression: previously used the `_timeout` helper, which
        # produced 'waitfor_until_healed' — misleading since
        # wait_until_healed is a recipe, not a primitive wait.
        from src.lang.bridge import ScriptError

        c = self._client(hp=100, max_hp=1000)
        with self.assertRaises(ScriptError) as cm:
            c.wait_until_healed(target_pct=95.0, window=0.05)
        self.assertNotIn("waitfor_", str(cm.exception))
        self.assertIn("wait_until_healed", str(cm.exception))


class TestRecipeIntegration(unittest.TestCase):
    def _run_and_wait(self, script: str, timeout: float = 3.0):
        from src.lang.bridge import LuaBridge

        b = LuaBridge(asyncio.new_event_loop())
        errors: list[str] = []
        b.on_error(errors.append)
        b.run(script)
        deadline = time.time() + timeout
        while b.running and time.time() < deadline:
            time.sleep(0.02)
        if b.running:
            b.stop()
            self.fail("script did not finish")
        return errors

    def test_sky_does_not_contain_moved_recipes(self):
        # If someone re-adds these to stdlib.lua by accident, this fails.
        errors = self._run_and_wait("""
            assert(sky.farm_dungeon == nil, 'farm_dungeon should be on client')
            assert(sky.enter_sigil == nil, 'enter_sigil should be on client')
            assert(sky.ensure_health == nil, 'ensure_health should be on client')
            assert(sky.kill_boss == nil, 'kill_boss should be on client')
        """)
        self.assertEqual(errors, [])

    def test_sky_still_has_pure_helpers(self):
        errors = self._run_and_wait("""
            assert(sky.flow.retry ~= nil)
            assert(sky.multi.each ~= nil)
            assert(sky.dump ~= nil)
            assert(sky.flow.with_timeout ~= nil)
            assert(sky.flow.repeat_until ~= nil)
        """)
        self.assertEqual(errors, [])

    def test_client_method_callable_from_lua_with_table_opts(self):
        # End-to-end: register a fake-client function so Lua can call
        # `c:farm_dungeon{...}`, and verify the Lua table is parsed and
        # the Lua callback fires from inside the Python recipe.
        from src.lang.bridge import LuaBridge

        b = LuaBridge(asyncio.new_event_loop())
        errors: list[str] = []
        b.on_error(errors.append)

        class FakeClient:
            def __init__(self):
                self.calls = []

            def farm_dungeon(self, opts):
                # Read every option exactly the way the real recipe does.
                self.calls.append(
                    {
                        "until_drop": opts.until_drop,
                        "max_runs": opts.max_runs,
                        "exit_gate": opts.exit_gate,
                    }
                )
                # Call the user-supplied Lua callback.
                opts.enter()
                opts.enter()
                return 99

        fc = FakeClient()
        b.register("c", lambda: fc, is_async=False)
        b.run("""
            local count = 0
            local n = c():farm_dungeon({
                until_drop = 'horns',
                max_runs = 7,
                exit_gate = 'Back',
                enter = function() count = count + 1 end,
            })
            assert(n == 99, 'wrong return: ' .. tostring(n))
            assert(count == 2, 'wrong callback count: ' .. count)
        """)
        deadline = time.time() + 3
        while b.running and time.time() < deadline:
            time.sleep(0.02)
        self.assertEqual(errors, [])
        self.assertEqual(len(fc.calls), 1)
        self.assertEqual(fc.calls[0]["until_drop"], "horns")
        self.assertEqual(fc.calls[0]["max_runs"], 7)
        self.assertEqual(fc.calls[0]["exit_gate"], "Back")


class TestDumpQuest(unittest.TestCase):
    def _run(self, coro):
        return asyncio.get_event_loop().run_until_complete(coro)

    def _client(self, *, qid=100, gid=7, goals=None):
        from src.lang.client import LuaClient

        raw = MagicMock()
        raw.quest_id = AsyncMock(return_value=qid)
        raw.goal_id = AsyncMock(return_value=gid)
        # _resolve_lang passes the lang key through cache_handler.
        raw.cache_handler.get_langcode_name = AsyncMock(side_effect=lambda k: k)

        quest = MagicMock()
        quest.name_lang_key = AsyncMock(return_value="The Traitor Within")

        goal_objs = {}
        for g_id, (name, gtype, dest) in (goals or {}).items():
            g = MagicMock()
            g.name_lang_key = AsyncMock(return_value=name)
            g.goal_type = AsyncMock(return_value=gtype)
            g.goal_destination_zone = AsyncMock(return_value=dest)
            goal_objs[g_id] = g
        quest.goal_data = AsyncMock(return_value=goal_objs)

        mgr = MagicMock()
        mgr.quest_data = AsyncMock(return_value={qid: quest})
        raw.quest_manager = AsyncMock(return_value=mgr)

        import threading as _t

        return LuaClient(raw, self._run, _t.Event(), lambda v: v)

    def test_resolves_active_goal_with_empty_name(self):
        # The live case: goal exists in the map but carries no name text.
        # dump_quest must report goal_in_map=True (lookup worked) and an empty
        # active_goal_name — proving tracking_goal can't match, not that the
        # lookup is broken.
        c = self._client(
            qid=100,
            gid=7,
            goals={
                7: ("", "bounty", "Grizzleheim/Interiors/GH_RedClaw_T1"),
                8: ("Open jail cell", "persona", "GH_RedClaw_T1"),
            },
        )
        out = c.dump_quest()
        self.assertEqual(out["quest_id"], 100)
        self.assertEqual(out["goal_id"], 7)
        self.assertTrue(out["goal_in_map"])
        self.assertEqual(out["quest_name"], "The Traitor Within")
        self.assertEqual(out["active_goal_name"], "")
        self.assertEqual(len(out["goals"]), 2)
        active = next(g for g in out["goals"] if g["id"] == 7)
        self.assertEqual(active["dest_zone"], "Grizzleheim/Interiors/GH_RedClaw_T1")

    def test_flags_goal_id_not_in_map(self):
        # gid not among the quest's goals → goal_in_map=False, which tells us
        # the lookup itself missed (vs. an empty-but-present goal).
        c = self._client(
            qid=100,
            gid=99,
            goals={7: ("", "bounty", "ZoneX")},
        )
        out = c.dump_quest()
        self.assertFalse(out["goal_in_map"])

    def test_reports_error_when_quest_missing_from_map(self):
        from src.lang.client import LuaClient

        raw = MagicMock()
        raw.quest_id = AsyncMock(return_value=100)
        raw.goal_id = AsyncMock(return_value=7)
        mgr = MagicMock()
        mgr.quest_data = AsyncMock(return_value={})  # active quest absent
        raw.quest_manager = AsyncMock(return_value=mgr)
        import threading as _t

        c = LuaClient(raw, self._run, _t.Event(), lambda v: v)
        out = c.dump_quest()
        self.assertIn("not in quest_data map", out["error"])

    def test_tracking_goal_reads_hud_text_not_memory_map(self):
        # The registry's active_goal_id doesn't key into the memory goal map,
        # so tracking_goal/current_goal_name read the on-screen quest-helper
        # HUD (txtGoalName) instead. Verify substring matching against it.
        c = self._client()
        win = MagicMock()
        win.maybe_text = AsyncMock(
            return_value="<center>Sabotage the Weapons Cache</center>"
        )
        with patch("src.utils.get_window_from_path", AsyncMock(return_value=win)):
            self.assertEqual(c.current_goal_name(), "Sabotage the Weapons Cache")
            self.assertTrue(c.tracking_goal("weapons cache"))  # substring
            self.assertTrue(c.tracking_goal("SABOTAGE"))  # case-insensitive
            self.assertFalse(c.tracking_goal("open jail cell"))

    def test_tracking_goal_false_when_hud_absent(self):
        # HUD not present (in combat / loading) → get_window_from_path returns
        # False → empty text → no match, no crash.
        c = self._client()
        with patch("src.utils.get_window_from_path", AsyncMock(return_value=False)):
            self.assertEqual(c.current_goal_name(), "")
            self.assertFalse(c.tracking_goal("anything"))

    def test_quest_destination_zone_and_in_zone(self):
        # The destination comes from the active quest's goal_data (the active
        # quest lookup works even though the goal-id lookup doesn't). Used to
        # tell whether the tracked quest belongs to the current dungeon.
        c = self._client(
            qid=100,
            gid=7,
            goals={7: ("", "bounty", "Grizzleheim/Interiors/GH_RedClaw_T1")},
        )
        self.assertEqual(
            c.quest_destination_zone(), "Grizzleheim/Interiors/GH_RedClaw_T1"
        )
        self.assertTrue(c.quest_in_zone("grizzleheim"))  # case-insensitive
        self.assertTrue(c.quest_in_zone("GH_RedClaw"))  # substring
        self.assertFalse(c.quest_in_zone("Wysteria"))

    def test_quest_in_zone_false_for_foreign_quest(self):
        # A pre-dungeon quest (destination outside the dungeon) → quest_in_zone
        # for the dungeon zone is False, so the loop can stop / skip it.
        c = self._client(
            qid=100,
            gid=7,
            goals={7: ("Talk To", "persona", "Wysteria/PA_Hub")},
        )
        self.assertEqual(c.quest_destination_zone(), "Wysteria/PA_Hub")
        self.assertFalse(c.quest_in_zone("Grizzleheim"))

    def test_quest_destination_zone_skips_empty_dest_goals(self):
        # First goal has no destination; the method falls through to the goal
        # that does, rather than returning "".
        c = self._client(
            qid=100,
            gid=7,
            goals={
                7: ("", "bounty", ""),
                8: ("", "waypoint", "Grizzleheim/GH_RedClaw"),
            },
        )
        self.assertEqual(c.quest_destination_zone(), "Grizzleheim/GH_RedClaw")


class TestNearestGateToward(unittest.TestCase):
    def _pick(self, gates, x, y, z):
        from src.lang.client import _nearest_gate_toward

        return _nearest_gate_toward(gates, x, y, z)

    def test_empty_returns_none(self):
        self.assertIsNone(self._pick([], 0, 0, 0))

    def test_picks_nearest(self):
        gates = [
            {"name": "Far", "x": 1000, "y": 0, "z": 0, "kind": "exit"},
            {"name": "Near", "x": 10, "y": 0, "z": 0, "kind": "exit"},
        ]
        self.assertEqual(self._pick(gates, 0, 0, 0)["name"], "Near")

    def test_prefers_exit_over_closer_arrival(self):
        # The arrival gate is closer, but walking it goes back where we came
        # from — the (farther) exit must win.
        gates = [
            {"name": "Back", "x": 5, "y": 0, "z": 0, "kind": "arrival"},
            {"name": "Forward", "x": 200, "y": 0, "z": 0, "kind": "exit"},
        ]
        self.assertEqual(self._pick(gates, 0, 0, 0)["name"], "Forward")

    def test_falls_back_to_any_when_no_exit(self):
        gates = [
            {"name": "A", "x": 300, "y": 0, "z": 0, "kind": "other"},
            {"name": "B", "x": 20, "y": 0, "z": 0, "kind": "arrival"},
        ]
        self.assertEqual(self._pick(gates, 0, 0, 0)["name"], "B")


if __name__ == "__main__":
    unittest.main()
