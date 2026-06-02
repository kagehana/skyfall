from __future__ import annotations


import re

from dataclasses import dataclass, field

from typing import Callable


@dataclass
class TemplateReq:
    types: list[str]


@dataclass
class Condition:
    raw: str

    subject: str

    attr: str

    op: str

    value: float

    percent: bool


@dataclass
class MoveConfig:
    is_pass: bool = False

    is_willcast: bool = False

    draw_count: int = 0

    is_discard: bool = False

    petcast_spell: str | None = None

    spell: str | TemplateReq | None = None

    enchant: str | None = None

    enchant2: str | None = None

    target: str | None = None

    target_n: int | None = None

    target_spell: TemplateReq | str | None = None

    condition: Condition | None = None

    lua_condition: Callable | None = None

    # free-action focus swap. writes the school to self and keeps scanning,
    # doesn't burn the round. handled in NativeCombat._exec_move
    set_focus: str | None = None

    # free-action school-pip assign. clicks SchoolPipPanel to bind an
    # unassigned pip, doesn't burn the round. no-ops if the panel's hidden
    set_pip: str | None = None


@dataclass
class PriorityLine:
    moves: list[MoveConfig]


@dataclass
class CombatConfig:
    lines: list[PriorityLine] = field(default_factory=list)

    round_map: dict[int, list[PriorityLine]] = field(default_factory=dict)

    # school to switch to when this config activates, none leaves it alone
    # stored lowercase, applied in NativeCombat._apply_focus_school
    focus_school: str | None = None

    # default school for SchoolPipPanel clicks, assigns unassigned pips each
    # round. unlike focus_school this re-fires since pips trickle in
    pip_school: str | None = None


_ROUND_RE = re.compile(r"^\{(\d+)\}\s*(.*)", re.DOTALL)

_FOCUS_RE = re.compile(r"^focus\s*[:=]\s*([A-Za-z]+)\s*$", re.IGNORECASE)

# move-level focus directive: `focus: storm`, `focus = storm`, `focus storm`,
# `setfocus storm`. separator is required so we don't match `focusstorm`
_SETFOCUS_MOVE_RE = re.compile(
    r"^(?:setfocus|focus)\s*(?:[:=]|\s)\s*([A-Za-z]+)\s*$",
    re.IGNORECASE,
)

# static pip directive: `pip: storm` / `setpip: storm` as a bare segment,
# sets CombatConfig.pip_school
_PIP_RE = re.compile(
    r"^(?:setpip|pip)\s*[:=]\s*([A-Za-z]+)\s*$",
    re.IGNORECASE,
)

# move-level pip directive, same shape but usable inside a line so it can
# be conditional or chained
_SETPIP_MOVE_RE = re.compile(
    r"^(?:setpip|pip)\s*(?:[:=]|\s)\s*([A-Za-z]+)\s*$",
    re.IGNORECASE,
)

_COND_RE = re.compile(r"^\?\((.+?)\)\s*(.*)", re.DOTALL)

_DRAW_RE = re.compile(r"^draw\s*\(\s*(\d+)\s*\)", re.IGNORECASE)

_ENCHANT_RE = re.compile(r"\[([^\]]+)\]")

_TARGET_RE = re.compile(
    r"^(self|boss|aoe|enemies|allies|enemy|ally)"
    r"(?:\s*\(\s*(\d+)\s*\))?$",
    re.IGNORECASE,
)

_SPELL_TGT_RE = re.compile(r"^spell\s*\((.+)\)$", re.IGNORECASE)

_SELECT_TGT_RE = re.compile(r"^select\s*\((.+)\)$", re.IGNORECASE)

_ANY_RE = re.compile(r"^any\s*<([^>]+)>", re.IGNORECASE)

_COND_EXPR_RE = re.compile(r"^(\w+(?:\.\w+)*)\s*([<>!]=?|==)\s*(\d+\.?\d*)\s*(%?)$")


def parse_config(text: str) -> CombatConfig:

    cfg = CombatConfig()

    for raw in _split_pipes(text):
        raw = raw.strip()

        if not raw:
            continue

        m_focus = _FOCUS_RE.match(raw)

        if m_focus:
            cfg.focus_school = m_focus.group(1).lower()
            continue

        m_pip = _PIP_RE.match(raw)

        if m_pip:
            cfg.pip_school = m_pip.group(1).lower()
            continue

        m = _ROUND_RE.match(raw)

        if m:
            rn, body = int(m.group(1)), m.group(2).strip()

            cfg.round_map.setdefault(rn, []).append(_parse_line(body))

        else:
            cfg.lines.append(_parse_line(raw))

    return cfg


def parse_lua_table(tbl) -> CombatConfig:

    cfg = CombatConfig()

    if tbl is None:
        return cfg

    for k, v in tbl.items():
        # top-level `focus = "<school>"` directive
        if isinstance(k, str) and k.lower() == "focus" and isinstance(v, str):
            cfg.focus_school = v.strip().lower() or None
            continue

        # top-level `pip = "<school>"` directive
        if isinstance(k, str) and k.lower() == "pip" and isinstance(v, str):
            cfg.pip_school = v.strip().lower() or None
            continue

        if isinstance(k, int) and not isinstance(v, str):
            sub = v if hasattr(v, "items") else {1: v}

            lines = []

            for _, s in sub.items():
                if isinstance(s, str):
                    lines.append(_parse_line(s.strip()))

            cfg.round_map[k] = lines

        elif isinstance(v, str):
            cfg.lines.append(_parse_line(v.strip()))

        elif hasattr(v, "__call__"):
            cfg.lines.append(_parse_table_entry(v))

    return cfg


def _split_top_level(text: str, splitter: str) -> list[str]:

    parts, buf = [], []

    depth = 0  # combined <>, [], () depth outside conditions

    i = 0

    while i < len(text):
        ch = text[i]

        # ?(...) is opaque, copy it verbatim up to the matching ')'. the
        # < > & | inside a condition don't count toward depth, else an
        # unmatched < pins depth and the line won't split
        if ch == "?" and i + 1 < len(text) and text[i + 1] == "(":
            buf.append(ch)

            i += 1

            cond_depth = 0

            while i < len(text):
                c = text[i]
                buf.append(c)
                if c == "(":
                    cond_depth += 1
                elif c == ")":
                    cond_depth -= 1
                    if cond_depth == 0:
                        i += 1
                        break
                i += 1

            continue

        if ch in "<([":
            depth += 1
        elif ch in ">)]":
            depth -= 1

        if ch == splitter and depth == 0:
            parts.append("".join(buf))
            buf = []
        else:
            buf.append(ch)

        i += 1

    parts.append("".join(buf))

    return parts


def _split_pipes(text: str) -> list[str]:

    return _split_top_level(text, "|")


def _parse_line(text: str) -> PriorityLine:

    parts = [p.strip() for p in _split_top_level(text, "&")]

    return PriorityLine(moves=[_parse_move(p) for p in parts if p])


def _parse_move(text: str) -> MoveConfig:

    text = text.strip()

    lo = text.lower()

    if lo == "pass":
        return MoveConfig(is_pass=True)

    if lo == "willcast" or lo.startswith("willcast ") or lo.startswith("willcast@"):
        return MoveConfig(is_willcast=True)

    if lo == "discard" or lo.startswith("discard ") or lo.startswith("discard@"):
        return MoveConfig(is_discard=True)

    m = _DRAW_RE.match(text)

    if m:
        return MoveConfig(draw_count=int(m.group(1)))

    condition = None

    m = _COND_RE.match(text)

    if m:
        condition = _parse_condition(m.group(1))

        text = m.group(2).strip()

    # move-level focus, a free-action MoveConfig. matched after the condition
    # is stripped so `?(round==1) focus: storm` works
    m_focus = _SETFOCUS_MOVE_RE.match(text)
    if m_focus:
        return MoveConfig(
            set_focus=m_focus.group(1).lower(),
            condition=condition,
        )

    # move-level pip, same as focus but clicks SchoolPipPanel instead of
    # writing the focus field
    m_pip = _SETPIP_MOVE_RE.match(text)
    if m_pip:
        return MoveConfig(
            set_pip=m_pip.group(1).lower(),
            condition=condition,
        )

    lo = text.lower()

    if (
        lo == "petcast"
        or lo.startswith("petcast ")
        or lo.startswith('petcast"')
        or lo.startswith("petcast'")
    ):
        rest = text[7:].lstrip()
        at_idx = _find_at(rest)
        if at_idx >= 0:
            spell_name = rest[:at_idx].strip().strip('"').strip("'")
            target_part = rest[at_idx + 1 :].strip()
        else:
            spell_name = rest.strip().strip('"').strip("'")
            target_part = "enemy"
        target, target_n, _ = _parse_target(target_part)
        return MoveConfig(
            petcast_spell=spell_name,
            target=target,
            target_n=target_n,
            condition=condition,
        )

    at_idx = _find_at(text)

    if at_idx >= 0:
        spell_part = text[:at_idx].strip()

        target_part = text[at_idx + 1 :].strip()

    else:
        spell_part = text.strip()

        target_part = "enemy"

    enchants = _ENCHANT_RE.findall(spell_part)

    spell_raw = _ENCHANT_RE.sub("", spell_part).strip().strip('"').strip("'")

    spell = _parse_spell(spell_raw)

    target, target_n, target_spell = _parse_target(target_part)

    return MoveConfig(
        spell=spell,
        enchant=enchants[0] if enchants else None,
        enchant2=enchants[1] if len(enchants) > 1 else None,
        target=target,
        target_n=target_n,
        target_spell=target_spell,
        condition=condition,
    )


def _find_at(text: str) -> int:

    depth = 0

    for i, ch in enumerate(text):
        if ch in "<([":
            depth += 1

        elif ch in ">)]":
            depth -= 1

        if ch == "@" and depth == 0:
            return i

    return -1


def _parse_spell(raw: str) -> str | TemplateReq:

    m = _ANY_RE.match(raw)

    if m:
        types = [t.strip() for t in m.group(1).split("&")]

        return TemplateReq(types=types)

    return raw


def _parse_target(raw: str):

    raw = raw.strip()

    m = _SPELL_TGT_RE.match(raw)

    if m:
        inner = m.group(1).strip().strip('"').strip("'")

        spell_tgt = _parse_spell(inner)

        return "spell", None, spell_tgt

    m = _SELECT_TGT_RE.match(raw)

    if m:
        return "select", None, m.group(1).strip()

    if raw.startswith('"') or raw.startswith("'"):
        return raw.strip('"').strip("'"), None, None

    m = _TARGET_RE.match(raw)

    if m:
        base = m.group(1).lower()

        n = int(m.group(2)) if m.group(2) else None

        return base, n, None

    return raw.lower(), None, None


def _parse_condition(raw: str) -> Condition | None:

    m = _COND_EXPR_RE.match(raw.strip())

    if not m:
        return None

    subject_attr, op, val_str, pct = m.group(1), m.group(2), m.group(3), m.group(4)

    parts = subject_attr.split(".")

    subject = parts[0] if len(parts) > 1 else "self"

    attr = parts[-1]

    value = float(val_str)

    return Condition(
        raw=raw, subject=subject, attr=attr, op=op, value=value, percent=bool(pct)
    )


def _parse_table_entry(entry) -> PriorityLine:

    spell_raw = None

    target = "enemy"

    enchant = enchant2 = None

    lua_cond = None

    target_n = None

    target_spell = None

    for k, v in entry.items():
        if isinstance(k, int):
            if k == 1:
                spell_raw = str(v)

            elif k == 2:
                enchant = str(v)

        elif k == "target":
            target, target_n, target_spell = _parse_target(str(v))

        elif k == "enchant":
            enchant = str(v)

        elif k == "enchant2":
            enchant2 = str(v)

        elif k == "when":
            lua_cond = v

    spell = _parse_spell(spell_raw) if spell_raw else None

    mc = MoveConfig(
        spell=spell,
        enchant=enchant,
        enchant2=enchant2,
        target=target,
        target_n=target_n,
        target_spell=target_spell,
        lua_condition=lua_cond,
    )

    return PriorityLine(moves=[mc])
