# Camdram API Python Client

A Python client for the [Camdram API](https://camdram.github.io/api) — Cambridge's theatre and performance database.

## Setup

```bash
pip install -r requirements.txt
```

## Quick Start

```python
from camdram_client import CamdramClient

client = CamdramClient()

# Fetch a show
show = client.get_show("2019-legally-blonde")
print(show["name"], show["author"])

# Fetch a venue
venue = client.get_venue("adc-theatre")

# Fetch a society
society = client.get_society("cambridge-university-musical-theatre-society")

# Get diary (performances by date)
diary = client.get_diary(from_date="2025-02-24", to_date="2025-03-01")
```

## Authentication (Recommended)

Unauthenticated requests work for testing but have low rate limits. For production use:

1. Create an API app at [camdram.net/api/apps](https://www.camdram.net/api/apps)
2. Copy `config.example.py` to `config.py` and add your credentials
3. Or set environment variables: `CAMDRAM_CLIENT_ID` and `CAMDRAM_CLIENT_SECRET`

```python
client = CamdramClient()
client.authenticate()  # Uses Client Credentials OAuth2

# Now you can access authenticated endpoints
my_shows = client.get_account_shows()  # Shows you can edit
```

## API Methods

| Method | Description |
|--------|-------------|
| `get_show(slug)` | Get a show by slug |
| `get_show_roles(slug)` | Get cast/roles for a show |
| `get_society(slug)` | Get a society |
| `get_society_shows(slug, from_date, to_date)` | Society's shows |
| `get_society_diary(slug, from_date, to_date)` | Society's diary |
| `get_venue(slug)` | Get a venue |
| `get_venue_shows(slug, from_date, to_date)` | Venue's shows |
| `get_venue_diary(slug, from_date, to_date)` | Venue's diary |
| `get_diary(from_date, to_date)` | Main diary (all performances) |
| `get_account_shows()` | Your editable shows (requires auth) |

## Run Demo

```bash
python camdram_client.py
```

## GUI

Searchable GUI for people ranked by roles:

```bash
python camdram_gui.py
```

Uses cached data from `rank_all_people.py` or `shared_roles.py`. Click "Fetch Data" to populate the full cache (~10 min). Double-click a person to open their Camdram profile.

## Web app (Flask)

A Flask app provides the same rankings in a browser, with sortable tables and a “By role” view.

### Run locally

```bash
pip install -r requirements.txt
python -m flask --app application run
# or: flask --app application run
```

Then open http://127.0.0.1:5000/

### Host on PythonAnywhere

1. Create a free account at [pythonanywhere.com](https://www.pythonanywhere.com).
2. Upload this project (or clone from your repo) into your home directory.
3. In the **Web** tab, add a new web app, choose **Manual configuration** and **Python 3.10** (or your version).
4. Set **Source code** to your project directory (e.g. `/home/yourusername/CamDramAPI`).
5. In **Code**, set **WSGI configuration file** to your project path, e.g. `/home/yourusername/CamDramAPI/wsgi.py`. Open that file and ensure it imports `application` from `application` (it already does).
6. In **Virtualenv**, create and use a venv in the project folder and install deps:  
   `pip install -r requirements.txt`
7. The app reads from `rank_all_people_cache.json` (and `shared_roles_cache.json` if present). Generate the cache locally by running `python rank_all_people.py --refresh`, then upload the cache file(s) into the project directory, or run the script on a PA scheduled task if you have one.
8. Reload the web app from the Web tab.

The app will show “No cache found” until the cache file(s) are present in the project directory.
