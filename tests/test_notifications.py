from immich_album_relay.api import RelayError
from immich_album_relay.relay import Relay


def test_optional_ntfy_disabled(config, fake, monkeypatch):
    def unexpected(*args, **kwargs):
        raise AssertionError("ntfy should be disabled")

    monkeypatch.setattr("immich_album_relay.relay.Transport.request", unexpected)
    assert Relay(config, client_factory=fake.client).execute(config.jobs[0]).ok


def test_ntfy_success_unicode_and_secret_redaction(config, fake, monkeypatch):
    config.ntfy.enabled = True
    config.ntfy.topic = "test-topic"
    config.ntfy.token = type(config.ntfy.token)("ntfy-secret")
    config.jobs[0].name = "Family 📷 secret-alex"
    calls = []
    monkeypatch.setattr("immich_album_relay.relay.Transport.request", lambda *a, **k: calls.append((a, k)))
    relay = Relay(config, client_factory=fake.client)
    assert relay.execute(config.jobs[0]).ok
    body = calls[0][0][4]
    assert body["topic"] == "test-topic" and "6 assets added" in body["message"]
    assert "secret-alex" not in body["title"] and "📷" in body["title"]
    assert calls[0][0][3]["Authorization"] == "Bearer ntfy-secret"
    relay.execute(config.jobs[0])
    assert len(calls) == 1  # Unchanged memberships do not notify.


def test_ntfy_failure_does_not_fail_job(config, fake, monkeypatch):
    config.ntfy.enabled = True
    config.ntfy.topic = "test-topic"

    def fail(*args, **kwargs):
        raise RelayError("Network failure")

    monkeypatch.setattr("immich_album_relay.relay.Transport.request", fail)
    assert Relay(config, client_factory=fake.client).execute(config.jobs[0]).ok


def test_per_job_notification_override(config, fake, monkeypatch):
    config.ntfy.enabled = True
    config.ntfy.topic = "test-topic"
    config.jobs[0].ntfy.enabled = False
    calls = []
    monkeypatch.setattr("immich_album_relay.relay.Transport.request", lambda *a, **k: calls.append(a))
    assert Relay(config, client_factory=fake.client).execute(config.jobs[0]).ok
    assert not calls


def test_startup_notifications_supported_by_default(config, fake, monkeypatch):
    config.ntfy.enabled = True
    config.ntfy.topic = "test-topic"
    calls = []
    monkeypatch.setattr("immich_album_relay.relay.Transport.request", lambda *a, **k: calls.append(a))
    assert Relay(config, client_factory=fake.client).execute(config.jobs[0], trigger="startup").ok
    assert len(calls) == 1
    assert "Trigger: startup" in calls[0][4]["message"]
