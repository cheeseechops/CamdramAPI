"""
Rank all active people by number of distinct roles (since Sept 2023).
Uses the shared_roles cache - run shared_roles.py first if needed.
"""

import json
import sys
from pathlib import Path

CACHE_FILE = Path(__file__).parent / "shared_roles_cache.json"


def main() -> None:
    if not CACHE_FILE.exists():
        print("No cache found. Run shared_roles.py first to populate the cache.")
        sys.exit(1)

    with open(CACHE_FILE, encoding="utf-8") as f:
        data = json.load(f)

    show_roles = data.get("show_roles", {})
    from_date = data.get("from_date", "?")
    to_date = data.get("to_date", "?")

    # person_id -> (name, set of distinct role names)
    person_roles: dict[int, tuple[str, set[str]]] = {}

    for slug, roles in show_roles.items():
        for role in roles:
            person = role.get("person", {})
            if not person:
                continue
            pid = person.get("id")
            name = person.get("name", "Unknown")
            role_name = role.get("role", "Unknown")
            if pid is None:
                continue
            if pid not in person_roles:
                person_roles[pid] = (name, set())
            person_roles[pid][1].add(role_name)

    # Sort by number of distinct roles descending, then by name
    ranked = sorted(
        ((pid, name, roles) for pid, (name, roles) in person_roles.items()),
        key=lambda x: (-len(x[2]), x[1]),
    )

    print(f"\n=== People ranked by distinct roles (since Sept 2023) ===\n")
    print(f"Data from {from_date} to {to_date}\n")

    for i, (pid, name, roles) in enumerate(ranked[:10], 1):
        count = len(roles)
        roles_str = ", ".join(sorted(roles)[:3])
        if len(roles) > 3:
            roles_str += f" ... (+{len(roles) - 3} more)"
        line = f"  {i:4d}.  {count:3d}  {name}"
        if roles_str:
            line += f"  ({roles_str})"
        try:
            print(line)
        except UnicodeEncodeError:
            print(line.encode("ascii", errors="replace").decode())


if __name__ == "__main__":
    main()
