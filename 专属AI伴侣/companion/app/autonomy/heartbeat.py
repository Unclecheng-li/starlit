"""心跳调度。

三个要点：
1. **不规则拟人节奏**（ProactiveRhythm）：不再用固定间隔，改成
   近 / 常 / 远 三档混合分布，并受孤独度、焦虑、社交电量影响。
   有时候 20 分钟后就冒头，有时候一整天不出现。
2. **这一轮可能选择不开口**：skip_probability 概率下顺延一个周期。
3. **到期不等于授权发送**：每次醒来先过六层抑制链，
   还要判断「这次想说什么」（decide_initiative），草稿写完再过复核。
"""
from __future__ import annotations

import asyncio
import random
import time
from datetime import datetime
from typing import List, Optional

from ..act import Sender
from ..channel.napcat import NapCatChannel
from ..config import AutonomyConfig, BehaviorConfig, QQConfig
from ..llm import LLM
from ..memory import Memory
from ..state import StateMachine
from ..store import Store
from ..think import (decide_initiative, express, format_recent,
                     format_time_context)
from .digest import Digest, ShareItem, share_card
from .suppress import Decision, Suppressor


def fmt_minutes(m: float) -> str:
    if m < 60:
        return f"{m:.0f} 分钟"
    if m < 60 * 24:
        return f"{m / 60:.1f} 小时"
    return f"{m / 1440:.1f} 天"


class ProactiveRhythm:
    """决定「下一次大概什么时候来找你」。

    真人的主动是不规则的 —— 固定间隔一眼就假。这里用**四档混合**：

      马上 (1 分钟 ~ 8 分钟)   —— 就是现在忽然想起你，立刻冒一句
      近   (20 分钟 ~ 2 小时)  —— 刚聊完意犹未尽
      常   (2 ~ 8 小时)        —— 日常节奏
      远   (12 ~ 48 小时)      —— 忙、累，或者就是没话说

    「马上」这一档是关键：没有它，最早也要等 20 分钟，
    体感就不像「随时可能来一句」，而像「定时任务」。
    权重上给得不低（默认 0.30），保证常有「刚分开就又想说话」的时候。

    再叠加情绪影响：越孤独 / 越焦虑，越容易往早的档偏；
    社交电量越低，越容易往「远」偏。
    最后还有 skip_probability 的「这一轮先不开口」——不是取消，是顺延。
    """

    def __init__(self, cfg: AutonomyConfig):
        self.cfg = cfg

    def _bands(self) -> List[List[int]]:
        """四档区间。兼容只有三档的旧配置。"""
        w = list(self.cfg.rhythm_weights or [])
        if len(w) >= 4:
            return [self.cfg.rhythm_instant, self.cfg.rhythm_near,
                    self.cfg.rhythm_normal, self.cfg.rhythm_long]
        # 旧的三档配置：把「马上」折进 near（取 near 的下界当最早）
        return [self.cfg.rhythm_near, self.cfg.rhythm_near,
                self.cfg.rhythm_normal, self.cfg.rhythm_long]

    def _weights(self, emotion, relationship) -> List[float]:
        if not self.cfg.rhythm_weights:
            return []
        w = [max(0.0, float(x)) for x in list(self.cfg.rhythm_weights)[:4]]
        while len(w) < 4:
            w.append(0.0)
        k = max(0.0, min(1.0, self.cfg.state_influence))

        lonely = emotion.loneliness / 100.0
        anxiety = emotion.anxiety / 100.0
        energy = emotion.energy / 100.0

        # 想找人 → 往最早的两档加
        near = k * (0.60 * lonely + 0.40 * anxiety)
        w[0] += near * 0.55          # 孤独焦虑时更容易「立刻就想说」
        w[1] += near * 0.45
        # 想缩着 → 往最晚那档加
        w[3] += k * max(0.0, 0.60 - energy) * 1.8

        w = [max(0.02, x) for x in w]
        s = sum(w)
        return [x / s for x in w]

    def next_delay_minutes(self, emotion, relationship) -> float:
        w = self._weights(emotion, relationship)
        if not w:   # 向后兼容：没配 weights 就用旧的固定间隔
            base = self.cfg.base_interval_min + random.uniform(
                -self.cfg.jitter_min, self.cfg.jitter_min
            )
            minutes = max(15.0, base)
            return self._cap(minutes)

        bands = self._bands()
        idx = random.choices([0, 1, 2, 3], weights=w, k=1)[0]
        minutes = random.uniform(float(bands[idx][0]), float(bands[idx][1]))

        # 「这一轮先不开口」：顺延一个周期，而不是彻底取消
        if random.random() < max(0.0, min(0.9, self.cfg.skip_probability)):
            j = random.choices([0, 1, 2, 3], weights=w, k=1)[0]
            minutes += random.uniform(float(bands[j][0]), float(bands[j][1]))

        return self._cap(max(1.0, minutes))

    def _cap(self, minutes: float) -> float:
        """不能因为抽到「远」档就一整天不出现 —— 热情派生的硬上限。"""
        cap = float(getattr(self.cfg, "max_gap_min", 0) or 0)
        if cap > 0:
            return min(minutes, cap)
        return minutes


class Heartbeat:
    def __init__(
        self,
        cfg: AutonomyConfig,
        qq: QQConfig,
        store: Store,
        llm: LLM,
        state: StateMachine,
        memory: Memory,
        suppressor: Suppressor,
        sender: Sender,
        digest: Digest,
        persona_loader,
        sender_id: str = "",
        sender_name: str = "",
        trait_text: str = "",
        delay_scale: float = 1.0,
        presence_text: str = "",
        schedule=None,
    ):
        self.cfg = cfg
        self.qq = qq
        self.store = store
        self.llm = llm
        self.state = state
        self.memory = memory
        self.suppressor = suppressor
        self.sender = sender
        self.digest = digest
        self.load_persona = persona_loader
        self.sender_id = sender_id
        self.sender_name = sender_name
        self.trait_text = trait_text
        self.delay_scale = delay_scale
        self.presence_text = presence_text
        # ★ 角色自己的作息：睡着时**不主动开口**（但对方来找她，她照样回）。
        #   以前所有角色共用一份全局 quiet_hours，于是「一到点大家集体睡」。
        self.schedule = schedule
        self._stop = asyncio.Event()
        self._replan = asyncio.Event()
        self.rhythm = ProactiveRhythm(cfg)

    def replan(self) -> None:
        """配置变了（热情调整）：打断当前等待，立刻按新节奏重排。"""
        self._replan.set()

    # ---------- 计数器 ----------
    @property
    def last_spoke_ts(self) -> float:
        return self.store.counter_get("last_spoke_ts", 0.0)

    @property
    def last_reply_ts(self) -> float:
        return self.store.counter_get("last_reply_ts", 0.0)

    def _cold_streak(self) -> int:
        return int(self.store.counter_get("cold_streak", 0.0))

    def _bump_cold(self) -> None:
        self.store.counter_set("cold_streak", self._cold_streak() + 1)

    def _reset_cold(self) -> None:
        self.store.counter_set("cold_streak", 0.0)

    def on_user_message(self) -> None:
        """收到用户消息时调用：重置冷场计数。"""
        self.store.counter_set("last_reply_ts", time.time())
        if self._cold_streak():
            self._reset_cold()

    def _today_count(self) -> float:
        return self.store.counter_get(f"proactive_{datetime.now():%Y-%m-%d}", 0.0)

    def _bump_today(self) -> None:
        k = f"proactive_{datetime.now():%Y-%m-%d}"
        self.store.counter_set(k, self.store.counter_get(k) + 1)

    # ---------- 主循环 ----------
    async def run(self) -> None:
        if not self.cfg.enabled:
            print("[heartbeat] 已禁用")
            return
        bands = (f"马上 {self.cfg.rhythm_instant[0]}~{self.cfg.rhythm_instant[1]} 分钟 / "
                 f"近 {self.cfg.rhythm_near[0]}~{self.cfg.rhythm_near[1]} 分钟 / "
                 f"常 {self.cfg.rhythm_normal[0]}~{self.cfg.rhythm_normal[1]} 分钟 / "
                 f"远 {self.cfg.rhythm_long[0]}~{self.cfg.rhythm_long[1]} 分钟")
        print(f"[heartbeat] 启动，拟人节奏：{bands}")
        print(f"[heartbeat] 权重 {list(self.cfg.rhythm_weights)}"
              f"，顺延概率 {self.cfg.skip_probability:.0%}"
              f"，情绪影响 {self.cfg.state_influence}")

        # 冷启动：从没主动说过话时，第一次安排得近一点，
        # 否则一旦抽到「远」档（12~48 小时），体感就是「它从来不会主动找我」。
        first_contact = self.last_spoke_ts <= 0 and self.cfg.first_contact_max_min > 0

        while not self._stop.is_set():
            if first_contact:
                minutes = random.uniform(5.0, float(self.cfg.first_contact_max_min))
                cap = float(getattr(self.cfg, "max_gap_min", 0) or 0)
                if cap > 0:
                    minutes = min(minutes, cap)
                first_contact = False
                print(f"[heartbeat] 冷启动：还没主动说过话，"
                      f"首次安排在 {fmt_minutes(minutes)} 后")
            else:
                minutes = self.rhythm.next_delay_minutes(
                    self.state.emotion, self.state.relationship
                )

            # ★ 角色自己的作息：睡着的人不该被抽中主动开口。
            #   把排期直接推到「她起床之后 + 一点点」—— 而不是每一分钟醒一次
            #   然后被挡掉（那只会刷日志、还容易抽到「远」档睡过头）。
            if self.schedule is not None:
                left = self.schedule.minutes_until_wake()
                if left > 0:
                    pushed = left + random.uniform(1.0, 12.0)
                    if pushed > minutes:
                        print(f"[heartbeat] {self.sender_name or '她'} 正在睡"
                              f"（还有 {left:.0f} 分钟到起床点），排期顺延到起床后")
                        minutes = pushed

            # 把「下次大概什么时候」存下来，方便随时查（inspect / /next）
            self.store.counter_set("next_proactive_at", time.time() + minutes * 60)

            nxt = datetime.fromtimestamp(time.time() + minutes * 60).strftime("%H:%M")
            print(f"[heartbeat] 下次约 {fmt_minutes(minutes)} 后（{nxt}）"
                  f" ｜ 孤独 {self.state.emotion.loneliness:.0f}"
                  f" 焦虑 {self.state.emotion.anxiety:.0f}"
                  f" 电量 {self.state.emotion.energy:.0f}")
            try:
                interrupted = await self._sleep_or_interrupt(minutes * 60)
            except asyncio.CancelledError:
                raise
            if self._stop.is_set():
                break  # 被要求停止
            if interrupted:
                # replan：热情参数改过了，不唤醒、直接按新配置重排
                continue
            try:
                await self._wake()
            except Exception as e:  # noqa: BLE001
                print(f"[heartbeat] 本轮出错：{e!r}")

    async def _sleep_or_interrupt(self, timeout: float) -> bool:
        """睡到 timeout，或在 stop / replan 时提前醒来。

        返回 True 表示被打断（replan），False 表示正常睡满。
        """
        stop_wait = asyncio.ensure_future(self._stop.wait())
        replan_wait = asyncio.ensure_future(self._replan.wait())
        try:
            done, pending = await asyncio.wait(
                {stop_wait, replan_wait}, timeout=timeout,
                return_when=asyncio.FIRST_COMPLETED)
            for task in pending:
                task.cancel()
            if replan_wait in done and not stop_wait in done:
                self._replan.clear()
                return True
            return False
        finally:
            for task in (stop_wait, replan_wait):
                if not task.done():
                    task.cancel()

    # ---------- 对外查询 ----------
    def next_at(self) -> float:
        return self.store.counter_get("next_proactive_at", 0.0)

    def next_desc(self) -> str:
        t = self.next_at()
        if not t:
            return "未排期（心跳可能没在跑）"
        left = (t - time.time()) / 60.0
        when = datetime.fromtimestamp(t).strftime("%m-%d %H:%M")
        if left <= 0:
            return f"已到点（{when}），下一轮 tick 就会判断是否开口"
        return f"{fmt_minutes(left)} 后（{when}）"

    def stop(self) -> None:
        self._stop.set()

    async def _wake(self) -> None:
        # 推进状态：静默时段算休息，电量恢复
        resting = self.suppressor.in_quiet_hours()
        gap_h = (time.time() - self.last_reply_ts) / 3600.0 if self.last_reply_ts else None
        # ★ 把「我发出去的消息多久没人回」交给情绪状态机 —— 等得越久，
        #   越担心/沮丧/难过、越藏不住想被回应的需求感（describe 会写出来）。
        self.state.tick(last_interaction_ago_h=gap_h, resting=resting,
                        unanswered_h=self.state.waiting_hours())

        # 顺带跑一次自主浏览（内部自带频率限制）
        share: Optional[ShareItem] = None
        try:
            share = await self.digest.run_once()
        except Exception as e:  # noqa: BLE001
            print(f"[digest] 出错：{e!r}")

        decision = await self.poke_once(share=share)
        print(f"[heartbeat] {decision}")

    # ---------- 单次尝试 ----------
    async def poke_once(
        self,
        force: bool = False,
        share: Optional[ShareItem] = None,
        kind: Optional[str] = None,
        force_go: bool = False,
    ) -> Decision:
        if not force and self._today_count() >= self.cfg.daily_max:
            return Decision(False, "配额", f"今日主动已达上限 {self.cfg.daily_max} 次")

        turns = self.store.recent_turns(12)
        recent = format_recent(turns)
        time_text = format_time_context(turns)
        content_hint = ""
        if share:
            content_hint = f"{share.text}\n链接：{share.url}\n（和「{share.topic}」有关）"
            # 终审给的「值得聊的点」—— 让分享像真人随口聊起，
            # 而不是把搜索摘要原文甩出去（实测那种一眼广告）
            angle = getattr(share, "angle", "") or ""
            if angle:
                content_hint += f"\n值得聊的点：{angle}"

        decision = await self.suppressor.check(
            last_spoke_ts=self.last_spoke_ts,
            last_reply_ts=self.last_reply_ts,
            cold_streak=self._cold_streak(),
            recent=recent,
            has_content=bool(share),
            content_hint=content_hint,
            force_go=force_go,
            force=force,
        )
        if not decision.allowed:
            return decision

        share_kind = kind or decision.kind or "miss"

        # 生成草稿
        persona = self.load_persona("persona.md")
        world = self.load_persona("world.md")
        boundaries = self.load_persona("boundaries.md")
        state_text = self.state.describe()
        mem_query = decision.topic or " ".join(self.memory.top_interests(4)) or "最近"
        memory_text = self.memory.recall_text(mem_query, top_k=5)

        draft = await express(
            self.llm, persona, boundaries, state_text, memory_text,
            recent, user_text="", analysis=None,
            extra_hint=content_hint, proactive=True,
            share_kind=share_kind, world=world,
            time_text=time_text,
            schedule_text=(self.schedule.scene_text()
                           if self.schedule is not None else ""),
            profile_text=self.memory.profile_text(),   # 主动开口也要问对方的事
            arousal=self.state.emotion.arousal,
            valence=self.state.emotion.valence,
            trait_text=self.trait_text,
            presence_text=self.presence_text,
        )
        if not draft or "[NO_MESSAGE]" in draft:
            return Decision(False, "有话可说", "模型判断没什么想说的", kind=share_kind)

        # 第 ⑥ 层：送出前复核（强制开口时跳过 —— 它也会过度保守）
        if not force_go:
            ok, why = await self.suppressor.revalidate(draft, recent, decision.topic)
            if not ok:
                return Decision(False, "送出复核", why, kind=share_kind)

        send_kwargs = {"user_id": self.qq.owner_id,
                       "delay_scale": self.delay_scale}
        if self.sender_id or self.sender_name:
            send_kwargs["sender_id"] = self.sender_id
            send_kwargs["sender_name"] = self.sender_name
        # ★ 搜到的内容用真人的「甩分享」发出去（一张卡片），而不是把搜索
        #   摘要原文当正文念一遍。实测真人重启话题的第一手段就是甩分享
        #   （占 38%，问句只占 2%）。卡片是**附在文字气泡之后**的一条，
        #   文字仍然写进 transcript，所以重开窗口也看得到聊了什么。
        if share:
            card = share_card(share)
            if card:
                send_kwargs["card"] = card
        await self.sender.reply(draft, **send_kwargs)
        self.store.counter_set("last_spoke_ts", time.time())
        self._bump_today()
        self.store.add_turn("assistant", draft[:400])
        self.store.add_event(f"主动开口[{share_kind}]：{draft[:80]}", kind="proactive")

        # 冷场统计：上次说话后有没有收到回复
        if self.last_reply_ts < self.last_spoke_ts:
            self._bump_cold()

        if share:
            self.digest.mark_shared()

        return Decision(True, "已发送", f"已主动发出：{draft[:40]}…", topic=decision.topic)
