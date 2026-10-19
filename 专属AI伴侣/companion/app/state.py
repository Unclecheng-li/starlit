"""情绪 / 关系 状态机。

设计取舍（见 02_技术设计与接口确认.md 第三节）：
初版只用「数值 + 衰减 + 事件增量」，不上微分方程。
但保留了微分方程版本的接口形状（tick / apply_interaction / apply_event），
以后想换成 Emergent Psychology Engine 那种连续模型，只需重写这三个方法。

关键点：情绪是**被持久化的状态**，不是 prompt 里的一句形容词。
"""
from __future__ import annotations

import time
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, Optional

from .store import Store


def _clamp(v: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, v))


def _toward(cur: float, target: float, amount: float) -> float:
    """向目标靠近 amount（不做越界）。"""
    if cur < target:
        return min(target, cur + amount)
    return max(target, cur - amount)


@dataclass
class EmotionState:
    valence: float = 0.0      # -100 ~ 100，正=开心
    arousal: float = 30.0     # 0 ~ 100，唤醒度
    energy: float = 80.0      # 0 ~ 100，社交电量
    anxiety: float = 10.0     # 0 ~ 100
    loneliness: float = 10.0  # 0 ~ 100
    updated_at: float = field(default_factory=time.time)


@dataclass
class RelationshipState:
    trust: float = 50.0
    security: float = 50.0
    intimacy: float = 40.0
    attachment: float = 40.0
    possessiveness: float = 20.0


@dataclass
class PersonaTraits:
    """慢变的人格基线，来自 persona。用于调制事件增量。"""
    neuroticism: float = 50.0   # 情绪波动性
    extraversion: float = 55.0
    agreeableness: float = 65.0
    openness: float = 70.0


# 事件 → 增量。intensity 为 0~1 外部强度。
EVENT_TABLE: Dict[str, Dict[str, float]] = {
    "praise":     {"valence": 35, "arousal": 15, "anxiety": -12, "loneliness": -10,
                   "trust": 1.2, "intimacy": 1.0, "security": 0.8},
    "comfort":    {"valence": 20, "arousal": -5, "anxiety": -15, "loneliness": -18,
                   "trust": 1.0, "intimacy": 1.2, "security": 1.0},
    "criticism":  {"valence": -30, "arousal": 20, "anxiety": 18, "loneliness": 10,
                   "trust": -1.0, "security": -1.2},
    "ignored":    {"valence": -18, "arousal": 8, "anxiety": 22, "loneliness": 25,
                   "security": -0.8, "possessiveness": 0.6},
    "reunion":    {"valence": 30, "arousal": 18, "anxiety": -25, "loneliness": -30,
                   "intimacy": 0.8, "attachment": 0.5},
    "conflict":   {"valence": -40, "arousal": 30, "anxiety": 25, "trust": -1.5, "security": -1.5},
    "jealousy":   {"valence": -25, "arousal": 20, "anxiety": 15, "possessiveness": 1.5, "security": -0.6},
    "casual":     {"valence": 6, "arousal": 3, "loneliness": -5},
    "deep_talk":  {"valence": 14, "arousal": 8, "loneliness": -12,
                   "intimacy": 1.4, "trust": 1.0, "security": 0.8},
}


class StateMachine:
    KEY = "emotion_state"
    RKEY = "relationship_state"

    def __init__(self, store: Store, traits: Optional[PersonaTraits] = None):
        self.store = store
        self.traits = traits or PersonaTraits()
        self.emotion = self._load_emotion()
        self.relationship = self._load_relationship()

    # ---------- 持久化 ----------
    def _load_emotion(self) -> EmotionState:
        raw = self.store.kv_get(self.KEY)
        if not raw:
            return EmotionState()
        return EmotionState(**{k: raw.get(k, getattr(EmotionState(), k))
                               for k in EmotionState().__dict__})

    def _load_relationship(self) -> RelationshipState:
        raw = self.store.kv_get(self.RKEY)
        if not raw:
            return RelationshipState()
        return RelationshipState(**{k: raw.get(k, getattr(RelationshipState(), k))
                                    for k in RelationshipState().__dict__})

    def save(self) -> None:
        self.store.kv_set(self.KEY, asdict(self.emotion))
        self.store.kv_set(self.RKEY, asdict(self.relationship))

    # ---------- 时间演化 ----------
    def tick(
        self,
        now: Optional[float] = None,
        last_interaction_ago_h: Optional[float] = None,
        resting: bool = False,
    ) -> float:
        """按经过的时间推进状态。返回推进的小时数。"""
        now = now or time.time()
        dt = max(0.0, (now - self.emotion.updated_at) / 3600.0)
        if dt <= 0:
            return 0.0
        e = self.emotion

        e.valence = _toward(e.valence, 0.0, 0.12 * dt)
        e.arousal = _toward(e.arousal, 30.0, 0.25 * dt)

        if resting:
            e.energy = _clamp(e.energy + 8.0 * dt)
        else:
            e.energy = _clamp(e.energy - 1.5 * dt)

        recent = last_interaction_ago_h is not None and last_interaction_ago_h < 0.5
        if recent:
            e.anxiety = _toward(e.anxiety, 5.0, 0.6 * dt)
            e.loneliness = _toward(e.loneliness, 5.0, 0.5 * dt)
        else:
            gap = last_interaction_ago_h if last_interaction_ago_h is not None else 24.0
            if gap > 6:
                stress = min(1.0, (gap - 6.0) / 24.0)
                e.anxiety = _clamp(
                    e.anxiety + 1.2 * dt * stress * (self.traits.neuroticism / 50.0)
                )
                e.loneliness = _clamp(
                    e.loneliness
                    + 3.0 * dt * (0.5 + self.relationship.attachment / 100.0)
                )
            else:
                e.anxiety = _toward(e.anxiety, 10.0, 0.1 * dt)
                e.loneliness = _toward(e.loneliness, 10.0, 0.1 * dt)

        e.updated_at = now
        self.save()
        return dt

    # ---------- 事件驱动 ----------
    def apply_event(self, name: str, intensity: float = 1.0) -> None:
        table = EVENT_TABLE.get(name)
        if not table:
            return
        inten = _clamp(intensity, 0.0, 2.0)
        e, r = self.emotion, self.relationship
        for k, v in table.items():
            delta = v * inten
            if hasattr(e, k):
                cur = getattr(e, k)
                lo, hi = (-100.0, 100.0) if k == "valence" else (0.0, 100.0)
                setattr(e, k, _clamp(cur + delta, lo, hi))
            elif hasattr(r, k):
                setattr(r, k, _clamp(getattr(r, k) + delta))
        e.updated_at = time.time()
        self.save()

    def apply_interaction(self, quality: float) -> None:
        """quality 0~1：这一轮互动的质量（由分析通道给出）。"""
        q = _clamp(quality, 0.0, 1.0)
        e, r = self.emotion, self.relationship
        # ★ 用「朝目标靠拢」而不是「直接加」。
        # 原来是 valence += 30*(q-0.5)：quality 常年 0.8~0.9 → 每轮 +9~12，
        # 而且 tick 的回落只有 0.12/小时，于是**一天之内就顶到 100 不动了**，
        # 表现就是「情绪永远开心、太平」。arousal 同理。
        # 改成朝「由 q 决定的目标」渐进，天然有上限、也能回落。
        v_target = _clamp(60.0 * (q - 0.5) * 2, -70.0, 70.0)   # q=1→+60, q=0.5→0
        e.valence = _toward(e.valence, v_target, max(4.0, abs(v_target - e.valence) * 0.25))
        a_target = _clamp(30.0 + 35.0 * q)
        e.arousal = _toward(e.arousal, a_target, max(3.0, abs(a_target - e.arousal) * 0.25))
        # 电量随互动质量变化：**聊得投入其实会回血**，聊得敷衍才掉。
        # 原来是固定 -3，聊天时只降不升，一路到 0 → 会话层彻底卡死。
        e.energy = _clamp(e.energy - 1.5 + 2.5 * q)
        e.anxiety = _clamp(e.anxiety - 20.0 * q + 5.0 * (1 - q))
        e.loneliness = _clamp(e.loneliness - 25.0 * q)
        r.trust = _clamp(r.trust + 0.6 * q)
        r.intimacy = _clamp(r.intimacy + 0.5 * q)
        r.attachment = _clamp(r.attachment + 0.3 * q)
        r.security = _clamp(r.security + 0.4 * q)
        e.updated_at = time.time()
        self.save()

    def recharge(self, amount: float) -> None:
        """回血。聊天过程中也该慢慢回，不能只靠深夜休息。

        没有这个的话，连续聊天时 energy 只降不升 → 一路到 0 →
        会话层直接「社交电量 0 太低」再也不接话（实测就是这样卡死的）。
        """
        self.emotion.energy = _clamp(self.emotion.energy + amount)
        self.emotion.updated_at = time.time()
        self.save()

    def manual_mood(self, word: str) -> bool:
        presets = {
            "开心": {"valence": 70, "arousal": 55},
            "平静": {"valence": 20, "arousal": 25},
            "低落": {"valence": -55, "arousal": 20},
            "烦躁": {"valence": -30, "arousal": 70},
            "兴奋": {"valence": 65, "arousal": 80},
        }
        p = presets.get(word)
        if not p:
            return False
        for k, v in p.items():
            setattr(self.emotion, k, float(v))
        self.emotion.updated_at = time.time()
        self.save()
        return True

    # ---------- 输出 ----------
    def mood_label(self) -> str:
        v, a = self.emotion.valence, self.emotion.arousal
        if v >= 45:
            base = "开心" if a >= 55 else "满足"
        elif v >= 10:
            base = "平静" if a < 45 else "有点雀跃"
        elif v >= -25:
            base = "淡淡的" if a < 45 else "有点不安"
        else:
            base = "低落" if a < 45 else "烦躁"
        if self.emotion.energy < 30:
            base += "，但很累"
        return base

    def describe(self) -> str:
        e, r = self.emotion, self.relationship
        return (
            f"当前心情：{self.mood_label()}。"
            f"（效价 {e.valence:.0f}/100，唤醒度 {e.arousal:.0f}，社交电量 {e.energy:.0f}，"
            f"焦虑 {e.anxiety:.0f}，孤独 {e.loneliness:.0f}）\n"
            f"与对方的关系：信任 {r.trust:.0f}、安全感 {r.security:.0f}、"
            f"亲密 {r.intimacy:.0f}、依恋 {r.attachment:.0f}、占有欲 {r.possessiveness:.0f}（均 0-100）"
        )


# 情绪关键词 → 事件映射（perceive 打标后转成增量用）
EMOTION_TO_EVENT = {
    "开心": "praise", "感激": "comfort", "温柔": "comfort",
    "难过": "criticism", "生气": "conflict", "焦虑": "ignored",
    "疲惫": "casual", "平静": "casual", "兴奋": "deep_talk",
    "依恋": "deep_talk", "吃醋": "jealousy",
}
