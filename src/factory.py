from __future__ import annotations


import re

from typing import Dict


from .combat.handler import NativeCombat


default_config = (
    'Mass | "Detonate All" | Willcast @ enemy & Willcast @ boss'
    " & any<blade> @ spell(any<blade>) & any<trap> @ spell(any<trap>)"
    " & any<mod_damage> @ spell(any<damage>) & any<blade> @ self"
    " | any<trap> @ boss | any<trap> @ enemy | any<aura> | any<global>"
    " | any<damage&aoe> @ aoe | any<damage> @ boss | any<damage> @ enemy"
    " | any<damage> @ enemies | ?(self.health < 25%) any<heal> @ self"
)


_CLIENT_RE = re.compile(r"###\sp\s*(\d+)")


def make_combat_handler(
    *args, config: str = "", cast_time: float = 0.2, **kwargs
) -> NativeCombat:

    handler = NativeCombat(*args, cast_time=cast_time, **kwargs)

    handler.set_config_string(config or default_config)

    return handler


def delegate_combat_configs(
    input_data: str, fallback_clients: int = 1, line_sep: str = "\n"
) -> Dict[int, str]:

    lines = input_data.split(line_sep)

    configs: Dict[int, str] = {}

    cur_client = -1

    buf: list[str] = []

    for line in lines:
        m = _CLIENT_RE.search(line)

        if m:
            if cur_client >= 0:
                configs[cur_client] = line_sep.join(buf)

            cur_client = int(m.group(1)) - 1

            buf = []

        else:
            buf.append(line)

    if cur_client < 0:
        joined = line_sep.join(lines)

        return {i: joined for i in range(fallback_clients)}

    configs[cur_client] = line_sep.join(buf)

    return configs
