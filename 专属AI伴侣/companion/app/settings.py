"""运行时全局设置（网页「设置」里改，落盘到 data/settings.json）。

只存需要用户自己填的东西，优先于 config.yaml：
- LLM 的 base_url / api_key / model

为什么要单独一层：config.yaml 是给开发者看的，开源后普通用户
不应该被要求去编辑 YAML；网页里改完立即生效、重启也还在。
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict

ROOT = Path(__file__).resolve().parent.parent
SETTINGS_FILE = ROOT / "data" / "settings.json"


def load() -> Dict[str, Any]:
    try:
        data = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def save(data: Dict[str, Any]) -> None:
    SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = SETTINGS_FILE.with_name(SETTINGS_FILE.name + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2),
                   encoding="utf-8")
    tmp.replace(SETTINGS_FILE)


def llm_overrides() -> Dict[str, Any]:
    llm = load().get("llm")
    return llm if isinstance(llm, dict) else {}


def update_llm(patch: Dict[str, Any]) -> Dict[str, Any]:
    data = load()
    llm = data.get("llm")
    if not isinstance(llm, dict):
        llm = {}
    for key in ("base_url", "api_key", "model", "timeout"):
        if key in patch:
            llm[key] = patch[key]
    data["llm"] = llm
    save(data)
    return llm


def mask_key(key: str) -> str:
    key = str(key or "")
    if not key:
        return ""
    if len(key) <= 8:
        return "*" * len(key)
    return key[:4] + "*" * max(4, len(key) - 8) + key[-4:]
