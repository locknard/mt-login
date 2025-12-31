import os
from dataclasses import dataclass
from typing import Optional


def _env(name: str, default: Optional[str] = None) -> Optional[str]:
    value = os.environ.get(name)
    if value is None:
        return default
    value = value.strip()
    return value if value else default


def _env_bool(name: str, default: bool) -> bool:
    value = _env(name)
    if value is None:
        return default
    return value.lower() in {"1", "true", "yes", "y", "on"}


def _env_int(name: str, default: int) -> int:
    value = _env(name)
    if value is None:
        return default
    try:
        return int(value)
    except ValueError:
        raise ValueError(f"{name} must be an integer, got: {value!r}")


@dataclass(frozen=True)
class Settings:
    db_url: str
    data_dir: str
    master_key: str
    basic_auth_user: str
    basic_auth_password: str
    poll_interval_seconds: int


def load_settings() -> Settings:
    data_dir = _env("APP_DATA_DIR", "/data") or "/data"
    db_url = _env("APP_DB_URL", f"sqlite:///{data_dir.rstrip('/')}/app.db")
    master_key = _env("APP_MASTER_KEY")
    basic_auth_user = _env("APP_BASIC_AUTH_USER")
    basic_auth_password = _env("APP_BASIC_AUTH_PASSWORD")
    poll_interval_seconds = _env_int("APP_POLL_INTERVAL_SECONDS", 60)

    missing = [
        name
        for name, value in [
            ("APP_DB_URL", db_url),
            ("APP_MASTER_KEY", master_key),
            ("APP_BASIC_AUTH_USER", basic_auth_user),
            ("APP_BASIC_AUTH_PASSWORD", basic_auth_password),
        ]
        if not value
    ]
    if missing:
        raise ValueError(f"Missing required env vars: {', '.join(missing)}")

    return Settings(
        db_url=db_url,
        data_dir=data_dir,
        master_key=master_key,
        basic_auth_user=basic_auth_user,
        basic_auth_password=basic_auth_password,
        poll_interval_seconds=poll_interval_seconds,
    )

