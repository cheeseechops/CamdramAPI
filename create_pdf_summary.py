"""
Create a plaintext PDF summary from rank_all_people_cache.json.

Content:
- By-person summary data (paginated).
- Role-focused summary for requested roles (paginated, no role section split).
"""

from __future__ import annotations

import argparse
import itertools
import json
import re
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

from reportlab.lib.pagesizes import landscape, letter
from reportlab.pdfgen import canvas

from role_normalization import canonicalize_role

ROLE_GROUPS = {
    "Lighting Designer": {"Lighting Designer", "Lighting Design"},
    "CLX (Chief Electrician)": {"Chief Electrician"},
    "Sound Designer/Engineer": {
        "Sound Designer",
        "Sound Engineer",
        "Sound Design",
        "Assistant Sound Designer",
        "Associate Sound Designer",
        "Lighting & Sound Designer",
    },
    "DSM": {"Deputy Stage Manager"},
    "SM": {"Stage Manager"},
    "ASM": {"Assistant Stage Manager"},
    "TD": {"Technical Director"},
    "Director": {"Director"},
    "Producer": {"Producer"},
    "Photographer": {"Photographer"},
    "Publicity": {
        "Publicity (General)",
        "Publicity Designer",
        "Publicity Design",
        "Publicity Manager",
        "Publicity Officer",
        "Graphic Designer",
        "Poster Designer",
        "Programme Designer",
        "Web Designer",
    },
    "Welfare": {"Welfare"},
}
SOCIETY_TARGETS = [
    ("CUADC", "cambridge-university-amateur-dramatic-club"),
    ("Fletcher Players", "the-fletcher-players-society"),
    ("BREAD", "bread-theatre-film-company"),
    ("CUMTS", "cambridge-university-musical-theatre-society"),
    ("Footlights", "the-cambridge-footlights"),
    ("G&S", "cambridge-university-gilbert-and-sullivan-society"),
]
VENUE_PINNED_TARGETS = [
    ("ADC", "adc-theatre"),
    ("ADC Bar", "adc-theatre-bar"),
    ("Larkum Studio", "adc-theatre-larkum-studio"),
    ("Corpus", "corpus-playroom"),
    ("Fitzpat", "fitzpatrick-hall"),
    ("Minack", "the-minack-theatre"),
]

PAGE_SIZE = landscape(letter)
MARGIN_X = 40
MARGIN_TOP = 40
LINE_HEIGHT = 12
ROLE_COLUMNS = 3
ROLE_COLUMN_GUTTER = 20
ROLE_TITLE_CLEARANCE_LINES = 3


def _page_body_line_capacity() -> int:
    _width, height = PAGE_SIZE
    # Reserve 2 lines for title + blank line.
    return int((height - (2 * MARGIN_TOP)) / LINE_HEIGHT) - 2


def draw_plaintext_page(pdf: canvas.Canvas, title: str, lines: list[str]) -> None:
    _width, height = PAGE_SIZE

    text = pdf.beginText(MARGIN_X, height - MARGIN_TOP)
    text.setFont("Courier-Bold", 12)
    text.textLine(title)
    text.textLine("")
    text.setFont("Courier", 10)

    for line in lines:
        text.textLine(line)

    pdf.drawText(text)
    pdf.showPage()


def _draw_three_column_page(
    pdf: canvas.Canvas,
    title: str,
    page_num: int,
    column_lines: list[list[str]],
) -> None:
    width, height = PAGE_SIZE
    page_title = title if page_num == 1 else f"{title} (cont. {page_num})"
    pdf.setFont("Courier-Bold", 12)
    pdf.drawString(MARGIN_X, height - MARGIN_TOP, page_title)

    # Keep body safely below title.
    body_start_y = height - MARGIN_TOP - (ROLE_TITLE_CLEARANCE_LINES * LINE_HEIGHT)
    usable_width = width - (2 * MARGIN_X) - ((ROLE_COLUMNS - 1) * ROLE_COLUMN_GUTTER)
    column_width = usable_width / ROLE_COLUMNS

    for col_idx in range(ROLE_COLUMNS):
        start_x = MARGIN_X + col_idx * (column_width + ROLE_COLUMN_GUTTER)
        text = pdf.beginText(start_x, body_start_y)
        text.setFont("Courier", 10)
        for line in column_lines[col_idx]:
            text.textLine(line)
        pdf.drawText(text)

    pdf.showPage()


def draw_role_sections_three_columns_no_split(
    pdf: canvas.Canvas,
    title: str,
    intro_lines: list[str],
    role_sections: list[tuple[str, list[str]]],
) -> None:
    capacity = _page_body_line_capacity()
    page_num = 1
    current_col = 0
    page_columns: list[list[str]] = [[] for _ in range(ROLE_COLUMNS)]
    for section_title, section_lines in role_sections:
        block = [f"{section_title}:"] + section_lines + [""]

        # Keep each role section in one column (and therefore on one page).
        if len(block) > capacity:
            block = block[:capacity]

        placed = False
        while not placed:
            if len(page_columns[current_col]) + len(block) <= capacity:
                page_columns[current_col].extend(block)
                placed = True
                continue

            current_col += 1
            if current_col >= ROLE_COLUMNS:
                _draw_three_column_page(pdf, title, page_num, page_columns)
                page_num += 1
                page_columns = [[] for _ in range(ROLE_COLUMNS)]
                current_col = 0

    if any(page_columns[col] for col in range(ROLE_COLUMNS)) or page_num == 1:
        _draw_three_column_page(pdf, title, page_num, page_columns)


def draw_sections_single_column_paginated(
    pdf: canvas.Canvas,
    title: str,
    sections: list[tuple[str, list[str]]],
) -> None:
    capacity = _page_body_line_capacity()
    max_chars = 110
    all_lines: list[str] = []
    for section_title, section_lines in sections:
        all_lines.append(f"{section_title}:")
        for line in section_lines:
            all_lines.append((line or "")[:max_chars])
        all_lines.append("")

    if not all_lines:
        draw_plaintext_page(pdf, title, [])
        return

    page_num = 1
    for i in range(0, len(all_lines), capacity):
        page_title = title if page_num == 1 else f"{title} (cont. {page_num})"
        draw_plaintext_page(pdf, page_title, all_lines[i : i + capacity])
        page_num += 1


def _draw_sections_three_by_two_page(
    pdf: canvas.Canvas,
    title: str,
    page_num: int,
    sections: list[tuple[str, list[str]]],
) -> None:
    width, height = PAGE_SIZE
    page_title = title if page_num == 1 else f"{title} (cont. {page_num})"
    pdf.setFont("Courier-Bold", 12)
    pdf.drawString(MARGIN_X, height - MARGIN_TOP, page_title)

    cols = 3
    rows = 2
    row_gap = LINE_HEIGHT
    body_top = height - MARGIN_TOP - (ROLE_TITLE_CLEARANCE_LINES * LINE_HEIGHT)
    body_bottom = MARGIN_TOP
    body_height = max(LINE_HEIGHT * rows, body_top - body_bottom)
    usable_width = width - (2 * MARGIN_X) - ((cols - 1) * ROLE_COLUMN_GUTTER)
    cell_width = usable_width / cols
    cell_height = (body_height - row_gap) / rows
    max_lines = max(3, int(cell_height // LINE_HEIGHT) - 1)
    max_chars = max(24, int(cell_width // 6) - 2)

    for idx, (section_title, section_lines) in enumerate(sections[: cols * rows]):
        row = idx // cols
        col = idx % cols
        x = MARGIN_X + col * (cell_width + ROLE_COLUMN_GUTTER)
        top_y = body_top - row * (cell_height + row_gap)
        lines = [f"{section_title}:"] + section_lines
        clipped = [line[:max_chars] for line in lines]
        if len(clipped) > max_lines:
            clipped = clipped[: max_lines - 1] + ["..."]
        text = pdf.beginText(x, top_y)
        text.setFont("Courier", 10)
        for line in clipped:
            text.textLine(line)
        pdf.drawText(text)

    pdf.showPage()


def draw_sections_three_by_two_paginated(
    pdf: canvas.Canvas,
    title: str,
    sections: list[tuple[str, list[str]]],
) -> None:
    if not sections:
        _draw_sections_three_by_two_page(pdf, title, 1, [])
        return
    page_num = 1
    for i in range(0, len(sections), 6):
        _draw_sections_three_by_two_page(pdf, title, page_num, sections[i : i + 6])
        page_num += 1


def build_summaries(
    cache_data: dict,
    recent_last_role_years: int | None = None,
) -> tuple[list[str], list[str], list[tuple[str, list[str]]], list[str]]:
    shows = cache_data.get("shows", [])
    show_roles = cache_data.get("show_roles", {})
    from_date = cache_data.get("from_date", "unknown")
    to_date = cache_data.get("to_date", "unknown")
    cached_at = cache_data.get("cached_at", "unknown")

    person_name: dict[int, str] = {}
    person_total_roles: Counter[int] = Counter()
    person_show_ids: dict[int, set[int]] = defaultdict(set)
    person_role_breakdown: dict[int, Counter[str]] = defaultdict(Counter)
    role_group_counts: dict[str, Counter[int]] = {group: Counter() for group in ROLE_GROUPS}

    show_id_by_slug = {s.get("slug"): s.get("id") for s in shows if s.get("slug")}
    show_last_perf: dict[str, datetime] = {}
    show_year_hint: dict[str, int] = {}
    for show in shows:
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

    allowed_pids: set[int] | None = None
    cutoff_text = ""
    if recent_last_role_years is not None and recent_last_role_years > 0:
        now = datetime.now(timezone.utc)
        cutoff = now - timedelta(days=365 * recent_last_role_years)
        person_last_role: dict[int, datetime] = {}
        person_last_year_hint: dict[int, int] = {}
        for show_slug, roles in show_roles.items():
            show_dt = show_last_perf.get(show_slug)
            year_hint = show_year_hint.get(show_slug)
            if show_dt is None and year_hint is None:
                continue
            for role in roles:
                person = role.get("person") or {}
                pid = person.get("id")
                if pid is None:
                    continue
                if show_dt is not None:
                    existing = person_last_role.get(pid)
                    if existing is None or show_dt > existing:
                        person_last_role[pid] = show_dt
                else:
                    prev_year = person_last_year_hint.get(pid, 0)
                    if year_hint and year_hint > prev_year:
                        person_last_year_hint[pid] = year_hint
        allowed_pids = {pid for pid, last_dt in person_last_role.items() if last_dt >= cutoff}
        cutoff_year = cutoff.year
        for pid, year_hint in person_last_year_hint.items():
            if pid in allowed_pids:
                continue
            if year_hint >= cutoff_year:
                allowed_pids.add(pid)
        cutoff_text = cutoff.date().isoformat()

    total_role_entries = 0
    for show_slug, roles in show_roles.items():
        show_id = show_id_by_slug.get(show_slug)
        for role in roles:
            person = role.get("person") or {}
            pid = person.get("id")
            if pid is None:
                continue
            if allowed_pids is not None and pid not in allowed_pids:
                continue

            total_role_entries += 1
            person_name[pid] = person.get("name", "Unknown")
            person_total_roles[pid] += 1
            if show_id is not None:
                person_show_ids[pid].add(show_id)

            canonical = canonicalize_role(role.get("role", "")) or "Unknown"
            person_role_breakdown[pid][canonical] += 1

            for group, role_names in ROLE_GROUPS.items():
                if canonical in role_names:
                    role_group_counts[group][pid] += 1

    by_person_lines: list[str] = [
        f"Date range: {from_date} to {to_date}",
        f"Cache timestamp: {cached_at}",
        f"Total shows: {len(shows)}",
        f"Total role entries: {total_role_entries}",
        f"Unique people: {len(person_total_roles)}",
    ]
    if allowed_pids is not None:
        by_person_lines.append(
            f"Filter: most recent role within last {recent_last_role_years} year(s) (since {cutoff_text})"
        )
    by_person_lines.extend(["", "Top people by total role count:"])

    ranked_people = sorted(
        person_total_roles.items(),
        key=lambda item: (-item[1], person_name.get(item[0], "Unknown").lower()),
    )

    for idx, (pid, total_roles) in enumerate(ranked_people, start=1):
        name = person_name.get(pid, "Unknown")
        num_shows = len(person_show_ids.get(pid, set()))
        top_roles = person_role_breakdown.get(pid, Counter()).most_common(2)
        if top_roles:
            top_role_text = ", ".join(f"{role}({count})" for role, count in top_roles)
        else:
            top_role_text = "None"
        by_person_lines.append(
            f"{idx:>2}. {name[:26]:<26} roles={total_roles:<4} shows={num_shows:<4} top={top_role_text}"
        )

    role_intro_lines: list[str] = []
    role_sections: list[tuple[str, list[str]]] = []

    for group_name, _ in ROLE_GROUPS.items():
        ranked_for_group = sorted(
            role_group_counts[group_name].items(),
            key=lambda item: (-item[1], person_name.get(item[0], "Unknown").lower()),
        )
        section_lines: list[str] = []
        if not ranked_for_group:
            section_lines.append("  - No matching records")
            role_sections.append((group_name, section_lines))
            continue

        for idx, (pid, count) in enumerate(ranked_for_group[:15], start=1):
            section_lines.append(f"  {idx}. {person_name.get(pid, 'Unknown')} ({count})")
        role_sections.append((group_name, section_lines))

    pair_counts: Counter[tuple[int, int]] = Counter()
    pair_role_breakdown: dict[tuple[int, int], Counter[str]] = defaultdict(Counter)

    for _show_slug, roles in show_roles.items():
        role_to_people: dict[str, set[int]] = defaultdict(set)
        for role in roles:
            person = role.get("person") or {}
            pid = person.get("id")
            if pid is None:
                continue
            if allowed_pids is not None and pid not in allowed_pids:
                continue
            canonical = canonicalize_role(role.get("role", ""))
            if canonical is None:
                continue
            role_to_people[canonical].add(pid)

        for canonical_role, pid_set in role_to_people.items():
            people = sorted(pid_set)
            if 2 <= len(people) <= 3:
                for pid_a, pid_b in itertools.combinations(people, 2):
                    pair = (pid_a, pid_b)
                    pair_counts[pair] += 1
                    pair_role_breakdown[pair][canonical_role] += 1

    pair_lines: list[str] = [
        "Pairs with most shared roles (only role groups of size 2 or 3):",
        "",
    ]
    ranked_pairs = sorted(
        pair_counts.items(),
        key=lambda item: (
            -item[1],
            person_name.get(item[0][0], "Unknown").lower(),
            person_name.get(item[0][1], "Unknown").lower(),
        ),
    )
    if not ranked_pairs:
        pair_lines.append("No qualifying pairs found.")
    else:
        for idx, ((pid_a, pid_b), count) in enumerate(ranked_pairs, start=1):
            name_a = person_name.get(pid_a, "Unknown")
            name_b = person_name.get(pid_b, "Unknown")
            top_shared_roles = pair_role_breakdown[(pid_a, pid_b)].most_common(2)
            top_roles_text = ", ".join(f"{role}({n})" for role, n in top_shared_roles)
            pair_lines.append(
                f"{idx:>2}. {name_a[:20]:<20} & {name_b[:20]:<20} shared={count:<3} top={top_roles_text}"
            )

    return by_person_lines, role_intro_lines, role_sections, pair_lines


def build_society_sections(cache_data: dict) -> list[tuple[str, list[str]]]:
    shows = cache_data.get("shows", []) or []
    show_roles = cache_data.get("show_roles", {}) or {}
    society_counts: dict[str, dict[int, set[str]]] = {
        label: defaultdict(set) for label, _slug in SOCIETY_TARGETS
    }
    person_name: dict[int, str] = {}
    slug_to_label = {slug: label for label, slug in SOCIETY_TARGETS}

    for show in shows:
        show_slug = show.get("slug")
        if not show_slug:
            continue
        matched_labels: set[str] = set()
        for society in show.get("societies", []) or []:
            s_slug = (society or {}).get("slug")
            if s_slug in slug_to_label:
                matched_labels.add(slug_to_label[s_slug])
        if not matched_labels:
            continue
        show_people: set[int] = set()
        for role in show_roles.get(show_slug, []) or []:
            person = role.get("person") or {}
            pid = person.get("id")
            if pid is None:
                continue
            show_people.add(pid)
            person_name[pid] = person.get("name", "Unknown")
        for label in matched_labels:
            for pid in show_people:
                society_counts[label][pid].add(show_slug)

    sections: list[tuple[str, list[str]]] = []
    for label, _slug in SOCIETY_TARGETS:
        ranked = sorted(
            society_counts[label].items(),
            key=lambda item: (-len(item[1]), person_name.get(item[0], "Unknown").lower()),
        )
        lines: list[str] = []
        if not ranked:
            lines.append("  - No matching records")
        else:
            for idx, (pid, show_set) in enumerate(ranked[:15], start=1):
                lines.append(f"  {idx}. {person_name.get(pid, 'Unknown')} ({len(show_set)})")
        sections.append((label, lines))
    return sections


def build_venue_sections(cache_data: dict, top_n_people: int = 15) -> list[tuple[str, list[str]]]:
    shows = cache_data.get("shows", []) or []
    show_roles = cache_data.get("show_roles", {}) or {}
    person_name: dict[int, str] = {}
    venue_person_showsets: dict[str, dict[int, set[str]]] = defaultdict(lambda: defaultdict(set))
    venue_show_counts: Counter[str] = Counter()
    venue_labels: dict[str, str] = {}

    for show in shows:
        show_slug = show.get("slug")
        if not show_slug:
            continue
        roles = show_roles.get(show_slug, []) or []
        if not roles:
            continue
        show_people: set[int] = set()
        for role in roles:
            person = role.get("person") or {}
            pid = person.get("id")
            if pid is None:
                continue
            show_people.add(pid)
            person_name[pid] = person.get("name", "Unknown")
        if not show_people:
            continue
        venues = show.get("venues") or []
        if not venues and isinstance(show.get("venue"), dict):
            venues = [show.get("venue")]
        seen_keys: set[str] = set()
        for venue in venues:
            if not isinstance(venue, dict):
                continue
            v_slug = (venue.get("slug") or "").strip().lower()
            v_name = (venue.get("name") or "").strip()
            venue_key = v_slug or v_name.lower()
            if not venue_key or venue_key in seen_keys:
                continue
            seen_keys.add(venue_key)
            if v_name:
                venue_labels[venue_key] = v_name
            venue_show_counts[venue_key] += 1
            for pid in show_people:
                venue_person_showsets[venue_key][pid].add(show_slug)

    pinned_keys = [slug for _label, slug in VENUE_PINNED_TARGETS]
    excluded_from_dynamic = set(pinned_keys)
    for key in venue_person_showsets.keys():
        for pinned in pinned_keys:
            if key.startswith(pinned + "-"):
                excluded_from_dynamic.add(key)
    dynamic_keys = sorted(
        [k for k in venue_person_showsets.keys() if k not in excluded_from_dynamic],
        key=lambda k: (-venue_show_counts.get(k, 0), (venue_labels.get(k, k) or k).lower()),
    )
    selected_keys = [k for k in pinned_keys if k in venue_person_showsets]
    selected_keys.extend(dynamic_keys[:6])
    pinned_label_by_slug = {slug: label for label, slug in VENUE_PINNED_TARGETS}

    sections: list[tuple[str, list[str]]] = []
    for venue_key in selected_keys:
        label = pinned_label_by_slug.get(venue_key) or venue_labels.get(venue_key, venue_key)
        ranked = sorted(
            venue_person_showsets[venue_key].items(),
            key=lambda item: (-len(item[1]), person_name.get(item[0], "Unknown").lower()),
        )
        lines = [f"  shows={venue_show_counts.get(venue_key, 0)}"]
        if not ranked:
            lines.append("  - No matching records")
        else:
            for idx, (pid, show_set) in enumerate(ranked[:top_n_people], start=1):
                lines.append(f"  {idx}. {person_name.get(pid, 'Unknown')} ({len(show_set)})")
        sections.append((label, lines))
    return sections


def main() -> None:
    parser = argparse.ArgumentParser(description="Create a paginated plaintext summary PDF.")
    parser.add_argument(
        "--input",
        type=Path,
        default=Path(__file__).parent / "rank_all_people_cache.json",
        help="Input JSON cache file (default: rank_all_people_cache.json)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(__file__).parent / "camdram_plaintext_summary.pdf",
        help="Output PDF file path",
    )
    parser.add_argument(
        "--recent-last-role-years",
        type=int,
        default=None,
        help="Only include people whose most recent role is within this many years.",
    )
    args = parser.parse_args()

    with args.input.open("r", encoding="utf-8") as f:
        cache_data = json.load(f)

    page1_lines, role_intro_lines, role_sections, pair_lines = build_summaries(
        cache_data,
        recent_last_role_years=args.recent_last_role_years,
    )
    society_sections = build_society_sections(cache_data)
    venue_sections = build_venue_sections(cache_data, top_n_people=15)

    pdf = canvas.Canvas(str(args.output), pagesize=PAGE_SIZE)
    # Keep all-people view to exactly one page.
    draw_plaintext_page(pdf, "By Person Summary", page1_lines[: _page_body_line_capacity()])
    draw_role_sections_three_columns_no_split(
        pdf, "Role-Focused Summary", role_intro_lines, role_sections
    )
    draw_role_sections_three_columns_no_split(
        pdf, "Society Top 15 (by show count)", [], society_sections
    )
    draw_sections_three_by_two_paginated(
        pdf, "Venue Top 15 (by show count)", venue_sections
    )
    draw_plaintext_page(pdf, "Shared Role Pairs", pair_lines[: _page_body_line_capacity()])
    pdf.save()

    print(f"Wrote PDF: {args.output}")


if __name__ == "__main__":
    main()
