"""
Persistent role consolidation mappings.

Maps source role names to a target role name so role statistics can be merged.
"""

from __future__ import annotations

import json
from pathlib import Path


_BASE = Path(__file__).resolve().parent
CONSOLIDATIONS_FILE = _BASE / "role_consolidations.json"


def _normalize_name(name: str) -> str:
    return (name or "").strip()


def _key(name: str) -> str:
    return _normalize_name(name).casefold()


def load_consolidations() -> dict[str, str]:
    """
    Return a mapping of source role name -> target role name.
    """
    if not CONSOLIDATIONS_FILE.exists():
        return {}
    try:
        with open(CONSOLIDATIONS_FILE, encoding="utf-8") as f:
            raw = json.load(f)
    except (OSError, json.JSONDecodeError, ValueError):
        return {}
    if not isinstance(raw, dict):
        return {}
    out: dict[str, str] = {}
    for source, target in raw.items():
        if not isinstance(source, str) or not isinstance(target, str):
            continue
        s = _normalize_name(source)
        t = _normalize_name(target)
        if not s or not t:
            continue
        if _key(s) == _key(t):
            continue
        out[s] = t
    return out


def save_consolidations(mapping: dict[str, str]) -> None:
    clean: dict[str, str] = {}
    for source, target in (mapping or {}).items():
        s = _normalize_name(source)
        t = _normalize_name(target)
        if not s or not t:
            continue
        if _key(s) == _key(t):
            continue
        clean[s] = t
    with open(CONSOLIDATIONS_FILE, "w", encoding="utf-8") as f:
        json.dump(clean, f, ensure_ascii=True, indent=2, sort_keys=True)
        f.write("\n")


def build_consolidation_lookup(mapping: dict[str, str]) -> dict[str, str]:
    lookup: dict[str, str] = {}
    for source, target in (mapping or {}).items():
        s = _normalize_name(source)
        t = _normalize_name(target)
        if not s or not t:
            continue
        if _key(s) == _key(t):
            continue
        lookup[_key(s)] = t
    return lookup


def apply_consolidation(
    role_name: str,
    mapping: dict[str, str],
    lookup: dict[str, str] | None = None,
) -> str:
    """
    Resolve role_name through mapping chains:
      A -> B -> C  => C
    If there is a cycle, return the original role_name.
    """
    current = _normalize_name(role_name)
    if not current:
        return role_name
    if not mapping:
        return current

    key_lookup = lookup if lookup is not None else build_consolidation_lookup(mapping)
    seen: set[str] = set()
    current_key = _key(current)

    while current_key in key_lookup:
        if current_key in seen:
            return _normalize_name(role_name)
        seen.add(current_key)
        target = _normalize_name(key_lookup.get(current_key, ""))
        if not target:
            return current
        current = target
        current_key = _key(current)
    return current

