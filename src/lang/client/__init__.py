from src.lang.client._main import (  # noqa: F401
    LuaClient,
    LuaItem,
    LuaMob,
    LuaCombatant,
    pause_logs,
    resume_logs,
    walk_quest_gate_if_cross_zone,
    quest_destination_zone_of,
    is_free,
    is_visible_by_path,
    WizGameObjectTemplate,
    _resolve_window,
    _nearest_gate_toward,
    _teleport_with_retry,
    _teleport_near,
)


def __getattr__(name):
    from src.lang.client import _main

    try:
        return getattr(_main, name)
    except AttributeError:
        raise AttributeError(
            f"module 'src.lang.client' has no attribute {name!r}"
        ) from None
