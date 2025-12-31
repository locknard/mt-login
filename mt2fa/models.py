from __future__ import annotations

import datetime as dt

from sqlalchemy import Boolean, DateTime, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def utcnow() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


class Base(DeclarativeBase):
    pass


class Account(Base):
    __tablename__ = "accounts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)

    login_url: Mapped[str] = mapped_column(String(1000), nullable=False)
    target_url: Mapped[str] = mapped_column(String(1000), nullable=False)

    username: Mapped[str] = mapped_column(String(200), nullable=False)
    password_enc: Mapped[str] = mapped_column(Text, nullable=False)
    totp_secret_enc: Mapped[str] = mapped_column(Text, nullable=False)

    username_selector: Mapped[str] = mapped_column(String(500), nullable=False, default='input[name="username"]')
    password_selector: Mapped[str] = mapped_column(String(500), nullable=False, default='input[name="password"]')
    submit_selector: Mapped[str] = mapped_column(String(500), nullable=False, default='button[type="submit"]')
    otp_selector: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    otp_submit_selector: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    logged_in_selector: Mapped[str] = mapped_column(String(500), nullable=False, default="")

    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    interval_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=24 * 60)
    start_jitter_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    headless: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    user_agent: Mapped[str] = mapped_column(
        String(500),
        nullable=False,
        default="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    )
    timezone_id: Mapped[str] = mapped_column(String(100), nullable=False, default="Asia/Shanghai")
    nav_timeout_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=60_000)

    last_run_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    next_run_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_status: Mapped[str] = mapped_column(String(50), nullable=False, default="never")
    last_message: Mapped[str] = mapped_column(Text, nullable=False, default="")

    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    updated_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow)


class LoginRun(Base):
    __tablename__ = "login_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    account_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)

    started_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    finished_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    ok: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    message: Mapped[str] = mapped_column(Text, nullable=False, default="")
    final_url: Mapped[str] = mapped_column(String(1500), nullable=False, default="")

    state_path: Mapped[str] = mapped_column(String(1000), nullable=False, default="")
    screenshot_path: Mapped[str] = mapped_column(String(1000), nullable=False, default="")
    error_screenshot_path: Mapped[str] = mapped_column(String(1000), nullable=False, default="")
