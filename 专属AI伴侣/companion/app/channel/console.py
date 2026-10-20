"""本地控制台通道。

作用：**在还没装 NapCat 之前，就能把整个大脑跑起来。**
它实现了和 NapCatChannel 一样的接口（send_text / send_sticker / send_segments /
file_uri），所以 Sender、Heartbeat、Digest 全都不用改。

同时也用于离线测试：`handle()` 接收的 IncomingMessage 结构完全一致。

用法：
    python -m app.main --console
    > 你好            # 普通消息
    > :img D:\\a.png   # 模拟发一张图
    > :quit           # 退出
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, List, Optional

from .napcat import IncomingMessage

Handler = Callable[[IncomingMessage], Awaitable[None]]


class ConsoleChannel:
    kind = "console"

    def __init__(self, self_id: str = "console", owner_id: str = "owner"):
        self.self_id = self_id
        self.owner_id = owner_id
        self._out_lines: List[str] = []   # 测试时可回读
        # 群聊要断言「是哪个角色开的口」，所以再记一份发送者（与 _out_lines 等长）
        self._out_senders: List[str] = []
        # 引用回复要断言「被引用的 mid 真的传到通道了」，同样与 _out_lines 等长
        self._reply_mids: List[str] = []
        # 出站消息的 mid（群里应该是库内 mid：g<id> / g<id>-2…），供测试断言
        self._out_mids: List[str] = []
        self.echo = True

    # ---------- 生命周期 ----------
    async def start(self) -> None:
        if self.echo:
            print("=" * 56)
            print(" 控制台模式：消息直接在这里输入，走完整管线")
            print(" 命令：:img <路径> 模拟发图 | :quit 退出")
            print("=" * 56)

    async def stop(self) -> None:
        return None

    @property
    def connected(self) -> asyncio.Event:
        ev = asyncio.Event()
        ev.set()
        return ev

    # ---------- 发送（与 NapCatChannel 同签名） ----------
    @staticmethod
    def file_uri(path: str | Path) -> str:
        return Path(path).resolve().as_posix()

    async def send_segments(
        self,
        segments: List[Dict[str, Any]],
        *,
        user_id: str = "",
        group_id: str = "",
        sender_id: str = "",
        sender_name: str = "",
        reply_to_mid: str = "",
        message_id: str = "",
    ) -> Dict[str, Any]:
        parts: List[str] = []
        for seg in segments:
            t = seg.get("type")
            d = seg.get("data") or {}
            if t == "text":
                parts.append(str(d.get("text", "")))
            elif t == "image":
                parts.append(f"［图片 sub_type={d.get('sub_type', 0)}：{d.get('file')}］")
            elif t == "record":
                parts.append(f"［语音：{d.get('file')}］")
            else:
                parts.append(f"［{t}］")
        line = "".join(parts)
        self._out_lines.append(line)
        self._out_senders.append(sender_name or "")
        self._reply_mids.append(str(reply_to_mid or ""))
        self._out_mids.append(str(message_id or ""))
        if self.echo:
            who = f"{sender_name}: " if sender_name else ""
            print(f"\n🤖 {who}{line}\n")
        return {"status": "ok", "message_id": len(self._out_lines)}

    async def send_text(self, text: str, *, user_id: str = "", group_id: str = "",
                        sender_id: str = "", sender_name: str = "",
                        reply_to_mid: str = "",
                        message_id: str = "") -> Dict[str, Any]:
        return await self.send_segments([{"type": "text", "data": {"text": text}}],
                                        user_id=user_id, group_id=group_id,
                                        sender_id=sender_id, sender_name=sender_name,
                                        reply_to_mid=reply_to_mid,
                                        message_id=message_id)

    async def send_sticker(
        self,
        file: str,
        *,
        user_id: str = "",
        group_id: str = "",
        summary: str = "[表情包]",
        sender_id: str = "",
        sender_name: str = "",
        reply_to_mid: str = "",
        message_id: str = "",
    ) -> Dict[str, Any]:
        return await self.send_segments(
            [{"type": "image", "data": {"file": file, "sub_type": 1, "summary": summary}}],
            user_id=user_id, group_id=group_id,
            sender_id=sender_id, sender_name=sender_name,
            reply_to_mid=reply_to_mid, message_id=message_id,
        )

    # ---------- 输入循环 ----------
    async def run(self, on_message: Handler) -> None:
        await self.start()
        loop = asyncio.get_running_loop()
        while True:
            try:
                raw = await loop.run_in_executor(None, _read_line)
            except (EOFError, KeyboardInterrupt):
                break
            if raw is None:
                break
            line = raw.strip()
            if not line:
                continue
            if line in (":quit", ":q", "exit", "quit"):
                break
            if line.startswith(":img"):
                path = line[4:].strip().strip('"').strip("'")
                p = Path(path)
                if not p.exists():
                    print(f"[console] 找不到文件：{path}")
                    continue
                await on_message(self.make_incoming("", images=[str(p)]))
                continue
            await on_message(self.make_incoming(line))

    # ---------- 构造入站消息（测试也用它） ----------
    def make_incoming(
        self,
        text: str,
        images: Optional[List[str]] = None,
        *,
        user_id: Optional[str] = None,
        group_id: str = "",
        mentions_self: bool = False,
    ) -> IncomingMessage:
        return IncomingMessage(
            kind="group" if group_id else "private",
            user_id=user_id or self.owner_id,
            group_id=group_id,
            message_id=f"c{len(self._out_lines)}",
            nickname="我",
            text=text,
            # 每张图包成一个「候选来源列表」，与 NapCat 侧结构一致
            images=[[str(p)] for p in (images or [])],
            mentions_self=mentions_self,
        )


def _read_line() -> Optional[str]:
    try:
        return input("你 > ")
    except EOFError:
        return None
