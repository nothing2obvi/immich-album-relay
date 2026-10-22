"""Command-line entry points; validate and dry-run never modify Immich."""

import argparse
import json
import logging
import os
import sys
import threading
from pathlib import Path

from .api import Immich, RelayError
from .config import ConfigError, load_config
from .relay import Relay
from .runtime import setup_logging
from .scheduler import healthcheck, serve


def parser():
    root = argparse.ArgumentParser(prog="immich-album-relay")
    root.add_argument("--config", default=os.environ.get("RELAY_CONFIG", "/config/config.yml"))
    commands = root.add_subparsers(dest="command", required=True)
    validate = commands.add_parser("validate", help="Validate config and read-only API connectivity")
    validate.add_argument("--offline", action="store_true", help="Validate only configuration")
    albums = commands.add_parser("list-albums")
    albums.add_argument("--user", required=True, help="Configured user reference")
    run = commands.add_parser("run")
    run.add_argument("--job")
    run.add_argument("--dry-run", action="store_true")
    commands.add_parser("serve")
    health = commands.add_parser("healthcheck")
    health.add_argument("--state-dir", default=os.environ.get("RELAY_STATE_DIR", "/data"))
    return root


def main(argv=None):
    args = parser().parse_args(argv)
    if args.command == "healthcheck":
        return healthcheck(Path(args.state_dir))
    try:
        config = load_config(args.config)
        setup_logging(config)
        stop = threading.Event()
        relay = Relay(config, stop)
        if args.command == "validate":
            if not args.offline:
                relay.validate()
            logging.info("Configuration valid | Timezone: %s", config.timezone)
        elif args.command == "list-albums":
            if args.user not in config.users:
                raise RelayError("Unknown configured user reference")
            client = Immich(config, args.user)
            client.identity()
            for album in client.albums():
                # Exclude shared-link secrets, metadata, and unnecessary personal fields.
                members = [
                    {"id": entry.get("user", {}).get("id"), "role": entry.get("role")}
                    for entry in album.get("albumUsers", [])
                ]
                print(
                    json.dumps(
                        {
                            "id": album.get("id"),
                            "name": album.get("albumName"),
                            "owner_id": album.get("ownerId")
                            or next((m["id"] for m in members if m["role"] == "owner"), None),
                            "shared": album.get("shared"),
                            "members": members,
                        }
                    )
                )
        elif args.command == "run":
            reports = [relay.execute(job, dry_run=args.dry_run) for job in relay.selected(args.job)]
            return 0 if all(report.ok for report in reports) else 1
        elif args.command == "serve":
            serve(relay, stop)
        return 0
    except (ConfigError, RelayError) as error:
        print(f"[ERROR] {error}", file=sys.stderr)
        return 1
    except (OSError, ValueError):
        print(
            "[ERROR] Cannot initialize runtime; check timezone, file permissions and settings",
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
