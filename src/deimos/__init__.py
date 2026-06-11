"""Deimos DSL → SkyFall Lua translator.

`tokenizer.py`, `types.py`, `parser.py` are vendored verbatim from upstream
(Deimos-Wizard101/Deimos-Wizard101 `src/deimoslang`) — do not edit them by hand;
re-vendor from upstream when the grammar changes. `emit.py` is the SkyFall-owned
back end that walks the parsed AST and produces Lua for the scripting bridge.
"""

from .emit import translate, TranslationError

__all__ = ["translate", "TranslationError"]
