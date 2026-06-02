from __future__ import annotations

import inspect
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from src.lang.client import LuaClient, LuaMob, LuaItem, LuaCombatant
from src.lang.wiki_meta import DOC


@dataclass
class LintIssue:
    severity: str  # "error" | "warning" | "info"
    line: int
    message: str

    def __str__(self) -> str:
        return f"{self.severity}: line {self.line}: {self.message}"


def _lua_client_method_set() -> set[str]:
    out: set[str] = set()
    for name, member in inspect.getmembers(LuaClient, predicate=inspect.isfunction):
        if not name.startswith("_"):
            out.add(name)
    return out


def _sky_recipe_set() -> set[str]:
    stdlib = Path(__file__).parent / "stdlib.lua"
    if not stdlib.exists():
        return set()
    src = stdlib.read_text(encoding="utf-8")
    out = set()
    for m in re.finditer(r"^function (sky[\w.]+)\(", src, re.M):
        out.add(m.group(1))
    for m in re.finditer(r"^(sky[\w.]+)\s*=", src, re.M):
        out.add(m.group(1))
    return out


def _edit_distance(a: str, b: str) -> int:
    if len(a) < len(b):
        a, b = b, a
    if not b:
        return len(a)
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cost = 0 if ca == cb else 1
            cur.append(min(prev[j] + 1, cur[-1] + 1, prev[j - 1] + cost))
        prev = cur
    return prev[-1]


def _suggest(name: str, options: Iterable[str]) -> str | None:
    name_l = name.lower()
    options = list(options)

    prefix_hits = [
        o
        for o in options
        if o.lower() != name_l
        and (name_l.startswith(o.lower()) or o.lower().startswith(name_l))
    ]
    if prefix_hits:
        return min(prefix_hits, key=lambda o: abs(len(o) - len(name)))

    best, best_dist = None, 99
    for o in options:
        d = _edit_distance(name_l, o.lower())
        if d < best_dist:
            best, best_dist = o, d
    cap = max(1, min(3, len(name) // 3))
    return best if best_dist <= cap else None


_CLIENT_CALL_RE = re.compile(r"(\w+):(\w+)\s*\(")
_SKY_CALL_RE = re.compile(r"\b(sky(?:\.\w+)+)\s*\(")
_RECEIVER_FROM_CLIENTS_RE = re.compile(
    r"\blocal\s+(\w+)\s*=\s*clients\s*\(\s*\)\s*\[", re.M
)


def _client_receivers(source: str) -> set[str]:
    receivers = {"client", "c", "p1", "p2", "p3", "p4"}
    for m in _RECEIVER_FROM_CLIENTS_RE.finditer(source):
        receivers.add(m.group(1))
    return receivers


def lint_script(source: str) -> list[LintIssue]:
    issues: list[LintIssue] = []
    client_methods = _lua_client_method_set()
    sky_recipes = _sky_recipe_set()
    receivers = _client_receivers(source)

    for ln, line in enumerate(source.splitlines(), start=1):
        # strip lua line comments before matching so commented-out calls
        # don't trip the linter
        clean = re.sub(r"--.*$", "", line)

        for m in _CLIENT_CALL_RE.finditer(clean):
            receiver, method = m.group(1), m.group(2)
            # flag only methods on receivers we're confident point at a LuaClient.
            # skipping unknown receivers avoids false positives on LuaMob/LuaItem
            if receiver in receivers:
                if method not in client_methods:
                    suggestion = _suggest(method, client_methods)
                    msg = f"unknown client method '{method}'"
                    if suggestion:
                        msg += f" — did you mean '{suggestion}'?"
                    issues.append(LintIssue("error", ln, msg))

        for m in _SKY_CALL_RE.finditer(clean):
            full = m.group(1)
            if full not in sky_recipes:
                suggestion = _suggest(full, sky_recipes)
                msg = f"unknown stdlib recipe '{full}'"
                if suggestion:
                    msg += f" — did you mean '{suggestion}'?"
                issues.append(LintIssue("error", ln, msg))

    return issues


def format_issues(issues: list[LintIssue]) -> str:
    if not issues:
        return "lint: clean"
    by_sev = {"error": 0, "warning": 0, "info": 0}
    for i in issues:
        by_sev[i.severity] = by_sev.get(i.severity, 0) + 1
    head = (
        f"lint: {by_sev['error']} error(s), "
        f"{by_sev['warning']} warning(s), "
        f"{by_sev['info']} info"
    )
    lines = [head]
    for i in issues:
        lines.append("  " + str(i))
    return "\n".join(lines)


# ─────────────────────────────────────────────────────────────────────────────
# Wiki emit
#
# Fills `<!-- AUTOGEN:KEY START -->` … `<!-- AUTOGEN:KEY END -->` blocks across
# the markdown pages in `wiki/`. Signatures and the method set come live from
# the source via `inspect`; descriptions and grouping come from `wiki_meta.DOC`.
# Curated prose lives outside the AUTOGEN blocks and is never touched.
# ─────────────────────────────────────────────────────────────────────────────

_CLASSES = {c.__name__: c for c in (LuaClient, LuaMob, LuaItem, LuaCombatant)}

_AUTOGEN_RE = re.compile(
    r"(<!-- AUTOGEN:(?P<key>[\w]+) START[^\n]*-->\n)(?:.*?)(\n<!-- AUTOGEN:(?P=key) END -->)",
    re.DOTALL,
)


def _wiki_dir() -> Path:
    return Path(__file__).resolve().parents[2] / "wiki"


def _live_methods(cls) -> dict[str, str]:
    """Public method name -> cleaned signature, read from the live class."""
    out: dict[str, str] = {}
    for name, member in inspect.getmembers(cls, predicate=inspect.isfunction):
        if name.startswith("_"):
            continue
        out[name] = _clean_sig(member)
    return out


def _clean_sig(member) -> str:
    try:
        sig = inspect.signature(member)
    except (TypeError, ValueError):
        return "()"
    params = [str(p) for n, p in sig.parameters.items() if n != "self"]
    ret = ""
    if sig.return_annotation is not inspect.Signature.empty:
        ret = f" -> {sig.return_annotation}"
    text = f"({', '.join(params)}){ret}"
    # `from __future__ import annotations` stringifies annotations, so they
    # arrive wrapped in quotes — strip them for readability.
    return text.replace("'", "")


def _md_escape(text: str) -> str:
    return text.replace("|", "\\|")


def _render_class(classname: str) -> str:
    cls = _CLASSES[classname]
    live = _live_methods(cls)
    documented: set[str] = set()
    sections: list[tuple[str, list[tuple[str, str]]]] = []

    for cat, rows in DOC.get(classname, []):
        kept = []
        for method, desc in rows:
            if method not in live:
                print(
                    f"warning: {classname}.{method} documented in wiki_meta "
                    f"but absent from source — prune it",
                    file=sys.stderr,
                )
                continue
            documented.add(method)
            kept.append((method, desc))
        if kept:
            sections.append((cat, kept))

    leftover = sorted(set(live) - documented)
    if leftover:
        sections.append(
            ("Uncategorized", [(m, "_(undocumented — add to wiki_meta)_") for m in leftover])
        )

    out: list[str] = []
    for cat, rows in sections:
        out.append(f"#### {cat}\n")
        out.append("| Method | Signature | Description |")
        out.append("|---|---|---|")
        for method, desc in rows:
            sig = _md_escape(live[method])
            out.append(f"| `{method}` | `{sig}` | {_md_escape(desc)} |")
        out.append("")
    return "\n".join(out).rstrip()


def _render_globals() -> str:
    rows = [
        ("clients()", "1-indexed table of `LuaClient`, one per hooked Wizard101 client"),
        ("sleep(secs)", "Block for `secs` seconds, interruptible by the stop signal"),
        ("clock()", "Monotonic wall-clock seconds, for timing inside a script"),
        ("print(...)", "Print a line to the script console"),
        ("json.encode(v[, pretty])", "Encode a Lua value to a JSON string"),
        ("json.decode(s)", "Decode a JSON string to a Lua value"),
        ("pause_logs()", "Pause SkyFall's log output"),
        ("resume_logs()", "Resume SkyFall's log output"),
    ]
    out = ["| Global | Description |", "|---|---|"]
    out += [f"| `{name}` | {_md_escape(desc)} |" for name, desc in rows]
    return "\n".join(out)


def _render_stdlib() -> str:
    stdlib = Path(__file__).parent / "stdlib.lua"
    if not stdlib.exists():
        return "_stdlib.lua not found_"
    lines = stdlib.read_text(encoding="utf-8").splitlines()
    out = ["| Recipe | Description |", "|---|---|"]
    fn_re = re.compile(r"^function (sky[\w.]+)\((.*)\)")
    for i, line in enumerate(lines):
        m = fn_re.match(line)
        if not m:
            continue
        name, args = m.group(1), m.group(2)
        # gather the contiguous comment block immediately above
        doc: list[str] = []
        j = i - 1
        while j >= 0 and lines[j].lstrip().startswith("--") and "──" not in lines[j]:
            doc.insert(0, lines[j].lstrip()[2:].strip())
            j -= 1
        desc = " ".join(doc).strip() or "—"
        out.append(f"| `{name}({args})` | {_md_escape(desc)} |")
    # top-level aliases
    alias_re = re.compile(r"^(sky\.\w+)\s*=\s*(sky[\w.]+|\w+)")
    aliases = [
        (m.group(1), m.group(2))
        for m in (alias_re.match(ln) for ln in lines)
        if m
    ]
    if aliases:
        out.append("")
        out.append("**Top-level aliases:** " + ", ".join(
            f"`{a}` → `{t}`" for a, t in aliases
        ))
    return "\n".join(out)


def _render(key: str) -> str:
    if key in _CLASSES:
        return _render_class(key)
    if key == "globals":
        return _render_globals()
    if key == "stdlib":
        return _render_stdlib()
    raise KeyError(f"unknown AUTOGEN key {key!r}")


def emit_wiki() -> int:
    """Fill every AUTOGEN block found under wiki/. Returns files changed."""
    wiki = _wiki_dir()
    if not wiki.exists():
        print(f"error: {wiki} does not exist", file=sys.stderr)
        return 0

    changed = 0
    seen_keys: set[str] = set()
    for page in sorted(wiki.glob("*.md")):
        src = page.read_text(encoding="utf-8")

        def _sub(m: re.Match) -> str:
            key = m.group("key")
            seen_keys.add(key)
            body = _render(key)
            return f"{m.group(1)}{body}\n{m.group(3).lstrip(chr(10))}"

        new = _AUTOGEN_RE.sub(_sub, src)
        if new != src:
            page.write_text(new, encoding="utf-8")
            changed += 1
            print(f"emit: updated {page.name}")

    for key in (*_CLASSES, "globals", "stdlib"):
        if key not in seen_keys:
            print(
                f"warning: no AUTOGEN:{key} block found in any wiki page",
                file=sys.stderr,
            )
    return changed


# CLI


if __name__ == "__main__":
    if "--emit" in sys.argv:
        n = emit_wiki()
        print(f"emit: {n} file(s) changed")
        sys.exit(0)

    if "--lint" in sys.argv:
        idx = sys.argv.index("--lint")
        path = sys.argv[idx + 1] if len(sys.argv) > idx + 1 else None
        if not path:
            print("usage: docgen.py --lint <script.lua>")
            sys.exit(2)
        src = Path(path).read_text(encoding="utf-8")
        issues = lint_script(src)
        print(format_issues(issues))
        sys.exit(1 if any(i.severity == "error" for i in issues) else 0)
    else:
        print("usage: docgen.py --lint <path>")
