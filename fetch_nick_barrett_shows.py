"""
Fetch all shows Nick Barrett has been involved with from Camdram.
"""

from camdram_client import CamdramClient


def main() -> None:
    client = CamdramClient()
    client.authenticate()

    roles = client.get_person_roles("nick-barrett")

    # Extract unique shows (preserve order by first appearance)
    seen_ids: set[int] = set()
    shows: list[dict] = []
    for role in roles:
        show = role.get("show")
        if show and show["id"] not in seen_ids:
            seen_ids.add(show["id"])
            shows.append(show)

    # Group roles by show for display
    show_roles: dict[int, list[str]] = {}
    for role in roles:
        show_id = role["show"]["id"]
        role_name = role.get("role", "Unknown")
        if show_id not in show_roles:
            show_roles[show_id] = []
        show_roles[show_id].append(role_name)

    print(f"Nick Barrett has been involved with {len(shows)} shows:\n")
    for show in shows:
        roles_str = ", ".join(show_roles[show["id"]])
        print(f"  • {show['name']}")
        print(f"    Roles: {roles_str}")
        print(f"    https://www.camdram.net/shows/{show['slug']}")
        print()


if __name__ == "__main__":
    main()
