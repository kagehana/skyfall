"""Deimos DSL -> SkyFall Lua translator.

Walks the AST produced by the vendored Deimos parser ([parser.py](parser.py),
fed by [tokenizer.py](tokenizer.py)) and emits an equivalent Lua script for the
SkyFall scripting bridge. The grammar is owned upstream; only this back end is
ours, so new Deimos commands surface here as a single dispatch gap rather than a
parser rewrite.

Design rules:
- Output is always *syntactically valid* Lua. Features with no SkyFall
  equivalent fail loudly — `_unsupported(...)` in value position (errors at
  runtime, never silently wrong) and a skipped `-- [deimos] unsupported: ...`
  comment in statement position. Every gap is also collected and listed in the
  header so the reader sees them up front.
- A Deimos `player selector` (mass / p1 p2 / except / any) becomes a Lua client
  list; `mass` (the default) means "all hooked clients". Action commands loop
  the subset; boolean selectors use `_all`/`_any` (mass = all must satisfy,
  matching the VM).
"""

import re

from .tokenizer import Tokenizer, TokenizerError
from .parser import Parser, ParserError
from .types import (
    CommandKind,
    TeleportKind,
    WaitforKind,
    ClickKind,
    CursorKind,
    LogKind,
    EvalKind,
    ExprKind,
    PlayerSelector,
    NumberExpression,
    StringExpression,
    IdentExpression,
    ConstantExpression,
    ConstantReferenceExpression,
    ConstantCheckExpression,
    XYZExpression,
    UnaryExpression,
    DivideExpression,
    SubExpression,
    GreaterExpression,
    EquivalentExpression,
    ContainsStringExpression,
    AndExpression,
    OrExpression,
    SelectorGroup,
    CommandExpression,
    ListExpression,
    Eval,
    ConstantDeclStmt,
    CommandStmt,
    ParallelCommandStmt,
    StmtList,
    IfStmt,
    WhileStmt,
    UntilStmt,
    LoopStmt,
    TimesStmt,
    BreakStmt,
    ReturnStmt,
    BlockDefStmt,
    CallStmt,
    MixinStmt,
    TimerStmt,
    TimerAction,
)
from .tokenizer import TokenKind


class TranslationError(Exception):
    pass


# Preamble helpers, emitted only when referenced.
_HELPERS = {
    "all": (
        "local function _all(list, pred)\n"
        "  for _, c in ipairs(list) do if not pred(c) then return false end end\n"
        "  return true\n"
        "end"
    ),
    "any": (
        "local function _any(list, pred)\n"
        "  for _, c in ipairs(list) do if pred(c) then return true end end\n"
        "  return false\n"
        "end"
    ),
    "except": (
        "local function _except(list, nums)\n"
        "  local out = {}\n"
        "  for i, c in ipairs(list) do\n"
        "    local skip = false\n"
        "    for _, n in ipairs(nums) do if n == i then skip = true end end\n"
        "    if not skip then out[#out + 1] = c end\n"
        "  end\n"
        "  return out\n"
        "end"
    ),
    "tp_mob": (
        "local function _tp_mob(c)\n"
        "  local m = c:nearest_mob()\n"
        "  if m then m:to() end\n"
        "end"
    ),
    "tp_entity": (
        "local function _tp_entity(c, name, nav)\n"
        "  local m = c:nearest_named(name)\n"
        "  if m then if nav then m:navigate_to() else m:to() end end\n"
        "end"
    ),
    "use_potion_if": (
        "local function _use_potion_if(c, h, m)\n"
        "  if c:health() < h or c:mana() < m then c:use_potion() end\n"
        "end"
    ),
    "wait_while": (
        "local function _wait_while(c, pred)\n"
        "  while pred(c) do sleep(0.25) end\n"
        "end"
    ),
    "unsupported": (
        'local function _unsupported(what)\n'
        '  error("[deimos->lua] unsupported: " .. what)\n'
        "end"
    ),
}


def _lua_str(s: str) -> str:
    s = (
        str(s)
        .replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\n", "\\n")
        .replace("\r", "")
    )
    return '"' + s + '"'


def _lua_num(n) -> str:
    if isinstance(n, bool):
        return "true" if n else "false"
    if isinstance(n, float) and n.is_integer():
        return str(int(n))
    return repr(n)


class Emitter:
    def __init__(self):
        self.lines: list[str] = []
        self.indent = 0
        self.helpers: set[str] = set()
        self.unsupported: list[str] = []
        self._block_names: set[str] = set()
        self._const_names: set[str] = set()

    # ---- output plumbing ----

    def w(self, text: str = ""):
        self.lines.append(("    " * self.indent + text) if text else "")

    def note(self, what: str):
        if what not in self.unsupported:
            self.unsupported.append(what)

    def _use(self, helper: str) -> str:
        self.helpers.add(helper)
        return "_" + helper

    # ---- program ----

    def emit_program(self, stmts: list):
        self._collect_hoists(stmts)
        for s in stmts:
            self.emit_stmt(s)

    def render(self) -> str:
        out: list[str] = []
        out.append("-- Translated from Deimos DSL by SkyFall.")
        if self.unsupported:
            out.append("-- Unsupported features (skipped or stubbed):")
            for u in self.unsupported:
                out.append(f"--   - {u}")
        out.append("")
        out.append("local cs = clients()")
        out.append("local client = cs[1]")
        out.append("")
        for name in sorted(self.helpers):
            out.append(_HELPERS[name])
            out.append("")
        # Forward-declare blocks (functions) and constants together so a block
        # can call/reference either regardless of source order — Deimos blocks
        # and constants are order-independent, but a Lua `local` is only visible
        # after its declaration line.
        hoisted = sorted(self._block_names | self._const_names)
        if hoisted:
            out.append("local " + ", ".join(hoisted))
            out.append("")
        out.extend(self.lines)
        text = "\n".join(out)
        while "\n\n\n" in text:
            text = text.replace("\n\n\n", "\n\n")
        return text.rstrip() + "\n"

    def _collect_hoists(self, stmts):
        for s in stmts:
            if isinstance(s, BlockDefStmt):
                self._block_names.add(self._ident(s.name))
            elif isinstance(s, ConstantDeclStmt):
                self._const_names.add(s.name)
            for child in self._child_lists(s):
                self._collect_hoists(child)

    def _child_lists(self, s):
        out = []
        for attr in ("body", "branch_true", "branch_false"):
            v = getattr(s, attr, None)
            if isinstance(v, StmtList):
                out.append(v.stmts)
        return out

    @staticmethod
    def _ident(expr) -> str:
        return expr.ident if isinstance(expr, IdentExpression) else str(expr)

    @staticmethod
    def _lua_name(ident: str) -> str:
        # parse_value keeps the leading `$` on a constant ref used as a value;
        # strip it so it resolves to the hoisted local of the same name.
        return ident[1:] if ident.startswith("$") else ident

    # ---- statements ----

    def emit_stmtlist(self, sl):
        stmts = sl.stmts if isinstance(sl, StmtList) else (sl or [])
        if not stmts:
            self.w("-- (empty)")
        for s in stmts:
            self.emit_stmt(s)

    def emit_stmt(self, s):
        if isinstance(s, CommandStmt):
            self.emit_command(s.command)
        elif isinstance(s, ParallelCommandStmt):
            self.w("-- && parallel commands run sequentially")
            for cmd in s.commands:
                self.emit_command(cmd)
        elif isinstance(s, ConstantDeclStmt):
            # `local` lives in the hoisted forward-declaration; assign in place
            self.w(f"{s.name} = {self.render_expr(s.value, 'client')}")
        elif isinstance(s, IfStmt):
            self.emit_if(s)
        elif isinstance(s, WhileStmt):
            self.w(f"while {self.render_expr(s.expr, 'client')} do")
            self.indent += 1
            self.emit_stmtlist(s.body)
            self.indent -= 1
            self.w("end")
        elif isinstance(s, UntilStmt):
            self.w(f"while not ({self.render_expr(s.expr, 'client')}) do")
            self.indent += 1
            self.emit_stmtlist(s.body)
            self.indent -= 1
            self.w("end")
        elif isinstance(s, LoopStmt):
            self.w("while true do")
            self.indent += 1
            self.emit_stmtlist(s.body)
            self.indent -= 1
            self.w("end")
        elif isinstance(s, TimesStmt):
            self.w(f"for _i = 1, {int(s.num)} do")
            self.indent += 1
            self.emit_stmtlist(s.body)
            self.indent -= 1
            self.w("end")
        elif isinstance(s, BreakStmt):
            self.w("break")
        elif isinstance(s, ReturnStmt):
            self.w("return")
        elif isinstance(s, BlockDefStmt):
            name = self._ident(s.name)
            self.w(f"function {name}()")
            self.indent += 1
            self.emit_stmtlist(s.body)
            self.indent -= 1
            self.w("end")
        elif isinstance(s, CallStmt):
            self.w(f"{self._ident(s.name)}()")
        elif isinstance(s, MixinStmt):
            self.w(f"{s.name}()  -- mixin")
        elif isinstance(s, TimerStmt):
            var = f"_timer_{s.timer_name}"
            if s.action == TimerAction.start:
                self.w(f"local {var} = clock()")
            else:
                self.w(f'print("timer {s.timer_name}: " .. (clock() - {var}))')
        else:
            self.note(f"statement {type(s).__name__}")
            self.w(f"-- [deimos] unsupported statement: {type(s).__name__}")

    def emit_if(self, stmt):
        self.w(f"if {self.render_expr(stmt.expr, 'client')} then")
        self.indent += 1
        self.emit_stmtlist(stmt.branch_true)
        self.indent -= 1
        cur = stmt
        while True:
            fb = cur.branch_false
            inner = fb.stmts if isinstance(fb, StmtList) else (fb or [])
            if len(inner) == 1 and isinstance(inner[0], IfStmt):
                nxt = inner[0]
                self.w(f"elseif {self.render_expr(nxt.expr, 'client')} then")
                self.indent += 1
                self.emit_stmtlist(nxt.branch_true)
                self.indent -= 1
                cur = nxt
                continue
            if len(inner) == 0:
                break
            self.w("else")
            self.indent += 1
            self.emit_stmtlist(fb)
            self.indent -= 1
            break
        self.w("end")

    # ---- commands ----

    def emit_command(self, cmd):
        # parse_command folds `a && b` into a ParallelCommandStmt that arrives
        # here wrapped as a CommandStmt's command
        if isinstance(cmd, ParallelCommandStmt):
            self.w("-- && parallel commands run sequentially")
            for sub in cmd.commands:
                self.emit_command(sub)
            return
        k = cmd.kind
        # non-per-client commands
        if k == CommandKind.sleep:
            self.w(f"sleep({self.render_expr(cmd.data[0], 'client')})")
            return
        if k == CommandKind.kill:
            self.w("do return end  -- kill")
            return
        if k == CommandKind.log:
            self.w(self.render_log(cmd.data))
            return
        if k in (
            CommandKind.relog,
            CommandKind.buypotions,
            CommandKind.restart_bot,
            CommandKind.autopet,
            CommandKind.set_yaw,
            CommandKind.select_friend,
            CommandKind.getdeck,
            CommandKind.cursor,
            CommandKind.set_zone,
            CommandKind.set_goal,
            CommandKind.set_quest,
        ):
            label = k.name
            self.note(f"command {label}")
            self.w(f"-- [deimos] unsupported command: {label}")
            return

        body = self.render_command_body(cmd, "c")
        if body is None:
            return
        # comment-only bodies (unsupported commands) aren't per-client and must
        # not be wrapped in a one-line `for ... do -- ... end` (the comment would
        # swallow the `end`). Emit them once, unwrapped.
        if all(ln.lstrip().startswith("--") for ln in body):
            for ln in body:
                self.w(ln)
            return
        sel = self.sel_list_expr(cmd.player_selector)
        if len(body) == 1:
            self.w(f"for _, c in ipairs({sel}) do {body[0]} end")
        else:
            self.w(f"for _, c in ipairs({sel}) do")
            self.indent += 1
            for ln in body:
                self.w(ln)
            self.indent -= 1
            self.w("end")

    def render_command_body(self, cmd, c) -> list:
        k = cmd.kind
        if k == CommandKind.teleport:
            return self.render_teleport(cmd, c)
        if k == CommandKind.goto:
            arg = cmd.data[0]
            if isinstance(arg, XYZExpression):
                return [f"{c}:navigate({self._xyz_args(arg, c)})"]
            v = self.render_expr(arg, c)
            return [f"{c}:navigate({v}[1], {v}[2], {v}[3])"]
        if k == CommandKind.sendkey:
            key = cmd.data[0].key
            secs = "0.1" if cmd.data[1] is None else self.render_expr(cmd.data[1], c)
            return [f"{c}:send_key({_lua_str(key)}, {secs})"]
        if k == CommandKind.waitfor:
            return self.render_waitfor(cmd, c)
        if k == CommandKind.tozone:
            arg = cmd.data[0]
            if isinstance(arg, list):
                return [f"{c}:to_zone({_lua_str('/'.join(arg))})"]
            if isinstance(arg, IdentExpression):
                return [f"{c}:to_zone({self._lua_name(arg.ident)})"]
            return [f"{c}:to_zone({self.render_expr(arg, c)})"]
        if k == CommandKind.load_playstyle:
            arg = cmd.data[0]
            if isinstance(arg, str):
                return [f"{c}:load_playstyle({_lua_str(arg)})"]
            if isinstance(arg, IdentExpression):
                return [f"{c}:load_playstyle({self._lua_name(arg.ident)})"]
            return [f"{c}:load_playstyle({self.render_expr(arg, c)})"]
        if k == CommandKind.setdeck:
            return [f"{c}:equip_deck({_lua_str(cmd.data[0])})"]
        if k == CommandKind.toggle_combat:
            if cmd.data and cmd.data[0].lower() == "off":
                return [f"{c}:disable_combat()"]
            if cmd.data and cmd.data[0].lower() == "on":
                return [f"{c}:enable_combat()"]
            self.note("togglecombat (no arg) -> enable_combat")
            return [f"{c}:enable_combat()"]
        if k == CommandKind.usepotion:
            if not cmd.data:
                return [f"{c}:use_potion()"]
            h = self.render_expr(cmd.data[0], c)
            m = self.render_expr(cmd.data[1], c)
            return [f"{self._use('use_potion_if')}({c}, {h}, {m})"]
        if k == CommandKind.click:
            if cmd.data and cmd.data[0] == ClickKind.window:
                return [f"{c}:click_window({self.lua_path(cmd.data[1])})"]
            self.note("click at x,y (mouse coords)")
            return [f"-- [deimos] unsupported: click at coordinates"]
        self.note(f"command {k.name}")
        return [f"-- [deimos] unsupported command: {k.name}"]

    def render_teleport(self, cmd, c) -> list:
        data = cmd.data
        kind = data[0]
        if kind == TeleportKind.position:
            arg = data[1]
            if isinstance(arg, XYZExpression):
                return [f"{c}:teleport({self._xyz_args(arg, c)})"]
            v = self.render_expr(arg, c)
            return [f"{c}:teleport({v}[1], {v}[2], {v}[3])"]
        if kind in (TeleportKind.plusteleport, TeleportKind.minusteleport):
            sign = "+" if kind == TeleportKind.plusteleport else "-"
            arg = data[1]
            if isinstance(arg, XYZExpression):
                dx = self.render_expr(arg.x, c)
                dy = self.render_expr(arg.y, c)
                dz = self.render_expr(arg.z, c)
                return [
                    f"{c}:teleport({c}:x() {sign} {dx}, "
                    f"{c}:y() {sign} {dy}, {c}:z() {sign} {dz})"
                ]
            self.note("relative teleport with non-literal offset")
            return [f"-- [deimos] unsupported: relative teleport"]
        if kind == TeleportKind.quest:
            return [f"{c}:tp_to_quest()"]
        if kind == TeleportKind.mob:
            return [f"{self._use('tp_mob')}({c})"]
        if kind == TeleportKind.client_num:
            n = int(data[1])
            return [f"{c}:teleport(cs[{n}]:x(), cs[{n}]:y(), cs[{n}]:z())"]
        if kind in (TeleportKind.entity_literal, TeleportKind.entity_vague):
            nav = TeleportKind.nav in data
            name = data[2] if nav else data[1]
            if isinstance(name, IdentExpression):
                name = name.ident
            navflag = "true" if nav else "false"
            return [f"{self._use('tp_entity')}({c}, {_lua_str(name)}, {navflag})"]
        if kind == TeleportKind.friend_name:
            name = data[1]
            if isinstance(name, IdentExpression):
                name = name.ident
            return [f"{c}:friend_tp({_lua_str(name)})"]
        if kind == TeleportKind.friend_icon:
            self.note("friendtp icon")
            return [f"-- [deimos] unsupported: friendtp icon"]
        self.note(f"teleport {kind}")
        return [f"-- [deimos] unsupported teleport: {kind}"]

    def render_waitfor(self, cmd, c) -> list:
        data = cmd.data
        kind = data[0]
        if kind == WaitforKind.dialog:
            completion = data[1]
            if completion:
                self.note("waitfor dialog completion -> waitfor_freedom")
                return [f"{c}:waitfor_freedom()"]
            return [f"{c}:waitfor_dialog()"]
        if kind == WaitforKind.battle:
            completion = data[1]
            return [f"{c}:waitfor_battle_finish()"] if completion else [
                f"{c}:waitfor_battle_start()"
            ]
        if kind == WaitforKind.free:
            completion = data[1]
            if completion:
                return [
                    f"{self._use('wait_while')}({c}, function(x) return x:is_free() end)"
                ]
            return [f"{c}:waitfor_freedom()"]
        if kind == WaitforKind.zonechange:
            completion = data[1]
            if completion:
                return [
                    f"{self._use('wait_while')}({c}, function(x) return x:is_loading() end)"
                ]
            return [f"{c}:waitfor_zone_change()"]
        if kind == WaitforKind.window:
            path = self.lua_path(data[1])
            completion = data[2]
            if completion:
                return [
                    f"{self._use('wait_while')}({c}, "
                    f"function(x) return x:window_visible({path}) end)"
                ]
            return [f"{c}:waitfor_window({path})"]
        self.note(f"waitfor {kind}")
        return [f"-- [deimos] unsupported waitfor: {kind}"]

    def render_log(self, data) -> str:
        expr = data[1]
        # StrFormatExpression: build string.format(...)
        from .types import StrFormatExpression

        if isinstance(expr, StrFormatExpression):
            args = ", ".join(self.render_expr(v, "client") for v in expr.values)
            fmt = _lua_str(expr.format_str)
            if args:
                return f"print(string.format({fmt}, {args}))"
            return f"print({fmt})"
        if isinstance(expr, StringExpression):
            return f"print({_lua_str(expr.string.rstrip())})"
        if isinstance(expr, IdentExpression):
            return f"print({expr.ident})"
        return f"print({self.render_expr(expr, 'client')})"

    # ---- selectors ----

    def sel_list_expr(self, sel: PlayerSelector) -> str:
        if sel is None or sel.mass:
            return "cs"
        if sel.any_player or sel.same_any or sel.wildcard:
            self.note("player selector (anyplayer/sameany/wildcard) -> all clients")
            return "cs"
        if sel.inverted:
            nums = ", ".join(str(n) for n in sel.player_nums)
            return f"{self._use('except')}(cs, {{{nums}}})"
        if not sel.player_nums:
            return "cs"
        return "{" + ", ".join(f"cs[{n}]" for n in sel.player_nums) + "}"

    # ---- expressions ----

    def _xyz_args(self, xyz: XYZExpression, c) -> str:
        return (
            f"{self.render_expr(xyz.x, c)}, "
            f"{self.render_expr(xyz.y, c)}, "
            f"{self.render_expr(xyz.z, c)}"
        )

    def lua_path(self, p) -> str:
        if isinstance(p, str):
            return "{" + _lua_str(p) + "}"
        if isinstance(p, IdentExpression):
            return p.ident
        items = None
        if isinstance(p, ListExpression):
            items = p.items
        elif isinstance(p, list):
            items = p
        if items is None:
            return self.render_expr(p, "client")
        parts = []
        for it in items:
            if isinstance(it, StringExpression):
                parts.append(_lua_str(it.string))
            elif isinstance(it, str):
                parts.append(_lua_str(it))
            elif isinstance(it, IdentExpression):
                # window-path segments are always string names, even unquoted
                parts.append(_lua_str(it.ident))
            else:
                parts.append(self.render_expr(it, "client"))
        return "{" + ", ".join(parts) + "}"

    def lua_val(self, v) -> str:
        if isinstance(v, str):
            return _lua_str(v)
        if isinstance(v, IdentExpression):
            return self._lua_name(v.ident)
        if isinstance(v, StringExpression):
            return _lua_str(v.string)
        if isinstance(v, NumberExpression):
            return _lua_num(v.number)
        return self.render_expr(v, "client")

    def render_expr(self, e, c) -> str:
        if isinstance(e, NumberExpression):
            return _lua_num(e.number)
        if isinstance(e, StringExpression):
            return _lua_str(e.string)
        if isinstance(e, ConstantReferenceExpression):
            return e.name
        if isinstance(e, ConstantExpression):
            if isinstance(e.value, StringExpression) and e.value.string in (
                "true",
                "false",
            ):
                return e.value.string
            return self.render_expr(e.value, c)
        if isinstance(e, ConstantCheckExpression):
            return f"({e.name} == {self.render_expr(e.value, c)})"
        if isinstance(e, IdentExpression):
            return self._lua_name(e.ident)
        if isinstance(e, XYZExpression):
            return f"{{{self._xyz_args(e, c)}}}"
        if isinstance(e, UnaryExpression):
            if e.operator.kind == TokenKind.minus:
                if isinstance(e.expr, NumberExpression):
                    return _lua_num(-e.expr.number)
                return f"-({self.render_expr(e.expr, c)})"
            if e.operator.kind == TokenKind.keyword_not:
                return f"(not ({self.render_expr(e.expr, c)}))"
            self.note(f"unary {e.operator.kind}")
            return f"{self._use('unsupported')}({_lua_str(str(e.operator.kind))})"
        if isinstance(e, DivideExpression):
            return f"({self.render_expr(e.lhs, c)} / {self.render_expr(e.rhs, c)})"
        if isinstance(e, SubExpression):
            return f"({self.render_expr(e.lhs, c)} - {self.render_expr(e.rhs, c)})"
        if isinstance(e, GreaterExpression):
            return f"({self.render_expr(e.lhs, c)} > {self.render_expr(e.rhs, c)})"
        if isinstance(e, EquivalentExpression):
            return f"({self.render_expr(e.lhs, c)} == {self.render_expr(e.rhs, c)})"
        if isinstance(e, ContainsStringExpression):
            hay = self.render_expr(e.lhs, c)
            needle = self.render_expr(e.rhs, c)
            return f"(string.find(tostring({hay}), {needle}, 1, true) ~= nil)"
        if isinstance(e, AndExpression):
            return "(" + " and ".join(self.render_expr(x, c) for x in e.expressions) + ")"
        if isinstance(e, OrExpression):
            return "(" + " or ".join(self.render_expr(x, c) for x in e.expressions) + ")"
        if isinstance(e, SelectorGroup):
            return self._render_selector_group(e.players, e.expr)
        if isinstance(e, CommandExpression):
            return self._render_command_expr(e.command)
        if isinstance(e, Eval):
            return self._render_eval(e, c)
        self.note(f"expression {type(e).__name__}")
        return f"{self._use('unsupported')}({_lua_str(type(e).__name__)})"

    def _render_selector_group(self, sel: PlayerSelector, inner) -> str:
        body = self.render_expr(inner, "c")
        listexpr = self.sel_list_expr(sel)
        helper = self._use("any") if (sel and sel.any_player) else self._use("all")
        return f"{helper}({listexpr}, function(c) return {body} end)"

    def _render_command_expr(self, cmd) -> str:
        body = self._render_expr_command_body(cmd, "c")
        listexpr = self.sel_list_expr(cmd.player_selector)
        sel = cmd.player_selector
        helper = self._use("any") if (sel and sel.any_player) else self._use("all")
        return f"{helper}({listexpr}, function(c) return {body} end)"

    def _render_expr_command_body(self, cmd, c) -> str:
        ek = cmd.data[0]
        if ek == ExprKind.window_visible:
            return f"{c}:window_visible({self.lua_path(cmd.data[1])})"
        if ek == ExprKind.window_disabled:
            return f"{c}:window_disabled({self.lua_path(cmd.data[1])})"
        if ek == ExprKind.in_zone:
            return f"{c}:in_zone({self.lua_val(cmd.data[1])})"
        if ek == ExprKind.in_combat:
            return f"{c}:in_combat()"
        if ek == ExprKind.loading:
            return f"{c}:is_loading()"
        if ek == ExprKind.tracking_quest:
            return f"{c}:tracking_quest({self.lua_val(cmd.data[1])})"
        if ek == ExprKind.tracking_goal:
            return f"{c}:tracking_goal({self.lua_val(cmd.data[1])})"
        if ek == ExprKind.has_quest:
            val = self.lua_val(cmd.data[1])
            return (
                f'(string.find(({c}:current_quest_name() or ""):lower(), '
                f"{val}, 1, true) ~= nil)"
            )
        if ek == ExprKind.items_dropped:
            items = cmd.data[1]
            if isinstance(items, list):
                ors = " or ".join(f"{c}:got_drop({_lua_str(x)})" for x in items)
                return f"({ors})"
            return f"{c}:got_drop({self.lua_val(items)})"
        self.note(f"predicate {ek.name}")
        return f"{self._use('unsupported')}({_lua_str(ek.name)})"

    def _render_eval(self, e: Eval, c) -> str:
        k = e.kind
        simple = {
            EvalKind.health: f"{c}:health()",
            EvalKind.max_health: f"{c}:max_health()",
            EvalKind.mana: f"{c}:mana()",
            EvalKind.max_mana: f"{c}:max_mana()",
            EvalKind.energy: f"{c}:energy()",
            EvalKind.bagcount: f"{c}:bag_used()",
            EvalKind.max_bagcount: f"{c}:bag_max()",
            EvalKind.potioncount: f"{c}:potion_count()",
            EvalKind.account_level: f"{c}:level()",
            EvalKind.playercount: "#cs",
        }
        if k in simple:
            return simple[k]
        if k == EvalKind.windowtext:
            # upstream stores these args three different ways: a raw [seg, seg]
            # path, a [path] wrapper, or a bare Ident/List expr. Normalise.
            path = e.args
            if (
                isinstance(path, list)
                and len(path) == 1
                and isinstance(path[0], (list, ListExpression, IdentExpression))
            ):
                path = path[0]
            return f"{c}:window_text({self.lua_path(path)})"
        self.note(f"eval {k.name}")
        return f"{self._use('unsupported')}({_lua_str(k.name)})"


# Recorded "flythrough" exports use a Deimos dialect where waitforzonechange is
# followed by the destination zone (`waitforzonechange World/Zone`). Canonical
# Deimos takes no argument — it just waits for the current zone to change — so
# the trailing zone is redundant with the change it's already waiting for. Strip
# it so the pristine parser accepts the line; it becomes waitfor_zone_change().
_WAITFORZONECHANGE_DIALECT = re.compile(r"(?i)\bwaitforzonechange\b[^\n#]*")


def _preprocess(src: str) -> str:
    out = []
    for line in src.splitlines():
        out.append(_WAITFORZONECHANGE_DIALECT.sub("waitforzonechange", line))
    return "\n".join(out)


def translate(src: str) -> str:
    """Translate Deimos DSL source text into SkyFall Lua. Raises
    ``TranslationError`` with a readable message on tokenize/parse failure."""
    try:
        tokens = Tokenizer().tokenize(_preprocess(src))
        stmts = Parser(tokens).parse()
    except (TokenizerError, ParserError) as exc:
        raise TranslationError(str(exc)) from exc
    em = Emitter()
    em.emit_program(stmts)
    return em.render()
