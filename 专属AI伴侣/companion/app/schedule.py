"""角色作息：**每个角色有自己的睡点和起点**。

## 为什么要这个

之前的 `quiet_hours` 是**全局一份**（00:30~08:30），于是所有角色在同一个
时段一起活跃、又在同一个时段一起消失 —— 用户实测的原话就是「一到晚上
所有学生都说很困，没有夜猫子陪我聊天」，这是同质化的另一半。

真实数据（`group_网络小白·蜜雪罐城` 57 万条）：凌晨 0~6 点仍有 **12%** 的
消息。所以真相不是「大家集体睡觉」，而是**不同的人在不同时段活跃** ——
把作息做成角色级的，凌晨自然只剩下夜猫子出声。

## 怎么配

`persona/schedules.json`（一个人一个文件，改起来最省事）：

    {
      "星野":  {"sleep": "05:30", "wake": "13:00", "nocturnal": true,
                "label": "夜里执勤，白天补觉"},
      "天童凯伊": {"sleep": "01:40", "wake": "07:20"},
      "橘光":  {"sleep": "23:00", "wake": "06:30", "nap": ["13:00", "14:00"]}
    }

- `sleep` / `wake`：HH:MM，睡点（含）到起点（不含），跨午夜自动处理
- `nap`：可选午睡 `[开始, 结束]`
- `nocturnal`：夜猫子（只影响提示词的说法，判定完全由 sleep/wake 决定）
- `label`：人设里的说法，被吵醒时她会拿这句搪塞

**没配的角色**按名字派生一个**稳定**的作息（同一个名字永远得到同一份，
重启不漂），所以人物天生就错开，不会被「统一睡点」拉平。
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional


def _to_min(value: Any, default: int) -> int:
    """把 "HH:MM" 转成一天内的分钟数；解析不了就用 default。"""
    try:
        h, m = str(value).split(":")
        return (int(h) % 24) * 60 + (int(m) % 60)
    except (ValueError, AttributeError, TypeError):
        return default


def _fmt(minutes: int) -> str:
    minutes %= 24 * 60
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


# 软边界的宽度（分钟）：刚醒 / 快睡 这一段不是「睡着」，只是「不清醒」
EDGE_MIN = 45


@dataclass
class Schedule:
    sleep: str = "00:30"
    wake: str = "08:00"
    nap: Optional[List[str]] = None
    nocturnal: bool = False
    label: str = ""

    # ---------------- 判定 ----------------

    @property
    def sleep_m(self) -> int:
        return _to_min(self.sleep, 30)

    @property
    def wake_m(self) -> int:
        return _to_min(self.wake, 8 * 60)

    @property
    def nap_m(self) -> Optional[int]:
        if not self.nap:
            return None
        return _to_min(self.nap[0], -1)

    def _nap_window(self) -> Optional[tuple]:
        if not isinstance(self.nap, (list, tuple)) or len(self.nap) < 2:
            return None
        a = _to_min(self.nap[0], -1)
        b = _to_min(self.nap[1], -1)
        if a < 0 or b < 0 or a == b:
            return None
        return a, b

    @staticmethod
    def _in_window(cur: int, start: int, end: int) -> bool:
        if start == end:
            return False
        if start < end:
            return start <= cur < end
        return cur >= start or cur < end          # 跨午夜

    def asleep(self, now: Optional[datetime] = None) -> bool:
        """现在是不是在睡（含午睡）。"""
        now = now or datetime.now()
        cur = now.hour * 60 + now.minute
        if self._in_window(cur, self.sleep_m, self.wake_m):
            return True
        nap = self._nap_window()
        return bool(nap and self._in_window(cur, nap[0], nap[1]))

    def wakefulness(self, now: Optional[datetime] = None) -> float:
        """清醒度 0~1。睡着 0；刚醒 / 快睡是 0.3~0.9 的坡。"""
        now = now or datetime.now()
        if self.asleep(now):
            return 0.0
        sleep_m, wake_m = self.sleep_m, self.wake_m
        cur = now.hour * 60 + now.minute
        day = 24 * 60
        # 「距起床过了多久」与「距睡觉还剩多久」（都用环形距离）
        since_wake = (cur - wake_m) % day
        until_sleep = (sleep_m - cur) % day
        ramp = 1.0
        if since_wake < EDGE_MIN:
            ramp = min(ramp, 0.35 + 0.65 * since_wake / EDGE_MIN)
        if until_sleep < EDGE_MIN:
            ramp = min(ramp, 0.35 + 0.65 * until_sleep / EDGE_MIN)
        return max(0.0, min(1.0, ramp))

    def minutes_until_wake(self, now: Optional[datetime] = None) -> float:
        """距离「醒来」还有多少分钟（醒着返回 0）。

        主动心跳用它把排期推到起床之后 —— 不然她会在凌晨 3 点抽到
        「马上（1~8 分钟）」，然后每一分钟醒一次、每次都被「她在睡」挡掉。
        """
        now = now or datetime.now()
        if not self.asleep(now):
            return 0.0
        cur = now.hour * 60 + now.minute
        nap = self._nap_window()
        target = nap[1] if (nap and self._in_window(cur, nap[0], nap[1])) \
            else self.wake_m
        return float((target - cur) % (24 * 60))

    # ---------------- 提示词 ----------------

    def scene_text(self, now: Optional[datetime] = None) -> str:
        """给提示词的一小段「你现在是什么状态」。清醒时段返回空串。"""
        now = now or datetime.now()
        clock = now.strftime("%H:%M")
        if self.asleep(now):
            why = f"（{self.label}）" if self.label else ""
            return (f"【作息】现在是 {clock}，你本来在睡{why} —— 这条是被手机"
                    "震醒的。脑子还没转过来：回话**短、慢、带困意**，可以含糊、"
                    "可以让他明天再说，别突然精神抖擞地聊起来。")
        w = self.wakefulness(now)
        if w >= 0.95:
            return ""
        sleep_m, wake_m = self.sleep_m, self.wake_m
        cur = now.hour * 60 + now.minute
        day = 24 * 60
        if (cur - wake_m) % day < EDGE_MIN:
            return (f"【作息】现在是 {clock}，你刚起来没多久，还有点懵、"
                    "头发乱着 —— 说话可以慢半拍、带点起床气或赖床。")
        return (f"【作息】现在是 {clock}，你快到睡觉的点了"
                f"（{_fmt(sleep_m)} 睡），开始犯困、注意力散 —— "
                "回话短一些，可以说明天再聊。")


def default_for(name: str) -> Schedule:
    """没配作息的角色：按名字派生一份**稳定**的作息。

    同一个名字永远得到同一份（重启不漂），不同的人天然错开 ——
    睡点在 23:00~01:40、起点在 07:00~10:20 之间。
    """
    h = int(hashlib.md5(str(name or "?").encode("utf-8")).hexdigest()[:8], 16)
    sleep_m = 23 * 60 + (h % 160)              # 23:00 ~ 01:40
    wake_m = 7 * 60 + ((h >> 8) % 200)         # 07:00 ~ 10:20
    noon_nap = None
    if (h >> 16) % 3 == 0:                     # 三分之一的人有午睡
        nap_at = 12 * 60 + 30 + ((h >> 20) % 90)
        noon_nap = [_fmt(nap_at), _fmt(nap_at + 50)]
    return Schedule(sleep=_fmt(sleep_m), wake=_fmt(wake_m), nap=noon_nap)


def load_schedules(cfg) -> Dict[str, Schedule]:
    """读 persona/schedules.json；坏文件不影响运行（回落默认派生）。"""
    out: Dict[str, Schedule] = {}
    path = cfg.persona_path("schedules.json")
    if not Path(path).exists():
        return out
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        print(f"[schedule] 读取 {path} 失败，改用名字派生的默认作息：{e!r}")
        return out
    for name, item in (raw or {}).items():
        if not isinstance(item, dict):
            continue
        out[str(name)] = Schedule(
            sleep=str(item.get("sleep") or "00:30"),
            wake=str(item.get("wake") or "08:00"),
            nap=item.get("nap"),
            nocturnal=bool(item.get("nocturnal")),
            label=str(item.get("label") or ""),
        )
    if out:
        print(f"[schedule] 已加载 {len(out)} 份角色作息："
              + "、".join(sorted(out)))
    return out


def schedule_for(name: str, table: Optional[Dict[str, Schedule]] = None
                 ) -> Schedule:
    if table and name in table:
        return table[name]
    return default_for(name)
