from __future__ import annotations

from typing import Any, Optional

import requests


class NextcloudApiError(RuntimeError):
    """Raised when the Nextcloud API returns an unexpected response."""


class NextcloudClient:
    """Thin HTTP client for the Nextcloud/Deck OCS API. Knows nothing about workflows -
    just authentication and request/response plumbing."""

    def __init__(self, base_url: str, username: str, app_password: str, timeout: float = 15.0) -> None:
        self._base_url = base_url.rstrip("/")
        self._auth = (username, app_password)
        self._timeout = timeout
        self._headers = {"OCS-APIRequest": "true", "Accept": "application/json"}

    def get(self, path: str, params: Optional[dict[str, Any]] = None) -> Any:
        return self._request("GET", path, params=params)

    def post(self, path: str, json: Optional[dict[str, Any]] = None) -> Any:
        return self._request("POST", path, json=json)

    def put(self, path: str, json: Optional[dict[str, Any]] = None) -> Any:
        return self._request("PUT", path, json=json)

    def delete(self, path: str) -> Any:
        return self._request("DELETE", path)

    def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        url = f"{self._base_url}{path}"
        response = requests.request(
            method, url, auth=self._auth, headers=self._headers, timeout=self._timeout, **kwargs
        )
        if not response.ok:
            raise NextcloudApiError(f"{method} {path} failed: {response.status_code} {response.text}")
        if not response.content:
            return None
        return response.json()
