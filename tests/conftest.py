import copy

import pytest

from immich_album_relay.api import RelayError
from immich_album_relay.config import Config

U1 = "11111111-1111-4111-8111-111111111111"
U2 = "22222222-2222-4222-8222-222222222222"
S1 = "cccccccc-cccc-4ccc-8ccc-cccccccccccc"
S2 = "dddddddd-dddd-4ddd-8ddd-dddddddddddd"
D1 = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
D2 = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
A1 = "10000000-0000-4000-8000-000000000001"
A2 = "10000000-0000-4000-8000-000000000002"
A3 = "10000000-0000-4000-8000-000000000003"


@pytest.fixture
def data(tmp_path):
    return {
        "immich_url": "https://photos.example.com",
        "state_dir": str(tmp_path / "state"),
        "users": {
            "alex": {"id": U1, "api_key": "secret-alex", "name": "Alex"},
            "sam": {"id": U2, "api_key": "secret-sam", "name": "Sam"},
        },
        "destinations": {
            "family": {"id": D1, "name": "Family", "user": "alex"},
            "holidays": {"id": D2, "name": "Holidays"},
        },
        "jobs": [
            {
                "id": "family",
                "destinations": ["family", "holidays"],
                "sources": [
                    {"user": "alex", "albums": [{"id": S1}, {"id": S2}]},
                    {"user": "sam", "albums": [{"id": S1}]},
                ],
            }
        ],
    }


@pytest.fixture
def config(data):
    return Config.model_validate(data)


@pytest.fixture
def fake(config):
    class World:
        albums = {
            S1: {A1: {"id": A1, "ownerId": U1}, A2: {"id": A2, "ownerId": U2}},
            S2: {A1: {"id": A1, "ownerId": U1}, A3: {"id": A3, "ownerId": U1}},
            D1: {},
            D2: {},
        }
        calls = []
        denied = set()
        bad_keys = set()
        partial = {}
        missing_results = set()
        failures = set()

        def client(self, ref):
            world = self

            class FakeClient:
                def identity(self):
                    if ref in world.bad_keys:
                        raise RelayError("Authentication failed (HTTP 401)")
                    return {"id": str(config.users[ref].id)}

                def version(self):
                    return {"major": 3, "minor": 3, "patch": 0}

                def album(self, album_id, editor=False):
                    album_id = str(album_id)
                    if album_id not in world.albums:
                        raise RelayError("Resource not found (HTTP 404)")
                    if (ref, album_id) in world.denied:
                        raise RelayError("Insufficient destination album permissions")
                    return {"id": album_id, "albumName": album_id}

                def assets(self, album_id):
                    return copy.deepcopy(world.albums[str(album_id)])

                def add(self, album_id, ids):
                    album_id = str(album_id)
                    world.calls.append((ref, album_id, list(ids)))
                    if (ref, album_id) in world.failures:
                        raise RelayError("Network failure; retry limit reached")
                    results = {}
                    for asset_id in ids:
                        if asset_id in world.missing_results:
                            continue
                        if asset_id in world.partial:
                            results[asset_id] = {
                                "id": asset_id,
                                "success": False,
                                "error": world.partial[asset_id],
                            }
                        elif asset_id in world.albums[album_id]:
                            results[asset_id] = {"id": asset_id, "success": False, "error": "duplicate"}
                        else:
                            world.albums[album_id][asset_id] = {
                                "id": asset_id,
                                "ownerId": str(config.users[ref].id),
                            }
                            results[asset_id] = {"id": asset_id, "success": True}
                    return results

            return FakeClient()

    return World()
