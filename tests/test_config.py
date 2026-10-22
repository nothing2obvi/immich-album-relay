import copy

import pytest
import yaml
from pydantic import ValidationError

from immich_album_relay.config import Config, ConfigError, load_config


def test_tz_environment_default(data, monkeypatch):
    monkeypatch.setenv("TZ", "America/Phoenix")
    config = Config.model_validate(data)
    assert config.timezone == "America/Phoenix"
    assert config.schedule(config.jobs[0]).timezone == "America/Phoenix"


def test_timezone_precedence(data, monkeypatch):
    monkeypatch.setenv("TZ", "UTC")
    data["timezone"] = "America/Phoenix"
    data["cron"] = {"timezone": "Europe/London"}
    data["jobs"][0]["cron"] = {"timezone": "Asia/Tokyo"}
    config = Config.model_validate(data)
    assert config.timezone == "America/Phoenix"
    assert config.schedule(config.jobs[0]).timezone == "Asia/Tokyo"


@pytest.mark.parametrize("tz", ["Invalid/Zone", "", "../etc/passwd"])
def test_invalid_tz(data, monkeypatch, tz):
    monkeypatch.setenv("TZ", tz)
    with pytest.raises((ValueError, ValidationError)):
        Config.model_validate(data)


def test_default_utc(data, monkeypatch):
    monkeypatch.delenv("TZ", raising=False)
    assert Config.model_validate(data).timezone == "UTC"


@pytest.mark.parametrize(
    "change",
    [
        lambda d: d.update(unknown=True),
        lambda d: d["jobs"].append(copy.deepcopy(d["jobs"][0])),
        lambda d: d["jobs"][0].update(destinations=["missing"]),
        lambda d: d["jobs"][0]["sources"][0].update(user="missing"),
        lambda d: d["users"]["alex"].update(id="not-a-uuid"),
        lambda d: d["users"]["alex"].update(api_key=""),
        lambda d: d.update(http={"batch_size": 0}),
        lambda d: d.update(cron={"expression": "* * * * * *"}),
        lambda d: d.update(cron={"expression": "@daily"}),
        lambda d: d.update(cron={"expression": "0 25 * * *"}),
        lambda d: d.update(ntfy={"enabled": True}),
        lambda d: d.update(immich_url="https://user:secret@example.com"),
        lambda d: d.update(immich_url="https://example.com?apiKey=secret"),
    ],
)
def test_invalid_settings(data, change):
    change(data)
    with pytest.raises((ValueError, ValidationError)):
        Config.model_validate(data)


def test_missing_env_and_yaml_secret_redaction(tmp_path, data, monkeypatch):
    path = tmp_path / "config.yml"
    data["users"]["alex"]["api_key"] = "${NONEXISTENT_RELAY_KEY}"
    path.write_text(yaml.safe_dump(data))
    monkeypatch.delenv("NONEXISTENT_RELAY_KEY", raising=False)
    with pytest.raises(ConfigError, match="Missing environment variable: NONEXISTENT_RELAY_KEY"):
        load_config(path)
    monkeypatch.setenv("NONEXISTENT_RELAY_KEY", "a: [dangerous-yaml-content")
    assert load_config(path).users["alex"].api_key.get_secret_value() == "a: [dangerous-yaml-content"
    data["unknown"] = "SUPER-SECRET-DO-NOT-LOG"
    path.write_text(yaml.safe_dump(data))
    with pytest.raises(ConfigError) as error:
        load_config(path)
    assert "SUPER-SECRET" not in str(error.value)


def test_duplicate_yaml_keys(tmp_path):
    path = tmp_path / "bad.yml"
    path.write_text("dry_run: true\ndry_run: false\n")
    with pytest.raises(ConfigError, match="unique"):
        load_config(path)


def test_global_master_switches(data):
    for kind in ["cron", "polling"]:
        data[kind] = {"enabled": False}
        data["jobs"][0][kind] = {"enabled": True}
    config = Config.model_validate(data)
    assert not config.schedule(config.jobs[0]).enabled
    assert not config.detection(config.jobs[0]).enabled


def test_example_valid(monkeypatch):
    monkeypatch.setenv("IMMICH_URL", "https://photos.example.com")
    monkeypatch.setenv("IMMICH_ALEX_API_KEY", "example-alex")
    monkeypatch.setenv("IMMICH_SAM_API_KEY", "example-sam")
    assert load_config("config.example.yml").dry_run is True


@pytest.mark.parametrize("expression", ["0 9 * MAR THU", "0 9 * JAN-MAR MON-FRI"])
def test_standard_named_cron_fields(data, expression):
    data["cron"] = {"expression": expression}
    assert Config.model_validate(data).cron.expression == expression


@pytest.mark.parametrize("expression", ["0 9 L * *", "H * * * *", "0 9 * * 5#2"])
def test_reject_nonstandard_cron_extensions(data, expression):
    data["cron"] = {"expression": expression}
    with pytest.raises(ValidationError):
        Config.model_validate(data)


def test_global_ntfy_disable_is_a_master_switch(data):
    data["ntfy"] = {"enabled": False}
    data["jobs"][0]["ntfy"] = {"enabled": True}
    config = Config.model_validate(data)
    assert not config.notification(config.jobs[0]).enabled


def test_startup_runs_enabled_by_default_and_support_optout(data):
    config = Config.model_validate(data)
    assert config.run_on_startup and config.jobs[0].run_on_startup
    data["run_on_startup"] = False
    data["jobs"][0]["run_on_startup"] = False
    config = Config.model_validate(data)
    assert not config.run_on_startup and not config.jobs[0].run_on_startup
