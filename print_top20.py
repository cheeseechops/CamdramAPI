"""Print the top 20 people by roles in text form (same as GUI, with extra stats)."""
from camdram_gui import load_rankings

r = load_rankings()
if not r:
    print("No cache found.")
else:
    # Build rank map (dense ranking)
    rank_map = {}
    rank, prev = 0, None
    for row in r:
        if prev is None or row[3] != prev:
            rank += 1
        rank_map[row[0]] = rank
        prev = row[3]

    print("Rank  Roles  Shows  Types  Top%   Name                              Top role")
    print("-" * 75)
    for row in r[:20]:
        pid, name, slug, count, top_role, top_role_count, num_shows, num_titles, top_pct, *_ = row
        rk = rank_map[pid]
        top_str = f"{top_role} ({top_role_count})" if top_role_count else "—"
        print(f"{rk:4d}  {count:4d}  {num_shows:4d}  {num_titles:4d}  {top_pct:3d}%  {name[:28]:<28}  {top_str}")
