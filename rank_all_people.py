"""
Rank all people on Camdram by total number of roles (each role instance counts).
Uses cache by default - run with --refresh to fetch fresh data.
"""

import json
import sys
import threading
import time
import argparse
import re
import calendar
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, date
from pathlib import Path

from camdram_client import CamdramClient

MAX_WORKERS = 20  # Maximum parallel requests

CACHE_FILE = Path(__file__).parent / "rank_all_people_cache.json"
CACHE_TTL_HOURS = 24 * 7  # 1 week
CURRENT_LOOKBACK_DAYS = 60
FUTURE_LOOKAHEAD_DAYS = 730
DEFAULT_SEARCH_BACK_TO_YEAR = 1994


def _slug_year_hint(slug: str | None) -> int | None:
    if not slug:
        return None
    m = re.search(r"(19|20)\d{2}", slug)
    if not m:
        return None
    return int(m.group(0))


def _load_cache() -> dict | None:
    """Load cache if it exists and is not expired."""
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


def _save_cache(
    venues: list,
    shows: list,
    show_roles: dict,
    from_date: str,
    to_date: str,
) -> None:
    """Save fetched data to cache."""
    data = {
        "cached_at": datetime.now().isoformat(),
        "from_date": from_date,
        "to_date": to_date,
        "venues": venues,
        "shows": shows,
        "show_roles": show_roles,
    }
    with open(CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def _merge_shows_for_window(
    client: CamdramClient,
    venues: list,
    shows: list[dict],
    from_str: str,
    to_str: str,
) -> list[dict]:
    """Fetch current/future shows and merge new IDs into shows list."""
    if not venues:
        venues = client.get_venues()
    societies = client.get_societies()
    shows_seen: set[int] = {s["id"] for s in shows if s.get("id")}
    shows_lock = threading.Lock()
    tls = threading.local()

    def init_worker():
        tls.client = CamdramClient()
        tls.client.authenticate()

    def merge_show_list(candidates: list[dict] | None) -> None:
        if not candidates:
            return
        for show in candidates:
            if show and show.get("id"):
                with shows_lock:
                    if show["id"] not in shows_seen:
                        shows_seen.add(show["id"])
                        shows.append(show)

    def fetch_venue_diary(venue: dict) -> list[dict]:
        slug = venue.get("slug")
        if not slug:
            return []
        try:
            diary = tls.client.get_venue_diary(slug, from_date=from_str, to_date=to_str)
            return [e.get("show") for e in diary.get("events", []) if e.get("show")]
        except Exception:
            return []

    def fetch_society_diary(society: dict) -> list[dict]:
        slug = society.get("slug")
        if not slug:
            return []
        try:
            diary = tls.client.get_society_diary(slug, from_date=from_str, to_date=to_str)
            return [e.get("show") for e in diary.get("events", []) if e.get("show")]
        except Exception:
            return []

    def fetch_society_shows(society: dict) -> list[dict]:
        slug = society.get("slug")
        if not slug:
            return []
        try:
            return tls.client.get_society_shows(slug, from_date=from_str, to_date=to_str)
        except Exception:
            return []

    def fetch_venue_shows(venue: dict) -> list[dict]:
        slug = venue.get("slug")
        if not slug:
            return []
        try:
            return tls.client.get_venue_shows(slug, from_date=from_str, to_date=to_str)
        except Exception:
            return []

    print(f"Incremental update window: {from_str} to {to_str}")
    with ThreadPoolExecutor(max_workers=MAX_WORKERS, initializer=init_worker) as ex:
        print("Fetching venue diaries for current/future window...")
        for venue_shows in ex.map(fetch_venue_diary, venues):
            merge_show_list(venue_shows)
        print("Fetching society shows for current/future window...")
        for society_shows in ex.map(fetch_society_shows, societies):
            merge_show_list(society_shows)
        print("Fetching society diaries for current/future window...")
        for diary_shows in ex.map(fetch_society_diary, societies):
            merge_show_list(diary_shows)
        print("Fetching venue shows for current/future window...")
        for venue_show_list in ex.map(fetch_venue_shows, venues):
            merge_show_list(venue_show_list)
    return venues


def _merge_shows_from_diary(
    client: CamdramClient,
    shows: list[dict],
    from_str: str,
    to_str: str,
) -> int:
    """Crawl global diary in monthly windows and merge newly discovered shows."""
    try:
        start = date.fromisoformat(from_str)
        end = date.fromisoformat(to_str)
    except ValueError:
        return 0
    if start > end:
        return 0

    shows_seen: set[int] = {s["id"] for s in shows if s.get("id")}
    added = 0
    cursor = date(start.year, start.month, 1)
    print(f"Diary crawl window: {from_str} to {to_str}")
    while cursor <= end:
        last_day = calendar.monthrange(cursor.year, cursor.month)[1]
        window_start = cursor if cursor >= start else start
        window_end = date(cursor.year, cursor.month, last_day)
        if window_end > end:
            window_end = end
        ws = window_start.isoformat()
        we = window_end.isoformat()
        try:
            diary = client.get_diary(from_date=ws, to_date=we)
            events = diary.get("events", []) if isinstance(diary, dict) else []
        except Exception:
            events = []
        for event in events:
            show = (event or {}).get("show") or {}
            if not isinstance(show, dict):
                continue
            sid = show.get("id")
            if not sid:
                continue
            if sid in shows_seen:
                continue
            shows_seen.add(sid)
            shows.append(show)
            added += 1
        if cursor.month == 12:
            cursor = date(cursor.year + 1, 1, 1)
        else:
            cursor = date(cursor.year, cursor.month + 1, 1)
    return added


def _merge_shows_from_year_search(
    client: CamdramClient,
    shows: list[dict],
    from_year: int,
    to_year: int,
) -> int:
    """Discover shows via paginated /search?q=<year> and merge missing entries."""
    shows_seen_ids: set[int] = {s["id"] for s in shows if s.get("id")}
    shows_seen_slugs: set[str] = {s["slug"] for s in shows if s.get("slug")}
    added = 0
    years = list(range(from_year, to_year + 1))
    print(f"Year-search crawl: {from_year} to {to_year}")
    for year in years:
        page = 1
        while True:
            try:
                hits = client._request("/search", params={"q": str(year), "page": page})
            except Exception:
                break
            if not isinstance(hits, list) or not hits:
                break
            page_added = 0
            for hit in hits:
                if not isinstance(hit, dict):
                    continue
                if hit.get("entity_type") != "show":
                    continue
                sid = hit.get("id")
                slug = hit.get("slug")
                if not sid or not slug:
                    continue
                if sid in shows_seen_ids or slug in shows_seen_slugs:
                    continue
                shows.append(
                    {
                        "id": sid,
                        "name": hit.get("name", ""),
                        "slug": slug,
                        "_type": "show",
                    }
                )
                shows_seen_ids.add(sid)
                shows_seen_slugs.add(slug)
                added += 1
                page_added += 1
            # Safety: break if endpoint repeats pages with no new info
            if page_added == 0 and page > 50:
                break
            page += 1
            if page > 400:
                break
        if year % 2 == 0:
            print(f"  year {year}: cumulative +{added}")
    return added


def _hydrate_missing_performances(
    shows: list[dict],
    show_roles: dict[str, list],
    min_year: int | None = None,
) -> int:
    """Backfill missing show.performance timestamps from /shows/{slug} details."""
    shows_by_slug = {s.get("slug"): s for s in shows if s.get("slug")}
    targets: list[str] = []
    for slug, show in shows_by_slug.items():
        if show.get("performances"):
            continue
        if not (show_roles.get(slug) or []):
            continue
        if min_year is not None:
            y = _slug_year_hint(slug)
            if y is None or y < min_year:
                continue
        targets.append(slug)

    if not targets:
        return 0

    print(f"Hydrating performances for {len(targets)} shows...")
    tls = threading.local()

    def init_worker():
        tls.client = CamdramClient()
        tls.client.authenticate()

    def fetch_show(slug: str) -> tuple[str, list] | None:
        try:
            detail = tls.client.get_show(slug)
            perfs = detail.get("performances") or []
            if perfs:
                return (slug, perfs)
        except Exception:
            return None
        return None

    updated = 0
    with ThreadPoolExecutor(max_workers=MAX_WORKERS, initializer=init_worker) as ex:
        futures = {ex.submit(fetch_show, slug): slug for slug in targets}
        for i, future in enumerate(as_completed(futures), 1):
            result = future.result()
            if result:
                slug, performances = result
                show_obj = shows_by_slug.get(slug)
                if show_obj is not None and not show_obj.get("performances"):
                    show_obj["performances"] = performances
                    updated += 1
            if i % 200 == 0:
                print(f"  Hydration progress: {i}/{len(targets)}")
    return updated


def _hydrate_missing_societies(
    shows: list[dict],
    show_roles: dict[str, list],
    min_year: int | None = None,
) -> int:
    """Backfill missing show society metadata from /shows/{slug} details."""
    shows_by_slug = {s.get("slug"): s for s in shows if s.get("slug")}
    targets: list[str] = []
    for slug, show in shows_by_slug.items():
        if show.get("societies"):
            continue
        if not (show_roles.get(slug) or []):
            continue
        if min_year is not None:
            y = _slug_year_hint(slug)
            if y is None or y < min_year:
                continue
        targets.append(slug)

    if not targets:
        return 0

    print(f"Hydrating societies for {len(targets)} shows...")
    tls = threading.local()

    def init_worker():
        tls.client = CamdramClient()
        tls.client.authenticate()

    def fetch_show(slug: str) -> tuple[str, list] | None:
        try:
            detail = tls.client.get_show(slug)
            societies = detail.get("societies") or []
            if societies:
                return (slug, societies)
        except Exception:
            return None
        return None

    updated = 0
    with ThreadPoolExecutor(max_workers=MAX_WORKERS, initializer=init_worker) as ex:
        futures = {ex.submit(fetch_show, slug): slug for slug in targets}
        for i, future in enumerate(as_completed(futures), 1):
            result = future.result()
            if result:
                slug, societies = result
                show_obj = shows_by_slug.get(slug)
                if show_obj is not None and not show_obj.get("societies"):
                    show_obj["societies"] = societies
                    updated += 1
            if i % 200 == 0:
                print(f"  Society hydration progress: {i}/{len(targets)}")
    return updated


def _hydrate_missing_venues(
    shows: list[dict],
    show_roles: dict[str, list],
    min_year: int | None = None,
) -> int:
    """Backfill missing show venue metadata from /shows/{slug} details."""
    shows_by_slug = {s.get("slug"): s for s in shows if s.get("slug")}
    targets: list[str] = []
    for slug, show in shows_by_slug.items():
        has_venues = bool(show.get("venues")) or bool(show.get("venue"))
        if has_venues:
            continue
        if not (show_roles.get(slug) or []):
            continue
        if min_year is not None:
            y = _slug_year_hint(slug)
            if y is None or y < min_year:
                continue
        targets.append(slug)

    if not targets:
        return 0

    print(f"Hydrating venues for {len(targets)} shows...")
    tls = threading.local()

    def init_worker():
        tls.client = CamdramClient()
        tls.client.authenticate()

    def fetch_show(slug: str) -> tuple[str, list] | None:
        try:
            detail = tls.client.get_show(slug)
            venues = detail.get("venues") or []
            if not venues:
                venue_single = detail.get("venue")
                if isinstance(venue_single, dict) and (venue_single.get("id") or venue_single.get("slug")):
                    venues = [venue_single]
            if not venues:
                # Most Camdram show payloads expose venue per performance.
                venue_map: dict[str, dict] = {}
                for perf in detail.get("performances", []) or []:
                    v = (perf or {}).get("venue")
                    if isinstance(v, dict):
                        key = str(v.get("id") or v.get("slug") or v.get("name") or "")
                        if key:
                            venue_map[key] = v
                venues = list(venue_map.values())
            if venues:
                return (slug, venues)
        except Exception:
            return None
        return None

    updated = 0
    with ThreadPoolExecutor(max_workers=MAX_WORKERS, initializer=init_worker) as ex:
        futures = {ex.submit(fetch_show, slug): slug for slug in targets}
        for i, future in enumerate(as_completed(futures), 1):
            result = future.result()
            if result:
                slug, venues = result
                show_obj = shows_by_slug.get(slug)
                if show_obj is not None and not (show_obj.get("venues") or show_obj.get("venue")):
                    show_obj["venues"] = venues
                    updated += 1
            if i % 200 == 0:
                print(f"  Venue hydration progress: {i}/{len(targets)}")
    return updated


def main() -> None:
    parser = argparse.ArgumentParser(description="Build/update rank_all_people cache.")
    parser.add_argument(
        "--refresh",
        action="store_true",
        help=(
            "Refetch full historical dataset. Also performs year-search crawl "
            f"(default back to {DEFAULT_SEARCH_BACK_TO_YEAR})."
        ),
    )
    parser.add_argument(
        "--update-current-future",
        action="store_true",
        help="Incrementally merge current/future shows into existing cache only.",
    )
    parser.add_argument(
        "--extend-back-to",
        type=str,
        default="",
        help="Extend existing cache backwards to this date (YYYY-MM-DD) without full refresh.",
    )
    parser.add_argument(
        "--crawl-diary-back-to",
        type=str,
        default="",
        help="Crawl global diary back to this date (YYYY-MM-DD) and merge missing shows.",
    )
    parser.add_argument(
        "--crawl-search-back-to-year",
        type=int,
        default=0,
        help="Crawl paginated show search by year from this year to now and merge missing shows.",
    )
    parser.add_argument(
        "--hydrate-missing-performances",
        action="store_true",
        help=(
            "Fetch show details to backfill missing performance timestamps in existing cache. "
            "Enabled by default on --refresh."
        ),
    )
    parser.add_argument(
        "--hydrate-missing-societies",
        action="store_true",
        help=(
            "Fetch show details to backfill missing society metadata in existing cache. "
            "Enabled by default on --refresh."
        ),
    )
    parser.add_argument(
        "--hydrate-missing-venues",
        action="store_true",
        help=(
            "Fetch show details to backfill missing venue metadata in existing cache. "
            "Enabled by default on --refresh."
        ),
    )
    parser.add_argument(
        "--hydrate-min-year",
        type=int,
        default=DEFAULT_SEARCH_BACK_TO_YEAR,
        help=(
            "Only hydrate shows with slug year >= this value "
            f"(default: {DEFAULT_SEARCH_BACK_TO_YEAR})."
        ),
    )
    parser.add_argument(
        "--lookback-days",
        type=int,
        default=CURRENT_LOOKBACK_DAYS,
        help=f"Days back for incremental update window (default: {CURRENT_LOOKBACK_DAYS}).",
    )
    parser.add_argument(
        "--lookahead-days",
        type=int,
        default=FUTURE_LOOKAHEAD_DAYS,
        help=f"Days forward for incremental update window (default: {FUTURE_LOOKAHEAD_DAYS}).",
    )
    args = parser.parse_args()

    force_refresh = args.refresh
    should_hydrate_performances = args.hydrate_missing_performances or force_refresh
    should_hydrate_societies = args.hydrate_missing_societies or force_refresh
    should_hydrate_venues = args.hydrate_missing_venues or force_refresh

    from_str = "2000-01-01"
    to_str = datetime.now().strftime("%Y-%m-%d")
    cache_from_str = from_str
    cache_to_str = to_str

    venues: list = []
    shows: list[dict] = []
    show_roles: dict[str, list] = {}

    if not force_refresh:
        cached = _load_cache()
        if cached:
            venues = cached.get("venues", [])
            shows = cached.get("shows", [])
            show_roles = cached.get("show_roles", {})
            cache_from_str = cached.get("from_date", cache_from_str)
            cache_to_str = cached.get("to_date", cache_to_str)
            print(f"Using cached data from {cached['cached_at'][:19]}")

    client = None
    if args.extend_back_to and shows:
        try:
            target_from = datetime.fromisoformat(args.extend_back_to).date()
        except ValueError:
            print("--extend-back-to must be YYYY-MM-DD", file=sys.stderr)
            sys.exit(2)
        try:
            current_from = datetime.fromisoformat(cache_from_str).date()
        except ValueError:
            current_from = datetime.fromisoformat(from_str).date()
        if target_from < current_from:
            client = CamdramClient()
            client.authenticate()
            extend_from_str = target_from.isoformat()
            extend_to_str = (current_from - timedelta(days=1)).isoformat()
            before_count = len(shows)
            venues = _merge_shows_for_window(
                client,
                venues,
                shows,
                extend_from_str,
                extend_to_str,
            )
            after_count = len(shows)
            cache_from_str = extend_from_str
            print(
                f"Historical backfill added {after_count - before_count} new shows "
                f"({extend_from_str} to {extend_to_str})."
            )
        else:
            print(
                f"No historical backfill needed (cache starts at {cache_from_str}, "
                f"target was {target_from.isoformat()})."
            )

    if args.crawl_diary_back_to and shows:
        try:
            diary_from = datetime.fromisoformat(args.crawl_diary_back_to).date().isoformat()
        except ValueError:
            print("--crawl-diary-back-to must be YYYY-MM-DD", file=sys.stderr)
            sys.exit(2)
        if client is None:
            client = CamdramClient()
            client.authenticate()
        before_count = len(shows)
        added = _merge_shows_from_diary(client, shows, diary_from, to_str)
        after_count = len(shows)
        if after_count != before_count + added:
            added = max(0, after_count - before_count)
        if diary_from < cache_from_str:
            cache_from_str = diary_from
        print(f"Diary crawl added {added} new shows.")

    # For full refresh, always include year-search crawl so sparse/missed
    # listings found via /search are merged in automatically.
    should_crawl_search = bool(args.crawl_search_back_to_year) or force_refresh
    did_crawl_search = False
    if should_crawl_search and shows:
        start_year = args.crawl_search_back_to_year or DEFAULT_SEARCH_BACK_TO_YEAR
        start_year = max(1900, int(start_year))
        end_year = datetime.now().year
        if client is None:
            client = CamdramClient()
            client.authenticate()
        added = _merge_shows_from_year_search(client, shows, start_year, end_year)
        if str(start_year) + "-01-01" < cache_from_str:
            cache_from_str = str(start_year) + "-01-01"
        print(f"Year-search crawl added {added} new shows.")
        did_crawl_search = True

    if args.update_current_future and shows:
        if client is None:
            client = CamdramClient()
            client.authenticate()
        now = datetime.now()
        update_from = (now - timedelta(days=max(0, args.lookback_days))).strftime("%Y-%m-%d")
        update_to = (now + timedelta(days=max(0, args.lookahead_days))).strftime("%Y-%m-%d")
        before_count = len(shows)
        venues = _merge_shows_for_window(client, venues, shows, update_from, update_to)
        after_count = len(shows)
        if update_to > cache_to_str:
            cache_to_str = update_to
        print(f"Incremental merge added {after_count - before_count} new shows.")

    if not shows:
        if args.extend_back_to:
            from_str = args.extend_back_to
            cache_from_str = from_str
        client = CamdramClient()
        client.authenticate()
        print(f"Fetching venues and diaries from {from_str} to {to_str}...")
        venues = client.get_venues()
        # Parallel venue diary fetch
        shows_seen: set[int] = set()
        shows_lock = threading.Lock()
        _diary_from, _diary_to = from_str, to_str
        tls = threading.local()

        def init_diary_worker():
            tls.client = CamdramClient()
            tls.client.authenticate()

        def fetch_venue_diary(venue: dict) -> list[dict]:
            slug = venue.get("slug")
            if not slug:
                return []
            try:
                diary = tls.client.get_venue_diary(
                    slug, from_date=_diary_from, to_date=_diary_to
                )
                return [e.get("show") for e in diary.get("events", []) if e.get("show")]
            except Exception:
                return []

        with ThreadPoolExecutor(max_workers=MAX_WORKERS, initializer=init_diary_worker) as ex:
            for venue_shows in ex.map(fetch_venue_diary, venues):
                for show in venue_shows:
                    if show and show.get("id"):
                        with shows_lock:
                            if show["id"] not in shows_seen:
                                shows_seen.add(show["id"])
                                shows.append(show)

        # Also fetch society shows (includes Edinburgh Fringe, international, etc.)
        print("Fetching society shows (includes non-Camdram venues)...")
        societies = client.get_societies()
        _soc_from, _soc_to = from_str, to_str

        def fetch_society_shows(society: dict) -> list[dict]:
            slug = society.get("slug")
            if not slug:
                return []
            try:
                return tls.client.get_society_shows(
                    slug, from_date=_soc_from, to_date=_soc_to
                )
            except Exception:
                return []

        with ThreadPoolExecutor(max_workers=MAX_WORKERS, initializer=init_diary_worker) as ex:
            for society_shows in ex.map(fetch_society_shows, societies):
                for show in society_shows or []:
                    if show and show.get("id"):
                        with shows_lock:
                            if show["id"] not in shows_seen:
                                shows_seen.add(show["id"])
                                shows.append(show)

        # Society diaries (may catch different performances)
        print("Fetching society diaries...")
        def fetch_society_diary(society: dict) -> list[dict]:
            slug = society.get("slug")
            if not slug:
                return []
            try:
                diary = tls.client.get_society_diary(
                    slug, from_date=_soc_from, to_date=_soc_to
                )
                return [e.get("show") for e in diary.get("events", []) if e.get("show")]
            except Exception:
                return []

        with ThreadPoolExecutor(max_workers=MAX_WORKERS, initializer=init_diary_worker) as ex:
            for diary_shows in ex.map(fetch_society_diary, societies):
                for show in diary_shows or []:
                    if show and show.get("id"):
                        with shows_lock:
                            if show["id"] not in shows_seen:
                                shows_seen.add(show["id"])
                                shows.append(show)

        # Venue shows (may differ from venue diary)
        print("Fetching venue shows...")
        def fetch_venue_shows(venue: dict) -> list[dict]:
            slug = venue.get("slug")
            if not slug:
                return []
            try:
                return tls.client.get_venue_shows(
                    slug, from_date=_diary_from, to_date=_diary_to
                )
            except Exception:
                return []

        with ThreadPoolExecutor(max_workers=MAX_WORKERS, initializer=init_diary_worker) as ex:
            for venue_show_list in ex.map(fetch_venue_shows, venues):
                for show in venue_show_list or []:
                    if show and show.get("id"):
                        with shows_lock:
                            if show["id"] not in shows_seen:
                                shows_seen.add(show["id"])
                                shows.append(show)

        # Paginate through /shows.json (global show list)
        print("Fetching shows via pagination...")
        page = 1
        while True:
            batch = client.get_shows(page=page, per_page=50)
            if not batch:
                break
            for show in batch:
                if show and show.get("id"):
                    with shows_lock:
                        if show["id"] not in shows_seen:
                            shows_seen.add(show["id"])
                            shows.append(show)
            if len(batch) < 50:
                break
            page += 1
            if page > 500:  # Safety limit
                break

    if should_crawl_search and shows and not did_crawl_search:
        start_year = args.crawl_search_back_to_year or DEFAULT_SEARCH_BACK_TO_YEAR
        start_year = max(1900, int(start_year))
        end_year = datetime.now().year
        if client is None:
            client = CamdramClient()
            client.authenticate()
        added = _merge_shows_from_year_search(client, shows, start_year, end_year)
        if str(start_year) + "-01-01" < cache_from_str:
            cache_from_str = str(start_year) + "-01-01"
        print(f"Year-search crawl added {added} new shows.")

    print(f"Found {len(shows)} shows. Fetching roles ({MAX_WORKERS} parallel)...\n")

    roles_to_fetch = [s for s in shows if s.get("slug") not in show_roles]
    should_save_cache = False
    if roles_to_fetch:
        show_roles_lock = threading.Lock()
        completed = [0]
        roles_tls = threading.local()

        def init_roles_worker():
            roles_tls.client = CamdramClient()
            roles_tls.client.authenticate()

        def fetch_roles(show: dict) -> tuple[str, list] | None:
            slug = show.get("slug")
            if not slug:
                return None
            try:
                roles = roles_tls.client.get_show_roles(slug)
                return (slug, roles)
            except Exception:
                return None

        with ThreadPoolExecutor(max_workers=MAX_WORKERS, initializer=init_roles_worker) as ex:
            futures = {ex.submit(fetch_roles, s): s for s in roles_to_fetch}
            for future in as_completed(futures):
                result = future.result()
                if result:
                    slug, roles = result
                    with show_roles_lock:
                        show_roles[slug] = roles
                        completed[0] += 1
                        if completed[0] % 200 == 0:
                            print(f"  Processed {completed[0]}/{len(roles_to_fetch)} shows...")
        should_save_cache = True
    else:
        print("  All roles loaded from cache.")
    hydrate_min_year = max(1900, int(args.hydrate_min_year)) if args.hydrate_min_year else None
    if should_hydrate_performances:
        hydrated = _hydrate_missing_performances(
            shows,
            show_roles,
            min_year=hydrate_min_year,
        )
        print(f"Hydrated {hydrated} shows with missing performance timestamps.")
        should_save_cache = True
    if should_hydrate_societies:
        hydrated_societies = _hydrate_missing_societies(
            shows,
            show_roles,
            min_year=hydrate_min_year,
        )
        print(f"Hydrated {hydrated_societies} shows with missing society metadata.")
        should_save_cache = True
    if should_hydrate_venues:
        hydrated_venues = _hydrate_missing_venues(
            shows,
            show_roles,
            min_year=hydrate_min_year,
        )
        print(f"Hydrated {hydrated_venues} shows with missing venue metadata.")
        should_save_cache = True

    if args.extend_back_to or args.update_current_future:
        should_save_cache = True

    if should_save_cache:
        _save_cache(venues, shows, show_roles, from_date=cache_from_str, to_date=cache_to_str)

    # Count roles per person
    person_role_count: dict[int, int] = {}
    person_name: dict[int, str] = {}
    for show in shows:
        slug = show.get("slug")
        for role in show_roles.get(slug, []):
            person = role.get("person", {})
            if not person:
                continue
            pid = person.get("id")
            if pid is None:
                continue
            person_role_count[pid] = person_role_count.get(pid, 0) + 1
            person_name[pid] = person.get("name", "Unknown")

    # Sort by role count descending
    ranked = sorted(
        ((pid, person_name[pid], count) for pid, count in person_role_count.items()),
        key=lambda x: (-x[2], x[1]),
    )

    print(f"\n=== Top 20 people by total roles (all of Camdram) ===\n")

    for i, (pid, name, count) in enumerate(ranked[:20], 1):
        line = f"  {i:2d}.  {count:4d}  {name}"
        try:
            print(line)
        except UnicodeEncodeError:
            print(line.encode("ascii", errors="replace").decode())


if __name__ == "__main__":
    main()
