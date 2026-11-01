#!/usr/bin/env python3
"""Minimal Instabox watchdog: liveness, anti-sleep and progress are separate."""
from __future__ import annotations

import json
import logging
import os
import secrets
import signal
import sys
import time
import argparse
import threading
import urllib.error
import urllib.request
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

STOP = False


def env(name: str, default: str | None = None, required: bool = False) -> str:
    value = os.getenv(name, default)
    if required and not value:
        raise RuntimeError(f"missing required environment variable: {name}")
    return value or ""


BASE = env("INSTABOX_API_BASE_URL", "https://api.instabox.sh").rstrip("/")
API_KEY = env("INSTABOX_API_KEY")
MACHINE_ID = env("INSTABOX_MACHINE_ID")
MACHINE_NAME = env("INSTABOX_MACHINE_NAME")
INTERVAL = int(env("WATCHDOG_INTERVAL_SECONDS", "300"))
TIMEOUT = int(env("API_TIMEOUT_SECONDS", "20"))
PROGRESS_MAX_AGE = int(env("PROGRESS_MAX_AGE_SECONDS", "1800"))
STATE_DIR = Path(env("STATE_DIR", "./state"))
PROGRESS_FILE = Path(env("PROGRESS_FILE", str(STATE_DIR / "progress.json")))
PORT = int(env("PORT", "10000"))


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def save_event(event: dict) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    with (STATE_DIR / "events.jsonl").open("a", encoding="utf-8") as fh:
        fh.write(json.dumps({"ts": now(), **event}, ensure_ascii=False) + "\n")


def request(method: str, path: str, body: dict | None = None) -> dict:
    payload = None if body is None else json.dumps(body).encode()
    headers = {
        "Accept": "application/json",
        "X-API-Key": API_KEY,
        "Idempotency-Key": f"watchdog-{secrets.token_hex(16)}",
    }
    if body is not None:
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(BASE + path, data=payload, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=TIMEOUT) as response:
        raw = response.read().decode("utf-8")
        return json.loads(raw) if raw else {}


def machine_target() -> str:
    target = MACHINE_ID or MACHINE_NAME
    if not target:
        raise RuntimeError("one of INSTABOX_MACHINE_NAME or INSTABOX_MACHINE_ID is required")
    return target


def get_machine() -> dict:
    if not API_KEY or not machine_target():
        raise RuntimeError("INSTABOX_API_KEY and one of INSTABOX_MACHINE_NAME or INSTABOX_MACHINE_ID are not configured")
    return request("GET", f"/v1/machines/{machine_target()}")


def resume_machine() -> dict:
    return request("POST", f"/v1/machines/{machine_target()}/resume", {})


def start_machine() -> dict:
    return request("POST", f"/v1/machines/{machine_target()}/start", {})


def stop_machine() -> dict:
    return request("POST", f"/v1/machines/{machine_target()}/stop", {})


def suspend_machine() -> dict:
    return request("POST", f"/v1/machines/{machine_target()}/suspend", {})


def control(action: str) -> int:
    if action in {"stop", "suspend", "restart"} and env("ALLOW_DESTRUCTIVE_ACTIONS", "false").lower() != "true":
        raise RuntimeError("destructive action blocked; set ALLOW_DESTRUCTIVE_ACTIONS=true explicitly")
    actions = {
        "resume": resume_machine,
        "start": start_machine,
        "stop": stop_machine,
        "suspend": suspend_machine,
    }
    if action == "restart":
        result = stop_machine()
        save_event({"kind": "control", "action": "stop", "result": result})
        deadline = time.time() + int(env("CONTROL_WAIT_SECONDS", "120"))
        while time.time() < deadline:
            state = str(get_machine().get("state", "unknown")).lower()
            if state in {"stopped", "paused"}:
                break
            time.sleep(3)
        result = start_machine()
    else:
        result = actions[action]()
    save_event({"kind": "control", "action": action, "result": result})
    logging.info("control action=%s completed", action)
    return 0


def progress_age() -> float | None:
    try:
        data = json.loads(PROGRESS_FILE.read_text(encoding="utf-8"))
        stamp = float(data["updated_at_epoch"])
        return max(0.0, time.time() - stamp)
    except (FileNotFoundError, KeyError, TypeError, ValueError, json.JSONDecodeError):
        return None


def check_once() -> None:
    machine = get_machine()
    state = machine.get("state", "unknown")
    logging.info("machine=%s state=%s", machine_target(), state)
    save_event({"kind": "liveness", "state": state})

    if str(state).lower() == "paused":
        logging.warning("machine is paused; requesting official resume")
        result = resume_machine()
        save_event({"kind": "anti_sleep", "action": "resume", "result": result})

    age = progress_age()
    if age is None:
        logging.warning("progress heartbeat is missing")
        save_event({"kind": "progress", "status": "missing"})
    elif age > PROGRESS_MAX_AGE:
        logging.error("progress is stale: %.0fs", age)
        save_event({"kind": "progress", "status": "stale", "age_seconds": age})
    else:
        save_event({"kind": "progress", "status": "fresh", "age_seconds": age})


def stop_handler(_signum: int, _frame: object) -> None:
    global STOP
    STOP = True


class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802
        if self.path not in {"/", "/healthz"}:
            self.send_response(404)
            self.end_headers()
            return
        body = json.dumps({"ok": True, "service": "instabox-watchdog", "configured": bool(API_KEY and (MACHINE_ID or MACHINE_NAME))}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, _format: str, *_args: object) -> None:
        return


def start_health_server() -> ThreadingHTTPServer:
    server = ThreadingHTTPServer(("0.0.0.0", PORT), HealthHandler)
    threading.Thread(target=server.serve_forever, name="health-server", daemon=True).start()
    return server


def main() -> int:
    parser = argparse.ArgumentParser(description="InstaBox liveness and lifecycle watchdog")
    parser.add_argument("action", nargs="?", choices=["monitor", "resume", "start", "stop", "suspend", "restart"], default="monitor")
    args = parser.parse_args()
    signal.signal(signal.SIGTERM, stop_handler)
    signal.signal(signal.SIGINT, stop_handler)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    health_server = start_health_server()
    if args.action != "monitor":
        try:
            return control(args.action)
        finally:
            health_server.shutdown()
    logging.info("starting watchdog interval=%ss machine=%s", INTERVAL, MACHINE_ID or MACHINE_NAME)
    while not STOP:
        try:
            check_once()
        except (urllib.error.URLError, TimeoutError, OSError, RuntimeError, ValueError) as exc:
            logging.exception("watchdog check failed: %s", exc)
            save_event({"kind": "error", "error": str(exc)})
        for _ in range(INTERVAL):
            if STOP:
                break
            time.sleep(1)
    logging.info("stopped")
    return 0


if __name__ == "__main__":
    sys.exit(main())
