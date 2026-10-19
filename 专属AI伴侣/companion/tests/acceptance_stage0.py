"""阶段 0 验收 —— 不需要真 QQ 的端到端集成测试。

做法：把「NapCat」这一侧用代码模拟出来：

    [假 NapCat HTTP 服务]  ←── Companion 通过它发消息（记录所有 send_msg 调用）
              ▲
              │ HTTP /send_msg
    [Companion: 真 NapCatChannel，真 WS 服务端，监听 16701]
              ▲
              │ OneBot 11 反向 WebSocket（真 socket）
    [假 NapCat WS 客户端]  ── 推 message 事件，模拟 QQ 来了消息

于是「真实 QQ 登录」之外的所有环节都被真跑了一遍：
反向 WS 握手 / access_token 鉴权 / 事件解析 / 权限过滤 /
完整对话管线 / 消息段构造 / 出站 HTTP 调用。

用法（在 companion 目录下）：
    .venv\\Scripts\\python.exe tests\\acceptance_stage0.py
"""
from __future__ import annotations

import asyncio
import json
import sys
import tempfile
import traceback
from pathlib import Path
from typing import Any, Dict, List

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import aiohttp  # noqa: E402
from aiohttp import web  # noqa: E402

from app.channel.napcat import NapCatChannel  # noqa: E402
from app.config import (  # noqa: E402
    AutonomyConfig, BehaviorConfig, Config, LLMConfig, MemoryConfig,
    QQConfig, SearchConfig, StickerConfig,
)
from app.main import Companion  # noqa: E402
from tests.mock_llm import MockLLM  # noqa: E402

WS_PORT = 16701
HTTP_PORT = 13000
TOKEN = "secret-token-123"
BOT_QQ = "10000"
OWNER_QQ = "10001"

PASS, FAIL = [], []


def check(name: str, cond: bool, detail: str = "") -> None:
    if cond:
        PASS.append(name)
        print(f"  \u2713 {name}")
    else:
        FAIL.append(f"{name} :: {detail}")
        print(f"  \u2717 {name}  {detail}")


def segs_of(calls: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [seg for c in calls for seg in (c.get("message") or [])]


def texts_of(calls: List[Dict[str, Any]]) -> str:
    return "".join(
        str(s["data"].get("text", "")) for s in segs_of(calls)
        if s.get("type") == "text" and isinstance(s.get("data"), dict)
    )


def images_of(calls: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [s for s in segs_of(calls) if s.get("type") == "image"]


class FakeNapCat:
    """假的 NapCat：一边提供 send_msg HTTP 接口，一边当反向 WS 客户端。"""

    def __init__(self) -> None:
        self.sent: List[Dict[str, Any]] = []
        self._runner: web.AppRunner | None = None
        self._session: aiohttp.ClientSession | None = None
        self._conn: aiohttp.ClientWebSocketResponse | None = None

    # ---------- HTTP：接收出站消息 ----------
    async def start_http(self) -> None:
        app = web.Application()
        app.router.add_post("/send_msg", self._on_send)
        self._runner = web.AppRunner(app)
        await self._runner.setup()
        await web.TCPSite(self._runner, "127.0.0.1", HTTP_PORT).start()

    async def _on_send(self, request: web.Request) -> web.Response:
        auth = request.headers.get("Authorization", "")
        body = await request.json()
        body["_auth_ok"] = auth == "Bearer tok-abc"
        self.sent.append(body)
        return web.json_response({"status": "ok", "data": {"message_id": len(self.sent)}})

    async def stop_http(self) -> None:
        if self._runner:
            await self._runner.cleanup()

    # ---------- WS：作为 NapCat 反向连接到 Companion ----------
    async def connect(self, token: str = TOKEN, path: str = "/onebot/v11/ws"):
        self._session = aiohttp.ClientSession()
        url = f"ws://127.0.0.1:{WS_PORT}{path}?access_token={token}"
        self._conn = await self._session.ws_connect(url)
        return self._conn

    async def push(self, event: Dict[str, Any], min_wait: float | None = None) -> None:
        assert self._conn is not None
        # 带图片的事件可能要走一次网络下载（失败时上限数秒），给足等待
        has_image = any(
            seg.get("type") == "image" for seg in (event.get("message") or [])
            if isinstance(seg, dict)
        )
        await self._conn.send_str(json.dumps(event, ensure_ascii=False))
        await self.settle(min_wait=min_wait if min_wait is not None else (4.5 if has_image else 1.2))

    async def settle(self, timeout: float = 10.0, quiet: float = 0.35, min_wait: float = 1.2) -> None:
        """等到出站不再有新动静为止。

        比固定 sleep 可靠：出站既有多段（文字 → 表情包）又有随机延迟，
        固定等待会出现「上一条的表情包晚到、串进下一个用例」的假失败。
        min_wait 是必要的：管线在处理中（还没产生任何出站）时，
        单纯的"稳定"判断会立刻返回，导致断言过早。
        """
        await asyncio.sleep(min_wait)
        last = len(self.sent)
        stable = 0.0
        elapsed = 0.0
        step = 0.1
        while elapsed < timeout:
            await asyncio.sleep(step)
            elapsed += step
            if len(self.sent) == last:
                stable += step
                if stable >= quiet:
                    return
            else:
                stable = 0.0
                last = len(self.sent)

    def reset(self) -> None:
        self.sent.clear()

    async def close(self) -> None:
        if self._conn:
            await self._conn.close()
        if self._session:
            await self._session.close()

    # ---------- 便捷构造 ----------
    def msg_event(
        self,
        text: str = "",
        *,
        user_id: str = OWNER_QQ,
        group_id: str = "",
        images: tuple = (),
        mention_bot: bool = False,
    ) -> Dict[str, Any]:
        segs: List[Dict[str, Any]] = []
        if mention_bot:
            segs.append({"type": "at", "data": {"qq": BOT_QQ}})
        if text:
            segs.append({"type": "text", "data": {"text": text}})
        for u in images:
            segs.append({"type": "image", "data": {"url": u}})
        return {
            "post_type": "message",
            "message_type": "group" if group_id else "private",
            "self_id": BOT_QQ,
            "user_id": user_id,
            "group_id": group_id,
            "message_id": f"m{len(self.sent)}",
            "raw_message": text,
            "message": segs,
            "sender": {"nickname": "测试用户", "card": ""},
        }


def build_cfg(tmp: Path) -> Config:
    cfg = Config(root=ROOT)
    cfg.llm = LLMConfig(api_key="mock", model="deepseek-flash")
    cfg.qq = QQConfig(
        self_id=BOT_QQ, owner_id=OWNER_QQ,
        group_mode="mention",          # 默认是 off；这里显式打开以便验证 @ 触发
        ws_host="127.0.0.1", ws_port=WS_PORT, ws_path="/onebot/v11/ws", ws_token=TOKEN,
        http_base=f"http://127.0.0.1:{HTTP_PORT}", http_token="tok-abc",
    )
    # 测试里把所有人造延迟清零，出站"节奏"本身不是本测试要验的东西
    cfg.behavior = BehaviorConfig(
        outbound_delay_ms=[0, 0], chunk_delay_ms=[0, 0], sticker_delay_ms=[0, 0],
        split_long_reply=False,
        # 关掉「多条消息合并」：否则每次 push 要等 3 秒 debounce，
        # 断言会在回复到达前就跑完（假失败）。
        merge_window_sec=0.0,
    )
    cfg.memory = MemoryConfig(
        db_path=str(tmp / "acc.db"),
        sticker_dir=str(tmp / "s"),
        sticker_index=str(tmp / "s" / "index.json"),
        # 诊断落盘必须改到临时目录！否则跑一次验收就会往用户的
        # 真实 data\failed_media.jsonl 里灌一堆看着像真事的测试噪音。
        debug_dir=str(tmp / "debug"),
    )
    cfg.search = SearchConfig(provider="", api_key="")
    cfg.autonomy = AutonomyConfig(quiet_hours=["03:00", "05:00"])
    # 表情包：测试要确定性，把频率策略调成「必发」，否则概率/冷却会让断言随机失败
    # 表情包判定用固定返回，避免随机张数
    cfg.sticker = StickerConfig(
        enabled=True, base_probability=1.0, min_gap_min=0, daily_max=999,
        energy_threshold=0, steal_enabled=False,
    )
    return cfg


def _png_bytes() -> bytes:
    """不依赖 Pillow，手写一张 16x16 纯色 PNG。"""
    import struct
    import zlib

    w = h = 16
    raw = b"".join(b"\x00" + bytes([40, 120, 200] * w) for _ in range(h))

    def chunk(tag: bytes, data: bytes) -> bytes:
        return (struct.pack(">I", len(data)) + tag + data
                + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))

    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw))
            + chunk(b"IEND", b""))


def make_stickers(tmp: Path) -> None:
    d = tmp / "s"
    d.mkdir(parents=True, exist_ok=True)
    f1 = d / "happy.png"; f1.write_bytes(b"\x89PNG\r\n\x1a\n" + b"1" * 32)
    f2 = d / "sad.png"; f2.write_bytes(b"\x89PNG\r\n\x1a\n" + b"2" * 32)
    (d / "index.json").write_text(
        json.dumps([
            {"file": str(f1), "desc": "猫在笑", "emotions": ["开心"], "tags": ["猫", "笑"]},
            {"file": str(f2), "desc": "猫在哭", "emotions": ["难过"], "tags": ["猫", "哭"]},
        ], ensure_ascii=False),
        encoding="utf-8",
    )


async def main() -> int:
    tmp = Path(tempfile.mkdtemp())
    make_stickers(tmp)
    cfg = build_cfg(tmp)
    # ★ reply 用列表轮换：每次表达的内容都不同 —— 否则接话草稿和上一条
    # 一样会被第⑦层重复拦截拦掉（那正是新逻辑该干的活，测试得配合）。
    # 每项都含「豆子」，前面的内容断言无论轮到哪条都成立。
    mock = MockLLM(reply=["听起来不错啊，哪家的豆子", "豆子是深烘的吗",
                          "这豆子哪买的呀", "豆子多少钱一杯",
                          "下次带我去喝这豆子"])
    napcat = FakeNapCat()

    comp = Companion(cfg, channel=NapCatChannel(cfg.qq, None), llm=mock)
    comp.channel.on_message = comp.handle   # 构造时传的 None，这里补真正的 handler

    await napcat.start_http()
    await comp.channel.start()

    try:
        print("\n=== 1. access_token 鉴权 ===")
        try:
            bad = await napcat.connect(token="wrong-token")
            msg = await asyncio.wait_for(bad.receive(), timeout=5)
            check("错误 token 被拒（收到关闭帧）",
                  msg.type in (aiohttp.WSMsgType.CLOSE, aiohttp.WSMsgType.CLOSING,
                               aiohttp.WSMsgType.CLOSED),
                  f"type={msg.type}")
            await bad.close()
        except Exception as e:  # noqa: BLE001
            check("错误 token 被拒", False, repr(e))
        await napcat.close()

        print("\n=== 2. 私聊文本（全链路） ===")
        await napcat.connect()
        check("反向 WS 握手成功", napcat._conn is not None and not napcat._conn.closed)

        await napcat.push(napcat.msg_event("今天喝到一杯超好喝的冰美式"))
        check("有出站消息", len(napcat.sent) >= 1, str(napcat.sent))
        if napcat.sent:
            s = napcat.sent[0]
            check("message_type = private", s.get("message_type") == "private", str(s))
            check("user_id 正确", str(s.get("user_id")) == OWNER_QQ, str(s))
            check("出站带了 Authorization", s.get("_auth_ok") is True)
            check("回复内容正确", "豆子" in texts_of(napcat.sent), texts_of(napcat.sent))
        check("情绪/分析/表达三个通道都被走到",
              all(k in mock.calls for k in ("emotion", "analyze", "express")),
              str(mock.calls))
        check("状态机已更新", comp.state.emotion.valence != 0.0,
              str(comp.state.emotion.valence))
        check("记忆已落库", len(comp.store.all_memories()) >= 1)

        print("\n=== 3. 发图（走视觉通道） ===")
        napcat.reset(); mock.calls.clear()
        img = tmp / "incoming.png"
        img.write_bytes(_png_bytes())
        await napcat.push(napcat.msg_event(images=(str(img),)))
        check("视觉通道被调用（本地图）", "vision" in mock.calls, str(mock.calls))
        check("发图后仍能作答", "豆子" in texts_of(napcat.sent), texts_of(napcat.sent))
        # 这条断言守的是一个真实出过的 bug：图能被识别，但描述没传给表达通道，
        # 结果它对着一张已经看清的图说「图没进来」。
        check("图片描述确实传进了表达通道",
              "熊猫头" in mock.last_express_prompt,
              mock.last_express_prompt[-160:])

        print("\n=== 3b. 图片取不到时的行为 ===")
        napcat.reset(); mock.calls.clear()
        # 指向必然拒绝连接的端口：所有候选来源都失败
        await napcat.push(napcat.msg_event(images=("http://127.0.0.1:1/none.png",)))
        check("取不到图时不会把坏链接丢给模型（不调视觉通道）",
              "vision" not in mock.calls, str(mock.calls))
        check("取不到图仍能正常作答，不崩", "豆子" in texts_of(napcat.sent),
              texts_of(napcat.sent))

        print("\n=== 3c. url 字段里装本地路径（NapCat 真实行为） ===")
        napcat.reset(); mock.calls.clear()
        local = tmp / "url_as_path.png"
        local.write_bytes(_png_bytes())
        await napcat.push(napcat.msg_event(images=(str(local),)))
        check("url 里是本地路径也能取到图（走视觉通道）",
              "vision" in mock.calls, str(mock.calls))
        check("本地路径取图后有作答", "豆子" in texts_of(napcat.sent), texts_of(napcat.sent))

        print("\n=== 4. 表情包出站（sub_type=1） ===")
        napcat.reset(); mock.calls.clear()
        # 上一条（3b）刚发过图，judge_sticker 会因「上一条已经发过图」直接抑制。
        # 这是刻意的防刷屏设计，所以这里先把状态复位，单独验证出站路径。
        comp.store.kv_set("last_was_sticker", False)
        mock.overrides["sticker"] = {"send": True, "emotion": "开心", "reason": "日常接梗"}
        # min_wait 拉长到 4.5s：表情包出站有 ≥3 秒的强制间隔（防 1 秒连甩两张
        # 一眼假），默认 1.2s 的稳定判定会在表情包到达前就提前返回（假失败）。
        await napcat.push(napcat.msg_event("今天好开心啊哈哈"), min_wait=4.5)
        imgs = images_of(napcat.sent)
        check("发出了图片段", len(imgs) >= 1, str(segs_of(napcat.sent)))
        if imgs:
            check("表情包 sub_type = 1", imgs[0]["data"].get("sub_type") == 1, str(imgs[0]))
            check("表情包来自本地库", "happy.png" in imgs[0]["data"].get("file", ""),
                  str(imgs[0]))

        print("\n=== 5. 权限过滤 ===")
        napcat.reset()
        await napcat.push(napcat.msg_event("你好", user_id="99999"))
        check("非主人私聊被忽略", len(napcat.sent) == 0, str(napcat.sent))

        await napcat.push(napcat.msg_event("在吗", group_id="88888"))
        check("群聊未 @ 被忽略", len(napcat.sent) == 0, str(napcat.sent))

        print("\n=== 6. 群聊 @ 触发 ===")
        napcat.reset()
        # min_wait=4.5：回复带的表情包有 ≥3s 强制间隔，默认 1.2s 的稳定判定
        # 会在表情包到达前返回，泄漏进 6b 的「绝不开口」静默断言（假失败）。
        await napcat.push(napcat.msg_event("在吗", group_id="88888", mention_bot=True),
                          min_wait=4.5)
        check("群聊 @ 后回复", len(napcat.sent) >= 1, str(napcat.sent))
        if napcat.sent:
            check("message_type = group", napcat.sent[0].get("message_type") == "group",
                  str(napcat.sent[0]))
            check("group_id 正确", str(napcat.sent[0].get("group_id")) == "88888")

        print("\n=== 6b. 群聊闸门（默认必须是关的） ===")
        comp.cfg.qq.group_mode = "off"
        napcat.reset()
        await napcat.push(napcat.msg_event("在吗", group_id="88888", mention_bot=True))
        check("off 模式下即使被 @ 也绝不开口", len(napcat.sent) == 0, str(napcat.sent))

        comp.cfg.qq.group_mode = "allowlist"
        comp.cfg.qq.group_allowlist = ["99999"]
        napcat.reset()
        await napcat.push(napcat.msg_event("在吗", group_id="88888", mention_bot=True))
        check("allowlist 未命中 → 不开口", len(napcat.sent) == 0, str(napcat.sent))

        comp.cfg.qq.group_allowlist = ["88888"]
        napcat.reset()
        # min_wait=4.5：命中后的回复带表情包（≥3s 强制间隔），等它落地，
        # 否则会泄漏进下一条「没 @ 也不开口」的静默断言（假失败）。
        await napcat.push(napcat.msg_event("在吗", group_id="88888", mention_bot=True),
                          min_wait=4.5)
        check("allowlist 命中 + 被 @ → 开口", len(napcat.sent) >= 1, str(napcat.sent))

        napcat.reset()
        await napcat.push(napcat.msg_event("在吗", group_id="88888", mention_bot=False))
        check("白名单群里没 @ 也不开口", len(napcat.sent) == 0, str(napcat.sent))

        comp.cfg.qq.group_mode = "mention"
        comp.cfg.qq.group_allowlist = []

        print("\n=== 7. 调试指令 ===")
        napcat.reset()
        await napcat.push(napcat.msg_event("/state"))
        check("/state 返回内部状态", "效价" in texts_of(napcat.sent), texts_of(napcat.sent)[:80])

        napcat.reset()
        await napcat.push(napcat.msg_event("/mood 低落"))
        check("/mood 生效", comp.state.emotion.valence < 0, str(comp.state.emotion.valence))

        print("\n=== 8. 出站失败不影响服务存活 ===")
        good_base = comp.channel.cfg.http_base
        comp.channel.cfg.http_base = "http://127.0.0.1:1"   # 无人监听的端口
        try:
            await napcat.push(napcat.msg_event("测试出站失败"))
            ok = True
        except Exception as e:  # noqa: BLE001
            ok = False
            print(f"    （异常：{e!r}）")
        check("出站失败被捕获，进程不崩", ok)
        comp.channel.cfg.http_base = good_base
        check("失败后连接仍在", napcat._conn is not None and not napcat._conn.closed)

        print("\n=== 9. 断线重连 ===")
        await napcat.close()
        await asyncio.sleep(0.3)
        await napcat.connect()
        napcat.reset()
        # min_wait=4.5：同理等回复自带的表情包落地，避免泄漏进测试 10 的窗口
        await napcat.push(napcat.msg_event("断线重连后还在吗"), min_wait=4.5)
        check("重连后仍能正常收发", len(napcat.sent) >= 1, str(napcat.sent))

        print("\n=== 10. 对话连贯性（真跑一遍） ===")
        # 把补话间隔压到最短，否则要等 25 秒以上
        # ★ 接话参数是按「热情/好感」派生的副本：运行时读的是 conversation.cfg，
        #   只改 cfg.conversation 不会生效（两处一起改）
        for _c in (comp.cfg.conversation, comp.conversation.cfg):
            _c.followup_delay_sec = [1, 2]
            _c.active_window_min = 2
        conv_task = asyncio.create_task(comp.conversation.run())
        try:
            napcat.reset(); mock.calls.clear()
            # ★ 换一组全新词表：前面 9 个用例已把「豆子」五连存进对话记录，
            # 若沿用旧词表，轮换绕回时接话草稿会和存档的 assistant 轮完全相同，
            # 被第⑦层重复拦截拦掉（正是新逻辑该干的活，测试得配合换词）。
            # 每次 express 消耗 3 个 mock call（2 次气泡尝试 + 1 次纯文本回退），
            # 步长 3 与表长 5 互素 → 管线回复 / 接话草稿互不相同。
            mock.reply = [
                "冰美式我也爱，苦得干脆",
                "那家店叫什么名字呀",
                "改天我也去搞一杯试试",
                "你今天怎么突然想喝冰的",
                "好喝就得趁冰块没化赶紧喝完",
            ]
            await napcat.push(napcat.msg_event("今天喝到一杯超好喝的冰美式"))
            after_reply = len(napcat.sent)
            await asyncio.sleep(13)
            total = len(napcat.sent)
            check("用户只说一句后，它会自己接着往下说",
                  total > after_reply, f"回复后 {after_reply} 条 → {total} 条")
            check("接话走的是 followup 判断通道",
                  "followup_judge" in mock.calls, str(mock.calls))
            check("接话内容有落库",
                  any(e["kind"] == "conversation"
                      for e in comp.store.recent_events(30, include_flagged=True)),
                  str([e["kind"] for e in comp.store.recent_events(10)]))
        finally:
            comp.conversation.stop()
            conv_task.cancel()
            try:
                await conv_task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass

        print("\n=== 11. 被忽略的消息绝不留痕 ===")
        # 把群聊关死，然后狂发群消息 + 非主人私聊（都带图），
        # 断言：不回复、不改情绪、不写记忆、不进对话记录。
        comp.cfg.qq.group_mode = "off"
        for _c in (comp.cfg.conversation, comp.conversation.cfg):
            _c.active_window_min = 0   # 关掉自动接话，避免干扰计数
        napcat.reset()
        state_before = dict(comp.state.emotion.__dict__)
        mem_before = len(comp.store.all_memories(5000))
        turns_before = len(comp.store.recent_turns(200))
        ignored_before = comp._ignored_count

        img = tmp / "group_img.png"
        img.write_bytes(_png_bytes())
        for i in range(5):
            await napcat.push(napcat.msg_event("群里随便说的话", group_id="954402631",
                                               user_id="1530104409", mention_bot=False))
        for i in range(3):
            await napcat.push(napcat.msg_event("", group_id="954402631",
                                               user_id="1530104409", mention_bot=True))
        for i in range(2):
            await napcat.push(napcat.msg_event("", images=(str(img),),
                                               group_id="954402631",
                                               user_id="1530104409", mention_bot=True))
        for i in range(2):
            await napcat.push(napcat.msg_event("陌生人私聊", user_id="99999"))

        check("群消息 + 非主人私聊一律不回复", len(napcat.sent) == 0, str(napcat.sent)[:200])
        check("情绪状态没被改动",
              dict(comp.state.emotion.__dict__) == state_before,
              f"{state_before.get('valence')} → {comp.state.emotion.__dict__.get('valence')}")
        check("没写进长期记忆", len(comp.store.all_memories(5000)) == mem_before,
              f"{mem_before} → {len(comp.store.all_memories(5000))}")
        check("没写进对话记录", len(comp.store.recent_turns(200)) == turns_before,
              f"{turns_before} → {len(comp.store.recent_turns(200))}")
        check("计数确实涨了（说明是被主动丢弃，不是没收着）",
              comp._ignored_count > ignored_before,
              f"{ignored_before} → {comp._ignored_count}")
        check("群里的图没被下载（视觉通道没被调用）",
              "vision" not in mock.calls, str(mock.calls))
        comp.cfg.qq.group_mode = "mention"

        print("\n=== 12. 加白名单后才会处理该群 ===")
        comp.cfg.qq.group_mode = "allowlist"
        comp.cfg.qq.group_allowlist = ["954402631"]
        napcat.reset(); mock.calls.clear()
        await napcat.push(napcat.msg_event("", images=(str(img),),
                                           group_id="954402631",
                                           user_id="1530104409", mention_bot=True))
        check("白名单群被 @ 后会处理（含读图）", "vision" in mock.calls, str(mock.calls))
        comp.cfg.qq.group_mode = "off"
        comp.cfg.qq.group_allowlist = []

    finally:
        await napcat.close()
        await napcat.stop_http()
        await comp.channel.stop()
        comp.store.close()

    print("\n" + "=" * 56)
    print(f"通过 {len(PASS)} 项，失败 {len(FAIL)} 项")
    if FAIL:
        print("\n失败明细：")
        for f in FAIL:
            print("  - " + f)
        return 1
    print("阶段 0 验收通过（真实 QQ 登录除外）。")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(asyncio.run(main()))
    except Exception:
        traceback.print_exc()
        sys.exit(2)
