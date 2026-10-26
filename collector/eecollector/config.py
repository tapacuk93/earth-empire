"""Settings from the environment, secrets from AWS Secrets Manager (or a local JSON file for tests).

Secret values are never logged; `Secrets.__repr__` hides them.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path



def env(name: str, default: str | None = None) -> str | None:
    v = os.environ.get(name)
    return v if v not in (None, "") else default


@dataclass
class Settings:
    api: str = field(default_factory=lambda: env("EE_API_URL", env("EE_API", "https://api.empire.earth")).rstrip("/"))
    region: str = field(default_factory=lambda: env("AWS_REGION", env("EE_REGION", "us-east-1")))
    state_dir: Path = field(default_factory=lambda: Path(env("EE_STATE_DIR", "/var/lib/earth-empire/collector")))
    # One persistent browser profile per site; the Facebook poster keeps its own next to it.
    profile_dir: Path = field(default_factory=lambda: Path(env("EE_BROWSER_PROFILE", "/var/lib/earth-empire/browser/instagram")))
    log_dir: Path = field(default_factory=lambda: Path(env("EE_LOG_DIR", "/var/log/earth-empire/collector")))
    secrets_file: str | None = field(default_factory=lambda: env("EE_SECRETS_FILE"))
    # Browser identity: keep it stable between runs.
    user_agent: str | None = field(default_factory=lambda: env("EE_USER_AGENT"))
    locale: str = field(default_factory=lambda: env("EE_LOCALE", "en-US"))
    timezone: str = field(default_factory=lambda: env("EE_TIMEZONE", "Europe/Kyiv"))
    channel: str | None = field(default_factory=lambda: env("EE_BROWSER_CHANNEL", "chromium"))
    # CONTRACT.md: automation does not type passwords. EE_AUTO_LOGIN=1 allows one attempt.
    auto_login: bool = field(default_factory=lambda: env("EE_AUTO_LOGIN", "0") == "1")
    headless: bool = field(default_factory=lambda: env("EE_HEADLESS", "1") != "0")
    # Pacing of Instagram requests (seconds) and a hard cap per hour.
    min_gap: float = field(default_factory=lambda: float(env("EE_MIN_GAP", "12")))
    max_gap: float = field(default_factory=lambda: float(env("EE_MAX_GAP", "30")))
    per_hour: int = field(default_factory=lambda: int(env("EE_MAX_PER_HOUR", "80")))
    # of those, kept for the owner's own profile (posts, stories, highlights): reposts never use them
    own_reserve: int = field(default_factory=lambda: int(env("EE_OWN_RESERVE_PER_HOUR", "20")))

    # Which machine runs the collector: the SSM parameter /earth-empire/collector/runner names it
    # ("box" or "mac"); a runner whose EE_RUNNER differs stays off Instagram. Missing = anyone.
    runner: str = field(default_factory=lambda: env("EE_RUNNER", "box"))
    runner_param: str = "/earth-empire/collector/runner"

    @property
    def profile_lock(self) -> Path:
        """CONTRACT.md: hold flock /var/lib/earth-empire/browser/<name>.lock while using a profile."""
        return self.profile_dir.parent / f"{self.profile_dir.name}.lock"

    @property
    def state_db(self) -> Path:
        return self.state_dir / "state.sqlite"


class Secrets:
    """Lazily read secrets. Values never appear in repr or logs."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self._cache: dict[str, dict] = {}

    def __repr__(self) -> str:
        return "<Secrets hidden>"

    def get(self, name: str, required: bool = True) -> dict | None:
        if name in self._cache:
            return self._cache[name]
        val: dict | None = None
        if self.settings.secrets_file:
            data = json.loads(Path(self.settings.secrets_file).read_text())
            val = data.get(name)
        else:
            import boto3
            from botocore.exceptions import ClientError
            sm = boto3.client("secretsmanager", region_name=self.settings.region)
            try:
                raw = sm.get_secret_value(SecretId=name)["SecretString"]
                try:
                    val = json.loads(raw)
                except json.JSONDecodeError:
                    val = raw
                if not isinstance(val, dict):
                    val = {"value": str(val)}
            except ClientError as e:
                code = e.response.get("Error", {}).get("Code")
                if code != "ResourceNotFoundException" or required:
                    raise
        if val is None and required:
            raise KeyError(f"secret {name} is missing")
        self._cache[name] = val
        return val

    def ingest_token(self) -> str:
        if env("EE_INGEST_TOKEN"):  # local tests against the mock backend
            return env("EE_INGEST_TOKEN")
        s = self.get("earth-empire/ingest-token")
        return str(s.get("token") or s.get("value"))

    def instagram(self) -> dict:
        return self.get("earth-empire/instagram")

    def target(self) -> str:
        return str(self.get("earth-empire/target")["username"]).lstrip("@")

    def session_state(self) -> dict | None:
        """A Playwright storageState handed over after a login elsewhere (optional)."""
        s = self.get("earth-empire/instagram-session", required=False)
        if isinstance(s, dict) and "value" in s and isinstance(s["value"], str):
            try:
                s = json.loads(s["value"])
            except json.JSONDecodeError:
                return None
        if isinstance(s, dict) and s.get("cookies"):
            return s
        return None


def is_placeholder(v: str | None) -> bool:
    if not v or not str(v).strip():
        return True
    low = str(v).strip().lower()
    return low.startswith("<") or any(m in low for m in ("placeholder", "changeme", "change-me")) \
        or low in ("todo", "tbd", "xxx", "username", "password", "example")


def active_runner(s: Settings) -> str | None:
    """The runner named in SSM, or None when unset or unreadable (then this runner may run)."""
    if env("EE_RUNNER_CHECK", "1") == "0":
        return None
    try:
        import boto3
        r = boto3.client("ssm", region_name=s.region).get_parameter(Name=s.runner_param)
        return r["Parameter"]["Value"].strip() or None
    except Exception as e:  # noqa: BLE001
        if "ParameterNotFound" in type(e).__name__ or "ParameterNotFound" in str(e):
            return None
        raise
