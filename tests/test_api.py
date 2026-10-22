import io
import json
from email.message import Message
from urllib.error import HTTPError, URLError

import pytest
from conftest import A1, D1, U1

from immich_album_relay.api import Immich, NoRedirect, RelayError, Transport


class Response(io.BytesIO):
    pass


class Opener:
    def __init__(self, sequence):
        self.sequence = iter(sequence)
        self.calls = []

    def open(self, request, **kwargs):
        self.calls.append(request)
        result = next(self.sequence)
        if isinstance(result, Exception):
            raise result
        return Response(json.dumps(result).encode())


def http_error(status, retry_after=None):
    headers = Message()
    if retry_after:
        headers["Retry-After"] = retry_after
    return HTTPError(
        "https://example.com", status, "PRIVATE REMOTE BODY", headers, io.BytesIO(b"REMOTE-SECRET")
    )


def test_retry_transient_and_rate_limit(config, monkeypatch):
    transport = Transport(config.http)
    transport.opener = Opener([http_error(503), http_error(429, "2"), {"ok": True}])
    delays = []
    monkeypatch.setattr(transport, "wait", delays.append)
    assert transport.request("GET", "https://example.com") == {"ok": True}
    assert len(delays) == 2 and delays[1] == 2


@pytest.mark.parametrize(
    "status, category",
    [(401, "Authentication"), (403, "Authorization"), (404, "not found"), (400, "rejected")],
)
def test_permanent_errors_not_retried_or_leaked(config, status, category):
    transport = Transport(config.http)
    transport.opener = Opener([http_error(status)])
    with pytest.raises(RelayError, match=category) as error:
        transport.request("GET", "https://example.com")
    assert "PRIVATE" not in str(error.value) and "SECRET" not in str(error.value)
    assert len(transport.opener.calls) == 1


def test_bounded_retry_exhaustion(config, monkeypatch):
    config.http.retries = 2
    transport = Transport(config.http)
    transport.opener = Opener([URLError("PRIVATE-NETWORK-ERROR")] * 3)
    monkeypatch.setattr(transport, "wait", lambda _: None)
    with pytest.raises(RelayError, match="retry limit") as error:
        transport.request("PUT", "https://example.com", body={"ids": [A1]})
    assert len(transport.opener.calls) == 3 and "PRIVATE" not in str(error.value)


def test_retry_after_never_retries_early(config):
    transport = Transport(config.http)
    transport.opener = Opener([http_error(429, "999999")])
    with pytest.raises(RelayError, match="Retry-After exceeds"):
        transport.request("GET", "https://example.com")


def test_redirects_never_forward_keys():
    assert NoRedirect().redirect_request(None, None, 302, "", {}, "https://evil.example") is None


def test_cursor_pagination(config):
    transport = Transport(config.http)
    transport.opener = Opener(
        [
            {"assets": {"items": [{"id": A1, "ownerId": U1}], "nextCursor": "opaque-page-two"}},
            {"assets": {"items": [{"id": "second", "ownerId": U1}], "nextCursor": None}},
        ]
    )
    client = Immich(config, "alex", transport)
    assert len(client.assets(D1)) == 2
    request = transport.opener.calls[1]
    assert json.loads(request.data)["cursor"] == "opaque-page-two"
    assert json.loads(request.data)["filter"] == {"albumIds": {"any": [D1]}}
    assert request.get_header("X-api-key") == "secret-alex"


def test_repeated_cursor_fails(config):
    transport = Transport(config.http)
    transport.opener = Opener([{"assets": {"items": [], "nextCursor": "same"}}] * 2)
    with pytest.raises(RelayError, match="repeated"):
        Immich(config, "alex", transport).assets(D1)


def test_wrong_identity(config):
    transport = Transport(config.http)
    transport.opener = Opener([{"id": "wrong-id"}])
    with pytest.raises(RelayError, match="different user"):
        Immich(config, "alex", transport).identity()


def test_shared_viewer_rejected(config):
    transport = Transport(config.http)
    transport.opener = Opener([{"id": D1, "albumUsers": [{"user": {"id": U1}, "role": "viewer"}]}])
    with pytest.raises(RelayError, match="editor"):
        Immich(config, "alex", transport).album(D1, editor=True)


def test_incompatible_version_response_fails_cleanly(config):
    transport = Transport(config.http)
    transport.opener = Opener([{"major": "3", "minor": 3, "patch": 0}])
    with pytest.raises(RelayError, match="version response"):
        Immich(config, "alex", transport).version()
