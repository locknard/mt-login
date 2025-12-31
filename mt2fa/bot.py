from __future__ import annotations

import os
import random
import time
from dataclasses import dataclass
from typing import Optional

import pyotp
from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright


@dataclass(frozen=True)
class BotConfig:
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


@dataclass(frozen=True)
class BotResult:
    ok: bool
    message: str
    final_url: str
    state_path: str
    screenshot_path: str
    error_screenshot_path: str


class BotRunError(RuntimeError):
    pass


def _ensure_parent_dir(path: str) -> None:
    parent = os.path.dirname(os.path.abspath(path))
    if parent:
        os.makedirs(parent, exist_ok=True)


def _totp_now(secret: str) -> str:
    return pyotp.TOTP(secret).now()


def _looks_logged_out(page, cfg: BotConfig) -> bool:
    if "login" in page.url.lower():
        return True
    if page.locator(cfg.password_selector).count() > 0:
        return True
    if page.locator(cfg.username_selector).count() > 0:
        return True
    if cfg.logged_in_selector:
        return page.locator(cfg.logged_in_selector).count() == 0
    return False


def _ensure_logged_in(page, cfg: BotConfig) -> None:
    page.goto(cfg.target_url, wait_until="networkidle", timeout=cfg.nav_timeout_ms)

    if not _looks_logged_out(page, cfg):
        return

    page.goto(cfg.login_url, wait_until="domcontentloaded", timeout=cfg.nav_timeout_ms)

    page.fill(cfg.username_selector, cfg.username)
    page.fill(cfg.password_selector, cfg.password)
    page.click(cfg.submit_selector)
    page.wait_for_load_state("networkidle")

    otp_selector = None
    if cfg.otp_selector and page.locator(cfg.otp_selector).count() > 0:
        otp_selector = cfg.otp_selector
    else:
        otp_selector = _detect_otp_selector(page)

    if otp_selector:
        code = _totp_now(cfg.totp_secret)
        page.fill(otp_selector, code)
        if cfg.otp_submit_selector and page.locator(cfg.otp_submit_selector).count() > 0:
            page.click(cfg.otp_submit_selector)
        else:
            page.keyboard.press("Enter")
        page.wait_for_load_state("networkidle")

    page.goto(cfg.target_url, wait_until="networkidle", timeout=cfg.nav_timeout_ms)
    if _looks_logged_out(page, cfg):
        raise BotRunError("Login completed but still looks logged out; check selectors or captcha/2FA flow.")


def _detect_otp_selector(page) -> Optional[str]:
    candidates = []
    keywords = ("otp", "totp", "2fa", "mfa", "auth", "verify", "code", "token", "passcode", "驗證", "验证", "动态", "動態")
    for el in page.query_selector_all("input"):
        attrs = {
            "id": (el.get_attribute("id") or "").strip(),
            "name": (el.get_attribute("name") or "").strip(),
            "type": (el.get_attribute("type") or "").strip().lower(),
            "placeholder": (el.get_attribute("placeholder") or "").strip(),
            "aria-label": (el.get_attribute("aria-label") or "").strip(),
            "maxlength": (el.get_attribute("maxlength") or "").strip(),
            "autocomplete": (el.get_attribute("autocomplete") or "").strip().lower(),
        }

        if attrs["type"] in {"password", "hidden"}:
            continue
        if attrs["autocomplete"] in {"username", "current-password", "password", "email"}:
            continue

        hay = " ".join([attrs["id"], attrs["name"], attrs["placeholder"], attrs["aria-label"]]).lower()
        score = 0
        for kw in keywords:
            if kw.lower() in hay:
                score += 2
        if attrs["maxlength"] in {"6", "8"}:
            score += 1
        if score <= 0:
            continue

        selector = None
        if attrs["id"]:
            selector = f"#{attrs['id']}"
        elif attrs["name"]:
            selector = f'input[name="{attrs["name"]}"]'
        else:
            continue
        candidates.append((score, selector))

    if not candidates:
        return None
    candidates.sort(key=lambda x: x[0], reverse=True)
    return candidates[0][1]


def run_login(cfg: BotConfig) -> BotResult:
    if cfg.start_jitter_seconds > 0:
        time.sleep(random.randint(0, cfg.start_jitter_seconds))

    _ensure_parent_dir(cfg.state_path)
    _ensure_parent_dir(cfg.screenshot_path)
    _ensure_parent_dir(cfg.error_screenshot_path)

    browser = None
    page = None
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=cfg.headless, args=["--no-sandbox"])
            context_kwargs = {
                "user_agent": cfg.user_agent,
                "timezone_id": cfg.timezone_id,
                "locale": "zh-CN",
                "viewport": {"width": 1280, "height": 800},
            }
            if os.path.exists(cfg.state_path):
                context_kwargs["storage_state"] = cfg.state_path

            context = browser.new_context(**context_kwargs)
            page = context.new_page()
            page.set_default_navigation_timeout(cfg.nav_timeout_ms)
            page.set_default_timeout(cfg.nav_timeout_ms)

            _ensure_logged_in(page, cfg)
            context.storage_state(path=cfg.state_path)

            time.sleep(random.uniform(2.0, 5.0))
            page.screenshot(path=cfg.screenshot_path, full_page=True)
            return BotResult(
                ok=True,
                message="ok",
                final_url=page.url,
                state_path=cfg.state_path,
                screenshot_path=cfg.screenshot_path,
                error_screenshot_path=cfg.error_screenshot_path,
            )
    except (BotRunError, PlaywrightTimeoutError, PlaywrightError, Exception) as e:
        message = str(e) or e.__class__.__name__
        final_url = ""
        try:
            if page is not None:
                final_url = page.url
                page.screenshot(path=cfg.error_screenshot_path, full_page=True)
            else:
                with sync_playwright() as p:
                    browser2 = p.chromium.launch(headless=True, args=["--no-sandbox"])
                    context2 = browser2.new_context(user_agent=cfg.user_agent, timezone_id=cfg.timezone_id)
                    page2 = context2.new_page()
                    page2.goto(cfg.target_url, wait_until="domcontentloaded", timeout=min(cfg.nav_timeout_ms, 30_000))
                    final_url = page2.url
                    page2.screenshot(path=cfg.error_screenshot_path, full_page=True)
                    browser2.close()
        except Exception:
            pass

        return BotResult(
            ok=False,
            message=message,
            final_url=final_url,
            state_path=cfg.state_path,
            screenshot_path=cfg.screenshot_path,
            error_screenshot_path=cfg.error_screenshot_path,
        )
    finally:
        try:
            if browser is not None:
                browser.close()
        except Exception:
            pass
