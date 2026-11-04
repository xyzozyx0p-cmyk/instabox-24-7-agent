#!/usr/bin/env python3
from __future__ import annotations

import asyncio
import json
import os
import re
import secrets
import select
import subprocess
import time
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field

APP = FastAPI(title="Claude Control Plane", version="0.1.0")
BEARER = HTTPBearer(auto_error=False)
TOKEN = os.environ.get("CONTROL_API_TOKEN", "")
WORKSPACE = Path(os.environ.get("CONTROL_WORKSPACE", "/data/workspace"))
DEFAULT_PROJECT = os.environ.get("CONTROL_PROJECT", str(WORKSPACE / "instabox-24-7-agent"))
PROVIDER_REGISTRY = Path(os.environ.get("PROVIDER_REGISTRY", "/data/infra/litellm/providers.json"))
MODEL_CACHE = Path(os.environ.get("MODEL_CACHE", "/data/infra/litellm/available-models.json"))
CLAUDE_SETTINGS = Path(os.environ.get("CLAUDE_SETTINGS", "/data/home/.claude/settings.json"))
MODEL_SYNC = Path(os.environ.get("MODEL_SYNC", "/data/infra/litellm/model_sync.py"))
MAX_MESSAGE = 32_000
SESSION_RE = re.compile(r"^[a-zA-Z0-9_-]{1,48}$")
AUTH_COOKIE = "control_session"


class MessageRequest(BaseModel):
    message: str = Field(min_length=1, max_length=MAX_MESSAGE)
    session: str = Field(default="claude", pattern=r"^[a-zA-Z0-9_-]{1,48}$")
    cwd: str | None = None


class CommandRequest(BaseModel):
    command: str = Field(min_length=1, max_length=16_000)
    session: str = Field(default="claude", pattern=r"^[a-zA-Z0-9_-]{1,48}$")


class SessionRequest(BaseModel):
    session: str = Field(default="terminal", pattern=r"^[a-zA-Z0-9_-]{1,48}$")
    cwd: str | None = None


class ModelSelectRequest(BaseModel):
    model: str = Field(min_length=2, max_length=200, pattern=r"^[a-zA-Z0-9._:/-]+$")


def require_token(request: Request, credentials: HTTPAuthorizationCredentials | None = Depends(BEARER)) -> None:
    supplied = credentials.credentials if credentials else request.cookies.get(AUTH_COOKIE)
    if not TOKEN or not supplied or not secrets.compare_digest(supplied, TOKEN):
        raise HTTPException(status_code=401, detail="unauthorized")


def check_token(value: str | None) -> None:
    if not TOKEN or not value or not secrets.compare_digest(value, TOKEN):
        raise HTTPException(status_code=401, detail="unauthorized")


def validate_session(name: str) -> str:
    if not SESSION_RE.fullmatch(name):
        raise HTTPException(status_code=400, detail="invalid session name")
    return name


def safe_cwd(cwd: str | None) -> str:
    candidate = Path(cwd or DEFAULT_PROJECT).expanduser().resolve()
    workspace = WORKSPACE.resolve()
    if candidate != workspace and workspace not in candidate.parents:
        raise HTTPException(status_code=400, detail="cwd must be under CONTROL_WORKSPACE")
    if not candidate.exists() or not candidate.is_dir():
        raise HTTPException(status_code=400, detail="cwd does not exist")
    return str(candidate)


def safe_file_path(relative_path: str) -> Path:
    candidate = (WORKSPACE / relative_path).resolve()
    workspace = WORKSPACE.resolve()
    if candidate != workspace and workspace not in candidate.parents:
        raise HTTPException(status_code=400, detail="path must be under CONTROL_WORKSPACE")
    return candidate


def registered_models() -> list[dict[str, Any]]:
    if not PROVIDER_REGISTRY.exists():
        return []
    data = json.loads(PROVIDER_REGISTRY.read_text(encoding="utf-8"))
    output = []
    cached = None
    if MODEL_CACHE.exists():
        try:
            cached = json.loads(MODEL_CACHE.read_text(encoding="utf-8")).get("providers", {})
        except (OSError, ValueError, TypeError):
            cached = None
    for provider in data.get("providers", []):
        if cached is None or not cached.get(provider["name"]):
            output.append({
                "alias": provider["name"] + "/*",
                "provider": provider["name"],
                "protocol": provider["protocol"],
                "api_base": provider["api_base"],
                "wildcard": True,
            })
        for model in provider.get("models", []) if cached is None else []:
            output.append({
                "alias": model["alias"],
                "provider": provider["name"],
                "protocol": provider["protocol"],
                "api_base": provider["api_base"],
                "wildcard": False,
            })
    if MODEL_CACHE.exists():
        try:
            cached = json.loads(MODEL_CACHE.read_text(encoding="utf-8")).get("providers", {})
            for provider in data.get("providers", []):
                for model_id in cached.get(provider["name"], []):
                    output.append({
                        "alias": provider["name"] + "/" + model_id,
                        "provider": provider["name"],
                        "protocol": provider["protocol"],
                        "api_base": provider["api_base"],
                        "wildcard": False,
                        "discovered": True,
                    })
        except (OSError, ValueError, TypeError):
            pass
    return output


async def sync_provider_models() -> dict[str, Any]:
    if not MODEL_SYNC.exists():
        return {"ok": False, "error": "model sync script not found"}
    try:
        result = await asyncio.to_thread(
            subprocess.run,
            ["/usr/bin/python3", str(MODEL_SYNC)],
            text=True,
            capture_output=True,
            timeout=45,
            check=False,
        )
        payload = json.loads(result.stdout.strip().splitlines()[-1]) if result.stdout.strip() else {}
        if result.returncode != 0:
            return {"ok": False, "error": "model sync failed", "details": payload}
        if payload.get("changed"):
            restart = await asyncio.to_thread(
                subprocess.run,
                ["sudo", "systemctl", "restart", "litellm-local.service"],
                text=True,
                capture_output=True,
                timeout=45,
                check=False,
            )
            if restart.returncode != 0:
                return {"ok": False, "error": "LiteLLM restart failed", "details": restart.stderr[-500:]}
            await asyncio.sleep(3)
        return {"ok": True, **payload}
    except Exception as exc:
        return {"ok": False, "error": type(exc).__name__}


def tmux(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["/usr/bin/tmux", *args], text=True, capture_output=True, check=check, timeout=15)


def has_session(name: str) -> bool:
    return tmux("has-session", "-t", name, check=False).returncode == 0


def create_session(name: str, cwd: str) -> None:
    validate_session(name)
    if not has_session(name):
        tmux("new-session", "-d", "-s", name, "-c", cwd, "bash")


def send_keys(name: str, text: str) -> None:
    validate_session(name)
    if not has_session(name):
        raise HTTPException(status_code=404, detail="session not found")
    # -l sends literal text, avoiding tmux key-name interpretation.
    tmux("send-keys", "-t", name, "-l", text)
    tmux("send-keys", "-t", name, "Enter")


def capture(name: str, lines: int = 300) -> str:
    validate_session(name)
    if not has_session(name):
        raise HTTPException(status_code=404, detail="session not found")
    result = tmux("capture-pane", "-p", "-S", f"-{max(1, min(lines, 2000))}", "-t", name)
    return result.stdout


@APP.get("/healthz")
async def healthz() -> dict[str, Any]:
    return {"ok": True, "service": "claude-control-plane"}


@APP.get("/", response_class=HTMLResponse)
async def login_page() -> str:
    return """<!doctype html><html><head><meta charset=utf-8><title>Claude Control Plane</title>
<style>body{font:16px system-ui;max-width:520px;margin:10vh auto;padding:24px;background:#111;color:#eee}input,button{font:inherit;padding:10px;margin-top:8px;width:100%;box-sizing:border-box}button{cursor:pointer}#msg{min-height:24px;color:#f88}</style></head>
<body><h1>Claude Control Plane</h1><p>Введите API-токен. Сервер проверит его до создания сессии.</p>
<form id=f><input id=t type=password autocomplete=current-password placeholder="CONTROL_API_TOKEN" required><button>Войти</button></form><p id=msg></p>
<script>f.onsubmit=async e=>{e.preventDefault();msg.textContent='Проверка...';let r=await fetch('/auth/login',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({token:t.value})});if(r.ok)location='/docs';else msg.textContent='Неверный токен (401)';}</script></body></html>"""


@APP.post("/auth/login")
async def login(request: Request) -> JSONResponse:
    try:
        payload = await request.json()
    except Exception as exc:
        raise HTTPException(status_code=400, detail="invalid JSON") from exc
    supplied = str(payload.get("token", ""))
    if not TOKEN or not secrets.compare_digest(supplied, TOKEN):
        raise HTTPException(status_code=401, detail="invalid credentials")
    response = JSONResponse({"ok": True})
    response.set_cookie(AUTH_COOKIE, TOKEN, max_age=86400, httponly=True, secure=True, samesite="strict")
    return response


@APP.post("/auth/logout")
async def logout() -> JSONResponse:
    response = JSONResponse({"ok": True})
    response.delete_cookie(AUTH_COOKIE)
    return response


@APP.get("/v1/status", dependencies=[Depends(require_token)])
async def status() -> dict[str, Any]:
    result = tmux("list-sessions", "-F", "#{session_name}", check=False)
    sessions = [s for s in result.stdout.splitlines() if s]
    return {
        "ok": True,
        "workspace": str(WORKSPACE),
        "default_project": DEFAULT_PROJECT,
        "sessions": sessions,
        "claude_installed": Path(os.path.expanduser("~/.local/bin/claude")).exists(),
    }


@APP.get("/v1/models", dependencies=[Depends(require_token)])
async def models() -> dict[str, Any]:
    current = None
    if CLAUDE_SETTINGS.exists():
        try:
            current = json.loads(CLAUDE_SETTINGS.read_text(encoding="utf-8")).get("env", {}).get("ANTHROPIC_MODEL")
        except (OSError, ValueError, TypeError):
            current = None
    return {"ok": True, "current": current, "models": registered_models()}


@APP.post("/v1/models/select", dependencies=[Depends(require_token)])
async def select_model(request: ModelSelectRequest) -> dict[str, Any]:
    aliases = {item["alias"] for item in registered_models()}
    if request.model not in aliases:
        raise HTTPException(status_code=404, detail="model alias not registered")
    settings = json.loads(CLAUDE_SETTINGS.read_text(encoding="utf-8")) if CLAUDE_SETTINGS.exists() else {}
    settings.setdefault("env", {})["ANTHROPIC_MODEL"] = request.model
    temp = CLAUDE_SETTINGS.with_suffix(".tmp")
    temp.write_text(json.dumps(settings, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    os.chmod(temp, 0o600)
    os.replace(temp, CLAUDE_SETTINGS)
    return {"ok": True, "model": request.model, "new_claude_session_required": True}


@APP.get("/v1/files", dependencies=[Depends(require_token)])
async def list_files(path: str = "") -> dict[str, Any]:
    directory = safe_file_path(path)
    if not directory.exists() or not directory.is_dir():
        raise HTTPException(status_code=404, detail="directory not found")
    entries = []
    for item in sorted(directory.iterdir(), key=lambda value: value.name.lower()):
        entries.append({
            "name": item.name,
            "path": str(item.relative_to(WORKSPACE)),
            "type": "directory" if item.is_dir() else "file",
            "size": item.stat().st_size if item.is_file() else None,
        })
    return {"ok": True, "path": path, "entries": entries}


@APP.post("/v1/files/upload", dependencies=[Depends(require_token)])
async def upload_file(path: str = Form(...), file: UploadFile = File(...)) -> dict[str, Any]:
    target = safe_file_path(path)
    if target == WORKSPACE.resolve():
        raise HTTPException(status_code=400, detail="file path is required")
    target.parent.mkdir(parents=True, exist_ok=True)
    size = 0
    try:
        with target.open("wb") as output:
            while chunk := await file.read(1024 * 1024):
                output.write(chunk)
                size += len(chunk)
    finally:
        await file.close()
    return {"ok": True, "path": str(target.relative_to(WORKSPACE)), "size": size}


@APP.get("/v1/files/download", dependencies=[Depends(require_token)])
async def download_file(path: str) -> FileResponse:
    target = safe_file_path(path)
    if not target.exists() or not target.is_file():
        raise HTTPException(status_code=404, detail="file not found")
    return FileResponse(target, filename=target.name, media_type="application/octet-stream")


@APP.post("/v1/sessions", dependencies=[Depends(require_token)])
async def create_terminal(request: SessionRequest) -> dict[str, Any]:
    session = validate_session(request.session)
    cwd = safe_cwd(request.cwd)
    create_session(session, cwd)
    return {"ok": True, "session": session, "cwd": cwd}


@APP.post("/v1/claude/start", dependencies=[Depends(require_token)])
async def start_claude(request: SessionRequest | None = None) -> dict[str, Any]:
    sync_result = await sync_provider_models()
    request = request or SessionRequest(session="claude")
    session = validate_session(request.session or "claude")
    cwd = safe_cwd(request.cwd)
    create_session(session, cwd)
    if not has_claude_process(session):
        tmux("send-keys", "-t", session, "-l", "claude")
        tmux("send-keys", "-t", session, "Enter")
    return {"ok": True, "session": session, "cwd": cwd, "model_sync": sync_result, "output": capture(session, 80)}


def has_claude_process(session: str) -> bool:
    result = tmux("list-panes", "-t", session, "-F", "#{pane_current_command}", check=False)
    return any("claude" in item.lower() for item in result.stdout.splitlines())


@APP.post("/v1/claude/message", dependencies=[Depends(require_token)])
async def claude_message(request: MessageRequest) -> dict[str, Any]:
    session = validate_session(request.session)
    cwd = safe_cwd(request.cwd)
    create_session(session, cwd)
    if not has_claude_process(session):
        tmux("send-keys", "-t", session, "-l", "claude")
        tmux("send-keys", "-t", session, "Enter")
        await asyncio.sleep(2)
    send_keys(session, request.message)
    return {"ok": True, "session": session, "accepted_at": time.time()}


@APP.get("/v1/claude/output", dependencies=[Depends(require_token)])
async def claude_output(session: str = "claude", lines: int = 300) -> dict[str, Any]:
    return {"ok": True, "session": validate_session(session), "output": capture(session, lines)}


@APP.post("/v1/command", dependencies=[Depends(require_token)])
async def command(request: CommandRequest) -> dict[str, Any]:
    send_keys(validate_session(request.session), request.command)
    return {"ok": True, "session": request.session, "accepted_at": time.time()}


async def ws_auth(websocket: WebSocket) -> None:
    query_token = websocket.query_params.get("token")
    cookie_token = websocket.cookies.get(AUTH_COOKIE)
    if (query_token and TOKEN and secrets.compare_digest(query_token, TOKEN)) or (cookie_token and TOKEN and secrets.compare_digest(cookie_token, TOKEN)):
        await websocket.accept()
        return
    await websocket.accept()
    try:
        raw = await asyncio.wait_for(websocket.receive_text(), timeout=10)
        data = json.loads(raw)
        if not TOKEN or not secrets.compare_digest(str(data.get("token", "")), TOKEN):
            await websocket.close(code=4401)
            raise WebSocketDisconnect(code=4401)
    except Exception:
        await websocket.close(code=4401)
        raise WebSocketDisconnect(code=4401)


@APP.websocket("/v1/sessions/{session}/ws")
async def terminal_ws(websocket: WebSocket, session: str) -> None:
    validate_session(session)
    await ws_auth(websocket)
    if websocket.client_state.name != "CONNECTED":
        return
    if not has_session(session):
        await websocket.close(code=4404)
        return

    master, slave = os.openpty()
    process = subprocess.Popen(
        ["/usr/bin/tmux", "attach-session", "-t", session],
        stdin=slave,
        stdout=slave,
        stderr=slave,
        close_fds=True,
        start_new_session=True,
    )
    os.close(slave)
    os.set_blocking(master, False)

    async def reader() -> None:
        while True:
            ready, _, _ = await asyncio.to_thread(select.select, [master], [], [], 1.0)
            if not ready:
                if process.poll() is not None:
                    return
                continue
            try:
                data = os.read(master, 8192)
            except (BlockingIOError, OSError):
                return
            if not data:
                return
            await websocket.send_bytes(data)

    async def writer() -> None:
        while True:
            message = await websocket.receive()
            if message.get("type") == "websocket.disconnect":
                return
            data = message.get("bytes")
            if data is None and message.get("text") is not None:
                data = message["text"].encode()
            if data:
                os.write(master, data)

    try:
        await asyncio.gather(reader(), writer())
    except (WebSocketDisconnect, RuntimeError, OSError):
        pass
    finally:
        try:
            process.terminate()
        except ProcessLookupError:
            pass
        os.close(master)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(APP, host="127.0.0.1", port=int(os.environ.get("CONTROL_PORT", "8787")))
