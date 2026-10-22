"""Bounded HTTP client; its sole write operation adds album memberships."""

from __future__ import annotations

import json
import logging
import random
import time
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, Request, build_opener

from .config import Config, Http

log = logging.getLogger(__name__)


class RelayError(RuntimeError):
    """Safe-to-log error containing no remote response bodies or credentials."""


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None  # Never forward API credentials to redirects, including other origins.


class Transport:
    def __init__(self, settings: Http, stop=None):
        self.settings = settings
        self.stop = stop
        self.opener = build_opener(NoRedirect())

    def wait(self, seconds):
        if self.stop:
            if self.stop.wait(seconds):
                raise RelayError("Execution interrupted by shutdown")
        else:
            time.sleep(seconds)

    def request(self, method, url, headers=None, body=None, *, expect_json=True):
        payload = json.dumps(body).encode() if body is not None else None
        for attempt in range(self.settings.retries + 1):
            if self.stop and self.stop.is_set():
                raise RelayError("Execution interrupted by shutdown")
            retry_after = None
            try:
                request = Request(
                    url,
                    data=payload,
                    method=method,
                    headers={"Content-Type": "application/json", **(headers or {})},
                )
                with self.opener.open(request, timeout=self.settings.timeout_seconds) as response:
                    raw = response.read()
                if not expect_json:
                    return None
                return json.loads(raw)
            except HTTPError as error:
                status = error.code
                retry_after = error.headers.get("Retry-After")
                error.close()
                category = {
                    401: "Authentication failed: invalid API key",
                    403: "Authorization failed: check API key scopes and shared album editor access",
                    404: "Resource not found: check album UUID and API base URL (or album access)",
                    400: "API rejected the request: check configuration and supported Immich version",
                    422: "API rejected the request schema: check Immich API compatibility",
                    429: "Rate limited by server",
                }.get(status, "HTTP API failure or incompatible endpoint")
                message = f"{category} (HTTP {status})"
                transient = status in {408, 425, 429, 500, 502, 503, 504}
                if not transient:
                    raise RelayError(message) from None
            except (URLError, TimeoutError, ConnectionError, OSError):
                message = "Network failure or timeout: check connectivity, TLS and server availability"
            except (ValueError, UnicodeError):
                raise RelayError("API incompatibility: response is not valid JSON") from None
            if attempt == self.settings.retries:
                raise RelayError(f"{message}; retry limit reached") from None
            delay = min(
                self.settings.max_retry_delay_seconds,
                self.settings.backoff_seconds * 2**attempt + random.uniform(0, 0.25),
            )
            if retry_after:
                try:
                    delay = max(0.0, float(retry_after))
                except ValueError:
                    try:
                        delay = max(
                            0.0, (parsedate_to_datetime(retry_after) - datetime.now(UTC)).total_seconds()
                        )
                    except (ValueError, TypeError, OverflowError):
                        pass
                if delay > self.settings.max_retry_delay_seconds:
                    raise RelayError(
                        "Server Retry-After exceeds configured limit; retry on the next run"
                    ) from None
            log.warning("%s | Retry %d/%d in %.1fs", message, attempt + 1, self.settings.retries, delay)
            self.wait(delay)


class Immich:
    def __init__(self, config: Config, user_ref: str, transport=None):
        self.config = config
        self.user = config.users[user_ref]
        self.transport = transport or Transport(config.http)
        self.base = config.immich_url
        if not self.base.endswith("/api"):
            self.base += "/api"

    def request(self, method, path, body=None):
        return self.transport.request(
            method, self.base + path, {"x-api-key": self.user.api_key.get_secret_value()}, body
        )

    def identity(self):
        data = self.request("GET", "/users/me")
        if not isinstance(data, dict) or data.get("id") != str(self.user.id):
            raise RelayError("API key belongs to a different user than the configured immutable user ID")
        return data

    def version(self):
        data = self.request("GET", "/server/version")
        if not isinstance(data, dict) or not all(
            type(data.get(k)) is int and data[k] >= 0 for k in ("major", "minor", "patch")
        ):
            raise RelayError("API incompatibility: unexpected server version response")
        return data

    def albums(self):
        data = self.request("GET", "/albums")
        if not isinstance(data, list):
            raise RelayError("API incompatibility: expected an album list")
        return data

    def album(self, album_id, *, editor=False):
        data = self.request("GET", f"/albums/{album_id}")
        if not isinstance(data, dict) or data.get("id") != str(album_id):
            raise RelayError("API incompatibility: invalid album response")
        if editor:
            entries = data.get("albumUsers", [])
            permitted = data.get("ownerId") == str(self.user.id) or any(
                entry.get("user", {}).get("id") == str(self.user.id)
                and entry.get("role") in {"owner", "editor"}
                for entry in entries
            )
            if not permitted:
                raise RelayError(
                    "Cannot add assets: source user must own the destination or be a shared album editor"
                )
        return data

    def assets(self, album_id):
        # v3.2+ structured, album-confined search includes other contributors' shared assets.
        # The API returns an opaque cursor; never infer pagination from result counts.
        cursor = None
        seen_cursors = set()
        assets = {}
        while True:
            body = {
                "filter": {"albumIds": {"any": [str(album_id)]}},
                "size": self.config.http.page_size,
                "withExif": False,
            }
            if cursor:
                body["cursor"] = cursor
            data = self.request("POST", "/search/metadata", body)
            page = data.get("assets") if isinstance(data, dict) else None
            if not isinstance(page, dict) or not isinstance(page.get("items"), list):
                raise RelayError("API incompatibility: invalid asset search response; requires Immich >=3.2")
            for asset in page["items"]:
                if not isinstance(asset, dict) or not isinstance(asset.get("id"), str):
                    raise RelayError("API incompatibility: asset is missing an ID")
                assets[asset["id"]] = asset
            if "nextCursor" not in page:
                raise RelayError("API incompatibility: missing nextCursor; requires Immich >=3.2")
            cursor = page["nextCursor"]
            if cursor is None:
                return assets
            if not isinstance(cursor, str) or not cursor or cursor in seen_cursors:
                raise RelayError("API incompatibility: invalid or repeated pagination cursor")
            seen_cursors.add(cursor)

    def add(self, album_id, ids):
        data = self.request("PUT", f"/albums/{album_id}/assets", {"ids": ids})
        if not isinstance(data, list):
            raise RelayError("API incompatibility: expected per-asset add results")
        results = {}
        for item in data:
            if not isinstance(item, dict) or item.get("id") not in ids or item["id"] in results:
                raise RelayError("API incompatibility: invalid per-asset add results")
            results[item["id"]] = item
        return results
