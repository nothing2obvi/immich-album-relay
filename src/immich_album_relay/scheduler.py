"""Independent cron and membership polling with bounded worker concurrency."""

from __future__ import annotations

import logging
import os
import signal
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from croniter import croniter

from .api import RelayError
from .runtime import lock

log = logging.getLogger(__name__)


@dataclass
class PollTracker:
    observed: str | None = None
    applied: str | None = None
    changed_at: float = 0
    last_success: float = 0

    def due(self, fingerprint, now, debounce, reconcile):
        if fingerprint != self.observed:
            self.observed = fingerprint
            self.changed_at = now
        stable = now - self.changed_at >= debounce
        return stable and (fingerprint != self.applied or now - self.last_success >= reconcile)

    def success(self, fingerprint, now):
        self.applied = fingerprint
        self.last_success = now


class CronTracker:
    def __init__(self):
        self.last_minute = {}

    def due(self, job_id, schedule, now):
        # Match wall clock minutes from UTC instants, so missing DST times are skipped and
        # repeated DST times each execute. No synthetic missed-run backlog on restart.
        minute = int(now.timestamp() // 60)
        if self.last_minute.get(job_id, -1) >= minute:
            return False
        self.last_minute[job_id] = minute
        return schedule.enabled and croniter.match(
            schedule.expression, now.astimezone(ZoneInfo(schedule.timezone))
        )


def write_health(path: Path):
    temporary = path.with_suffix(".tmp")
    temporary.write_text(str(time.time()))
    os.replace(temporary, path)


def healthcheck(state_dir):
    try:
        age = time.time() - (state_dir / "heartbeat").stat().st_mtime
        return 0 if 0 <= age < 30 else 1
    except OSError:
        return 1


def serve(relay, stop=None):
    config = relay.config
    stop = stop or threading.Event()
    relay.stop = stop
    previous = {}
    for sig in (signal.SIGINT, signal.SIGTERM):
        previous[sig] = signal.signal(sig, lambda *_: stop.set())
    try:
        with lock(config.state_dir, "scheduler"):
            heartbeat = config.state_dir / "heartbeat"
            cron = CronTracker()
            jobs = relay.selected()
            trackers = {job.id: PollTracker() for job in jobs}
            next_poll = {job.id: 0.0 for job in jobs}
            futures = {}
            queued_cron = {}

            def poll(job):
                settings = config.detection(job)
                try:
                    fingerprint = relay.fingerprint(job)
                    now = time.monotonic()
                    tracker = trackers[job.id]
                    if tracker.due(fingerprint, now, settings.debounce_seconds, settings.reconcile_seconds):
                        report = relay.execute(job, trigger="polling")
                        if report.ok:
                            tracker.success(fingerprint, time.monotonic())
                except RelayError as error:
                    log.error("Job %s | Polling failed: %s", job.id, error)

            log.info(
                "Scheduler started | Timezone: %s | Automatic detection: membership polling | Jobs: %d",
                config.timezone,
                len(jobs),
            )
            try:
                with ThreadPoolExecutor(max_workers=4, thread_name_prefix="relay") as workers:
                    while not stop.is_set():
                        write_health(heartbeat)
                        now = datetime.now(UTC)
                        tick = time.monotonic()
                        for job in jobs:
                            active = futures.get(job.id)
                            if active and active.done():
                                try:
                                    active.result()
                                except Exception:
                                    log.error(
                                        "Job %s | Worker failed; execution will be retried on its next trigger",
                                        job.id,
                                    )
                                del futures[job.id]
                                active = None
                            schedule = config.schedule(job)
                            if cron.due(job.id, schedule, now):
                                queued_cron[job.id] = now.replace(second=0, microsecond=0).isoformat()
                            if active:
                                continue
                            if job.id in queued_cron:
                                scheduled_at = queued_cron.pop(job.id)
                                futures[job.id] = workers.submit(
                                    relay.execute, job, "cron", False, scheduled_at
                                )
                            elif config.detection(job).enabled and tick >= next_poll[job.id]:
                                next_poll[job.id] = tick + config.detection(job).interval_seconds
                                futures[job.id] = workers.submit(poll, job)
                        stop.wait(1)
                    log.info("Shutdown requested; waiting for active operations to stop")
            finally:
                heartbeat.unlink(missing_ok=True)
    finally:
        for sig, handler in previous.items():
            signal.signal(sig, handler)
