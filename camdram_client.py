"""
Camdram API Python Client

A simple client for interacting with the Camdram API.
Supports shows, societies, venues, diary, and OAuth2 authentication.

API docs: https://camdram.github.io/api
Create API keys: https://www.camdram.net/api/apps
"""

import json
import os
from datetime import datetime
from typing import Any, Optional

import requests


class CamdramClient:
    """Client for the Camdram REST API."""

    BASE_URL = "https://www.camdram.net"
    TOKEN_URL = "https://www.camdram.net/oauth/v2/token"

    def __init__(
        self,
        client_id: Optional[str] = None,
        client_secret: Optional[str] = None,
        access_token: Optional[str] = None,
    ):
        """
        Initialize the Camdram client.

        Args:
            client_id: OAuth2 API app ID (from https://www.camdram.net/api/apps)
            client_secret: OAuth2 API app secret
            access_token: Pre-obtained bearer token (skips token fetch)
        """
        # Load from: constructor args > env vars > config.py
        if client_id and client_secret:
            pass  # use constructor args
        elif not client_id and not client_secret:
            try:
                from config import CAMDRAM_CLIENT_ID, CAMDRAM_CLIENT_SECRET
                client_id = CAMDRAM_CLIENT_ID
                client_secret = CAMDRAM_CLIENT_SECRET
            except ImportError:
                pass
        self.client_id = client_id or os.environ.get("CAMDRAM_CLIENT_ID")
        self.client_secret = client_secret or os.environ.get("CAMDRAM_CLIENT_SECRET")
        self._access_token = access_token
        self._session = requests.Session()
        self._session.headers["Accept"] = "application/json"

    def _get_auth_headers(self) -> dict[str, str]:
        """Get headers with Bearer token if authenticated."""
        headers = {}
        if self._access_token:
            headers["Authorization"] = f"Bearer {self._access_token}"
        return headers

    def authenticate(self) -> bool:
        """
        Obtain an access token using Client Credentials grant.
        Required for better rate limits and authenticated endpoints.

        Returns:
            True if authentication succeeded, False otherwise.
        """
        if not self.client_id or not self.client_secret:
            raise ValueError(
                "client_id and client_secret required. "
                "Set CAMDRAM_CLIENT_ID and CAMDRAM_CLIENT_SECRET env vars, "
                "or pass them to the constructor."
            )

        response = self._session.post(
            self.TOKEN_URL,
            json={
                "grant_type": "client_credentials",
                "client_id": self.client_id,
                "client_secret": self.client_secret,
            },
            headers={"Content-Type": "application/json"},
        )

        if response.status_code != 200:
            raise RuntimeError(
                f"Authentication failed: {response.status_code} - {response.text}"
            )

        data = response.json()
        self._access_token = data["access_token"]
        return True

    def _request(
        self,
        path: str,
        params: Optional[dict[str, Any]] = None,
        format: str = "json",
    ) -> dict[str, Any]:
        """
        Make a GET request to the Camdram API.

        Args:
            path: API path (e.g. /shows/2019-legally-blonde)
            params: Optional query parameters
            format: Response format (json, xml, ics). JSON is parsed and returned.

        Returns:
            Parsed JSON response
        """
        url = f"{self.BASE_URL}{path}"
        if not path.endswith(f".{format}"):
            url = f"{url}.{format}" if "." not in path.split("/")[-1] else url

        response = self._session.get(
            url,
            params=params,
            headers=self._get_auth_headers(),
        )

        response.raise_for_status()

        if format == "json":
            return response.json()
        return {"raw": response.text}

    # --- Shows ---

    def get_show(self, slug: str) -> dict[str, Any]:
        """
        Get a show by its URL slug.

        Args:
            slug: Show slug (e.g. '2019-legally-blonde')

        Returns:
            Show object with performances, societies, etc.
        """
        return self._request(f"/shows/{slug}")

    def get_show_roles(self, slug: str) -> list:
        """Get roles/cast for a show."""
        return self._request(f"/shows/{slug}/roles")

    # --- People ---

    def get_person(self, slug: str) -> dict[str, Any]:
        """Get a person by their URL slug."""
        return self._request(f"/people/{slug}")

    def get_person_roles(self, slug: str) -> list:
        """Get all roles (and thus shows) a person has been involved with."""
        return self._request(f"/people/{slug}/roles")

    # --- Societies ---

    def get_societies(self) -> list:
        """Get list of all societies."""
        return self._request("/societies")

    def get_society(self, slug: str) -> dict[str, Any]:
        """
        Get a society by its URL slug.

        Args:
            slug: Society slug (e.g. 'cambridge-university-musical-theatre-society')
        """
        return self._request(f"/societies/{slug}")

    def get_society_shows(
        self,
        slug: str,
        from_date: Optional[str] = None,
        to_date: Optional[str] = None,
    ) -> list:
        """
        Get shows for a society, optionally filtered by date range.

        Args:
            slug: Society slug
            from_date: Start date (YYYY-MM-DD or YYYY-MM-DD HH:MM)
            to_date: End date (defaults to 1 year after from_date)
        """
        params = {}
        if from_date:
            params["from"] = from_date
        if to_date:
            params["to"] = to_date
        return self._request(f"/societies/{slug}/shows", params=params)

    def get_society_diary(
        self,
        slug: str,
        from_date: Optional[str] = None,
        to_date: Optional[str] = None,
        format: str = "json",
    ) -> dict[str, Any]:
        """Get diary/performances for a society."""
        params = {}
        if from_date:
            params["from"] = from_date
        if to_date:
            params["to"] = to_date
        return self._request(f"/societies/{slug}/diary", params=params, format=format)

    # --- Venues ---

    def get_people(self, page: int = 1, per_page: int = 100) -> list:
        """Get list of people (paginated)."""
        return self._request("/people", params={"page": page, "per_page": per_page})

    def get_shows(self, page: int = 1, per_page: int = 100) -> list:
        """Get list of shows (paginated). Returns list of show dicts."""
        data = self._request("/shows", params={"page": page, "per_page": per_page})
        return data.get("shows", data) if isinstance(data, dict) else data

    def get_venues(self) -> list:
        """Get list of all venues."""
        return self._request("/venues")

    def get_venue(self, slug: str) -> dict[str, Any]:
        """
        Get a venue by its URL slug.

        Args:
            slug: Venue slug (e.g. 'adc-theatre')
        """
        return self._request(f"/venues/{slug}")

    def get_venue_shows(
        self,
        slug: str,
        from_date: Optional[str] = None,
        to_date: Optional[str] = None,
    ) -> list:
        """Get shows at a venue, optionally filtered by date range."""
        params = {}
        if from_date:
            params["from"] = from_date
        if to_date:
            params["to"] = to_date
        return self._request(f"/venues/{slug}/shows", params=params)

    def get_venue_diary(
        self,
        slug: str,
        from_date: Optional[str] = None,
        to_date: Optional[str] = None,
        format: str = "json",
    ) -> dict[str, Any]:
        """Get diary/performances at a venue."""
        params = {}
        if from_date:
            params["from"] = from_date
        if to_date:
            params["to"] = to_date
        return self._request(f"/venues/{slug}/diary", params=params, format=format)

    # --- Diary ---

    def get_diary(
        self,
        from_date: Optional[str] = None,
        to_date: Optional[str] = None,
        format: str = "json",
    ) -> dict[str, Any]:
        """
        Get the main Camdram diary (all performances).

        Args:
            from_date: Start date (YYYY-MM-DD)
            to_date: End date (defaults to 1 year after from_date)
            format: json, xml, or ics (iCal)
        """
        params = {}
        if from_date:
            params["from"] = from_date
        if to_date:
            params["to"] = to_date
        return self._request("/diary", params=params, format=format)

    # --- Authenticated endpoints (require OAuth) ---

    def get_account_shows(self) -> list:
        """
        Get shows the authenticated user can edit.
        Requires OAuth authentication.
        """
        return self._request("/auth/account/shows")


def main() -> None:
    """Example usage of the Camdram client."""
    client = CamdramClient()

    # Optional: authenticate for better rate limits
    # client.authenticate()

    print("=== Camdram API Demo ===\n")

    # Fetch a show
    print("Fetching show: 2019-legally-blonde")
    show = client.get_show("2019-legally-blonde")
    print(f"  Name: {show.get('name')}")
    print(f"  Author: {show.get('author')}")
    print(f"  Category: {show.get('category')}")
    if "performances" in show:
        print(f"  Performances: {len(show['performances'])}")

    # Fetch a venue
    print("\nFetching venue: adc-theatre")
    venue = client.get_venue("adc-theatre")
    print(f"  Name: {venue.get('name')}")
    print(f"  Address: {venue.get('address', 'N/A')[:50]}...")

    # Fetch a society
    print("\nFetching society: cambridge-university-musical-theatre-society")
    society = client.get_society("cambridge-university-musical-theatre-society")
    print(f"  Name: {society.get('name')}")
    print(f"  Short name: {society.get('short_name')}")

    # Fetch diary for next 7 days
    print("\nFetching diary (next 7 days)")
    from_date = datetime.now().strftime("%Y-%m-%d")
    # Simple date math for demo
    diary = client.get_diary(from_date=from_date)
    print(f"  Diary keys: {list(diary.keys())}")


if __name__ == "__main__":
    main()
