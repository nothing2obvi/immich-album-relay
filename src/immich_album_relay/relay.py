"""Relay orchestration: source credentials, owned assets, additive operations only."""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime

from .api import Immich, RelayError, Transport
from .runtime import lock

log = logging.getLogger(__name__)


@dataclass
class Row:
    user: str
    source: str
    destination: str
    found: int = 0
    already: int = 0
    added: int = 0
    skipped: int = 0
    failed: int = 0
    would_add: int = 0


@dataclass
class Report:
    job_id: str
    name: str
    trigger: str
    dry_run: bool
    rows: list[Row] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    duration: float = 0

    @property
    def added(self):
        return sum(r.added for r in self.rows)

    @property
    def ok(self):
        return not self.errors and not any(r.failed for r in self.rows)

    @property
    def status(self):
        return ("dry-run" if self.dry_run else "success") if self.ok else "failed"


class Relay:
    def __init__(self, config, stop=None, client_factory=None):
        self.config = config
        self.stop = stop
        self.client_factory = client_factory or (
            lambda ref: Immich(config, ref, Transport(config.http, stop))
        )

    def selected(self, job_id=None):
        if job_id and not any(j.id == job_id for j in self.config.jobs):
            raise RelayError("Unknown job ID")
        jobs = [j for j in self.config.jobs if j.enabled and (not job_id or j.id == job_id)]
        if job_id and not jobs:
            raise RelayError("Requested job is disabled; enable it in config.yml first")
        return jobs

    def validate(self):
        # Read-only; verify all configured users and enabled jobs. No empty write probes.
        for ref in self.config.users:
            client = self.client_factory(ref)
            client.identity()
            version = client.version()
            if (version["major"], version["minor"]) < (3, 2):
                raise RelayError(
                    "Requires Immich >=3.2 (structured album search); tested against v3.3.0 schema"
                )
            log.info(
                "User %s | Authentication verified | Immich %s.%s.%s",
                ref,
                version["major"],
                version["minor"],
                version["patch"],
            )
        for job in self.selected():
            for destination_ref in job.destinations:
                destination = self.config.destinations[destination_ref]
                if destination.user:
                    self.client_factory(destination.user).album(destination.id)
            for source in job.sources:
                client = self.client_factory(source.user)
                for album in source.albums:
                    client.album(album.id)
                    client.assets(album.id)
                for ref in job.destinations:
                    dest = self.config.destinations[ref]
                    client.album(dest.id, editor=True)
                    client.assets(dest.id)
        log.info(
            "Validation passed; write scopes and per-asset sharing permissions are confirmed only by an actual run"
        )

    def fingerprint(self, job):
        members = []
        for source in job.sources:
            client = self.client_factory(source.user)
            client.identity()
            for album in source.albums:
                client.album(album.id)
                members.append((source.user, str(album.id), sorted(client.assets(album.id))))
        return hashlib.sha256(json.dumps(members, sort_keys=True).encode()).hexdigest()

    def execute(self, job, trigger="manual", dry_run=False, scheduled_at=None):
        report = Report(job.id, job.name or job.id, trigger, dry_run or self.config.dry_run)
        started = time.monotonic()
        try:
            with lock(self.config.state_dir, f"job-{job.id}"):
                log.info(
                    "Job %s (%s) started | Trigger: %s | Scheduled: %s | Actual: %s | Dry-run: %s",
                    report.name,
                    job.id,
                    trigger,
                    scheduled_at or "-",
                    datetime.now(UTC).isoformat(),
                    report.dry_run,
                )
                self._execute(job, report)
        except RelayError as error:
            report.errors.append(str(error))
        except Exception:
            # Avoid logging arbitrary exception arguments that may contain credentials.
            report.errors.append(
                "Unexpected internal failure; check configuration or report a reproducible issue"
            )
        report.duration = time.monotonic() - started
        for error in report.errors:
            log.error("Job %s (%s) | %s", report.name, job.id, error)
        log.info(
            "Job %s (%s) completed | Trigger: %s | Status: %s | Added: %d | Duration: %.2fs",
            report.name,
            job.id,
            trigger,
            report.status,
            report.added,
            report.duration,
        )
        self.notify(job, report)
        return report

    def _execute(self, job, report):
        invalid_destinations = set()
        for ref in job.destinations:
            dest = self.config.destinations[ref]
            if dest.user:
                try:
                    owner = self.client_factory(dest.user)
                    owner.identity()
                    owner.album(dest.id)
                except RelayError as error:
                    invalid_destinations.add(ref)
                    report.errors.append(f"Destination {dest.name or ref} ({dest.id}): {error}")
        for source in job.sources:
            user = self.config.users[source.user]
            user_name = user.name or source.user
            client = self.client_factory(source.user)
            try:
                client.identity()
            except RelayError as error:
                report.errors.append(f"{user_name}: {error}")
                continue
            source_albums = []
            for album in source.albums:
                try:
                    info = client.album(album.id)
                    assets = client.assets(album.id)
                    label = f"{info.get('albumName', album.name)} ({album.id})"
                    source_albums.append((label, assets))
                except RelayError as error:
                    report.errors.append(f"{user_name} | Source {album.name} ({album.id}): {error}")
            for ref in job.destinations:
                if ref in invalid_destinations:
                    continue
                dest = self.config.destinations[ref]
                try:
                    info = client.album(dest.id, editor=True)
                    present = set(client.assets(dest.id))
                    destination_name = f"{info.get('albumName', dest.name)} ({dest.id})"
                except RelayError as error:
                    report.errors.append(f"{user_name} | Destination {dest.name or ref} ({dest.id}): {error}")
                    continue
                # Reuse destination membership across source albums to avoid duplicate writes.
                for source_name, assets in source_albums:
                    row = Row(user_name, source_name, destination_name, found=len(assets))
                    report.rows.append(row)
                    owned = {
                        asset_id for asset_id, asset in assets.items() if asset.get("ownerId") == str(user.id)
                    }
                    row.skipped = len(assets) - len(owned)
                    row.already = len(owned & present)
                    missing = sorted(owned - present)
                    if report.dry_run:
                        row.would_add = len(missing)
                        present.update(missing)
                    else:
                        for offset in range(0, len(missing), self.config.http.batch_size):
                            batch = missing[offset : offset + self.config.http.batch_size]
                            try:
                                results = client.add(dest.id, batch)
                                failure_reasons = {}
                                for asset_id in batch:
                                    result = results.get(asset_id, {})
                                    if result.get("success") is True:
                                        row.added += 1
                                        present.add(asset_id)
                                    elif result.get("error") == "duplicate":
                                        row.already += 1
                                        present.add(asset_id)
                                    else:
                                        row.failed += 1
                                        reason = result.get("error")
                                        safe_reason = (
                                            reason
                                            if reason
                                            in {"no_permission", "not_found", "unknown", "validation"}
                                            else "missing/invalid result"
                                        )
                                        failure_reasons[safe_reason] = failure_reasons.get(safe_reason, 0) + 1
                                    for reason, count in failure_reasons.items():
                                        report.errors.append(
                                            f"{user_name} → {destination_name}: {reason} ({count} assets)"
                                        )
                            except RelayError as error:
                                row.failed += len(batch)
                                report.errors.append(f"{user_name} → {destination_name}: {error}")
                    log.info(
                        "Job %s (%s) | %s | %s → %s | Found: %d | Added: %d | Already present: %d "
                        "| Skipped (not owned): %d | Failed: %d | Would add: %d",
                        report.name,
                        job.id,
                        user_name,
                        source_name,
                        destination_name,
                        row.found,
                        row.added,
                        row.already,
                        row.skipped,
                        row.failed,
                        row.would_add,
                    )

    def notify(self, job, report):
        settings = self.config.notification(job)
        if not settings.enabled or report.trigger not in settings.triggers:
            return
        if report.ok and (not settings.on_success or (not report.added and not settings.on_no_changes)):
            return
        if not report.ok and not settings.on_failure:
            return
        lines = [f"Trigger: {report.trigger}", f"Status: {report.status}"]
        for row in report.rows:
            lines.append(
                f"{row.user} | {row.source} → {row.destination}: {row.added} added, "
                f"{row.would_add} would add, {row.failed} failed"
            )
        lines += [f"Total: {report.added} assets added", *report.errors[:10]]
        # Redact known secrets even if a malicious album label contains a credential.
        message = "\n".join(lines)
        title = f"Immich Album Relay: {report.name}"
        for secret in [
            *(u.api_key.get_secret_value() for u in self.config.users.values()),
            settings.token.get_secret_value(),
            settings.password.get_secret_value(),
        ]:
            if secret:
                message = message.replace(secret, "[REDACTED]")
                title = title.replace(secret, "[REDACTED]")
        headers = {}
        if settings.token.get_secret_value():
            headers["Authorization"] = "Bearer " + settings.token.get_secret_value()
        elif settings.username:
            value = f"{settings.username}:{settings.password.get_secret_value()}"
            headers["Authorization"] = "Basic " + base64.b64encode(value.encode()).decode()
        try:
            # JSON publish supports Unicode titles without unsafe HTTP header interpolation.
            Transport(self.config.http, self.stop).request(
                "POST",
                settings.server_url,
                headers,
                {
                    "topic": settings.topic,
                    "title": title,
                    "message": message[:12000],
                    "priority": settings.priority,
                },
                expect_json=False,
            )
        except RelayError as error:
            log.warning("Job %s | ntfy notification failed: %s", job.id, error)
