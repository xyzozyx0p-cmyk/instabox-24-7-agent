#!/usr/bin/env python3
"""Manage LiteLLM provider aliases without storing provider keys in Git."""
from __future__ import annotations

import argparse
import getpass
import json
import os
import re
import secrets
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(os.environ.get("LITELLM_ROOT", "/data/infra/litellm"))
REGISTRY = ROOT / "providers.json"
CONFIG = ROOT / "config.yaml"
ENV_FILE = ROOT / "proxy.env"
SETTINGS = Path(os.environ.get("CLAUDE_SETTINGS", "/data/home/.claude/settings.json"))
SLUG = re.compile(r"^[a-z0-9][a-z0-9_-]{1,31}$")
ENV_NAME = re.compile(r"^[A-Z][A-Z0-9_]{2,63}$")


def load() -> dict:
    if not REGISTRY.exists():
        return {"providers": []}
    return json.loads(REGISTRY.read_text(encoding="utf-8"))


def save(data: dict) -> None:
    REGISTRY.parent.mkdir(parents=True, exist_ok=True)
    fd, temp = tempfile.mkstemp(prefix="providers.", dir=REGISTRY.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(data, handle, indent=2, ensure_ascii=False)
            handle.write("\n")
        os.chmod(temp, 0o600)
        os.replace(temp, REGISTRY)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


def q(value: str) -> str:
    return '"' + value.replace('\\', '\\\\').replace('"', '\\"') + '"'


def render_config(data: dict) -> None:
    lines = ["model_list:"]
    for provider in data.get("providers", []):
        protocol = provider["protocol"]
        base = provider.get("api_base", "").rstrip("/")
        env_key = provider["env_key"]
        for model in provider.get("models", []):
            lines += [
                f"  - model_name: {q(model['alias'])}",
                "    litellm_params:",
                f"      model: {q(protocol + '/' + model['id'])}",
                f"      api_base: {q(base)}",
                f"      api_key: {q('os.environ/' + env_key)}",
            ]
    lines += [
        "litellm_settings:",
        "  drop_params: true",
        "  set_verbose: false",
        "general_settings:",
        "  master_key: os.environ/PROXY_AUTH_TOKEN",
    ]
    CONFIG.write_text("\n".join(lines) + "\n", encoding="utf-8")
    os.chmod(CONFIG, 0o600)


def restart() -> None:
    subprocess.run(["sudo", "systemctl", "restart", "litellm-local.service"], check=True)


def add(args: argparse.Namespace) -> None:
    if not SLUG.fullmatch(args.name):
        raise SystemExit("name must contain 2-32 lowercase letters, digits, _ or -")
    if args.protocol not in {"anthropic", "openai"}:
        raise SystemExit("protocol must be anthropic or openai")
    if not ENV_NAME.fullmatch(args.env_key):
        raise SystemExit("env-key must be an uppercase environment variable name")
    data = load()
    providers = [p for p in data["providers"] if p["name"] != args.name]
    models = []
    for model_id in args.models:
        alias = f"{args.name}-{model_id}"
        models.append({"id": model_id, "alias": alias})
    providers.append({
        "name": args.name,
        "protocol": args.protocol,
        "api_base": args.api_base.rstrip("/"),
        "env_key": args.env_key,
        "models": models,
    })
    data["providers"] = sorted(providers, key=lambda p: p["name"])
    save(data)
    render_config(data)
    if args.key_stdin:
        key = os.read(0, 65536).decode().strip()
    else:
        key = getpass.getpass(f"Enter value for {args.env_key}: ").strip()
    if not key:
        raise SystemExit("empty provider key")
    set_env(args.env_key, key)
    restart()
    print(json.dumps({"ok": True, "provider": args.name, "models": [m["alias"] for m in models]}, ensure_ascii=False))


def set_env(name: str, value: str) -> None:
    lines = []
    found = False
    if ENV_FILE.exists():
        for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
            if line.startswith(name + "="):
                lines.append(f"{name}={value}")
                found = True
            else:
                lines.append(line)
    if not found:
        lines.append(f"{name}={value}")
    ENV_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8")
    os.chmod(ENV_FILE, 0o600)


def list_models(_args: argparse.Namespace) -> None:
    data = load()
    output = []
    env = {}
    if ENV_FILE.exists():
        for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
            if "=" in line:
                name, value = line.split("=", 1)
                env[name] = bool(value)
    for provider in data.get("providers", []):
        for model in provider.get("models", []):
            output.append({
                "alias": model["alias"],
                "provider": provider["name"],
                "protocol": provider["protocol"],
                "api_base": provider["api_base"],
                "key_configured": env.get(provider["env_key"], False),
            })
    print(json.dumps(output, indent=2, ensure_ascii=False))


def main() -> None:
    parser = argparse.ArgumentParser(description="LiteLLM provider/model registry")
    sub = parser.add_subparsers(dest="command", required=True)
    add_parser = sub.add_parser("add")
    add_parser.add_argument("name")
    add_parser.add_argument("--protocol", choices=["anthropic", "openai"], required=True)
    add_parser.add_argument("--api-base", required=True)
    add_parser.add_argument("--env-key", required=True)
    add_parser.add_argument("--key-stdin", action="store_true")
    add_parser.add_argument("models", nargs="+", help="provider model IDs")
    add_parser.set_defaults(func=add)
    list_parser = sub.add_parser("list")
    list_parser.set_defaults(func=list_models)
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
