"""NapCat / OneBot 11 通道。

接入方式：**反向 WebSocket** —— NapCat 主动连到本服务。
    ws://127.0.0.1:6701/onebot/v11/ws

发送走 NapCat 的 HTTP API：
    POST {http_base}/send_msg     body: {message_type, user_id|group_id, message}
    （也支持 face/mface/image/record 等消息段，见下）

消息段格式（OneBot 11）：
    {"type": "text",   "data": {"text": "..."}}
    {"type": "image",  "data": {"file": "...", "summary": "...", "sub_type": 0}}
        → **sub_type=1 才是表情包**，0 是普通图片。发自定义表情包一定要用 1。
    {"type": "record", "data": {"file": "..."}}   语音，格式 SILK/AMR/MP3
    {"type": "face",   "data": {"id": "1-221"}}   QQ 系统表情
    {"type": "at",     "data": {"qq": "..."}}

体积限制：图片 10MB、语音 60 秒、视频 100MB。
"""
from __future__ import annotations

import asyncio
import json
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, List, Optional

import aiohttp
from aiohttp import web

from ..config import QQConfig

Handler = Callable[["IncomingMessage"], Awaitable[None]]

CQ_RE = re.compile(r"\[CQ:([a-zA-Z_]+)((?:,[^\]]*)?)\]")


@dataclass
class IncomingMessage:
    kind: str                       # "private" | "group"
    user_id: str
    group_id: str = ""
    # 自托管通道里，「会话对象」可能是星野以外的角色；
    # NapCat 链路没有这个概念，保持空串即走原来的单角色逻辑。
    peer_id: str = ""
    message_id: str = ""
    nickname: str = ""
    text: str = ""
    # 每张图对应一个「候选来源列表」，按可靠性从高到低排。
    # 为什么要多个候选：QQ 的图片 CDN 链接带时效签名，经常取不到；
    # 而 NapCat 其实已经把图下载到本地了，本地路径往往才是能用的那个。
    images: List[List[str]] = field(default_factory=list)
    # 每张图对应的 NapCat file id —— 所有其它来源都被截断时，
    # 可以用它去调 NapCat 的 get_image 拿完整文件
    raw_image_ids: List[str] = field(default_factory=list)
    # NapCat 声明的每张图字节数 —— 和实际收到的比一比就知道有没有被截断
    raw_image_sizes: List[str] = field(default_factory=list)
    # 合并转发（QQ「聊天记录」）的 id —— 段里只有 id，正文要另调接口取
    forward_ids: List[str] = field(default_factory=list)
    mentions_self: bool = False
    raw: Dict[str, Any] = field(default_factory=dict)

    @property
    def is_private(self) -> bool:
        return self.kind == "private"

    @property
    def image_count(self) -> int:
        return len(self.images)


def _mime_of(name: str) -> str:
    ext = Path(str(name)).suffix.lower()
    return {
        ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
        ".gif": "image/gif", ".webp": "image/webp", ".bmp": "image/bmp",
    }.get(ext, "image/jpeg")


def describe_segments(raw_message: Any) -> str:
    """给日志用的段结构摘要 —— 不打印 base64 正文，只报字段名和长度。

    排查「图片/表情包收不到」时靠这个：能直接看出 NapCat 到底给了哪些字段。
    """
    if not isinstance(raw_message, list):
        return f"(非数组型：{type(raw_message).__name__})"
    parts: List[str] = []
    for seg in raw_message:
        if not isinstance(seg, dict):
            continue
        t = str(seg.get("type"))
        d = seg.get("data") or {}
        if t in ("image", "mface", "face", "marketface", "record", "video", "file"):
            keys = []
            for k, v in d.items():
                s = str(v)
                if k == "base64":
                    keys.append(f"base64={len(s)}B")
                elif len(s) > 60:
                    keys.append(f"{k}={s[:57]}...")
                else:
                    keys.append(f"{k}={s!r}")
            parts.append(f"{t}{{{', '.join(keys)}}}")
        else:
            parts.append(t)
    return " + ".join(parts) if parts else "(空消息)"


def image_candidates(d: Dict[str, Any]) -> List[str]:
    """给一个图片段，排出「按可靠性从高到低」的候选来源。

    顺序依据（查 NapCat 源码 + 官方文档后确认）：

      1. **本地路径**（file / path，以及 url 字段里可能装的本地路径）
         NapCat 的 `readFile(file, "base64")` 是读**完整文件**的，
         而 `file` 存的就是它下载好的本地路径 —— 同机直接读，最可靠。

      2. **远程 URL** —— QQ CDN 链接带时效签名，且普遍需要特定 Referer，次之。

      3. **base64 放最后** —— ⚠️ 这条最不可靠！
         实测它会给出**被截断的数据**（正好 32768 字节，PNG 缺 IEND）。
         之前我把它排第一、理由是「零网络必然可用」，**这个假设是错的**，
         而且正好是「图片打不开」的元凶之一：第一个候选就拿到残图。

    注意：本地路径里可能只是 NapCat 的**文件标识**（不是真实路径），
    那种情况由 `load_first_image` 里先走的 `get_image` 接口解决。
    """
    local: List[str] = []
    remote: List[str] = []
    b64_list: List[str] = []

    for key in ("file", "path", "url"):
        v = str(d.get(key) or "").strip()
        if not v:
            continue
        if v.startswith("data:"):
            local.append(v)
        elif v.startswith("base64://"):
            mime = _mime_of(d.get("file_name") or "")
            b64_list.append(f"data:{mime};base64,{v[9:]}")
        elif v.startswith(("http://", "https://")):
            remote.append(v)
        else:
            local.append(v)      # 没协议的：当本地路径

    b64 = d.get("base64")
    if b64:
        mime = _mime_of(d.get("file_name") or d.get("file") or "")
        b64_list.append(f"data:{mime};base64,{b64}")

    seen, out = set(), []
    for c in local + remote + b64_list:      # ← base64 垫底
        if c and c not in seen:
            seen.add(c)
            out.append(c)
    return out


def parse_message(raw_message: Any, self_id: str
                  ) -> tuple[str, List[List[str]], bool, List[str], List[str], List[str]]:
    """把 OneBot 的 message 字段解成 (纯文本, 图片候选列表, 是否@了我, file_id, 声明的字节数)。"""
    text_parts: List[str] = []
    images: List[List[str]] = []
    img_ids: List[str] = []
    img_sizes: List[str] = []          # NapCat 声明的 file_size，用来判断有没有被截断
    forward_ids: List[str] = []        # 合并转发（聊天记录）的 id
    mentioned = False

    if isinstance(raw_message, str):
        # CQ 码字符串形式
        pos = 0
        for m in CQ_RE.finditer(raw_message):
            text_parts.append(raw_message[pos:m.start()])
            pos = m.end()
            seg_type = m.group(1)
            params = dict(
                kv.split("=", 1) for kv in m.group(2).lstrip(",").split(",") if "=" in kv
            )
            if seg_type == "image":
                c = image_candidates(params)
                if c:
                    images.append(c)
                    img_ids.append(str(params.get("file_id") or params.get("file") or ""))
                    img_sizes.append(str(params.get("file_size") or ""))
            elif seg_type == "at":
                if params.get("qq") == self_id:
                    mentioned = True
                text_parts.append(f"@{params.get('qq')} ")
            elif seg_type == "face":
                text_parts.append("[表情]")
        text_parts.append(raw_message[pos:])
    elif isinstance(raw_message, list):
        for seg in raw_message:
            if not isinstance(seg, dict):
                continue
            t = seg.get("type")
            d = seg.get("data") or {}
            if t == "text":
                text_parts.append(str(d.get("text", "")))
            elif t == "image":
                c = image_candidates(d)
                if c:
                    images.append(c)
                    img_ids.append(str(d.get("file_id") or d.get("file") or ""))
                    img_sizes.append(str(d.get("file_size") or ""))
            elif t == "at":
                if str(d.get("qq")) == self_id:
                    mentioned = True
                text_parts.append(f"@{d.get('qq')} ")
            elif t == "face":
                # QQ 系统小黄脸
                text_parts.append(f"[QQ表情:{d.get('id', '')}]")
            elif t in ("mface", "marketface"):
                # QQ 商城表情（从表情面板发的大表情）。
                # OneBot 11 里这类段**没有图片文件**，只有 emoji_id / package / key / summary。
                # 所以先看有没有可用的图源，没有就把 summary 当文字线索交给模型。
                c = image_candidates(d)
                if c:
                    images.append(c)
                    img_ids.append(str(d.get("file_id") or d.get("file") or ""))
                    img_sizes.append(str(d.get("file_size") or ""))
                else:
                    s = str(d.get("summary") or "").strip()
                    text_parts.append(f"[对方发了一个QQ表情包{('：' + s) if s else ''}]")
            elif t == "record":
                text_parts.append("[语音]")
            elif t in ("forward", "json"):
                # QQ「聊天记录」（合并转发）。段里**只有 id，没有正文**，
                # 正文要另调 NapCat 的 get_forward_msg 去取（见 forward_ids）。
                # 原来是直接忽略的 —— 于是你发一整段聊天记录过来，
                # 模型眼里什么都没有。
                #
                # 两种形态都要认：
                #   1) {"type":"forward","data":{"id":"xxx"}}
                #   2) {"type":"json","data":{"data":"<嵌套JSON字符串>"}}
                #      嵌套里的 meta.detail.resid 才是真 id
                fid = ""
                if t == "forward":
                    fid = str(d.get("id") or d.get("message_id")
                              or d.get("file") or "").strip()
                else:
                    inner = d.get("data") or ""
                    if isinstance(inner, dict):
                        inner = inner.get("data") or ""
                    try:
                        j = json.loads(str(inner))
                        det = ((j.get("meta") or {}).get("detail") or {})
                        fid = str(det.get("resid") or det.get("uniseq")
                                  or j.get("resid") or "").strip()
                    except (json.JSONDecodeError, AttributeError, TypeError):
                        fid = ""
                if fid:
                    forward_ids.append(fid)
                    text_parts.append("【对方转发了一段聊天记录，内容见下】")
                else:
                    text_parts.append("[聊天记录]")

    return ("".join(text_parts).strip(), images, mentioned,
            img_ids, img_sizes, forward_ids)


def format_event_brief(data: Dict[str, Any]) -> str:
    """把原始消息结构整理成可以直接复制粘贴的几行。

    这样用户不用去找 failed_media.jsonl —— 控制台里就能直接复制发出来。
    base64 只报长度，不然一行几万字符没法看。
    """
    lines: List[str] = []
    msg = data.get("message")
    if isinstance(msg, list):
        for seg in msg:
            if not isinstance(seg, dict):
                continue
            t = str(seg.get("type"))
            d = seg.get("data") or {}
            if t in ("image", "mface", "marketface", "face", "record", "video"):
                parts = []
                for k, v in d.items():
                    s = str(v)
                    parts.append(f"{k}=<{len(s)}字符>" if k == "base64"
                                 else f"{k}={s[:80]!r}")
                lines.append(f"    {t}: {{{', '.join(parts)}}}")
            else:
                lines.append(f"    {t}: {str(d)[:100]}")
    else:
        lines.append(f"    (非数组型) {str(msg)[:200]}")
    return "\n".join(lines) if lines else "    (空消息)"


def dump_raw_event(data: Dict[str, Any], reason: str, out_dir: Optional[Path],
                   keep_base64_snippet: bool = False) -> Optional[Path]:
    """把原始事件落盘，专门用来排查「图片/表情收不到」。

    base64 默认只记长度（单个文件能到几 MB）。
    `keep_base64_snippet=True` 时额外记**头尾各 64 字符** ——
    排查「数据被截断」这类问题时，需要看到 base64 的**结尾长什么样**
    （完整数据结尾是 '=' 填充，截断的结尾是随机字符）。

    同时给每个图片段附上解析出的候选清单与各自长度，
    这样一眼就能看出「到底是哪个来源被截断了」。
    """
    if out_dir is None:
        return None
    try:
        out_dir = Path(out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        path = out_dir / "failed_media.jsonl"

        def slim(obj: Any) -> Any:
            if isinstance(obj, dict):
                out: Dict[str, Any] = {}
                for k, v in obj.items():
                    if k == "base64":
                        s = str(v)
                        n = len(s)
                        # base64 长度 → 原始字节数（按 4:3 估）
                        out[k] = (f"<{n} b64字符 ≈ {n * 3 // 4} 字节>"
                                  + (f" 头[{s[:64]}] 尾[{s[-64:]}]" if keep_base64_snippet else ""))
                    else:
                        out[k] = slim(v)
                return out
            if isinstance(obj, list):
                # 图片/表情段额外附上候选清单
                res: List[Any] = []
                for x in obj:
                    if isinstance(x, dict) and x.get("type") in (
                            "image", "mface", "marketface"):
                        y = slim(x)
                        try:
                            c = image_candidates(x.get("data") or {})
                            y["_candidates"] = [
                                (f"base64({len(z) * 3 // 4}B)" if z.startswith("data:")
                                 else z[:70]) for z in c]
                        except Exception:  # noqa: BLE001
                            pass
                        res.append(y)
                    else:
                        res.append(slim(x))
                return res
            return obj

        rec = {
            "ts": time.strftime("%Y-%m-%d %H:%M:%S"),
            "reason": reason,
            "message_type": data.get("message_type"),
            "user_id": data.get("user_id"),
            "group_id": data.get("group_id"),
            "message": slim(data.get("message")),
        }
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        return path
    except Exception as e:  # noqa: BLE001
        print(f"[channel] 诊断落盘失败：{e!r}")
        return None


class PortInUse(RuntimeError):
    """反向 WS 端口被占用。

    两种情况要分清楚，提示完全不同：
      - 是**上一个 Vol 还在跑** → 别重复启动，去关掉原来那个窗口
      - 是**别的程序**占了 → 换端口，或找出占用者
    """

    def __init__(self, port: int, is_our_own: bool):
        self.port = port
        self.is_our_own = is_our_own
        if is_our_own:
            msg = (
                f"端口 {port} 上已经有一个 Vol 在跑了 —— 这次不重复启动。\n"
                "  处理办法：双击 vol\\一键停止.bat 把旧的清掉，然后再启动；\n"
                "  或者干脆就用原来那个，不用再开（不影响 NapCat 连接）。"
            )
        else:
            msg = (
                f"端口 {port} 被别的程序占用了。\n"
                f"  查看占用者：netstat -ano | findstr :{port}\n"
                f"  然后在任务管理器里按 PID 找出来；\n"
                f"  或者改 companion/config.yaml 里的 qq.ws.port（和 NapCat 侧要同步改）。"
            )
        super().__init__(msg)


class NapCatChannel:
    def __init__(self, cfg: QQConfig, on_message: Handler,
                 dump_dir: Optional[Path] = None):
        self.cfg = cfg
        self.on_message = on_message
        self.dump_dir = dump_dir
        self._session: Optional[aiohttp.ClientSession] = None
        self._runner: Optional[web.AppRunner] = None
        self._clients: set[web.WebSocketResponse] = set()
        self.connected = asyncio.Event()
        # ★ 看门狗用：这个服务端**曾经**被 NapCat 连上过。
        # 「连上过 → 断开且不再回连」才自动修；从没连上过（还没点
        # 一键启动）就绝不自作主张拉起 QQ。
        self.ever_connected = False
        self._last_media_log = 0.0
        self._last_nosource_log = 0.0

    # ---------------- 服务端（收事件） ----------------
    async def _probe_own_instance(self) -> bool:
        """探测该端口上是不是「我们自己的另一个实例」。

        本服务在 /healthz 上返回 {"ok": true}，拿这个当指纹。
        判定故意放宽（只认 ok 字段，不强求新加的 service 字段）——
        否则用户跑着旧版实例时，会被误报成「端口被别的程序占用」，
        提示就指错方向了。
        """
        url = f"http://127.0.0.1:{self.cfg.ws_port}/healthz"
        try:
            async with aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=3), trust_env=False
            ) as s:
                async with s.get(url) as r:
                    if r.status != 200:
                        return False
                    data = json.loads(await r.text())
                    return bool(data.get("ok"))
        except Exception:  # noqa: BLE001
            return False

    async def start(self) -> None:
        app = web.Application()
        app.router.add_get(self.cfg.ws_path, self._ws_handler)
        app.router.add_get(
            "/healthz",
            lambda _r: web.json_response({"ok": True, "service": "vol-companion"}),
        )
        self._runner = web.AppRunner(app)
        await self._runner.setup()
        site = web.TCPSite(self._runner, self.cfg.ws_host, self.cfg.ws_port)
        try:
            await site.start()
        except OSError as e:
            await self._runner.cleanup()
            self._runner = None
            # 10048 = Windows 端口占用；98 = Linux EADDRINUSE
            if getattr(e, "errno", None) in (10048, 98) or "10048" in str(e):
                raise PortInUse(self.cfg.ws_port, await self._probe_own_instance()) from e
            raise
        print(f"[channel] 反向 WS 已监听 {self.cfg.ws_host}:{self.cfg.ws_port}{self.cfg.ws_path}")
        print(f"[channel] 请在 NapCat 侧配置反向 WebSocket 指向该地址。")

    async def stop(self) -> None:
        for ws in list(self._clients):
            await ws.close()
        if self._runner:
            await self._runner.cleanup()
        if self._session and not self._session.closed:
            await self._session.close()

    def _auth_ok(self, request: web.Request) -> bool:
        if not self.cfg.ws_token:
            return True
        token = request.query.get("access_token") or ""
        header = request.headers.get("Authorization", "")
        if header.startswith("Bearer "):
            token = token or header[7:]
        return token == self.cfg.ws_token

    async def _ws_handler(self, request: web.Request) -> web.WebSocketResponse:
        ws = web.WebSocketResponse(heartbeat=30, max_msg_size=16 * 1024 * 1024)
        await ws.prepare(request)
        if not self._auth_ok(request):
            # 注意：对带 Upgrade 头的请求直接返回普通 Response 会让 aiohttp 内部报错，
            # 所以这里先完成握手再用 1008（policy violation）关掉，语义也更清楚。
            print("[channel] 拒绝连接：access_token 不匹配")
            await ws.close(code=1008, message=b"bad access_token")
            return ws
        self._clients.add(ws)
        self.connected.set()
        self.ever_connected = True
        print("[channel] NapCat 已连接")
        try:
            async for msg in ws:
                if msg.type != aiohttp.WSMsgType.TEXT:
                    continue
                try:
                    data = json.loads(msg.data)
                except json.JSONDecodeError:
                    continue
                await self._dispatch(data)
        finally:
            self._clients.discard(ws)
            print("[channel] NapCat 连接断开")
        # ★ 必须返回 ws。少了这一句 aiohttp 会报
        #   "Missing return statement on request handler"
        #   → 'NoneType' object has no attribute 'prepare'
        #   → 连接被莫名掐断（表现为用着用着突然掉线）。
        return ws

    async def _dispatch(self, data: Dict[str, Any]) -> None:
        if data.get("post_type") != "message":
            return
        mtype = data.get("message_type")
        if mtype not in ("private", "group"):
            return

        self_id = str(data.get("self_id", self.cfg.self_id))
        raw_msg = data.get("message")
        (text, images, mentioned, img_ids, img_sizes,
         forward_ids) = parse_message(raw_msg, self_id)

        # 带媒体段的消息把结构摘出来打日志 —— 排查「图片/表情收不到」全靠这个。
        # 但要收敛：群可能很吵，而且被忽略的群消息打出来没意义。
        # 规则：私聊一律打；群聊只在「确实解析出了图源」时打。并且 30 秒最多一条。
        # 注意 has_img_seg / now 必须在分支外初始化 —— 否则字符串型消息
        # （CQ 码形式，不走 list 分支）会 UnboundLocalError。
        has_img_seg = False
        now = time.time()
        if isinstance(raw_msg, list):
            media_types = {"image", "mface", "marketface", "face", "record", "video"}
            has_media = any(
                isinstance(s, dict) and s.get("type") in media_types for s in raw_msg
            )
            if has_media:
                is_private = mtype == "private"
                if (is_private or images) and now - self._last_media_log > 30:
                    self._last_media_log = now
                    print(f"[channel] 媒体段结构：{describe_segments(raw_msg)}")
                if is_private and not images:
                    has_img_seg = any(
                        isinstance(s, dict)
                        and s.get("type") in ("image", "mface", "marketface")
                        for s in raw_msg
                    )
        if has_img_seg:
            p = dump_raw_event(data, "有图段但解析不出任何来源", self.dump_dir)
            if now - self._last_nosource_log > 30:
                self._last_nosource_log = now
                print("=" * 58)
                print("[channel] ⚠️ 收到图片/表情，但解析不出任何图源")
                print("[channel] 该段的**全部字段**如下（把这几行复制发出去就能定位）：")
                for seg in (data.get("message") or []):
                    if isinstance(seg, dict) and seg.get("type") in (
                            "image", "mface", "marketface"):
                        for k, v in (seg.get("data") or {}).items():
                            s = str(v)
                            # base64 正文太长，只报长度；其余字段全量打出来
                            print(f"[channel]   {k} = "
                                  + (f"<{len(s)} 字符>" if k == "base64" else repr(s)))
                if p:
                    print(f"[channel] （同时也记到了 {p}）")
                print("=" * 58)

        sender = data.get("sender") or {}

        incoming = IncomingMessage(
            kind=mtype,
            user_id=str(data.get("user_id", "")),
            group_id=str(data.get("group_id", "")) if mtype == "group" else "",
            message_id=str(data.get("message_id", "")),
            nickname=str(sender.get("card") or sender.get("nickname") or ""),
            text=text,
            images=images,
            raw_image_ids=img_ids,
            raw_image_sizes=img_sizes,
            forward_ids=forward_ids,
            mentions_self=mentioned,
            raw=data,
        )
        try:
            await self.on_message(incoming)
        except Exception as e:  # noqa: BLE001
            print(f"[channel] 处理消息出错：{e!r}")

    # ---------------- 客户端（发消息） ----------------
    async def _http(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=30)
            )
        return self._session

    def _headers(self) -> Dict[str, str]:
        h = {"Content-Type": "application/json"}
        if self.cfg.http_token:
            h["Authorization"] = f"Bearer {self.cfg.http_token}"
        return h

    async def call(self, action: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        url = self.cfg.http_base.rstrip("/") + "/" + action.lstrip("/")
        sess = await self._http()
        async with sess.post(url, json=payload, headers=self._headers()) as resp:
            body = await resp.text()
            if resp.status != 200:
                raise RuntimeError(f"NapCat API {action} HTTP {resp.status}: {body[:300]}")
            try:
                return json.loads(body)
            except json.JSONDecodeError:
                return {"raw": body}

    async def fetch_forward(self, fid: str, max_msgs: int = 60) -> str:
        """取「合并转发（聊天记录）」的正文，拍平成可读文本。

        为什么必须做：forward 段里**只有 id**。不调这个接口，
        对方转发一整段聊天记录过来，模型眼里是空的 ——
        只会回一句「记录要发就发」，非常出戏（实测就是这样）。
        """
        if not fid:
            return ""
        try:
            res = await self.call("get_forward_msg", {"message_id": fid})
        except Exception:
            try:
                res = await self.call("get_forward_msg", {"id": fid})
            except Exception as e:  # noqa: BLE001
                print(f"[channel] 取聊天记录失败：{e!r}")
                return ""
        data = res.get("data") if isinstance(res, dict) else None
        msgs = []
        if isinstance(data, dict):
            msgs = data.get("messages") or data.get("message") or []
        elif isinstance(data, list):
            msgs = data
        if not isinstance(msgs, list):
            return ""

        lines: List[str] = []
        for m in msgs[:max_msgs]:
            if not isinstance(m, dict):
                continue
            sender = (m.get("sender") or {}).get("nickname") \
                or (m.get("sender") or {}).get("card") or "?"
            t, imgs, _m, _i, _s, _f = parse_message(m.get("message"), "")
            bits = []
            if t:
                bits.append(t)
            if imgs:
                bits.append("[图片]")
            if not bits:
                continue
            lines.append(f"{sender}: {' '.join(bits)}")
        if len(msgs) > max_msgs:
            lines.append(f"…（还有 {len(msgs) - max_msgs} 条，略）")
        return "\n".join(lines)

    # ---- 消息段构造 ----
    @staticmethod
    def seg_text(text: str) -> Dict[str, Any]:
        return {"type": "text", "data": {"text": text}}

    @staticmethod
    def seg_image(file: str, *, is_sticker: bool = False, summary: str = "") -> Dict[str, Any]:
        data: Dict[str, Any] = {"file": file, "sub_type": 1 if is_sticker else 0}
        if summary:
            data["summary"] = summary
        return {"type": "image", "data": data}

    @staticmethod
    def seg_record(file: str) -> Dict[str, Any]:
        return {"type": "record", "data": {"file": file}}

    @staticmethod
    def seg_face(face_id: int) -> Dict[str, Any]:
        return {"type": "face", "data": {"id": str(face_id)}}

    @staticmethod
    def file_uri(path: str | Path) -> str:
        p = Path(path).resolve()
        # NapCat 支持 file:// 前缀；Windows 路径需转成 file:///C:/...
        posix = p.as_posix()
        return posix if posix.startswith("file://") else "file:///" + posix.lstrip("/")

    # ---- 高层发送 ----
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
        # message_id 是 vol 内部的库内 mid（自建通道用来统一 id 空间）；
        # 真 QQ 链路的消息 id 由腾讯分配，这里只能忽略它。
        # 引用回复：真 QQ 那边认 reply 段，这里顺手拼一个（群里引用我的消息时用）
        if reply_to_mid and group_id and str(reply_to_mid).strip():
            segments = [{"type": "reply", "data": {"id": str(reply_to_mid)}}] + list(segments)
        if group_id:
            payload = {"message_type": "group", "group_id": group_id, "message": segments}
        elif user_id:
            payload = {"message_type": "private", "user_id": user_id, "message": segments}
        else:
            raise ValueError("必须提供 user_id 或 group_id")
        return await self.call("send_msg", payload)

    async def send_text(self, text: str, *, user_id: str = "", group_id: str = "",
                        sender_id: str = "", sender_name: str = "",
                        reply_to_mid: str = "",
                        message_id: str = "") -> Dict[str, Any]:
        return await self.send_segments([self.seg_text(text)], user_id=user_id,
                                        group_id=group_id, sender_id=sender_id,
                                        sender_name=sender_name,
                                        reply_to_mid=reply_to_mid,
                                        message_id=message_id)

    async def send_sticker(
        self, file: str, *, user_id: str = "", group_id: str = "", summary: str = "[表情包]",
        sender_id: str = "", sender_name: str = "", reply_to_mid: str = "",
        message_id: str = "",
    ) -> Dict[str, Any]:
        return await self.send_segments(
            [self.seg_image(file, is_sticker=True, summary=summary)],
            user_id=user_id,
            group_id=group_id,
            sender_id=sender_id,
            sender_name=sender_name,
            reply_to_mid=reply_to_mid,
            message_id=message_id,
        )
