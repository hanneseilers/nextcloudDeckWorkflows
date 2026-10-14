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
        # One Session per instance, reused across every call this client ever
        # makes (Deck API and, via NextcloudCalendarGateway sharing this same
        # client, CalDAV) - keeps the TCP/TLS connection to that Nextcloud
        # host alive instead of reconnecting from scratch on every request, a
        # real cost over a run that makes a dozen+ calls to the same host.
        self._session = requests.Session()

    def get(self, path: str, params: Optional[dict[str, Any]] = None) -> Any:
        return self._request("GET", path, params=params)

    def post(self, path: str, json: Optional[dict[str, Any]] = None) -> Any:
        return self._request("POST", path, json=json)

    def put(self, path: str, json: Optional[dict[str, Any]] = None) -> Any:
        return self._request("PUT", path, json=json)

    def delete(self, path: str) -> Any:
        return self._request("DELETE", path)

    def request_xml(self, method: str, path: str, body: str = "", depth: Optional[int] = None) -> str:
        """For CalDAV (PROPFIND/REPORT with an XML body, XML response) - the
        Deck/OCS API above is JSON-only, CalDAV is XML-only, so this returns
        raw response text instead of calling .json()."""

        headers = {"Content-Type": "application/xml; charset=utf-8"}
        if depth is not None:
            headers["Depth"] = str(depth)
        response = self._send(method, path, headers=headers, data=body.encode("utf-8"))
        return response.text

    def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        response = self._send(method, path, headers=self._headers, **kwargs)
        if not response.content:
            return None
        return response.json()

    def _send(self, method: str, path: str, **kwargs: Any) -> Any:
        """Shared request/status-check for _request() and request_xml() -
        they only differ in headers/body and how the response body is
        parsed afterwards (.json() vs .text)."""

        response = self._session.request(
            method, f"{self._base_url}{path}", auth=self._auth, timeout=self._timeout, **kwargs
        )
        if not response.ok:
            raise NextcloudApiError(f"{method} {path} failed: {response.status_code} {response.text}")
        return response
