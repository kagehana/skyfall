from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Optional

# PropertyFlags bits we care about (katsuba-types/property.rs).
F_DEPRECATED = 1 << 6
F_DELTA_ENCODE = 1 << 8
F_BITS = 1 << 20
F_ENUM = 1 << 21
ENUM_LIKE = F_ENUM | F_BITS


@dataclass(slots=True)
class Property:
    name: str
    type: str
    id: int
    flags: int
    dynamic: bool
    hash: int
    enum_options: dict = field(default_factory=dict)

    def is_enum(self) -> bool:
        return bool(self.flags & ENUM_LIKE) or self.type.startswith("enum")


@dataclass(slots=True)
class TypeDef:
    name: str
    hash: int
    # property-hash -> Property, ordered by ``id`` (matches deep-mode order)
    properties: dict[int, Property]


class TypeList:
    def __init__(self, classes: Optional[dict[int, TypeDef]] = None):
        self.classes: dict[int, TypeDef] = classes or {}

    def get(self, hash_: int) -> Optional[TypeDef]:
        return self.classes.get(hash_)

    def add(self, type_def: TypeDef) -> None:
        self.classes[type_def.hash] = type_def

    # loading
    @classmethod
    def open(cls, path: str) -> "TypeList":
        with open(path, "r", encoding="utf-8") as fh:
            return cls.from_dict(json.load(fh))

    @classmethod
    def from_dict(cls, root: dict) -> "TypeList":
        version = root.get("version", 1)
        entries = root.get("classes", root) if version == 2 else root

        classes: dict[int, TypeDef] = {}
        for name, body in entries.items():
            if name in ("version", "classes"):
                continue
            classes[body["hash"]] = _parse_typedef(name, body)
        return cls(classes)


def _parse_typedef(name: str, body: dict) -> TypeDef:
    props: list[Property] = []
    for pname, p in body.get("properties", {}).items():
        props.append(
            Property(
                name=pname,
                type=p["type"],
                id=p.get("id", 0),
                flags=p.get("flags", 0),
                dynamic=bool(p.get("dynamic", False)),
                hash=p["hash"],
                enum_options=p.get("enum_options", {}) or {},
            )
        )
    # deep mode names each property by hash; order is irrelevant for lookup,
    # but we keep id-order to mirror katsuba (and for shallow mode parity)
    props.sort(key=lambda pr: pr.id)
    return TypeDef(
        name=name, hash=body["hash"], properties={pr.hash: pr for pr in props}
    )
