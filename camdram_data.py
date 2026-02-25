"""
Shared data loading for Camdram rankings (no GUI deps).
Used by camdram_gui and the Flask web app.

Optimised: in-memory cache keyed by (cache_path, mtime). Single JSON load and
single pass over shows/show_roles to compute both rankings and role_rankings.
Uses orjson for faster parse when available.
"""

import json
import calendar
import re
from datetime import datetime, timezone
from pathlib import Path

from role_normalization import canonicalize_role, categorize_role, main_group_for_category
from role_consolidation import (
    CONSOLIDATIONS_FILE,
    load_consolidations,
    apply_consolidation,
    build_consolidation_lookup,
)
_BASE = Path(__file__).resolve().parent
CACHE_FILE = _BASE / "rank_all_people_cache.json"
SHARED_ROLES_CACHE = _BASE / "shared_roles_cache.json"

try:
    import orjson
    def _load_json(path: Path) -> dict:
        return orjson.loads(path.read_bytes())
    _json_errors: tuple = (orjson.JSONDecodeError, ValueError)
except ImportError:
    def _load_json(path: Path) -> dict:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    _json_errors = (json.JSONDecodeError, ValueError)


# In-memory cache: (rankings, roles_list, role_rankings) keyed by cache + consolidation mtimes
_cache: tuple[list[tuple], list[tuple[str, int]], dict[str, list[tuple]]] | None = None
_cache_key: tuple[str, float, float] | None = None
_recent_starters_cache: dict[tuple[float, int], set[int]] = {}
_recent_activity_cache: dict[tuple[float, int], set[int]] = {}


def _compute_from_data(
    data: dict,
    consolidation_map: dict[str, str] | None = None,
) -> tuple[list[tuple], list[tuple[str, int]], dict[str, list[tuple]]]:
    """One pass over shows/show_roles to build both person rankings and role rankings."""
    shows = data.get("shows", [])
    show_roles = data.get("show_roles", {})
    show_date_ranges: dict[str, tuple[datetime, datetime]] = {}
    for show in shows:
        slug = show.get("slug")
        if not slug:
            continue
        first_dt: datetime | None = None
        last_dt: datetime | None = None
        for perf in show.get("performances", []) or []:
            start_at = perf.get("start_at")
            if not start_at:
                continue
            try:
                dt = datetime.fromisoformat(str(start_at).replace("Z", "+00:00"))
            except ValueError:
                continue
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            if first_dt is None or dt < first_dt:
                first_dt = dt
            if last_dt is None or dt > last_dt:
                last_dt = dt
        if first_dt is not None and last_dt is not None:
            show_date_ranges[slug] = (first_dt, last_dt)
    person_role_count: dict[int, int] = {}
    person_name: dict[int, str] = {}
    person_slug: dict[int, str] = {}
    person_role_freq: dict[int, dict[str, int]] = {}
    person_subcategory_freq: dict[int, dict[str, int]] = {}
    person_category_freq: dict[int, dict[str, int]] = {}
    person_shows: dict[int, set[str]] = {}
    person_first_credit: dict[int, datetime] = {}
    person_last_credit: dict[int, datetime] = {}
    role_person_count: dict[str, dict[int, int]] = {}
    consolidation_lookup = build_consolidation_lookup(consolidation_map or {})

    for show in shows:
        slug = show.get("slug")
        for role_entry in show_roles.get(slug, []):
            person = role_entry.get("person", {})
            if not person:
                continue
            pid = person.get("id")
            if pid is None:
                continue
            role_name = canonicalize_role(role_entry.get("role") or "Unknown")
            if role_name is None:
                continue
            role_name = apply_consolidation(role_name, consolidation_map or {}, lookup=consolidation_lookup)
            person_role_count[pid] = person_role_count.get(pid, 0) + 1
            person_name[pid] = person.get("name", "Unknown")
            person_slug[pid] = person.get("slug", "")
            if pid not in person_shows:
                person_shows[pid] = set()
            person_shows[pid].add(slug)
            show_range = show_date_ranges.get(slug)
            if show_range is not None:
                show_first, show_last = show_range
                existing_first = person_first_credit.get(pid)
                if existing_first is None or show_first < existing_first:
                    person_first_credit[pid] = show_first
                existing_last = person_last_credit.get(pid)
                if existing_last is None or show_last > existing_last:
                    person_last_credit[pid] = show_last
            if pid not in person_role_freq:
                person_role_freq[pid] = {}
            person_role_freq[pid][role_name] = person_role_freq[pid].get(role_name, 0) + 1
            subcategory = categorize_role(role_name)
            if pid not in person_subcategory_freq:
                person_subcategory_freq[pid] = {}
            person_subcategory_freq[pid][subcategory] = person_subcategory_freq[pid].get(subcategory, 0) + 1
            category = main_group_for_category(subcategory)
            if pid not in person_category_freq:
                person_category_freq[pid] = {}
            person_category_freq[pid][category] = person_category_freq[pid].get(category, 0) + 1
            if role_name not in role_person_count:
                role_person_count[role_name] = {}
            role_person_count[role_name][pid] = role_person_count[role_name].get(pid, 0) + 1

    def top_role_and_stats(pid: int, total: int) -> tuple[str, int, int, int, int, str, int, str, int]:
        freqs = person_role_freq.get(pid, {})
        subcategory_freqs = person_subcategory_freq.get(pid, {})
        category_freqs = person_category_freq.get(pid, {})
        num_shows = len(person_shows.get(pid, set()))
        num_titles = len(freqs)
        if not freqs:
            return ("—", 0, num_shows, num_titles, 0, "—", 0, "—", 0)
        role, top_count = max(freqs.items(), key=lambda x: (x[1], x[0]))
        top_subcategory, top_subcategory_count = max(
            subcategory_freqs.items(),
            key=lambda x: (x[1], x[0]),
        )
        top_category, top_category_count = max(
            category_freqs.items(),
            key=lambda x: (x[1], x[0]),
        )
        top_pct = round(100 * top_count / total) if total else 0
        return (
            role,
            top_count,
            num_shows,
            num_titles,
            top_pct,
            top_subcategory,
            top_subcategory_count,
            top_category,
            top_category_count,
        )

    rankings = sorted(
        (
            (
                pid,
                person_name[pid],
                person_slug.get(pid, ""),
                count,
                *top_role_and_stats(pid, count),
                person_first_credit.get(pid).date().isoformat() if person_first_credit.get(pid) else "",
                person_last_credit.get(pid).date().isoformat() if person_last_credit.get(pid) else "",
            )
            for pid, count in person_role_count.items()
        ),
        key=lambda x: (-x[3], x[1]),
    )

    role_rankings: dict[str, list[tuple[int, str, str, int]]] = {}
    for role_name, pid_counts in role_person_count.items():
        ranked = sorted(
            (
                (pid, person_name[pid], person_slug.get(pid, ""), count)
                for pid, count in pid_counts.items()
            ),
            key=lambda x: (-x[3], x[1]),
        )
        role_rankings[role_name] = ranked
    roles_list = sorted(
        ((rn, len(r)) for rn, r in role_rankings.items()),
        key=lambda x: (-x[1], x[0]),
    )
    return (rankings, roles_list, role_rankings)


def _get_cached() -> tuple[list[tuple], list[tuple[str, int]], dict[str, list[tuple]]] | None:
    """Return cached (rankings, roles_list, role_rankings) if valid."""
    global _cache, _cache_key
    consolidation_map = load_consolidations()
    consolidation_mtime = 0.0
    try:
        if CONSOLIDATIONS_FILE.exists():
            consolidation_mtime = CONSOLIDATIONS_FILE.stat().st_mtime
    except OSError:
        consolidation_mtime = 0.0
    for cache_path in [CACHE_FILE, SHARED_ROLES_CACHE]:
        if not cache_path.exists():
            continue
        try:
            mtime = cache_path.stat().st_mtime
            key = (str(cache_path), mtime, consolidation_mtime)
            if _cache_key == key and _cache is not None:
                return _cache
            data = _load_json(cache_path)
            _cache = _compute_from_data(data, consolidation_map=consolidation_map)
            _cache_key = key
            return _cache
        except (OSError, *_json_errors):
            continue
    return None


def load_rankings() -> list[tuple]:
    """
    Load rankings from cache (cached in memory after first load).
    Returns list of:
    (pid, name, slug, count, top_role, top_role_count, num_shows, num_role_titles,
     top_pct, top_subcategory, top_subcategory_count, top_category, top_category_count,
     first_credit_date, last_credit_date).
    """
    cached = _get_cached()
    return cached[0] if cached else []


def load_role_rankings() -> tuple[list[tuple[str, int]], dict[str, list[tuple[int, str, str, int]]]]:
    """
    Load from cache: all roles and per-role rankings (cached in memory after first load).
    Returns (roles_list, role_rankings).
    """
    cached = _get_cached()
    if cached:
        return (cached[1], cached[2])
    return ([], {})


def load_active_person_ids() -> set[int]:
    """
    Load person IDs active in the last 6 months.
    Uses show performance dates from rank_all_people_cache.json when available.
    """
    try:
        data = _load_json(CACHE_FILE)
    except (OSError, *_json_errors):
        return set()

    now = datetime.now(timezone.utc)
    cutoff_month = now.month - 6
    cutoff_year = now.year
    while cutoff_month <= 0:
        cutoff_month += 12
        cutoff_year -= 1
    cutoff_day = min(now.day, calendar.monthrange(cutoff_year, cutoff_month)[1])
    cutoff = now.replace(year=cutoff_year, month=cutoff_month, day=cutoff_day)

    recent_show_slugs: set[str] = set()
    for show in data.get("shows", []):
        slug = show.get("slug")
        if not slug:
            continue
        for perf in show.get("performances", []) or []:
            start_at = perf.get("start_at")
            if not start_at:
                continue
            try:
                dt = datetime.fromisoformat(str(start_at).replace("Z", "+00:00"))
            except ValueError:
                continue
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            if dt >= cutoff:
                recent_show_slugs.add(slug)
                break

    show_roles = data.get("show_roles", {})
    active_ids: set[int] = set()
    for slug, roles in show_roles.items():
        if slug not in recent_show_slugs:
            continue
        for role_entry in roles or []:
            person = role_entry.get("person", {})
            pid = person.get("id")
            if isinstance(pid, int):
                active_ids.add(pid)
    return active_ids


def _years_ago(dt: datetime, years: int) -> datetime:
    """Return dt shifted back by N years, clamped for leap-day edge cases."""
    target_year = dt.year - years
    target_day = dt.day
    max_day = calendar.monthrange(target_year, dt.month)[1]
    if target_day > max_day:
        target_day = max_day
    return dt.replace(year=target_year, day=target_day)


def load_recent_starter_person_ids(years: int = 4) -> set[int]:
    """
    Load person IDs whose first known role date is within the last `years` years.
    Uses show performance dates from rank_all_people_cache.json.
    """
    if years <= 0:
        return set()
    try:
        mtime = CACHE_FILE.stat().st_mtime
    except OSError:
        return set()

    cache_key = (mtime, years)
    cached = _recent_starters_cache.get(cache_key)
    if cached is not None:
        return cached

    try:
        data = _load_json(CACHE_FILE)
    except (OSError, *_json_errors):
        return set()

    show_first_perf: dict[str, datetime] = {}
    for show in data.get("shows", []):
        slug = show.get("slug")
        if not slug:
            continue
        first_dt: datetime | None = None
        for perf in show.get("performances", []) or []:
            start_at = perf.get("start_at")
            if not start_at:
                continue
            try:
                dt = datetime.fromisoformat(str(start_at).replace("Z", "+00:00"))
            except ValueError:
                continue
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            if first_dt is None or dt < first_dt:
                first_dt = dt
        if first_dt is not None:
            show_first_perf[slug] = first_dt

    person_first_role: dict[int, datetime] = {}
    for slug, roles in (data.get("show_roles", {}) or {}).items():
        show_dt = show_first_perf.get(slug)
        if show_dt is None:
            continue
        for role_entry in roles or []:
            person = role_entry.get("person", {})
            pid = person.get("id")
            if not isinstance(pid, int):
                continue
            existing = person_first_role.get(pid)
            if existing is None or show_dt < existing:
                person_first_role[pid] = show_dt

    now = datetime.now(timezone.utc)
    cutoff = _years_ago(now, years)
    out = {pid for pid, first_dt in person_first_role.items() if first_dt >= cutoff}
    _recent_starters_cache.clear()
    _recent_starters_cache[cache_key] = out
    return out


def load_recently_active_person_ids(years: int = 1) -> set[int]:
    """
    Load person IDs whose most recent known role date is within the last `years` years.
    Uses show performance dates from rank_all_people_cache.json.
    """
    if years <= 0:
        return set()
    try:
        mtime = CACHE_FILE.stat().st_mtime
    except OSError:
        return set()

    cache_key = (mtime, years)
    cached = _recent_activity_cache.get(cache_key)
    if cached is not None:
        return cached

    try:
        data = _load_json(CACHE_FILE)
    except (OSError, *_json_errors):
        return set()

    show_last_perf: dict[str, datetime] = {}
    show_year_hint: dict[str, int] = {}
    for show in data.get("shows", []):
        slug = show.get("slug")
        if not slug:
            continue
        last_dt: datetime | None = None
        for perf in show.get("performances", []) or []:
            start_at = perf.get("start_at")
            if not start_at:
                continue
            try:
                dt = datetime.fromisoformat(str(start_at).replace("Z", "+00:00"))
            except ValueError:
                continue
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            if last_dt is None or dt > last_dt:
                last_dt = dt
        if last_dt is not None:
            show_last_perf[slug] = last_dt
            continue
        m = re.search(r"(19|20)\d{2}", slug)
        if m:
            show_year_hint[slug] = int(m.group(0))

    person_last_role: dict[int, datetime] = {}
    person_last_year_hint: dict[int, int] = {}
    for slug, roles in (data.get("show_roles", {}) or {}).items():
        show_dt = show_last_perf.get(slug)
        year_hint = show_year_hint.get(slug)
        if show_dt is None:
            if year_hint is None:
                continue
        for role_entry in roles or []:
            person = role_entry.get("person", {})
            pid = person.get("id")
            if not isinstance(pid, int):
                continue
            if show_dt is not None:
                existing = person_last_role.get(pid)
                if existing is None or show_dt > existing:
                    person_last_role[pid] = show_dt
            elif year_hint is not None:
                existing_year = person_last_year_hint.get(pid, 0)
                if year_hint > existing_year:
                    person_last_year_hint[pid] = year_hint

    now = datetime.now(timezone.utc)
    cutoff = _years_ago(now, years)
    out = {pid for pid, last_dt in person_last_role.items() if last_dt >= cutoff}
    cutoff_year = cutoff.year
    for pid, year_hint in person_last_year_hint.items():
        if pid in out:
            continue
        # Fallback for shows with no performance timestamps: include if slug hints recent year.
        if year_hint >= cutoff_year:
            out.add(pid)
    _recent_activity_cache.clear()
    _recent_activity_cache[cache_key] = out
    return out


def invalidate_cache() -> None:
    """Force next load to re-read from disk (e.g. after cache file update)."""
    global _cache, _cache_key
    _cache = None
    _cache_key = None
    _recent_starters_cache.clear()
    _recent_activity_cache.clear()
