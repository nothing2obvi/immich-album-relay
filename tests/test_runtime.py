import logging
import time
from datetime import UTC, datetime

import pytest

from immich_album_relay.api import RelayError
from immich_album_relay.config import Cron
from immich_album_relay.runtime import SafeFormatter, lock
from immich_album_relay.scheduler import CronTracker, PollTracker, healthcheck, write_health


def test_poll_debounce_retry_reconcile():
    tracker = PollTracker()
    assert not tracker.due("first", 0, 10, 100)
    assert not tracker.due("second", 5, 10, 100)
    assert not tracker.due("second", 14, 10, 100)
    assert tracker.due("second", 15, 10, 100)
    # Failed execution does not checkpoint, so retry even with unchanged membership.
    assert tracker.due("second", 20, 10, 100)
    tracker.success("second", 20)
    assert not tracker.due("second", 21, 10, 100)
    assert tracker.due("second", 120, 10, 100)


def test_tz_cron_and_same_minute_deduplication():
    tracker = CronTracker()
    schedule = Cron(expression="0 3 * * *", timezone="America/Phoenix")
    now = datetime(2026, 10, 21, 10, 0, tzinfo=UTC)
    assert tracker.due("job", schedule, now)
    assert not tracker.due("job", schedule, now.replace(second=30))
    assert not tracker.due("job", schedule, now.replace(minute=1))


def test_standard_cron_day_of_month_or_week():
    tracker = CronTracker()
    schedule = Cron(expression="0 9 1 * 3", timezone="UTC")
    assert tracker.due("a", schedule, datetime(2026, 10, 21, 9, tzinfo=UTC))
    assert tracker.due("b", schedule, datetime(2026, 11, 1, 9, tzinfo=UTC))


def test_dst_repeated_hour_each_runs_and_missing_hour_skipped():
    tracker = CronTracker()
    schedule = Cron(expression="30 1 * * *", timezone="America/New_York")
    assert tracker.due("job", schedule, datetime(2026, 11, 1, 5, 30, tzinfo=UTC))
    assert tracker.due("job", schedule, datetime(2026, 11, 1, 6, 30, tzinfo=UTC))
    spring = Cron(expression="30 2 * * *", timezone="America/New_York")
    assert not tracker.due("spring", spring, datetime(2026, 3, 8, 7, 30, tzinfo=UTC))


def test_process_overlap_lock(tmp_path):
    with lock(tmp_path, "job"):
        with pytest.raises(RelayError, match="already running"):
            with lock(tmp_path, "job"):
                pass
    with lock(tmp_path, "job"):
        pass


def test_timezone_log_redaction():
    formatter = SafeFormatter("America/Phoenix", ["SECRET"])
    record = logging.LogRecord("test", logging.INFO, "", 0, "name\nSECRET\x1b[31m", (), None)
    record.created = datetime(2026, 10, 21, 10, tzinfo=UTC).timestamp()
    text = formatter.format(record)
    assert "03:00:00-07:00" in text
    assert "SECRET" not in text and "\n" not in text and "\x1b" not in text


def test_health_requires_fresh_heartbeat(tmp_path, monkeypatch):
    assert healthcheck(tmp_path) == 1
    write_health(tmp_path / "heartbeat")
    assert healthcheck(tmp_path) == 0
    monkeypatch.setattr(time, "time", lambda: (tmp_path / "heartbeat").stat().st_mtime + 31)
    assert healthcheck(tmp_path) == 1


@pytest.mark.parametrize(
    "global_enabled,job_enabled,enabled,dry_run,expected",
    [
        (True, True, True, False, 1),
        (False, True, True, False, 0),
        (True, False, True, False, 0),
        (True, True, False, False, 0),
        (True, True, True, True, 1),
    ],
)
def test_startup_execution_independent_of_cron_and_polling(
    config, fake, monkeypatch, global_enabled, job_enabled, enabled, dry_run, expected
):
    import threading

    from immich_album_relay.relay import Relay
    from immich_album_relay.scheduler import serve

    class Stop(threading.Event):
        ticks = 0

        def wait(self, timeout=None):
            self.ticks += 1
            if self.ticks >= 20:
                self.set()
            return super().wait(0.01)

    config.run_on_startup = global_enabled
    config.jobs[0].run_on_startup = job_enabled
    config.jobs[0].enabled = enabled
    config.cron.enabled = config.polling.enabled = False
    config.dry_run = dry_run
    stop = Stop()
    relay = Relay(config, stop, client_factory=fake.client)
    reports = []
    execute = relay.execute

    def record(*args, **kwargs):
        report = execute(*args, **kwargs)
        reports.append(report)
        return report

    monkeypatch.setattr(relay, "execute", record)
    serve(relay, stop)
    assert len(reports) == expected
    assert all(r.trigger == "startup" and r.ok and r.dry_run == dry_run for r in reports)
    if dry_run or not expected:
        assert not fake.calls
    assert not (config.state_dir / "heartbeat").exists()


def test_startup_coalesces_initial_cron_and_polling(config, fake, monkeypatch):
    import threading

    from immich_album_relay.relay import Relay
    from immich_album_relay.scheduler import serve

    class Stop(threading.Event):
        ticks = 0

        def wait(self, timeout=None):
            self.ticks += 1
            if self.ticks >= 20:
                self.set()
            return super().wait(0.01)

    config.cron.expression = "* * * * *"
    config.polling.interval_seconds = 60
    stop = Stop()
    relay = Relay(config, stop, client_factory=fake.client)
    triggers = []
    execute = relay.execute

    def record(*args, **kwargs):
        report = execute(*args, **kwargs)
        triggers.append(report.trigger)
        return report

    monkeypatch.setattr(relay, "execute", record)
    serve(relay, stop)
    assert triggers == ["startup"]
