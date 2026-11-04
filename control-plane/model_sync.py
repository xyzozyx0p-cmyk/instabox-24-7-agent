#!/usr/bin/env python3
"""Fetch provider model catalogs with their configured keys and refresh LiteLLM routes."""
from __future__ import annotations

import json
import os
import tempfile
import urllib.request
from pathlib import Path

ROOT = Path(os.environ.get("LITELLM_ROOT", "/data/infra/litellm"))
REGISTRY = ROOT / "providers.json"
ENV_FILE = ROOT / "proxy.env"
CONFIG = ROOT / "config.yaml"
CACHE = ROOT / "available-models.json"
BLOCKED = (
    "image", "audio", "tts", "whisper", "transcrib", "embedding", "moderation",
    "realtime", "sora", "computer-use", "computer_use", "container", "music",
    "video", "speech",
)


def env_values() -> dict[str, str]:
    result = {}
    for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            key, value = line.split("=", 1)
            result[key] = value
    return result


def quote(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def fetch_models(provider: dict, values: dict[str, str]) -> list[str]:
    key = values.get(provider["env_key"], "")
    if not key:
        return []
    url = provider["api_base"].rstrip("/") + "/models"
    request = urllib.request.Request(url, headers={"Authorization": "Bearer " + key})
    with urllib.request.urlopen(request, timeout=25) as response:
        payload = json.load(response)
    rows = payload.get("data", payload if isinstance(payload, list) else [])
    output = []
    for row in rows:
        model_id = str(row.get("id", "")) if isinstance(row, dict) else str(row)
        if model_id and not any(word in model_id.lower() for word in BLOCKED):
            output.append(model_id)
    return sorted(set(output), key=str.lower)


def write_config(registry: dict, discovered: dict[str, list[str]]) -> None:
    lines = ["model_list:"]
    for provider in registry.get("providers", []):
        name = provider["name"]
        protocol = provider["protocol"]
        base = provider["api_base"].rstrip("/")
        env_key = provider["env_key"]
        # Once the provider catalog is fetched, expose only the filtered, key-authenticated
        # catalog. A wildcard is used only when discovery failed and there is no cache.
        if not discovered.get(name):
            lines += [
                f"  - model_name: {quote(name + '/*')}",
                "    litellm_params:",
                f"      model: {quote(protocol + '/*')}",
                f"      api_base: {quote(base)}",
                f"      api_key: {quote('os.environ/' + env_key)}",
            ]
        for model_id in discovered.get(name, []):
            lines += [
                f"  - model_name: {quote(name + '/' + model_id)}",
                "    litellm_params:",
                f"      model: {quote(protocol + '/' + model_id)}",
                f"      api_base: {quote(base)}",
                f"      api_key: {quote('os.environ/' + env_key)}",
            ]
        for model in provider.get("models", []):
            lines += [
                f"  - model_name: {quote(model['alias'])}",
                "    litellm_params:",
                f"      model: {quote(protocol + '/' + model['id'])}",
                f"      api_base: {quote(base)}",
                f"      api_key: {quote('os.environ/' + env_key)}",
            ]
    lines += [
        "litellm_settings:",
        "  drop_params: true",
        "  set_verbose: false",
        "general_settings:",
        "  master_key: os.environ/PROXY_AUTH_TOKEN",
    ]
    new_text = "\n".join(lines) + "\n"
    old_text = CONFIG.read_text(encoding="utf-8") if CONFIG.exists() else ""
    if new_text != old_text:
        fd, temp = tempfile.mkstemp(prefix="config.", dir=ROOT)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(new_text)
        os.chmod(temp, 0o600)
        os.replace(temp, CONFIG)
        return True
    return False


def sync() -> dict:
    registry = json.loads(REGISTRY.read_text(encoding="utf-8"))
    values = env_values()
    previous = {}
    if CACHE.exists():
        try:
            previous = json.loads(CACHE.read_text(encoding="utf-8")).get("providers", {})
        except (OSError, ValueError, TypeError):
            previous = {}
    discovered = {}
    errors = {}
    for provider in registry.get("providers", []):
        try:
            discovered[provider["name"]] = fetch_models(provider, values)
        except Exception as exc:
            discovered[provider["name"]] = previous.get(provider["name"], [])
            errors[provider["name"]] = type(exc).__name__
    CACHE.write_text(json.dumps({"providers": discovered, "errors": errors}, indent=2) + "\n", encoding="utf-8")
    changed = write_config(registry, discovered)
    return {"changed": changed, "counts": {k: len(v) for k, v in discovered.items()}, "errors": errors}


if __name__ == "__main__":
    print(json.dumps(sync(), ensure_ascii=False))
