from __future__ import annotations

import argparse
import json
import os
from dataclasses import dataclass, asdict
from typing import Any, Optional

from playwright.sync_api import sync_playwright


def _ensure_parent_dir(path: str) -> None:
    parent = os.path.dirname(os.path.abspath(path))
    if parent:
        os.makedirs(parent, exist_ok=True)


def _pick_selector(tag: str, attrs: dict[str, Optional[str]]) -> str:
    el_id = (attrs.get("id") or "").strip()
    if el_id:
        return f"#{el_id}"
    name = (attrs.get("name") or "").strip()
    if name:
        return f'{tag}[name="{name}"]'
    aria = (attrs.get("aria-label") or "").strip()
    if aria:
        # best-effort; may match multiple
        return f'{tag}[aria-label="{aria}"]'
    placeholder = (attrs.get("placeholder") or "").strip()
    if placeholder:
        return f'{tag}[placeholder="{placeholder}"]'
    return tag


@dataclass(frozen=True)
class ProbedElement:
    tag: str
    selector: str
    attrs: dict[str, Optional[str]]


@dataclass(frozen=True)
class ProbeReport:
    url: str
    final_url: str
    title: str
    forms: list[dict[str, Any]]
    inputs: list[ProbedElement]
    buttons: list[ProbedElement]
    suggested: dict[str, str]


def probe(url: str, *, user_agent: str, headless: bool, timeout_ms: int) -> ProbeReport:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless, args=["--no-sandbox"])
        context = browser.new_context(
            user_agent=user_agent,
            locale="zh-CN",
            viewport={"width": 1280, "height": 800},
        )
        page = context.new_page()
        page.set_default_navigation_timeout(timeout_ms)
        page.set_default_timeout(timeout_ms)

        page.goto(url, wait_until="domcontentloaded")
        page.wait_for_load_state("networkidle")

        title = page.title()
        final_url = page.url

        forms: list[dict[str, Any]] = []
        for idx, form in enumerate(page.query_selector_all("form")):
            attrs = {
                "id": form.get_attribute("id"),
                "name": form.get_attribute("name"),
                "action": form.get_attribute("action"),
                "method": form.get_attribute("method"),
            }
            forms.append({"index": idx, "attrs": attrs})

        inputs: list[ProbedElement] = []
        for el in page.query_selector_all("input"):
            attrs = {
                "id": el.get_attribute("id"),
                "name": el.get_attribute("name"),
                "type": el.get_attribute("type"),
                "placeholder": el.get_attribute("placeholder"),
                "autocomplete": el.get_attribute("autocomplete"),
                "aria-label": el.get_attribute("aria-label"),
                "maxlength": el.get_attribute("maxlength"),
            }
            inputs.append(ProbedElement(tag="input", selector=_pick_selector("input", attrs), attrs=attrs))

        buttons: list[ProbedElement] = []
        for el in page.query_selector_all("button"):
            attrs = {
                "id": el.get_attribute("id"),
                "name": el.get_attribute("name"),
                "type": el.get_attribute("type"),
                "aria-label": el.get_attribute("aria-label"),
            }
            buttons.append(ProbedElement(tag="button", selector=_pick_selector("button", attrs), attrs=attrs))

        suggested: dict[str, str] = {}

        # Suggest login form elements by heuristics
        password_input = None
        for el in inputs:
            if (el.attrs.get("type") or "").lower() == "password":
                password_input = el
                break

        if password_input is not None:
            suggested["password_selector"] = password_input.selector

        username_input = None
        for el in inputs:
            t = (el.attrs.get("type") or "").lower()
            ac = (el.attrs.get("autocomplete") or "").lower()
            name = (el.attrs.get("name") or "").lower()
            if t in {"text", "email"} or t == "":
                if "user" in ac or "email" in ac or "user" in name or "email" in name:
                    username_input = el
                    break
        if username_input is None:
            for el in inputs:
                t = (el.attrs.get("type") or "").lower()
                if t in {"text", "email"}:
                    username_input = el
                    break
        if username_input is not None:
            suggested["username_selector"] = username_input.selector

        submit_button = None
        for el in buttons:
            if (el.attrs.get("type") or "").lower() == "submit":
                submit_button = el
                break
        if submit_button is not None:
            suggested["submit_selector"] = submit_button.selector
        else:
            # Fallback to common selector
            suggested["submit_selector"] = 'button[type="submit"]'

        browser.close()

    return ProbeReport(
        url=url,
        final_url=final_url,
        title=title,
        forms=forms,
        inputs=inputs,
        buttons=buttons,
        suggested=suggested,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Probe a website page to suggest CSS selectors.")
    parser.add_argument("--url", required=True)
    parser.add_argument("--out", default="data/probe")
    parser.add_argument("--headless", default="true")
    parser.add_argument("--timeout-ms", default="60000")
    parser.add_argument(
        "--user-agent",
        default="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    )
    args = parser.parse_args()

    headless = str(args.headless).lower() in {"1", "true", "yes", "y", "on"}
    timeout_ms = int(args.timeout_ms)
    out_base = args.out

    report = probe(args.url, user_agent=args.user_agent, headless=headless, timeout_ms=timeout_ms)

    report_path = f"{out_base}.json"
    _ensure_parent_dir(report_path)
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(
            {
                **asdict(report),
                "inputs": [asdict(x) for x in report.inputs],
                "buttons": [asdict(x) for x in report.buttons],
            },
            f,
            ensure_ascii=False,
            indent=2,
        )

    print(f"Wrote: {report_path}")
    print(f"Final URL: {report.final_url}")
    print(f"Title: {report.title}")
    print("Suggested selectors:")
    for k, v in report.suggested.items():
        print(f"  {k} = {v}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

