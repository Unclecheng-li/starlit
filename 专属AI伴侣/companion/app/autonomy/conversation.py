"""对话连贯性：让聊天能持续下去，而不是一问一答就断。

## 为什么需要这个

原来的逻辑是「收到一条 → 回一条 → 结束」。等下一次，要等心跳（20 分钟到 48 小时）。
所以体感就是：我发一句，它回一句，然后就没声了。**这不是对话，是问答。**

真人的对话是这样的：
  - 你说一句，对方回三句，其中一句是追问
  - 你只发了半句就跑去忙了，对方过了一会儿又补一句「对了，刚才那个……」
  - 话题聊干了，对方自己起一个新话题
  - 但也不会没完没了 —— 连发几条没回应就自己收住

## 这里的做法

**活跃会话窗口**：用户最后一条消息之后 `active_window_min` 分钟内，
算「两个人还在聊」。窗口内它会在短暂停顿后自己判断要不要接着往下说；
窗口外才交给那套慢节奏的主动机制（心跳）。

**每一轮补话前都要过一遍判断**（`think.decide_followup`）：
有真实的补充/追问才说，只是「怕冷场」就不说。

**多层刹车，防止变成刷屏**（对比真实聊天记录后全面收紧）：
  1. 连发上限**按气泡计**：普通 3 条、深聊 6 条 —— 原来「轮」为单位，
     一轮拆 5 条，实际能刷出 40 条
  2. 无回应**阶梯退避**：第 1 次隔几十秒，第 2 次隔十几分钟，再往后停
  3. 用户来了新消息 → **在途草稿作废**（generation 代际检查）
  4. 对方收尾（晚安/去忙）→ 互道收尾后**不再追话**
  5. 同一话题追问限次（防查户口）、深夜更克制
"""
from __future__ import annotations

import asyncio
import random
import re
import time
from dataclasses import dataclass, field
from typing import Any, Callable, List, Optional

from ..act import Sender
from ..config import BehaviorConfig, ConversationConfig, QQConfig
from ..llm import LLM
from ..memory import Memory
from ..state import StateMachine
from ..store import Store
from ..think import decide_followup, express, extract_overused_terms
from .suppress import Suppressor

TICK_SECONDS = 5.0

# 收尾式话语：互道收尾后，这些话不再触发长回复
_CLOSING_RE = re.compile(
    r"(晚安|睡啦|睡了|先睡|拜拜|下次聊|回头聊|回见|明天聊|去忙|先忙|"
    r"忙去了|下线|断电|关机|上课去|上课啦|吃饭去|吃饭啦|走了哈|先走了)"
)


def is_closing_text(text: str) -> bool:
    """这句话是不是「收尾式」的（晚安/去忙/下线这类，短句才算）。"""
    t = (text or "").strip()
    if not t or len(t) > 20:
        return False
    return bool(_CLOSING_RE.search(t))


@dataclass
class ConvState:
    topic: str = ""
    last_user_ts: float = 0.0
    last_bot_ts: float = 0.0
    # 自用户最后一条消息以来，自己已经连着发了多少条（★按气泡计，不按轮）
    bot_turns_since_user: int = 0
    followups_this_topic: int = 0
    # 本话题已经追问过几次（防查户口）
    probes_this_topic: int = 0
    next_turn_at: float = 0.0
    quiet_turns: int = 0
    deep: bool = False           # 本轮是不是情绪深聊（放宽连发上限）
    # ★ 代际计数：用户每来一条新消息 +1。接话草稿生成期间代际变了
    # → 草稿作废。否则会出现「对着旧上下文写的话，插进新对话里」。
    generation: int = 0
    # ★ 刚互道过收尾（晚安/去忙）：不再追话，直到用户重新开话
    closed: bool = False
    # ★ 对方最近的响应时长样本（节奏镜像用）
    paces: List[float] = field(default_factory=list)
    # 上一个 tick 时是否在活跃窗口（检测「由真转假」的边沿写会话摘要）
    was_active: bool = False
    # ── 话题重启（数据驱动）────────────────────────────────
    # 全量数据：话题死在自己手里时，真人好友 59% 会重新开口找新话题
    #（中位 176 分钟）。以前窗口一过就彻底沉默，把找话题全推给对方。
    reopens: int = 0             # 本周期已重启几次
    next_reopen_at: float = 0.0   # 下一次重启的时间点（0 = 未排班）

    def last_activity(self) -> float:
        return max(self.last_user_ts, self.last_bot_ts)


class ConversationRunner:
    """在「活跃会话窗口」内，像真人一样把话接下去。"""

    def __init__(
        self,
        cfg: ConversationConfig,
        bcfg: BehaviorConfig,
        qq: QQConfig,
        store: Store,
        llm: LLM,
        state: StateMachine,
        memory: Memory,
        sender: Sender,
        suppressor: Suppressor,
        persona_loader: Callable[[str], str],
        sender_id: str = "",
        sender_name: str = "",
        trait_text: str = "",
        delay_scale: float = 1.0,
        presence_text: str = "",
    ):
        self.cfg = cfg
        self.bcfg = bcfg
        self.qq = qq
        self.store = store
        self.llm = llm
        self.state = state
        self.memory = memory
        self.sender = sender
        self.suppressor = suppressor
        self.load_persona = persona_loader
        self.sender_id = sender_id
        self.sender_name = sender_name
        self.trait_text = trait_text
        self.delay_scale = delay_scale
        self.presence_text = presence_text
        self.conv = ConvState()
        self._stop = asyncio.Event()
        self._lock = asyncio.Lock()
        self._last_block_reason = ""     # 去重：同一条拦截原因不重复刷日志

    # ---------- 外部通知 ----------
    def on_user_message(self, text: str = "", topic: str = "", deep: bool = False,
                        bump_generation: bool = True) -> None:
        """用户说话了：刷新会话，重置计数，安排下一次可能的接话。

        `deep=True` 表示这一轮是**情绪深聊**（对方在倾诉 / 需要安慰）——
        此时把连发上限放宽，因为「三轮就收住」在那种场景明显不够。

        ★ 同时做三件事：
        - 记录对方的响应时长（节奏镜像：她回话的快慢要往对方靠）
        - 代际 +1：所有还在途的接话草稿作废
        - 解除「刚互道收尾」状态（对方重新开话 = 新一段对话）

        bump_generation=False：只刷新会话状态、**不作废在途回复**。
        主管线用它在入口刷新状态，真正的代际 bump 推迟到「确定这批
        必定要开口」之后 —— 否则「只甩表情包不回话」的批次会白白
        顶掉上一批马上要发的回复（7 条文字被一张图吞掉，实测事故）。
        """
        now = time.time()
        if not deep and self.conv.last_bot_ts > 0:
            gap = now - self.conv.last_bot_ts
            # ★ 只收「即时节奏」样本（真人私聊响应中位 14s / P75 54s）。
            # 更久的间隔是「离开过」而不是「打字慢」—— 实测事故：
            # 隔 21 分钟回来的消息把 pace 样本污染成 1297s，节奏镜像
            # 据此把回复拖了整整 10 分钟（sleep 上限 600s），用户体感
            # 「发消息不回」。久别重逢时真人也是正常速度回话的。
            if 1.0 < gap < 120.0:
                self.conv.paces.append(gap)
                del self.conv.paces[:-6]      # 只留最近 6 个样本
        self.conv.last_user_ts = now
        self.conv.bot_turns_since_user = 0
        self.conv.followups_this_topic = 0
        # ★ probes_this_topic 故意**不重置**：追问配额按「话题」计，
        # 不是按「用户每说一句」计 —— 否则对方连发几批，每批都送一次
        # 追问配额，攒出一串查户口式连环问（实测四连问）。话题随
        # 会话结束（_write_session_summary）自然重置。
        self.conv.quiet_turns = 0
        self.conv.deep = bool(deep)
        self.conv.closed = False
        self.conv.reopens = 0           # 对方开口 = 新一轮，重启配额重置
        self.conv.next_reopen_at = 0.0
        if topic:
            self.conv.topic = topic
        if bump_generation:
            self.conv.generation += 1    # ★ 在途草稿作废
        self.conv.next_turn_at = now + self._next_delay()

    def on_bot_message(self, count_as_turn: bool = True, bubbles: int = 1) -> None:
        """自己刚发完话。`bubbles` 是实际发出的气泡条数（连发上限按它算）。"""
        now = time.time()
        self.conv.last_bot_ts = now
        if count_as_turn:
            self.conv.bot_turns_since_user += max(1, int(bubbles))
        self.conv.next_turn_at = now + self._next_delay()

    def on_close(self) -> None:
        """对方收尾了这次对话（晚安/去忙/下线）。互道收尾后不再追话。"""
        self.conv.closed = True
        # 下次就算要接话，也推到活跃窗口之外（事实上就是停）
        self.conv.next_turn_at = time.time() + self.cfg.active_window_min * 2 * 60

    def in_close(self) -> bool:
        return self.conv.closed

    def rearm_close(self) -> None:
        """收尾后又回了一句收尾话（互道晚安循环）：重新挂上停话状态。"""
        self.on_close()

    def partner_pace(self) -> float:
        """对方最近的典型响应时长（中位数，秒）。没有样本时为 0。"""
        p = sorted(self.conv.paces)
        if not p:
            return 0.0
        return p[len(p) // 2]

    def in_active_window(self) -> bool:
        if not self.conv.last_activity():
            return False
        return (time.time() - self.conv.last_activity()) < self.cfg.active_window_min * 60

    def _next_delay(self) -> float:
        """距下一次考虑接话的间隔。

        ★ 阶梯退避：用户刚说完 → followup_delay_sec（正常接话节奏）；
        之后每补一次还没等到回音，间隔跳一档（followup_backoff_sec）；
        表耗尽就事实上停掉，等用户先开口。
        原来是每次都固定 25~150 秒 —— 对方不理也一直小步试探，就是刷屏。
        """
        n = self.conv.followups_this_topic
        if n <= 0:
            lo, hi = (list(self.cfg.followup_delay_sec) + [25, 150])[:2]
            return random.uniform(float(lo), float(hi))
        backoff = self.cfg.followup_backoff_sec or []
        if n > len(backoff):
            return 30 * 86400.0        # 表耗尽：停，等用户先开口
        lo, hi = (list(backoff[n - 1]) + [30, 120])[:2]
        return random.uniform(float(lo), float(hi))

    # ---------- 主循环 ----------
    async def run(self) -> None:
        if not self.cfg.enabled:
            print("[conv] 已禁用")
            return
        print(f"[conv] 启动：活跃窗口 {self.cfg.active_window_min} 分钟"
              f"，补话间隔 {self.cfg.followup_delay_sec[0]}~{self.cfg.followup_delay_sec[1]} 秒"
              f"，连发上限 {self.cfg.max_burst_bubbles} 条/深聊 {self.cfg.deep_max_burst_bubbles} 条（按气泡计）"
              f"，退避 {self.cfg.followup_backoff_sec}")
        while not self._stop.is_set():
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=TICK_SECONDS)
                break
            except asyncio.TimeoutError:
                pass
            try:
                await self._tick()
            except Exception as e:  # noqa: BLE001
                print(f"[conv] 出错：{e!r}")

    def stop(self) -> None:
        self._stop.set()

    async def _tick(self) -> None:
        async with self._lock:
            now = time.time()
            active = self.in_active_window()
            # 「由真转假」的边沿：一段对话刚结束 → 写一条会话摘要。
            # 下次开话时注入给表达通道，解决「跨会话身份断裂」：
            # 新开一段对话时它还记得上一段聊到哪了。
            if self.conv.was_active and not active:
                self._write_session_summary()
                self._schedule_reopen(now)
            self.conv.was_active = active
            if not active:
                # ★ 话题重启：窗口外不只有「沉默」一条路。
                # 话题死在我手里、配额没用完、到点了 → 也允许开口。
                # 真人是「双方都会找话题」的：全量统计里好友在话题
                # 聊死之后 59% 会自己再开口（中位等 176 分钟）——
                # 以前这里一刀切 return，把找话题全推给了对方。
                if not self._reopen_due(now):
                    return
                await self._try_followup(reopen=True)
                return
            if now < self.conv.next_turn_at:
                return
            await self._try_followup()

    def _topic_dead_on_bot(self) -> bool:
        """话题是否死在我手里：我发了话、对方一直没接。"""
        c = self.conv
        return (c.bot_turns_since_user > 0 and c.last_bot_ts > c.last_user_ts)

    def _schedule_reopen(self, now: float) -> None:
        """活跃窗口刚过期且话题死在我手里 → 排一次「重新开口」的闹钟。

        间隔从 reopen_delay_sec 抽（真人最快一批 P5≈19 分钟，
        参考最快 10% 的 15~25 分钟区间压的下限）。
        """
        c = self.conv
        if c.next_reopen_at > 0 or c.reopens >= self.cfg.max_reopens:
            return
        if not self._topic_dead_on_bot():
            return                      # 话题死在对方手里 → 该对方找话（数据：对照仅 28%）
        lo, hi = (list(self.cfg.reopen_delay_sec) + [1200, 5400])[:2]
        c.next_reopen_at = c.last_bot_ts + random.uniform(float(lo), float(hi))

    def _reopen_due(self, now: float) -> bool:
        c = self.conv
        if c.reopens >= self.cfg.max_reopens or c.next_reopen_at <= 0:
            return False
        if not self._topic_dead_on_bot():
            return False                # 对方后来又开口过 → 正常流程接管
        return now >= c.next_reopen_at

    def _write_session_summary(self) -> None:
        """一段活跃会话结束了，把要点落一条摘要事件。"""
        turns = self.store.recent_turns(6)
        if not turns:
            return
        last_user = next((t["text"] for t in reversed(turns) if t["role"] == "user"), "")
        last_bot = next((t["text"] for t in reversed(turns) if t["role"] == "assistant"), "")
        topic = self.conv.topic or "闲聊"
        parts = [f"上次聊到：{topic}"]
        if last_user:
            parts.append(f"对方最后说：{last_user[:60]}")
        if last_bot:
            parts.append(f"我最后说：{last_bot[:60]}")
        self.store.add_event("；".join(parts), kind="summary")
        self.conv.topic = ""          # 摘要已落盘，话题归零等新会话
        self.conv.probes_this_topic = 0   # 新会话 → 追问配额重新发

    # ---------- 单次接话 ----------
    def block_reason(self, reopen: bool = False) -> str:
        """返回不能接话的原因；空字符串表示可以。

        reopen=True：话题重启模式 —— 窗口已过/连发上限/话题上限这些
        「追话类」限制不再适用（重启本来就是在窗口外说一句**新的**），
        但收尾、深夜、电量这些**硬约束**照拦不误。
        """
        c = self.conv
        if c.closed:
            return "刚互道过收尾，等对方先开口"
        if not reopen:
            if not self.in_active_window():
                return "会话窗口已过"
            # 连发上限按气泡计（普通 5 / 深聊 9），防「一轮拆 5 条、刷出 40 条」
            cap_bubbles = (self.cfg.deep_max_burst_bubbles if c.deep
                           else self.cfg.max_burst_bubbles)
            cap_follow = (self.cfg.deep_max_followups if c.deep
                          else self.cfg.max_followups_per_topic)
            if c.bot_turns_since_user >= cap_bubbles:
                return f"已连发 {c.bot_turns_since_user} 条没等到回复，收住（上限 {cap_bubbles}）"
            if c.followups_this_topic >= cap_follow:
                return f"这个话题已补 {c.followups_this_topic} 次，够了（上限 {cap_follow}）"
        if self.suppressor.in_quiet_hours():
            if c.quiet_turns >= self.cfg.quiet_hours_max_turns:
                return "深夜，已说过一条，不再补"
        if self.state.emotion.energy < self.cfg.energy_threshold:
            return f"社交电量 {self.state.emotion.energy:.0f} 太低"
        return ""

    async def _try_followup(self, force_kind: Optional[str] = None,
                           reopen: bool = False) -> Optional[str]:
        # ★ 代际捕获：这个数字变了，说明草稿生成期间对方又说话了，
        # 上下文已旧 → 后面所有成果作废（对着旧上下文写的话，插进新对话里最吓人）
        gen = self.conv.generation

        reason = self.block_reason(reopen=True) if reopen else (
            self.block_reason() if not force_kind else "")
        if reason:
            # 只在「原因变了」的时候打一次 —— 否则卡住时会每 60 秒刷一行，
            # 把日志淹掉（实测被「社交电量 0 太低」刷了几十行）。
            if reason != self._last_block_reason:
                self._last_block_reason = reason
                print(f"[conv] 不接话：{reason}")
            # 把下次时间推远，避免每 5 秒空转判断一次
            self.conv.next_turn_at = time.time() + 60
            return None
        self._last_block_reason = ""

        recent = [f"{t['role']}: {t['text']}" for t in self.store.recent_turns(10)]
        state_text = self.state.describe()

        if force_kind or reopen:
            # 话题重启固定走 pivot（起话头）—— 追问/补充类在这里没有意义：
            # 对方早就没接话了，追旧话只会像自言自语。真人重启的方式
            # 是想起一件**新的**事随口说（38% 靠甩分享，问句只占 2%）
            plan: dict[str, Any] = {"speak": True,
                                    "kind": force_kind or "pivot", "topic": ""}
        else:
            plan = await decide_followup(
                self.llm,
                state_text=state_text,
                recent=recent,
                consecutive_bot_turns=self.conv.bot_turns_since_user + 1,
                topic=self.conv.topic,
            )
        if not plan.get("speak"):
            print(f"[conv] 判断为不说：{plan.get('reason', '')}")
            self.conv.next_turn_at = time.time() + self._next_delay()
            return None

        kind = str(plan.get("kind") or "more")
        # 同一话题追问限次：probe 配额用完就降级成「补充」，不再问问题。
        # 防的是查户口式连环追问（真实聊天记录里对方被问三连会明显不想接）。
        if kind == "probe" and self.conv.probes_this_topic >= self.cfg.max_probes_per_topic:
            kind = "more"
        topic = str(plan.get("topic") or self.conv.topic)

        persona = self.load_persona("persona.md")
        world = self.load_persona("world.md")
        boundaries = self.load_persona("boundaries.md")
        memory_text = self.memory.recall_text(topic or " ".join(recent[-2:]), top_k=4)

        # 禁用词：自己最近说多了的词，这轮别再碰（防复读环的硬约束）
        turns = self.store.recent_turns(12)
        avoid = extract_overused_terms(
            [t["text"] for t in turns if t["role"] == "assistant"],
            [t["text"] for t in turns if t["role"] == "user"],
        )

        # 会话恢复提示：话题重启时尤其重要 —— 知道上次聊到哪，
        # 才能做到「说一件新的」而不是把旧话捡起来再嚼一遍
        resume_hint = ""
        now_ts = time.time()
        for ev in self.store.recent_events(30):
            if ev.get("kind") == "summary" and now_ts - float(ev.get("ts") or 0) < 7 * 86400:
                resume_hint = str(ev.get("text") or "")[:200]
                break

        draft = await express(
            self.llm, persona, boundaries, state_text, memory_text,
            recent, user_text="", analysis=None,
            extra_hint="", proactive=True,
            share_kind=kind, world=world,
            profile_text=self.memory.profile_text(),   # 接话时也要记得对方
            arousal=self.state.emotion.arousal,
            valence=self.state.emotion.valence,
            bubble_mode=True,                          # ★ 气泡协议：输出多条短气泡
            avoid_terms=avoid or None,
            resume_hint=resume_hint,
            self_facts_text=self.memory.self_facts_text(),
            trait_text=self.trait_text,
            presence_text=self.presence_text,
        )
        if gen != self.conv.generation:
            return None                                # 表达期间对方插话，草稿作废

        # 气泡列表 vs 纯文本（解析失败会回退纯文本协议）
        if isinstance(draft, list):
            bubbles = [b for b in draft if b]
            if not bubbles:
                self.conv.next_turn_at = time.time() + self._next_delay()
                return None
            draft_text = "\n".join(bubbles)
        else:
            bubbles = []
            draft_text = draft
        if not draft_text or "[NO_MESSAGE]" in draft_text:
            self.conv.next_turn_at = time.time() + self._next_delay()
            return None

        # 送出前复核（和第⑥层同一个思路：写了不等于该发）
        ok, why = await self.suppressor.revalidate(draft_text, recent, topic)
        if not ok:
            print(f"[conv] 复核拦下：{why}")
            self.conv.next_turn_at = time.time() + self._next_delay()
            return None
        if gen != self.conv.generation:
            return None                                # 复核期间对方插话，作废

        # 发送中途对方插话 → 停发剩余气泡（对齐主管线的代际中止）
        def _stale() -> bool:
            return gen != self.conv.generation

        send_kwargs = {"user_id": self.qq.owner_id, "abort_check": _stale,
                       "delay_scale": self.delay_scale}
        if self.sender_id or self.sender_name:
            send_kwargs["sender_id"] = self.sender_id
            send_kwargs["sender_name"] = self.sender_name
        if bubbles:
            sent = await self.sender.reply_bubbles(bubbles, **send_kwargs)
        else:
            sent = await self.sender.reply(draft_text, **send_kwargs)
        if sent == 0 and _stale():
            return None                                 # 刚进锁就被中止，什么都没发出去

        self.store.add_turn("assistant", draft_text[:400])
        label = "话题重启" if reopen else f"接话[{kind}]"
        self.store.add_event(f"{label}：{draft_text[:70]}", kind="conversation")
        if self.suppressor.in_quiet_hours():
            self.conv.quiet_turns += 1
        if kind == "probe":
            self.conv.probes_this_topic += 1
        self.conv.followups_this_topic += 1
        if reopen:
            # ★ 话题重启的记账：这一句是一个**新话题**的开场 ——
            #  - 计一次重启配额（max_reopens 用完就真的安静等对方）
            #  - 新话题 = 新一轮：补话/追问配额重置（新话题里允许
            #    正常接话，旧话题的死亡状态不背过来）
            #  - 闹钟清零（下次话题再死时由边沿重新排班）
            #  - 写 last_spoke_ts：心跳的「距上次主动开口」以此为准，
            #    不写的话心跳可能在重启后几分钟又插一句（两个模块各说各的）
            self.conv.reopens += 1
            self.conv.next_reopen_at = 0.0
            self.conv.followups_this_topic = 0
            self.conv.probes_this_topic = 0
            try:
                self.store.counter_set("last_spoke_ts", time.time())
            except Exception:  # noqa: BLE001
                pass
        # 连发上限按气泡计：发 3 条就是 3，不是 1
        self.on_bot_message(count_as_turn=True, bubbles=max(1, sent))
        print(f"[conv] {label}：{draft_text[:50]}")
        return draft_text
