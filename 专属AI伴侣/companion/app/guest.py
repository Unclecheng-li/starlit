"""新增角色的运行时。

和星野共用同一个 LLM / 发送器 / 表情包库 / 搜索器，但拥有：

- 独立的 SQLite（`data/characters/<id>/companion.db`）
- 独立的短期对话、长期记忆、情绪状态
- 自己的人格卡

为了让新角色也「像活人」而不是只会被动回答，这里接上了和星野
同一套行为习惯：心跳主动、上线问候、接话、表情包节奏、时间感知。
只替换人格卡；行为参数（节奏、延迟、拆条、抑制链）保持一致。

为避免十个角色同时刷屏，每个新增角色的主动配额更克制：
每日 2 次、最小间隔 2 小时、自主分享每日 1 次。
"""
from __future__ import annotations

import asyncio
import time
from dataclasses import replace
from typing import List

from .act import Sender
from .autonomy.conversation import ConversationRunner, is_closing_text
from .autonomy.digest import Digest
from .autonomy.heartbeat import Heartbeat
from .autonomy.suppress import Suppressor
from .channel.napcat import IncomingMessage
from .characters import Character
from .config import Config
from .memory import Memory
from .perceive import describe_image, load_first_image
from .presence import get_presence, presence_text
from .state import EMOTION_TO_EVENT, StateMachine
from .sticker import StickerPolicy
from .store import Store
from .think import (analyze, express, extract_overused_terms,
                    format_recent, format_time_context, judge_sticker)
from .traits import (derive_autonomy, derive_conversation, get_traits,
                     trait_text)


def _store_user_turns(store: Store, msg: IncomingMessage,
                      reply_mid: str = "") -> None:
    """按原始分条写用户消息（合并后的输入不能变成一条长历史）。"""
    raw = msg.raw or {}
    texts = raw.get("_merged_texts")
    times = raw.get("_merged_times")
    if isinstance(texts, list) and texts:
        last_tid = 0
        for i, t in enumerate(texts):
            ts = None
            if isinstance(times, list) and i < len(times):
                ts = float(times[i] or 0) or None
            last_tid = store.add_turn("user", str(t)[:400], ts=ts)
        if reply_mid and last_tid:
            store.set_turn_reply(last_tid, reply_mid)
        return
    tid = store.add_turn("user", (msg.text or "[图片]")[:400])
    if reply_mid and tid:
        store.set_turn_reply(tid, reply_mid)


def _reply_mid_of(msg: IncomingMessage) -> str:
    """这条消息引用了哪一条（reply 段的 id）。"""
    raw = msg.raw or {}
    for seg in (raw.get("message") or []):
        if isinstance(seg, dict) and seg.get("type") == "reply":
            d = seg.get("data") if isinstance(seg.get("data"), dict) else {}
            rid = str(d.get("id") or d.get("message_id") or "").strip()
            if rid:
                return rid
    return str(raw.get("_reply_id") or "").strip()


def _sticker_like(msg: IncomingMessage) -> bool:
    if not msg.images:
        return False
    raw = (msg.raw or {}).get("message")
    if not isinstance(raw, list):
        return False
    for seg in raw:
        if not isinstance(seg, dict):
            continue
        t = str(seg.get("type") or "")
        d = seg.get("data") or {}
        if t in ("mface", "marketface"):
            return True
        if t == "image" and str(d.get("sub_type") or d.get("subType") or "") == "1":
            return True
    return False


class GuestRuntime:
    def __init__(self, cfg: Config, char: Character, llm, sender: Sender,
                 *, stickers=None, search=None, stealer=None,
                 group_context_getter=None):
        self.cfg = cfg
        self.char = char
        self.llm = llm
        self.sender = sender
        self.stickers = stickers
        self.search = search
        self.stealer = stealer
        # ★ 私聊里也要知道「自己在群里说过什么、群里发生了什么」——
        #   群消息只写进 events（不写 transcript，免得污染私聊摘要），
        #   所以这里由 Companion 提供一段「她参与过的群聊近况」文本。
        #   None 表示她还没进任何群（那就什么都不注入）。
        self.group_context_getter = group_context_getter

        db = cfg.root / "data" / "characters" / char.id / "companion.db"
        self.store = Store(db)
        # 兴趣也必须按角色分开：星野的鲸鱼/午睡不能跑到别人身上
        interests = (cfg.root / "persona" / "characters" / char.slug
                     / "interests.md")
        self.memory = Memory(self.store, interests if interests.exists() else None)
        self.state = StateMachine(self.store)
        self.boundaries = cfg.read_persona("boundaries.md")

        # 行为习惯照搬星野的配置，再由「热情/好感」派生具体频率：
        # 热情低 → 主动少、回复慢；好感高 → 接话更密、更黏人。
        self.traits = get_traits(char.id, char.name)
        # ★ 在线状态和星野共用同一份（它是「用户现在方不方便被找」，
        #   不随角色变）—— 也叠在热情之上。
        self.presence = get_presence()
        self.presence_text = presence_text(self.presence)
        self.base_autonomy = replace(
            cfg.autonomy,
            enabled=True,
            digest_interval_min=240,       # 多个角色共用搜索，别查太勤
            greet_on_start=False,          # 上线问候由 Companion 统一错峰安排
        )
        self.base_conversation = cfg.conversation
        self.autonomy_cfg = self._derived_autonomy(self.traits)
        self.conv_cfg = derive_conversation(self.base_conversation, self.traits,
                                            self.presence)

        def _load(name: str) -> str:
            if name == "persona.md":
                return char.persona
            if name == "boundaries.md":
                return self.boundaries
            # 新角色没有单独的世界观文件，设定已经写进人格卡
            return "" if name == "world.md" else self.cfg.read_persona(name)

        self.load_persona = _load
        self.suppressor = Suppressor(self.autonomy_cfg, self.store, llm,
                                     self.state, self.memory)
        self.digest = Digest(self.autonomy_cfg, cfg.memory, llm, self.memory,
                             self.state, self.store, search)
        self.heartbeat = Heartbeat(
            self.autonomy_cfg, cfg.qq, self.store, llm, self.state, self.memory,
            self.suppressor, sender, self.digest, self.load_persona,
            sender_id=char.id, sender_name=char.name,
            trait_text=trait_text(self.traits),
            delay_scale=self.traits.delay_scale,
            presence_text=self.presence_text,
            schedule=char.schedule,
        )
        self.conversation = ConversationRunner(
            self.conv_cfg, cfg.behavior, cfg.qq, self.store, llm,
            self.state, self.memory, sender, self.suppressor, self.load_persona,
            sender_id=char.id, sender_name=char.name,
            trait_text=trait_text(self.traits),
            delay_scale=self.traits.delay_scale,
            presence_text=self.presence_text,
        )
        self.sticker_policy = StickerPolicy(cfg.sticker, self.store)
        self._hb_task = None
        self._conv_task = None
        self._started = False

    def _derived_autonomy(self, t):
        auto = derive_autonomy(self.base_autonomy, t, self.presence)
        # 九个角色共用同一套搜索/摘要资源，自主分享最多 2 条/天
        return replace(auto, digest_max_share_per_day=min(
            2, auto.digest_max_share_per_day))

    @property
    def modules(self) -> tuple[str, ...]:
        """和星野对齐的完整模块清单（新角色也必须全部具备）。"""
        return ("心跳主动", "接话", "自主分享", "抑制链",
                "表情包/偷图", "记忆", "情绪状态")

    def apply_traits(self, t) -> None:
        """网页上改了热情/好感：立即换配置并重排主动消息。"""
        self.traits = t
        self._refresh_config()

    def apply_presence(self, p) -> None:
        """用户切了在线状态：立即换配置并重排主动消息。"""
        self.presence = p
        self.presence_text = presence_text(p)
        self._refresh_config()

    def _refresh_config(self) -> None:
        """热情 + 在线状态一起重算（和星野同一层结构）。"""
        t = self.traits
        auto = self._derived_autonomy(t)
        conv = derive_conversation(self.base_conversation, t, self.presence)
        self.autonomy_cfg = auto
        self.conv_cfg = conv
        self.heartbeat.cfg = auto
        self.heartbeat.rhythm.cfg = auto
        self.suppressor.cfg = auto
        self.digest.cfg = auto
        self.conversation.cfg = conv
        self.heartbeat.trait_text = trait_text(t)
        self.heartbeat.delay_scale = t.delay_scale
        self.conversation.trait_text = trait_text(t)
        self.conversation.delay_scale = t.delay_scale
        self.heartbeat.presence_text = self.presence_text
        self.conversation.presence_text = self.presence_text
        self.heartbeat.replan()

    # ---------- 生命周期 ----------

    def start(self) -> None:
        if self._started:
            return
        self._started = True
        self._hb_task = asyncio.create_task(self.heartbeat.run())
        self._conv_task = asyncio.create_task(self.conversation.run())

    def stop(self) -> None:
        self.heartbeat.stop()
        self.conversation.stop()

    def close(self) -> None:
        self.stop()
        try:
            self.store.close()
        except Exception:  # noqa: BLE001
            pass

    async def aclose(self) -> None:
        self.stop()
        for task in (self._hb_task, self._conv_task):
            if task and not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
                except Exception:  # noqa: BLE001
                    pass
        self.close()

    async def greet(self):
        """上线问候：强制开口一次（由 Companion 错峰调用）。"""
        return await self.heartbeat.poke_once(force=True, kind="miss",
                                              force_go=True)

    # ---------- 收消息 ----------

    async def _image_desc(self, msg: IncomingMessage, *, steal: bool = False) -> str:
        if not msg.images:
            return ""
        ch_cfg = getattr(self.sender.channel, "cfg", None) or self.cfg.qq
        descs: List[str] = []
        for cands in msg.images:
            try:
                raw, mime, _hit, _why = await load_first_image(
                    cands,
                    file_id=msg.raw_image_ids[0] if msg.raw_image_ids else "",
                    http_base=getattr(ch_cfg, "http_base", ""),
                    http_token=getattr(ch_cfg, "http_token", ""),
                )
            except Exception as e:  # noqa: BLE001
                print(f"[guest:{self.char.name}] 取图失败：{e!r}")
                continue
            if not raw:
                continue
            one = await describe_image(
                self.llm, raw, msg.text, mime,
                dump_dir=self.cfg.resolve(self.cfg.memory.debug_dir))
            # 和星野一样：私聊里看到合适的图就静默收进表情包库
            if steal and self.stealer is not None:
                try:
                    sv = await self.stealer.consider(
                        self.llm, raw, mime, image_desc=one, user_text=msg.text)
                    if sv.keep:
                        self.stealer.save(raw, mime, sv)
                except Exception as e:  # noqa: BLE001
                    print(f"[guest:{self.char.name}] 偷表情包失败：{e!r}")
            if one:
                descs.append(one)
        return " | ".join(d for d in descs if d)

    async def handle(self, msg: IncomingMessage) -> None:
        text = (msg.text or "").strip()
        image_is_sticker = _sticker_like(msg)
        image_desc = await self._image_desc(msg, steal=msg.is_private)

        # 和星野一样：用户开口 → 重置冷场、刷新活跃会话、排下一次接话
        # ★ 先记下「回来之前是不是在等回应」 —— 等了很久就是一次重逢
        prev_reply = self.heartbeat.last_reply_ts
        last_spoke = self.heartbeat.last_spoke_ts
        wait_h = ((time.time() - last_spoke) / 3600.0
                  if last_spoke and last_spoke > prev_reply else 0.0)
        self.heartbeat.on_user_message()
        self.conversation.on_user_message(text, bump_generation=True)
        if wait_h >= 1.0:
            self.state.note_reunion(wait_h)
            print(f"[guest:{self.char.name}] 重逢：等了 {wait_h:.1f} 小时被回")

        turns = self.store.recent_turns(12)
        time_text = format_time_context(turns)
        recent = format_recent(turns)

        last_ts = float(turns[-1].get("ts") or 0) if turns else 0.0
        gap_h = (time.time() - last_ts) / 3600.0 if last_ts else None
        # unanswered_h=0：对方开口了 → 委屈感消退
        self.state.tick(last_interaction_ago_h=gap_h, resting=False,
                        unanswered_h=0.0)

        user_text = text or ("（发来一个表情包）" if image_is_sticker
                             else ("（发来一张图片）" if image_desc else "（发来一张图）"))
        relation = trait_text(self.traits)
        analysis = await analyze(
            self.llm,
            user_text=user_text,
            recent=recent,
            profile_text=self.memory.profile_text(),
            state_text=self.state.describe(),
            image_desc=image_desc,
            image_is_sticker=image_is_sticker,
            time_text=time_text,
            trait_text=relation,
            presence_text=self.presence_text,
            self_name=self.char.name,
        )
        if analysis.get("intent"):
            self.conversation.conv.topic = str(analysis["intent"])

        # 和星野一样：情绪标签 → 情绪状态机
        emo_label = str(analysis.get("emotion_label") or "")
        event = EMOTION_TO_EVENT.get(emo_label)
        if event:
            self.state.apply_event(event,
                                   intensity=float(analysis.get("quality", 0.5)))

        # 情绪深聊时放宽接话/连发上限
        need = str(analysis.get("latent_need") or "")
        deep = (need in ("想倾诉", "被安慰", "想陪伴", "被看见", "被认可")
                or str(analysis.get("risk") or "none") not in ("", "none")
                or float(analysis.get("relation_signal") or 0) > 0.5)
        if deep:
            self.conversation.on_user_message(text, deep=True,
                                              bump_generation=False)
        closing = bool(analysis.get("is_closing")) or is_closing_text(text)
        for fact in analysis.get("self_facts") or []:
            if isinstance(fact, dict):
                self.memory.set_self_fact(str(fact.get("key", "")),
                                          str(fact.get("value", "")))

        # 和星野一样：禁用词 + 会话恢复提示
        avoid = extract_overused_terms(
            [t["text"] for t in turns if t["role"] == "assistant"],
            [t["text"] for t in turns if t["role"] == "user"],
        )
        resume_hint = ""
        now_ts = time.time()
        for ev in self.store.recent_events(30):
            if (ev.get("kind") == "summary"
                    and now_ts - float(ev.get("ts") or 0) < 7 * 86400):
                resume_hint = str(ev.get("text") or "")[:200]
                break

        # ★ 作息：凌晨三点被叫醒的人，回话不该精神抖擞（每个角色睡点不同）
        try:
            sched_text = (self.char.schedule.scene_text()
                          if self.char.schedule else "")
        except Exception:  # noqa: BLE001
            sched_text = ""

        # ★ 私聊 ⇄ 群聊记忆互通：把她参与过的群聊近况带进私聊上下文
        group_context = ""
        if self.group_context_getter:
            try:
                group_context = self.group_context_getter(self.char.id) or ""
            except Exception:  # noqa: BLE001
                group_context = ""

        reply = await express(
            self.llm,
            persona=self.char.persona,
            boundaries=self.boundaries,
            state_text=self.state.describe(),
            memory_text=self.memory.recall_text(text or image_desc,
                                                self.cfg.memory.recall_top_k),
            recent=recent,
            user_text=user_text,
            analysis=analysis,
            world="",
            image_desc=image_desc,
            image_is_sticker=image_is_sticker,
            time_text=time_text,
            profile_text=self.memory.profile_text(),
            arousal=self.state.emotion.arousal,
            valence=self.state.emotion.valence,
            serious=analysis.get("risk") not in (None, "", "none"),
            bubble_mode=True,
            self_facts_text=self.memory.self_facts_text(),
            trait_text=relation,
            closing=closing,
            avoid_terms=avoid or None,
            resume_hint=resume_hint,
            presence_text=self.presence_text,
            schedule_text=sched_text,
            group_context=group_context,
        )
        if not reply:
            print(f"[guest:{self.char.name}] 表达通道返回空，重试一次")
            try:
                reply = await express(
                    self.llm,
                    persona=self.char.persona,
                    boundaries=self.boundaries,
                    state_text=self.state.describe(),
                    memory_text=self.memory.recall_text(
                        text or image_desc, self.cfg.memory.recall_top_k),
                    recent=recent,
                    user_text=user_text,
                    analysis=analysis,
                    world="",
                    image_desc=image_desc,
                    image_is_sticker=image_is_sticker,
                    time_text=time_text,
                    profile_text=self.memory.profile_text(),
                    arousal=self.state.emotion.arousal,
                    valence=self.state.emotion.valence,
                    serious=analysis.get("risk") not in (None, "", "none"),
                    bubble_mode=False,
                    self_facts_text=self.memory.self_facts_text(),
                    trait_text=relation,
                    closing=closing,
                    avoid_terms=avoid or None,
                    resume_hint=resume_hint,
                    presence_text=self.presence_text,
                    schedule_text=sched_text,
                    group_context=group_context,
                )
            except Exception as e:  # noqa: BLE001
                print(f"[guest:{self.char.name}] 重试也失败：{e!r}")
                reply = ""
        if not reply:
            print(f"[guest:{self.char.name}] 本轮没有生成内容（用户消息已保留）")
            _store_user_turns(self.store, msg, _reply_mid_of(msg))
            return
        bubbles = reply if isinstance(reply, list) else [reply]
        bubbles = [str(b).strip() for b in bubbles if str(b).strip()]
        if not bubbles:
            return

        # 和星野一样的表情包节奏（策略 → 模型判定 → 选图）
        sticker_files: List[str] = []
        last_sticker = bool(self.store.kv_get("last_was_sticker", False))
        if self.stickers is not None:
            try:
                emo = str(analysis.get("emotion_label") or "中性")
                pol = self.sticker_policy.evaluate(
                    emotion=emo,
                    intensity=float(analysis.get("quality", 0.6)),
                    valence=self.state.emotion.valence,
                    energy=getattr(self.state.emotion, "energy", 60.0),
                    last_was_sticker=last_sticker,
                )
                if pol.send:
                    room = int(self.sticker_policy.remaining_today())
                    verdict = await judge_sticker(
                        self.llm, "\n".join(bubbles), text or image_desc, emo,
                        last_was_sticker=last_sticker,
                        hint=f"（图库共 {len(self.stickers.items)} 张可选）",
                        outgoing_room=room,
                    )
                    if verdict.get("send"):
                        want = int(verdict.get("count") or 0) or \
                            self.sticker_policy.how_many(
                                float(analysis.get("quality", 0.6)), emo)
                        want = self.sticker_policy.clamp_count(want, room=room)
                        picked = self.stickers.pick_many(
                            str(verdict.get("emotion") or emo),
                            text or image_desc, want,
                            prefer_source=self.char.name)
                        sticker_files = [p["file"] for p in picked]
                    elif "失败" in str(verdict.get("reason") or ""):
                        # 判定模型失败时退回本地策略，别让表情包功能静默消失
                        it = self.stickers.pick(
                            emo, text or image_desc,
                            prefer_source=self.char.name)
                        if it:
                            sticker_files = [it["file"]]
            except Exception as e:  # noqa: BLE001
                print(f"[guest:{self.char.name}] 选表情包失败：{e!r}")

        _store_user_turns(self.store, msg, _reply_mid_of(msg))
        # 注意：这里**不传 abort_check**。新增角色的回复本来就该以用户
        # 最新一条为准；如果代际检查误判，会把整批回复静默吞掉（实测
        # 用户看到「发了消息但对方一直不回」）。发送锁已经保证不交错。
        sent = await self.sender.reply_bubbles(
            bubbles,
            user_id=msg.user_id,
            sticker_files=sticker_files or None,
            sender_id=self.char.id,
            sender_name=self.char.name,
            delay_scale=self.traits.delay_scale,
        )
        # 只有真的发出去才写进历史；被中止的草稿不能污染回放
        if sent:
            self.store.add_turn("assistant", "\n".join(bubbles)[:800])
            self.store.kv_set("last_was_sticker", bool(sticker_files))
            # 和星野一样：把这次发言计入接话额度，避免紧接着又追话
            self.conversation.on_bot_message(count_as_turn=True,
                                             bubbles=max(1, sent))
            if closing:
                self.conversation.on_close()
        if sent and sticker_files:
            self.sticker_policy.note_sent(len(sticker_files))

        self.state.apply_interaction(float(analysis.get("quality", 0.5)))

        for upd in analysis.get("profile_updates") or []:
            if isinstance(upd, dict):
                self.memory.set_profile(str(upd.get("key", "")),
                                        str(upd.get("value", "")))
        if analysis.get("memory_worthy") and analysis.get("memory_summary"):
            emo = {"label": analysis.get("emotion_label") or "中性",
                   "intensity": 0.5}
            self.memory.add_episodic(
                str(analysis["memory_summary"]),
                emotion=emo,
                importance=float(analysis.get("quality", 0.5)),
            )
