"""Strict configuration validation and safe scalar environment expansion."""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import yaml
from croniter import croniter
from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator, model_validator


class ConfigError(ValueError):
    pass


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


def timezone_name(value: str) -> str:
    try:
        ZoneInfo(value)
    except (ValueError, ZoneInfoNotFoundError):
        raise ValueError("must be a valid IANA timezone") from None
    return value


def http_url(value: str) -> str:
    parts = urlsplit(value)
    if parts.scheme not in {"http", "https"} or not parts.hostname or parts.username or parts.password:
        raise ValueError("must be an HTTP(S) URL without embedded credentials")
    if parts.query or parts.fragment:
        raise ValueError("URL cannot contain query parameters or a fragment")
    return value.rstrip("/")


class User(Model):
    id: UUID
    name: str = ""
    api_key: SecretStr

    @field_validator("api_key")
    @classmethod
    def key_not_empty(cls, value):
        if not value.get_secret_value().strip():
            raise ValueError("API key cannot be empty")
        return value


class Album(Model):
    id: UUID
    name: str = ""


class Destination(Album):
    user: str | None = None


class Source(Model):
    user: str
    albums: list[Album] = Field(min_length=1)


class CronOverride(Model):
    enabled: bool | None = None
    expression: str | None = None
    timezone: str | None = None

    @field_validator("expression")
    @classmethod
    def valid_cron(cls, value):
        # Exclude croniter extensions (seconds, years, aliases, random, hashed, last/nth).
        if value is not None:
            if (
                len(value.split()) != 5
                or re.search(r"[^\d\s*,/\-A-Za-z]", value)
                or any(
                    word.upper()
                    not in {
                        "JAN",
                        "FEB",
                        "MAR",
                        "APR",
                        "MAY",
                        "JUN",
                        "JUL",
                        "AUG",
                        "SEP",
                        "OCT",
                        "NOV",
                        "DEC",
                        "SUN",
                        "MON",
                        "TUE",
                        "WED",
                        "THU",
                        "FRI",
                        "SAT",
                    }
                    for word in re.findall(r"[A-Za-z]+", value)
                )
                or not croniter.is_valid(value)
            ):
                raise ValueError("must be a standard five-field cron expression")
        return value

    @field_validator("timezone")
    @classmethod
    def valid_zone(cls, value):
        return timezone_name(value) if value is not None else value


class Cron(CronOverride):
    enabled: bool = True
    expression: str = "0 * * * *"


class PollOverride(Model):
    enabled: bool | None = None
    interval_seconds: int | None = Field(default=None, ge=1)
    debounce_seconds: int | None = Field(default=None, ge=0)
    reconcile_seconds: int | None = Field(default=None, ge=1)


class Polling(PollOverride):
    enabled: bool = True
    interval_seconds: int = Field(default=60, ge=1)
    debounce_seconds: int = Field(default=10, ge=0)
    reconcile_seconds: int = Field(default=3600, ge=1)


class NtfyOverride(Model):
    enabled: bool | None = None
    on_success: bool | None = None
    on_failure: bool | None = None
    on_no_changes: bool | None = None
    triggers: list[Literal["cron", "polling", "manual", "startup"]] | None = None


class Ntfy(NtfyOverride):
    enabled: bool = False
    server_url: str = "https://ntfy.sh"
    topic: str = ""
    token: SecretStr = SecretStr("")
    username: str = ""
    password: SecretStr = SecretStr("")
    priority: int = Field(default=3, ge=1, le=5)
    on_success: bool = True
    on_failure: bool = True
    on_no_changes: bool = False
    triggers: list[Literal["cron", "polling", "manual", "startup"]] = ["cron", "polling", "manual", "startup"]
    _url = field_validator("server_url")(http_url)

    @model_validator(mode="after")
    def authentication(self):
        if self.token.get_secret_value() and (self.username or self.password.get_secret_value()):
            raise ValueError("choose ntfy token or username/password")
        if bool(self.username) != bool(self.password.get_secret_value()):
            raise ValueError("ntfy username and password must be provided together")
        if self.topic and not re.fullmatch(r"[A-Za-z0-9_-]+", self.topic):
            raise ValueError("ntfy topic must contain only letters, numbers, underscores or hyphens")
        if self.enabled and not self.topic:
            raise ValueError("enabled ntfy requires a topic")
        return self


class Http(Model):
    timeout_seconds: float = Field(default=30, gt=0, le=300)
    retries: int = Field(default=3, ge=0, le=10)
    backoff_seconds: float = Field(default=1, ge=0, le=60)
    max_retry_delay_seconds: float = Field(default=60, ge=1, le=300)
    batch_size: int = Field(default=200, ge=1, le=1000)
    page_size: int = Field(default=500, ge=1, le=1000)


class Logging(Model):
    level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    file: Path | None = None
    max_bytes: int = Field(default=10485760, ge=1024)
    backup_count: int = Field(default=3, ge=1, le=100)


class Job(Model):
    id: str = Field(pattern=r"^[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}$")
    name: str = ""
    enabled: bool = True
    run_on_startup: bool = True
    destinations: list[str] = Field(min_length=1)
    sources: list[Source] = Field(min_length=1)
    cron: CronOverride = Field(default_factory=CronOverride)
    polling: PollOverride = Field(default_factory=PollOverride)
    ntfy: NtfyOverride = Field(default_factory=NtfyOverride)


def merge(base, override):
    return type(base).model_validate(base.model_dump() | override.model_dump(exclude_none=True))


class Config(Model):
    immich_url: str
    timezone: str = Field(default_factory=lambda: os.environ.get("TZ", "UTC"))
    state_dir: Path = Path("/data")
    dry_run: bool = False
    run_on_startup: bool = True
    users: dict[str, User] = Field(min_length=1)
    destinations: dict[str, Destination] = Field(min_length=1)
    jobs: list[Job] = Field(min_length=1)
    cron: Cron = Field(default_factory=Cron)
    polling: Polling = Field(default_factory=Polling)
    http: Http = Field(default_factory=Http)
    logging: Logging = Field(default_factory=Logging)
    ntfy: Ntfy = Field(default_factory=Ntfy)
    _url = field_validator("immich_url")(http_url)
    _zone = field_validator("timezone")(timezone_name)

    @model_validator(mode="after")
    def references(self):
        timezone_name(self.timezone)  # Also validate default obtained from TZ.
        if len({job.id for job in self.jobs}) != len(self.jobs):
            raise ValueError("job IDs must be unique")
        if len({user.id for user in self.users.values()}) != len(self.users):
            raise ValueError("define each immutable user ID once, then reuse its reference")
        for destination in self.destinations.values():
            if destination.user is not None and destination.user not in self.users:
                raise ValueError("destination references an unknown user")
        for job in self.jobs:
            if set(job.destinations) - self.destinations.keys():
                raise ValueError("job references an unknown destination")
            if len(set(job.destinations)) != len(job.destinations):
                raise ValueError("job has duplicate destination references")
            if len({s.user for s in job.sources}) != len(job.sources):
                raise ValueError("combine a user's source albums into one source entry per job")
            for source in job.sources:
                if source.user not in self.users:
                    raise ValueError("source references an unknown user")
            self.notification(job)  # Validate enabled per-job notification settings.
        return self

    def schedule(self, job):
        result = merge(self.cron, job.cron)
        result.enabled = self.cron.enabled and result.enabled
        result.timezone = result.timezone or self.timezone
        return result

    def detection(self, job):
        result = merge(self.polling, job.polling)
        result.enabled = self.polling.enabled and result.enabled
        return result

    def notification(self, job):
        values = self.ntfy.model_dump() | job.ntfy.model_dump(exclude_none=True)
        values["enabled"] = self.ntfy.enabled and values["enabled"]
        return Ntfy.model_validate(values)


class UniqueLoader(yaml.SafeLoader):
    pass


def unique_mapping(loader, node, deep=False):
    result = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if not isinstance(key, str) or key in result:
            raise ConfigError("YAML mapping keys must be unique strings")
        result[key] = loader.construct_object(value_node, deep=deep)
    return result


UniqueLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, unique_mapping)
ENV = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")


def expand(value):
    if isinstance(value, str):

        def replace(match):
            name = match[1]
            if name not in os.environ:
                raise ConfigError(f"Missing environment variable: {name}")
            return os.environ[name]

        return ENV.sub(replace, value)
    if isinstance(value, list):
        return [expand(item) for item in value]
    if isinstance(value, dict):
        return {key: expand(item) for key, item in value.items()}
    return value


def load_config(path: Path | str) -> Config:
    from pydantic import ValidationError

    try:
        data = yaml.load(Path(path).read_text(), Loader=UniqueLoader)
        return Config.model_validate(expand(data))
    except ValidationError as error:
        # Never include input values, context, or arbitrary validator error text (may contain secrets).
        details = "; ".join(
            f"{'.'.join(map(str, e['loc'])) or 'config'}: {e['type']}"
            for e in error.errors(include_input=False, include_context=False)
        )
        raise ConfigError(
            f"Invalid configuration ({details}); check IDs, references, timezone and settings"
        ) from None
    except (yaml.YAMLError, OSError, RecursionError):
        raise ConfigError(
            "Cannot read configuration or invalid YAML; check file, syntax and permissions"
        ) from None
