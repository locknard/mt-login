from __future__ import annotations

import datetime as dt
import os
import threading
import time
from dataclasses import dataclass
from typing import Dict, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from mt2fa.bot import BotConfig, run_login
from mt2fa.crypto import Crypto
from mt2fa.models import Account, LoginRun, utcnow


def _as_opt(value: str) -> Optional[str]:
    value = (value or "").strip()
    return value or None


def _ensure_dir(path: str) -> None:
    os.makedirs(path, exist_ok=True)


def _compute_next_run(now: dt.datetime, interval_minutes: int) -> dt.datetime:
    interval_minutes = max(1, int(interval_minutes))
    return now + dt.timedelta(minutes=interval_minutes)


@dataclass(frozen=True)
class SchedulerConfig:
    data_dir: str
    poll_interval_seconds: int = 60


class LoginScheduler:
    def __init__(self, session_factory: sessionmaker[Session], crypto: Crypto, cfg: SchedulerConfig):
        self._session_factory = session_factory
        self._crypto = crypto
        self._cfg = cfg
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self._locks: Dict[int, threading.Lock] = {}

        _ensure_dir(os.path.join(cfg.data_dir, "state"))
        _ensure_dir(os.path.join(cfg.data_dir, "screenshots"))

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run_loop, name="mt2fa-scheduler", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=5)

    def trigger_account(self, account_id: int) -> bool:
        lock = self._locks.setdefault(account_id, threading.Lock())
        if not lock.acquire(blocking=False):
            return False

        def _bg() -> None:
            try:
                self._run_one(account_id, triggered_by="manual")
            finally:
                lock.release()

        threading.Thread(target=_bg, name=f"mt2fa-run-{account_id}", daemon=True).start()
        return True

    def _run_loop(self) -> None:
        while not self._stop.is_set():
            try:
                self._run_due_once()
            except Exception:
                pass
            self._stop.wait(self._cfg.poll_interval_seconds)

    def _run_due_once(self) -> None:
        now = utcnow()
        with self._session_factory() as session:
            due_accounts = session.execute(
                select(Account).where(
                    Account.enabled.is_(True),
                    Account.next_run_at.is_not(None),
                    Account.next_run_at <= now,
                )
            ).scalars().all()
            due_ids = [a.id for a in due_accounts]

            # Initialize next_run_at for newly created accounts
            uninitialized = session.execute(
                select(Account).where(Account.enabled.is_(True), Account.next_run_at.is_(None))
            ).scalars().all()
            for acc in uninitialized:
                acc.next_run_at = now
            session.commit()

        for account_id in due_ids:
            lock = self._locks.setdefault(account_id, threading.Lock())
            if not lock.acquire(blocking=False):
                continue
            try:
                self._run_one(account_id, triggered_by="schedule")
            finally:
                lock.release()

    def _run_one(self, account_id: int, triggered_by: str) -> None:
        now = utcnow()
        ts = now.strftime("%Y%m%dT%H%M%SZ")

        state_rel = f"state/{account_id}/state.json"
        screenshot_rel = f"screenshots/{account_id}/{ts}.png"
        error_screenshot_rel = f"screenshots/{account_id}/{ts}.error.png"

        state_abs = os.path.join(self._cfg.data_dir, state_rel)
        screenshot_abs = os.path.join(self._cfg.data_dir, screenshot_rel)
        error_screenshot_abs = os.path.join(self._cfg.data_dir, error_screenshot_rel)

        _ensure_dir(os.path.dirname(state_abs))
        _ensure_dir(os.path.dirname(screenshot_abs))

        with self._session_factory() as session:
            acc = session.get(Account, account_id)
            if acc is None:
                return
            if not acc.enabled:
                return

            run = LoginRun(
                account_id=acc.id,
                started_at=now,
                ok=False,
                message=f"running ({triggered_by})",
                state_path=state_rel,
                screenshot_path=screenshot_rel,
                error_screenshot_path=error_screenshot_rel,
            )
            session.add(run)
            acc.last_status = "running"
            acc.last_message = f"running ({triggered_by})"
            session.commit()
            run_id = run.id

        with self._session_factory() as session:
            acc = session.get(Account, account_id)
            if acc is None:
                return
            password = self._crypto.decrypt_text(acc.password_enc)
            totp_secret = self._crypto.decrypt_text(acc.totp_secret_enc)

            result = run_login(
                BotConfig(
                    username=acc.username,
                    password=password,
                    totp_secret=totp_secret,
                    login_url=acc.login_url,
                    target_url=acc.target_url,
                    username_selector=acc.username_selector,
                    password_selector=acc.password_selector,
                    submit_selector=acc.submit_selector,
                    otp_selector=_as_opt(acc.otp_selector),
                    otp_submit_selector=_as_opt(acc.otp_submit_selector),
                    logged_in_selector=_as_opt(acc.logged_in_selector),
                    state_path=state_abs,
                    screenshot_path=screenshot_abs,
                    error_screenshot_path=error_screenshot_abs,
                    user_agent=acc.user_agent,
                    headless=bool(acc.headless),
                    start_jitter_seconds=int(acc.start_jitter_seconds),
                    nav_timeout_ms=int(acc.nav_timeout_ms),
                    timezone_id=acc.timezone_id,
                )
            )

            run = session.get(LoginRun, run_id)
            if run is None:
                return
            if os.path.exists(state_abs):
                run.state_path = state_rel
            else:
                run.state_path = ""

            if os.path.exists(screenshot_abs):
                run.screenshot_path = screenshot_rel
            else:
                run.screenshot_path = ""

            if (not result.ok) and os.path.exists(error_screenshot_abs):
                run.error_screenshot_path = error_screenshot_rel
            else:
                run.error_screenshot_path = ""

            run.ok = bool(result.ok)
            run.message = result.message
            run.final_url = result.final_url
            run.finished_at = utcnow()

            acc.last_run_at = now
            acc.last_status = "ok" if result.ok else "error"
            acc.last_message = result.message
            acc.next_run_at = _compute_next_run(now, int(acc.interval_minutes))

            session.commit()
