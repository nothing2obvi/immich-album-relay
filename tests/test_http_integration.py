"""Exercise the real HTTP transport and CLI against a local fake Immich server."""

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import yaml
from conftest import A1, A2, A3, D1, D2, S1, S2, U1, U2

from immich_album_relay.cli import main


def test_http_cli_validate_preview_run_and_repeat(data, tmp_path):
    albums = {
        S1: [{"id": A1, "ownerId": U1}, {"id": A2, "ownerId": U2}],
        S2: [{"id": A1, "ownerId": U1}, {"id": A3, "ownerId": U1}],
        D1: [],
        D2: [],
    }
    writes = []
    requests = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def reply(self, body, status=200):
            encoded = json.dumps(body).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)

        def do_GET(self):
            requests.append(("GET", self.path))
            if self.path == "/api/users/me":
                self.reply({"id": U1 if self.headers.get("x-api-key") == "secret-alex" else U2})
            elif self.path == "/api/server/version":
                self.reply({"major": 3, "minor": 3, "patch": 0})
            elif self.path.startswith("/api/albums/"):
                self.reply(
                    {
                        "id": self.path.rsplit("/", 1)[1],
                        "albumName": "Test album",
                        "albumUsers": [
                            {"user": {"id": U1}, "role": "owner"},
                            {"user": {"id": U2}, "role": "editor"},
                        ],
                    }
                )
            else:
                self.reply({}, 404)

        def body(self):
            return json.loads(self.rfile.read(int(self.headers["Content-Length"])))

        def do_POST(self):
            requests.append(("POST", self.path))
            assert self.path == "/api/search/metadata"
            body = self.body()
            album_id = body["filter"]["albumIds"]["any"][0]
            offset = int(body.get("cursor", "0"))
            items = albums[album_id][offset : offset + 1]
            cursor = str(offset + 1) if offset + 1 < len(albums[album_id]) else None
            self.reply({"assets": {"items": items, "nextCursor": cursor}})

        def do_PUT(self):
            requests.append(("PUT", self.path))
            writes.append((self.path, self.headers.get("x-api-key")))
            album_id = self.path.split("/")[-2]
            ids = self.body()["ids"]
            owner_id = U1 if self.headers.get("x-api-key") == "secret-alex" else U2
            results = []
            for asset_id in ids:
                already = any(a["id"] == asset_id for a in albums[album_id])
                if not already:
                    albums[album_id].append({"id": asset_id, "ownerId": owner_id})
                results.append(
                    {"id": asset_id, "success": not already, **({"error": "duplicate"} if already else {})}
                )
            self.reply(results)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    try:
        data["immich_url"] = f"http://127.0.0.1:{server.server_port}"
        data["http"] = {"page_size": 1}
        path = tmp_path / "config.yml"
        path.write_text(yaml.safe_dump(data))
        prefix = ["--config", str(path)]
        assert main(prefix + ["validate"]) == 0
        assert main(prefix + ["run", "--dry-run"]) == 0
        assert not writes
        assert main(prefix + ["run"]) == 0
        assert len(albums[D1]) == len(albums[D2]) == 3
        count = len(writes)
        assert main(prefix + ["run"]) == 0
        assert len(writes) == count
        assert all(method != "DELETE" for method, _ in requests)
        assert all(path.endswith("/assets") for path, _ in writes)
    finally:
        server.shutdown()
        server.server_close()
        worker.join(timeout=5)
