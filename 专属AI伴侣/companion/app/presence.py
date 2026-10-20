"""用户的在线状态（像 QQ 的状态菜单）。

状态不是装饰，是**主动性的乘数**：

- 切到「在线 / Q我吧」→ 好友会主动来打招呼，主动频率提高
- 「离开 / 忙碌 / 隐身 / 离线」→ 频率降低，但**不是不发**
- 「请勿打扰」→ 只有这个状态完全不主动

为什么要有这个东西：用户的原话是「今天都上线了，还要我自己去发起聊天，
挺心累的」。她要的是一个会主动来找她的朋友，而不是一个等她喂消息的机器人。

数值接在 `traits.derive_autonomy` / `derive_conversation` 之上，
和「热情 / 好感」是同一层结构：改完立即 replay（heartbeat.replan）。

状态是**手动**切换的 —— 和 QQ 一样。这里没有可靠的「用户真的在电脑前」
信号，硬猜只会让打招呼在不该出现的时候冒出来。
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parent.parent
PRESENCE_FILE = ROOT / "data" / "presence.json"

# 两次「上线打招呼」之间的最小间隔：防止来回切状态把人刷烦
GREET_COOLDOWN_SEC = 900.0

# status 表。freq = 主动频率乘数；follow = 接话/追问的乘数；
# greet = 切到这个状态时是否触发「好友来打招呼」；silent = 完全不主动。
STATUSES: List[Dict[str, Any]] = [
    {
        "key": "online", "label": "在线", "emoji": "🟢",
        "freq": 1.0, "follow": 1.0, "greet": True, "silent": False,
        "desc": "随时可以来找我",
        "hint": "对方现在在线，可能只是在等你说点什么。",
    },
    {
        "key": "qme", "label": "Q我吧", "emoji": "🟠",
        "freq": 2.0, "follow": 1.4, "greet": True, "silent": False,
        "desc": "我现在有空，来找我聊",
        "hint": ("对方刚刚把状态改成「Q我吧」—— 这是明确的邀请：他现在有空，"
                 "想被你找。别客气，主动一点、多陪陪他；想到什么就发，不用等他先开口。"),
    },
    {
        "key": "away", "label": "离开", "emoji": "🌙",
        "freq": 0.6, "follow": 0.65, "greet": False, "silent": False,
        "desc": "暂时不在，稍微安静一点",
        "hint": "对方是离开状态，可能在忙别的。可以说话，但别追问、别连着发。",
    },
    {
        "key": "busy", "label": "忙碌", "emoji": "⛔",
        "freq": 0.4, "follow": 0.5, "greet": False, "silent": False,
        "desc": "在忙，消息少一点",
        "hint": "对方正忙。消息可以发，但要短，别要求回应。",
    },
    {
        "key": "dnd", "label": "请勿打扰", "emoji": "🚫",
        "freq": 0.12, "follow": 0.25, "greet": False, "silent": True,
        "desc": "先别来打扰，等我来找你",
        "hint": ("对方设了「请勿打扰」，不想被打扰。除非你特别想说，"
                 "否则先别开口 —— 他忙完会主动来找你的。"),
    },
    {
        "key": "invisible", "label": "隐身", "emoji": "👻",
        "freq": 0.35, "follow": 0.7, "greet": False, "silent": False,
        "desc": "想安静待着，但别断联",
        "hint": "对方隐身：想安静待着，但并没有真的下线。可以偶尔轻声说一句，别连着追。",
    },
    {
        "key": "offline", "label": "离线", "emoji": "⚫",
        "freq": 0.25, "follow": 0.6, "greet": False, "silent": False,
        "desc": "下线了，留言就好",
        "hint": ("对方下线了。可以留言（他回来会看到），"
                 "但别指望马上有回应，也别一条接一条。"),
    },
]

DEFAULT_STATUS = "online"
_BY_KEY: Dict[str, Dict[str, Any]] = {s["key"]: s for s in STATUSES}


@dataclass
class Presence:
    key: str = DEFAULT_STATUS
    updated_at: float = 0.0
    last_greet_ts: float = 0.0

    @property
    def meta(self) -> Dict[str, Any]:
        return _BY_KEY.get(self.key, _BY_KEY[DEFAULT_STATUS])

    @property
    def label(self) -> str:
        return str(self.meta["label"])

    @property
    def emoji(self) -> str:
        return str(self.meta["emoji"])

    @property
    def desc(self) -> str:
        return str(self.meta["desc"])

    @property
    def hint(self) -> str:
        return str(self.meta["hint"])

    @property
    def freq(self) -> float:
        return float(self.meta["freq"])

    @property
    def follow(self) -> float:
        return float(self.meta["follow"])

    @property
    def greet(self) -> bool:
        return bool(self.meta["greet"])

    @property
    def silent(self) -> bool:
        return bool(self.meta["silent"])


# ---------------------------------------------------------------- 存储

def _load() -> Dict[str, Any]:
    try:
        data = json.loads(PRESENCE_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _save(data: Dict[str, Any]) -> None:
    PRESENCE_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = PRESENCE_FILE.with_name(PRESENCE_FILE.name + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2),
                   encoding="utf-8")
    tmp.replace(PRESENCE_FILE)


def get_presence() -> Presence:
    data = _load()
    key = str(data.get("status") or DEFAULT_STATUS)
    if key not in _BY_KEY:
        key = DEFAULT_STATUS
    return Presence(
        key=key,
        updated_at=float(data.get("updated_at") or 0.0),
        last_greet_ts=float(data.get("last_greet_ts") or 0.0),
    )


def set_status(key: str) -> Tuple[Presence, str]:
    """设置状态。返回 (新状态, 之前的状态 key)。

    调用方靠「之前的状态」判断要不要触发上线打招呼：
    从非打招呼状态切到「在线 / Q我吧」才算「上线」。
    """
    key = str(key or "").strip().lower()
    if key not in _BY_KEY:
        raise ValueError(f"没有这个状态：{key}")
    data = _load()
    prev = str(data.get("status") or DEFAULT_STATUS)
    data["status"] = key
    data["updated_at"] = time.time()
    _save(data)
    return get_presence(), prev


def greet_cooldown_ok(min_sec: float = GREET_COOLDOWN_SEC) -> bool:
    p = get_presence()
    return (time.time() - p.last_greet_ts) >= max(0.0, min_sec)


def mark_greeted() -> None:
    data = _load()
    data["last_greet_ts"] = time.time()
    _save(data)


def reset_greet_cooldown() -> None:
    """测试用：把打招呼冷却清掉。"""
    data = _load()
    data["last_greet_ts"] = 0.0
    _save(data)


# ---------------------------------------------------------------- 提示词

def presence_text(p: Optional[Presence] = None) -> str:
    p = p or get_presence()
    if p.key == DEFAULT_STATUS:
        return ""
    return f"【对方状态】{p.label}（{p.desc}）\n- {p.hint}"


# ---------------------------------------------------------------- API

def presence_payload(p: Optional[Presence] = None) -> Dict[str, Any]:
    p = p or get_presence()
    return {
        "status": p.key,
        "label": p.label,
        "emoji": p.emoji,
        "desc": p.desc,
        "hint": p.hint,
        "freq": p.freq,
        "follow": p.follow,
        "greet": p.greet,
        "silent": p.silent,
        "updated_at": p.updated_at,
        "preview": f"主动频率 ×{p.freq:g}",
        "statuses": [
            {"key": s["key"], "label": s["label"], "emoji": s["emoji"],
             "desc": s["desc"], "silent": bool(s["silent"])}
            for s in STATUSES
        ],
    }
