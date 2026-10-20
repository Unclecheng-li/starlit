"""行动层：把回复送出去。

三条「像真人」的最低成本手段（对齐 astral-bridge 的做法）：
  1. 出站前随机延迟 3~5 秒（可配）
  2. 长回复拆成两条发
  3. 表情包与文字分开发（先文字后图，或先图后文字）

★ 发送互斥：所有出口（回复 / 接话 / 心跳主动）共用一把锁串行。
之前主管线和接话循环是并发的 asyncio.create_task —— 用户连发几条时
多轮生成齐头并进，气泡交错着蹦出来，还有「（图呢——」这种半截草稿
漏出去。串行化之后，一条消息一定完整发完才轮到下一条。
"""
from __future__ import annotations

import asyncio
import random
from pathlib import Path
from typing import Callable, Dict, List, Optional

from .channel.napcat import NapCatChannel
from .config import BehaviorConfig


class Sender:
    def __init__(self, channel: NapCatChannel, behavior: BehaviorConfig):
        self.channel = channel
        self.behavior = behavior
        # 发送互斥按「会话」拆开：多个角色同时说话时，不能互相排队等
        # 对方把 5~20 秒的出站延迟睡完（那会让部分角色看起来不回话）。
        self._send_locks: dict[tuple, asyncio.Lock] = {}

    def _lock_for(self, user_id: str, group_id: str,
                  sender_id: str) -> asyncio.Lock:
        key = (str(group_id or ""), str(user_id or ""), str(sender_id or ""))
        lock = self._send_locks.get(key)
        if lock is None:
            lock = asyncio.Lock()
            self._send_locks[key] = lock
        return lock

    @staticmethod
    def _scale(v: float) -> float:
        """角色的「热情」换算出的节奏倍率，限制在合理区间。"""
        try:
            return max(0.10, min(6.0, float(v)))
        except (TypeError, ValueError):
            return 1.0

    async def _delay(self, scale: float = 1.0) -> None:
        lo, hi = (self.behavior.outbound_delay_ms + [3000, 5000])[:2]
        s = self._scale(scale)
        await asyncio.sleep(random.randint(int(lo), int(hi)) / 1000.0 * s)

    async def _gap(self, kind: str, scale: float = 1.0) -> None:
        """条与条之间的间隔。kind: bubble | chunk | sticker

        sticker 强制至少 3 秒：表情包 1 秒连甩两张一眼假。
        """
        if kind == "sticker":
            pair = self.behavior.sticker_delay_ms
        elif kind == "bubble":
            pair = self.behavior.bubble_delay_ms
        else:
            pair = self.behavior.chunk_delay_ms
        lo, hi = (list(pair or [0, 0]) + [0, 0])[:2]
        s = self._scale(scale)
        sec = random.uniform(int(lo), int(hi)) / 1000.0 * s
        if kind == "sticker":
            sec = max(sec, 3.0)
        await asyncio.sleep(sec)

    def _bubble_gap(self, text: str, scale: float = 1.0) -> float:
        """气泡间的间隔随长度分档：短碎片几乎零间隔，长句要「打一会儿字」。"""
        pair = (self.behavior.short_bubble_delay_ms
                if len(text) < 6 else self.behavior.long_bubble_delay_ms)
        lo, hi = (list(pair or [500, 1500]) + [500, 1500])[:2]
        return random.uniform(int(lo), int(hi)) / 1000.0 * self._scale(scale)

    # 句末标点：这些地方断句
    _SENT_END = "。！？!?…"
    # 波浪号也常用来断句（「呜嘿~」/「随便随便~」），但只在很短的前缀后才断，
    # 否则会出现「大叔我啊~觉得~这事儿~」这种碎成渣的切法
    _TILDE = "~～"
    _TILDE_MAX_PREFIX = 14

    def split(self, text: str) -> List[str]:
        """按真人聊天的节奏拆成多条短消息。

        不是按长度硬切 —— 真人是一次发一两句，停一两秒，再发下一句。
        所以策略是：**按句子拆**，最多 max_chunks 条，太短的整条不拆。
        """
        if not self.behavior.split_long_reply:
            return [text]
        t = (text or "").strip()
        if not t:
            return []
        max_chunks = max(1, int(self.behavior.max_chunks))
        # 太短就别折腾了（6 个字以下拆开会显得神经质）
        if max_chunks == 1 or len(t) < 6:
            return [t]

        chunks: List[str] = []
        buf = ""
        for ch in t:
            buf += ch
            if ch in self._SENT_END:
                chunks.append(buf.strip())
                buf = ""
            elif ch in self._TILDE and 0 < len(buf.strip()) <= self._TILDE_MAX_PREFIX:
                chunks.append(buf.strip())
                buf = ""
        if buf.strip():
            chunks.append(buf.strip())
        chunks = [c for c in chunks if c]

        # 只有一句时，如果较长且带逗号，按逗号再切一次
        if len(chunks) <= 1:
            if len(t) > max(40, int(self.behavior.split_threshold)) and "，" in t:
                parts = t.split("，")
                chunks = [p.strip() + "，" for p in parts[:-1]]
                chunks.append(parts[-1].strip())
            else:
                return [t]

        # 太碎的后半段合并：字数少于 3 的并到前一条
        merged: List[str] = []
        for c in chunks:
            if merged and len(c) < 3:
                merged[-1] = merged[-1] + c
            else:
                merged.append(c)
        chunks = merged

        # ★ 开头的短感叹词要**并进下一句**，不要单独占一条。
        # 例如「呜嘿~」孤零零发出去、正文另发一条 —— 看着就像模板。
        # 真人是「呜嘿，这个我熟」一气说完。所以这里把开头的短块并到后面。
        if len(chunks) >= 2 and len(chunks[0]) <= 6:
            chunks = [chunks[0] + chunks[1]] + chunks[2:]

        # 超过上限就把多余的合并进最后一条
        if len(chunks) > max_chunks:
            chunks = chunks[: max_chunks - 1] + ["".join(chunks[max_chunks - 1:])]
        return chunks if chunks else [t]

    async def reply(
        self,
        text: str,
        *,
        user_id: str = "",
        group_id: str = "",
        sticker_file: Optional[str] = None,
        sticker_files: Optional[List[str]] = None,
        sticker_first: bool = False,
        abort_check: Optional[Callable[[], bool]] = None,
        delay_sec: Optional[float] = None,
        delay_scale: float = 1.0,
        sender_id: str = "",
        sender_name: str = "",
        card: Optional[Dict[str, Any]] = None,
    ) -> int:
        """发送整段文字（本地按句拆条）。返回实际发出的**文字条数**。

        abort_check：每条发出前调一次，返回 True 就立刻停发剩余内容
        （用于「发送中途对方又说话了 → 旧回复作废」的代际中止）。
        delay_sec：**第一条**发出前要等多久（追时用）；不传就走随机出站延迟。
        delay_scale：角色热情换算的节奏倍率（低热情更慢、高热情更快）。
        sender_id/sender_name：自托管通道里「以哪个角色身份发」。
        """
        target = {"user_id": user_id, "group_id": group_id}
        if sender_id or sender_name:
            target["sender_id"] = sender_id
            target["sender_name"] = sender_name

        # 两种写法都收：单张用 sticker_file，多张用 sticker_files
        files: List[str] = list(sticker_files or [])
        if sticker_file and sticker_file not in files:
            files.insert(0, sticker_file)

        sent = 0
        async with self._lock_for(user_id, group_id, sender_id):
            if files and sticker_first:
                for i, f in enumerate(files):
                    if abort_check and abort_check():
                        break
                    if i > 0:
                        await self._gap("sticker", delay_scale)
                    await self._send_sticker(f, **target)

            if text:
                for i, chunk in enumerate(self.split(text)):
                    if abort_check and abort_check():
                        break
                    if i > 0:
                        await self._gap("bubble", delay_scale)
                    if i == 0 and delay_sec is not None:
                        if delay_sec > 0:
                            await asyncio.sleep(delay_sec * self._scale(delay_scale))
                    elif i == 0:
                        await self._delay(delay_scale)
                    await self.channel.send_text(chunk, **target)
                    sent += 1

            if files and not sticker_first:
                for f in files:
                    if abort_check and abort_check():
                        break
                    await self._gap("sticker", delay_scale)
                    await self._send_sticker(f, **target)

            if card:
                # 卡片另起一条（真人的「甩分享」也是单独一条），排在最后
                if not (abort_check and abort_check()):
                    await self._gap("bubble", delay_scale)
                    await self._send_card(card, **target)
        return sent

    async def reply_bubbles(
        self,
        bubbles: List[str],
        *,
        user_id: str = "",
        group_id: str = "",
        sticker_files: Optional[List[str]] = None,
        sticker_first: bool = False,
        abort_check: Optional[Callable[[], bool]] = None,
        delay_sec: Optional[float] = None,
        delay_scale: float = 1.0,
        sender_id: str = "",
        sender_name: str = "",
        reply_to_mid: str = "",
        card: Optional[Dict[str, Any]] = None,
        mid_base: str = "",
    ) -> int:
        """直接按模型给定的气泡列表逐条发送（不做本地拆句）。

        间隔随气泡长度分档：短碎片（<6 字）像顺嘴补一句，几乎零间隔；
        完整长句像在打字，要等一会儿。返回发出的条数。

        abort_check：每条气泡发出前调一次，返回 True 就停发剩余
        —— 用户连发几批消息时，旧批次的回复排队等到锁之后，
        上下文已经旧了，整批发出去就是「对着空气自说自话」。
        delay_sec：**第一条**发出前要等多久。主管线用它做「追时」——
        真人 14s 的响应延迟是**总时间**（等待+读+打字），
        模型推理已经花掉的时间要从里面扣，不能在处理完之后再额外等。
        delay_scale：角色热情换算的节奏倍率。
        """
        target = {"user_id": user_id, "group_id": group_id}
        if sender_id or sender_name:
            target["sender_id"] = sender_id
            target["sender_name"] = sender_name
        if reply_to_mid:
            # 引用回复：让通道把被引用的那条一并带进事件（真 QQ 则拼 reply 段）
            target["reply_to_mid"] = reply_to_mid
        sent = 0
        async with self._lock_for(user_id, group_id, sender_id):
            if sticker_files and sticker_first:
                for i, f in enumerate(sticker_files):
                    if abort_check and abort_check():
                        break
                    if i > 0:
                        await self._gap("sticker", delay_scale)
                    await self._send_sticker(f, **target)
            for i, b in enumerate(bubbles):
                if not b:
                    continue
                if abort_check and abort_check():
                    break
                if i == 0:
                    if delay_sec is not None:
                        if delay_sec > 0:
                            await asyncio.sleep(delay_sec * self._scale(delay_scale))
                    else:
                        await self._delay(delay_scale)
                else:
                    await asyncio.sleep(self._bubble_gap(b, delay_scale))
                # ★ 群里带上**库内 mid**（g<id>）：第一条就是这条消息的 mid，
                #   第 2、3 条气泡是 g<id>-2 / g<id>-3。这样客户端收到的实时
                #   message_id 和刷新后历史里的完全一致 —— 引用回复才能按 mid
                #   查到那条消息（以前实时是随机序号，引用整个失效）。
                kw = dict(target)
                if mid_base:
                    kw["message_id"] = (str(mid_base) if i == 0
                                        else f"{mid_base}-{i + 1}")
                await self.channel.send_text(b, **kw)
                sent += 1
            if sticker_files and not sticker_first:
                for f in sticker_files:
                    if abort_check and abort_check():
                        break
                    await self._gap("sticker", delay_scale)
                    await self._send_sticker(f, **target)
            if card:
                # 卡片单独一条（真人的「甩分享」也是另起一条），排在后面
                if not (abort_check and abort_check()):
                    await self._gap("bubble", delay_scale)
                    await self._send_card(card, **target)
        return sent

    async def _send_card(self, card: Dict[str, Any], *, user_id: str = "",
                         group_id: str = "", sender_id: str = "",
                         sender_name: str = "") -> None:
        """发一条结构化卡片（OneBot 的 `json` 段，前端渲染成可点卡片）。"""
        try:
            await self.channel.send_segments(
                [card], user_id=user_id, group_id=group_id,
                sender_id=sender_id, sender_name=sender_name)
        except Exception as e:  # noqa: BLE001
            print(f"[act] 发卡片失败：{e!r}")

    async def _send_sticker(self, file: str, *, user_id: str = "", group_id: str = "",
                            sender_id: str = "", sender_name: str = "") -> None:
        path = Path(file)
        if not path.exists():
            print(f"[act] 表情包文件不存在：{file}")
            return
        uri = self.channel.file_uri(path)
        try:
            await self.channel.send_sticker(
                uri, user_id=user_id, group_id=group_id,
                sender_id=sender_id, sender_name=sender_name)
        except Exception as e:  # noqa: BLE001
            print(f"[act] 发表情包失败：{e!r}，降级为文字")
            await self.channel.send_text(
                "[表情包]", user_id=user_id, group_id=group_id,
                sender_id=sender_id, sender_name=sender_name)

    async def send_voice(self, silk_path: str, *, user_id: str = "", group_id: str = "") -> None:
        """发送语音。注意：必须小于 60 秒、SILK/AMR/MP3 格式。"""
        await self._delay()
        await self.channel.send_segments(
            [self.channel.seg_record(self.channel.file_uri(silk_path))],
            user_id=user_id,
            group_id=group_id,
        )
