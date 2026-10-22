#!/usr/bin/env python3
"""Verify idle scheduler health, TZ and SIGTERM using a clearly isolated fake config."""

import json
import os
import subprocess
import tempfile
import time
from pathlib import Path


def docker(*args):
    return subprocess.check_output(["docker", *args], text=True).strip()


def main():
    image = os.environ.get("RELAY_SMOKE_IMAGE", "immich-album-relay-test:local")
    with tempfile.TemporaryDirectory(prefix="relay-smoke-") as directory:
        directory = Path(directory)
        directory.chmod(0o755)
        config = directory / "config.yml"
        # Fictional data, no calls are made: both automatic methods and the job are disabled.
        config.write_text("""immich_url: https://unused.example.com
dry_run: true
users:
  smoke:
    id: 11111111-1111-4111-8111-111111111111
    api_key: fictional-smoke-key
destinations:
  smoke:
    id: aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa
cron:
  enabled: false
polling:
  enabled: false
jobs:
  - id: smoke
    enabled: false
    destinations: [smoke]
    sources:
      - user: smoke
        albums:
          - id: cccccccc-cccc-4ccc-8ccc-cccccccccccc
""")
        config.chmod(0o644)
        container = docker(
            "run",
            "-d",
            "--read-only",
            "--cap-drop=ALL",
            "--security-opt=no-new-privileges:true",
            "-e",
            "TZ=America/Phoenix",
            "--mount",
            f"type=bind,src={config},dst=/config/config.yml,readonly",
            image,
        )
        try:
            for _ in range(30):
                state = json.loads(docker("inspect", "--format", "{{json .State}}", container))
                if state.get("Health", {}).get("Status") == "healthy":
                    break
                if state["Status"] != "running":
                    raise RuntimeError("Smoke scheduler exited before becoming healthy")
                time.sleep(1)
            else:
                raise RuntimeError("Smoke health check timed out")
            logs = docker("logs", container)
            if "Timezone: America/Phoenix" not in logs or "Jobs: 0" not in logs:
                raise RuntimeError("Timezone or idle scheduler verification failed")
            if docker("exec", container, "id", "-u") != "10001":
                raise RuntimeError("Expected non-root runtime user")
            docker("stop", "--time", "10", container)
            state = json.loads(docker("inspect", "--format", "{{json .State}}", container))
            if state["ExitCode"] != 0:
                raise RuntimeError("Scheduler did not shut down cleanly")
            print(
                "PASS: isolated idle container healthy, UID 10001, TZ America/Phoenix, graceful SIGTERM exit 0"
            )
            print(
                "This smoke check makes no Immich requests and does not replace live private deployment validation."
            )
        finally:
            docker("rm", "-f", "-v", container)


if __name__ == "__main__":
    main()
