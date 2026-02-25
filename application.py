"""
Flask app: Camdram people & role rankings.
Host on PythonAnywhere: set WSGI to application.application
When behind a reverse proxy (e.g. nginx at /visage/camdram), set X-Forwarded-Prefix
so url_for() and static links use the correct subpath.

Optimised: data is cached in memory (camdram_data). Index page loads data via
/api/bootstrap (client-side) so the initial HTML is small and fast.
"""

import json
import re
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from flask import Flask, render_template, jsonify, url_for, request, send_file, abort
from werkzeug.middleware.proxy_fix import ProxyFix

from camdram_data import (
    CACHE_FILE,
    SHARED_ROLES_CACHE,
    invalidate_cache,
    load_rankings,
    load_role_rankings,
    load_active_person_ids,
    load_recently_active_person_ids,
)
from role_normalization import canonicalize_role, categorize_role, main_group_for_category
from role_consolidation import load_consolidations, save_consolidations

app = Flask(__name__)
# Respect X-Forwarded-Prefix so links work when mounted at e.g. /visage/camdram/
app.wsgi_app = ProxyFix(app.wsgi_app, x_prefix=1)

_raw_role_counts_cache_key: tuple[str, float] | None = None
_raw_role_counts_cache_value: dict[str, int] | None = None
_society_rankings_cache_key: tuple[str, float] | None = None
_society_rankings_cache_value: list[dict] | None = None
_venue_rankings_cache_key: tuple[str, float] | None = None
_venue_rankings_cache_value: list[dict] | None = None
SUMMARY_PDF = Path(__file__).resolve().parent / "camdram_plaintext_summary.pdf"

SOCIETY_TARGETS = [
    {
        "key": "cuadc",
        "label": "CUADC",
        "slug": "cambridge-university-amateur-dramatic-club",
        "aliases": {"cambridge university amateur dramatic club", "cuadc"},
    },
    {
        "key": "fletcher-players",
        "label": "Fletcher Players",
        "slug": "the-fletcher-players-society",
        "aliases": {"the fletcher players society", "fletcher players"},
    },
    {
        "key": "bread",
        "label": "BREAD",
        "slug": "bread-theatre-film-company",
        "aliases": {"bread theatre & film company", "bread theatre and film company", "bread"},
    },
    {
        "key": "cumts",
        "label": "CUMTS",
        "slug": "cambridge-university-musical-theatre-society",
        "aliases": {"cambridge university musical theatre society", "cumts"},
    },
    {
        "key": "footlights",
        "label": "Footlights",
        "slug": "the-cambridge-footlights",
        "aliases": {"the cambridge footlights", "footlights"},
    },
    {
        "key": "gilbert-and-sullivan",
        "label": "G&S",
        "slug": "cambridge-university-gilbert-and-sullivan-society",
        "aliases": {
            "cambridge university gilbert and sullivan society",
            "gilbert and sullivan",
            "g&s",
        },
    },
]

VENUE_PINNED_TARGETS = [
    {"key": "adc-theatre", "label": "ADC", "slug": "adc-theatre"},
    {"key": "adc-theatre-bar", "label": "ADC Bar", "slug": "adc-theatre-bar"},
    {"key": "adc-theatre-larkum-studio", "label": "Larkum Studio", "slug": "adc-theatre-larkum-studio"},
    {"key": "corpus-playroom", "label": "Corpus", "slug": "corpus-playroom"},
    {"key": "fitzpatrick-hall", "label": "Fitzpat", "slug": "fitzpatrick-hall"},
    {"key": "the-minack-theatre", "label": "Minack", "slug": "the-minack-theatre"},
]


def _rankings_to_people(rankings):
    """Serialize rankings to list of dicts for JSON (shared by bootstrap + api/rankings)."""
    def _credit_range_text(first_credit: str, last_credit: str) -> str:
        if first_credit and last_credit:
            if first_credit == last_credit:
                return first_credit
            return f"{first_credit} - {last_credit}"
        return first_credit or last_credit or "—"

    return [
        {
            "pid": r[0],
            "name": r[1],
            "slug": r[2],
            "count": r[3],
            "top_role": r[4],
            "top_role_count": r[5],
            "num_shows": r[6],
            "num_titles": r[7],
            "top_pct": r[8],
            "top_subcategory": r[9],
            "top_subcategory_count": r[10],
            "top_category": r[11],
            "top_category_count": r[12],
            "first_credit_date": r[13] if len(r) > 13 else "",
            "last_credit_date": r[14] if len(r) > 14 else "",
            "credit_date_range": _credit_range_text(
                r[13] if len(r) > 13 else "",
                r[14] if len(r) > 14 else "",
            ),
        }
        for r in rankings
    ]

def _role_rankings_to_json(
    roles_list,
    role_rankings,
    include_count1_only_roles: bool = False,
    active_only: bool = False,
):
    """Serialize role data for JSON (shared by bootstrap + api/roles)."""
    min_people = 6  # "more than 5"
    active_ids = load_active_person_ids() if active_only else None
    roles = []
    for name, _n in roles_list:
        ranked = role_rankings.get(name, [])
        if active_ids is not None:
            ranked = [p for p in ranked if p[0] in active_ids]
        n = len(ranked)
        if n < min_people:
            continue
        # Exclude roles where every person has only done it once, unless requested.
        if (not include_count1_only_roles) and ranked and max((p[3] or 0) for p in ranked) <= 1:
            continue
        category = categorize_role(name)
        roles.append(
            {
                "name": name,
                "num_people": n,
                "category": category,
                "main_group": main_group_for_category(category),
            }
        )
    main_order = {"Tech": 0, "Prod": 1, "Cast": 2, "Band": 3}
    roles.sort(
        key=lambda r: (
            main_order.get(r["main_group"], 99),
            r["category"],
            -r["num_people"],
            r["name"].lower(),
        )
    )
    allowed_role_names = {r["name"] for r in roles}
    by_role = {
        name: [{"pid": p[0], "name": p[1], "slug": p[2], "count": p[3]} for p in rank]
        for name, rank in role_rankings.items()
        if name in allowed_role_names
    }
    return roles, by_role


@app.route("/")
def index():
    # Single cache hit to check has_data; no big serialisation for template
    has_data = len(load_rankings()) > 0
    # Never embed 20k rows: client fetches /api/bootstrap (cached) and builds UI
    return render_template(
        "index.html",
        has_data=has_data,
        people=[],
        roles=[],
        by_role={},
        bootstrap_url=url_for("api_bootstrap"),
        rankings_url=url_for("api_rankings"),
        roles_url=url_for("api_roles"),
        person_url_template=url_for("person_stats", pid=0),
        static_js_url=url_for("static", filename="js/app.js"),
    )


@app.route("/game")
def game():
    has_data = len(load_rankings()) > 0
    return render_template(
        "game.html",
        has_data=has_data,
        game_bootstrap_url=url_for("api_game_bootstrap"),
        static_game_js_url=url_for("static", filename="js/game.js"),
    )


@app.route("/role-organisation")
def role_organisation():
    has_data = len(load_rankings()) > 0
    return render_template(
        "role_organisation.html",
        has_data=has_data,
        role_org_bootstrap_url=url_for("api_role_consolidations"),
        role_org_update_url=url_for("api_role_consolidations_update"),
        role_org_delete_url=url_for("api_role_consolidations_delete"),
        static_role_org_js_url=url_for("static", filename="js/role_organisation.js"),
    )


def _load_cache_data() -> dict:
    cache_path = CACHE_FILE if CACHE_FILE.exists() else SHARED_ROLES_CACHE
    if not cache_path.exists():
        return {}
    try:
        return _load_json_file(cache_path)
    except (OSError, json.JSONDecodeError, ValueError):
        return {}


def _parse_show_date_range(show: dict) -> tuple[datetime | None, datetime | None]:
    first_dt: datetime | None = None
    last_dt: datetime | None = None
    for perf in show.get("performances", []) or []:
        start_at = (perf or {}).get("start_at")
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
        return first_dt, last_dt
    slug = (show.get("slug") or "").strip()
    m = re.search(r"(19|20)\d{2}", slug)
    if m:
        y = int(m.group(0))
        fallback = datetime(y, 1, 1, tzinfo=timezone.utc)
        return fallback, fallback
    return None, None


def _build_person_stats(pid: int) -> dict | None:
    data = _load_cache_data()
    if not data:
        return None
    shows = data.get("shows", []) or []
    show_roles = data.get("show_roles", {}) or {}
    show_map = {s.get("slug"): s for s in shows if s.get("slug")}

    total_credits = 0
    unique_shows: set[str] = set()
    role_counts: dict[str, int] = defaultdict(int)
    society_counts: dict[str, int] = defaultdict(int)
    venue_counts: dict[str, int] = defaultdict(int)
    year_counts: dict[int, int] = defaultdict(int)
    first_credit: datetime | None = None
    last_credit: datetime | None = None
    person_name = "Unknown"
    person_slug = ""
    recent_shows: list[dict] = []

    for show_slug, roles in show_roles.items():
        if not show_slug:
            continue
        show = show_map.get(show_slug, {})
        person_roles: list[str] = []
        for role_entry in roles or []:
            person = (role_entry or {}).get("person", {}) or {}
            role_pid = person.get("id")
            if role_pid != pid:
                continue
            person_name = person.get("name", person_name)
            person_slug = person.get("slug", person_slug)
            role_name = canonicalize_role((role_entry or {}).get("role") or "Unknown")
            if not role_name:
                role_name = "Unknown"
            role_counts[role_name] += 1
            person_roles.append(role_name)
            total_credits += 1

        if not person_roles:
            continue
        unique_shows.add(show_slug)
        start_dt, end_dt = _parse_show_date_range(show)
        if start_dt is not None:
            if first_credit is None or start_dt < first_credit:
                first_credit = start_dt
            if last_credit is None or end_dt > last_credit:
                last_credit = end_dt
            year_counts[end_dt.year] += 1
        for society in show.get("societies", []) or []:
            if not isinstance(society, dict):
                continue
            name = (society.get("name") or "").strip()
            if name:
                society_counts[name] += 1
        venues = show.get("venues") or []
        if not venues and isinstance(show.get("venue"), dict):
            venues = [show.get("venue")]
        for venue in venues:
            if not isinstance(venue, dict):
                continue
            name = (venue.get("name") or "").strip()
            if name:
                venue_counts[name] += 1
        recent_shows.append(
            {
                "name": show.get("name") or show_slug,
                "slug": show_slug,
                "roles": person_roles,
                "last_date": end_dt.date().isoformat() if end_dt is not None else "",
            }
        )

    if total_credits == 0:
        return None

    recent_shows.sort(
        key=lambda s: ((s.get("last_date") or ""), s.get("name") or ""),
        reverse=True,
    )
    span_years = 0.0
    if first_credit is not None and last_credit is not None:
        span_years = max(1.0, (last_credit - first_credit).days / 365.25)
    credits_per_year = (total_credits / span_years) if span_years > 0 else 0.0

    return {
        "pid": pid,
        "name": person_name,
        "slug": person_slug,
        "camdram_url": f"https://www.camdram.net/people/{person_slug}" if person_slug else "",
        "total_credits": total_credits,
        "unique_shows": len(unique_shows),
        "unique_roles": len(role_counts),
        "first_credit_date": first_credit.date().isoformat() if first_credit else "—",
        "last_credit_date": last_credit.date().isoformat() if last_credit else "—",
        "span_years": round(span_years, 2) if span_years else 0,
        "credits_per_year": round(credits_per_year, 2),
        "top_roles": sorted(role_counts.items(), key=lambda x: (-x[1], x[0]))[:15],
        "top_societies": sorted(society_counts.items(), key=lambda x: (-x[1], x[0]))[:10],
        "top_venues": sorted(venue_counts.items(), key=lambda x: (-x[1], x[0]))[:10],
        "by_year": sorted(year_counts.items(), key=lambda x: x[0], reverse=True),
        "recent_shows": recent_shows[:20],
    }


@app.route("/person/<int:pid>")
def person_stats(pid: int):
    stats = _build_person_stats(pid)
    if not stats:
        abort(404)
    return render_template("person.html", stats=stats)


@app.route("/summary-pdf")
def summary_pdf():
    if not SUMMARY_PDF.exists():
        return jsonify({"ok": False, "error": "Summary PDF not found"}), 404
    return send_file(
        SUMMARY_PDF,
        mimetype="application/pdf",
        as_attachment=True,
        download_name="camdram_plaintext_summary.pdf",
    )


def _load_json_file(path: Path) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _load_raw_role_counts() -> dict[str, int]:
    global _raw_role_counts_cache_key, _raw_role_counts_cache_value
    cache_path = CACHE_FILE if CACHE_FILE.exists() else SHARED_ROLES_CACHE
    if not cache_path.exists():
        return {}
    try:
        mtime = cache_path.stat().st_mtime
    except OSError:
        return {}
    key = (str(cache_path), mtime)
    if _raw_role_counts_cache_key == key and _raw_role_counts_cache_value is not None:
        return dict(_raw_role_counts_cache_value)
    try:
        data = _load_json_file(cache_path)
    except (OSError, json.JSONDecodeError, ValueError):
        return {}
    out: dict[str, int] = {}
    for role_entries in (data.get("show_roles", {}) or {}).values():
        for role_entry in role_entries or []:
            role_name = canonicalize_role((role_entry or {}).get("role") or "Unknown")
            if role_name is None:
                continue
            out[role_name] = out.get(role_name, 0) + 1
    _raw_role_counts_cache_key = key
    _raw_role_counts_cache_value = out
    return out


def _build_role_consolidation_payload() -> dict:
    role_counts = _load_raw_role_counts()
    available_roles = sorted(
        [{"name": name, "count": count} for name, count in role_counts.items()],
        key=lambda r: (-r["count"], (r["name"] or "").lower()),
    )
    mapping = load_consolidations()
    grouped: dict[str, list[str]] = {}
    for source, target in mapping.items():
        grouped.setdefault(target, []).append(source)

    consolidations = []
    available_set = set(role_counts.keys())
    for target, sources in sorted(grouped.items(), key=lambda x: x[0].casefold()):
        clean_sources = sorted({s for s in sources if s and s.casefold() != target.casefold()}, key=str.casefold)
        active_sources = [s for s in clean_sources if s in available_set]
        future_sources = [s for s in clean_sources if s not in available_set]
        consolidations.append(
            {
                "target": target,
                "sources": clean_sources,
                "active_sources": active_sources,
                "future_sources": future_sources,
            }
        )

    return {
        "available_roles": available_roles,
        "consolidations": consolidations,
        "total_mappings": len(mapping),
    }


@app.route("/api/role-consolidations")
def api_role_consolidations():
    return jsonify(_build_role_consolidation_payload())


@app.route("/api/role-consolidations/update", methods=["POST"])
def api_role_consolidations_update():
    payload = request.get_json(silent=True) or {}
    target_raw = payload.get("targetRole")
    source_roles_raw = payload.get("sourceRoles")
    if not isinstance(target_raw, str):
        return jsonify({"ok": False, "error": "targetRole must be a string"}), 400
    if not isinstance(source_roles_raw, list):
        return jsonify({"ok": False, "error": "sourceRoles must be a list"}), 400

    target = canonicalize_role(target_raw)
    if not target:
        return jsonify({"ok": False, "error": "targetRole is invalid"}), 400

    mapping = load_consolidations()
    changed = 0
    for source_raw in source_roles_raw:
        if not isinstance(source_raw, str):
            continue
        source = canonicalize_role(source_raw)
        if not source or source.casefold() == target.casefold():
            continue
        if mapping.get(source) != target:
            mapping[source] = target
            changed += 1

    if changed:
        save_consolidations(mapping)
        invalidate_cache()
        _invalidate_role_org_cache()
    return jsonify({"ok": True, "changed": changed, **_build_role_consolidation_payload()})


@app.route("/api/role-consolidations/delete", methods=["POST"])
def api_role_consolidations_delete():
    payload = request.get_json(silent=True) or {}
    mapping = load_consolidations()
    changed = 0

    source_raw = payload.get("sourceRole")
    target_raw = payload.get("targetRole")

    if isinstance(source_raw, str):
        source = canonicalize_role(source_raw)
        if source in mapping:
            del mapping[source]
            changed += 1
    elif isinstance(target_raw, str):
        target = canonicalize_role(target_raw)
        if target:
            to_remove = [source for source, mapped_target in mapping.items() if mapped_target.casefold() == target.casefold()]
            for source in to_remove:
                del mapping[source]
            changed += len(to_remove)
    else:
        return jsonify({"ok": False, "error": "sourceRole or targetRole required"}), 400

    if changed:
        save_consolidations(mapping)
        invalidate_cache()
        _invalidate_role_org_cache()
    return jsonify({"ok": True, "changed": changed, **_build_role_consolidation_payload()})


def _invalidate_role_org_cache() -> None:
    global _raw_role_counts_cache_key, _raw_role_counts_cache_value
    global _society_rankings_cache_key, _society_rankings_cache_value
    global _venue_rankings_cache_key, _venue_rankings_cache_value
    _raw_role_counts_cache_key = None
    _raw_role_counts_cache_value = None
    _society_rankings_cache_key = None
    _society_rankings_cache_value = None
    _venue_rankings_cache_key = None
    _venue_rankings_cache_value = None


def _load_society_rankings_top(limit: int = 15) -> list[dict]:
    global _society_rankings_cache_key, _society_rankings_cache_value
    cache_path = CACHE_FILE if CACHE_FILE.exists() else SHARED_ROLES_CACHE
    if not cache_path.exists():
        return []
    try:
        mtime = cache_path.stat().st_mtime
    except OSError:
        return []
    key = (str(cache_path), mtime)
    if _society_rankings_cache_key == key and _society_rankings_cache_value is not None:
        return _society_rankings_cache_value
    try:
        data = _load_json_file(cache_path)
    except (OSError, json.JSONDecodeError, ValueError):
        return []

    show_roles = data.get("show_roles", {}) or {}
    target_counts: dict[str, dict[int, set[str]]] = {
        target["key"]: defaultdict(set) for target in SOCIETY_TARGETS
    }
    person_names: dict[int, str] = {}
    person_slugs: dict[int, str] = {}
    slug_to_target = {target["slug"]: target["key"] for target in SOCIETY_TARGETS}

    for show in data.get("shows", []) or []:
        show_slug = show.get("slug")
        if not show_slug:
            continue
        societies = show.get("societies") or []
        matched_targets: set[str] = set()
        for society in societies:
            if not isinstance(society, dict):
                continue
            s_slug = (society.get("slug") or "").strip().lower()
            s_name = (society.get("name") or "").strip().lower()
            if s_slug in slug_to_target:
                matched_targets.add(slug_to_target[s_slug])
                continue
            for target in SOCIETY_TARGETS:
                if s_name in target["aliases"]:
                    matched_targets.add(target["key"])
        if not matched_targets:
            continue
        roles = show_roles.get(show_slug, []) or []
        show_people: set[int] = set()
        for role_entry in roles:
            person = (role_entry or {}).get("person", {}) or {}
            pid = person.get("id")
            if not isinstance(pid, int):
                continue
            show_people.add(pid)
            person_names[pid] = person.get("name", "Unknown")
            person_slugs[pid] = person.get("slug", "")
        for target_key in matched_targets:
            for pid in show_people:
                target_counts[target_key][pid].add(show_slug)

    out: list[dict] = []
    for target in SOCIETY_TARGETS:
        counts_map = target_counts.get(target["key"], {})
        ranked = sorted(
            counts_map.items(),
            key=lambda item: (
                -len(item[1]),
                (person_names.get(item[0], "Unknown") or "").lower(),
                item[0],
            ),
        )
        out.append(
            {
                "key": target["key"],
                "label": target["label"],
                "top": [
                    {
                        "pid": pid,
                        "name": person_names.get(pid, "Unknown"),
                        "slug": person_slugs.get(pid, ""),
                        "count": len(show_set),
                    }
                    for pid, show_set in ranked[:limit]
                ],
            }
        )

    _society_rankings_cache_key = key
    _society_rankings_cache_value = out
    return out


def _extract_show_venues(show: dict) -> list[dict]:
    venues = show.get("venues") or []
    if venues:
        return [v for v in venues if isinstance(v, dict)]
    venue_single = show.get("venue")
    if isinstance(venue_single, dict):
        return [venue_single]
    return []


def _load_venue_rankings_top(limit: int = 15) -> list[dict]:
    global _venue_rankings_cache_key, _venue_rankings_cache_value
    cache_path = CACHE_FILE if CACHE_FILE.exists() else SHARED_ROLES_CACHE
    if not cache_path.exists():
        return []
    try:
        mtime = cache_path.stat().st_mtime
    except OSError:
        return []
    key = (str(cache_path), mtime)
    if _venue_rankings_cache_key == key and _venue_rankings_cache_value is not None:
        return _venue_rankings_cache_value
    try:
        data = _load_json_file(cache_path)
    except (OSError, json.JSONDecodeError, ValueError):
        return []

    show_roles = data.get("show_roles", {}) or {}
    person_names: dict[int, str] = {}
    person_slugs: dict[int, str] = {}
    venue_person_showsets: dict[str, dict[int, set[str]]] = defaultdict(lambda: defaultdict(set))
    venue_show_counts: dict[str, int] = defaultdict(int)
    venue_labels: dict[str, str] = {}

    for show in data.get("shows", []) or []:
        show_slug = show.get("slug")
        if not show_slug:
            continue
        roles = show_roles.get(show_slug, []) or []
        if not roles:
            continue
        show_people: set[int] = set()
        for role_entry in roles:
            person = (role_entry or {}).get("person", {}) or {}
            pid = person.get("id")
            if not isinstance(pid, int):
                continue
            show_people.add(pid)
            person_names[pid] = person.get("name", "Unknown")
            person_slugs[pid] = person.get("slug", "")
        if not show_people:
            continue
        seen_venues: set[str] = set()
        for venue in _extract_show_venues(show):
            v_slug = (venue.get("slug") or "").strip().lower()
            v_name = (venue.get("name") or "").strip()
            venue_key = v_slug or v_name.lower()
            if not venue_key or venue_key in seen_venues:
                continue
            seen_venues.add(venue_key)
            if v_name:
                venue_labels[venue_key] = v_name
            venue_show_counts[venue_key] += 1
            for pid in show_people:
                venue_person_showsets[venue_key][pid].add(show_slug)

    pinned_by_key = {v["key"]: v for v in VENUE_PINNED_TARGETS}
    pinned_keys = set(pinned_by_key.keys())
    excluded_from_dynamic = set(pinned_keys)
    for k in list(venue_person_showsets.keys()):
        for pinned in pinned_keys:
            if k.startswith(pinned + "-"):
                excluded_from_dynamic.add(k)

    dynamic_keys = sorted(
        [k for k in venue_person_showsets.keys() if k not in excluded_from_dynamic],
        key=lambda k: (-venue_show_counts.get(k, 0), (venue_labels.get(k, k) or k).lower()),
    )
    selected_keys = [v["key"] for v in VENUE_PINNED_TARGETS if v["key"] in venue_person_showsets]
    selected_keys.extend(dynamic_keys[:6])

    out: list[dict] = []
    for venue_key in selected_keys:
        counts_map = venue_person_showsets.get(venue_key, {})
        ranked = sorted(
            counts_map.items(),
            key=lambda item: (
                -len(item[1]),
                (person_names.get(item[0], "Unknown") or "").lower(),
                item[0],
            ),
        )
        label = pinned_by_key.get(venue_key, {}).get("label") or venue_labels.get(venue_key, venue_key)
        out.append(
            {
                "key": venue_key,
                "label": label,
                "venue_name": venue_labels.get(venue_key, label),
                "show_count": venue_show_counts.get(venue_key, 0),
                "top": [
                    {
                        "pid": pid,
                        "name": person_names.get(pid, "Unknown"),
                        "slug": person_slugs.get(pid, ""),
                        "count": len(show_set),
                    }
                    for pid, show_set in ranked[:limit]
                ],
            }
        )

    _venue_rankings_cache_key = key
    _venue_rankings_cache_value = out
    return out


@app.route("/api/bootstrap")
def api_bootstrap():
    """Lightweight: roles, byRole, totalPeople. People loaded via paginated /api/rankings."""
    rankings = load_rankings()
    if not rankings:
        return jsonify({"totalPeople": 0, "roles": [], "byRole": {}})
    roles_list, role_rankings = load_role_rankings()
    roles, by_role = _role_rankings_to_json(roles_list, role_rankings, include_count1_only_roles=False)
    return jsonify(
        totalPeople=len(rankings),
        roles=roles,
        byRole=by_role,
        societyTop=_load_society_rankings_top(limit=15),
        venueTop=_load_venue_rankings_top(limit=15),
    )


@app.route("/api/game/bootstrap")
def api_game_bootstrap():
    """Game payload filtered to people active in the last year."""
    rankings = load_rankings()
    if not rankings:
        return jsonify({"roles": [], "byRole": {}, "recentActivePeople": 0})
    roles_list, role_rankings = load_role_rankings()
    roles, by_role = _role_rankings_to_json(roles_list, role_rankings, include_count1_only_roles=False)
    allowed_ids = load_recently_active_person_ids(years=1)
    filtered_by_role = {}
    for role_name, people in by_role.items():
        ranked = [p for p in people if p.get("pid") in allowed_ids]
        if len(ranked) >= 3:
            filtered_by_role[role_name] = ranked
    filtered_roles = []
    for role in roles:
        role_name = role.get("name")
        if role_name not in filtered_by_role:
            continue
        new_role = dict(role)
        new_role["num_people"] = len(filtered_by_role[role_name])
        filtered_roles.append(new_role)
    return jsonify(
        roles=filtered_roles,
        byRole=filtered_by_role,
        recentActivePeople=len(allowed_ids),
    )


def _filter_rankings(rankings, search: str):
    """Filter rankings by name (case-insensitive) if search given."""
    if not search or not search.strip():
        return rankings
    q = search.strip().lower()
    return [r for r in rankings if (r[1] or "").lower().find(q) >= 0]


def _parse_bool_arg(value: str) -> bool:
    return (value or "").strip().lower() in {"1", "true", "yes", "on"}


def _sort_rankings(rankings, sort_col: str, sort_dir: str):
    """Sort rankings by supported columns, with stable name/id tiebreakers."""
    allowed_cols = {
        "count",
        "num_shows",
        "num_titles",
        "name",
        "last_credit_date",
        "top_role",
        "top_subcategory",
        "top_category",
    }
    col = sort_col if sort_col in allowed_cols else "count"
    descending = (sort_dir or "").strip().lower() != "asc"

    # Stable tiebreaker so paging stays deterministic.
    out = sorted(rankings, key=lambda r: ((r[1] or "").lower(), r[0]))

    if col == "name":
        return sorted(out, key=lambda r: ((r[1] or "").lower(), r[0]), reverse=descending)
    if col == "last_credit_date":
        with_dates = [r for r in out if len(r) > 14 and (r[14] or "")]
        without_dates = [r for r in out if not (len(r) > 14 and (r[14] or ""))]
        with_dates = sorted(
            with_dates,
            key=lambda r: (
                r[14] or "",
                r[13] or "",
                (r[1] or "").lower(),
                r[0],
            ),
            reverse=descending,
        )
        return with_dates + without_dates
    if col == "top_role":
        # Sort by role popularity first (how many people have done that role),
        # then by each person's top-role count.
        roles_list, _ = load_role_rankings()
        role_people_count = {name: n for name, n in roles_list}
        return sorted(
            out,
            key=lambda r: (
                role_people_count.get(r[4], 0),
                r[5] or 0,
                (r[4] or "").lower(),
                (r[1] or "").lower(),
                r[0],
            ),
            reverse=descending,
        )
    if col == "num_shows":
        return sorted(out, key=lambda r: r[6] or 0, reverse=descending)
    if col == "num_titles":
        return sorted(out, key=lambda r: r[7] or 0, reverse=descending)
    if col == "top_subcategory":
        return sorted(
            out,
            key=lambda r: (
                r[10] or 0,
                (r[9] or "").lower(),
                (r[1] or "").lower(),
                r[0],
            ),
            reverse=descending,
        )
    if col == "top_category":
        return sorted(
            out,
            key=lambda r: (
                r[12] or 0,
                (r[11] or "").lower(),
                (r[1] or "").lower(),
                r[0],
            ),
            reverse=descending,
        )
    # default: count
    return sorted(out, key=lambda r: r[3] or 0, reverse=descending)


@app.route("/api/rankings")
def api_rankings():
    """Paginated list. Optional: ?page=1&per_page=100&search=name&active_only=1&sort_col=count&sort_dir=desc."""
    rankings = load_rankings()
    active_only = _parse_bool_arg(request.args.get("active_only"))
    if active_only:
        active_ids = load_active_person_ids()
        rankings = [r for r in rankings if r[0] in active_ids]
    search = (request.args.get("search") or "").strip()
    rankings = _filter_rankings(rankings, search)
    sort_col = (request.args.get("sort_col") or "count").strip()
    sort_dir = (request.args.get("sort_dir") or "desc").strip()
    rankings = _sort_rankings(rankings, sort_col, sort_dir)
    total = len(rankings)
    per_page = min(max(1, request.args.get("per_page", 100, type=int)), 500)
    page = max(1, request.args.get("page", 1, type=int))
    start = (page - 1) * per_page
    slice_ = rankings[start : start + per_page]
    return jsonify(
        people=_rankings_to_people(slice_),
        total=total,
        page=page,
        per_page=per_page,
    )


@app.route("/api/roles")
def api_roles():
    roles_list, role_rankings = load_role_rankings()
    include_count1 = _parse_bool_arg(request.args.get("include_count1"))
    active_only = _parse_bool_arg(request.args.get("active_only"))
    roles, by_role = _role_rankings_to_json(
        roles_list,
        role_rankings,
        include_count1_only_roles=include_count1,
        active_only=active_only,
    )
    return jsonify({"roles": roles, "by_role": by_role})


application = app  # PythonAnywhere looks for "application"

if __name__ == "__main__":
    import os
    port = int(os.environ.get("PORT", 5002))
    app.run(host="127.0.0.1", port=port)
