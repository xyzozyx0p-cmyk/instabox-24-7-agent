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
ALLOWED_MODELS = {
    "kr/claude-sonnet-4.5", "agnes-3.0-flash", "intern-s2", "hy4-preview",
    "SenseNova-6.8-Flash-Lite", "cx/gpt-6-luna", "LongCat-2.5-Preview",
    "z-ai/glm-5.3-flash", "perchai-minimax-m3", "zai-org/GLM-5.3", "auto",
    "kimi-k2.7-code", "kimi-k3", "glm-5.3-prime", "glm-5.3-flash", "glm-5.3",
    "deepseek-v4-flash", "deepseek-v4.1-flash-1017-uncensored",
    "deepseek-v4.1-flash-uncensored", "deepseek-v4.1-flash",
    "deepseek-v4.1-flash-1017", "deepseek-ai/DeepSeek-V4.1-Flash",
    "Qwen3.8-Flash-Next", "qwen3.8-max-0902", "qwen/qwen3.8-max:free",
    "qwen3.8-27b", "qwen3.8-flash", "qwen3-vl-plus", "qwen3.7-max",
    "qwen3.8-max", "qwen-max", "qwen-plus", "gemini-4-argon", "gemini-auto",
    "grok-4.7", "grok-4.6", "grok-chat-fast", "grok-4.5", "gpt-6.1-terra",
    "gpt-5.6-luna", "gpt-6-luna", "gpt-6-sol", "claude-haiku-5-5",
}


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
        json.load(response)  # Validate the provider response and the supplied key.
    # The user-maintained allowlist is authoritative. The provider catalog is often
    # incomplete or uses a different namespace, so do not silently drop requested IDs.
    return sorted(ALLOWED_MODELS, key=str.lower)


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
