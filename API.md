# SkyFall Lua scripting API

The full scripting API now lives in the **[wiki](wiki/Home.md)**:

- [Getting Started](wiki/Getting-Started.md) — script model, preamble, globals
- [Client API](wiki/Client-API.md) — the `client:*` methods
- [Mob API](wiki/Mob-API.md) · [Combatant API](wiki/Combatant-API.md) · [Item API](wiki/Item-API.md)
- [Standard Library](wiki/Standard-Library.md) — globals + `sky.*`
- [Combat Playstyles](wiki/Combat-Playstyles.md) · [Navigation](wiki/Navigation.md) · [Examples](wiki/Examples.md)

The reference tables are generated from source — descriptions live in
`src/lang/wiki_meta.py`, signatures come from `src/lang/client/` via
introspection. Regenerate after changing the API:

```
python -m src.lang.docgen --emit
```
