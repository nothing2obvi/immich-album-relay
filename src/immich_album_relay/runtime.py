"""Local process locks, credential redaction and timezone-aware logging."""

import fcntl
import logging
import re
import sys
from contextlib import contextmanager
from datetime import datetime
from logging.handlers import RotatingFileHandler
from zoneinfo import ZoneInfo

from .api import RelayError


@contextmanager
def lock(state_dir, name):
    state_dir.mkdir(parents=True, exist_ok=True)
    with (state_dir / f"{name}.lock").open("a") as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RelayError("Execution already running; overlapping execution skipped") from None
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


class SafeFormatter(logging.Formatter):
    def __init__(self, zone, secrets):
        super().__init__("%(asctime)s [%(levelname)s] %(message)s")
        self.zone = ZoneInfo(zone)
        self.secrets = sorted((s for s in secrets if s), key=len, reverse=True)

    def formatTime(self, record, datefmt=None):
        return datetime.fromtimestamp(record.created, self.zone).isoformat(timespec="seconds")

    def format(self, record):
        text = super().format(record)
        for secret in self.secrets:
            text = text.replace(secret, "[REDACTED]")
        # Keep untrusted album names/config labels on one log line, remove terminal control characters.
        return re.sub(r"[\x00-\x1f\x7f]", " ", text)


def setup_logging(config):
    secrets = [u.api_key.get_secret_value() for u in config.users.values()]
    secrets += [config.ntfy.token.get_secret_value(), config.ntfy.password.get_secret_value()]
    formatter = SafeFormatter(config.timezone, secrets)
    handlers = [logging.StreamHandler(sys.stdout)]
    if config.logging.file:
        config.logging.file.parent.mkdir(parents=True, exist_ok=True)
        handlers.append(
            RotatingFileHandler(
                config.logging.file,
                maxBytes=config.logging.max_bytes,
                backupCount=config.logging.backup_count,
            )
        )
    for handler in handlers:
        handler.setFormatter(formatter)
    logging.basicConfig(level=config.logging.level, handlers=handlers, force=True)
