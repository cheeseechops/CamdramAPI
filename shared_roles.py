"""
Find all pairs (or larger groups) of people who shared the same role on a show
since September 2023.
"""

import itertools
import json
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from pathlib import Path

from camdram_client import CamdramClient

CACHE_FILE = Path(__file__).parent / "shared_roles_cache.json"
CACHE_TTL_HOURS = 24


def _load_cache(from_str: str, to_str: str) -> dict | None:
    """Load cache if valid for this exact date range and not expired."""
    if not CACHE_FILE.exists():
        return None
    try:
        with open(CACHE_FILE, encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        return None
    if data.get("from_date") != from_str or data.get("to_date") != to_str:
        return None
    cached_at = datetime.fromisoformat(data["cached_at"])
    if (datetime.now() - cached_at).total_seconds() > CACHE_TTL_HOURS * 3600:
        return None
    return data


def _load_any_fresh_cache() -> dict | None:
    """Load cache if it exists and is not expired (any date range)."""
    if not CACHE_FILE.exists():
        return None
    try:
        with open(CACHE_FILE, encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        return None
    cached_at = datetime.fromisoformat(data["cached_at"])
    if (datetime.now() - cached_at).total_seconds() > CACHE_TTL_HOURS * 3600:
        return None
    return data


def _save_cache(from_str: str, to_str: str, venues: list, shows: list, show_roles: dict) -> None:
    """Save fetched data to cache."""
    data = {
        "cached_at": datetime.now().isoformat(),
        "from_date": from_str,
        "to_date": to_str,
        "venues": venues,
        "shows": shows,
        "show_roles": show_roles,
    }
    with open(CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def main() -> None:
    force_refresh = "--refresh" in sys.argv

    # Date range: September 2023 to now
    end_date = datetime.now()
    start_date = datetime(2023, 9, 1)
    from_str = start_date.strftime("%Y-%m-%d")
    to_str = end_date.strftime("%Y-%m-%d")

    # Try cache first (unless --refresh)
    venues: list = []
    shows: list[dict] = []
    show_roles: dict[str, list] = {}
    gaps_to_fetch: list[tuple[str, str]] = []  # [(from, to), ...]

    if not force_refresh:
        cached = _load_cache(from_str, to_str)
        if cached:
            venues = cached.get("venues", [])
            shows = cached.get("shows", [])
            show_roles = cached.get("show_roles", {})
            print(f"Using cached data from {cached['cached_at'][:19]}")
        else:
            # Try to merge with existing cache (e.g. add Sept 23 - Sept 24)
            existing = _load_any_fresh_cache()
            if existing:
                cache_from = existing.get("from_date", "")
                cache_to = existing.get("to_date", "")
                venues = existing.get("venues", [])
                shows = list(existing.get("shows", []))
                show_roles = dict(existing.get("show_roles", {}))
                # Find gaps: need [from_str, cache_from) and (cache_to, to_str]
                if cache_from and cache_to:
                    if from_str < cache_from:
                        gaps_to_fetch.append((from_str, cache_from))
                    if cache_to < to_str:
                        gaps_to_fetch.append((cache_to, to_str))
                if not gaps_to_fetch:
                    print(f"Using cached data from {existing['cached_at'][:19]} (covers range)")
                else:
                    print(f"Extending cache: adding {gaps_to_fetch}")

    client = None
    if not shows or gaps_to_fetch:
        if client is None:
            client = CamdramClient()
            client.authenticate()
        if not venues:
            venues = client.get_venues()
            time.sleep(0.2)

        if not shows:
            # Full fetch
            print(f"Fetching venues and diaries from {from_str} to {to_str}...")
            ranges = [(from_str, to_str)]
        else:
            ranges = gaps_to_fetch

        shows_seen = {s["id"] for s in shows}
        for gap_from, gap_to in ranges:
            print(f"Fetching diaries from {gap_from} to {gap_to}...")
            for venue in venues:
                slug = venue.get("slug")
                if not slug:
                    continue
                try:
                    diary = client.get_venue_diary(slug, from_date=gap_from, to_date=gap_to)
                except Exception:
                    continue
                for event in diary.get("events", []):
                    show = event.get("show")
                    if show and show["id"] not in shows_seen:
                        shows_seen.add(show["id"])
                        shows.append(show)
                time.sleep(0.15)

    print(f"Found {len(shows)} shows. Fetching roles for each...\n")

    # Fetch roles (from cache or API)
    shared_roles: list[tuple[dict, str, list[dict]]] = []
    roles_to_fetch = [s for s in shows if s["slug"] not in show_roles]

    if roles_to_fetch:
        if client is None:
            client = CamdramClient()
            client.authenticate()
        for i, show in enumerate(roles_to_fetch):
            slug = show["slug"]
            name = show["name"]
            try:
                roles = client.get_show_roles(slug)
                show_roles[slug] = roles
            except Exception as e:
                print(f"  Skipping {name}: {e}")
                continue
            time.sleep(0.2)
            if (i + 1) % 50 == 0:
                print(f"  Processed {i + 1}/{len(roles_to_fetch)} shows...")
    else:
        print("  All roles loaded from cache.")

    # Save cache when we fetched new data
    if roles_to_fetch:
        _save_cache(from_str, to_str, venues, shows, show_roles)

    # Process roles into shared_roles
    for show in shows:
        slug = show["slug"]
        roles = show_roles.get(slug, [])
        role_to_people: dict[str, list[dict]] = defaultdict(list)
        for role in roles:
            role_name = role.get("role", "Unknown")
            person = role.get("person", {})
            if person:
                role_to_people[role_name].append(person)
        for role_name, people in role_to_people.items():
            if 2 <= len(people) <= 3:
                shared_roles.append((show, role_name, people))

    # Count shared roles per pair (use frozenset of person ids for consistent keys)
    pair_counts: dict[frozenset[int], int] = defaultdict(int)
    pair_names: dict[frozenset[int], tuple[str, str]] = {}
    pair_roles: dict[frozenset[int], Counter[str]] = defaultdict(Counter)

    for show, role_name, people in shared_roles:
        person_ids = [p["id"] for p in people]
        for id_a, id_b in itertools.combinations(person_ids, 2):
            pair = frozenset({id_a, id_b})
            pair_counts[pair] += 1
            pair_roles[pair][role_name] += 1
            # Store names (will be overwritten but same for same pair)
            if pair not in pair_names:
                names = {p["id"]: p.get("name", "Unknown") for p in people}
                n1, n2 = names[id_a], names[id_b]
                pair_names[pair] = (min(n1, n2), max(n1, n2))

    # Sort pairs by count descending
    sorted_pairs = sorted(
        pair_counts.items(),
        key=lambda x: (-x[1], pair_names[x[0]][0], pair_names[x[0]][1]),
    )

    # Output
    print(f"\n=== Pairs of people by shared roles (since Sept 2023) ===\n")
    print(f"Pairs ordered by number of roles done together:\n")

    for pair, count in sorted_pairs[:10]:
        if count == 1:
            continue
        name_a, name_b = pair_names[pair]
        role_parts = [
            f"{role} (x{n})" if n > 1 else role
            for role, n in sorted(pair_roles[pair].items())
        ]
        roles_str = ", ".join(role_parts)
        line = f"  {count:3d}  {name_a} & {name_b} ({roles_str})"
        try:
            print(line)
        except UnicodeEncodeError:
            print(line.encode("ascii", errors="replace").decode())


if __name__ == "__main__":
    main()
