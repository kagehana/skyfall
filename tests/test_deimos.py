"""Tests for the Deimos DSL -> SkyFall Lua translator (src/deimos).

Every command/expression snippet is translated and then compiled with lupa
(the same Lua engine the bridge uses), so a syntax regression in the emitter or
a new upstream command with no dispatch arm fails loudly here.
"""

import unittest

from src.deimos import translate, TranslationError


def _compile(lua_src: str):
    """Compile (not run) Lua to assert it is syntactically valid."""
    import lupa

    rt = lupa.LuaRuntime(register_eval=False, register_builtins=False)
    # wrap in a function so top-level returns (e.g. `do return end`) are legal
    rt.compile("local function _chunk()\n" + lua_src + "\nend")


# Each entry is a self-contained Deimos snippet exercising one command/form.
# Stored as a dict so a failure reports exactly which construct broke.
SNIPPETS = {
    "kill": "kill",
    "sleep": "sleep 2",
    "log_str": 'log "hello world"',
    "log_health": "log health",
    "log_window": 'log window ["A", "B"]',
    "tp_xyz": "tp XYZ(1, 2, 3)",
    "tp_neg_xyz": "tp XYZ(-5045.6, -2700.1, 257.0)",
    "tp_quest": "teleport quest",
    "tp_mob": "teleport mob",
    "tp_client": "teleport p2",
    "plus_tp": "plustp XYZ(0, 0, 50)",
    "minus_tp": "minustp XYZ(0, 0, 50)",
    "friendtp_name": "friendtp Bob The Builder",
    "friendtp_icon": "friendtp icon",
    "entitytp_lit": 'entitytp "Bartleby"',
    "entitytp_vague": "entitytp Bartleby",
    "entitytp_nav": 'entitytp nav "Bartleby"',
    "goto": "goto XYZ(1, 2, 3)",
    "sendkey": "sendkey W, 0.5",
    "sendkey_nodur": "sendkey X",
    "sendkey_end": "sendkey END, 0.1",
    "waitfor_dialog": "waitfordialog",
    "waitfor_dialog_compl": "waitfordialogue completion",
    "waitfor_battle": "waitforbattle",
    "waitfor_battle_compl": "waitforbattle completion",
    "waitfor_zonechange": "waitforzonechange",
    "waitfor_zonechange_dialect": "waitforzonechange WizardCity/WC_Hub",
    "waitfor_free": "waitforfree",
    "waitfor_window": 'waitforwindow ["A", "B"]',
    "waitfor_window_compl": 'waitforwindow ["A", "B"] completion',
    "usepotion": "usepotion",
    "usepotion_thr": "usepotion 500, 50",
    "buypotions": "buypotions",
    "buypotions_ifneeded": "buypotions ifneeded",
    "relog": "relog",
    "click_window": 'clickwindow ["A", "B"]',
    "click_pos": "click 10, 20",
    "cursor_pos": "cursor 10, 20",
    "tozone_path": "tozone WizardCity/WC_Hub",
    "loadplaystyle": 'loadplaystyle "Feint @ enemy | pass"',
    "set_yaw": "turncam 90",
    "selectfriend": "selectfriend Bob",
    "setdeck": 'setdeck "Boss Deck"',
    "getdeck": "getdeck",
    "autopet": "autopet",
    "togglecombat_on": "togglecombat on",
    "togglecombat_off": "togglecombat off",
    "togglecombat_bare": "togglecombat",
    "restartbot": "restartbot",
    "logzone": "logzone",
    "loggoal": "loggoal",
    "logquest": "logquest",
    # selectors
    "sel_p1": "p1 teleport quest",
    "sel_multi": "p1:p2 teleport quest",
    "sel_except": "except p1 teleport quest",
    "sel_any": "anyplayer teleport quest",
    # control flow
    "con": "con X = 5",
    "con_xyz": "con Home = XYZ(1, 2, 3)",
    "if": "if mass incombat {\n  sleep 1\n}",
    "if_else": "if mass incombat {\n  sleep 1\n} else {\n  sleep 2\n}",
    "if_elif": (
        "if mass incombat {\n  sleep 1\n} elif mass loading {\n"
        "  sleep 2\n} else {\n  sleep 3\n}"
    ),
    "while": "while mass incombat {\n  sleep 1\n}",
    "until": "until mass incombat {\n  sleep 1\n}",
    "loop_break": "loop {\n  break\n}",
    "times": "times 3 {\n  sleep 1\n}",
    "block_call": "block Foo {\n  sleep 1\n}\ncall Foo",
    "block_return": "block Foo {\n  return\n}",
    "mixin": "block A {\n  sleep 1\n}\nblock B {\n  mixin A\n}",
    "timer": "starttimer T\nendtimer T",
    "parallel": "sleep 1 && sleep 2",
    # expression commands (wrapped in if)
    "expr_windowvisible": 'if mass windowvisible ["A"] {\n  sleep 1\n}',
    "expr_windowdisabled": 'if mass windowdisabled ["A"] {\n  sleep 1\n}',
    "expr_inzone": "if mass inzone WizardCity/WC_Hub {\n  sleep 1\n}",
    "expr_loading": "if mass loading {\n  sleep 1\n}",
    "expr_trackingquest": 'if mass trackingquest "foo" {\n  sleep 1\n}',
    "expr_trackinggoal": 'if mass trackinggoal "foo" {\n  sleep 1\n}',
    "expr_hasquest": 'if mass hasquest "foo" {\n  sleep 1\n}',
    "expr_itemdropped": 'if mass itemdropped "foo" {\n  sleep 1\n}',
    "expr_healthbelow": "if mass healthbelow 25% {\n  sleep 1\n}",
    "expr_healthabove": "if mass healthabove 25% {\n  sleep 1\n}",
    "expr_mana": "if mass mana > 5 {\n  sleep 1\n}",
    "expr_energy": "if mass energy > 5 {\n  sleep 1\n}",
    "expr_bagcount": "if mass bagcount > 5 {\n  sleep 1\n}",
    "expr_gold": "if mass gold > 5 {\n  sleep 1\n}",
    "expr_potioncount": "if mass potioncount > 5 {\n  sleep 1\n}",
    "expr_playercount": "if mass playercount > 1 {\n  sleep 1\n}",
    "expr_accountlevel": "if mass accountlevel > 5 {\n  sleep 1\n}",
    "expr_windowtext": 'if mass windowtext ["A"] "hi" {\n  sleep 1\n}',
    "expr_and_or_not": (
        "if mass incombat and not mass loading {\n  sleep 1\n}"
    ),
}


class TestDeimosTranslate(unittest.TestCase):
    def test_every_snippet_translates_and_compiles(self):
        for name, src in SNIPPETS.items():
            with self.subTest(snippet=name):
                lua = translate(src)
                self.assertIsInstance(lua, str)
                self.assertTrue(lua.strip(), "empty translation")
                _compile(lua)

    def test_wizard_city_flythrough(self):
        src = (
            "mass tp XYZ(-5045.65625, -2700.6396484375, 257.1866149902344)\n"
            "sleep 3\n"
            "#unicorn way\n"
            "mass tp XYZ(6280.86, 5576.79, -27.9)\n"
            "mass waitforzonechange WizardCity/WC_Streets/WC_Unicorn\n"
            "mass sendkey END, 0.1\n"
            "mass waitfordialogue completion\n"
            "kill\n"
        )
        lua = translate(src)
        _compile(lua)
        self.assertIn("clients()", lua)
        self.assertIn("c:teleport(-5045.65625, -2700.6396484375, 257.1866149902344)", lua)
        self.assertIn("c:waitfor_zone_change()", lua)
        self.assertIn("c:send_key(\"END\", 0.1)", lua)
        self.assertIn("do return end", lua)  # kill
        # negative coords must not be wrapped as -(...)
        self.assertNotIn("-(5045", lua)

    def test_selector_subset_and_mass(self):
        self.assertIn("ipairs(cs)", translate("mass teleport quest"))
        self.assertIn("cs[2]", translate("p2 teleport quest"))
        self.assertIn("_except(cs, {1})", translate("except p1 teleport quest"))
        multi = translate("p1:p3 teleport quest")
        self.assertIn("cs[1]", multi)
        self.assertIn("cs[3]", multi)

    def test_friendtp_maps_to_friend_tp(self):
        self.assertIn("friend_tp(\"Bob\")", translate("friendtp Bob"))

    def test_usepotion_threshold(self):
        lua = translate("usepotion 500, 50")
        self.assertIn("_use_potion_if(c, 500, 50)", lua)
        self.assertIn("c:use_potion()", translate("usepotion"))

    def test_unsupported_is_reported_not_crashed(self):
        lua = translate("relog")
        self.assertIn("unsupported", lua.lower())
        _compile(lua)  # still valid Lua

    def test_health_percent_uses_max(self):
        lua = translate("if mass healthbelow 25% {\n  sleep 1\n}")
        self.assertIn("c:health() / c:max_health()", lua)
        self.assertIn("0.25", lua)

    def test_tozone_joins_path(self):
        self.assertIn('to_zone("WizardCity/WC_Hub")', translate("tozone WizardCity/WC_Hub"))

    def test_blocks_are_hoisted(self):
        lua = translate("call Foo\nblock Foo {\n  sleep 1\n}")
        # forward declaration precedes the call so the reference resolves
        self.assertIn("local Foo", lua)
        self.assertIn("function Foo()", lua)
        _compile(lua)

    def test_constant_referenced_before_declaration_is_hoisted(self):
        # a block defined before the `con` still resolves the constant: the
        # `local` must be hoisted above the block, not emitted in place.
        lua = translate('block Show {\n  log $Greeting\n}\ncon Greeting = "hi"\ncall Show')
        _compile(lua)
        decl = lua.index("local Greeting")
        func = lua.index("function Show()")
        self.assertLess(decl, func, "constant local must be hoisted above the block")
        self.assertIn("Greeting =", lua)  # assigned in place, no second `local`
        self.assertNotIn("local Greeting =", lua)

    def test_loadplaystyle_quotes_not_long_bracket(self):
        lua = translate('loadplaystyle "Feint[Colossal] @ enemy | pass"')
        _compile(lua)
        self.assertIn('load_playstyle("Feint[Colossal] @ enemy | pass")', lua)

    def test_parse_error_raises_translation_error(self):
        with self.assertRaises(TranslationError):
            translate("if mass {\n  sleep 1\n}")  # missing condition


if __name__ == "__main__":
    unittest.main()
