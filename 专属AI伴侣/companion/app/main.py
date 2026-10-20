"""入口：装配所有模块，起 WS 服务 + 后台心跳。

运行：
    cd companion
    python -m app.main
"""
from __future__ import annotations

import asyncio
import base64
import io
import json
import os
import random
import re
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Dict, List, Optional

from .act import Sender
from .autonomy.conversation import ConversationRunner, is_closing_text
from .autonomy.digest import Digest
from .autonomy.heartbeat import Heartbeat
from .autonomy.search import build_provider
from .autonomy.suppress import Suppressor
from .channel.napcat import (
    IncomingMessage, NapCatChannel, PortInUse, dump_raw_event, format_event_brief,
)
from .channel.onebot_server import OneBotServerChannel
from .characters import CharacterRegistry
from .config import Config, load_config
from .group import GroupRuntime, Member
from .group_store import GroupRegistry
from .guest import GuestRuntime
from .llm import LLM
from .memory import Memory
from .perceive import describe_image, load_first_image, tag_emotion
from .presence import (get_presence, greet_cooldown_ok, mark_greeted,
                       presence_payload, presence_text, set_status)
from .state import EMOTION_TO_EVENT, StateMachine
from .sticker import StickerLibrary, StickerPolicy, StickerStealer
from .store import Store
from .think import (analyze, express, extract_overused_terms, format_recent,
                    format_time_context, judge_sticker)
from .traits import (derive_autonomy, derive_conversation, ensure_defaults,
                     get_traits, save_traits, trait_preview, trait_text,
                     traits_payload)

HIGH_RISK = {"自伤倾向", "极端情绪"}

# schtasks 等命令行工具的输出按控制台代码页编码（中文系统是 GBK）
CONSOLE_ENC = "gbk" if os.name == "nt" else "utf-8"

# 互道收尾时的超短回应。收尾循环里再长篇大论就是恐怖片。
_SHORT_CLOSINGS = ("嗯，晚安", "晚安", "嗯嗯，拜拜", "好，明天见", "嗯，去忙吧")

# 角色「搜到群 → 想进来」时递的入群理由（真人申请入群也就这一句半句）
JOIN_REQUEST_NOTES = (
    "刷到这个群，想进来看看",
    "听人提过，有点好奇",
    "想找个地方一起聊天",
    "看看你们平时都在聊什么",
)

# 表情包相关的「收下/斗图/入库」说法 —— 真实聊天里极少出现（0.2%）。
# 除了提示词约束，再兜一层：模型偶尔会照抄历史里的旧句式，必须拦掉。
_META_STICKER_STRICT = re.compile(
    r"收下|收了|收进|存了|存图|归我|斗图|表情包库|图我")
_META_IMAGE_NARROW = re.compile(
    r"(图|图片|这张|表情包).{0,6}(收下|收了|收进|存了|存图|归我|归大叔)"
    r"|(收下|收了).{0,4}(图|表情包)"
    r"|斗图|表情包库")


def _short_src(src: str) -> str:
    """给候选来源一个可读的短标签（base64 只报估算字节数，否则刷屏）。"""
    if src.startswith("data:"):
        n = len(src)
        return f"base64 ≈ {n * 3 // 4} 字节"
    return src if len(src) <= 80 else src[:77] + "..."


def catchup_delay_ms(target_range: List[int], last_user_ts: float,
                     now: float) -> float:
    """★ 追时：把「响应延迟」从叠加改成总量控制。

    真人数据（3.8 万个对话段统计）：好友第一响应距对方**段末**中位 14s、
    P25 5s —— 这是**总时间**（阅读 + 打字都算在内）。
    而 vol 的耗时 = 合并等待 + 模型推理（10~30s，不可控）+ 出站延迟：
    原来出站延迟是**在处理完之后再额外加** 5~20s，总延迟轻松 40s+，
    比真人慢 2~4 倍 —— 体感「太机械太慢」的直接来源。

    做法：从 target_range 抽一个「目标总延迟」，减去已经花掉的时间
    （对方最后一条 → 现在），剩下的才是发送前要等的时间。
    处理快就多等会儿，处理慢就立即发 —— 总延迟始终贴着真人分布。
    """
    lo, hi = [float(x) for x in (list(target_range) + [5000, 20000])[:2]]
    target_total = random.uniform(lo, hi) / 1000.0
    if last_user_ts <= 0:
        return target_total * 1000.0        # 没有参照点（比如主动开口）→ 走原分布
    elapsed = max(0.0, now - last_user_ts)
    return max(0.0, target_total - elapsed) * 1000.0


class Companion:
    def __init__(self, cfg: Config, channel=None, llm=None):
        self.cfg = cfg
        self.characters = CharacterRegistry(cfg)
        # 「热情/好感」：每个角色一套，派生主动频率与回复节奏
        self.base_autonomy = cfg.autonomy
        self.base_conversation = cfg.conversation
        self.primary_traits = get_traits(self.characters.primary.id,
                                         self.characters.primary.name)
        ensure_defaults(self.characters.all())
        # ★ 在线状态（QQ 式）：叠在热情之上的一层乘数 —— 决定「你现在
        #   方不方便被找」。必须在派生配置之前读，否则初始排期用的是旧状态。
        self.presence = get_presence()
        self.presence_text = presence_text(self.presence)
        autonomy_cfg = derive_autonomy(self.base_autonomy, self.primary_traits,
                                       self.presence)
        conv_cfg = derive_conversation(self.base_conversation,
                                       self.primary_traits, self.presence)
        self._guests: Dict[str, GuestRuntime] = {}
        self._guest_pending: Dict[str, List[IncomingMessage]] = {}
        self._guest_tasks: Dict[str, asyncio.Task] = {}
        # 群聊：群索引 + 每个群一个引擎（懒创建）
        self.groups = GroupRegistry(cfg)
        self._group_runtimes: Dict[str, GroupRuntime] = {}
        self._group_scout_task: Optional[asyncio.Task] = None
        self.store = Store(cfg.resolve(cfg.memory.db_path))
        self._ignored_count = 0
        self._ignored_last_log = 0.0
        # 多条消息合并（debounce）—— 见 _queue_for_merge
        self._pending: List[IncomingMessage] = []
        self._pending_first_ts = 0.0
        self._merge_task: Optional[asyncio.Task] = None
        self.memory = Memory(self.store, cfg.persona_path("interests.md"))
        self.state = StateMachine(self.store)
        self.llm = llm or LLM(cfg.llm)
        self.stickers = StickerLibrary(cfg.resolve(cfg.memory.sticker_index))
        self.sticker_policy = StickerPolicy(cfg.sticker, self.store)
        self.stealer = StickerStealer(
            cfg.sticker, self.store, self.stickers,
            cfg.resolve(cfg.memory.sticker_dir),
        )
        self.dump_dir = cfg.resolve(cfg.memory.debug_dir)
        # 通道选择：onebot-server = 自托管（Stapxs 等客户端直连 vol，
        # 不碰 QQ）；默认 napcat = 旧 QQ 链路（NapCat 反向 WS）
        self.channel_kind = (getattr(cfg.qq, "channel", "napcat") or "napcat").lower()
        if channel is not None:
            self.channel = channel            # 测试注入
        elif self.channel_kind == "onebot-server":
            self.channel = OneBotServerChannel(
                cfg.qq, self.handle,
                store=self.store,
                sticker_dir=cfg.resolve(cfg.memory.sticker_dir),
                dump_dir=self.dump_dir,
                webapp_dir=cfg.resolve("data/webclient"),
                legacy_webapp_dir=cfg.resolve("data/webapp"),
                sticker_lib=self.stickers,
                characters=self.characters,
                store_for=self.store_for,
                settings_get=self.get_settings,
                settings_set=self.save_settings,
                character_creator=self.create_character,
                traits_get=self.get_character_traits,
                traits_set=self.set_character_traits,
                presence_get=self.get_presence,
                presence_set=self.set_presence,
                group_api=self,
            )
        else:
            self.channel = NapCatChannel(cfg.qq, self.handle, dump_dir=self.dump_dir)
        self.sender = Sender(self.channel, cfg.behavior)

        self.search = build_provider(cfg.search)
        search = self.search
        self.digest = Digest(autonomy_cfg, cfg.memory, self.llm, self.memory,
                             self.state, self.store, search)
        self.suppressor = Suppressor(autonomy_cfg, self.store, self.llm,
                                     self.state, self.memory)
        self.heartbeat = Heartbeat(
            autonomy_cfg, cfg.qq, self.store, self.llm, self.state, self.memory,
            self.suppressor, self.sender, self.digest, cfg.read_persona,
            trait_text=trait_text(self.primary_traits),
            delay_scale=self.primary_traits.delay_scale,
            presence_text=self.presence_text,
            schedule=self.characters.primary.schedule,
        )
        self.conversation = ConversationRunner(
            conv_cfg, cfg.behavior, cfg.qq, self.store, self.llm,
            self.state, self.memory, self.sender, self.suppressor, cfg.read_persona,
            trait_text=trait_text(self.primary_traits),
            delay_scale=self.primary_traits.delay_scale,
            presence_text=self.presence_text,
        )

    # ---------------- 多角色 ----------------

    def store_for(self, peer_id: str):
        """按会话角色取历史库；未知 id 落回主角色，避免接口报错。"""
        cid = str(peer_id or "")
        if not cid or cid == self.characters.primary.id:
            return self.store
        g = self._guests.get(cid) or self._guest_for(cid)
        return g.store if g else self.store

    def _guest_for(self, peer_id: str) -> Optional[GuestRuntime]:
        cid = str(peer_id or "")
        g = self._guests.get(cid)
        if g:
            return g
        char = self.characters.get(cid)
        if not char or char.is_primary:
            return None
        g = GuestRuntime(self.cfg, char, self.llm, self.sender,
                         stickers=self.stickers, search=self.search,
                         stealer=self.stealer)
        self._guests[cid] = g
        if getattr(self, "_started", False):
            g.start()
        print(f"[main] 角色已就绪：{char.name}（{cid}）｜"
              f"模块：{'/'.join(g.modules)}")
        return g

    # ---------------- 全局设置 / 新增角色 ----------------

    def get_settings(self) -> dict:
        from .settings import mask_key

        llm = self.cfg.llm
        return {
            "llm": {
                "base_url": llm.base_url,
                "model": llm.model,
                "api_key_set": bool(llm.api_key),
                "api_key_hint": mask_key(llm.api_key),
            }
        }

    async def save_settings(self, body: dict) -> dict:
        """更新 LLM 配置：立即生效 + 落盘到 data/settings.json。"""
        llm = body.get("llm") if isinstance(body.get("llm"), dict) else body
        patch = {}
        for key in ("base_url", "model", "api_key"):
            val = str(llm.get(key) or "").strip() if isinstance(llm, dict) else ""
            if val:
                patch[key] = val.rstrip("/") if key == "base_url" else val
        if not patch:
            return self.get_settings()

        if patch.get("base_url"):
            self.cfg.llm.base_url = patch["base_url"]
        if patch.get("model"):
            self.cfg.llm.model = patch["model"]
        if patch.get("api_key"):
            self.cfg.llm.api_key = patch["api_key"]

        from .settings import update_llm

        update_llm(patch)
        self.llm.cfg = self.cfg.llm
        # 关掉旧连接，下一次请求用新 key / base_url 重新建连
        await self.llm.close()
        print(f"[settings] LLM 已更新：model={self.cfg.llm.model} "
              f"base_url={self.cfg.llm.base_url} "
              f"key={'***' + self.cfg.llm.api_key[-4:] if self.cfg.llm.api_key else '(空)'}")
        return self.get_settings()

    # ---------------- 热情 / 好感 ----------------

    def get_character_traits(self, peer_id: str) -> dict:
        cid = str(peer_id or "").strip()
        char = self.characters.get(cid)
        if not char:
            raise ValueError("没有这个角色")
        return traits_payload(cid, char.name)

    def set_character_traits(self, peer_id: str,
                             enthusiasm, affection) -> dict:
        cid = str(peer_id or "").strip()
        char = self.characters.get(cid)
        if not char:
            raise ValueError("没有这个角色")
        t = save_traits(cid, enthusiasm, affection)
        if char.is_primary:
            self._apply_primary_traits(t)
        else:
            g = self._guests.get(cid)
            if g:
                g.apply_traits(t)
        print(f"[traits] {char.name}：热情 {t.enthusiasm} / 好感 {t.affection}"
              f"（{trait_text(t).splitlines()[0]}）")
        return traits_payload(cid, char.name)

    def _refresh_primary_config(self) -> None:
        """用当前的热情 + 在线状态重算星野的派生配置，并立即重排主动消息。

        热情和状态都会走到这里 —— 它们是同一层结构（都是乘数），
        所以任何一边变了都整体重算一次，避免两套逻辑互相覆盖。
        """
        t = self.primary_traits
        p = self.presence
        auto = derive_autonomy(self.base_autonomy, t, p)
        conv = derive_conversation(self.base_conversation, t, p)
        self.heartbeat.cfg = auto
        self.heartbeat.rhythm.cfg = auto
        self.suppressor.cfg = auto
        self.digest.cfg = auto
        self.conversation.cfg = conv
        self.heartbeat.trait_text = trait_text(t)
        self.heartbeat.delay_scale = t.delay_scale
        self.conversation.trait_text = trait_text(t)
        self.conversation.delay_scale = t.delay_scale
        self.presence_text = presence_text(p)
        self.heartbeat.presence_text = self.presence_text
        self.conversation.presence_text = self.presence_text
        self.heartbeat.replan()

    def _apply_primary_traits(self, t) -> None:
        self.primary_traits = t
        self._refresh_primary_config()

    # ---------------- 在线状态（QQ 式） ----------------

    def get_presence(self) -> dict:
        return presence_payload(self.presence)

    async def set_presence(self, key: str) -> dict:
        """切换在线状态：立即生效 + 广播到所有角色 + 需要时来一句问候。

        和 QQ 一样是**手动**切换。切到「在线 / Q我吧」视为「上线」，
        好友会主动来打招呼；「离线 / 隐身」只降低频率，不会完全不发；
        「请勿打扰」是唯一真的安静下来的状态。
        """
        prev_p = self.presence
        p, prev_key = set_status(key)
        self.presence = p
        self.presence_text = presence_text(p)
        # 主角色
        self._refresh_primary_config()
        # 全部新增角色（含还没实例化的：下次实例化时会读到新状态）
        for g in list(self._guests.values()):
            g.apply_presence(p)
        print(f"[presence] 状态：{prev_p.label} → {p.label}"
              f"（主动频率 ×{p.freq:g}，接话 ×{p.follow:g}"
              f"{'，完全不主动' if p.silent else ''}）")
        # ★ 上线打招呼：从「非在线」切到「在线 / Q我吧」才算「上线」。
        #   反向切换（下线/隐身）不触发，避免每切一下都被刷屏。
        if p.greet and not prev_p.greet and prev_p.key not in ("online", "qme"):
            if not self.suppressor.in_quiet_hours() and greet_cooldown_ok():
                mark_greeted()
                asyncio.create_task(self._presence_greet_wave())
        return presence_payload(p)

    async def _presence_greet_wave(self) -> None:
        """上线打招呼：星野先开口，再挑几个好感高的角色错峰跟上。

        不做成「全场同时刷屏」—— 真人朋友不会在你在线上线的瞬间
        集体出现。星野最先（她是最亲近的），其他人随机排序、间隔 25~70 秒。
        """
        try:
            if self.suppressor.in_quiet_hours():
                return
            await asyncio.sleep(random.uniform(5.0, 20.0))
            if self.suppressor.in_quiet_hours() or not self._channel_connected():
                return
            d = await self.heartbeat.poke_once(force=True, kind="miss",
                                               force_go=True)
            print(f"[presence] 上线问候（星野）：{d}")
        except asyncio.CancelledError:
            raise
        except Exception as e:  # noqa: BLE001
            print(f"[presence] 上线问候出错：{e!r}")

        # 再挑几个角色：好感高的优先，最多 3 个，彼此错峰
        try:
            guests = []
            for c in self.characters.guests():
                g = self._guests.get(c.id)
                if g:
                    guests.append((g.traits.affection, random.random(), g))
            guests.sort(key=lambda x: (-x[0], x[1]))
            picks = [g for _a, _r, g in guests[:3]]
            for i, g in enumerate(picks):
                if self.suppressor.in_quiet_hours() or not self._channel_connected():
                    return
                await asyncio.sleep(random.uniform(25.0, 70.0))
                if self.suppressor.in_quiet_hours() or not self._channel_connected():
                    return
                try:
                    d = await g.greet()
                    print(f"[presence] 上线问候（{g.char.name}）：{d}")
                except Exception as e:  # noqa: BLE001
                    print(f"[presence] 上线问候（{g.char.name}）出错：{e!r}")
        except asyncio.CancelledError:
            raise
        except Exception as e:  # noqa: BLE001
            print(f"[presence] 角色上线问候出错：{e!r}")


    # ---------------- 群聊 ----------------

    def _group_member(self, cid: str) -> Optional[Member]:
        """把「星野」或某个新增角色统一成同一个「群成员」形状。

        星野没有 GuestRuntime（她的运行时是 Companion 自己那套），所以这里
        做一层适配 —— 引擎就不用关心成员内部是哪种角色了。
        """
        cid = str(cid or "")
        char = self.characters.get(cid)
        if not char:
            return None
        if char.is_primary:
            return Member(
                id=cid, name=char.name,
                persona=self.cfg.read_persona("persona.md"),
                boundaries=self.cfg.read_persona("boundaries.md"),
                world=self.cfg.read_persona("world.md"),
                state=self.state, memory=self.memory, store=self.store,
                traits=self.primary_traits,
                delay_scale=self.primary_traits.delay_scale,
                schedule=char.schedule,
            )
        g = self._guest_for(cid)
        if not g:
            return None
        return Member(id=cid, name=char.name, persona=g.char.persona,
                      boundaries=g.boundaries, world="",
                      state=g.state, memory=g.memory, store=g.store,
                      traits=g.traits, delay_scale=g.traits.delay_scale,
                      schedule=char.schedule)

    def group_store_for(self, gid: str):
        """★ 群 id 绝不能走 `store_for`（它对未知 peer 会回落到主人格的库）。"""
        return self.groups.store_for(gid)

    @staticmethod
    def _schedule_text_for(char) -> str:
        """角色的作息提示词（没配作息、或正在清醒时段 → 空串）。"""
        sch = getattr(char, "schedule", None)
        if sch is None:
            return ""
        try:
            return sch.scene_text()
        except Exception:  # noqa: BLE001
            return ""

    def group_runtime_for(self, gid: str) -> Optional[GroupRuntime]:
        key = str(gid or "")
        if not key or not self.groups.exists(key):
            return None
        rt = self._group_runtimes.get(key)
        if rt:
            return rt
        group = self.groups.get(key)
        rt = GroupRuntime(
            self.cfg, group, self.groups, self.llm, self.sender,
            self._group_member,
            presence_getter=lambda: self.presence,
            quiet_check=self.suppressor.in_quiet_hours,
            on_system=self._push_group_system,
        )
        self._group_runtimes[key] = rt
        if getattr(self, "_started", False):
            rt.start()
        print(f"[main] 群已就绪：{group.name}（{key}）｜"
              f"成员 {len(rt.store.members())} 人")
        return rt

    def _push_group_system(self, gid: str, text: str) -> None:
        """群里的系统消息（建群/改名/入群/踢人/公告）→ 立刻推给打开的客户端。

        引擎写 system() 时是同步调用，这里把异步推送丢进事件循环，不阻塞。
        """
        fn = getattr(self.channel, "push_group_system", None)
        if not fn:
            return
        try:
            asyncio.create_task(fn(gid, text))
        except RuntimeError:  # 没有运行中的事件循环（测试收尾）→ 静默
            pass

    async def _handle_group(self, msg: IncomingMessage) -> None:
        """自建群里的消息：只服务主人，交给群引擎。"""
        if self.cfg.qq.owner_id and msg.user_id != self.cfg.qq.owner_id:
            self._note_ignored("群聊", msg.group_id,
                               f"不是主人（只认 {self.cfg.qq.owner_id}）")
            return
        rt = self.group_runtime_for(msg.group_id)
        if not rt:
            return
        await rt.on_owner_message(msg)

    # ---- 对外的群接口（channel 的 action / 网页的 HTTP 端点都走这里）----

    def groups_payload(self) -> List[dict]:
        out: List[dict] = []
        for g in self.groups.all():
            st = self.groups.store_for(g.id)
            out.append({
                "group_id": g.id,
                "group_name": g.name,
                "avatar": g.avatar,
                "member_count": len(st.members()),
                "mute_all": bool(st.mute_all().get("on")),
                "searchable": bool(st.meta().get("searchable", True)),
                "announce": str(st.announcement().get("text") or ""),
                "pending": len(st.pending_requests()),
            })
        return out

    def group_detail(self, gid: str) -> dict:
        g = self.groups.get(gid)
        if not g:
            raise ValueError("没有这个群")
        st = self.groups.store_for(gid)
        members = st.members()
        out = []
        for uid, m in members.items():
            out.append({
                "user_id": str(uid),
                "nickname": str(m.get("nickname") or uid),
                "role": str(m.get("role") or "member"),
                "level": int(st.member_level(uid)),
                "title": str(m.get("title") or ""),
                "joined_ts": float(m.get("joined_ts") or 0),
                "muted_until": float(m.get("muted_until") or 0),
                "is_me": str(uid) == str(self.cfg.qq.owner_id or ""),
            })
        # 群主排第一，其余按角色/入群时间
        out.sort(key=lambda x: (x["role"] != "owner", x["joined_ts"]))
        rt = self.group_runtime_for(gid)
        return {
            "group_id": g.id, "group_name": g.name, "avatar": g.avatar,
            "member_count": len(members), "members": out,
            "mute_all": bool(st.mute_all().get("on")),
            "searchable": bool(st.meta().get("searchable", True)),
            "announce": st.announcement(),
            # ★ 待审申请统一带上 user_id（库里存的是 uid）—— 前端以前读 r.user_id
            #   取到 undefined，点同意就等于把空 uid 发给后端 → 「没有这个申请」。
            "pending": [{**r, "user_id": str(r.get("uid") or "")}
                        for r in st.pending_requests()],
            "limits": rt.limits_payload() if rt else [],
        }

    def set_group_limits(self, gid: str, values: dict) -> dict:
        """改这个群的节奏参数（人数上限/每人额度/接话概率…）。"""
        rt = self.group_runtime_for(gid)
        if not rt:
            raise ValueError("没有这个群")
        rt.apply_limits(values or {})
        return self.group_detail(gid)

    def group_messages(self, gid: str, count: int = 40) -> List[dict]:
        """群历史（给 channel 拼 OneBot 段用）。"""
        if not self.groups.exists(str(gid)):
            return []
        st = self.groups.store_for(gid)
        return st.recent_gmsgs(max(1, min(200, int(count or 40))))

    def create_group(self, name: str, member_ids: Optional[List[str]] = None) -> dict:
        owner_id = str(self.cfg.qq.owner_id or "")
        names = {c.id: c.name for c in self.characters.all()}
        picked = [str(x) for x in (member_ids or []) if str(x) in names
                  and str(x) != owner_id]
        limit = max(1, int(self.cfg.group.max_members) - 1)
        g = self.groups.create(
            name, owner_id, self.cfg.qq.server.owner_nickname,
            member_ids=picked[:limit], member_names=names,
        )
        self.group_runtime_for(g.id)
        return self.group_detail(g.id)

    def invite_group_member(self, gid: str, uid: str, name: str = "") -> dict:
        """群主**直接**拉人入群。

        不走「申请入群」那条路：那条会受「允许被搜索」开关限制，群主关掉搜索后
        连自己邀请都会被拒（实测会报「这个群不允许被搜索」）。这里直接加成员。
        """
        rt = self.group_runtime_for(gid)
        if not rt:
            raise ValueError("没有这个群")
        uid = str(uid or "")
        if not uid:
            raise ValueError("缺少 user_id")
        if rt.store.member(uid):
            raise ValueError("这个人已经在群里了")
        limit = max(1, int(self.cfg.group.max_members) - 1)
        if len(rt.store.members()) - 1 >= limit:
            raise ValueError(f"群满了（上限 {limit + 1} 人）")
        if not name:
            char = self.characters.get(uid)
            name = char.name if char else uid
        rt.store.add_member(uid, name, role="member")
        rt.system(f"{name} 加入了群聊")
        print(f"[main] 群 {gid} 邀请了 {name}（{uid}）")
        return self.group_detail(gid)

    def kick_group_member(self, gid: str, uid: str) -> dict:
        rt = self.group_runtime_for(gid)
        if not rt:
            raise ValueError("没有这个群")
        uid = str(uid or "")
        m = rt.store.member(uid)
        if not m:
            raise ValueError("这个人不在群里")
        if str(m.get("role")) == "owner":
            raise ValueError("不能移出群主")
        rt.store.remove_member(uid)
        rt.system(f"{m.get('nickname') or uid} 被移出了群聊")
        print(f"[main] 群 {gid} 移出成员 {uid}")
        return self.group_detail(gid)

    def set_group_admin(self, gid: str, uid: str, on: bool = True) -> dict:
        rt = self.group_runtime_for(gid)
        if not rt:
            raise ValueError("没有这个群")
        m = rt.store.set_member(str(uid), role="admin" if on else "member")
        if not m:
            raise ValueError("这个人不在群里")
        rt.system(f"{m.get('nickname') or uid} "
                  + ("被设为管理员" if on else "被取消管理员"))
        return self.group_detail(gid)

    def set_group_announce(self, gid: str, text: str) -> dict:
        rt = self.group_runtime_for(gid)
        if not rt:
            raise ValueError("没有这个群")
        rt.post_announcement(str(text or ""),
                             by=self.cfg.qq.server.owner_nickname)
        print(f"[main] 群 {gid} 发布公告（{len(rt.ai_member_ids())} 人已看到）")
        return self.group_detail(gid)

    def set_group_mute_all(self, gid: str, on: bool) -> dict:
        rt = self.group_runtime_for(gid)
        if not rt:
            raise ValueError("没有这个群")
        rt.set_mute_all(bool(on), by=self.cfg.qq.server.owner_nickname)
        print(f"[main] 群 {gid} 全员禁言 = {bool(on)}")
        return self.group_detail(gid)

    def rename_group(self, gid: str, name: str) -> dict:
        if not self.groups.rename(gid, name):
            raise ValueError("改群名失败")
        rt = self.group_runtime_for(gid)
        if rt:
            rt.group.name = name.strip()
            rt.system(f"群名改为「{name.strip()}」")
        return self.group_detail(gid)

    def set_group_searchable(self, gid: str, on: bool) -> dict:
        if not self.groups.exists(gid):
            raise ValueError("没有这个群")
        self.groups.store_for(gid).set_meta(searchable=bool(on))
        return self.group_detail(gid)

    # ---- 群文件 / 群相册 ----

    _IMAGE_EXT = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp"}

    def group_files(self, gid: str) -> List[dict]:
        gid = str(gid or "")
        if not self.groups.exists(gid):
            return []
        items = self.groups.store_for(gid).kv_get("files", [])
        if not isinstance(items, list):
            return []
        return [x for x in items if isinstance(x, dict) and x.get("id")]

    def group_file_path(self, gid: str, fid: str):
        """按 file_id 找真实文件路径（只认登记过的 id，防路径穿越）。"""
        want = str(fid or "")
        for it in self.group_files(gid):
            if str(it.get("id")) == want and it.get("stored"):
                p = self.groups.files_dir(gid) / str(it["stored"])
                if p.is_file():
                    return p
        return None

    def add_group_file(self, gid: str, name: str, blob: bytes,
                       uploader: str = "") -> dict:
        """把一份文件放进群文件/群相册（图片自动归到相册）。"""
        gid = str(gid or "")
        if not self.groups.exists(gid):
            raise ValueError("没有这个群")
        if not blob:
            raise ValueError("空文件")
        if len(blob) > 20 * 1024 * 1024:
            raise ValueError("文件太大（上限 20MB）")
        safe = re.sub(r"[^\w.\-\u4e00-\u9fff]", "_", str(name or "file").strip())
        safe = (safe or "file")[:60]
        ext = Path(safe).suffix.lower()
        fid = f"f{int(time.time() * 1000)}{random.randint(0, 999):03d}"
        d = self.groups.files_dir(gid)
        d.mkdir(parents=True, exist_ok=True)
        stored = fid + ext
        (d / stored).write_bytes(blob)
        item = {
            "id": fid,
            "name": safe,
            "size": len(blob),
            "kind": "image" if ext in self._IMAGE_EXT else "file",
            "stored": stored,
            "uploader": str(uploader or ""),
            "ts": time.time(),
        }
        st = self.groups.store_for(gid)
        items = self.group_files(gid)
        items.append(item)
        st.kv_set("files", items[-200:])          # 只留最近 200 份登记
        rt = self.group_runtime_for(gid)
        if rt:
            rt.system(f"{uploader or '有人'} 上传了文件「{safe}」")
        print(f"[main] 群 {gid} 新增文件：{safe}（{len(blob)} 字节）")
        return item

    def remove_group_file(self, gid: str, fid: str, by: str = "") -> dict:
        """删一份群文件。by = 发起人显示名：群主能删任何文件，其他人只能删自己传的。"""
        gid = str(gid or "")
        fid = str(fid or "")
        items = self.group_files(gid)
        keep, target = [], None
        for it in items:
            if str(it.get("id")) == fid:
                target = it
            else:
                keep.append(it)
        if target is None:
            raise ValueError("没有这个文件")
        owner = str(self.cfg.qq.server.owner_nickname or "")
        uploader = str(target.get("uploader") or "")
        if uploader and by and by != owner and uploader != by:
            raise ValueError("只能删自己上传的文件")
        self.groups.store_for(gid).kv_set("files", keep)
        try:
            (self.groups.files_dir(gid) / str(target.get("stored") or "")).unlink()
        except OSError:
            pass
        return {"group_id": gid, "file_id": fid}

    def group_join_requests(self, gid: str = "") -> List[dict]:
        if gid:
            st = self.groups.store_for(gid)
            return st.pending_requests()
        out: List[dict] = []
        for g in self.groups.all():
            for r in self.groups.store_for(g.id).pending_requests():
                out.append({**r, "user_id": str(r.get("uid") or ""),
                            "group_id": g.id,
                            "group_name": self.groups.get(g.id).name})
        return out

    def resolve_group_request(self, gid: str, uid: str, approve: bool) -> dict:
        rt = self.group_runtime_for(gid)
        if not rt:
            raise ValueError("没有这个群")
        req = rt.store.resolve_join_request(str(uid), bool(approve))
        if not req:
            raise ValueError("没有这个申请")
        name = str(req.get("name") or uid)
        if approve:
            # ★ 已经在群里就不要再播一次「加入了群聊」——实测出现同一个人
            #   （橘雪莉）两条入群系统消息：她先被邀请进群，申请又被点了同意。
            if rt.store.member(str(uid)):
                return self.group_detail(gid)
            rt.store.add_member(str(uid), name, role="member")
            rt.system(f"{name} 加入了群聊")
        else:
            rt.system(f"{name} 的入群申请被拒绝")
        return self.group_detail(gid)

    def apply_join_group(self, gid: str, uid: str, name: str = "",
                         note: str = "") -> dict:
        """某个角色申请入群（本人/自动触发都走这里）。"""
        g = self.groups.get(gid)
        if not g:
            raise ValueError("没有这个群")
        st = self.groups.store_for(gid)
        if not bool(st.meta().get("searchable", True)):
            raise ValueError("这个群不允许被搜索")
        if str(uid) in st.members():
            raise ValueError("已经在群里了")
        req = st.add_join_request(str(uid), name or str(uid), note)
        if not req:
            raise ValueError("已经申请过了，等群主处理")
        print(f"[main] {name or uid} 申请加入群「{g.name}」（待人审）")
        return req

    def _next_character_id(self) -> str:
        nums = []
        for c in self.characters.all():
            try:
                nums.append(int(c.id))
            except ValueError:
                continue
        return str(max(nums + [3901000000]) + 1)

    async def create_character(self, name: str, avatar_data: str) -> dict:
        """新增角色：头像 + 名字 → 联网蒸馏人设 → 入库并立即可聊。"""
        name = (name or "").strip()
        if not name:
            raise ValueError("请填写角色名")
        if any(c.name == name for c in self.characters.all()):
            raise ValueError("已经有同名角色了")
        if not self.cfg.llm.api_key:
            raise ValueError("请先在「设置」里填写模型 API Key")

        slug = re.sub(r'[\\/:*?"<>|]+', "_", name).strip().strip(".")[:24]
        slug = slug or "character"

        # 解码头像
        raw = avatar_data or ""
        if raw.startswith("data:") and "," in raw:
            raw = raw.split(",", 1)[1]
        try:
            blob = base64.b64decode(raw)
        except Exception:  # noqa: BLE001
            raise ValueError("头像数据损坏，请重新选择图片")
        if len(blob) > 8 * 1024 * 1024:
            raise ValueError("头像太大（上限 8MB）")

        cid = self._next_character_id()
        avatar_path = self.cfg.root / "data" / "avatars" / f"{cid}.png"
        pristine_path = (self.cfg.root / "data" / "character_avatars"
                         / f"{cid}.png")
        try:
            from PIL import Image

            with Image.open(io.BytesIO(blob)) as im:
                im = im.convert("RGB")
                side = min(im.width, im.height)
                left = (im.width - side) // 2
                top = (im.height - side) // 2
                im = im.crop((left, top, left + side, top + side))
                im = im.resize((256, 256), Image.LANCZOS)
                avatar_path.parent.mkdir(parents=True, exist_ok=True)
                pristine_path.parent.mkdir(parents=True, exist_ok=True)
                im.save(avatar_path, "PNG", optimize=True)
                im.save(pristine_path, "PNG", optimize=True)
        except Exception as e:  # noqa: BLE001
            raise ValueError(f"头像读取失败：{e}")

        # 联网搜索 + 蒸馏（这一步最慢）
        try:
            from .persona_builder import build_persona

            info = await build_persona(self.llm, name)
        except Exception:
            for p in (avatar_path, pristine_path):
                try:
                    p.unlink(missing_ok=True)
                except OSError:
                    pass
            raise

        persona_md = str(info.get("persona_md") or "").strip()
        if len(persona_md) < 200:
            raise ValueError("人设蒸馏结果为空，请重试或换一个更知名的角色名")

        pdir = self.cfg.root / "persona" / "characters" / slug
        if pdir.exists() and (pdir / "meta.json").exists():
            slug = f"{slug}_{cid[-4:]}"
            pdir = self.cfg.root / "persona" / "characters" / slug
        pdir.mkdir(parents=True, exist_ok=True)
        (pdir / "persona.md").write_text(persona_md, encoding="utf-8")

        interests = [str(x).strip() for x in (info.get("interests") or [])
                     if str(x).strip()][:8]
        if not interests:
            interests = [str(info.get("series") or name)]
        shared = self.cfg.read_persona("interests.md")
        marker = "## 用户的兴趣种子"
        tail = shared[shared.index(marker):] if marker in shared else ""
        (pdir / "interests.md").write_text(
            "# 兴趣\n\n## 她自己的兴趣\n\n"
            + "\n".join(f"- {x}" for x in interests)
            + "\n\n" + tail,
            encoding="utf-8",
        )
        (pdir / "meta.json").write_text(json.dumps({
            "id": cid, "name": name, "slug": slug,
            "series": info.get("series") or "",
            "source": "web-research",
            "avatar": f"data/avatars/{cid}.png",
        }, ensure_ascii=False, indent=2), encoding="utf-8")

        # 注册表
        reg_path = self.cfg.root / "data" / "characters.json"
        try:
            reg = json.loads(reg_path.read_text(encoding="utf-8"))
            if not isinstance(reg, dict):
                reg = {"characters": []}
        except (OSError, json.JSONDecodeError):
            reg = {"characters": []}
        chars = reg.get("characters")
        if not isinstance(chars, list):
            chars = []
        chars.append({"id": cid, "name": name, "slug": slug,
                      "series": info.get("series") or "",
                      "source": "web-research"})
        reg["characters"] = chars
        reg_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = reg_path.with_name(reg_path.name + ".tmp")
        tmp.write_text(json.dumps(reg, ensure_ascii=False, indent=2),
                       encoding="utf-8")
        tmp.replace(reg_path)

        self.characters.reload()
        ensure_defaults([self.characters.get(cid)])
        # 新角色和现有学生走同一个 GuestRuntime：
        # 心跳主动 / 接话 / 自主分享 / 抑制链 / 表情包 / 记忆 / 情绪全部具备
        g = self._guest_for(cid)
        if g:
            asyncio.create_task(self._greet_new_character(g))
        print(f"[characters] 新增角色：{name}（{cid}）")
        return {
            "character": {
                "id": cid,
                "name": name,
                "series": info.get("series") or "",
            }
        }

    async def _greet_new_character(self, g: GuestRuntime) -> None:
        try:
            await asyncio.sleep(2.0)
            if self.suppressor.in_quiet_hours():
                return
            d = await g.greet()
            print(f"[main] {g.char.name} 新角色问候：{d}")
        except Exception as e:  # noqa: BLE001
            print(f"[main] {g.char.name} 新角色问候出错：{e!r}")

    # ---------------- 生命周期 ----------------
    async def start(self) -> None:
        self._started = True
        await self.channel.start()
        self._print_policy()
        self._hb_task = asyncio.create_task(self.heartbeat.run())
        self._conv_task = asyncio.create_task(self.conversation.run())
        # 新增角色：各自的心跳 / 接话也一起跑起来（只换人格，习惯不变）
        self._start_guests()
        # 群聊：每个群有自己的节奏（不定时有人起话头、别人接话）
        self._start_groups()
        # ★ 看门狗只在 napcat 链路有意义（修的是 NapCat/QQ 进程）。
        # onebot-server 模式下没有 QQ —— 断线=客户端没连着，
        # 不需要（也不应该）触发 NapCat 修复任务。
        if self.channel_kind != "onebot-server":
            self._watchdog_task = asyncio.create_task(self._channel_watchdog())
        # ★ 上线必发一条：用户明确要求「每次上线都一定主动发消息」。
        # 不等心跳抽签（那可能几小时都不开口）。
        if self.cfg.autonomy.greet_on_start:
            self._greet_task = asyncio.create_task(self._greet_on_start())
            self._guest_greet_task = asyncio.create_task(self._greet_guests())

    def _start_guests(self) -> None:
        for char in self.characters.guests():
            g = self._guest_for(char.id)
            if g:
                g.start()        # 幂等：确保每个学生的模块都真的跑起来

    def _start_groups(self) -> None:
        """把已有的群引擎都跑起来（幂等）。"""
        for g in self.groups.all():
            rt = self.group_runtime_for(g.id)
            if rt:
                rt.start()
        if self._group_scout_task is None or self._group_scout_task.done():
            self._group_scout_task = asyncio.create_task(self._group_join_scout())

    # ---------------- 「搜到群 → 申请加入」----------------

    async def _group_join_scout(self) -> None:
        """让还没进群的角色偶尔「搜到」可被搜索的群，递一条入群申请。

        用户要的：「其他好友也能搜索到群聊申请加入」。这里不假装有人在搜群
        —— 就是给每个角色一段随机长的时间，到点了她刷到这个群、想进来看看，
        于是递申请；群主在网页右侧的「入群申请」里同意或拒绝。
        """
        await asyncio.sleep(random.uniform(240.0, 900.0))
        while True:
            try:
                await self._group_join_once()
            except asyncio.CancelledError:
                raise
            except Exception as e:  # noqa: BLE001
                print(f"[group] 入群申请巡查出错：{e!r}")
            await asyncio.sleep(random.uniform(1500.0, 4200.0))

    async def _group_join_once(self) -> None:
        if self.presence.silent or not self._channel_connected():
            return
        groups = self.groups.all()
        if not groups:
            return
        limit = max(1, int(self.cfg.group.max_members) - 1)
        now = time.time()
        cooldown = max(1, int(self.cfg.group.join_request_cooldown_h)) * 3600
        for g in groups:
            st = self.groups.store_for(g.id)
            if not bool(st.meta().get("searchable", True)):
                continue
            members = st.members()
            if len(members) - 1 >= limit:
                continue
            for char in self.characters.guests():
                cid = str(char.id)
                if cid in members:
                    continue
                guest = self._guest_for(cid)
                if not guest:
                    continue
                try:
                    last = float(guest.store.kv_get("group_join_at", 0) or 0)
                except Exception:  # noqa: BLE001
                    last = 0.0
                if now - last < cooldown:
                    continue
                if random.random() > 0.35:
                    continue
                guest.store.kv_set("group_join_at", now)
                try:
                    self.apply_join_group(g.id, cid, char.name,
                                          random.choice(JOIN_REQUEST_NOTES))
                    print(f"[main] {char.name} 想加入群「{g.name}」（待群主审核）")
                except Exception as e:  # noqa: BLE001
                    print(f"[main] {char.name} 的入群申请被忽略：{e!r}")
                return

    async def _greet_guests(self) -> None:
        """新增角色的上线问候：错峰发送，避免九个人同时刷屏。"""
        guests = [self._guests[c.id] for c in self.characters.guests()
                  if c.id in self._guests
                  and not self._guests[c.id].store.recent_turns(1)]
        if not guests:
            return
        delay = max(5.0, float(self.cfg.autonomy.greet_delay_sec))
        cap = max(delay, float(getattr(self.cfg.autonomy,
                                      "greet_wait_max_sec", 1200)))
        try:
            if self.presence.silent:
                print(f"[main] 角色问候跳过：当前状态是「{self.presence.label}」")
                return
            await asyncio.sleep(delay)
            waited = 0.0
            while waited < cap:
                if self._channel_connected():
                    break
                await asyncio.sleep(5.0)
                waited += 5.0
            if not self._channel_connected():
                print(f"[main] 角色问候放弃：等了 {waited:.0f} 秒仍没有客户端")
                return
            if self.suppressor.in_quiet_hours():
                print("[main] 角色问候跳过：当前是免打扰时段")
                return
            random.shuffle(guests)
            for i, g in enumerate(guests):
                if self.suppressor.in_quiet_hours():
                    break
                try:
                    d = await g.greet()
                    print(f"[main] {g.char.name} 上线问候：{d}")
                except Exception as e:  # noqa: BLE001
                    print(f"[main] {g.char.name} 上线问候出错：{e!r}")
                if i < len(guests) - 1:
                    await asyncio.sleep(random.uniform(12, 30))
        except asyncio.CancelledError:
            raise
        except Exception as e:  # noqa: BLE001
            print(f"[main] 角色问候出错：{e!r}")

    async def _channel_watchdog(self) -> None:
        """★ 通道看门狗：NapCat 断线后无人值守自愈。

        背景（实测事故 2026-10-15 夜）：NTQQ 会无声自我回收进程树，
        NapCat 是注入进 QQ 进程里的 —— 随旧进程死亡，新 QQ 没有注入，
        **永远不会自己回连**。第二天一看，vol 聋了一整夜。

        做法：每 30 秒看一眼通道。「曾经连上过 → 断开持续超过宽限期」
        就用 `schtasks /Run` 触发以最高权限注册好的计划任务
        「Vol_NapCat_AutoRepair」（由 register_napcat_repair.bat 注册）。
        之所以走计划任务：修复要杀管理员权限的 QQ 进程，普通权限的
        伴侣进程既杀不动、也没法不弹 UAC 地重启 NapCat —— 计划任务
        在注册时就授过权，/Run 静默执行，这是无人值守的关键。

        三重保险，避免误伤：
        - ever_connected：从没连上过（还没点一键启动）绝不自作主张
        - 宽限 3 分钟：躲开 NapCat 自己的重连重试
        - 节流 15 分钟：修不好也不无限循环杀起 QQ
        """
        task_name = "Vol_NapCat_AutoRepair"
        grace_sec = 180.0
        throttle_sec = 900.0
        last_repair = 0.0
        down_since: Optional[float] = None
        while True:
            await asyncio.sleep(30)
            try:
                ch = self.channel
                if not getattr(ch, "ever_connected", False):
                    continue                      # 从没连上过 → 不管
                if getattr(ch, "_clients", None):
                    down_since = None             # 通道活着 → 清观察态
                    continue
                now = time.time()
                if down_since is None:
                    down_since = now
                    print("[watchdog] 通道断开，观察中（给自动重连留 3 分钟）...")
                    continue
                if now - down_since < grace_sec:
                    continue                      # 还在宽限期内
                if now - last_repair < throttle_sec:
                    continue                      # 修过了，冷却中
                last_repair = now
                print(f"[watchdog] 通道断开已 {int((now - down_since) / 60)} 分钟"
                      f" → 触发自动修复任务 {task_name}")
                r = subprocess.run(
                    ["schtasks", "/Run", "/TN", task_name],
                    capture_output=True, timeout=30)
                ok = r.returncode == 0
                tail = (r.stdout or r.stderr).decode(CONSOLE_ENC, errors="replace").strip()
                print(f"[watchdog] schtasks → {'成功' if ok else '失败'} {tail[:120]}")
                if not ok:
                    print("[watchdog] 计划任务没跑起来 —— 双击"
                          "vol\\register_napcat_repair.bat 重新注册一次")
                down_since = None                # 给新进程时间起来，重新观察
            except Exception as e:  # noqa: BLE001
                print(f"[watchdog] 出错：{e!r}")

    async def _greet_on_start(self) -> None:
        """启动后打一次招呼。

        ⚠️ 这里**不能设短超时**：NapCat 往往要弹 UAC、还要扫码登录，
        一分钟内根本连不上。原来给 60 秒超时就放弃，
        结果「上线问候」几乎永远发不出去（实测 last_spoke_ts 一直是 0）。
        现在改成**轮询等待**，最长等 greet_wait_max_sec（默认 20 分钟）。
        """
        delay = max(3.0, float(self.cfg.autonomy.greet_delay_sec))
        cap = max(delay, float(getattr(self.cfg.autonomy, "greet_wait_max_sec", 1200)))
        try:
            if self.presence.silent:
                print(f"[main] 上线问候跳过：当前状态是「{self.presence.label}」")
                return
            await asyncio.sleep(delay)
            # 轮询等 NapCat 连上
            waited = 0.0
            while waited < cap:
                if self._channel_connected():
                    break
                await asyncio.sleep(5.0)
                waited += 5.0
            if not self._channel_connected():
                print(f"[main] 上线问候放弃：等了 {waited:.0f} 秒 NapCat 仍未连上")
                return
            if self.suppressor.in_quiet_hours():
                print("[main] 上线问候跳过：当前是免打扰时段")
                return
            d = await self.heartbeat.poke_once(force=True, kind="miss", force_go=True)
            print(f"[main] 上线问候：{d}")
            if not d.allowed:
                # 没发出去就过一会儿再试一次（比如模型这次没话可说）
                await asyncio.sleep(90)
                d2 = await self.heartbeat.poke_once(force=True, kind="miss", force_go=True)
                print(f"[main] 上线问候（重试）：{d2}")
        except asyncio.CancelledError:
            raise
        except Exception as e:  # noqa: BLE001
            print(f"[main] 上线问候出错：{e!r}")

    def _channel_connected(self) -> bool:
        """NapCat 连上了没。没有 connected 属性时按「已连」处理，避免误判。"""
        ev = getattr(self.channel, "connected", None)
        if ev is None:
            return True
        try:
            return bool(ev.is_set())
        except AttributeError:
            return True

    def _print_policy(self) -> None:
        c = self.cfg.qq
        if self.channel_kind == "onebot-server":
            print("[policy] 通道：onebot-server（自托管，已脱离 QQ/腾讯）")
            print(f"[policy] 聊天页面：http://<本机IP>:{c.server.port}/"
                  "（浏览器直接打开即聊；手机连同一 WiFi 访问电脑 IP）")
            guests = self.characters.guests()
            if guests:
                print(f"[policy] 登录者 = 主人；角色：{c.server.bot_nickname}"
                      f"（{c.self_id}）+ {len(guests)} 个新增角色")
            else:
                print("[policy] 登录者 = 主人；好友列表 = "
                      f"{c.server.bot_nickname}（{c.self_id}）一人")
            if not c.server.token:
                print("[policy] ⚠️ 未配置 qq.server.token —— 上公网前务必填写")
            print("[policy] 私聊以外的消息不处理（本模式也没有群）")
            return
        gm = c.group_mode or "off"
        desc = {
            "off": "关闭（任何群消息都不回）",
            "mention": "被 @ 时回",
            "allowlist": f"仅白名单群被 @ 时回（{len(c.group_allowlist)} 个群）",
        }.get(gm, f"未知值 {gm!r}，按 off 处理")
        print(f"[policy] 群聊响应：{gm} —— {desc}")
        print("[policy] 私聊：只回 %s，其他人一律不理" % (c.owner_id or "(未设置)"))
        print("[policy] 主动消息：只发给主人的私聊，任何时候都不会发到群里")
        print("[policy] 注意：NapCat 会把你账号收到的**所有**群消息都转发过来，"
              "本服务在入口就丢弃（不回复/不下图/不入记忆）")
        if gm == "mention":
            print("[policy] ⚠️ mention 模式下，群里任何 @ 它的成员都能让它开口")
        c = self.cfg.conversation
        if c.enabled:
            print(f"[policy] 对话连贯：会话窗口 {c.active_window_min} 分钟，"
                  f"窗口内会自己把话接下去（连发上限 {c.max_burst_bubbles} 条/深聊 "
                  f"{c.deep_max_burst_bubbles} 条，按气泡计）")
        else:
            print("[policy] 对话连贯：已关闭（回到一问一答）")

    async def stop(self) -> None:
        self.heartbeat.stop()
        self.conversation.stop()
        if self._group_scout_task and not self._group_scout_task.done():
            self._group_scout_task.cancel()
        self._group_scout_task = None
        for rt in list(self._group_runtimes.values()):
            rt.close()
        self._group_runtimes.clear()
        for g in list(self._guests.values()):
            await g.aclose()
        self._guests.clear()
        await self.channel.stop()
        await self.llm.close()
        self.groups.close()
        self.store.close()

    # ---------------- 消息入口 ----------------
    def _group_allowed(self, msg: IncomingMessage) -> bool:
        """群聊闸门。默认 off —— 任何群消息都不回。

        刻意不在这里 print：学校群可能很吵，逐条打印会把日志刷爆。
        """
        mode = self.cfg.qq.group_mode or "off"
        if mode == "off":
            return False
        if not msg.mentions_self:
            return False
        if mode == "allowlist":
            allow = {str(g) for g in self.cfg.qq.group_allowlist}
            return msg.group_id in allow
        return True   # mention

    async def handle(self, msg: IncomingMessage) -> None:
        # ★ 自建群优先于「外来群闸门」。_group_allowed 是给 NapCat 转发进来
        #   的**外部**群用的（默认 off，防止小号在学校群里乱开口）；自己建的
        #   群要是被它拦住，就会出现「我的群永远不吭声」。
        gid = str(msg.group_id or "")
        if (not msg.is_private) and gid and self.groups.exists(gid):
            await self._handle_group(msg)
            return

        # 私聊：只服务主人；群聊：受 group_mode 闸门控制
        if msg.is_private:
            if self.cfg.qq.owner_id and msg.user_id != self.cfg.qq.owner_id:
                self._note_ignored("私聊", msg.user_id, f"不是主人（只认 {self.cfg.qq.owner_id}）")
                return
        elif not self._group_allowed(msg):
            self._note_ignored("群聊", msg.group_id,
                               f"qq.group_mode={self.cfg.qq.group_mode}，群里不回")
            return

        # 新增角色：各自独立的记忆与人设，只走轻量回复管线
        # （不接心跳/主动分享，避免十个角色同时找你）
        peer = str(getattr(msg, "peer_id", "") or "")
        if msg.is_private and peer and self.characters.is_guest(peer):
            self._queue_guest(msg)
            return

        text = msg.text.strip()
        if text and await self._handle_command(msg, text):
            return

        # ★ 多条消息合并：真人聊天是一口气发好几条，对方读完再一起接。
        # 原来是「来一条处理一条」，于是你连发 5 条她会回 5 次，
        # 而且每条都只看得到前一条 —— 体验非常割裂。
        # merge_window_sec <= 0 时关闭合并（测试用得到）。
        if float(self.cfg.behavior.merge_window_sec) <= 0:
            await self._run_pipeline(msg, notify=True)
            return
        self._queue_for_merge(msg)

    def _queue_for_merge(self, msg: IncomingMessage) -> None:
        """把消息放进合并队列，静默一小段后再统一处理。"""
        self._pending.append(msg)
        first_ts = getattr(self, "_pending_first_ts", 0.0)
        if not first_ts or len(self._pending) == 1:
            self._pending_first_ts = time.time()
            first_ts = self._pending_first_ts

        if len(self._pending) >= max(2, int(self.cfg.behavior.merge_max_msgs)):
            self._flush_pending()          # 攒太多了，直接处理
            return

        waited = time.time() - first_ts
        window = float(self.cfg.behavior.merge_window_sec)
        if waited >= float(self.cfg.behavior.merge_max_wait_sec):
            self._flush_pending()          # 第一条等太久了，别再拖
            return

        if self._merge_task and not self._merge_task.done():
            self._merge_task.cancel()
        self._merge_task = asyncio.create_task(self._merge_after(window))

    async def _merge_after(self, delay: float) -> None:
        try:
            await asyncio.sleep(delay)
        except asyncio.CancelledError:
            return                          # 又来新消息了，重新计时
        self._flush_pending()

    def _flush_pending(self) -> None:
        """把攒下的消息合成一条，走正常流程。"""
        if not self._pending:
            return
        batch, self._pending = self._pending, []
        self._pending_first_ts = 0.0
        if self._merge_task and not self._merge_task.done():
            self._merge_task.cancel()
        self._merge_task = None
        merged = self._merge_messages(batch)
        if len(batch) > 1:
            print(f"[main] 合并 {len(batch)} 条消息为一次回复")
        asyncio.create_task(self._run_pipeline(merged))

    # ---- 新增角色的合并队列（按角色独立，互不打断）----

    def _queue_guest(self, msg: IncomingMessage) -> None:
        cid = str(msg.peer_id or "")
        if not cid:
            return
        batch = self._guest_pending.setdefault(cid, [])
        batch.append(msg)
        window = float(self.cfg.behavior.merge_window_sec)
        if window <= 0 or len(batch) >= max(2, int(self.cfg.behavior.merge_max_msgs)):
            self._flush_guest(cid)
            return
        task = self._guest_tasks.get(cid)
        if task and not task.done():
            task.cancel()
        self._guest_tasks[cid] = asyncio.create_task(self._guest_after(cid, window))

    async def _guest_after(self, cid: str, delay: float) -> None:
        try:
            await asyncio.sleep(delay)
        except asyncio.CancelledError:
            return
        self._flush_guest(cid)

    def _flush_guest(self, cid: str) -> None:
        batch = self._guest_pending.pop(cid, [])
        if not batch:
            return
        task = self._guest_tasks.pop(cid, None)
        if task and not task.done() and task is not asyncio.current_task():
            task.cancel()
        merged = self._merge_messages(batch)
        g = self._guest_for(cid)
        if not g:
            return
        asyncio.create_task(self._run_guest(g, merged))

    async def _run_guest(self, g: GuestRuntime, msg: IncomingMessage) -> None:
        try:
            await g.handle(msg)
        except Exception as e:  # noqa: BLE001
            print(f"[main] 角色 {g.char.name} 回复失败：{e!r}")

    @staticmethod
    def _merge_messages(batch: List[IncomingMessage]) -> IncomingMessage:
        """把同一批消息并成一条：文本拼接、图片/转发 id 汇总。"""
        head = batch[0]
        texts = [m.text.strip() for m in batch if m.text.strip()]
        # 给 transcript 留一份「原始分条」：合并只用于这一轮理解，
        # 历史里仍然一条一条显示，不再变成一条长消息。
        store_texts: List[str] = []
        store_times: List[float] = []
        images: List[List[str]] = []
        ids: List[str] = []
        sizes: List[str] = []
        fwds: List[str] = []
        for m in batch:
            t = m.text.strip()
            if not t:
                t = "[图片]" if m.images else "[消息]"
            store_texts.append(t)
            store_times.append(float((m.raw or {}).get("time") or 0) or time.time())
            images.extend(m.images)
            ids.extend(m.raw_image_ids)
            sizes.extend(m.raw_image_sizes)
            fwds.extend(m.forward_ids)
        head.text = "\n".join(texts)
        head.images = images
        head.raw_image_ids = ids
        head.raw_image_sizes = sizes
        head.forward_ids = fwds
        head.raw = {**(head.raw or {}), "_merged_count": len(batch),
                    "_merged_texts": store_texts, "_merged_times": store_times}
        return head

    @staticmethod
    def _store_user_turns(store: Store, msg: IncomingMessage) -> None:
        """把用户消息按原始分条写进历史（合并只影响理解，不影响回放）。"""
        raw = msg.raw or {}
        texts = raw.get("_merged_texts")
        times = raw.get("_merged_times")
        if isinstance(texts, list) and texts:
            for i, t in enumerate(texts):
                ts = None
                if isinstance(times, list) and i < len(times):
                    ts = float(times[i] or 0) or None
                store.add_turn("user", str(t)[:400], ts=ts)
            return
        store.add_turn("user", (msg.text or "[图片]")[:400])

    @staticmethod
    def _is_sticker_only(msg: IncomingMessage) -> bool:
        """这条是不是「只甩了个表情包、没有文字」。

        ⚠️ 判定必须**有正面证据**，不能只凭「没文字 + 有图」—— 
        因为**截图/长图也是没文字的**，那种必须回。
        （实测踩过：把用户发的聊天记录截图当成表情包跳过了。）

        算表情包的证据（NapCat 会给）：
          - 段类型是 mface / marketface（QQ 商城表情）
          - sub_type == "1"（自定义表情）
          - summary 含「动画表情」
        没有这些标记的普通 image 段，一律当**正经内容**处理。
        """
        if (msg.text or "").strip():
            return False
        if msg.forward_ids:
            return False
        if not msg.images:
            return False
        return Companion._message_is_sticker(msg)

    @staticmethod
    def _message_is_sticker(msg: IncomingMessage) -> bool:
        """消息里的图是不是全都是表情包（配了文字也算）。

        用来决定表达通道要不要点评图片：表情包基本不点评，
        普通照片/截图才聊画面内容。
        """
        if not msg.images:
            return False
        segs = msg.raw.get("message")
        if not isinstance(segs, list):
            return False
        saw_sticker = False
        for s in segs:
            if not isinstance(s, dict):
                continue
            t = s.get("type")
            d = s.get("data") or {}
            if t in ("mface", "marketface"):
                saw_sticker = True
            elif t == "image":
                summary = str(d.get("summary") or "")
                if str(d.get("sub_type") or "") == "1" or "动画表情" in summary:
                    saw_sticker = True
                else:
                    return False      # 混着普通图 → 按图片处理
        return saw_sticker

    @staticmethod
    def _strip_meta_reply(reply, *, aggressive: bool = False):
        """去掉「图大叔收下了 / 斗图正好用 / 收进表情包库」这类句子。

        aggressive=True 用于表情包（任何「收下/收了」都突兀）；
        普通图片只拦「这张图/收图/斗图」这类明确指向图片的说法，
        避免误伤「这话我收下了」。
        """
        pat = _META_STICKER_STRICT if aggressive else _META_IMAGE_NARROW

        def keep(line: str) -> bool:
            return bool(str(line).strip()) and not pat.search(str(line))

        if isinstance(reply, list):
            out: List[str] = []
            for bubble in reply:
                kept = [ln for ln in str(bubble).split("\n") if keep(ln)]
                if kept:
                    out.append("\n".join(kept))
            return out
        return "\n".join(ln for ln in str(reply).split("\n") if keep(ln))

    @staticmethod
    def _sanitize_recent(lines: List[str]) -> List[str]:
        """提示词里的历史记录剔掉旧句式；UI 里的历史不动。"""
        out: List[str] = []
        for line in lines:
            if "assistant:" in line and _META_STICKER_STRICT.search(line):
                continue
            out.append(line)
        return out

    async def _run_pipeline(self, msg: IncomingMessage, notify: bool = False) -> None:
        try:
            await self._pipeline(msg)
        except Exception as e:  # noqa: BLE001
            print(f"[main] 处理出错：{e!r}")
            if notify:
                await self.channel.send_text(
                    "（这边出了点问题，稍后再试）",
                    user_id=msg.user_id if msg.is_private else "",
                    group_id=msg.group_id,
                )

    def _note_ignored(self, kind: str, peer: str, why: str) -> None:
        """被忽略的消息打一条节流日志。

        为什么要打日志：NapCat 会把**它收到的所有消息**都推给本服务
        （包括你在的所有群），所以日志里会看到大量「接收 <- 群聊」。
        那不是我们在处理，是 NapCat 在转发，我们在门口就丢了。
        但不打日志的话，用户只能靠猜 —— 所以这里 30 秒提示一次，并累计计数。
        """
        self._ignored_count += 1
        now = time.time()
        if now - self._ignored_last_log < 30:
            return
        self._ignored_last_log = now
        print(f"[main] 已忽略 {kind}消息（累计 {self._ignored_count} 条，"
              f"最近来自 {peer}）：{why}")
        print("[main]   ↳ 忽略 = 不回复、不下载图片、不写入记忆、不影响情绪状态")

    # ---------------- 调试指令 ----------------
    async def _handle_command(self, msg: IncomingMessage, text: str) -> bool:
        target = {"user_id": msg.user_id if msg.is_private else "", "group_id": msg.group_id}
        if text == "/state":
            await self.channel.send_text(
                "内部状态：\n" + self.state.describe()
                + f"\n\n已忽略消息：{self._ignored_count} 条"
                + f"（群聊策略 {self.cfg.qq.group_mode}，非主人私聊也不回）"
                + f"\n它们不影响情绪状态，也没进记忆。",
                **target,
            )
            return True
        if text == "/why":
            last = self.store.kv_get("last_analysis") or {}
            import json
            await self.channel.send_text(
                "上一轮分析通道输出：\n```json\n"
                + json.dumps(last, ensure_ascii=False, indent=1)
                + "\n```",
                **target,
            )
            return True
        if text == "/poke":
            decision = await self.heartbeat.poke_once(force=True)
            await self.channel.send_text("心跳结果：" + str(decision), **target)
            return True
        if text == "/next":
            a = self.heartbeat.cfg
            t = self.primary_traits
            await self.channel.send_text(
                "下一次主动消息：" + self.heartbeat.next_desc()
                + f"\n\n今日已主动 {int(self.heartbeat._today_count())}/{a.daily_max} 次"
                + f"\n连续冷场 {int(self.heartbeat._cold_streak())} 次"
                + f"\n免打扰 {a.quiet_hours[0]}~{a.quiet_hours[1]}"
                + f"\n\n节奏权重 {list(a.rhythm_weights)}"
                + f"（马上/近/常/远），顺延概率 {a.skip_probability:.0%}"
                + f"\n\n关系参数 热情 {t.enthusiasm} / 好感 {t.affection}"
                + f"\n{trait_preview(t)}",
                **target,
            )
            return True
        if text.startswith("/mood"):
            word = text[5:].strip()
            ok = self.state.manual_mood(word) if word else False
            await self.channel.send_text(
                f"已把心情设为「{word}」" if ok else "没有这个预设（开心/平静/低落/烦躁/兴奋）",
                **target,
            )
            return True
        return False

    # ---------------- 主管线 ----------------
    async def _pipeline(self, msg: IncomingMessage) -> None:
        # 先算「距上次互动多久」，再重置计数器
        import time as _t

        prev_reply_ts = self.heartbeat.last_reply_ts
        gap_h = (_t.time() - prev_reply_ts) / 3600.0 if prev_reply_ts else None
        # ★ 对方回来之前，我是不是在「等回应」？等了多久？
        #   （上一条主动消息发出后一直没人回 → 这次回来就是「重逢」）
        last_spoke = self.heartbeat.last_spoke_ts
        wait_h = ((_t.time() - last_spoke) / 3600.0
                  if last_spoke and last_spoke > prev_reply_ts else 0.0)
        self.heartbeat.on_user_message()
        if wait_h >= 1.0:
            self.state.note_reunion(wait_h)
            print(f"[main] 重逢：等了 {wait_h:.1f} 小时终于被回 → 开心/惊喜/撒娇一次")

        # ★ 互道收尾循环防护：对方收尾、自己也回过收尾之后，
        # 对方再发一句「晚安」这种收尾话 —— 不再走完整管线
        # （原来的行为：对着「晚安」再写一大段，或者干脆把窗口重新点着继续聊）。
        if self.conversation.in_close() and is_closing_text(msg.text or ""):
            self._store_user_turns(self.store, msg)
            print(f"[main] 互道收尾（{msg.text[:12]}…）→ 超短回应或沉默")
            if random.random() < 0.5:
                await self.sender.reply(
                    random.choice(_SHORT_CLOSINGS),
                    user_id=msg.user_id if msg.is_private else "",
                    group_id=msg.group_id,
                )
            self.conversation.rearm_close()
            return

        # 用户说话了 → 进入/刷新「活跃会话窗口」，之后它会自己把话接下去
        # ★ bump_generation=False：此刻还不知道这批会不会开口（表情包
        #   批次可能整批跳过不回话）。真正顶掉在途旧回复的代际 bump
        #   推迟到下面「确定必定要开口」之后，见那边的注释。
        self.conversation.on_user_message(msg.text, bump_generation=False)
        # unanswered_h=0：对方开口了 → 「被晾着」的委屈感开始消退
        self.state.tick(last_interaction_ago_h=gap_h, resting=False,
                        unanswered_h=0.0)

        target = {"user_id": msg.user_id if msg.is_private else "", "group_id": msg.group_id}

        # 1) 感知：图片（每张图可能是多个候选来源，依次尝试）
        image_desc = ""
        image_is_sticker = self._message_is_sticker(msg)
        if msg.images:
            descs: List[str] = []
            for cands in msg.images[:2]:
                # ★ 把图片段的**全部原始字段**打出来。
                # 之前只打「候选」，结果看不出是字段名不对还是数据被截断 ——
                # 而这两件事的修法完全不同，必须先把事实看清。
                print("[main] 图片段原始字段：")
                for seg in (msg.raw.get("message") or []):
                    if isinstance(seg, dict) and seg.get("type") in (
                            "image", "mface", "marketface"):
                        for k, v in (seg.get("data") or {}).items():
                            s = str(v)
                            print(f"[main]   {k} = "
                                  + (f"<{len(s)} 字符>" if k == "base64" else repr(s)))
                        break
                print(f"[main] 解析出的候选（共 {len(cands)} 个）：")
                for c in cands:
                    print(f"[main]   - {_short_src(c)}")
                declared = (msg.raw_image_sizes[0] if msg.raw_image_sizes else "")
                if declared:
                    print(f"[main] NapCat 声明这张图有 {declared} 字节"
                          f"（拿到后我会比对，看有没有被截断）")

                # NapCat 的 HTTP 接口地址：优先用 channel 的配置，
                # 测试里用的是 ConsoleChannel（没有 cfg），所以从 self.cfg 兜底。
                ch_cfg = getattr(self.channel, "cfg", None) or self.cfg.qq
                raw, mime, hit, why = await load_first_image(
                    cands,
                    file_id=msg.raw_image_ids[0] if msg.raw_image_ids else "",
                    http_base=ch_cfg.http_base,
                    http_token=ch_cfg.http_token,
                )
                if raw:
                    src_tag = "base64" if hit.startswith("data:") else hit[:60]
                    extra = f"（{why}）" if why else ""
                    # ★ 用 NapCat 声明的字节数校验：对不上就是被截断了
                    try:
                        want = int(declared) if declared else 0
                    except ValueError:
                        want = 0
                    if want and len(raw) < want:
                        print(f"[main] ⚠️⚠️ 截断确认：NapCat 说有 {want} 字节，"
                              f"实际只拿到 {len(raw)} 字节（差 {want - len(raw)}）")
                    elif want:
                        print(f"[main] 字节数吻合（{want}）—— 数据完整")
                    print(f"[main] 图片取到了（来源：{src_tag}，类型 {mime}，"
                          f"{len(raw)} bytes）{extra}")
                    one = await describe_image(self.llm, raw, msg.text, mime,
                                               dump_dir=self.dump_dir)
                    descs.append(one)
                    # 任何「看不成」的情况都把原始段结构落盘（含 base64 头尾）
                    if one.startswith("（图片"):
                        print(f"[main] ⚠️ 识图失败，原样内容：{one[:200]}")
                        p = dump_raw_event(msg.raw, f"识图失败：{one[:60]}",
                                           self.dump_dir, keep_base64_snippet=True)
                        if p:
                            print(f"[main] 原始结构（含 base64 头尾+候选清单）已写入 {p}")

                    # 偷表情包：私聊主人发的图才考虑（群里的默认不收）
                    if msg.is_private:
                        sv = await self.stealer.consider(
                            self.llm, raw, mime, image_desc=one, user_text=msg.text)
                        if sv.keep:
                            item = self.stealer.save(raw, mime, sv)
                            if item:
                                # 只在自己的库里收，不往回复里带话。
                                # 真人几乎不会专门说「这张图我收下了」——
                                # 实测 4878 次发表情，这类话只出现 10 次（0.2%）。
                                print("[steal] 已静默入库（不在回复里提）")
                        else:
                            print(f"[steal] 没收：{sv.reason}")
                else:
                    print("=" * 58)
                    print("[main] ⚠️ 图片取不到。各个来源依次试过：")
                    for c in cands:
                        print(f"[main]   - {_short_src(c)}")
                    print("[main] 原始消息结构（把这几行复制发出去就能定位）：")
                    print(format_event_brief(msg.raw))
                    p = dump_raw_event(msg.raw, "所有图片来源都取不到", self.dump_dir,
                                       keep_base64_snippet=True)
                    if p:
                        print(f"[main] （同时也记到了 {p}）")
                    print("=" * 58)
                    descs.append("（图片没取到，没能看到内容）")
            image_desc = " | ".join(d for d in descs if d)
            if image_desc:
                print(f"[main] 图片理解：{image_desc[:60]}")
                # 存下来，方便事后从数据库看「它到底看到了什么」
                self.store.kv_set("last_image_desc", image_desc[:500])
            else:
                # 有图却什么都没得到 —— 这是最坏的情况：模型会自己编「打不开」
                print("[main] ⚠️⚠️ 收到了图但没得到任何描述（异常或空返回），"
                      "上层只能瞎猜。看上面 [perceive] 的日志定位。")
        elif msg.raw.get("message"):
            # 消息里明明有媒体段，却一张图都没解析出来
            raw_list = msg.raw.get("message")
            if isinstance(raw_list, list) and any(
                isinstance(s, dict) and s.get("type") in ("image", "mface", "marketface")
                for s in raw_list
            ):
                p = dump_raw_event(msg.raw, "有图段但没解析出候选来源", self.dump_dir)
                if p:
                    print(f"[main] 该消息有图段但解析不出图源，原始结构已写入 {p}")

        # 1b) 合并转发（QQ「聊天记录」）—— 段里只有 id，正文要另取。
        # 不做这一步的话，对方转发一整段聊天记录过来，模型眼里是空的。
        if msg.forward_ids:
            chunks: List[str] = []
            for fid in msg.forward_ids[:2]:
                body = await self.channel.fetch_forward(fid)
                if body:
                    chunks.append(body)
                    print(f"[main] 聊天记录已展开（{len(body)} 字符）")
            if chunks:
                merged = "\n----------\n".join(chunks)
                if len(merged) > 4000:
                    merged = merged[:4000] + "\n…（内容过长，已截断）"
                msg.text = (msg.text + "\n" + merged).strip()
            else:
                print("[main] ⚠️ 聊天记录取不到正文（接口没应答或返回为空）")

        # ★ 只发了一个表情包（没有文字）→ 不用每条都回。
        # 真人不会你甩一张图他就接一句；但也不能完全不吭声，
        # 所以按概率决定，并且**照常更新状态、照常偷图**。
        if self._is_sticker_only(msg):
            if random.random() > float(self.cfg.behavior.sticker_only_reply_prob):
                # 只更新状态与记忆，不回话
                self.state.apply_interaction(0.55)
                self.store.add_turn("user", "[表情包]")
                print("[main] 只发了个表情包 → 这轮不回（它自己不这么干）")
                return

        # ★ 代际 bump 的正确位置：过了这道门，本批**必定要开口**。
        # 不能在管线入口就 bump —— 「纯表情包」批次走上面那条路整批
        # 跳过、永远不回话，却把上一批正在生成的回复顶掉了：
        # 实测事故 = 7 条正经文字被随后一张表情图吞掉，干等 8 分钟
        # 才由接话循环兜底。跳过的批次不 bump，在途回复就能活着发出。
        self.conversation.conv.generation += 1

        # 2) 感知：情绪打标 → 状态机
        turns = self.store.recent_turns(12)
        # ★ 提示词里必须带日期和时间：否则模型看到「晚安」就以为还是刚才，
        #   第二天下午还会问「不是说睡了，睡不着又爬回来了？」（实测事故）
        time_text = format_time_context(turns)
        recent = format_recent(turns)
        # 旧回复里可能留着「图大叔收下了」这类句式；从提示词里剔掉，避免照抄
        recent = self._sanitize_recent(recent)
        emotion = await tag_emotion(self.llm, msg.text or image_desc, recent)
        event = EMOTION_TO_EVENT.get(emotion["label"])
        if event:
            self.state.apply_event(event, intensity=emotion["intensity"])

        # 3) 认知：分析通道
        relation = trait_text(self.primary_traits)
        analysis = await analyze(
            self.llm,
            user_text=msg.text or ("（发来一个表情包）" if image_is_sticker
                                   else "（发来一张图）"),
            recent=recent,
            profile_text=self.memory.profile_text(),
            state_text=self.state.describe(),
            image_desc=image_desc,
            image_is_sticker=image_is_sticker,
            time_text=time_text,
            trait_text=relation,
            presence_text=self.presence_text,
        )
        self.store.kv_set("last_analysis", {**analysis, "emotion_tag": emotion})
        if analysis.get("intent"):
            self.conversation.conv.topic = str(analysis["intent"])

        # ★ 对方在收尾（晚安/去忙）：表达按收尾话写，发完就停，不再追话
        closing = bool(analysis.get("is_closing")) or is_closing_text(msg.text or "")
        # ★ 自己说出口的事实/承诺落库（防「上午答应的事下午全忘」的人设断裂）
        for fact in analysis.get("self_facts") or []:
            if isinstance(fact, dict):
                self.memory.set_self_fact(str(fact.get("key", "")),
                                          str(fact.get("value", "")))

        # ★ 判断这轮是不是「情绪深聊」，是就把连发上限放宽。
        # 用户反馈：倾诉/需要安慰时「三轮就收住」明显不够。
        need = str(analysis.get("latent_need") or "")
        deep = (need in ("想倾诉", "被安慰", "想陪伴", "被看见", "被认可")
                or str(analysis.get("risk") or "none") not in ("", "none")
                or float(analysis.get("relation_signal") or 0) > 0.5)
        if deep:
            self.conversation.on_user_message(msg.text, deep=True,
                                              bump_generation=False)

        # 4) 状态与记忆更新
        self.state.apply_interaction(float(analysis.get("quality", 0.5)))
        for upd in analysis.get("profile_updates") or []:
            if isinstance(upd, dict):
                self.memory.set_profile(str(upd.get("key", "")), str(upd.get("value", "")))
        if analysis.get("memory_worthy") and analysis.get("memory_summary"):
            self.memory.add_episodic(
                str(analysis["memory_summary"]), emotion=emotion,
                importance=float(emotion.get("intensity", 0.5)),
            )
        if analysis.get("interest_terms"):
            for term in analysis["interest_terms"]:
                self.memory.bump_interest(str(term), 1.0)

        risk = str(analysis.get("risk", "none"))
        if risk in HIGH_RISK:
            self.store.add_event(msg.text[:200], kind="risk", emotion=emotion,
                                 importance=1.0, flagged=True)
            print(f"[main] ⚠️ 风险信号：{risk}")

        self._store_user_turns(self.store, msg)

        # ★ 会话恢复：最近 7 天内上一次会话的摘要 —— 新开话时它
        # 还记得上次聊到哪（防「跨会话身份断裂」）
        resume_hint = ""
        now_ts = _t.time()
        for ev in self.store.recent_events(30):
            if ev.get("kind") == "summary" and now_ts - float(ev.get("ts") or 0) < 7 * 86400:
                resume_hint = str(ev.get("text") or "")[:200]
                break

        # ★ 禁用词：自己最近说多了的词，这轮别再碰（防复读环的硬约束）
        _turns = self.store.recent_turns(12)
        avoid_terms = extract_overused_terms(
            [t["text"] for t in _turns if t["role"] == "assistant"],
            [t["text"] for t in _turns if t["role"] == "user"],
        )

        # ★ 代际捕获：从这里开始，如果用户又说了话（generation +1），
        # 说明这条回复面对的上下文已经旧了 —— 更新的那批消息会得到
        # 覆盖全貌的回复。旧批次若照发，就是「对着空气自说自话」，
        # 排队在发送锁后面时尤其严重（用户体感：他一句一句回不完）。
        gen = self.conversation.conv.generation

        # 5) 表达通道
        reply = await express(
            self.llm,
            persona=self.cfg.read_persona("persona.md"),
            boundaries=self.cfg.read_persona("boundaries.md"),
            state_text=self.state.describe(),
            memory_text=self.memory.recall_text(msg.text or image_desc, self.cfg.memory.recall_top_k),
            recent=recent,
            user_text=msg.text or (
                "（对方发来一个表情包）" if image_is_sticker
                else ("（对方发来一张图片）" if image_desc else "")),
            analysis=analysis,
            world=self.cfg.read_persona("world.md"),
            image_desc=image_desc,      # 关键：图的内容必须给到表达通道，否则等于没看
            image_is_sticker=image_is_sticker,
            time_text=time_text,        # 当前时间 + 距上次说话多久
            profile_text=self.memory.profile_text(),   # ★ 让她记得对方是谁/在做什么
            arousal=self.state.emotion.arousal,
            valence=self.state.emotion.valence,
            # 对方在倾诉/有风险信号时，说话收一点（别太飘）
            serious=(risk not in ("", "none") or need in ("想倾诉", "被安慰")),
            # ★ 气泡协议 + 收尾意图 + 禁用词 + 会话恢复 + 既定事实
            bubble_mode=True,
            closing=closing,
            avoid_terms=avoid_terms or None,
            resume_hint=resume_hint,
            self_facts_text=self.memory.self_facts_text(),
            trait_text=relation,
            presence_text=self.presence_text,
            # ★ 作息：凌晨三点被叫醒的人，回话不该精神抖擞（角色各有睡点）
            schedule_text=self._schedule_text_for(self.characters.primary),
        )
        if not reply:
            return
        # ★ 表达期间用户又说话了 → 这批回复作废（新批次的回复会覆盖全部内容）
        if gen != self.conversation.conv.generation:
            print("[main] 用户在生成期间又说话了 → 本批回复作废（由最新批次统一回应）")
            return

        # ★ 兜底过滤：表情包/图片回复里不许出现「收下 / 斗图 / 收进图库」。
        #   提示词已经禁止，但旧历史style偶尔还是会被照抄，发出去就崩。
        if msg.images:
            reply = self._strip_meta_reply(
                reply, aggressive=image_is_sticker)
            if not reply:
                reply = "哈哈" if image_is_sticker else "嗯"
                print("[main] 回复只剩「收下/斗图」句式 → 已替换成短反应")

        # 气泡列表 vs 纯文本（气泡解析失败时自动回退纯文本协议）
        if isinstance(reply, list):
            bubbles = [b for b in reply if b]
            if not bubbles:
                return
            reply_text = "\n".join(bubbles)
        else:
            bubbles = []
            reply_text = reply
        if not reply_text:
            return

        # 6) 表情包决策：先过「频率策略」，过了再问模型——发不发、发几张、发哪类
        sticker_files: List[str] = []
        if self.stickers.available:
            room = self.sticker_policy.remaining_today()
            intensity = float(emotion.get("intensity", 0.5) or 0.5)
            pol = self.sticker_policy.evaluate(
                emotion=emotion["label"],
                intensity=intensity,
                valence=self.state.emotion.valence,
                energy=self.state.emotion.energy,
                last_was_sticker=bool(self.store.kv_get("last_was_sticker", False)),
            )
            if not pol.send:
                print(f"[main] 不发表情包：{pol.reason}")
            else:
                verdict = await judge_sticker(
                    self.llm, reply_text, msg.text, emotion["label"],
                    last_was_sticker=False,
                    hint=f"（图库共 {len(self.stickers.items)} 张可选）",
                    outgoing_room=int(room),
                )
                if verdict.get("send"):
                    emo = str(verdict.get("emotion") or emotion["label"])
                    # ★ 张数由模型按语境定；策略只做兜底 + 封顶
                    want = int(verdict.get("count") or 0) or \
                        self.sticker_policy.how_many(intensity, emo)
                    want = self.sticker_policy.clamp_count(want, room=int(room))
                    picked = self.stickers.pick_many(emo, reply_text, want,
                                                     prefer_source="星野")
                    if picked:
                        sticker_files = [p["file"] for p in picked]
                        self.sticker_policy.note_sent(len(sticker_files))
                        names = "、".join(Path(f).name for f in sticker_files)
                        print(f"[main] 发表情包 {len(sticker_files)} 张：{names}"
                              f"（情绪 {emo}｜{pol.reason}"
                              f"｜{verdict.get('reason', '')}）")
                    else:
                        print(f"[main] 图库里没有情绪「{emo}」的合适表情")
                else:
                    print(f"[main] 模型判断不配图：{verdict.get('reason', '')}")

        # 7) 发送
        # ★ 节奏镜像：对方回话一直很慢（>30s）时，自己也不秒回 ——
        # 秒回本身就不像人。快节奏闲聊不镜像（不然对话被拖死）。
        # 上限 120s（原 600s 配合被污染的 pace 样本能拖出 10 分钟
        # 「发消息不回」的事故；真人慢节奏也就一两分钟）。
        pace = self.conversation.partner_pace()
        if pace > 30:
            await asyncio.sleep(min(120.0, max(2.0, pace * random.uniform(0.6, 1.5))))

        # ★ 节奏镜像的等待也给了对方插话的机会 —— 再查一次代际
        if gen != self.conversation.conv.generation:
            print("[main] 发送前用户又说话了 → 本批回复作废（由最新批次统一回应）")
            return

        # 发送中途对方插话 → 停发剩余气泡（同频的关键：别把一整轮旧话
        # 灌完才轮到对方）。
        def _stale() -> bool:
            return gen != self.conversation.conv.generation

        # ★ 追时：目标总延迟按真人分布抽（outbound_delay_ms 的语义
        # 从「出站前的额外等待」升级为「距对方最后一条的总延迟目标」），
        # 扣掉合并等待 + 推理已经花掉的时间 —— 总延迟贴真人（中位 14s）
        delay_ms = catchup_delay_ms(self.cfg.behavior.outbound_delay_ms,
                                    self.conversation.conv.last_user_ts,
                                    time.time())

        if bubbles:
            sent = await self.sender.reply_bubbles(
                bubbles, sticker_files=sticker_files, abort_check=_stale,
                delay_sec=delay_ms / 1000.0,
                delay_scale=self.primary_traits.delay_scale, **target)
        else:
            sent = await self.sender.reply(
                reply_text, sticker_files=sticker_files, abort_check=_stale,
                delay_sec=delay_ms / 1000.0,
                delay_scale=self.primary_traits.delay_scale, **target)
        # 一条都没发出去（刚进锁就被中止）→ 等同于作废
        if sent == 0 and gen != self.conversation.conv.generation:
            print("[main] 本批回复被新消息中止，未发出任何内容")
            return
        self.store.kv_set("last_was_sticker", bool(sticker_files))
        self.store.add_turn("assistant", reply_text[:400])
        # ★ 连发上限按气泡计：这条「回答」也占配额（发了 3 条就是 3，
        # 不是 1），确保一口气 5 气泡的长回复之后不再追话
        self.conversation.on_bot_message(count_as_turn=True, bubbles=max(1, sent))
        # 对方收尾了：互道收尾后停，等下次开话
        if closing:
            self.conversation.on_close()


def _pid_file() -> Path:
    """把 PID 写到 vol/run/companion.pid，「一键停止」靠它精确停进程。

    路径：app/main.py -> app -> companion -> 专属AI伴侣 -> vol
    """
    return Path(__file__).resolve().parent.parent.parent.parent / "run" / "companion.pid"


def _write_pid() -> None:
    try:
        p = _pid_file()
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(str(os.getpid()), encoding="ascii")
    except OSError as e:
        print(f"[main] PID 记录失败（不影响运行）：{e!r}")


def _clear_pid() -> None:
    try:
        p = _pid_file()
        if p.exists():
            p.unlink()
    except OSError:
        pass


async def amain(console: bool = False) -> None:
    cfg = load_config()
    _write_pid()

    if console:
        from .channel.console import ConsoleChannel

        ch = ConsoleChannel(owner_id=cfg.qq.owner_id or "owner")
        comp = Companion(cfg, channel=ch)
        # 控制台模式默认不开心跳（避免刷屏），要测就手动 /poke
        comp.heartbeat._stop.set()
        comp._print_policy()
        # 但对话连贯要开着 —— 不然在终端里也测不出「聊下去」的效果
        conv_task = asyncio.create_task(comp.conversation.run())
        try:
            # 注意：ConsoleChannel.run() 内部自己会调 start()，这里不要再调一次
            await comp.channel.run(comp.handle)
        except (KeyboardInterrupt, EOFError):
            pass
        finally:
            comp.conversation.stop()
            conv_task.cancel()
            await comp.stop()
            _clear_pid()
            print("\n[main] 已退出")
        return

    comp = Companion(cfg)

    loop = asyncio.get_running_loop()
    stop = asyncio.Event()

    def _sig(*_a):
        stop.set()

    try:
        loop.add_signal_handler(signal.SIGINT, _sig)
        loop.add_signal_handler(signal.SIGTERM, _sig)
    except NotImplementedError:
        # Windows 上 add_signal_handler 不完整支持，退化为 KeyboardInterrupt
        pass

    await comp.start()
    print("[main] 已就绪。Ctrl+C 退出。")
    try:
        await stop.wait()
    except KeyboardInterrupt:
        pass
    finally:
        await comp.stop()
        _clear_pid()
        print("[main] 已退出")


def _fatal(msg: str, code: int = 3) -> int:
    print()
    print("=" * 58)
    print(msg)
    print("=" * 58)
    return code


class _Tee:
    """把 stdout/stderr 同时写到控制台和日志文件。

    为什么需要：原来日志只进控制台窗口，窗口一关就没了 ——
    你排查不了、我也看不到「它到底为什么没主动找我」。
    有了落盘日志，出问题直接看 data/companion.log 就行。
    """

    def __init__(self, path, stream):
        self.stream = stream
        self.path = path
        self._lock = threading.Lock()
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            # 超过 4MB 就轮转一份，避免无限长
            if path.exists() and path.stat().st_size > 4 * 1024 * 1024:
                bak = path.with_suffix(".1.log")
                try:
                    if bak.exists():
                        bak.unlink()
                    path.replace(bak)
                except OSError:
                    pass
            self._fh = io.open(path, "a", encoding="utf-8", errors="replace")
        except OSError:
            self._fh = None

    def write(self, s):
        with self._lock:
            try:
                self.stream.write(s)
            except Exception:  # noqa: BLE001
                pass
            if self._fh is not None:
                try:
                    self._fh.write(s)
                    self._fh.flush()          # 崩了也要留下最后几行
                except Exception:  # noqa: BLE001
                    pass

    def flush(self):
        for f in (self.stream, self._fh):
            try:
                if f is not None:
                    f.flush()
            except Exception:  # noqa: BLE001
                pass


def _install_log_file() -> None:
    """装日志落盘（幂等）。控制台模式不装，免得干扰。"""
    if getattr(_install_log_file, "_done", False):
        return
    _install_log_file._done = True
    try:
        root = Path(__file__).resolve().parent.parent
    except NameError:
        return
    log = root / "data" / "companion.log"
    sys.stdout = _Tee(log, sys.stdout)
    sys.stderr = _Tee(log, sys.stderr)
    print(f"[main] 日志同时写入 {log}")


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser(description="专属 AI 伴侣")
    ap.add_argument(
        "--console",
        action="store_true",
        help="本地控制台模式：不连 QQ，直接在终端对话（用来调人设和情绪）",
    )
    args = ap.parse_args()
    if not args.console:
        _install_log_file()

    try:
        asyncio.run(amain(console=args.console))
    except PortInUse as e:
        sys.exit(_fatal(f"启动失败：{e}"))
    except RuntimeError as e:      # onebot-server 端口占用等
        sys.exit(_fatal(f"启动失败：{e}"))
    except (KeyboardInterrupt, SystemExit):
        sys.exit(0)
