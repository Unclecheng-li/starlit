"""六层抑制链。

难的不是「能主动发消息」，是「该不该发」。乱发比不发更伤关系。

① 免打扰     当前处于静默时段？
② 间隔       距上次主动发言 < min_gap？
③ 冷场计数   连续 N 次主动没得到回复？
④ 电量       社交电量低于阈值？
⑤ 有话可说   LLM 判断现在真有想说的吗？
⑥ 送出复核   用当前上下文重判，这条现在还成立吗？
⑦ 重复拦截   本地 n-gram 比对：这条是不是把刚说过的话又说一遍？

第 ⑥ 层来自 arXiv:2610.05159 ——「到期不等于授权发送」。
定时器触发只是"提议"，每条消息在真正送出前必须重新判断一次，
否则就会发出「面试加油！」而你昨天已经说面试取消了。

第 ⑦ 层来自实测翻车：自回归复读环 ——「中午那声我记着呢」一晚出现 6 次。
LLM 复核自己写的稿子时几乎看不出重复（它眼里每条都是"新的"），
所以这层用**本地硬比对**，不依赖模型自觉。
"""
from __future__ import annotations

import re
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from ..config import AutonomyConfig
from ..store import Store
from ..think import decide_initiative
from ..state import StateMachine
from ..memory import Memory
from ..llm import LLM

# format_recent 给每行加了「[今天 15:48] 」这样的时间前缀；
# 第⑦层做行解析时必须先把它剥掉，否则永远匹配不到自己说过的话。
_TIME_PREFIX = re.compile(r"^\s*\[[^\]]*\]\s*")
# 「自己说过的话」在历史里的 role 名（新增角色也写 assistant）
_BOT_ROLES = ("assistant", "小星", "星野")


@dataclass
class Decision:
    allowed: bool
    stage: str
    reason: str
    topic: str = ""
    kind: str = ""          # content / joy / view / miss / mood，仅第⑤层通过时有值

    def __str__(self) -> str:
        flag = "允许" if self.allowed else "拦截"
        extra = ""
        if self.kind:
            extra += f" | 类型：{self.kind}"
        if self.topic:
            extra += f" | 话题：{self.topic}"
        return f"[{flag}@{self.stage}] {self.reason}{extra}"


class Suppressor:
    def __init__(self, cfg: AutonomyConfig, store: Store, llm: LLM,
                 state: StateMachine, memory: Memory):
        self.cfg = cfg
        self.store = store
        self.llm = llm
        self.state = state
        self.memory = memory

    # ---------- 时间工具 ----------
    def in_quiet_hours(self, now: Optional[datetime] = None) -> bool:
        now = now or datetime.now()
        try:
            start_s, end_s = self.cfg.quiet_hours[0], self.cfg.quiet_hours[1]
        except (IndexError, TypeError):
            return False
        cur = now.hour * 60 + now.minute

        def to_min(s: str) -> int:
            h, m = s.split(":")
            return int(h) * 60 + int(m)

        start, end = to_min(start_s), to_min(end_s)
        if start <= end:
            return start <= cur < end
        # 跨天，如 23:30 ~ 08:30
        return cur >= start or cur < end

    # ---------- 主链 ----------
    async def check(
        self,
        *,
        last_spoke_ts: float,
        last_reply_ts: float,
        cold_streak: int,
        recent: List[str],
        hint: str = "",
        has_content: bool = False,
        content_hint: str = "",
        force_go: bool = False,
        force: bool = False,
    ) -> Decision:
        """
        `force_go=True` → 跳过第⑤层「有话可说」的 LLM 判断。

        什么时候该跳：**上线问候**这种「一定要发」的场景。
        实测它被这一层拦掉了 —— 模型给的理由是「刚问完对方香干口感，
        还没得到回应，此刻没有新的想说的内容」，于是上线问候永远发不出去。

        `force=True` → 连②间隔③冷场④电量都跳（仍保留①免打扰 ——
        深夜启动不该弹问候，那是作息保护）。实测事故：电量 11 低于
        阈值 30，用户明确要求的「每次上线必发一条」连续两次被拦。
        """
        now = time.time()

        # ① 免打扰（唯一不随 force 跳过的层）
        if self.in_quiet_hours():
            return Decision(False, "免打扰", "当前处于静默时段")

        # ★ 完全强制：上线问候专用通道（②~⑥ 全部跳过）
        if force:
            return Decision(True, "通过（强制）", "强制开口（上线问候）",
                            topic="", kind="miss")

        # ② 间隔（连续冷场时自动拉长，但**不是永久停**）
        gap_min = (now - last_spoke_ts) / 60.0 if last_spoke_ts else 9999.0
        need = self.cfg.min_gap_min
        if cold_streak >= self.cfg.cold_streak_limit:
            need = max(need, int(self.silence_minutes(cold_streak)))
        if gap_min < need:
            return Decision(False, "间隔",
                            f"距上次主动发言仅 {gap_min:.0f} 分钟（需 {need} 分钟"
                            + (f"，冷场 {cold_streak} 次已拉长" if cold_streak >= self.cfg.cold_streak_limit else "")
                            + "）")

        # ③ 冷场 —— 这里刻意**不再永久拦截**。
        # 原来 cold_streak >= limit+2 直接「暂时不再打扰」，而且冷场计数
        # 只在用户开口时才重置 → 效果是「她再也不会主动找我」，与预期相反。
        # 现在改成：拉长间隔（见 ②），静默期满后回来「关心一句」。
        checkin = cold_streak >= self.cfg.cold_streak_limit

        # ④ 电量
        if self.state.emotion.energy < self.cfg.energy_threshold:
            return Decision(
                False, "电量",
                f"社交电量 {self.state.emotion.energy:.0f} 低于阈值 {self.cfg.energy_threshold}",
            )

        # ⑤ 有话可说 —— 同时判定这次开口属于哪一类意图
        # force_go 时跳过（上线问候必须发）
        if force_go:
            return Decision(True, "通过（强制）", "强制开口（上线问候）",
                            topic="", kind="miss")

        state_text = self.state.describe()
        mem_text = self.memory.recall_text(
            " ".join(self.memory.top_interests(5)) or "最近的事", top_k=5
        )
        # 冷场回来后，第一句优先是「关心状态」而不是继续分享
        kind_hint = ""
        if checkin:
            kinds = self.cfg.checkin_kinds or ["miss"]
            want = kinds[cold_streak % len(kinds)]
            kind_hint = (
                f"\n\n【这一条的特殊要求】你已经连着 {cold_streak} 次主动开口，"
                "对方一次都没回。现在你静默了一段时间，是回来看看 ta 怎么了。\n"
                "所以这一句要：\n"
                "- 以**关心对方的状态**为主（是不是忙、是不是不舒服、是不是出事了），"
                "而不是继续讲自己刚才想讲的东西\n"
                "- 语气要自然，**不要质问**（别说「你怎么不理我」），"
                "也不要显得受伤或讨债\n"
                "- 可以带一点点不安，但别演成委屈\n"
                f"- 这次开口的类型偏向：{want}"
            )
        judge = await decide_initiative(
            self.llm, state_text, mem_text, recent,
            has_content=has_content and not checkin,
            content_hint=(content_hint or hint) + kind_hint,
        )
        if not judge.get("speak"):
            return Decision(False, "有话可说", str(judge.get("reason", "没什么想说的")))

        kind = str(judge.get("kind") or "miss")
        if kind == "none":
            return Decision(False, "有话可说", "模型选了 none")
        if checkin:
            kind = "miss"          # 冷场回来固定走「想起你 / 关心」这一类
            return Decision(True, "通过（冷场后关心）",
                            f"静默期满，回来关心一句（已冷场 {cold_streak} 次）",
                            topic=str(judge.get("topic", "")), kind=kind)

        return Decision(
            True, "通过", f"可以发送（{kind}）",
            topic=str(judge.get("topic", "")), kind=kind,
        )

    def silence_minutes(self, cold_streak: int) -> float:
        """冷场 N 次后，这次要静默多久才回来。

        **不是永久停，是越来越久**：静默时长随时冷场次数指数增长，但有上限。
        这样「你一天不理她」和「你三天不理她」的体感是不一样的。
        """
        if cold_streak < self.cfg.cold_streak_limit:
            return 0.0
        extra = cold_streak - self.cfg.cold_streak_limit
        v = self.cfg.silence_min * (self.cfg.silence_growth ** extra)
        return min(float(self.cfg.silence_max_min), v)

    # ---------- 第 ⑦ 层：本地重复拦截 ----------
    # 聊天里超高频的口语片段：这些片段撞上了不算复读（避免误杀正常聊天）
    _BENIGN_FRAGMENTS = {
        "哈哈哈哈", "我觉得吧", "怎么回事", "你怎么样了", "真的假的",
        "好的好的", "行吧行吧", "嗯嗯好的", "对对对对", "那没事了",
        "你不是说", "你上次说", "你刚才说", "我记得你", "我跟你说",
        "忽然想起", "突然想到", "我说真的", "那就这样", "我先去忙",
        "我先睡了", "你早点睡", "早点休息", "注意身体", "明天再说",
        "下次再说", "回头再说", "改天再聊", "后来怎么样", "怎么样了",
    }

    @staticmethod
    def _ngrams(text: str, n: int = 4) -> set:
        s = "".join((text or "").split())        # 去掉空白/换行再切
        return {s[i:i + n] for i in range(len(s) - n + 1)} if len(s) >= n else set()

    def _is_repeat(self, draft: str, recent: List[str]) -> Tuple[bool, str]:
        """和最近自己说过的话硬比对。命中返回 (True, 原因)。

        recent 是 "role: text" 格式；只和自己（assistant）的比。
        两条判据（任一命中即拦）：
          a) 4-gram 重合度 > 0.5 —— 整体就是同一句话的复读
          b) 草稿里出现「最近 6 条自己消息中 ≥5 字的连续片段」
             —— 换皮复读（开头结尾换了，中间还是那句）
             （片段判据用 5-gram 而不是 4-gram：四字口语太容易撞，
              「你不是说」「怎么回事」这种正常聊天不该被拦）
        """
        bot_texts: List[str] = []
        for line in recent or []:
            # ★ 容忍 format_recent 的时间前缀：调用方传进来的是
            #   `[今天 15:48] assistant: 文本`，而这里原来只认裸的
            #   `assistant:` 开头 → bot_texts 恒为空 → 这一层从未生效。
            s = _TIME_PREFIX.sub("", str(line or ""))
            role, sep, body = s.partition(":")
            if sep and body.strip() and role.strip() in _BOT_ROLES:
                bot_texts.append(body.strip())
        if not bot_texts or not draft:
            return False, ""

        draft_flat = draft.replace(" ", "")
        draft_grams = self._ngrams(draft)
        if not draft_grams:
            return False, ""

        # a) 整体复读：和最近 20 条里**任一条**的重合度
        for old in bot_texts[-20:]:
            old_grams = self._ngrams(old)
            if not old_grams:
                continue
            overlap = len(draft_grams & old_grams) / len(draft_grams)
            if overlap > 0.5:
                frag = draft[:24]
                return True, f"和刚说过的「{old[:24]}」重合度 {overlap:.0%}（复读）[{frag}]"

        # b) 换皮复读：草稿包含最近 6 条里出现过的 5 字连续片段
        for old in bot_texts[-6:]:
            if not old or len(old) < 5:
                continue
            for g in self._ngrams(old, 5):
                if g in self._BENIGN_FRAGMENTS:
                    continue
                if g in draft_flat:
                    return True, f"片段「{g}」刚在「{old[:20]}」里说过"

        return False, ""

    # ---------- 第 ⑥ 层：送出前复核 ----------
    async def revalidate(self, draft: str, recent: List[str], topic: str = "") -> Tuple[bool, str]:
        """草稿写完后、真正送出前的最后一道检查。"""
        # ⑦ 先做本地硬比对（零成本、不吃模型自觉）
        hit, why = self._is_repeat(draft, recent)
        if hit:
            return False, f"重复拦截：{why}"

        prompt = (
            "下面是一条你刚刚写好、准备主动发出的消息草稿。\n"
            "请结合最近的对话判断：这条现在发出去**是否明显有问题**？\n\n"
            f"最近的对话：\n{chr(10).join(recent[-6:]) if recent else '（无）'}\n\n"
            f"草稿：\n{draft}\n\n"
            '只输出 JSON：{"send": true/false, "reason": "一句话"}。\n'
            "★ 默认放行（send=true）。**只有**下面三种情况才 send=false：\n"
            "  1) 和最近对话里的内容明显重复（同一件事刚说过）；\n"
            "  2) 提到的事情已经明确过期、或时态明显不对（例如把还没发生的事当成已发生）；\n"
            "  3) 内容会伤害对方（嘲讽、指责、翻旧账）。\n"
            "⚠️ 「可能有点突兀」「话题跳了一下」「对方还没回上一句」都**不算**理由——"
            "真人主动找人的时候本来就经常突然想起一件别的事。"
        )
        try:
            res = await self.llm.chat_json(
                [{"role": "user", "content": prompt}], temperature=0.2, max_tokens=600
            )
            return bool(res.get("send")), str(res.get("reason", ""))
        except Exception as e:  # noqa: BLE001
            # ★ 复核失败要**放行**，不能「保守放弃」：模型偶尔输出非 JSON
            #   就会把一条本来没问题的主动消息静默丢掉（日志里这种
            #   「复核失败，保守放弃」出现过十几次，也是「她怎么不找我」的
            #   一个成因）。宁可偶尔发得略显突兀，也不要一声不吭。
            print(f"[suppress] 复核失败 → 放行：{e!r}")
            return True, "复核不可用，放行"
