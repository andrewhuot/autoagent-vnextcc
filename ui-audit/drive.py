#!/usr/bin/env python3
"""Vision-loop harness: persistent Chromium driven via short CLI subcommands.

Launches a single browser + context + page via Playwright (chromium) on Xvfb and
exposes a simple command protocol. State (PID, CDP endpoint, last page URL) is
stored in ui-audit/session.json so each Bash invocation re-attaches to the same
browser instead of launching a new one.

Subcommands:
  start [url]                  -- launch browser (if not running), open url
  stop                         -- close browser, delete session
  nav <url>                    -- navigate current page
  snap [label]                 -- full-page screenshot + dumps
  click <locator>              -- click by text= / role= / css selector (auto-detect)
  type <locator> <value>       -- fill() into locator
  press <key>                  -- keyboard press (e.g. Enter)
  wait <locator> [timeout_ms]  -- wait for locator visible
  waittext <text> [timeout_ms] -- wait for text to appear
  eval <js>                    -- page.evaluate, prints result
  console [tail]               -- dump last N console events (default 40)
  net [tail]                   -- dump last N network events (default 40)
  status                       -- print URL + title
  accessibility [label]        -- save aria snapshot to screenshots dir

Locator syntax (for click/type/wait):
  text=Foo           -- getByText('Foo', exact=False)
  role=button:Label  -- getByRole('button', name='Label')
  testid=foo         -- getByTestId('foo')
  <anything else>    -- CSS selector, via page.locator()
"""
from __future__ import annotations

import json
import os
import re
import signal
import subprocess
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright, Page, Browser, BrowserContext, TimeoutError as PwTimeout

ROOT = Path(__file__).resolve().parent
SESSION = ROOT / "session.json"
SHOTS = ROOT / "screenshots"
EVENTS = ROOT / "events.jsonl"
DRIVER_LOG = ROOT / "driver.log"
XVFB_DISPLAY = ":99"
XVFB_RES = "1440x900x24"

SHOTS.mkdir(parents=True, exist_ok=True)


def _log(msg: str) -> None:
    ts = time.strftime("%H:%M:%S")
    with DRIVER_LOG.open("a") as f:
        f.write(f"[{ts}] {msg}\n")


def _ensure_xvfb() -> None:
    if Path(f"/tmp/.X{XVFB_DISPLAY[1:]}-lock").exists():
        return
    # Launch Xvfb detached
    subprocess.Popen(
        ["Xvfb", XVFB_DISPLAY, "-screen", "0", XVFB_RES, "-nolisten", "tcp"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    # wait for socket to appear
    for _ in range(40):
        if Path(f"/tmp/.X{XVFB_DISPLAY[1:]}-lock").exists():
            break
        time.sleep(0.05)
    time.sleep(0.2)


def _save_session(endpoint: str, pid: int) -> None:
    SESSION.write_text(json.dumps({"endpoint": endpoint, "pid": pid, "started": time.time()}))


def _load_session() -> dict | None:
    if not SESSION.exists():
        return None
    try:
        return json.loads(SESSION.read_text())
    except Exception:
        return None


def _attach(pw, sess: dict) -> tuple[Browser, BrowserContext, Page]:
    browser = pw.chromium.connect_over_cdp(sess["endpoint"])
    ctx = browser.contexts[0] if browser.contexts else browser.new_context(viewport={"width": 1440, "height": 900})
    page = ctx.pages[0] if ctx.pages else ctx.new_page()
    return browser, ctx, page


def _parse_locator(page: Page, spec: str):
    if spec.startswith("text="):
        return page.get_by_text(spec[5:], exact=False).first
    if spec.startswith("role="):
        body = spec[5:]
        if ":" in body:
            role, name = body.split(":", 1)
            return page.get_by_role(role.strip(), name=name.strip()).first
        return page.get_by_role(body).first
    if spec.startswith("testid="):
        return page.get_by_test_id(spec[7:]).first
    return page.locator(spec).first


def _record_events(ctx: BrowserContext, page: Page) -> None:
    """Install console + network listeners (idempotent)."""
    if getattr(ctx, "_al_recorded", False):
        return
    ctx._al_recorded = True  # type: ignore[attr-defined]

    def on_console(msg):
        try:
            entry = {
                "ts": time.time(),
                "type": "console",
                "level": msg.type,
                "text": msg.text,
                "url": page.url,
            }
            with EVENTS.open("a") as f:
                f.write(json.dumps(entry) + "\n")
        except Exception:
            pass

    def on_pageerror(err):
        entry = {"ts": time.time(), "type": "pageerror", "text": str(err), "url": page.url}
        with EVENTS.open("a") as f:
            f.write(json.dumps(entry) + "\n")

    def on_response(resp):
        try:
            if resp.status >= 400:
                entry = {
                    "ts": time.time(),
                    "type": "netfail",
                    "status": resp.status,
                    "url": resp.url,
                    "method": resp.request.method,
                }
                with EVENTS.open("a") as f:
                    f.write(json.dumps(entry) + "\n")
        except Exception:
            pass

    page.on("console", on_console)
    page.on("pageerror", on_pageerror)
    page.on("response", on_response)


def _snap(page: Page, label: str) -> Path:
    safe = re.sub(r"[^a-z0-9._-]+", "-", label.lower()).strip("-") or "shot"
    ts = time.strftime("%H%M%S")
    path = SHOTS / f"{ts}-{safe}.png"
    page.screenshot(path=str(path), full_page=True)
    return path


def _tail_events(kind: str, n: int) -> list[dict]:
    if not EVENTS.exists():
        return []
    out = []
    with EVENTS.open() as f:
        for line in f:
            try:
                obj = json.loads(line)
            except Exception:
                continue
            if kind == "console" and obj.get("type") == "console":
                out.append(obj)
            elif kind == "console" and obj.get("type") == "pageerror":
                out.append(obj)
            elif kind == "net" and obj.get("type") == "netfail":
                out.append(obj)
    return out[-n:]


def cmd_start(args: list[str]) -> int:
    _ensure_xvfb()
    sess = _load_session()
    if sess:
        # verify it's responsive
        try:
            with sync_playwright() as pw:
                browser, ctx, page = _attach(pw, sess)
                url = args[0] if args else page.url
                if url and url != "about:blank":
                    page.goto(url, wait_until="domcontentloaded", timeout=30000)
                _record_events(ctx, page)
                shot = _snap(page, f"start-{url or 'current'}")
                print(f"OK reattached url={page.url} shot={shot}")
                return 0
        except Exception as e:
            _log(f"reattach failed: {e}; starting fresh")
            SESSION.unlink(missing_ok=True)

    # Launch new browser via a helper that keeps browser alive in background.
    helper = ROOT / "_browser_holder.py"
    helper.write_text(_HELPER_SRC)
    env = {**os.environ, "DISPLAY": XVFB_DISPLAY}
    proc = subprocess.Popen(
        [sys.executable, str(helper)],
        stdout=open(ROOT / "holder.log", "a"),
        stderr=subprocess.STDOUT,
        env=env,
        start_new_session=True,
    )
    # wait for session.json to be written
    for _ in range(100):
        if SESSION.exists():
            break
        time.sleep(0.1)
    sess = _load_session()
    if not sess:
        print("ERROR: browser holder did not start (see ui-audit/holder.log)")
        return 1
    with sync_playwright() as pw:
        browser, ctx, page = _attach(pw, sess)
        _record_events(ctx, page)
        url = args[0] if args else None
        if url:
            page.goto(url, wait_until="domcontentloaded", timeout=30000)
        shot = _snap(page, f"start-{url or 'blank'}")
        print(f"OK started pid={proc.pid} endpoint={sess['endpoint']} url={page.url} shot={shot}")
    return 0


def cmd_stop(_args: list[str]) -> int:
    sess = _load_session()
    if not sess:
        print("no session")
        return 0
    try:
        os.killpg(os.getpgid(sess["pid"]), signal.SIGTERM)
    except Exception:
        pass
    SESSION.unlink(missing_ok=True)
    print("OK stopped")
    return 0


def _with_page(fn):
    def wrapper(args: list[str]) -> int:
        sess = _load_session()
        if not sess:
            print("ERROR: no session. run start first.")
            return 2
        with sync_playwright() as pw:
            browser, ctx, page = _attach(pw, sess)
            _record_events(ctx, page)
            return fn(page, ctx, args)
    return wrapper


@_with_page
def cmd_nav(page: Page, _ctx, args: list[str]) -> int:
    if not args:
        print("ERROR: nav <url>")
        return 2
    url = args[0]
    page.goto(url, wait_until="domcontentloaded", timeout=45000)
    # let react render
    try:
        page.wait_for_load_state("networkidle", timeout=8000)
    except PwTimeout:
        pass
    shot = _snap(page, f"nav-{url.replace('http://','').replace('/','_')[:40]}")
    print(f"OK url={page.url} title={page.title()[:80]!r} shot={shot}")
    return 0


@_with_page
def cmd_snap(page: Page, _ctx, args: list[str]) -> int:
    label = args[0] if args else "snap"
    shot = _snap(page, label)
    print(f"OK shot={shot} url={page.url}")
    return 0


@_with_page
def cmd_click(page: Page, _ctx, args: list[str]) -> int:
    if not args:
        print("ERROR: click <locator>")
        return 2
    spec = " ".join(args)
    loc = _parse_locator(page, spec)
    try:
        loc.wait_for(state="visible", timeout=5000)
    except PwTimeout:
        pass
    try:
        loc.click(timeout=8000)
    except Exception as e:
        print(f"ERROR click failed: {e}")
        return 1
    try:
        page.wait_for_load_state("networkidle", timeout=6000)
    except PwTimeout:
        pass
    shot = _snap(page, f"click-{spec[:40]}")
    print(f"OK clicked {spec!r} shot={shot}")
    return 0


@_with_page
def cmd_type(page: Page, _ctx, args: list[str]) -> int:
    if len(args) < 2:
        print("ERROR: type <locator> <value>")
        return 2
    spec = args[0]
    value = " ".join(args[1:])
    loc = _parse_locator(page, spec)
    try:
        loc.wait_for(state="visible", timeout=5000)
        loc.fill(value, timeout=8000)
    except Exception as e:
        print(f"ERROR type failed: {e}")
        return 1
    shot = _snap(page, f"type-{spec[:40]}")
    print(f"OK typed into {spec!r} (len={len(value)}) shot={shot}")
    return 0


@_with_page
def cmd_press(page: Page, _ctx, args: list[str]) -> int:
    if not args:
        print("ERROR: press <key>")
        return 2
    key = args[0]
    try:
        page.keyboard.press(key)
    except Exception as e:
        print(f"ERROR press failed: {e}")
        return 1
    try:
        page.wait_for_load_state("networkidle", timeout=4000)
    except PwTimeout:
        pass
    shot = _snap(page, f"press-{key}")
    print(f"OK pressed {key} shot={shot}")
    return 0


@_with_page
def cmd_wait(page: Page, _ctx, args: list[str]) -> int:
    if not args:
        print("ERROR: wait <locator> [timeout_ms]")
        return 2
    spec = args[0]
    timeout = int(args[1]) if len(args) > 1 else 15000
    loc = _parse_locator(page, spec)
    try:
        loc.wait_for(state="visible", timeout=timeout)
    except PwTimeout:
        print(f"TIMEOUT waiting for {spec!r}")
        _snap(page, f"wait-timeout-{spec[:30]}")
        return 1
    shot = _snap(page, f"wait-{spec[:40]}")
    print(f"OK saw {spec!r} shot={shot}")
    return 0


@_with_page
def cmd_waittext(page: Page, _ctx, args: list[str]) -> int:
    if not args:
        print("ERROR: waittext <text> [timeout_ms]")
        return 2
    text = args[0]
    timeout = int(args[1]) if len(args) > 1 else 15000
    try:
        page.get_by_text(text, exact=False).first.wait_for(state="visible", timeout=timeout)
    except PwTimeout:
        print(f"TIMEOUT waiting for text {text!r}")
        _snap(page, f"waittext-timeout-{text[:30]}")
        return 1
    shot = _snap(page, f"waittext-{text[:40]}")
    print(f"OK saw text {text!r} shot={shot}")
    return 0


@_with_page
def cmd_eval(page: Page, _ctx, args: list[str]) -> int:
    if not args:
        print("ERROR: eval <js>")
        return 2
    js = " ".join(args)
    try:
        res = page.evaluate(js)
    except Exception as e:
        print(f"ERROR eval failed: {e}")
        return 1
    print(json.dumps(res, default=str)[:2000])
    return 0


@_with_page
def cmd_status(page: Page, _ctx, _args: list[str]) -> int:
    print(json.dumps({"url": page.url, "title": page.title()}))
    return 0


@_with_page
def cmd_accessibility(page: Page, _ctx, args: list[str]) -> int:
    label = args[0] if args else "a11y"
    tree = page.accessibility.snapshot()
    path = SHOTS / f"{time.strftime('%H%M%S')}-{label}-a11y.json"
    path.write_text(json.dumps(tree, indent=2, default=str))
    print(f"OK a11y saved to {path}")
    return 0


def cmd_console(args: list[str]) -> int:
    n = int(args[0]) if args else 40
    for e in _tail_events("console", n):
        lvl = e.get("level", e.get("type"))
        print(f"[{lvl}] {e.get('text','')}  @ {e.get('url','')}")
    return 0


def cmd_net(args: list[str]) -> int:
    n = int(args[0]) if args else 40
    for e in _tail_events("net", n):
        print(f"[{e.get('status')}] {e.get('method','')} {e.get('url','')}")
    return 0


_HELPER_SRC = '''
import json, os, sys, time, signal
from pathlib import Path
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent
SESSION = ROOT / "session.json"

def main():
    with sync_playwright() as pw:
        browser = pw.chromium.launch(
            headless=False,
            args=[
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--disable-blink-features=AutomationControlled",
                "--remote-debugging-port=9222",
                "--remote-debugging-address=127.0.0.1",
            ],
        )
        ctx = browser.new_context(viewport={"width": 1440, "height": 900})
        page = ctx.new_page()
        page.goto("about:blank")
        time.sleep(0.3)
        # discover ws endpoint
        endpoint = None
        try:
            import urllib.request
            meta = json.loads(urllib.request.urlopen("http://127.0.0.1:9222/json/version").read())
            endpoint = meta.get("webSocketDebuggerUrl")
        except Exception:
            endpoint = None
        SESSION.write_text(json.dumps({"endpoint": endpoint or "", "pid": os.getpid(), "started": time.time()}))
        # keep alive until killed
        def _term(*_):
            try: browser.close()
            finally: os._exit(0)
        signal.signal(signal.SIGTERM, _term)
        signal.signal(signal.SIGINT, _term)
        while True:
            time.sleep(3600)

if __name__ == "__main__":
    main()
'''


COMMANDS = {
    "start": cmd_start,
    "stop": cmd_stop,
    "nav": cmd_nav,
    "snap": cmd_snap,
    "click": cmd_click,
    "type": cmd_type,
    "press": cmd_press,
    "wait": cmd_wait,
    "waittext": cmd_waittext,
    "eval": cmd_eval,
    "status": cmd_status,
    "accessibility": cmd_accessibility,
    "console": cmd_console,
    "net": cmd_net,
}


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    cmd = sys.argv[1]
    args = sys.argv[2:]
    fn = COMMANDS.get(cmd)
    if not fn:
        print(f"unknown command: {cmd}")
        return 2
    return fn(args)


if __name__ == "__main__":
    sys.exit(main())
