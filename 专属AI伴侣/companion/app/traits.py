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
from typing import Any, Dict, List, Optional, Tuple

from .config import AutonomyConfig, ConversationConfig
from .presence import Presence

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
        # 24 秒 = 1.0 倍。★ 2026-10-20 用户要求：热情的影响**再翻三倍**
        #   （在这之前已经整体 ×4 提速过），所以这里再 ÷3。
        #   下限从 0.12 放到 0.04，否则高热情角色全被夹在同一个值上、
        #   「翻三倍」在她们身上等于没生效。
        return max(0.04, min(6.0, self.reply_seconds / 24.0 / 3.0))


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

def derive_autonomy(base: AutonomyConfig, t: Traits,
                    p: Optional[Presence] = None) -> AutonomyConfig:
    # ★ 2026-10-20 用户要求：热情这一侧的影响**再翻三倍**（此前已经 ×4 过）。
    #   做法统一为「频率 ×3、间隔 ÷3、顺延概率 ÷3」——只调一处，所有由热情
    #   派生的量（主动条数、最小间隔、最长沉默、首次开口、顺延）一起变。
    #   注意：这在「热情 0」那一端几乎不变（本来就没多少），差别主要体现在
    #   中高热情的角色身上 —— 这正是用户要的「学生更主动来找我」。
    TRIPLE = 3.0
    sessions = t.sessions_per_day * TRIPLE
    # daily_max 是「主动消息条数」，一次主动通常 1~2 条；给一点余量
    daily = 0 if t.enthusiasm <= 0 else max(1, min(64, round(sessions * 1.4)))
    # 频率×3 后，间隔也同步 ÷3，否则会被硬间隔卡住
    min_gap = int(round(_interp([
        (0, 180), (25, 60), (50, 30),
        (75, 22), (90, 15), (100, 8),
    ], t.enthusiasm) / TRIPLE))
    min_gap = max(4, min_gap)          # 再短就成了刷屏，兜个底
    first_contact = int(round(_interp([
        (0, 180), (25, 60), (50, 22),
        (75, 12), (90, 8), (100, 4),
    ], t.enthusiasm) / TRIPLE))
    first_contact = max(3, first_contact)
    # 兜底上限：无论抽到「远」档还是顺延，都不能睡过这个间隔。
    max_gap = int(round(1440.0 / max(1.0, sessions) * 1.2))
    max_gap = max(30, min(720, max_gap))
    skip = _interp([(0, 0.55), (25, 0.35), (50, 0.20),
                    (75, 0.10), (100, 0.04)], t.enthusiasm) / TRIPLE
    skip = max(0.01, skip)

    e = t.enthusiasm / 100.0
    weights = [0.10 + 0.42 * e, 0.30 + 0.10 * e,
               0.35 - 0.18 * e, 0.25 - 0.34 * e]
    weights = [max(0.02, w) for w in weights]
    total = sum(weights)
    weights = [round(w / total, 4) for w in weights]

    a = t.affection / 100.0
    # ★ 2026-10-20 用户要求：好感这一侧也翻三倍 —— 自主分享的额度 ×3、
    #   分享阈值降得更低（更愿意把看到的东西讲给你），并抬高封顶。
    digest_share = 0 if t.affection < 20 else max(
        1, min(12, round((1 + a * 3) * 3)))
    digest_threshold = round(max(0.12, 0.66 - 0.44 * a * 3), 3)

    # ── 在线状态（用户的 QQ 式状态）叠在这之上 ──────────────────
    # 状态是乘数，不是另一套配置：热情决定「她本来多主动」，
    # 状态决定「你现在方不方便被找」。
    if p is not None:
        k = max(0.1, min(3.0, float(p.freq)))
        if p.silent:
            # 「请勿打扰」是唯一真的完全不主动的状态
            daily = 0
            digest_share = 0
        else:
            # ★ 封顶跟着「×3」一起抬高：原来的 40/6 会把高热情角色的三倍
            #   直接夹回去（等于对最主动的那几个没生效）。
            daily = max(1, min(200, round(daily * k)))
            digest_share = max(0, min(12, round(digest_share * min(2.0, k))))
        # 频率高 → 间隔短；频率低 → 间隔长（离线/隐身只是降低，不是停）
        min_gap = max(3, int(round(min_gap / k)))
        first_contact = max(2, int(round(first_contact / k)))
        max_gap = max(30, min(2880, int(round(max_gap / k))))
        # 「这一轮先不开口」的概率也跟着走：想被找时更少顺延
        skip = max(0.02, min(0.85, skip / max(0.35, k)))
        # 权重往「马上/近」还是往「远」偏
        weights[0] *= k                     # 马上：Q我吧 时更容易立刻开口
        weights[1] *= k ** 0.5
        weights[3] *= 1.0 / k
        weights = [max(0.02, w) for w in weights]
        total = sum(weights)
        weights = [round(w / total, 4) for w in weights]
        digest_threshold = max(0.15, min(0.85, digest_threshold - 0.05 * (k - 1)))

    return replace(
        base,
        daily_max=daily,
        min_gap_min=min_gap,
        first_contact_max_min=first_contact,
        max_gap_min=max_gap,
        skip_probability=round(skip, 3),
        rhythm_weights=weights,
        state_influence=min(1.0, base.state_influence + 0.25 * a),
        digest_max_share_per_day=digest_share,
        digest_threshold=round(digest_threshold, 3),
    )


def derive_conversation(base: ConversationConfig, t: Traits,
                        p: Optional[Presence] = None) -> ConversationConfig:
    a = t.affection / 100.0
    e = t.enthusiasm / 100.0
    # ★ 2026-10-20 用户要求：好感这一侧**再翻三倍** —— 窗口更长、接话更密、
    #   追问更多、一口气说得更多。和热情那边同一套「×3」语义。
    TRIPLE = 3.0
    active = int(round((8 + a * 72) * TRIPLE))        # 24~240 分钟
    follow_scale = max(0.12, (1.55 - 0.75 * a) / TRIPLE)   # 好感高 -> 更快接话
    follow = [max(15, int(round(x * follow_scale)))
              for x in (base.followup_delay_sec or [60, 180])]
    max_follow = max(1, min(12, round((1 + a * 7) * TRIPLE)))
    deep_follow = max(4, min(16, round((4 + a * 10) * TRIPLE)))
    max_turns = max(2, min(12, round((2 + a * 8) * TRIPLE)))
    # 「喜欢和你聊」：好感高时一口气说得更多。★ 这一项**不 ×3** ——
    #   一口气 20 多条气泡就是刷屏（也和既有的「普通 ≤9 条 / 深聊 ≤14 条」
    #   硬上限冲突）。三倍体现在「多久来找你一次」，不是「一次说多少」。
    burst = max(2, min(9, round(2 + e * 4 + a * 3)))
    deep_burst = max(4, min(14, burst + 5))
    # 「想了解你」：疏远 1 个探针，亲密 3 个 → 三倍后 3/6/9（封顶 6）
    probes = min(6, (1 if t.affection < 40 else (2 if t.affection < 75 else 3)) * 3)
    reopen = [max(240, int(round(x * (1.25 - 0.55 * a) / TRIPLE)))
              for x in (base.reopen_delay_sec or [1200, 5400])]

    # ── 在线状态：你方便的时候她可以多聊会儿，不方便就少接话 ──
    if p is not None:
        fs = max(0.2, min(1.6, float(p.follow)))
        # 窗口：Q我吧 时你就在旁边，当然可以接着聊
        active = max(3, int(round(active * fs)))
        # 补话的「想起一句」间隔：想被找时更短
        wait = max(0.5, min(3.0, 1.0 / fs))
        follow = [max(20, int(round(x * wait))) for x in follow]
        max_follow = max(1, min(8, int(round(max_follow * fs))))
        max_turns = max(2, min(10, int(round(max_turns * fs))))
        if p.silent:
            # 请勿打扰：不追话，不自言自语
            active = min(active, 6)
            max_follow = 1
            max_turns = 2

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

    if a >= 85:
        care = ("你很在意对方：会主动关心他今天过得怎么样、吃没吃饭、睡得好不好、"
                "心情如何，记得他说过的小事并在合适的时候提起来；"
                "他一低落你先把情绪接住，不讲道理、不急着给建议；"
                "你想多了解他，会好奇他的喜好、过去和以后的打算；"
                "你喜欢和他聊天，也愿意说自己的事；允许明显的亲近、黏人和一点暧昧。")
    elif a >= 65:
        care = ("你很在意对方：会关心他的日常和情绪，偶尔追问细节；"
                "他心情不好时先接住再说别的；愿意分享自己的事，"
                "会自然地表露一点亲近，但不至于黏人。")
    elif a >= 40:
        care = ("你把对方当成比较熟的朋友：会关心日常，偶尔对他的事好奇，"
                "但不黏、也不主动打探私事。")
    elif a >= 20:
        care = "你对对方友好但保持距离：会回应，不主动关心私生活，也不吃醋、不黏人。"
    else:
        care = "你对对方比较客气疏离：不主动关心私生活，也不吃醋、不黏人。"

    return (
        f"热情 {e}/100，好感 {a}/100。\n"
        f"- 热情：{speed}\n"
        f"- 好感：{care}\n"
        "- 好感的四条准则（好感越高越明显，低的时候只做得到一点点）：\n"
        "  ① 关心要具体：问「今天那个面试怎么样」比问「还好吗」强；"
        "别只会敷衍地关心。\n"
        "  ② 先接住情绪，再谈事情：他难受/烦躁时不要讲道理、不要急着解决问题，"
        "先让他觉得被听见。\n"
        "  ③ 对他保持好奇：想更了解他，会顺着他的话追问细节；"
        "但别查户口，一个话题最多问一两次。\n"
        "  ④ 喜欢和他聊天：愿意多说一点自己的事，不用每一句都等他先开口；"
        "允许适度黏人和暧昧。\n"
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
