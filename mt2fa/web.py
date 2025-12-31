from __future__ import annotations

import os
from pathlib import Path
from contextlib import asynccontextmanager
from secrets import compare_digest
from typing import Optional

from fastapi import Depends, FastAPI, Form, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import select

from mt2fa.crypto import Crypto
from mt2fa.db import make_engine, make_session_factory, session_scope
from mt2fa.migration import MigrationDecodeError, decode_migration_uri, pick_best_totp
from mt2fa.models import Account, Base, LoginRun, utcnow
from mt2fa.scheduler import LoginScheduler, SchedulerConfig
from mt2fa.settings import Settings, load_settings


security = HTTPBasic()
templates = Jinja2Templates(directory="templates")
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)


def _require_auth(request: Request, credentials: HTTPBasicCredentials = Depends(security)) -> str:
    settings: Settings = request.app.state.settings
    ok_user = compare_digest(credentials.username, settings.basic_auth_user)
    ok_pass = compare_digest(credentials.password, settings.basic_auth_password)
    if not (ok_user and ok_pass):
        raise HTTPException(status_code=401, headers={"WWW-Authenticate": "Basic"})
    return credentials.username


def _mask_secret(value: str) -> str:
    value = (value or "").strip()
    if len(value) <= 6:
        return "*" * len(value)
    return value[:2] + "*" * (len(value) - 4) + value[-2:]


def _to_bool(value: Optional[str]) -> bool:
    return (value or "").lower() in {"1", "true", "yes", "y", "on"}


def _to_int(value: Optional[str], default: int) -> int:
    if value is None or value.strip() == "":
        return default
    return int(value)


def _clean(value: Optional[str]) -> str:
    return (value or "").strip()


def _app_state_dirs(data_dir: str) -> tuple[str, str]:
    state_dir = os.path.join(data_dir, "state")
    shots_dir = os.path.join(data_dir, "screenshots")
    os.makedirs(state_dir, exist_ok=True)
    os.makedirs(shots_dir, exist_ok=True)
    return state_dir, shots_dir


def _safe_under(base_dir: str, rel_path: str) -> Path:
    base = Path(base_dir).resolve()
    candidate = (base / rel_path).resolve()
    if base not in candidate.parents and candidate != base:
        raise HTTPException(400, "Invalid path")
    return candidate


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = load_settings()
    engine = make_engine(settings.db_url)
    session_factory = make_session_factory(engine)
    Base.metadata.create_all(engine)
    _app_state_dirs(settings.data_dir)

    crypto = Crypto.from_master_key(settings.master_key)
    scheduler = LoginScheduler(
        session_factory=session_factory,
        crypto=crypto,
        cfg=SchedulerConfig(data_dir=settings.data_dir, poll_interval_seconds=settings.poll_interval_seconds),
    )
    scheduler.start()

    app.state.settings = settings
    app.state.crypto = crypto
    app.state.session_factory = session_factory
    app.state.scheduler = scheduler

    try:
        yield
    finally:
        scheduler.stop()


app = FastAPI(lifespan=lifespan)
app.mount("/static", StaticFiles(directory="static"), name="static")


@app.get("/", response_class=HTMLResponse)
def index(_: str = Depends(_require_auth)):
    return RedirectResponse(url="/accounts", status_code=303)


@app.get("/accounts", response_class=HTMLResponse)
def accounts_list(request: Request, _: str = Depends(_require_auth)):
    session_factory = request.app.state.session_factory
    with session_scope(session_factory) as session:
        accounts = session.execute(select(Account).order_by(Account.id.desc())).scalars().all()
    return templates.TemplateResponse(
        "accounts.html",
        {
            "request": request,
            "accounts": accounts,
        },
    )


@app.get("/accounts/new", response_class=HTMLResponse)
def accounts_new_form(request: Request, _: str = Depends(_require_auth)):
    preset = (request.query_params.get("preset") or "").strip().lower()
    draft = {
        "name": "",
        "login_url": "",
        "target_url": "",
        "username": "",
        "enabled": True,
        "interval_minutes": 24 * 60,
        "start_jitter_seconds": 0,
        "headless": True,
        "timezone_id": "Asia/Shanghai",
        "nav_timeout_ms": 60_000,
        "user_agent": DEFAULT_USER_AGENT,
        "username_selector": 'input[name="username"]',
        "password_selector": 'input[name="password"]',
        "submit_selector": 'button[type="submit"]',
        "otp_selector": "",
        "otp_submit_selector": "",
        "logged_in_selector": "",
    }
    if preset == "kp":
        draft.update(
            {
                "name": "kp.m-team.cc",
                "login_url": "https://kp.m-team.cc/login",
                "target_url": "https://kp.m-team.cc/index",
                "username_selector": "#username",
                "password_selector": "#password",
                "submit_selector": 'button[type="submit"]',
                "otp_selector": "",
                "logged_in_selector": "",
            }
        )
    return templates.TemplateResponse(
        "account_form.html",
        {
            "request": request,
            "mode": "new",
            "account": None,
            "draft": draft,
            "masked_password": "",
            "masked_totp": "",
            "default_ua": DEFAULT_USER_AGENT,
            "preset": preset,
            "error": "",
        },
    )


@app.post("/accounts/new")
def accounts_new(
    request: Request,
    _: str = Depends(_require_auth),
    name: str = Form(...),
    login_url: str = Form(...),
    target_url: str = Form(...),
    username: str = Form(...),
    password: str = Form(...),
    totp_secret: str = Form(""),
    totp_migration_url: str = Form(""),
    enabled: Optional[str] = Form(None),
    interval_minutes: Optional[str] = Form(None),
    start_jitter_seconds: Optional[str] = Form(None),
    headless: Optional[str] = Form(None),
    user_agent: Optional[str] = Form(None),
    timezone_id: Optional[str] = Form(None),
    nav_timeout_ms: Optional[str] = Form(None),
    username_selector: Optional[str] = Form(None),
    password_selector: Optional[str] = Form(None),
    submit_selector: Optional[str] = Form(None),
    otp_selector: Optional[str] = Form(None),
    otp_submit_selector: Optional[str] = Form(None),
    logged_in_selector: Optional[str] = Form(None),
):
    settings: Settings = request.app.state.settings
    crypto: Crypto = request.app.state.crypto
    session_factory = request.app.state.session_factory

    draft = {
        "name": _clean(name),
        "login_url": _clean(login_url),
        "target_url": _clean(target_url),
        "username": _clean(username),
        "enabled": _to_bool(enabled),
        "interval_minutes": _to_int(interval_minutes, 24 * 60),
        "start_jitter_seconds": _to_int(start_jitter_seconds, 0),
        "headless": _to_bool(headless),
        "timezone_id": _clean(timezone_id) or "Asia/Shanghai",
        "nav_timeout_ms": _to_int(nav_timeout_ms, 60_000),
        "user_agent": _clean(user_agent) or DEFAULT_USER_AGENT,
        "username_selector": _clean(username_selector) or 'input[name="username"]',
        "password_selector": _clean(password_selector) or 'input[name="password"]',
        "submit_selector": _clean(submit_selector) or 'button[type="submit"]',
        "otp_selector": _clean(otp_selector),
        "otp_submit_selector": _clean(otp_submit_selector),
        "logged_in_selector": _clean(logged_in_selector),
    }

    try:
        totp_secret_clean = _clean(totp_secret)
        totp_migration_url_clean = _clean(totp_migration_url)
        if not totp_secret_clean and totp_migration_url_clean:
            entries = decode_migration_uri(totp_migration_url_clean)
            picked = pick_best_totp(entries, username_hint=draft["username"])
            totp_secret_clean = picked.secret_base32
        if not totp_secret_clean:
            raise HTTPException(status_code=400, detail="TOTP secret is required (either provide secret or migration URL).")
    except (MigrationDecodeError, HTTPException, ValueError) as e:
        detail = getattr(e, "detail", None) or str(e)
        if isinstance(e, MigrationDecodeError):
            detail = f"Invalid migration URL: {e}"
        return templates.TemplateResponse(
            "account_form.html",
            {
                "request": request,
                "mode": "new",
                "account": None,
                "draft": draft,
                "masked_password": "",
                "masked_totp": "",
                "default_ua": DEFAULT_USER_AGENT,
                "preset": "",
                "error": detail,
            },
            status_code=400,
        )

    acc = Account(
        name=draft["name"],
        login_url=draft["login_url"],
        target_url=draft["target_url"],
        username=draft["username"],
        password_enc=crypto.encrypt_text(_clean(password)),
        totp_secret_enc=crypto.encrypt_text(totp_secret_clean),
        enabled=bool(draft["enabled"]),
        interval_minutes=int(draft["interval_minutes"]),
        start_jitter_seconds=int(draft["start_jitter_seconds"]),
        headless=bool(draft["headless"]),
        user_agent=draft["user_agent"],
        timezone_id=draft["timezone_id"],
        nav_timeout_ms=int(draft["nav_timeout_ms"]),
        username_selector=draft["username_selector"],
        password_selector=draft["password_selector"],
        submit_selector=draft["submit_selector"],
        otp_selector=draft["otp_selector"],
        otp_submit_selector=draft["otp_submit_selector"],
        logged_in_selector=draft["logged_in_selector"],
        next_run_at=utcnow(),
    )

    os.makedirs(settings.data_dir, exist_ok=True)
    with session_scope(session_factory) as session:
        session.add(acc)

    return RedirectResponse(url="/accounts", status_code=303)


@app.get("/accounts/{account_id}", response_class=HTMLResponse)
def accounts_edit_form(request: Request, account_id: int, _: str = Depends(_require_auth)):
    crypto: Crypto = request.app.state.crypto
    session_factory = request.app.state.session_factory
    with session_scope(session_factory) as session:
        acc = session.get(Account, account_id)
        if acc is None:
            raise HTTPException(404)
        masked_password = _mask_secret(crypto.decrypt_text(acc.password_enc))
        masked_totp = _mask_secret(crypto.decrypt_text(acc.totp_secret_enc))

    return templates.TemplateResponse(
        "account_form.html",
        {
            "request": request,
            "mode": "edit",
            "account": acc,
            "draft": None,
            "masked_password": masked_password,
            "masked_totp": masked_totp,
            "default_ua": DEFAULT_USER_AGENT,
            "error": "",
        },
    )


@app.post("/accounts/{account_id}")
def accounts_edit(
    request: Request,
    account_id: int,
    _: str = Depends(_require_auth),
    name: str = Form(...),
    login_url: str = Form(...),
    target_url: str = Form(...),
    username: str = Form(...),
    password: Optional[str] = Form(None),
    totp_secret: Optional[str] = Form(None),
    totp_migration_url: Optional[str] = Form(None),
    enabled: Optional[str] = Form(None),
    interval_minutes: Optional[str] = Form(None),
    start_jitter_seconds: Optional[str] = Form(None),
    headless: Optional[str] = Form(None),
    user_agent: Optional[str] = Form(None),
    timezone_id: Optional[str] = Form(None),
    nav_timeout_ms: Optional[str] = Form(None),
    username_selector: Optional[str] = Form(None),
    password_selector: Optional[str] = Form(None),
    submit_selector: Optional[str] = Form(None),
    otp_selector: Optional[str] = Form(None),
    otp_submit_selector: Optional[str] = Form(None),
    logged_in_selector: Optional[str] = Form(None),
):
    crypto: Crypto = request.app.state.crypto
    session_factory = request.app.state.session_factory
    draft = {
        "name": _clean(name),
        "login_url": _clean(login_url),
        "target_url": _clean(target_url),
        "username": _clean(username),
        "enabled": _to_bool(enabled),
        "interval_minutes": _to_int(interval_minutes, 24 * 60),
        "start_jitter_seconds": _to_int(start_jitter_seconds, 0),
        "headless": _to_bool(headless),
        "timezone_id": _clean(timezone_id) or "Asia/Shanghai",
        "nav_timeout_ms": _to_int(nav_timeout_ms, 60_000),
        "user_agent": _clean(user_agent) or DEFAULT_USER_AGENT,
        "username_selector": _clean(username_selector),
        "password_selector": _clean(password_selector),
        "submit_selector": _clean(submit_selector),
        "otp_selector": _clean(otp_selector or ""),
        "otp_submit_selector": _clean(otp_submit_selector or ""),
        "logged_in_selector": _clean(logged_in_selector or ""),
    }

    try:
        with session_scope(session_factory) as session:
            acc = session.get(Account, account_id)
            if acc is None:
                raise HTTPException(404)

            acc.name = draft["name"]
            acc.login_url = draft["login_url"]
            acc.target_url = draft["target_url"]
            acc.username = draft["username"]
            acc.enabled = bool(draft["enabled"])
            acc.interval_minutes = _to_int(interval_minutes, acc.interval_minutes)
            acc.start_jitter_seconds = _to_int(start_jitter_seconds, acc.start_jitter_seconds)
            acc.headless = bool(draft["headless"])
            if user_agent is not None and draft["user_agent"]:
                acc.user_agent = draft["user_agent"]
            if timezone_id is not None and draft["timezone_id"]:
                acc.timezone_id = draft["timezone_id"]
            if nav_timeout_ms is not None and _clean(nav_timeout_ms):
                acc.nav_timeout_ms = _to_int(nav_timeout_ms, acc.nav_timeout_ms)

            if draft["username_selector"]:
                acc.username_selector = draft["username_selector"]
            if draft["password_selector"]:
                acc.password_selector = draft["password_selector"]
            if draft["submit_selector"]:
                acc.submit_selector = draft["submit_selector"]
            if otp_selector is not None:
                acc.otp_selector = draft["otp_selector"]
            if otp_submit_selector is not None:
                acc.otp_submit_selector = draft["otp_submit_selector"]
            if logged_in_selector is not None:
                acc.logged_in_selector = draft["logged_in_selector"]

            if password is not None and _clean(password):
                acc.password_enc = crypto.encrypt_text(_clean(password))
            if totp_secret is not None and _clean(totp_secret):
                acc.totp_secret_enc = crypto.encrypt_text(_clean(totp_secret))
            elif totp_migration_url is not None and _clean(totp_migration_url):
                entries = decode_migration_uri(_clean(totp_migration_url))
                picked = pick_best_totp(entries, username_hint=acc.username)
                acc.totp_secret_enc = crypto.encrypt_text(picked.secret_base32)

            if acc.next_run_at is None and acc.enabled:
                acc.next_run_at = utcnow()
    except (MigrationDecodeError, HTTPException, ValueError) as e:
        detail = getattr(e, "detail", None) or str(e)
        if isinstance(e, MigrationDecodeError):
            detail = f"Invalid migration URL: {e}"
        with session_scope(session_factory) as session:
            acc = session.get(Account, account_id)
            if acc is None:
                raise HTTPException(404)
            masked_password = _mask_secret(crypto.decrypt_text(acc.password_enc))
            masked_totp = _mask_secret(crypto.decrypt_text(acc.totp_secret_enc))
        return templates.TemplateResponse(
            "account_form.html",
            {
                "request": request,
                "mode": "edit",
                "account": acc,
                "draft": None,
                "masked_password": masked_password,
                "masked_totp": masked_totp,
                "default_ua": DEFAULT_USER_AGENT,
                "error": detail,
            },
            status_code=400,
        )

    return RedirectResponse(url="/accounts", status_code=303)


@app.post("/accounts/{account_id}/delete")
def accounts_delete(request: Request, account_id: int, _: str = Depends(_require_auth)):
    session_factory = request.app.state.session_factory
    with session_scope(session_factory) as session:
        acc = session.get(Account, account_id)
        if acc is None:
            raise HTTPException(404)
        session.delete(acc)
    return RedirectResponse(url="/accounts", status_code=303)


@app.post("/accounts/{account_id}/run")
def accounts_run_now(request: Request, account_id: int, _: str = Depends(_require_auth)):
    scheduler: LoginScheduler = request.app.state.scheduler
    started = scheduler.trigger_account(account_id)
    return RedirectResponse(url=f"/accounts/{account_id}/runs?started={'1' if started else '0'}", status_code=303)


@app.get("/accounts/{account_id}/runs", response_class=HTMLResponse)
def accounts_runs(request: Request, account_id: int, started: str = "0", _: str = Depends(_require_auth)):
    session_factory = request.app.state.session_factory
    with session_scope(session_factory) as session:
        acc = session.get(Account, account_id)
        if acc is None:
            raise HTTPException(404)
        runs = (
            session.execute(select(LoginRun).where(LoginRun.account_id == account_id).order_by(LoginRun.id.desc()).limit(50))
            .scalars()
            .all()
        )
    return templates.TemplateResponse(
        "runs.html",
        {"request": request, "account": acc, "runs": runs, "started": started},
    )


@app.get("/shots/{rel_path:path}")
def shots(request: Request, rel_path: str, _: str = Depends(_require_auth)):
    settings: Settings = request.app.state.settings
    # Only allow serving from screenshots/ subtree
    rel_path = rel_path.strip().lstrip("/")
    if not rel_path.startswith("screenshots/"):
        raise HTTPException(403, "Forbidden")
    path = _safe_under(settings.data_dir, rel_path)
    if not path.exists():
        raise HTTPException(404)
    return FileResponse(path)
