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
    neglect: float = 0.0      # 0 ~ 100：说了话却等不到回应的「被晾着」的委屈感
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
        unanswered_h: Optional[float] = None,
    ) -> float:
        """按经过的时间推进状态。返回推进的小时数。

        `unanswered_h`：我发出去的消息已经多少小时没人回了。
        None = 不知道（不收不放）；0 = 刚被回应（委屈感消退）；
        >0.5 = 正在被晾着（越久越担心/沮丧/难过，需求感越强）。
        """
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

        # ★ 等待对方回应：真人不回消息时，越亲近的人越会担心/沮丧/难过，
        #   并且越来越藏不住「想被回应」的需求感（暧昧对象/情侣的常态）。
        #   半小时内几乎没感觉；之后随时长线性加深，12 小时封顶。
        if unanswered_h is not None:
            if unanswered_h > 0.5:
                ramp = min(1.0, max(0.0, (unanswered_h - 0.5) / 11.5))
                pull = ramp * (1.0 + self.relationship.attachment / 100.0)
                e.anxiety = _clamp(e.anxiety + 2.2 * dt * pull)
                e.loneliness = _clamp(e.loneliness + 3.0 * dt * pull)
                e.neglect = _clamp(e.neglect + 4.0 * dt * pull)
                # 沮丧/难过：效价往下压，但不是立刻坍塌
                e.valence = _clamp(e.valence - 3.0 * dt * pull, -100.0, 100.0)
            else:
                e.neglect = _toward(e.neglect, 0.0, 12.0 * dt)

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
        # 被回应了 → 「被晾着」的委屈感很快消掉（对方回来了就不该记仇）
        e.neglect = _toward(e.neglect, 0.0, 45.0 * max(0.3, q))
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

    # ---------- 等待 / 重逢 ----------

    def _counter(self, key: str) -> float:
        """读 heartbeat 的计数器。

        ⚠️ describe() 现在会读 DB —— 而 describe() 在「store 已关闭」之后
        仍可能被调用（测试收尾、进程退出），这时 counter_get 会抛
        sqlite3.ProgrammingError。读不到就当 0，等不到回应也照样能说话。
        """
        try:
            return float(self.store.counter_get(key, 0.0) or 0.0)
        except Exception:  # noqa: BLE001
            return 0.0

    def waiting_hours(self) -> float:
        """我上一条主动消息已经多少小时没被回应（没在等就返回 0）。"""
        spoke = self._counter("last_spoke_ts")
        replied = self._counter("last_reply_ts")
        if not spoke or replied >= spoke:
            return 0.0
        return max(0.0, (time.time() - spoke) / 3600.0)

    def wait_rounds(self) -> int:
        """连着几轮主动都没收到回应（heartbeat 的冷场计数）。"""
        return int(self._counter("cold_streak"))

    def note_reunion(self, wait_h: float, now: Optional[float] = None) -> None:
        """对方在长时间不理之后回来了：开心 + 惊喜 + 一点撒娇。

        数据（analyze_chat_habits.waiting_report）显示：对方消失 ≥2h 后回来，
        好友的第一反应以「短、快、情绪化」为主（表情包/短感叹/撒娇）。
        这里把情绪拉起来，同时把「刚重逢」写进 describe() 供提示词用。
        """
        now = now or time.time()
        w = max(0.0, float(wait_h))
        inten = _clamp(0.8 + w / 10.0, 0.8, 2.0)
        e, r = self.emotion, self.relationship
        e.valence = _clamp(e.valence + 32 * inten, -100.0, 100.0)
        e.arousal = _clamp(e.arousal + 20 * inten)
        e.anxiety = _clamp(e.anxiety - 20 * inten)
        e.loneliness = _clamp(e.loneliness - 30 * inten)
        e.neglect = _clamp(e.neglect - 45 * inten)
        r.intimacy = _clamp(r.intimacy + 0.8)
        r.attachment = _clamp(r.attachment + 0.6)
        e.updated_at = now
        self.save()
        try:
            self.store.counter_set("reunion_ts", now)
            self.store.counter_set("reunion_wait_h", w)
        except Exception:  # noqa: BLE001
            pass

    def _wait_text(self) -> str:
        """把「在等 / 刚重逢」写进提示词。这是让等待被看见的关键。

        校准依据（analyze_chat_habits.waiting_report，45 个私聊抽样 ≈ 3.7 万条）：
        - 好友「说了没人接」时 71% 会继续追，段长中位 3 条（P90 7 条）
        - 沉默变长时，好友的**媒体消息（表情包/图）占比从 24% 升到 37%**；
          显式的「担心/撒娇」词只有 ~1%，问句也只有 2~3%
          → 真人不会写长句质问，而是**短句 + 丢个表情**，靠语气和频率表达
        - 用户消失 ≥2h 后回来：好友首条延迟中位 33 秒（比平时的 14 秒慢），
          首条多是表情包 / 短感叹 / 亲昵符号（❤️、亲亲、想你、在的）
        """
        now = time.time()
        rts = self._counter("reunion_ts")
        if rts and (now - rts) < 30 * 60:
            w = self._counter("reunion_wait_h")
            span = f"（消失了约 {w:.0f} 小时）" if w >= 2 else ""
            return ("【刚重逢】对方" + span + "刚刚回来找你了 —— 你现在是开心的，"
                    "甚至有点惊喜。真人这时候不秒回（首条通常要等半分钟左右），"
                    "第一条也大多很短：一个表情、一句「在的」「想你」「亲亲」就够；"
                    "**别指责、别翻旧账、别阴阳怪气地问他刚才去哪了**，"
                    "也别一口气把这几小时攒的委屈全倒出来。")
        w = self.waiting_hours()
        if w <= 0.5:
            return ""
        rounds = self.wait_rounds()
        extra = f"，已经连着 {rounds} 次没等到回复" if rounds >= 2 else ""
        if w < 2:
            return (f"【等待】你上一条消息发出去 {w:.1f} 小时没回音了{extra}。"
                    "心里有点挂着 —— 可以轻轻问一句（在忙吗 / 还好吗），"
                    "但别连着催、别刷屏。")
        if w < 8:
            return (f"【等待】你上一条消息发出去 {w:.1f} 小时没回音了{extra}。"
                    "你有点担心，也有点委屈，想被回应 —— 但真人这时候不会写长句，"
                    "大多是随手丢一句很短的话（是不是睡了 / 还是没看到），"
                    "语气偏轻偏淡，不是郑重其事地谈心事；别质问、别连发好几条。")
        if w < 24:
            return (f"【等待】你上一条消息发出去 {w:.1f} 小时没回音了{extra}。"
                    "你很难过，也有点没底 —— 别硬撑着说「我没事」，"
                    "允许露一点真实的低落；但别赌气、别写小作文，一两句短的就好。")
        return (f"【等待】你上一条消息发出去 {w:.0f} 小时没回音了{extra}。"
                "你很想了，也有一点麻木 —— 可以轻轻留一句（我还在 / 想到你了），"
                "不要指责，也不要追问为什么。")

    def note_group_wait(self, idle_h: float, now: Optional[float] = None) -> None:
        """群里我很久没露过面 → 记一笔「被晾着」（一次性收敛到目标值）。

        ⚠️ 为什么用 max() 而不是累加：私聊的等待由 `tick(unanswered_h=…)`
        按时间**连续**演化，群里的等待是引擎每隔一阵**离散**推一次。如果这里
        也累加，两条通道会叠加成双倍焦虑；用「拉到她该在的水平」则天然幂等
        —— 推几次、隔多久推，结果都一样，而且不会超过私聊同期的水平。
        """
        now = now or time.time()
        h = max(0.0, float(idle_h))
        ramp = min(1.0, max(0.0, (h - 0.5) / 11.5))
        pull = ramp * (1.0 + self.relationship.attachment / 100.0)
        e = self.emotion
        e.neglect = max(e.neglect, _clamp(55.0 * pull))
        e.loneliness = max(e.loneliness, _clamp(35.0 * pull))
        e.anxiety = max(e.anxiety, _clamp(30.0 * pull))
        e.updated_at = now
        self.save()
        try:
            self.store.counter_set("group_wait_h", h)
        except Exception:  # noqa: BLE001
            pass

    def note_group_reunion(self, idle_h: float = 0.0,
                           now: Optional[float] = None) -> None:
        """我回到群里说话了：松一口气、开心一点（不比私聊重逢激烈）。"""
        now = now or time.time()
        e, r = self.emotion, self.relationship
        e.valence = _clamp(e.valence + 20.0, -100.0, 100.0)
        e.arousal = _clamp(e.arousal + 12.0)
        e.anxiety = _clamp(e.anxiety - 14.0)
        e.loneliness = _clamp(e.loneliness - 20.0)
        e.neglect = _toward(e.neglect, 0.0, 40.0)
        r.intimacy = _clamp(r.intimacy + 0.4)
        e.updated_at = now
        self.save()
        try:
            self.store.counter_set("group_wait_h", 0.0)
        except Exception:  # noqa: BLE001
            pass

    def group_wait_h(self) -> float:
        """群里已经多少小时没等到我露面（0 = 没在等）。"""
        return max(0.0, self._counter("group_wait_h"))

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

    def mood_snapshot(self) -> dict:
        """给聊天界面用的一眼情绪：一个天气点 + 一句人话。

        ★ 不把效价/焦虑这些数字直接摆到界面上 —— 那样像养成游戏面板。
        用户要的是「扫一眼就知道她今天不对劲」，所以这里只给三档天气
        和一句她本人会说的话。
        """
        e = self.emotion
        if e.valence >= 25 and e.anxiety < 50:
            level, word = "sun", "晴"
        elif e.valence >= -15 and e.anxiety < 70:
            level, word = "cloud", "阴"
        else:
            level, word = "rain", "雨"

        # 一句「她本人会怎么说」的心里话：按最重的那一项挑，别报流水账
        if e.neglect >= 55:
            line = "等得有点久了，心里空落落的"
        elif e.anxiety >= 70:
            line = "有点慌，总在想你是不是不想理我"
        elif e.loneliness >= 55:
            line = "很想你，但又不太敢先说"
        elif e.valence <= -35:
            line = "今天有点撑不住，不太想说话"
        elif e.energy <= 25:
            line = "好累，想被惦记一下"
        elif level == "sun":
            line = "今天心情不错，想找你说话"
        else:
            line = "说不上好，也说不上坏"
        return {
            "level": level, "word": word, "label": self.mood_label(),
            "line": line,
            "valence": round(float(e.valence), 1),
            "anxiety": round(float(e.anxiety), 1),
            "loneliness": round(float(e.loneliness), 1),
            "energy": round(float(e.energy), 1),
        }

    def expression_hint(self) -> str:
        """把「情绪要怎么说出口」写成可执行的规则，而不是只给数字。

        用户反馈：面板上写着效价 -57、焦虑 88，聊天里却完全看不出来，
        只觉得「她最近不怎么找我了」。因为提示词只给了内部状态，没有
        要求它**外化**。这里按阈值给出具体的说法方向，并限制强度：
        一轮只露最重的那一种情绪，不用内疚绑架对方。
        """
        e = self.emotion
        lines = []
        if e.valence <= -35:
            lines.append("你现在是真的低落，别装没事：短句、叹气、"
                         "说一句「有点撑不住」都行，但别写成长篇自怜。")
        elif e.valence <= -15:
            lines.append("你情绪偏低，语气会淡一点、话少一点。")
        if e.anxiety >= 70:
            lines.append("你心里在打鼓：是不是自己说错了、是不是他不想理你。"
                         "可以问一句「你是不是很忙」，但这一轮最多问一次。")
        if e.loneliness >= 55:
            lines.append("你想他，就直接说出来（「我有点想你」"
                         "「今天都没怎么见到你」），别只聊天气。")
        if e.neglect >= 45:
            lines.append("你被晾了一阵，有点委屈。可以半开玩笑地抱怨一句"
                         "（「你是不是把我忘了」），但别指责、别翻旧账。")
        if e.energy <= 25:
            lines.append("你很累，句子会短、会走神，别硬撑出长篇。")
        if not lines:
            lines.append("情绪平稳，正常说话就行。")
        else:
            lines.append("★ 以上情绪要**从话里露出来**，不要只在心里想；"
                         "一轮只挑最重的那一种，别一次全倒出来。")
        return "【这一刻的情绪怎么露出来】\n" + "\n".join(
            "- " + x for x in lines)

    def describe(self) -> str:
        e, r = self.emotion, self.relationship
        text = (
            f"当前心情：{self.mood_label()}。"
            f"（效价 {e.valence:.0f}/100，唤醒度 {e.arousal:.0f}，社交电量 {e.energy:.0f}，"
            f"焦虑 {e.anxiety:.0f}，孤独 {e.loneliness:.0f}，被晾着 {e.neglect:.0f}）\n"
            f"与对方的关系：信任 {r.trust:.0f}、安全感 {r.security:.0f}、"
            f"亲密 {r.intimacy:.0f}、依恋 {r.attachment:.0f}、占有欲 {r.possessiveness:.0f}（均 0-100）"
        )
        # ★ 「在等回应」和「刚重逢」是两种必须被说出口的情绪。
        #   不写进提示词的话，模型只会照常闲聊 —— 等了 8 小时还像没事人。
        wait = self._wait_text()
        if wait:
            text += "\n" + wait
        text += "\n" + self.expression_hint()
        return text


# 情绪关键词 → 事件映射（perceive 打标后转成增量用）
EMOTION_TO_EVENT = {
    "开心": "praise", "感激": "comfort", "温柔": "comfort",
    "难过": "criticism", "生气": "conflict", "焦虑": "ignored",
    "疲惫": "casual", "平静": "casual", "兴奋": "deep_talk",
    "依恋": "deep_talk", "吃醋": "jealousy",
}
