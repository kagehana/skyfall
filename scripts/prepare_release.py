from __future__ import annotations

import re
import shutil
import sys
from datetime import date
from pathlib import Path

ROOT         = Path(__file__).resolve().parent.parent
PYPROJECT    = ROOT / "pyproject.toml"
VERSION_INFO = ROOT / "version_info.txt"
SKIP_DIRS    = {".git", ".venv", "venv", "node_modules", "build", "dist"}


def compute_version() -> tuple[str, tuple[int, int, int, int]]:
    today         = date.today()
    version_str   = f"{today.year}.{today.month}.{today.day}"
    version_tuple = (today.year, today.month, today.day, 0)

    return version_str, version_tuple


def patch_pyproject(version: str) -> None:
    text        = PYPROJECT.read_text(encoding="utf-8")
    new_text, n = re.subn(
        r'^version\s*=\s*"[^"]*"',
        f'version = "{version}"',
        text,
        count=1,
        flags=re.MULTILINE,
    )

    if n != 1:
        raise SystemExit(f"could not find `version = \"...\"` in {PYPROJECT}")
    
    PYPROJECT.write_text(new_text, encoding="utf-8")


def patch_version_info(version: str, tup: tuple[int, int, int, int]) -> None:
    text    = VERSION_INFO.read_text(encoding="utf-8")
    tup_str = f"({tup[0]}, {tup[1]}, {tup[2]}, {tup[3]})"
    dotted  = ".".join(str(n) for n in tup)                # e.g. "2026.5.27.0"

    text, n1 = re.subn(r"filevers=\([^)]*\)", f"filevers={tup_str}", text, count=1)
    text, n2 = re.subn(r"prodvers=\([^)]*\)", f"prodvers={tup_str}", text, count=1)
    text, n3 = re.subn(
        r"(StringStruct\(u'FileVersion',\s*u')[^']*(')",
        rf"\g<1>{dotted}\g<2>",
        text,
        count=1,
    )
    
    text, n4 = re.subn(
        r"(StringStruct\(u'ProductVersion',\s*u')[^']*(')",
        rf"\g<1>{dotted}\g<2>",
        text,
        count=1,
    )

    if not (n1 == n2 == n3 == n4 == 1):
        raise SystemExit(f"version_info.txt did not match expected layout ({n1=},{n2=},{n3=},{n4=})")
    VERSION_INFO.write_text(text, encoding="utf-8")


def purge_pycache() -> int:
    removed = 0
    stack   = [ROOT]

    while stack:
        d = stack.pop()

        try:
            for child in d.iterdir():
                if not child.is_dir():
                    continue
                if child.name in SKIP_DIRS:
                    continue
                if child.name == "__pycache__":
                    shutil.rmtree(child, ignore_errors=True)

                    removed += 1
                else:
                    stack.append(child)
        except PermissionError:
            continue

    return removed


def main() -> int:
    version, tup = compute_version()

    patch_pyproject(version)
    patch_version_info(version, tup)

    n = purge_pycache()

    print(f"version  -> {version}")
    print(f"pycache  -> removed {n} __pycache__ dir(s)")
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
