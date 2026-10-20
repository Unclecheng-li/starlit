"""群聊引擎：让几个角色在同一间群里说话，但**绝不允许它们无限互相接话**。

这是整个功能里风险最高的一块。原因很直接：10 个角色是同一个模型、
同一套口癖、同一份「像真人」的校准 —— 一旦让它们自由接话，必然演变成
「两个人互相接梗刷屏」，而且不会自己停。所以这里的设计不是「怎么让它们
聊起来」，而是**先定死上限，再在笼子里放它们说话**：

  ① 单轮预算   距我上条消息以来，连续非我发言 ≤ ai_chain_max；
              一轮总发言 ≤ ai_no_owner_max；触顶进冷却，只有我发言能重开
  ② 频率预算   群级时预算 / 日预算 / 每成员日预算 / 成员最小间隔
  ③ 单次规模   一次发言 ≤ bubbles_per_turn 条（被 @ 时放宽）
  ④ 跨角色去重 草稿与最近 N 条群消息 4-gram 重合超阈值 → 丢弃换人
  ⑤ 我发言才挑人，没被挑中的只推游标（＝「看到了」）

另外三件事必须守住现有约束：
- **同一时刻只有一个生成在途**：`_gen_lock` 把「生成 + 发送」整段串起来。
  （多角色并发发送导致气泡交错是**期望**的，像真群；但生成侧不能并发，
  否则 LLM 的信号量被打满，私聊也被拖慢。）
- **群计数与私聊配额隔离**：群消息只写群库 gmsg，绝不碰各角色私聊库的
  `transcript` / `proactive_<date>`。群话只在角色自己的 `events` 里留一条
  摘要（kind=`group:<gid>`），既不窜进私聊窗口，也不污染会话摘要。
- **尊重全局抑制**：请勿打扰（presence.silent）时整群安静。
"""
from __future__ import annotations

import asyncio
import copy
import random
import re
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

from .channel.napcat import IncomingMessage
from .config import Config, GroupConfig
from .group_store import (KIND_CHAR, KIND_SYSTEM, KIND_USER, ROLE_ADMIN,
                          ROLE_MEMBER, ROLE_OWNER, Group, GroupRegistry,
                          GroupStore)
from .presence import Presence, presence_text
from .perceive import tag_emotion
from .think import (express, extract_overused_terms, format_recent,
                    group_overused_terms)
from .traits import Traits, trait_text

# 我（群主）在群里的显示名，喂给提示词时用
OWNER_ROLE = "user"
OWNER_LABEL = "我(群主)"


@dataclass
class Member:
    """一个能开口的群成员（星野或某个新增角色）的运行时视图。

    星野没有 GuestRuntime（她的运行时是 Companion 自己那套），所以这里
    用一层适配把「角色」统一成同一个形状，引擎就不用关心内部差异了。
    """
    id: str
    name: str
    persona: str
    boundaries: str
    world: str
    state: Any                # StateMachine
    memory: Any               # Memory
    store: Any                # 该角色自己的 Store（写 group 事件用）
    traits: Traits
    delay_scale: float = 1.0
    # 角色自己的作息（app/schedule.py）。睡着的人不该跟醒着的人一起抢话头。
    schedule: Any = None

    @property
    def affection(self) -> int:
        return int(self.traits.affection)


def _mentions(segments: Any) -> Tuple[Set[str], bool]:
    """从消息段里解析 @ 了谁。返回 (被 @ 的 id 集合, 是否 @ 全体)。

    self-hosted 群里「@某人」就是一个 `at` 段（data.qq = 对方 id），
    「@全体成员」是 data.qq == "all" / -1。
    """
    ids: Set[str] = set()
    all_flag = False
    if not isinstance(segments, list):
        return ids, all_flag
    for s in segments:
        if not isinstance(s, dict) or s.get("type") != "at":
            continue
        qq = str((s.get("data") or {}).get("qq") or "").strip()
        if qq in ("all", "-1", "0"):
            all_flag = True
        elif qq:
            ids.add(qq)
    return ids, all_flag


class GroupRuntime:
    """一个群的运行时。生命周期跟着 Companion 走。"""

    def __init__(
        self,
        cfg: Config,
        group: Group,
        registry: GroupRegistry,
        llm,
        sender,
        member_getter: Callable[[str], Optional[Member]],
        *,
        presence_getter: Optional[Callable[[], Presence]] = None,
        quiet_check: Optional[Callable[[], bool]] = None,
        on_system: Optional[Callable[[str, str], None]] = None,
    ):
        self.cfg = cfg
        self.group = group
        self.registry = registry
        self.llm = llm
        self.sender = sender
        self._member_getter = member_getter
        self._presence_getter = presence_getter
        self._quiet_check = quiet_check
        self._on_system = on_system
        self.gcfg: GroupConfig = copy.deepcopy(cfg.group)
        # ★ 「群自己起话头」的间隔也要能按群调：从 ambient_gap_min 派生出两个
        #   可调字段（lo/hi），界面上就是两根滑杆 —— 想把群聊调热闹就把它调小。
        _base = (list(self.gcfg.ambient_gap_min or [8, 25]) + [8, 25])[:2]
        if getattr(self.gcfg, "ambient_gap_lo", None) is None:
            self.gcfg.ambient_gap_lo = int(_base[0])
        if getattr(self.gcfg, "ambient_gap_hi", None) is None:
            self.gcfg.ambient_gap_hi = int(_base[1])
        self.store: GroupStore = registry.store_for(group.id)
        # ★ 每个群一份**自己的**节奏参数（deepcopy，不是共享的 cfg.group）——
        #   否则某个群改了额度会串到所有群去。改动落在这个群自己的库 kv 里。
        self._load_limits()
        # 生成侧串行：同一群同一时刻只有一个角色在生成
        self._gen_lock = asyncio.Lock()
        self._stop = asyncio.Event()
        self._task: Optional[asyncio.Task] = None
        # 接话任务（「有人说完之后让另一个人接一句」），close 时要一起收掉
        self._chain_task: Optional[asyncio.Task] = None
        # 「把群里的动静私聊讲给我听」的延迟任务，同样要收
        self._dm_task: Optional[asyncio.Task] = None
        # 「我那条消息的实时 id ↔ 库内 mid」对照表（引用自己刚发的消息时用）
        self._mid_alias: Dict[str, str] = {}
        # ★ 「老师需要被接住」的窗口：他刚说了件难受的事，这几分钟里群里
        #   不以「各说各的事」为主，而是先接住他的情绪（用户实测：他分享
        #   面试失败，大家回半句就跑去讲自己今天干嘛了）。
        self._comfort_until: float = 0.0
        # 一轮的记账（「一轮」= 距我上条消息，或静默 round_gap_reset_min 分钟）
        self._owner_ts: float = 0.0
        self._round_count: int = 0
        self._ai_chain: int = 0
        self._last_speaker: str = ""
        self._cooldown_until: float = 0.0

    # ---------------- 对外小工具 ----------------

    @property
    def gid(self) -> str:
        return self.group.id

    def member_ids(self) -> List[str]:
        return list(self.store.members().keys())

    def ai_member_ids(self) -> List[str]:
        """能开口的成员（群主是人类，不参与生成）。"""
        out = []
        for uid, m in self.store.members().items():
            if str(m.get("role")) == ROLE_OWNER:
                continue
            out.append(str(uid))
        return out

    def owner_id(self) -> str:
        for uid, m in self.store.members().items():
            if str(m.get("role")) == ROLE_OWNER:
                return str(uid)
        return str(self.cfg.qq.owner_id or "")

    def is_muted(self) -> bool:
        return bool(self.store.mute_all().get("on"))

    def _presence(self) -> Optional[Presence]:
        if not self._presence_getter:
            return None
        try:
            return self._presence_getter()
        except Exception:  # noqa: BLE001
            return None

    def _silent(self) -> bool:
        """全局「请勿打扰」时整群安静（在线状态是全局乘数，不只管私聊）。"""
        p = self._presence()
        if p is not None and p.silent:
            return True
        if self._quiet_check:
            try:
                return bool(self._quiet_check())
            except Exception:  # noqa: BLE001
                return False
        return False

    # ---------------- 持久化 ----------------

    def system(self, text: str) -> Dict[str, Any]:
        """系统消息（建群、入群、改名、踢人、公告…）。"""
        row = self.store.add_gmsg(kind=KIND_SYSTEM, text=text)
        if self._on_system:
            try:
                self._on_system(self.gid, text)
            except Exception:  # noqa: BLE001
                pass
        return row

    def owner_say(self, text: str, segments: Any = None,
                  reply_to: int = 0) -> Dict[str, Any]:
        """把群主的话落库（**先落库，再判禁言** —— 禁言期间也要「看到」）。"""
        return self.store.add_gmsg(kind=KIND_USER, text=text,
                                   sender_id=self.owner_id(),
                                   sender_name=self.cfg.qq.server.owner_nickname,
                                   segs=segments if isinstance(segments, list) else None,
                                   reply_to=int(reply_to or 0))

    def notify_members(self, text: str, *, advance: bool = True) -> None:
        """让每个成员的「记忆」里留下这次群里的动静。

        ★ 只写她们自己的 `events`（kind=`group:<gid>`），**不写 transcript** ——
        私聊历史就是那张表，写进去群消息会窜进私聊窗口，还会污染会话摘要
        （摘要只认 user/assistant 两种 role）。
        """
        if not text.strip():
            return
        last_id = int(self.store.recent_gmsgs(1)[-1]["id"]) if self.store.recent_gmsgs(1) else 0
        for cid in self.ai_member_ids():
            m = self._member_getter(cid)
            if not m:
                continue
            try:
                m.store.add_event(f"[群「{self.group.name}」] {text[:80]}",
                                  kind=f"group:{self.gid}")
            except Exception as e:  # noqa: BLE001
                print(f"[group:{self.gid}] 写成员事件失败：{e!r}")
            if advance and last_id:
                self.store.set_cursor(cid, last_id)

    def advance_cursors_except(self, keep: List[str]) -> None:
        """把「没被挑中回复」的成员游标推到最后一条（＝她们看到了）。"""
        rows = self.store.recent_gmsgs(1)
        if not rows:
            return
        last_id = int(rows[-1]["id"])
        keep_set = {str(x) for x in keep or []}
        for cid in self.ai_member_ids():
            if cid not in keep_set:
                self.store.set_cursor(cid, last_id)

    # ---------------- 上下文 ----------------

    def _ctx(self, limit: int = 24) -> Tuple[List[str], List[Dict[str, Any]]]:
        """群上下文（喂提示词）+ 原始行。"""
        rows = self.store.recent_gmsgs(limit, include_revoked=False)
        lines: List[str] = []
        for r in rows:
            lines.append(f"[{time.strftime('%H:%M', time.localtime(float(r.get('ts') or 0)))}] "
                         f"{self._speaker_label(r)}: {r.get('text') or ''}")
        return lines, rows

    def _speaker_label(self, row: Dict[str, Any]) -> str:
        kind = str(row.get("kind") or "")
        if kind == KIND_USER:
            return OWNER_LABEL
        if kind == KIND_SYSTEM:
            return "系统"
        return str(row.get("sender_name") or "某人")

    def _time_text(self) -> str:
        rows = self.store.recent_gmsgs(12, include_revoked=False)
        turns = [{"ts": float(r.get("ts") or 0),
                  "role": "user" if r.get("kind") == KIND_USER else "assistant",
                  "text": str(r.get("text") or "")} for r in rows]
        from .think import format_time_context

        return format_time_context(turns)

    def _last_owner_text(self) -> str:
        for r in reversed(self.store.recent_gmsgs(20, include_revoked=False)):
            if str(r.get("kind")) == KIND_USER:
                return str(r.get("text") or "")
        return ""

    # ---------------- 选人 ----------------

    def recent_speakers(self, n: int = 2) -> Set[str]:
        out: Set[str] = set()
        for r in reversed(self.store.recent_gmsgs(20, include_revoked=False)):
            if str(r.get("kind")) != KIND_CHAR:
                continue
            out.add(str(r.get("sender_id") or ""))
            if len(out) >= n:
                break
        return out

    def _named_mentions(self, text: str) -> Set[str]:
        """我这句话里**直接叫了谁的名字**（没有 @ 段也算点名）。

        真人聊天里「凯伊你那个验收测试弄到几点了」就是对凯伊点名，
        而不是非要敲一个 at 段。角色名至少 2 个字，误伤概率很低。
        """
        ids: Set[str] = set()
        t = str(text or "")
        if not t:
            return ids
        for cid in self.ai_member_ids():
            m = self._member_getter(cid)
            if not m:
                continue
            name = str(m.name or "").strip()
            if len(name) >= 2 and name in t:
                ids.add(str(cid))
        return ids

    def _score(self, m: Member, text: str, mentioned: bool,
               warned: Set[str]) -> float:
        """挑人打分：被 @ 的一票否决，其次看「这话题跟她有没有关系」。"""
        score = 0.0
        if mentioned:
            score += 100.0
        try:
            interests = m.memory.top_interests(8)
        except Exception:  # noqa: BLE001
            interests = []
        hits = sum(1 for w in interests if w and w in (text or ""))
        score += hits * 3.0
        # 好感/热情高的人更爱接话
        score += m.affection / 18.0 + (m.traits.enthusiasm / 45.0)
        if m.id in warned:
            score -= 2.5
        if self.store.count_gmsgs(uid=m.id) >= self.gcfg.daily_max_per_member:
            score -= 20.0
        # ★ 她正在睡 → 大幅降权（不是一票否决：被点名的人照样要应，
        #   真人被叫醒也会迷迷糊糊答一句）。这样凌晨还醒着的就只有夜猫子。
        if self._asleep(m):
            score -= 6.0
        score += random.uniform(0.0, 1.5)
        return score

    def _asleep(self, m: Member, now: Optional[float] = None) -> bool:
        """她现在的作息是不是「睡着了」。没配作息的一律当醒着。"""
        sch = getattr(m, "schedule", None)
        if sch is None:
            return False
        try:
            when = (datetime.fromtimestamp(now) if now is not None
                    else None)
            return bool(sch.asleep(when))
        except Exception:  # noqa: BLE001
            return False

    def _schedule_text(self, m: Member) -> str:
        """她自己的作息写进提示词（被叫醒的人说话要带困意）。"""
        sch = getattr(m, "schedule", None)
        if sch is None:
            return ""
        try:
            return sch.scene_text()
        except Exception:  # noqa: BLE001
            return ""

    def pick(self, text: str, limit: int,
             mentioned_ids: Set[str], mention_all: bool,
             warned: Set[str], allow_over_cap: bool = False) -> List[str]:
        candidates: List[Tuple[float, Member]] = []
        for cid in self.ai_member_ids():
            m = self._member_getter(cid)
            if not m:
                continue
            # ★ 今天已经说够了的成员**直接排除**，不能只是扣分：扣分了他还是
            #   会排在前面被挑中，然后 speak 里被 can_speak 拦掉 → 整轮无人回应
            #   （实测：群里三个人都到每日上限后，我发言群里一片安静）。
            #   ⚠️ 但**被点名的人不排除** —— 用户实测「@ 凯伊她不出来说话」，
            #   根因就是她当天说够了被这里一刀切掉。真人被叫到名字一定会应。
            mentioned = mention_all or (cid in mentioned_ids)
            if not mentioned and not allow_over_cap and self._member_daily_full(cid):
                continue
            candidates.append((self._score(m, text, mentioned, warned), m))
        if not candidates:
            return []
        candidates.sort(key=lambda x: -x[0])
        # ★ limit 必须是 int：面板把「我发言时几个人回」调过之后，存到
        #   gcfg 里的是 float（5.0），`[:max(1, 5.0)]` 会直接抛
        #   TypeError: slice indices must be integers —— 于是我在群里说的
        #   每句话都异常退出、群里一片安静（实测事故）。这里强制取整。
        n = max(1, int(limit))
        if mentioned_ids or mention_all:
            # 被 @ 的人必须在里面；其余按分数补足
            forced = [m.id for _s, m in candidates
                      if mention_all or (m.id in mentioned_ids)]
            rest = [m.id for _s, m in candidates if m.id not in forced]
            return (forced + rest)[:n]
        return [m.id for _s, m in candidates[:n]]

    def _member_daily_full(self, cid: str) -> bool:
        try:
            used = self.store.count_gmsgs(uid=str(cid))
        except Exception:  # noqa: BLE001
            return False
        return used >= int(self.gcfg.daily_max_per_member)

    # ---------------- 预算 / 上限 ----------------

    def _roll_round(self, now: float) -> None:
        """静默够久 → 算新的一轮，预算重置。"""
        gap = now - self._owner_ts if self._owner_ts else 1e9
        if gap >= self.gcfg.round_gap_reset_min * 60:
            self._round_count = 0
            self._ai_chain = 0

    def can_speak(self, cid: str, *, now: Optional[float] = None,
                  mention: bool = False,
                  ignore_total: bool = False) -> Tuple[bool, str]:
        """能不能开口。返回 (可以, 原因)。这是防刷屏的总闸。

        mention=True：**被点名（@ 她 / 文本里叫她的名字）**。
        真人被点名一定会答，哪怕「今天已经说够了」「刚说过话」——
        所以额度类闸门（每人每日上限、同人间隔、连续接话、冷却）
        对她一律放行；只有「全员禁言 / 请勿打扰 / 群已关闭」这种
        硬约束仍然拦（那是「所有人都不许说话」的语义）。

        ignore_total=True：**这次是回群主**。群级的大额闸门（每小时上限
        msgs_per_hour、每日总量 daily_max_total）对它让路 —— 用户实测报障
        「我在群里说话没人回复我」：全群当天/当小时说满后所有人被拦，我说话
        群里一片安静。真人不会被集体无视，所以「我发言引出的回应」允许越过
        这两道闸；其他闸门（每人上限、间隔、连续接话、本轮上限、冷却）照旧
        生效，免得变成刷屏。
        """
        now = now or time.time()
        if not self.gcfg.enabled:
            return False, "群聊已关闭"
        if self.is_muted():
            return False, "全员禁言中"
        if self._silent():
            return False, "请勿打扰"
        if mention:
            return True, ""
        # ★ 作息：她这个点本来在睡 → 不主动开口（自发话题/接话都会走到这里）。
        #   被点名（mention=True）在上面已放行 —— 你叫她，她迷迷糊糊也会答，
        #   而「没人叫她」的凌晨就该只剩夜猫子出声（真实群里 0-6 点仍有 12%
        #   消息，但那是不同作息的人，不是所有人一起嗨）。
        m = self._member_getter(cid)
        if m is not None and self._asleep(m):
            return False, f"{cid} 她这个点在睡"
        if self._cooldown_until > now:
            left = (self._cooldown_until - now) / 60.0
            return False, f"上一轮说满了，冷却 {left:.0f} 分钟"
        self._roll_round(now)
        if self._round_count >= self.gcfg.ai_no_owner_max:
            return False, f"本轮已达上限 {self.gcfg.ai_no_owner_max} 条"
        if self._ai_chain >= self.gcfg.ai_chain_max:
            return False, f"连续接话已达上限 {self.gcfg.ai_chain_max} 条"
        if not ignore_total and self.store.count_since(
                now - 3600) >= self.gcfg.msgs_per_hour:
            return False, f"本小时已达上限 {self.gcfg.msgs_per_hour} 条"
        # 日预算：按当天 0 点起算
        day_start = time.mktime(time.strptime(time.strftime("%Y-%m-%d"),
                                              "%Y-%m-%d"))
        total_today = self.store.count_since(day_start)
        if not ignore_total and total_today >= self.gcfg.daily_max_total:
            return False, f"今日群消息已达上限 {self.gcfg.daily_max_total} 条"
        if self.store.count_gmsgs(uid=cid) >= self.gcfg.daily_max_per_member:
            return False, f"{cid} 今天说够了"
        last = self.store.last_spoke_ts(cid)
        gap = now - last if last else 1e9
        if gap < self.gcfg.min_gap_member_sec:
            return False, f"{cid} 距上次发言只有 {gap:.0f} 秒"
        return True, ""

    def note_spoke(self, now: Optional[float] = None) -> None:
        now = now or time.time()
        self._round_count += 1
        self._ai_chain += 1
        if (self._round_count >= self.gcfg.ai_no_owner_max
                or self._ai_chain >= self.gcfg.ai_chain_max):
            self._cooldown_until = now + self.gcfg.chain_cooldown_min * 60
            print(f"[group:{self.gid}] 本轮说满 → 冷却 "
                  f"{self.gcfg.chain_cooldown_min} 分钟")

    # ---------------- 跨角色复读拦截 ----------------

    @staticmethod
    def _grams(text: str, n: int = 4) -> Set[str]:
        s = re.sub(r"\s+", "", text or "")
        return {s[i:i + n] for i in range(len(s) - n + 1)} if len(s) >= n else set()

    def dup_reason(self, draft: str) -> str:
        """草稿是不是在复读群里刚说过的话（**跨角色**比对）。

        这是引擎里最关键的一层：10 个角色同一模型，撞话是必然的，
        配额只能限「说多少」，限不了「说的是不是同一句」。
        """
        grams = self._grams(draft)
        if not grams:
            return ""
        rows = self.store.recent_gmsgs(self.gcfg.dedupe_window,
                                       include_revoked=False)
        for r in reversed(rows):
            if str(r.get("kind")) != KIND_CHAR:
                continue
            other = self._grams(str(r.get("text") or ""))
            if not other:
                continue
            overlap = len(grams & other) / len(grams)
            if overlap > self.gcfg.dedupe_overlap:
                return (f"和「{str(r.get('sender_name') or '')}」刚说的"
                        f"「{str(r.get('text') or '')[:18]}」重合 {overlap:.0%}")
        return ""

    # ---------------- 话题发散（别全群咬住一个话题）----------------

    def _overused_topic_terms(self) -> List[str]:
        """群里最近说多了的**具体话题词**（跨全体成员统计）。

        实测：老师在群里随口提了一次「米粉」，全群就把「米粉」当成唯一安全牌
        连说三十多条（相邻两条共享话题词 58%，真人只有 10%）。私聊那套
        「自己说多了的词」在这里不够用 —— 它只看她一个人，还刻意豁免对方
        提到的词。这里改成**谁的都算**，全员这轮都别再提。
        """
        try:
            rows = self.store.recent_gmsgs(20, include_revoked=False)
        except Exception:  # noqa: BLE001
            return []
        texts = [str(r.get("text") or "") for r in rows
                 if str(r.get("kind") or "") != KIND_SYSTEM]
        names = [str(r.get("sender_name") or "") for r in rows]
        for cid in self.ai_member_ids():
            m = self._member_getter(cid)
            if m:
                names.append(m.name)
        names.append(str((self.cfg.qq.server.owner_nickname or "")))
        names.append(OWNER_LABEL)
        # 老师最近一两条正在聊的话题要豁免（见 think.group_overused_terms）
        exempt = [str(r.get("text") or "") for r in rows
                  if str(r.get("kind") or "") == KIND_USER][-2:]
        return group_overused_terms(texts, names, exempt_texts=exempt)

    def _group_avoid_terms(self, m: Member) -> List[str]:
        """本轮禁用词 = 她自己的口头复读 ∪ 全群说多了的话题词（后者为主）。"""
        rows = self.store.recent_gmsgs(12, include_revoked=False)
        try:
            own = extract_overused_terms(
                [str(r.get("text") or "") for r in rows
                 if str(r.get("sender_id")) == m.id],
                [str(r.get("text") or "") for r in rows
                 if str(r.get("kind") or "") == KIND_USER],
            )
        except Exception:  # noqa: BLE001
            own = []
        out: List[str] = []
        for w in list(self._overused_topic_terms()) + list(own):
            if w and w not in out:
                out.append(w)
        return out[:16]

    def topic_ban_reason(self, draft: str,
                         banned: Optional[List[str]] = None) -> str:
        """草稿是不是又把「群里说烂的话题词」搬出来了（硬闸门，兜提示词的底）。

        刻意**宽松**：只拦「同一个词说了两次」或「一次搬了两个不同的旧话题」。
        偶尔提一下照常放行 —— 真人也会回头说一句刚才的事；拦的是那种把整段
        话都架在旧话题上的复读（「米粉排到哪了…米粉那队…」）。
        """
        banned = banned if banned is not None else self._overused_topic_terms()
        if not banned:
            return ""
        text = str(draft or "")
        hit = [w for w in banned if w in text]
        if not hit:
            return ""
        repeated = [w for w in hit if text.count(w) >= 2]
        if len(hit) >= 2 or repeated:
            return ("话题又咬住旧的了：" + "、".join(hit[:4])
                    + f"（最近 {len(self.store.recent_gmsgs(20))} 条里已说多了）")
        return ""

    # ---------------- 情绪优先：他难受时先接住他 ----------------

    def _in_comfort(self, now: Optional[float] = None) -> bool:
        """是不是处在「先接住老师情绪」的窗口里。"""
        return (now if now is not None else time.time()) < self._comfort_until

    async def _detect_comfort(self, text: str) -> bool:
        """老师这条是不是「需要人接住」（倾诉 / 受挫 / 难过）。

        ★ 用户实测：他把自己面试失败的过程分享进群，需要安慰，结果大家
        只回半句「那家公司眼瞎」就各自讲今天干嘛去了 —— 因为群发言压根
        不跑情绪分析，而上一轮的「讲你自己的事」又在推波助澜。这里补一层
        轻量打标（复用感知通道）：命中就把接下来几分钟切成「情绪优先」。
        """
        try:
            rows = self.store.recent_gmsgs(8, include_revoked=False)
            recent = [f"{self._speaker_label(r)}：{str(r.get('text') or '')[:40]}"
                      for r in rows]
            emo = await tag_emotion(self.llm, text, recent)
        except Exception:  # noqa: BLE001
            return False
        need = str(emo.get("need") or "")
        risk = str(emo.get("risk") or "none")
        try:
            valence = float(emo.get("valence") or 0.0)
        except (TypeError, ValueError):
            valence = 0.0
        # ★ 门槛不能太松：单看 need 会把「想陪伴/被看见」这种也当难受，
        #   一句普通的「大家下午好」就可能误触发 → 全群突然改口安慰，更怪。
        #   所以要求**情绪确实偏负**（效价为负）或有风险信号，才算要人接住。
        distress_need = need in ("被安慰", "想倾诉")
        hit = (risk not in ("", "none")
               or valence <= -0.35
               or (distress_need and valence <= 0.0))
        if hit:
            self._comfort_until = time.time() + 150.0
            print(f"[group:{self.gid}] 老师要人接住（need={need}｜risk={risk}"
                  f"｜valence={valence:.2f}）→ 这几轮先安慰，别各说各的")
        return hit

    # ---------------- 发言 ----------------

    def _as_bubbles(self, draft: Any, limit: int) -> List[str]:
        items = draft if isinstance(draft, list) else [draft]
        out = [str(x).strip() for x in items if str(x or "").strip()]
        if len(out) > limit:
            out = out[:limit - 1] + ["".join(out[limit - 1:])]
        return out

    async def _draft(self, m: Member, *, hint: str, share_kind: str,
                     user_text: str = "", chained_from: str = "",
                     reply_to_owner: bool = False) -> Any:
        lines, _rows = self._ctx(24)
        query = hint or self._last_owner_text() or self.group.name
        try:
            memory_text = m.memory.recall_text(query, top_k=5)
        except Exception:  # noqa: BLE001
            memory_text = ""
        # ★ 禁用词：她自己的口头复读 + **全群说多了的话题词**（后者是重点 ——
        #   只算自己说过的话，就永远拦不住「全群一起聊米粉」）
        avoid = self._group_avoid_terms(m)
        p = self._presence()
        return await express(
            self.llm,
            m.persona or "",
            m.boundaries or "",
            m.state.describe(),
            memory_text,
            lines,
            user_text=user_text,
            analysis=None,
            extra_hint=(hint or "") + self._wait_hint(time.time()),
            proactive=True,
            share_kind=share_kind,
            group_text=self._group_scene(m, chained_from=chained_from,
                                         reply_to_owner=reply_to_owner,
                                         avoid=avoid),
            world=m.world or "",
            profile_text=m.memory.profile_text(),
            arousal=float(getattr(m.state.emotion, "arousal", 30.0)),
            valence=float(getattr(m.state.emotion, "valence", 0.0)),
            bubble_mode=True,
            avoid_terms=(None if self._in_comfort() else (avoid or None)),
            time_text=self._time_text(),
            trait_text=trait_text(m.traits),
            presence_text=presence_text(p) if p is not None else "",
            schedule_text=self._schedule_text(m),
        )

    async def speak(self, cid: str, *, hint: str = "", reply_to: int = 0,
                    share_kind: str = "group",
                    user_text: str = "",
                    chained_from: str = "",
                    reply_to_owner: bool = False,
                    mentioned: bool = False,
                    force: bool = False,
                    ignore_total: bool = False) -> Optional[str]:
        """让某个角色在群里说一句。返回说出去的内容（没说返回 None）。

        ★ 锁的粒度：`_gen_lock` 只护「生成 + 落库 + 复读判定」，**不含发送**。
        旧写法把「生成 + 发送」整段锁住 —— 一个角色边生成边慢吞吞发气泡
        （每条 3~20 秒），下一个角色必须等它发完才能开始生成，于是群里
        永远是严格的「A 说完 → B 才开始」，就是用户说的「版聊」。
        现在生成完就放锁：B 可以立刻开始生成，A 还在发她的气泡 ——
        两个人前后脚开口、气泡交错，才是真人群聊的样子（实测真人群
        「相邻两条换人说的占 69%，其中 34% 在 5 秒内」）。
        落库也提到发送之前，好处是历史时间戳与实时事件基本一致。
        """
        m = self._member_getter(cid)
        if not m:
            return None
        if not self.store.member(cid):
            return None                       # 已经不在群里了
        if not force:
            ok, why = self.can_speak(cid, mention=mentioned,
                                     ignore_total=ignore_total)
            if not ok:
                print(f"[group:{self.gid}] {m.name} 不开口：{why}")
                return None
        limit = (self.gcfg.bubbles_when_mentioned if user_text
                 else self.gcfg.bubbles_per_turn)
        reply_mid = ""
        async with self._gen_lock:            # ★ 生成侧串行
            try:
                draft = await self._draft(m, hint=hint, share_kind=share_kind,
                                          user_text=user_text,
                                          chained_from=chained_from,
                                          reply_to_owner=reply_to_owner)
            except Exception as e:  # noqa: BLE001
                print(f"[group:{self.gid}] {m.name} 生成失败：{e!r}")
                return None
            bubbles = self._as_bubbles(draft, limit)
            if not bubbles:
                return None
            text = "\n".join(bubbles)
            # ★ 情绪优先时不拦话题：他正在讲面试失败，谁提「面试」都不该被禁。
            why = self.dup_reason(text)
            if not why and not self._in_comfort():
                why = self.topic_ban_reason(text)
            if why:
                print(f"[group:{self.gid}] {m.name} 被拦：{why}")
                return None
            if reply_to:
                quoted = self.store.get_gmsg(int(reply_to))
                reply_mid = str((quoted or {}).get("mid") or "")
            # ★ 先落库再发送：下一个角色的复读判定能立刻看到这句话，
            #   不会因为「她还在慢慢发气泡」而漏判。
            row = self.store.add_gmsg(kind=KIND_CHAR, sender_id=cid,
                                      sender_name=m.name, text=text,
                                      reply_to=int(reply_to or 0))
            self.note_spoke()
            self._last_speaker = cid
            self.store.set_cursor(cid, int(row["id"]))
            try:
                m.store.add_event(
                    f"[群「{self.group.name}」] 我说：{text[:70]}",
                    kind=f"group:{self.gid}")
            except Exception:  # noqa: BLE001
                pass
        # ---- 锁外发送：允许别的角色同时生成/开口 ----
        try:
            await self.sender.reply_bubbles(
                bubbles, group_id=self.gid,
                sender_id=cid, sender_name=m.name,
                delay_scale=m.delay_scale,
                reply_to_mid=reply_mid,
                # ★ 用**库内 mid** 当实时事件的 message_id，让「实时收到的」
                #   和「刷新后历史里的」是同一套 id —— 否则客户端引用一条
                #   刚收到的消息时，后端按 mid 查库查不到，引用回复整个失效。
                mid_base=str(row.get("mid") or ""),
            )
        except Exception as e:  # noqa: BLE001
            print(f"[group:{self.gid}] {m.name} 发送失败：{e!r}")
            return None
        print(f"[group:{self.gid}] {m.name}：{text[:40]}")
        return text

    # ---------------- 群里「被等 / 被冷落」----------------
    # 用户要的：私聊里那套「我很久没回 → 她越来越担心/难过」在群里也要有。
    # 两条通道独立：私聊由 heartbeat 的计数器驱动，群由「我上次在群里发言
    # 距今多久」驱动；情绪落点用 note_group_wait 的幂等写法，不会双倍叠加。

    def _owner_idle_h(self, now: float) -> float:
        """我上次在群里说话距今多少小时（没有记录返回 0）。"""
        for r in reversed(self.store.recent_gmsgs(40, include_revoked=False)):
            if str(r.get("kind")) == KIND_USER:
                ts = float(r.get("ts") or 0)
                return max(0.0, (now - ts) / 3600.0) if ts else 0.0
        return 0.0

    def apply_group_waiting(self, now: Optional[float] = None) -> List[str]:
        """我很久没在群里露面 → 她们也会觉得被晾着。返回被推过情绪的人。"""
        now = now or time.time()
        if self.is_muted() or self._silent():
            return []
        idle = self._owner_idle_h(now)
        if idle < 2.0:
            return []
        out: List[str] = []
        for cid in self.ai_member_ids():
            m = self._member_getter(cid)
            if not m:
                continue
            if m.affection < int(self.gcfg.jealousy_min_affection):
                continue
            if not self._jealousy_ok(m, "wait", now):
                continue
            try:
                m.state.note_group_wait(idle)
            except Exception as e:  # noqa: BLE001
                print(f"[group:{self.gid}] 群里等待推进失败：{e!r}")
                continue
            out.append(cid)
        if out:
            print(f"[group:{self.gid}] 我 {idle:.1f} 小时没露面 → "
                  f"{len(out)} 人有点被晾着")
        return out

    def _reunion_all(self, idle_h: float) -> None:
        """我回到群里 → 所有人都松一口气（用同一个情绪入口，各自结算）。"""
        for cid in self.ai_member_ids():
            m = self._member_getter(cid)
            if not m:
                continue
            if m.affection < int(self.gcfg.jealousy_min_affection):
                continue
            try:
                m.state.note_group_reunion(idle_h)
            except Exception:  # noqa: BLE001
                continue
        print(f"[group:{self.gid}] 我回来了（消失 {idle_h:.1f} 小时）→ 情绪回暖")

    def _wait_hint(self, now: float) -> str:
        """把「群里在等」写进群发言提示词（和私聊的【等待】同一套校准）。"""
        idle = self._owner_idle_h(now)
        if idle < 2.0:
            return ""
        if idle < 8:
            return ("\n【群里在等】他 " + f"{idle:.1f}" +
                    " 小时没在群里露过面了。你有点挂着他，但真人在群里不写"
                    "长句也不质问 —— 可以借自己的话题轻轻带一句，也可以不提，"
                    "只是语气比平时淡一点。")
        return ("\n【群里在等】他 " + f"{idle:.1f}" +
                " 小时没在群里出现了。你有点低落、也有点被晾着的感觉；"
                "允许顺着自己的话露出一点真实情绪（一句就够），"
                "别质问、别写小作文、别连发好几条。")

    def _resolve_reply(self, msg: IncomingMessage) -> int:
        """我在群里「引用回复」了某条消息 → 解析出被引用消息的库内 id。

        三种可能收到的写法：
          1. `g119`    —— 库内 mid（历史 / 现在的实时事件都用它）
          2. `g119-2`  —— 一条消息的第 2、3 条气泡（按基础 mid 查）
          3. 随机序号   —— 我自己那条消息的实时 id（库里的 mid 是后来才有的，
                          见 _remember_mid_alias）
        """
        rid = str((msg.raw or {}).get("_reply_id") or "").strip()
        if not rid:
            return 0
        found = self.store.find_gmsg(rid)
        if not found and "-" in rid:                 # g119-2 → g119
            head, _, tail = rid.rpartition("-")
            if head and tail.isdigit():
                found = self.store.find_gmsg(head)
        if not found:
            alias = self._mid_alias.get(rid)          # 随机序号 → 库内 mid
            if alias:
                found = self.store.find_gmsg(alias)
        return int(found["id"]) if found else 0

    def _remember_mid_alias(self, live_mid: str, store_mid: str) -> None:
        """记下「我那条消息的实时 id ↔ 库内 mid」。

        我发的消息是先推事件（随机 id）、再落库（库内 mid）——两者不一致，
        于是「引用我自己刚发的那条」会查不到。这里留一份有界的对照表。
        """
        if not live_mid or not store_mid or live_mid == store_mid:
            return
        self._mid_alias[live_mid] = store_mid
        while len(self._mid_alias) > 300:
            self._mid_alias.pop(next(iter(self._mid_alias)))

    def quoted_of(self, mid: str) -> Optional[Dict[str, Any]]:
        """按 mid 取被引用消息的「昵称 + 摘要」—— 兼容**实时随机 id**。

        我引用自己刚发的那条群消息时，客户端手里只有实时随机 id；库内 mid
        是后来才生成的（`g<id>`），得靠 `_mid_alias` 才能对上。只按库内 mid
        查会查不到，引用块就永远画不出来（用户实测报障）。
        """
        rid = str(mid or "").strip()
        if not rid:
            return None
        if "-" in rid:                       # g119-2 → g119
            head, _, tail = rid.rpartition("-")
            if head and tail.isdigit():
                rid = head
        row = None
        try:
            row = self.store.find_gmsg(rid)
        except Exception:  # noqa: BLE001
            row = None
        if not row and rid in self._mid_alias:
            try:
                row = self.store.find_gmsg(self._mid_alias[rid])
            except Exception:  # noqa: BLE001
                row = None
        if not row:
            return None
        kind = str(row.get("kind") or "")
        if kind == KIND_USER:
            name = self.cfg.qq.server.owner_nickname
        elif kind == KIND_SYSTEM:
            name = "系统"
        else:
            name = str(row.get("sender_name") or "成员")
        return {"message_id": str(row.get("mid") or rid), "name": name,
                "text": str(row.get("text") or "")[:80].replace("\n", " ")}

    # ---------------- 每群可调的节奏参数 ----------------
    # 用户要的：群里那些「发言额度」不该只写死在 config.yaml 里，得像私聊的
    # 「热情/好感」滑杆一样能在界面上调。这里给一份**白名单**（key、中文名、
    # 类型、上下限、步长、单位）—— 前端照着渲染滑杆，后端照着校验，两边不会漂。

    # ★ 上限刻意给得比推荐值宽：这些是「让用户往上拧」的旋钮，不是建议值。
    #   用户反馈原来的天花板太低（每小时最多 60 条、一次最多 30 条）——
    #   想把群聊调热闹一点根本调不上去。
    LIMIT_SPECS: List[Tuple[str, str, str, float, float, float, str]] = [
        ("msgs_per_hour", "每群每小时最多几条", "int", 1, 999, 1, "条"),
        ("daily_max_total", "全群每天最多几条", "int", 20, 9999, 10, "条"),
        ("daily_max_per_member", "每人每天最多几条", "int", 1, 999, 1, "条"),
        ("ai_no_owner_max", "一轮里最多几条", "int", 1, 120, 1, "条"),
        ("ai_chain_max", "连续接话上限", "int", 0, 40, 1, "条"),
        ("responders", "我发言时几个人回", "int", 1, 20, 1, "人"),
        ("bubbles_per_turn", "一次最多几条气泡", "int", 1, 20, 1, "条"),
        ("min_gap_member_sec", "同一人两次发言间隔", "int", 0, 600, 5, "秒"),
        ("chain_reply_probability", "有人说完后别人接话的概率", "pct", 0, 100, 5, "%"),
        ("ambient_gap_lo", "群自己起话头的最小间隔", "int", 1, 240, 1, "分"),
        ("ambient_gap_hi", "群自己起话头的最大间隔", "int", 1, 480, 1, "分"),
        ("ambient_enabled", "让群自己起话头", "bool", 0, 1, 1, ""),
    ]

    def _load_limits(self) -> None:
        """把落在这个群库里的覆盖值套回去（重启也保留）。"""
        saved = self.store.kv_get("limits") or {}
        if not isinstance(saved, dict):
            return
        for key, _label, kind, lo, hi, _step, _unit in self.LIMIT_SPECS:
            if key not in saved:
                continue
            value = saved[key]
            try:
                if kind == "bool":
                    setattr(self.gcfg, key, bool(value))
                elif kind == "int":
                    # ★ 必须落成 int：整型参数一旦是 float，凡是拿它当切片
                    #   下标的地方（如 pick 的 [:limit]）会抛 TypeError，
                    #   表现为「我在群里说话没人理」（实测事故）。
                    setattr(self.gcfg, key,
                            max(int(lo), min(int(hi), int(float(value)))))
                else:
                    setattr(self.gcfg, key, max(lo, min(hi, float(value))))
            except (TypeError, ValueError):
                continue

    def limits_payload(self) -> List[Dict[str, Any]]:
        """给界面用：每条限制的当前值 + 滑杆范围。"""
        out: List[Dict[str, Any]] = []
        for key, label, kind, lo, hi, step, unit in self.LIMIT_SPECS:
            raw = getattr(self.gcfg, key, 0)
            if kind == "bool":
                value: Any = 1 if raw else 0
            elif kind == "pct":
                value = int(round(float(raw) * 100))
            else:
                value = int(float(raw))
            out.append({"key": key, "label": label, "kind": kind,
                        "min": lo, "max": hi, "step": step, "unit": unit,
                        "value": value})
        return out

    def apply_limits(self, values: Dict[str, Any]) -> List[Dict[str, Any]]:
        """改几个值：按白名单校验 → 写进自己的 gcfg → 落盘到群库。"""
        saved = self.store.kv_get("limits") or {}
        if not isinstance(saved, dict):
            saved = {}
        for key, _label, kind, lo, hi, _step, _unit in self.LIMIT_SPECS:
            if key not in (values or {}):
                continue
            value = values.get(key)
            try:
                if kind == "bool":
                    real: Any = bool(value)
                    saved[key] = real
                else:
                    n = max(float(lo), min(float(hi), float(value)))
                    # ★ 整型参数必须存成 int：面板拖过之后的 5.0 走到切片
                    #   下标会把整条群管线打断（实测「我在群里说话没人理」）。
                    if kind == "pct":
                        real = n / 100.0
                    elif kind == "int":
                        real = int(n)
                    else:
                        real = n
                    saved[key] = real
            except (TypeError, ValueError):
                continue
            setattr(self.gcfg, key, real)
        self.store.kv_set("limits", saved)
        print(f"[group:{self.gid}] 节奏参数已更新：{sorted(saved)}")
        return self.limits_payload()

    # ---------------- 我发言 → 一轮回应 ----------------

    async def on_owner_message(self, msg: IncomingMessage) -> None:
        """我在群里说了话。

        ★ 顺序很重要：**先落库、先广播给每个成员的记忆，再判禁言**。
        「全员禁言」的语义是「她们都看到了，但都不回」—— 所以禁言只拦
        生成，不拦记录；解禁后靠 backlog 游标把没回的那些补回来。
        """
        text = (msg.text or "").strip()
        if not text and not msg.images:
            return
        segments = (msg.raw or {}).get("message")
        show = text or "[图片]"
        # 我先前的「消失」时长：用于「刚回来」的情绪，以及落地后清零
        idle_h = self._owner_idle_h(time.time())
        reply_to = self._resolve_reply(msg)
        row = self.owner_say(show, segments=segments, reply_to=reply_to)
        # 我这条消息的实时 id（随机序号）和库内 mid 对不上，记一份对照，
        # 好让「引用我自己刚发的那条」也能解析出库内 id。
        # ★ 必须**紧接着** owner_say 记下来：下面那步情绪打标是一次 LLM 调用
        #   （几秒），排在它后面的话，我在这几秒里引用这条消息就查不到对照，
        #   引用块会丢（实测：引用自己刚发的消息，历史里 reply_to=0）。
        self._remember_mid_alias(str(msg.message_id or ""),
                                 str(row.get("mid") or ""))
        # ★ 再判一下我这条是不是「需要被接住」（倾诉/受挫）。后面挑人时的
        #   提示词要整段换掉：不是「讲你自己」，而是「先接住他」。
        comfort = await self._detect_comfort(show)
        self._owner_ts = time.time()
        self._roll_round(self._owner_ts)
        # 我开口 → 这是「新的一轮」的起点：重置连续接话计数
        self._ai_chain = 0
        self._round_count = 0
        self._cooldown_until = 0.0
        # 我回来了 → 「群里被晾着」的那口气松掉（只有真的等过才算）
        if idle_h >= 2.0:
            self._reunion_all(idle_h)

        muted = self.is_muted()
        keep = [] if muted else None
        # 进她们的记忆；禁言时**不推进游标**（留 backlog，解禁后补回）
        self.notify_members(f"{OWNER_LABEL}：{show}", advance=not muted)
        if muted:
            print(f"[group:{self.gid}] 全员禁言中：我的消息已记录（{len(self.ai_member_ids())} 人看到了），暂无人回")
            return
        if self._silent():
            print(f"[group:{self.gid}] 请勿打扰：我不回应群里的消息")
            return

        mentioned_ids, mention_all = _mentions(segments)
        # ★ 「在句子里直接叫名字」也算点名：用户实测「call 了凯伊她不出来说话」
        #   —— 很多时候是打字写她的名字（没有 at 段），真人语境里这就是点名。
        mentioned_ids |= self._named_mentions(show)
        limit = (self.gcfg.responders_all_mention if mention_all
                 else self.gcfg.responders)
        picks = self.pick(show, limit, mentioned_ids, mention_all,
                          self.recent_speakers(2))
        # ★ 全员都到每日上限时，群里会对我**完全静默**（实测：我说「哈喽」
        #   之后 15 分钟没人应 —— 因为挑人阶段全被每日额度切掉了）。
        #   真人从来不集体无视你，所以兜底：放宽额度也要挑出人来回应，
        #   并且按「被点名」待遇放行额度闸门（不然挑出来又会被 can_speak 拦掉）。
        over_cap = False
        if not picks:
            picks = self.pick(show, limit, mentioned_ids, mention_all,
                              self.recent_speakers(2), allow_over_cap=True)
            over_cap = bool(picks)
        if not picks:
            return
        print(f"[group:{self.gid}] 我发言 → 挑中 {len(picks)} 人回应：{picks}"
              + ("（全员已到每日额度，放宽额度兜底）" if over_cap else ""))
        # ★ 真人群聊不是「一人一句轮播」：实测相邻两条消息里 69% 是换人说的，
        #   其中 34% 在 5 秒内、60% 在 15 秒内 —— 大家是**前后脚各自开口**，
        #   气泡交错着叠在一起。旧写法给每个回应者串行 `await sleep(6~25s)`，
        #   于是永远是「A 说完 → B 才开始」，就是用户说的「版聊」。
        #   现在给每个人一个**各自独立**的开口延迟，并发跑（生成仍由 _gen_lock
        #   串行，保证 LLM 不被并发打满；发送已是锁外，气泡可以真交错）。
        lo, hi = (list(self.gcfg.responder_gap_sec or [2, 18]) + [2, 18])[:2]
        tasks: List[asyncio.Task] = []
        for cid in picks:
            m = self._member_getter(cid)
            if not m:
                continue
            called = mention_all or (cid in mentioned_ids)
            # 额度闸门放行条件：
            #  · called  —— 被 @ 或叫了名字
            #  · over_cap —— 全员额度耗尽时的兜底
            #  · 她在睡   —— 我直接说话把她吵醒了；真人被吵醒也会迷迷糊糊答一句
            #    （否则凌晨我发「哈喽」又会是一片安静 —— 那正是用户最烦的）
            bypass = called or over_cap or self._asleep(m)
            if comfort:
                # ★ 情绪优先：先接住我，别各说各的、别急着换话题。
                hint = (f"{OWNER_LABEL}刚在群里说：{show[:80]}\n"
                        "他现在心里不好受，需要有人接住。**这一轮先别讲你自己"
                        "今天干嘛**：先关心他、替他抱不平、安慰他；不要说教、"
                        "别急着给建议、别把话题转到你身上。")
            elif called:
                hint = (f"{OWNER_LABEL}刚才在群里叫了你"
                        "（@ 了你，或者提了你的名字），点名让你说话。")
            elif over_cap:
                hint = (f"{OWNER_LABEL}刚才在群里说：{show[:60]}\n"
                        "你回他一句 —— 别因为大家都没接就晾着他。")
            else:
                # ★ 没被 @ 的人也要明确「现在要接的是我刚说的那句」。
                #   以前这里 hint 为空，模型只看到最近 24 条群消息，就会自己
                #   挑一句接 —— 于是出现「A 早说过的话被 B 现在才接」的错位感。
                hint = (f"{OWNER_LABEL}刚才在群里说：{show[:60]}\n"
                        "你回应他一句就行 —— 主要说说**你自己眼下在干嘛**，"
                        "别复述他提到的那些具体东西，也别顺着那个话题往下扯。")
            tasks.append(asyncio.create_task(self._respond_later(
                cid, random.uniform(float(lo), float(hi)),
                hint=hint, reply_to=int(row["id"]), user_text=show,
                mentioned=bypass, reply_to_owner=not called,
                # ★ 回群主不受「全群今日总量」限制（否则说满 120 条后我说话
                #   全员静默）；被点名时的其他额度闸门早已在 bypass 里放开。
                ignore_total=True)))
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self.advance_cursors_except(picks)
        # 争宠（走真实情绪状态机）：我点名别人 → 其他人酸；只是没人被点名
        # → 没被挑中的那几位有点失落。强度远小于「我被冷落」，且各自节流。
        if mentioned_ids or mention_all:
            self.spark_jealousy(picks[0] if picks else "", 0.5, excluded=picks)
        else:
            self.mark_ignored(picks, 0.25)
        # ★ 我刚把群里聊热了 → 也允许有人过一会儿把这段「讲给我听」
        #   （以前只有群自己的节奏会掷这个骰子，我发言引出的热闹永远不会触发）
        if picks:
            self._kick_dm_share(random.choice(picks))

    async def _respond_later(self, cid: str, delay: float, *, hint: str,
                             reply_to: int = 0, user_text: str = "",
                             mentioned: bool = False,
                             reply_to_owner: bool = False,
                             chained_from: str = "",
                             ignore_total: bool = False) -> None:
        """过 `delay` 秒开口（每个回应者各自延迟，互不排队）。"""
        try:
            if delay > 0:
                await asyncio.sleep(delay)
        except asyncio.CancelledError:
            raise
        if self.is_muted() or self._silent():
            return
        await self.speak(cid, hint=hint, reply_to=reply_to,
                         user_text=user_text, reply_to_owner=reply_to_owner,
                         mentioned=mentioned, chained_from=chained_from,
                         ignore_total=ignore_total)

    # ---------------- 群聊场景（让她们意识到「我在群里说话」）----------------

    def _group_scene(self, m: Member, chained_from: str = "",
                     reply_to_owner: bool = False,
                     avoid: Optional[List[str]] = None) -> str:
        """群发言专用的场景块。

        用户反馈：群里全在聊「米粉」，注意力死死咬住一个话题（对照真实群：
        相邻两条共享话题词只有 10%，我们却有 58%）。原先这句笼统的
        「别像接力赛」拦不住 —— 模型会照抄上下文里那个现成的名词。所以这里
        改成**具体、可执行**的硬规矩，并把近期说烂的词直接点名。

        另一条：真实群里单条中位只有 9~13 字，我们的却有 29 字 —— 一条里塞
        三件事，等于给下一个人递三根话题钩子。所以「短、一条一事」也要写明。
        """
        others = [mm.name for mm in
                  (self._member_getter(c) for c in self.ai_member_ids())
                  if mm and mm.id != m.id]
        who = "、".join(others) if others else "（暂时只有你）"
        comfort = self._in_comfort()
        lines = [
            "【场景】这是**群聊**，不是一对一私聊。",
            f"- 群里的人：{who}，还有「{OWNER_LABEL}」。你现在是「{m.name}」。",
            f"- ⚠️ 你是「{m.name}」，**不是**群里其他任何人（也别拿别人的名字"
            "自称，比如星野/小星）；你有你自己的名字和身份。",
            "- 你这句话是**当众**说的，群里每个人都看得到 —— 所以别把它讲成"
            "只有你们俩知道的事。",
            "- 下面【最近的对话】只是**背景**，是别人在聊的事。你看一眼就行，"
            "**不用接、也别复述里面说过的具体东西**。",
            "- 群里说话比私聊更短更碎：**一句就够，一条只说一件事，每条不超过 "
            "15 字**（真人群里单条中位才 9~13 字）。别把三件事塞进一条里。",
        ]
        if comfort:
            # ★ 情绪优先：他刚说了件难受的事 —— 这时候「各说各的」是错的。
            lines += [
                f"- ★★ 「{OWNER_LABEL}」刚说了件让他不好受的事，**这几轮重点是"
                "接住他**：先说一句心疼/抱不平/安慰，再聊别的。",
                "- 不要说教、不要急着给解决方案、不要马上把话题转到你自己身上；"
                "也别只回一个「嗯」就完了。",
            ]
        else:
            lines += [
                "- ★ **讲你自己眼下在干嘛**：你手头的事、你刚看到的、你的心情。"
                "这才是群里大多数话的样子 —— 各说各的，偶尔才有人搭一句。",
                "- ⚠️ **别像接力赛那样句句都挂在上一条上**，也别把上一条里出现的"
                "**具体名词**（吃的、地点、排队、价格、某样东西）再搬出来一遍。",
                "- ⚠️ 多数消息**不要以问句结尾**（真人群里只有 6% 的话是问句）；"
                "想问也别每个话题都问，更别追着同一个问题反复问。",
            ]
        lines += [
            "- 别点某个人的名字去点名（那是开会点名，不是聊天）；偶尔叫一下就行。",
            "- 说出来的话里**不要出现「群」「群里」这类词**（真人不会这么讲）。",
            "- 如果确实没什么想说的，只输出：[NO_MESSAGE]",
        ]
        if chained_from:
            lines.append(f"- 群里「{chained_from}」刚说了一句。**你可以完全不接** "
                         "—— 说说你自己眼下的事就行。")
        if reply_to_owner:
            lines.append(f"- 这段话主要是接「{OWNER_LABEL}」刚在群里说的那句。")
        if avoid and not comfort:
            lines.append(
                "- 🚫 群里最近**反复提到、已经说烂**的词：" + "、".join(avoid[:8])
                + " —— 这一轮**一个都别再出现**，换成你自己的事。")
        return "\n".join(lines)

    # ---------------- 群自己的节奏 ----------------

    def _ambient_gap(self) -> float:
        base = (list(self.gcfg.ambient_gap_min or [8, 25]) + [8, 25])[:2]
        lo = float(getattr(self.gcfg, "ambient_gap_lo", None) or base[0])
        hi = float(getattr(self.gcfg, "ambient_gap_hi", None) or base[1])
        if hi < lo:
            lo, hi = hi, lo
        return random.uniform(lo, hi) * 60.0

    # ---------------- 接话：让群里的话有人接 ----------------
    # 用户反馈：「A 说了话没人接，等我发消息 B 才突然接 A 的话」。
    # 根因是群里的发言只有两个来源 —— 我开口、或 8~25 分钟一次的自发话题；
    # 自发这条又被「刚有人说过话就别说」的守卫按住，于是 A 说完之后要等很久
    # 才会有人理，看起来就像「大家都在等你开口」。这里补一个短窗口的反应：
    # 有人说完话之后，过 10~50 秒让另一个人接一句（仍受链长/预算/复读拦截约束）。

    def _name_of(self, cid: str) -> str:
        m = self._member_getter(cid)
        return m.name if m else str(cid)

    def _kick_chain(self, speaker: str) -> None:
        if self._stop.is_set():
            return
        if random.random() > float(self.gcfg.chain_reply_probability):
            return
        if self._chain_task and not self._chain_task.done():
            return                              # 上一波反应还没跑完，先不叠
        self._chain_task = asyncio.create_task(self._chain_reply(speaker))

    async def _chain_reply(self, speaker: str) -> None:
        """过一小会儿，让另一个人接上「刚刚那句话」。"""
        lo, hi = (list(self.gcfg.chain_reply_gap_sec or [10, 50]) + [10, 50])[:2]
        try:
            await asyncio.sleep(random.uniform(float(lo), float(hi)))
        except asyncio.CancelledError:
            raise
        if self.is_muted() or self._silent():
            return
        rows = self.store.recent_gmsgs(1, include_revoked=False)
        if not rows:
            return
        last = rows[-1]
        # 我们睡觉这段时间群里已经有新动静了（我发言 / 别人接话 / 系统消息）
        # → 这一波反应作废，交给新的那一波处理
        if str(last.get("kind")) != KIND_CHAR:
            return
        if str(last.get("sender_id")) != str(speaker):
            return
        text = str(last.get("text") or "")
        picks = self.pick(text, 3, set(), False,
                          self.recent_speakers(2) | {str(speaker)})
        # 刚说完的那个人不能自己接自己（pick 只是降权、不排除）
        picks = [p for p in picks if str(p) != str(speaker)]
        if not picks:
            return
        # ★ 真群里一条消息之后 60 秒里平均有 2.59 个**不同的人**开口 ——
        #   只让一个人接（且必须等他说完）就是「版聊」。这里放 1~2 人，
        #   第二个人用独立的延迟，两个人的气泡可以堆在一起。
        n = 2 if (len(picks) > 1 and random.random() < 0.45) else 1
        tasks: List[asyncio.Task] = []
        for k, cid in enumerate(picks[:n]):
            ok, why = self.can_speak(cid)
            if not ok:
                print(f"[group:{self.gid}] 接话被拦（{self._name_of(cid)}）：{why}")
                continue
            print(f"[group:{self.gid}] 接话：{self._name_of(cid)} 接 "
                  f"{self._name_of(speaker)} 的那句")
            if self._in_comfort():
                hint = ("老师刚说了件让他难受的事，群里正等着有人接住他 —— "
                        "你接一句，先关心他/替他抱不平，别讲你自己今天干嘛。")
            else:
                hint = (f"群里「{self._name_of(speaker)}」刚说：{text[:60]}\n"
                        "你不用接他这句，也不用提他说的东西 —— 说说**你自己"
                        "眼下的事**就行（一句，别超过 15 字）。")
            tasks.append(asyncio.create_task(self._respond_later(
                cid, 0.0 if k == 0 else random.uniform(4.0, 25.0),
                hint=hint,
                reply_to=int(last.get("id") or 0),
                chained_from=self._name_of(speaker))))
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    # ---------------- 私聊片段 → 群（好友抖私聊）----------------
    # 用户明确要的：「好友在群里会转发/分享我和他们聊天的内容」。
    # 不真做「转发」那种生硬的消息卡片 —— 真人也从不这么说；而是让她把
    # 私聊里的那件事用**自己的口气**带进群里（可能带得意/吃醋/抱怨），
    # 复读拦截与频率预算照旧生效。

    def _private_snippet(self, cid: str, hours: float = 12.0,
                         limit: int = 140) -> str:
        """取她和我私聊里最近的一段（短文，够她起个话头）。"""
        m = self._member_getter(cid)
        if not m:
            return ""
        try:
            turns = m.store.recent_turns(12)
        except Exception:  # noqa: BLE001
            return ""
        if not turns:
            return ""
        cutoff = time.time() - hours * 3600
        # ★ recent_turns 是**按时间正序**返回的（旧 → 新），别当新→旧用
        picked = [t for t in turns if float(t.get("ts") or 0) >= cutoff]
        if not picked:
            return ""
        lines: List[str] = []
        for t in picked[-6:]:
            who = "我" if str(t.get("role")) == "user" else m.name
            txt = str(t.get("text") or "").replace("\n", " / ")[:60]
            if txt:
                lines.append(f"{who}：{txt}")
        return "\n".join(lines)[-limit:]

    def _day(self) -> str:
        return time.strftime("%Y-%m-%d")

    def _share_budget_ok(self, cid: str) -> bool:
        used = int(self.store.kv_get(f"share:{self._day()}:{cid}", 0) or 0)
        return used < int(self.gcfg.share_daily_max)

    def note_share(self, cid: str) -> None:
        key = f"share:{self._day()}:{cid}"
        self.store.kv_set(key, int(self.store.kv_get(key, 0) or 0) + 1)

    def _share_candidates(self, limit: int = 4) -> List[str]:
        """能抖私聊的人：有近期私聊、今天还没抖过；好感高的优先。"""
        out: List[Tuple[int, str]] = []
        for cid in self.ai_member_ids():
            m = self._member_getter(cid)
            if not m or not self._share_budget_ok(cid):
                continue
            if not self._private_snippet(cid):
                continue
            out.append((m.affection, cid))
        out.sort(key=lambda x: -x[0])
        return [cid for _a, cid in out[:limit]]

    async def share_private_to_group(self, cid: str) -> Optional[str]:
        """她把和我私聊里的一段带进群里说。"""
        snippet = self._private_snippet(cid)
        if not snippet or not self._share_budget_ok(cid):
            return None
        hint = ("下面这段是你和" + OWNER_LABEL + "在私聊里刚说的"
                "（**不是群里别人说的话**，也别说「聊天记录 / 截图 / 转发」"
                "这类词）：\n" + snippet +
                "\n现在你想把这件事带到群里说一句 —— 用你自己的口气，"
                "可以带点得意、吃醋或抱怨，1~3 条短句。")
        out = await self.speak(cid, hint=hint, share_kind="group_share")
        if out:
            self.note_share(cid)
            # 她把私聊抖进群 → 别人被抢了注意力
            self.spark_jealousy(cid, 0.5)
            self._kick_chain(cid)
        return out

    # ---------------- 争宠：吃醋 / 被冷落（走真实情绪状态机）----------------

    def _jealousy_ok(self, m: Member, key: str, now: float) -> bool:
        """每人每种情绪有冷却，避免群里一有动静就全员吃醋。"""
        k = f"gjeal:{self.gid}:{key}"
        try:
            last = float(m.store.kv_get(k, 0) or 0)
        except Exception:  # noqa: BLE001
            last = 0.0
        if now - last < self.gcfg.jealousy_cooldown_min * 60:
            return False
        try:
            m.store.kv_set(k, now)
        except Exception:  # noqa: BLE001
            pass
        return True

    def _emotional_scale(self, m: Member) -> float:
        """占有欲 / 依恋越强越容易酸。"""
        try:
            rel = m.state.relationship
            return (0.4
                    + 0.9 * (float(getattr(rel, "possessiveness", 20.0)) / 100.0)
                    + 0.5 * (float(getattr(rel, "attachment", 40.0)) / 100.0))
        except Exception:  # noqa: BLE001
            return 0.7

    def spark_jealousy(self, speaker_cid: str = "", base: float = 0.5,
                       excluded: Optional[List[str]] = None) -> List[str]:
        """有人抢走了我的注意力 → 其他人酸一下。返回被点着的人。

        只有好感够高（jealousy_min_affection）才真在意 —— 泛泛之交不会吃醋。
        """
        now = time.time()
        skip = {str(x) for x in (excluded or [])}
        if speaker_cid:
            skip.add(str(speaker_cid))
        out: List[str] = []
        for cid in self.ai_member_ids():
            if cid in skip:
                continue
            m = self._member_getter(cid)
            if not m:
                continue
            if m.affection < int(self.gcfg.jealousy_min_affection):
                continue
            if not self._jealousy_ok(m, "j", now):
                continue
            intensity = max(0.15, min(1.0, float(base) * self._emotional_scale(m)))
            try:
                m.state.apply_event("jealousy", intensity)
            except Exception as e:  # noqa: BLE001
                print(f"[group:{self.gid}] 吃醋事件失败：{e!r}")
                continue
            out.append(cid)
        if out:
            print(f"[group:{self.gid}] 吃醋 ×{len(out)}：{out}")
        return out

    def mark_ignored(self, picked: List[str], base: float = 0.25) -> List[str]:
        """我说话但没点到她 → 有点失落（强度比吃醋轻）。"""
        now = time.time()
        keep = {str(x) for x in (picked or [])}
        out: List[str] = []
        for cid in self.ai_member_ids():
            if cid in keep:
                continue
            m = self._member_getter(cid)
            if not m:
                continue
            if m.affection < int(self.gcfg.jealousy_min_affection):
                continue
            if not self._jealousy_ok(m, "i", now):
                continue
            try:
                m.state.apply_event("ignored",
                                    max(0.1, min(0.6, float(base))))
            except Exception:  # noqa: BLE001
                continue
            out.append(cid)
        return out

    # ---------------- 群里的动静 → 私聊（她来找我告状）----------------

    def _recent_group_snippet(self, limit: int = 160) -> str:
        rows = self.store.recent_gmsgs(8, include_revoked=False)
        lines: List[str] = []
        for r in rows:
            if str(r.get("kind")) == KIND_SYSTEM:
                continue
            txt = str(r.get("text") or "").replace("\n", " / ")[:50]
            if txt:
                lines.append(f"{self._speaker_label(r)}：{txt}")
        return "\n".join(lines)[-limit:]

    def _dm_budget_ok(self, cid: str) -> bool:
        used = int(self.store.kv_get(f"dm:{self._day()}:{cid}", 0) or 0)
        return used < int(self.gcfg.dm_share_daily_max)

    def _dm_candidates(self, limit: int = 4) -> List[str]:
        out: List[Tuple[int, str]] = []
        for cid in self.ai_member_ids():
            m = self._member_getter(cid)
            if not m or not self._dm_budget_ok(cid):
                continue
            if m.affection < int(self.gcfg.jealousy_min_affection):
                continue
            out.append((m.affection, cid))
        out.sort(key=lambda x: -x[0])
        return [cid for _a, cid in out[:limit]]

    def _kick_dm_share(self, cid: str) -> None:
        """过一小会儿把群里这段动静私聊讲给我听（我发言引发的那种也算）。

        和接话同样是「延迟一小会儿」的任务，避免她刚在群里说完就立刻私聊
        复述一遍（那会很怪）。仍然受每人每日 dm 上限约束。
        """
        if self._stop.is_set() or not cid:
            return
        if not self._dm_budget_ok(cid):
            return
        if random.random() > float(self.gcfg.dm_share_probability):
            return
        if self._dm_task and not self._dm_task.done():
            return
        self._dm_task = asyncio.create_task(self._dm_share_later(cid))

    async def _dm_share_later(self, cid: str) -> None:
        try:
            await asyncio.sleep(random.uniform(25.0, 120.0))
        except asyncio.CancelledError:
            raise
        try:
            await self.share_group_to_owner(cid)
        except asyncio.CancelledError:
            raise
        except Exception as e:  # noqa: BLE001
            print(f"[group:{self.gid}] 私聊分享出错：{e!r}")

    async def share_group_to_owner(self, cid: str) -> bool:
        """她把群里刚发生的事**私聊**讲给我听（看到好玩的来告状）。

        直接走 Sender 的私聊通道 —— 发送锁的键是 (user_id, group_id,
        sender_id)，和私聊主管线用的是同一把，所以不会和她的私聊回复交错；
        发出去之后补一条 transcript，私聊窗口重开时回放才对得上。
        """
        if self.is_muted() or self._silent() or not self._dm_budget_ok(cid):
            return False
        m = self._member_getter(cid)
        if not m:
            return False
        ok, why = self.can_speak(cid)
        if not ok:
            return False
        snippet = self._recent_group_snippet()
        if not snippet:
            return False
        hint = ("下面这段是群里刚刚的对话（**不是" + OWNER_LABEL +
                "单独跟我说的话**）：\n" + snippet +
                f"\n现在你想把群里这件事单独讲给{OWNER_LABEL}听 —— 像看到"
                "好玩的东西忍不住来找他说，1~2 条短句，别提「群」这个字。")
        async with self._gen_lock:
            try:
                draft = await self._draft(m, hint=hint, share_kind="group_share")
                bubbles = self._as_bubbles(draft, 2)
            except Exception as e:  # noqa: BLE001
                print(f"[group:{self.gid}] 私聊分享生成失败：{e!r}")
                return False
        if not bubbles:
            return False
        text = "\n".join(bubbles)
        if self.dup_reason(text):
            return False
        try:
            sent = await self.sender.reply_bubbles(
                bubbles, user_id=self.owner_id(), sender_id=cid,
                sender_name=m.name, delay_scale=m.delay_scale)
        except Exception as e:  # noqa: BLE001
            print(f"[group:{self.gid}] 私聊分享发送失败：{e!r}")
            return False
        if sent:
            key = f"dm:{self._day()}:{cid}"
            self.store.kv_set(key, int(self.store.kv_get(key, 0) or 0) + 1)
            try:
                m.store.add_turn("assistant", text[:800])
                m.store.add_event(
                    f"[群「{self.group.name}」] 我把群里的事私聊讲给他听",
                    kind=f"group:{self.gid}")
            except Exception:  # noqa: BLE001
                pass
            print(f"[group:{self.gid}] {m.name} 私聊分享群里的动静：{text[:40]}")
        return bool(sent)

    async def tick_once(self, now: Optional[float] = None) -> Optional[str]:
        """群自己到点说一句（不定时有人起话头）。可注入 now 做确定性测试。"""
        now = now or time.time()
        if not self.gcfg.ambient_enabled or not self.gcfg.enabled:
            return None
        if self.is_muted() or self._silent():
            return None
        # 我很久没露面 → 她们的「被晾着」要跟着涨（和说不说话无关）
        self.apply_group_waiting(now)
        self._roll_round(now)
        if now < self._cooldown_until:
            return None
        # 群里刚有人说过话就别抢话（避免「环境自发」变成连续剧）。
        # ★ 这道守卫必须跟着可调间隔走：用户把「群自己起话头的最小间隔」
        #   调到 1 分钟时，写死的 90 秒会把它永远挡住（等于调了没生效）。
        guard = min(90.0, max(15.0, float(self.gcfg.ambient_gap_lo or 8) * 60.0 * 0.6))
        rows = self.store.recent_gmsgs(1, include_revoked=False)
        if rows and now - float(rows[-1].get("ts") or 0) < guard:
            return None

        # ① 先掷骰子：这次是「抖一段私聊进群」吗（用户要的转发/分享）
        if random.random() < float(self.gcfg.ambient_share_probability):
            cands = self._share_candidates()
            if cands:
                out = await self.share_private_to_group(random.choice(cands))
                if out:
                    return out
        # ② 再掷一次：把群里的动静私聊讲给我听
        if random.random() < float(self.gcfg.dm_share_probability):
            cands = self._dm_candidates()
            if cands:
                if await self.share_group_to_owner(random.choice(cands)):
                    return "[dm]"

        # ③ 平时的自发话头
        last = self._last_owner_text()
        picks = self.pick(last or self.group.name, 1, set(), False,
                          self.recent_speakers(3))
        if not picks:
            return None
        cid = picks[0]
        hint = ("群里你有一阵没说话了 —— 起一个你自己的话头："
                "你刚做的事、看到的东西、想到的事，随口说出来。"
                "别追问别人的私事，别问「在吗」。")
        out = await self.speak(cid, hint=hint, share_kind="group")
        if out:
            self._kick_chain(cid)          # ★ 让这句话在群里有人接
        return out

    async def run(self) -> None:
        """群自己的节奏循环。"""
        # 首轮别等太久：原来的 30~120 秒在「最小间隔 1 分钟」的设置下显得很拖
        await asyncio.sleep(random.uniform(10.0, 40.0))
        while not self._stop.is_set():
            try:
                await self.tick_once()
            except Exception as e:  # noqa: BLE001
                print(f"[group:{self.gid}] 自发话题出错：{e!r}")
            try:
                await asyncio.wait_for(self._stop.wait(),
                                       timeout=self._ambient_gap())
            except asyncio.CancelledError:
                raise
            except asyncio.TimeoutError:
                pass
            except Exception:  # noqa: BLE001
                pass

    def start(self) -> None:
        if self._task and not self._task.done():
            return
        self._task = asyncio.create_task(self.run())

    def stop(self) -> None:
        self._stop.set()

    def close(self) -> None:
        self.stop()
        for t in (self._chain_task, self._dm_task):
            if t and not t.done():
                t.cancel()
        self._chain_task = None
        self._dm_task = None
        if self._task and not self._task.done():
            self._task.cancel()
        self._task = None

    # ---------------- 禁言 / 公告 ----------------

    def set_mute_all(self, on: bool, by: str = "") -> Dict[str, Any]:
        st = self.store.set_mute_all(on, by=by)
        name = "全员禁言" if on else "解除全员禁言"
        self.system(f"{by or OWNER_LABEL} 开启了{name}" if on
                    else f"{by or OWNER_LABEL} 解除了全员禁言")
        if not on and self._backlog_pending():
            asyncio.create_task(self.backlog_wave())
        return st

    def _backlog_pending(self) -> bool:
        """有没有「禁言期间发过、但没人回」的消息。"""
        rows = self.store.recent_gmsgs(1, include_revoked=False)
        if not rows:
            return False
        last_id = int(rows[-1]["id"])
        return any(self.store.cursor(cid) < last_id
                   for cid in self.ai_member_ids())

    def backlog_text(self, limit: int = 600) -> str:
        """禁言期间攒下的内容（截断），喂给解禁后的第一条。"""
        parts: List[str] = []
        for r in self.store.recent_gmsgs(40, include_revoked=False):
            if str(r.get("kind")) != KIND_USER:
                continue
            parts.append(str(r.get("text") or ""))
        text = " / ".join(p for p in parts if p)
        return text[-limit:]

    async def backlog_wave(self) -> None:
        """解禁后补一次：挑几个人把禁言期间没回的话回掉（**只跑一次**）。"""
        keep: List[str] = []
        text = self.backlog_text()
        if not text:
            return
        picks = self.pick(text, self.gcfg.backlog_responders, set(), False,
                          self.recent_speakers(3))
        print(f"[group:{self.gid}] 解禁补话：{len(picks)} 人")
        lo, hi = (list(self.gcfg.backlog_span_sec or [20, 90]) + [20, 90])[:2]
        for i, cid in enumerate(picks):
            if i:
                await asyncio.sleep(random.uniform(float(lo), float(hi)))
            if self.is_muted() or self._silent():
                break
            await self.speak(cid,
                             hint=f"（刚才群里禁言了一阵，这是期间{OWNER_LABEL}说的："
                                  f"{text}）你现在可以接着这些说一句。",
                             share_kind="group")
            keep.append(cid)
        self.advance_cursors_except(keep)

    def post_announcement(self, text: str, by: str = "") -> Dict[str, Any]:
        """发群公告：落库 + 每个成员都记一条（＝她们都看到了）。"""
        a = self.store.set_announcement(text, by=by)
        self.system(f"{by or OWNER_LABEL} 发布了新公告")
        for cid in self.ai_member_ids():
            m = self._member_getter(cid)
            if not m:
                continue
            try:
                m.store.add_event(f"[群「{self.group.name}」公告] {text[:120]}",
                                  kind=f"group:{self.gid}")
            except Exception:  # noqa: BLE001
                pass
        return a
