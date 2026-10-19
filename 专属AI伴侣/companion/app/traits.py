"""每个对话角色的「热情 / 好感」参数。

数值参考了桌面 data 目录里 75 位好友的真实聊天（脚本统计见
`data/chat_frequency_stats.json`）：

- 好友主动发起会话：P10 0.70 / 中位 1.23 / P90 2.04 次/活跃日
- 好友回复延迟：P10 15s / 中位 24s / P90 41s

所以这里用同一条分位曲线把 0~100 的热情映射成：
- 主动频率（好友主动发起会话/天）
- 回复速度（中位回复秒数）

好感不改变硬频率，而是改变「关心、好奇、黏人、暧昧」的提示词强度，
以及接话窗口、追问次数、连发上限等软参数。
"""
from __future__ import annotations

import json
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Dict, List, Tuple

from .config import AutonomyConfig, ConversationConfig

ROOT = Path(__file__).resolve().parent.parent
TRAITS_FILE = ROOT / "data" / "character_traits.json"

# 默认值：按角色性格给一个接近真人的起点；新角色用 50/60
DEFAULT_TRAITS: Dict[str, Tuple[int, int]] = {
    "星野": (78, 85),
    "古关忧": (30, 55),
    "夏目安安": (35, 62),
    "天童凯伊": (50, 66),
    "天童爱丽丝": (72, 76),
    "早濑优香": (60, 72),
    "橘光": (76, 66),
    "橘希望": (82, 72),
    "橘雪莉": (58, 56),
    "空崎日奈": (46, 72),
}

# 真实聊天分位曲线（x=热情, y=次数/天 或 秒）
# ★ 2026-10-18 用户要求：热情对「主动频率 / 回复速度」的影响放大 4 倍。
#   频率 ×4，回复耗时 ÷4（即速度 ×4）。
_SESSION_POINTS: List[Tuple[float, float]] = [
    (0, 0.32), (10, 2.00), (25, 3.76), (50, 4.92),
    (75, 6.48), (90, 8.16), (100, 16.40),
]
_REPLY_POINTS: List[Tuple[float, float]] = [
    (0, 37.5), (10, 17.5), (25, 11.25), (50, 6),
    (75, 5), (90, 4), (100, 3),
]


def _interp(points: List[Tuple[float, float]], x: float) -> float:
    x = max(points[0][0], min(points[-1][0], float(x)))
    for (x0, y0), (x1, y1) in zip(points, points[1:]):
        if x <= x1:
            if x1 == x0:
                return y1
            return y0 + (y1 - y0) * (x - x0) / (x1 - x0)
    return points[-1][1]


def _clamp_int(v: Any, lo: int = 0, hi: int = 100) -> int:
    try:
        n = int(round(float(v)))
    except (TypeError, ValueError):
        return lo
    return max(lo, min(hi, n))


@dataclass
class Traits:
    enthusiasm: int = 50
    affection: int = 60

    @property
    def sessions_per_day(self) -> float:
        return _interp(_SESSION_POINTS, self.enthusiasm)

    @property
    def reply_seconds(self) -> float:
        return _interp(_REPLY_POINTS, self.enthusiasm)

    @property
    def delay_scale(self) -> float:
        # 24 秒 = 1.0 倍；4 倍提速后高热情可以到 0.125
        return max(0.12, min(6.0, self.reply_seconds / 24.0))


# ---------------------------------------------------------------- 存储

def _load_all() -> Dict[str, Dict[str, int]]:
    try:
        data = json.loads(TRAITS_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _save_all(data: Dict[str, Dict[str, int]]) -> None:
    TRAITS_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = TRAITS_FILE.with_name(TRAITS_FILE.name + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2),
                   encoding="utf-8")
    tmp.replace(TRAITS_FILE)


def get_traits(peer_id: str, name: str = "") -> Traits:
    saved = _load_all().get(str(peer_id))
    if isinstance(saved, dict):
        return Traits(
            enthusiasm=_clamp_int(saved.get("enthusiasm", 50)),
            affection=_clamp_int(saved.get("affection", 60)),
        )
    e, a = DEFAULT_TRAITS.get(name, (50, 60))
    return Traits(enthusiasm=e, affection=a)


def save_traits(peer_id: str,
                enthusiasm: Any, affection: Any) -> Traits:
    t = Traits(enthusiasm=_clamp_int(enthusiasm),
               affection=_clamp_int(affection))
    data = _load_all()
    data[str(peer_id)] = {"enthusiasm": t.enthusiasm, "affection": t.affection}
    _save_all(data)
    return t


def ensure_defaults(chars) -> None:
    """为还没有记录的角色的写入默认值（不改动用户已经调过的）。"""
    data = _load_all()
    changed = False
    for c in chars or []:
        cid = str(getattr(c, "id", "") or "")
        name = str(getattr(c, "name", "") or "")
        if not cid or cid in data:
            continue
        e, a = DEFAULT_TRAITS.get(name, (50, 60))
        data[cid] = {"enthusiasm": e, "affection": a}
        changed = True
    if changed:
        _save_all(data)


# ---------------------------------------------------------------- 派生配置

def derive_autonomy(base: AutonomyConfig, t: Traits) -> AutonomyConfig:
    sessions = t.sessions_per_day
    # daily_max 是「主动消息条数」，一次主动通常 1~2 条；给一点余量
    daily = 0 if t.enthusiasm <= 0 else max(1, min(24, round(sessions * 1.4)))
    # 频率整体 ×4 后，间隔也同步缩短到 1/4，否则会被硬间隔卡住
    min_gap = int(round(_interp([
        (0, 180), (25, 60), (50, 30),
        (75, 22), (90, 15), (100, 8),
    ], t.enthusiasm)))
    first_contact = int(round(_interp([
        (0, 180), (25, 60), (50, 22),
        (75, 12), (90, 8), (100, 4),
    ], t.enthusiasm)))
    # 兜底上限：无论抽到「远」档还是顺延，都不能睡过这个间隔。
    # 按目标频率算平均间隔，再留 1.2 倍余量；最低 1 小时、最高 12 小时。
    max_gap = int(round(1440.0 / max(1.0, sessions) * 1.2))
    max_gap = max(60, min(720, max_gap))
    skip = _interp([(0, 0.55), (25, 0.35), (50, 0.20),
                    (75, 0.10), (100, 0.04)], t.enthusiasm)

    e = t.enthusiasm / 100.0
    weights = [0.10 + 0.42 * e, 0.30 + 0.10 * e,
               0.35 - 0.18 * e, 0.25 - 0.34 * e]
    weights = [max(0.02, w) for w in weights]
    total = sum(weights)
    weights = [round(w / total, 4) for w in weights]

    a = t.affection / 100.0
    digest_share = 0 if t.affection < 20 else max(
        1, min(3, round(1 + a * 2)))
    return replace(
        base,
        daily_max=daily,
        min_gap_min=min_gap,
        first_contact_max_min=first_contact,
        max_gap_min=max_gap,
        skip_probability=round(skip, 3),
        rhythm_weights=weights,
        state_influence=min(1.0, base.state_influence + 0.15 * a),
        digest_max_share_per_day=digest_share,
        digest_threshold=round(0.62 - 0.30 * a, 3),
    )


def derive_conversation(base: ConversationConfig,
                        t: Traits) -> ConversationConfig:
    a = t.affection / 100.0
    e = t.enthusiasm / 100.0
    active = int(round(10 + a * 35))                 # 10~45 分钟
    follow_scale = 1.30 - 0.55 * a                    # 好感高 -> 更快接话
    follow = [max(20, int(round(x * follow_scale)))
              for x in (base.followup_delay_sec or [60, 180])]
    max_follow = max(1, min(5, round(1 + a * 4)))
    deep_follow = max(4, min(10, round(4 + a * 6)))
    max_turns = max(2, min(7, round(2 + a * 5)))
    burst = max(2, min(8, round(2 + e * 6)))
    deep_burst = max(4, min(12, burst + 4))
    probes = 1 if t.affection < 70 else 2
    reopen = [max(300, int(round(x * (1.15 - 0.35 * a))))
              for x in (base.reopen_delay_sec or [1200, 5400])]
    return replace(
        base,
        active_window_min=active,
        followup_delay_sec=follow,
        max_bot_turns_without_reply=max_turns,
        max_followups_per_topic=max_follow,
        deep_max_bot_turns=max(deep_follow, max_turns),
        deep_max_followups=deep_follow,
        max_burst_bubbles=burst,
        deep_max_burst_bubbles=deep_burst,
        max_probes_per_topic=probes,
        reopen_delay_sec=reopen,
    )


# ---------------------------------------------------------------- 提示词

def trait_text(t: Traits) -> str:
    e, a = t.enthusiasm, t.affection
    if e >= 80:
        speed = "你回得很快，也愿意主动找话题；想到什么就发，不端着。"
    elif e >= 55:
        speed = "你会正常地接话、偶尔主动；不会一直等对方先开口。"
    elif e >= 30:
        speed = "你偏慢热，主动不多；对方找你时会认真回，但不会连着追。"
    else:
        speed = "你很少主动，回复也慢半拍；话不多，更多是听和简短回应。"

    if a >= 80:
        care = ("你很在意对方：会关心吃饭、睡觉、身体和情绪，记得他说过的小事；"
                "会有点黏人，也允许一点只对他有的亲近和暧昧。")
    elif a >= 55:
        care = ("你把对方当熟人里比较亲近的人：会关心日常，偶尔追问，"
                "但不会太黏，也不会把关心挂嘴上。")
    elif a >= 30:
        care = "你对对方友好，但保持距离；会回应，不主动打探私事。"
    else:
        care = "你对对方比较客气疏离；不主动关心私生活，也不吃醋、不黏人。"

    return (
        f"热情 {e}/100，好感 {a}/100。\n"
        f"- 热情：{speed}\n"
        f"- 好感：{care}\n"
        "- 按这个强度自然表现，不要把数值说出来，也不要一次把所有特征都用上。\n"
        "- 角色设定为未成年的：好感高只表现为亲近、依赖、撒娇，"
        "不写性暗示，不推进恋爱关系。"
    )


def trait_preview(t: Traits) -> str:
    return (f"参考真实聊天：主动约 {t.sessions_per_day:.1f} 次/天 · "
            f"回复约 {int(round(t.reply_seconds))} 秒")


def traits_payload(peer_id: str, name: str = "") -> Dict[str, Any]:
    t = get_traits(peer_id, name)
    return {
        "peer_id": str(peer_id),
        "enthusiasm": t.enthusiasm,
        "affection": t.affection,
        "preview": trait_preview(t),
    }
