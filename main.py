import os
import sys
from dataclasses import dataclass
from typing import Optional

from mt2fa.bot import BotConfig, run_login


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
class Config:
    username: str
    password: str
    totp_secret: str
    login_url: str
    target_url: str

    username_selector: str
    password_selector: str
    submit_selector: str
    otp_selector: Optional[str]
    otp_submit_selector: Optional[str]
    logged_in_selector: Optional[str]

    state_path: str
    screenshot_path: str
    error_screenshot_path: str
    user_agent: str
    headless: bool
    start_jitter_seconds: int
    nav_timeout_ms: int
    timezone_id: str


def load_config() -> Config:
    username = _env("BOT_USERNAME")
    password = _env("BOT_PASSWORD")
    totp_secret = _env("BOT_TOTP_SECRET")
    login_url = _env("BOT_LOGIN_URL")
    target_url = _env("BOT_TARGET_URL")

    missing = [
        name
        for name, value in [
            ("BOT_USERNAME", username),
            ("BOT_PASSWORD", password),
            ("BOT_TOTP_SECRET", totp_secret),
            ("BOT_LOGIN_URL", login_url),
            ("BOT_TARGET_URL", target_url),
        ]
        if not value
    ]
    if missing:
        raise ValueError(f"Missing required env vars: {', '.join(missing)}")

    username_selector = _env("BOT_USERNAME_SELECTOR", 'input[name="username"]') or 'input[name="username"]'
    password_selector = _env("BOT_PASSWORD_SELECTOR", 'input[name="password"]') or 'input[name="password"]'
    submit_selector = _env("BOT_SUBMIT_SELECTOR", 'button[type="submit"]') or 'button[type="submit"]'

    otp_selector = _env("BOT_OTP_SELECTOR")
    otp_submit_selector = _env("BOT_OTP_SUBMIT_SELECTOR")
    logged_in_selector = _env("BOT_LOGGED_IN_SELECTOR")

    state_path = _env("BOT_STATE_PATH", "state.json") or "state.json"
    screenshot_path = _env("BOT_SCREENSHOT_PATH", "screenshot.png") or "screenshot.png"
    error_screenshot_path = _env("BOT_ERROR_SCREENSHOT_PATH", "error.png") or "error.png"

    user_agent = _env(
        "BOT_USER_AGENT",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    )
    headless = _env_bool("BOT_HEADLESS", True)
    start_jitter_seconds = _env_int("BOT_START_JITTER_SECONDS", 0)
    nav_timeout_ms = _env_int("BOT_NAV_TIMEOUT_MS", 60_000)
    timezone_id = _env("BOT_TIMEZONE_ID", "Asia/Shanghai") or "Asia/Shanghai"

    return Config(
        username=username,
        password=password,
        totp_secret=totp_secret,
        login_url=login_url,
        target_url=target_url,
        username_selector=username_selector,
        password_selector=password_selector,
        submit_selector=submit_selector,
        otp_selector=otp_selector,
        otp_submit_selector=otp_submit_selector,
        logged_in_selector=logged_in_selector,
        state_path=state_path,
        screenshot_path=screenshot_path,
        error_screenshot_path=error_screenshot_path,
        user_agent=user_agent,
        headless=headless,
        start_jitter_seconds=start_jitter_seconds,
        nav_timeout_ms=nav_timeout_ms,
        timezone_id=timezone_id,
    )


def main() -> int:
    try:
        cfg = load_config()
        result = run_login(
            BotConfig(
                username=cfg.username,
                password=cfg.password,
                totp_secret=cfg.totp_secret,
                login_url=cfg.login_url,
                target_url=cfg.target_url,
                username_selector=cfg.username_selector,
                password_selector=cfg.password_selector,
                submit_selector=cfg.submit_selector,
                otp_selector=cfg.otp_selector,
                otp_submit_selector=cfg.otp_submit_selector,
                logged_in_selector=cfg.logged_in_selector,
                state_path=cfg.state_path,
                screenshot_path=cfg.screenshot_path,
                error_screenshot_path=cfg.error_screenshot_path,
                user_agent=cfg.user_agent,
                headless=cfg.headless,
                start_jitter_seconds=cfg.start_jitter_seconds,
                nav_timeout_ms=cfg.nav_timeout_ms,
                timezone_id=cfg.timezone_id,
            )
        )
        if result.ok:
            print(">>> 任务完成")
            return 0
        print(f"!!! 失败: {result.message}", file=sys.stderr)
        return 1
    except (ValueError, RuntimeError) as e:
        print(f"!!! 失败: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
