"""OneBot 11 服务端通道：Stapxs QQ Lite 等客户端直连 vol。

## 为什么有这个

NapCat 是 QQ 协议的第三方实现，账号有被腾讯风控的风险（学校用的
号不能冒险）。这个通道把 vol 自己变成 OneBot 11 **服务端**：
Stapxs QQ Lite（Web/Electron/Android）把 vol 当成「NapCat」连接，
聊天全程不碰腾讯 —— 零封号风险，数据全在自己手里。

## 身份模型（和 NapCat 链路的关键差异）

NapCat 链路里 vol 冒充小号（self_id）和用户（owner）聊。
这里角色反转：

  - 登录者 = **用户自己**（get_login_info 返回 owner_id）
    —— 客户端里「我」就是用户，就像真的在用 QQ
  - 好友列表 = 只有「星野」一个人（self_id 扮演）
  - 用户在客户端打字 → send_msg(user_id=星野) → vol 主管线
    （IncomingMessage.user_id = owner_id，通过「是不是主人」校验）
  - 星野回复 → 推送 OneBot message 事件（sender=星野）→ 客户端
    左侧气泡；主动消息/表情包同一条路
  - 用户消息受理 → 推送 message_sent 事件（sender=用户）→
    发送端替换预发送占位（fake_msg），其他设备同步显示

## 协议行为（对照 Stapxs 源码逐条确认过）

  - 正向 WS：客户端连上来之后，API 调用（{action, params, echo}）
    和事件推送**走同一条 WS**，响应原样带回 echo
  - 鉴权：URL query ?access_token=...（或 Authorization 头）
  - 心跳：必须定期推 meta_event heartbeat，否则客户端
    「心跳包超时」强制断线（超时 = interval * 系数 或 interval+宽限）
  - 握手链：get_version_info（app_name 含 "NapCat" 让它加载
    NapCat pathMap）→ get_login_info → get_friends_with_category
    + get_group_list
  - 图片：客户端发图用 base64://（file 字段）；vol 发表情包用
    HTTP URL（本服务自带静态文件路由 /assets/stickers/...）
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import inspect
import itertools
import json
import random
import re
import shutil
import time
import traceback
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, Set
from urllib.parse import quote

from aiohttp import web, WSMsgType

from ..config import QQConfig
from .napcat import (
    IncomingMessage, Handler, describe_segments, parse_message,
)

# 心跳事件里上报的 interval（毫秒）。实际推送周期取 heartbeat_sec（默认
# 25s）—— 故意比上报值短，保证客户端的超时看门狗永远不会先到。
_REPORTED_HEARTBEAT_MS = 30000

# 静态文件（表情包下载）的 URL 前缀
_ASSET_PREFIX = "assets/stickers"


class OneBotServerChannel:
    """vol 即 OneBot 11 服务端。"""

    def __init__(
        self,
        cfg: QQConfig,
        on_message: Handler,
        *,
        store=None,
        sticker_dir: Optional[Path] = None,
        dump_dir: Optional[Path] = None,
        webapp_dir: Optional[Path] = None,
        legacy_webapp_dir: Optional[Path] = None,
        sticker_lib=None,
        characters=None,
        store_for=None,
        settings_get=None,
        settings_set=None,
        character_creator=None,
        traits_get=None,
        traits_set=None,
        presence_get=None,
        presence_set=None,
        group_api=None,
    ):
        self.cfg = cfg                 # QQConfig（self_id=星野号 owner_id=用户号）
        self.scfg = cfg.server         # QQServerConfig
        self.on_message = on_message
        self.store = store             # 主角色（星野）的存储
        # 角色库 + 按角色取存储的回调（星野之外的角色各自一个 SQLite）
        self.characters = characters
        self.store_for = store_for
        # 网页全局设置 / 添加角色（回调由 Companion 提供）
        self.settings_get = settings_get
        self.settings_set = settings_set
        self.character_creator = character_creator
        self.traits_get = traits_get
        self.traits_set = traits_set
        self.presence_get = presence_get
        self.presence_set = presence_set
        # 群聊接口（由 Companion 提供）：list/detail/create/kick/announce/
        # mute_all/rename/requests/... —— 见 Companion 里的「对外的群接口」
        self.group_api = group_api
        self.sticker_lib = sticker_lib  # 可选：让新上传/删除立刻对 vol 生效
        self.sticker_dir = Path(sticker_dir).resolve() if sticker_dir else None
        # 表情包缩略图缓存（列表用静态首帧，hover 才加载原图/动图）
        self.thumb_dir = (self.sticker_dir.parent / "sticker_thumbs"
                          if self.sticker_dir else None)
        # 自定义聊天头像（用户在网页「聊天设置」里裁剪上传的）
        self.avatar_dir = (self.sticker_dir.parent / "avatars"
                           if self.sticker_dir else None)
        # 每个角色（对话）允许使用的表情包分类
        self.sets_path = (self.sticker_dir.parent / "sticker_sets.json"
                          if self.sticker_dir else None)
        self._sticker_sets: Dict[str, List[str]] = {}
        # 用户自建的（可能是空的）分类
        self.categories_path = (self.sticker_dir.parent / "sticker_categories.json"
                                if self.sticker_dir else None)
        self._categories: List[str] = []
        self.dump_dir = dump_dir
        # 自建聊天页面的托管目录（data/webclient）。vol 一个端口全包：
        # 浏览器直接打开 http://<ip>:<port>/ 就是完整聊天界面，
        # 不依赖 GitHub Pages、不需要另起静态服务。
        self.webapp_dir = (Path(webapp_dir).resolve()
                           if webapp_dir and Path(webapp_dir).is_dir() else None)
        # 旧版 Stapxs 页面（data/webapp）：保留在 /stapxs/ 下备用，
        # 功能更全但版式由第三方决定。
        self.legacy_dir = (Path(legacy_webapp_dir).resolve()
                           if legacy_webapp_dir and Path(legacy_webapp_dir).is_dir()
                           else None)

        self._clients: Set[web.WebSocketResponse] = set()
        self._runner: Optional[web.AppRunner] = None
        self._hb_task: Optional[asyncio.Task] = None
        self._msg_ids = itertools.count(random.randint(1_000_000, 9_000_000))
        # ★ 离线消息队列：客户端一个都不在线时，星野的消息（心跳主动/
        # 接话/回复）不能就这么丢了 —— QQ 链路里腾讯服务器会暂存，
        # 这里用本地队列顶上，客户端一连上就重放。
        self._offline_queue: List[Dict[str, Any]] = []
        # 有其他端在线时产生的事件也留一份：新设备连上来补发最近一段，
        # 解决「手机在线时电脑错过消息」的多端同步问题。
        self._recent_events: List[Dict[str, Any]] = []
        # 实时消息 id → 会话/角色/文本，撤回时用来定位 transcript。
        self._live_msgs: Dict[str, Dict[str, Any]] = {}
        # 合并转发（「聊天记录」）的内容：id → node 列表。客户端点开卡片时
        # 用 get_forward_msg 取回（自托管链路里内容只能由 vol 保管）。
        self._forwards: Dict[str, List[Dict[str, Any]]] = {}
        self._api_table = self._build_api_table()
        # 兼容 main.py：channel.connected / ever_connected / _clients
        self.connected = asyncio.Event()
        self.ever_connected = False
        self._last_media_log = 0.0

    # ---------------- 生命周期 ----------------

    async def start(self) -> None:
        self._load_sticker_sets()
        self._load_categories()
        app = web.Application(client_max_size=32 * 1024 * 1024)
        # 正向 WS：Stapxs 连接地址可配 /onebot/v11/ws 或 /ws；
        # 根路径 GET 视情况：带 WebSocket Upgrade 头 → 也走 WS
        #（兼容 ws://ip:port 这种填法），否则 → 托管的聊天页面。
        app.router.add_get("/onebot/v11/ws", self._ws_handler)
        app.router.add_get("/ws", self._ws_handler)
        app.router.add_get("/", self._root)
        # HTTP API（SSE 模式 / 调试用）：POST /<action>
        app.router.add_post("/{action}", self._http_api)
        # 表情包静态下载
        app.router.add_get(f"/{_ASSET_PREFIX}/{{tail:.+}}", self._sticker_file)
        app.router.add_get("/healthz", self._healthz)
        # 表情包面板：分类清单 / 缩略图 / 上传 / 删除 / 每个角色的可用分类
        app.router.add_get("/api/stickers", self._api_stickers)
        app.router.add_get("/api/sticker-thumb", self._sticker_thumb)
        app.router.add_get("/api/sticker-sets", self._api_sticker_sets)
        app.router.add_post("/api/sticker-sets", self._api_sticker_sets_save)
        app.router.add_post("/api/stickers/upload", self._api_sticker_upload)
        app.router.add_post("/api/stickers/delete", self._api_sticker_delete)
        app.router.add_post("/api/sticker-category/create", self._api_category_create)
        app.router.add_post("/api/sticker-category/delete", self._api_category_delete)
        # 自定义聊天头像：列表 / 读取 / 上传（客户端已裁成方形）/ 恢复默认
        app.router.add_get("/api/avatars", self._api_avatars)
        app.router.add_get("/api/avatar", self._api_avatar_file)
        app.router.add_post("/api/avatar", self._api_avatar_save)
        app.router.add_post("/api/avatar/delete", self._api_avatar_delete)
        # 网页全局设置（API Key / Base URL / 模型）+ 新增角色
        app.router.add_get("/api/settings", self._api_settings_get)
        app.router.add_post("/api/settings", self._api_settings_post)
        app.router.add_post("/api/characters/create", self._api_character_create)
        # 每个角色的「热情 / 好感」
        app.router.add_get("/api/character-traits", self._api_traits_get)
        app.router.add_post("/api/character-traits", self._api_traits_post)
        app.router.add_get("/api/presence", self._api_presence_get)
        app.router.add_post("/api/presence", self._api_presence_post)
        # 群聊：建群 / 群详情（含成员与公告）/ 审批 / 管理
        app.router.add_get("/api/identity", self._api_identity)
        app.router.add_get("/api/groups", self._api_groups_list)
        app.router.add_get("/api/groups/detail", self._api_groups_detail)
        app.router.add_get("/api/groups/history", self._api_groups_history)
        app.router.add_post("/api/groups/create", self._api_groups_create)
        app.router.add_post("/api/groups/manage", self._api_groups_manage)
        app.router.add_get("/api/groups/files", self._api_groups_files)
        app.router.add_post("/api/groups/upload", self._api_groups_upload)
        app.router.add_post("/api/groups/files/delete", self._api_groups_file_del)
        app.router.add_get("/api/groups/file", self._api_groups_file_get)
        # 旧版 Stapxs 页面备用入口（必须先于根路径的静态兜底注册）
        if self.legacy_dir:
            app.router.add_get("/stapxs", self._legacy_root)
            app.router.add_get("/stapxs/", self._legacy_root)
            app.router.add_static("/stapxs/", self.legacy_dir,
                                  name="legacy-webapp", show_index=False)
        # 自建页面（css/js 等静态资源兜底；具体路由在上面已优先）
        if self.webapp_dir:
            app.router.add_static("/", self.webapp_dir,
                                  name="webapp", show_index=False)

        self._runner = web.AppRunner(app)
        await self._runner.setup()
        site = web.TCPSite(self._runner, self.scfg.listen, self.scfg.port)
        try:
            await site.start()
        except OSError as e:
            await self._runner.cleanup()
            self._runner = None
            raise RuntimeError(
                f"onebot-server 端口 {self.scfg.port} 启动失败：{e}"
                "（被占用的话先跑「一键停止.bat」，或改 qq.server.port）"
            ) from e
        self._hb_task = asyncio.create_task(self._heartbeat_loop())
        base = self.scfg.base_url
        auth = "已启用 access_token" if self.scfg.token else "未启用（仅限本机测试！）"
        print(f"[onebot-server] 已监听 {self.scfg.listen}:{self.scfg.port}"
              f"（鉴权：{auth}）")
        print(f"[onebot-server] 客户端连接地址：ws://<本机IP>:{self.scfg.port}"
              f"{'/?access_token=***' if self.scfg.token else ''}")
        if self.webapp_dir:
            print(f"[onebot-server] ★ 聊天页面已托管：浏览器打开 {base}/ 即聊"
                  "（手机用 http://<电脑IP>:" + str(self.scfg.port) + "/）")
        print(f"[onebot-server] 表情包下载地址前缀：{base}/{_ASSET_PREFIX}/")
        print("[onebot-server] 聊天页面：自建页面在 /，Stapxs 备用在 /stapxs/")

    async def stop(self) -> None:
        if self._hb_task:
            self._hb_task.cancel()
            self._hb_task = None
        for ws in list(self._clients):
            try:
                await ws.close()
            except Exception:  # noqa: BLE001
                pass
        self._clients.clear()
        if self._runner:
            await self._runner.cleanup()
            self._runner = None

    # ---------------- 根路径：页面 or WS ----------------

    async def _root(self, request: web.Request) -> web.StreamResponse:
        """GET / 的双重身份：

        - WebSocket 握手（带 Upgrade 头）→ 当 WS 用（ws://ip:port 这种
          连接地址不写路径也能连）
        - 普通请求 → 自建聊天页面（webapp_dir 不存在时给一个简短的
          指引页）
        """
        if "websocket" in (request.headers.get("Upgrade") or "").lower():
            return await self._ws_handler(request)
        if self.webapp_dir and (self.webapp_dir / "index.html").is_file():
            return web.FileResponse(
                self.webapp_dir / "index.html",
                headers={"Cache-Control": "no-cache"})
        return web.Response(text=(
            "<h3>vol onebot-server</h3>"
            "<p>聊天页面未部署（companion/data/webclient 不存在）。</p>"
            "<p>WS 地址：ws://&lt;本机IP&gt;:" + str(self.scfg.port) + "/</p>"),
            content_type="text/html")

    async def _legacy_root(self, _request: web.Request) -> web.StreamResponse:
        """Stapxs 备用页面的入口（静态目录 show_index=False，需显式给 index）。"""
        if not self.legacy_dir:
            return web.Response(status=404)
        return web.FileResponse(
            self.legacy_dir / "index.html",
            headers={"Cache-Control": "no-cache"})

    # ---------------- 鉴权 ----------------
    def _auth_ok(self, request: web.Request) -> bool:
        if not self.scfg.token:
            return True
        token = request.query.get("access_token") or ""
        header = request.headers.get("Authorization", "")
        if header.startswith("Bearer "):
            token = token or header[7:]
        return token == self.scfg.token

    # ---------------- WebSocket（事件推送 + API 调用） ----------------

    async def _ws_handler(self, request: web.Request) -> web.WebSocketResponse:
        ws = web.WebSocketResponse(heartbeat=30, max_msg_size=32 * 1024 * 1024)
        await ws.prepare(request)
        if not self._auth_ok(request):
            print("[onebot-server] 拒绝连接：access_token 不匹配")
            await ws.close(code=1008, message=b"bad access_token")
            return ws
        self._clients.add(ws)
        self.connected.set()
        self.ever_connected = True
        print(f"[onebot-server] 客户端已连接（当前 {len(self._clients)} 个）")
        # 重放离线期间攒下的消息（没有任何端在线时）。
        queued: List[Dict[str, Any]] = []
        if self._offline_queue:
            queued, self._offline_queue = self._offline_queue, []
            print(f"[onebot-server] 重放 {len(queued)} 条离线消息")
        # 再补发「其他端在线时」最近产生的事件，让新设备追上刚才的对话。
        # 客户端会按 message_id / 内容去重，重复补发不会多出气泡。
        recent = [e for e in self._recent_events
                  if float(e.get("time") or 0) >= time.time() - 1800]
        if recent:
            print(f"[onebot-server] 补发最近 {len(recent)} 条同步事件")
        for ev in sorted(queued + recent,
                         key=lambda e: float(e.get("time") or 0)):
            try:
                payload = dict(ev)
                payload["_replay"] = True
                await ws.send_json(payload)
            except Exception:  # noqa: BLE001
                break
        try:
            async for msg in ws:
                if msg.type != WSMsgType.TEXT:
                    continue
                try:
                    data = json.loads(msg.data)
                except json.JSONDecodeError:
                    continue
                if not isinstance(data, dict):
                    continue
                action = str(data.get("action") or "")
                params = data.get("params") or {}
                result = await self._dispatch(action, params)
                if result is not None and data.get("echo") is not None:
                    result["echo"] = data.get("echo")
                    try:
                        await ws.send_json(result)
                    except ConnectionResetError:
                        break
        finally:
            self._clients.discard(ws)
            print(f"[onebot-server] 客户端断开（剩 {len(self._clients)} 个）")
        # ★ 必须返回 ws（与 napcat.py 同坑：aiohttp 要求）
        return ws

    async def _http_api(self, request: web.Request) -> web.Response:
        """POST /<action>：和 WS 同一套 dispatch（SSE 模式 / 调试用）。"""
        if not self._auth_ok(request):
            return web.json_response({"status": "failed", "retcode": 1403,
                                      "wording": "bad access_token"}, status=403)
        action = request.match_info["action"]
        try:
            params = await request.json()
        except Exception:  # noqa: BLE001
            params = {}
        if not isinstance(params, dict):
            params = {}
        result = await self._dispatch(action, params)
        # CORS：Stapxs Web 版（https 页面）用 SSE 模式时会跨域 fetch
        return web.json_response(result, headers={
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Headers": "*",
        })

    # ---------------- 事件广播 ----------------

    async def _broadcast(self, event: Dict[str, Any]) -> None:
        if not self._clients:
            return
        dead: List[web.WebSocketResponse] = []
        for ws in list(self._clients):
            try:
                # 客户端卡死/不读时，send_json 可能一直挂着；
                # 发送锁是全局的，一条挂住会让所有角色都发不出话。
                await asyncio.wait_for(ws.send_json(event), timeout=3.0)
            except Exception:  # noqa: BLE001
                dead.append(ws)
        for ws in dead:
            self._clients.discard(ws)
            try:
                await ws.close()
            except Exception:  # noqa: BLE001
                pass

    async def _heartbeat_loop(self) -> None:
        interval = max(5, int(self.scfg.heartbeat_sec))
        while True:
            await asyncio.sleep(interval)
            if not self._clients:
                continue
            await self._broadcast({
                "time": int(time.time()),
                "self_id": int(self.cfg.owner_id or 0),
                "post_type": "meta_event",
                "meta_event_type": "heartbeat",
                "status": "ok",
                "interval": _REPORTED_HEARTBEAT_MS,
            })

    # ---------------- API 分发 ----------------

    def _build_api_table(self) -> Dict[str, Any]:
        """action → 处理函数。在 __init__ 构造一次（绑定的方法引用），
        放在 _dispatch 里现构造的话，写错方法名会在每次调用时炸。"""
        return {
            "get_version_info": self.api_get_version_info,
            "get_status": self.api_get_status,
            "get_login_info": self.api_get_login_info,
            "get_friend_list": self.api_get_friend_list,
            "get_friends_with_category": self.api_get_friends_with_category,
            "get_friend_list_ex": self.api_get_friends_with_category,
            "get_group_list": self.api_get_group_list,
            "get_group_info": self.api_get_group_info,
            "get_group_info_ex": self.api_get_group_info,
            "get_group_member_list": self.api_get_group_member_list,
            "get_group_member_info": self.api_get_stranger_info,
            "get_group_system_msg": self.api_get_group_system_msg,
            "set_group_add_request": self.api_set_group_add_request,
            "set_group_kick": self.api_set_group_kick,
            "set_group_admin": self.api_set_group_admin,
            "set_group_name": self.api_set_group_name,
            "set_group_card": self.api_set_group_card,
            "set_group_special_title": self.api_set_group_special_title,
            "set_group_whole_ban": self.api_set_group_whole_ban,
            "_set_group_whole_ban": self.api_set_group_whole_ban,
            "set_group_ban": self.api_set_group_card,      # 单成员禁言：占位不报错
            "_send_group_notice": self.api_send_group_notice,
            "_set_group_notice": self.api_send_group_notice,
            "set_group_portrait": self.api_set_group_portrait,
            "upload_group_file": self.api_upload_group_file,
            "get_stranger_info": self.api_get_stranger_info,
            "send_msg": self.api_send_msg,
            "send_private_msg": self.api_send_msg,
            "send_group_msg": self.api_send_group_msg,
            "send_private_forward_msg": self.api_send_private_forward_msg,
            "send_group_forward_msg": self.api_send_group_forward_msg,
            "get_friend_msg_history": self.api_get_friend_msg_history,
            "get_group_msg_history": self.api_get_group_msg_history,
            "get_msg": self.api_get_msg,
            "get_msg_history": self.api_get_friend_msg_history,
            "get_forward_msg": self.api_get_forward_msg,
            "mark_private_msg_as_read": self.api_set_msg_read,
            "mark_group_msg_as_read": self.api_set_msg_read,
            "set_msg_read": self.api_set_msg_read,
            "set_msg_emoji_like": self.api_noop,
            "send_like": self.api_noop,
            "delete_msg": self.api_delete_msg,
            "fetch_custom_face": self.api_fetch_custom_face,
            "get_recent_contact": self.api_get_recent_contact,
            "get_record": self.api_null,
            "get_image": self.api_null,
            "get_cookies": self.api_empty_str,
            "get_csrf_token": self.api_empty_str,
            "can_send_image": self.api_can_send,
            "can_send_record": self.api_can_send,
            "get_online_clients": self.api_null,
            "getEssenceMsgList": self.api_null,
            "_get_group_notice": self.api_get_group_notice,
            "get_group_root_files": self.api_null,
        }

    async def _dispatch(self, action: str, params: Dict[str, Any]) -> Dict[str, Any]:
        handler = self._api_table.get(action)
        if handler is None:
            # 未知 action：回 ok + null（不回 failed，避免客户端弹错误弹窗），
            # 但打一条日志 —— 后续按实际被调用的频率决定要不要真实现。
            print(f"[onebot-server] 未实现的 action：{action}"
                  f"（params: {str(params)[:80]}）→ 返回 ok/null")
            return self._ok(None)
        try:
            data = await handler(params)
            return self._ok(data)
        except Exception as e:  # noqa: BLE001
            print(f"[onebot-server] action {action} 出错：{e!r}")
            return {"status": "failed", "retcode": 1200,
                    "wording": str(e)[:200], "data": None}

    @staticmethod
    def _ok(data: Any) -> Dict[str, Any]:
        return {"status": "ok", "retcode": 0, "data": data}

    # ---------------- 元信息类 API ----------------

    async def api_get_version_info(self, _p: Dict[str, Any]) -> Dict[str, Any]:
        # app_name 含 "NapCat" → Stapxs 会加载 NapCat.Onebot.yaml pathMap
        return {
            "app_name": "NapCat",
            "app_version": "vol/onebot-server 1.0",
            "protocol_version": "v11",
            "impl": "vol",
        }

    async def api_get_status(self, _p: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "online": bool(self._clients),
            "good": True,
            "app_initialized": True,
            "statistics": {"packet_received": 0, "message_sent": 0},
        }

    async def api_get_login_info(self, _p: Dict[str, Any]) -> Dict[str, Any]:
        """登录者 = 用户自己。客户端里的「我」就是用户。"""
        return {"user_id": int(self.cfg.owner_id or 0),
                "nickname": self.scfg.owner_nickname}

    async def api_get_friend_list(self, _p: Dict[str, Any]) -> List[Dict[str, Any]]:
        if self.characters:
            return [self.characters.buddy(c) for c in self.characters.all()]
        return [self._bot_buddy()]

    async def api_get_friends_with_category(
            self, _p: Dict[str, Any]) -> List[Dict[str, Any]]:
        """NapCat 分类格式：data[*].buddyList[*]（Stapxs pathMap source）。"""
        if self.characters:
            buddies = [self.characters.buddy(c) for c in self.characters.all()]
        else:
            buddies = [self._bot_buddy()]
        return [{
            "categoryId": 1,
            "categoryName": "角色",
            "categorySortId": 1,
            "buddyList": buddies,
        }]

    def _bot_buddy(self) -> Dict[str, Any]:
        return {
            "user_id": int(self.cfg.self_id or 0),
            "nickname": self.scfg.bot_nickname,
            "remark": "",
            "longNick": "",
            "q_id": "",
            "sex": "unknown",
        }

    async def api_get_group_list(self, _p: Dict[str, Any]) -> List[Dict[str, Any]]:
        if not self.group_api:
            return []
        try:
            groups = self.group_api.groups_payload()
        except Exception as e:  # noqa: BLE001
            print(f"[onebot-server] 取群列表失败：{e!r}")
            return []
        return [{
            "group_id": int(g["group_id"]) if str(g["group_id"]).isdigit() else 0,
            "group_name": str(g.get("group_name") or "群聊"),
            "member_count": int(g.get("member_count") or 0),
            "max_member_count": 200,
            "group_create_time": 0,
            "group_level": 1,
            "group_memo": str(g.get("announce") or ""),
        } for g in groups]

    async def api_get_stranger_info(self, p: Dict[str, Any]) -> Dict[str, Any]:
        cid = str(p.get("user_id") or "")
        c = self.characters.get(cid) if self.characters else None
        if c:
            return {
                "user_id": int(c.id), "nickname": c.name, "sex": "unknown",
                "age": 17, "qid": "", "longNick": "", "city": "基沃托斯",
            }
        return {
            "user_id": int(self.cfg.self_id or 0),
            "nickname": self.scfg.bot_nickname,
            "sex": "unknown",
            "age": 17,
            "qid": "",
            "longNick": "随便随便~ 要轻松最重要啦~",
            "city": "阿拜多斯",
        }

    # ---------------- 发消息（用户 → vol） ----------------

    async def api_send_msg(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """用户在客户端发消息。user_id 参数 = 星野（会话目标）。

        构造 IncomingMessage（user_id=owner，通过主管线的「是不是主人」
        校验）→ fire 进主管线（不阻塞响应）→ 立即推 message_sent
        事件（发送端替换 fake_msg，其他端同步）。
        """
        message = params.get("message")
        target_id = str(params.get("user_id") or "")
        group_id = str(params.get("group_id") or "")
        if group_id:
            return await self._send_group_msg(group_id, message)

        # 消息段归一：Stapxs 偶尔发 subType（驼峰）—— 统一成 sub_type，
        # 这样主管线的 _is_sticker_only 判定（认 sub_type=="1"）才能命中
        segments = self._normalize_segments(message)
        raw = {"message_type": "private",
               "time": int(time.time()),
               "user_id": int(self.cfg.owner_id or 0) if self.cfg.owner_id else 0,
               "message": segments,
               "_target_id": target_id}

        text, images, mentioned, img_ids, img_sizes, fwd_ids = parse_message(
            segments, self.cfg.owner_id)
        # base64:// 不是 NapCat 的 file_id —— 别让它触发 get_image 旁路
        img_ids = [i for i in img_ids if not str(i).startswith("base64://")]
        # ★ 合并转发：登记内容并把正文并入 text。fwd_ids 清空 —— 正文已经在
        #   text 里了，再让主管线 fetch 一遍会重复一遍。
        text = self._prepare_forwards(segments, text)
        fwd_ids = []

        if images:
            now = time.time()
            if now - self._last_media_log > 30:
                self._last_media_log = now
                print(f"[onebot-server] 收到带图消息：{describe_segments(segments)}")

        mid = str(next(self._msg_ids))
        peer_id = target_id or str(self.cfg.self_id or "")
        msg = IncomingMessage(
            kind="private",
            user_id=str(self.cfg.owner_id or ""),   # 发送者 = 用户
            peer_id=peer_id,                        # 会话对象 = 星野或新增角色
            group_id="",
            message_id=mid,
            nickname=self.scfg.owner_nickname,
            text=text,
            images=images,
            raw_image_ids=img_ids,
            raw_image_sizes=img_sizes,
            forward_ids=fwd_ids,
            mentions_self=mentioned,
            raw=raw,
        )
        # 先广播 message_sent（客户端把预发送占位替换成真消息），
        # 再进主管线。★ 用 create_task 延迟推送：保证 send_msg 的 echo
        # 响应先回到客户端、事件紧随其后 —— 和 NapCat 的「HTTP 响应 +
        # 事件通道」时序一致，客户端的等待逻辑不会被事件抢跑打乱。
        asyncio.create_task(self._push_user_message(mid, segments, text, peer_id))
        asyncio.create_task(self._safe_handle(msg))
        return {"message_id": mid}

    async def api_send_group_msg(self, params: Dict[str, Any]) -> Dict[str, Any]:
        return await self.api_send_msg(params)

    async def api_send_private_forward_msg(
            self, params: Dict[str, Any]) -> Dict[str, Any]:
        """合并转发（私聊）。Stapxs 合并转发走的是这个 action。

        messages = [{type:"node", data:{user_id, nickname, content:[段]}}, …]
        """
        return await self._api_send_forward(params, group=False)

    async def api_send_group_forward_msg(
            self, params: Dict[str, Any]) -> Dict[str, Any]:
        """合并转发（群聊）。"""
        return await self._api_send_forward(params, group=True)

    async def _api_send_forward(self, params: Dict[str, Any],
                                *, group: bool) -> Dict[str, Any]:
        """收到一份合并转发：存内容 → 推「聊天记录」卡片 → 正文进主管线。

        卡片段只带 id + 摘要（和 QQ 一致，内容点开再取）；正文另外并入
        text 喂主管线，这样星野和新增角色都能读到里面说了什么。
        """
        nodes = self._nodes_of(params.get("messages"))
        mid = str(next(self._msg_ids))
        if not nodes:
            return {"message_id": mid}          # 空的转发：不回错误，静默
        fid = self._register_forward(nodes)
        segments = [self._forward_seg(fid, nodes)]
        body = self._forward_text(nodes)
        text = ("【转发了一段聊天记录，内容见下】"
                + (("\n" + body) if body else "")).strip()
        if group:
            gid = str(params.get("group_id") or "")
            if not self._has_group(gid):
                print(f"[onebot-server] 转发到未知群（group_id={gid}），忽略")
                return {"message_id": mid}
            raw = {"message_type": "group", "time": int(time.time()),
                   "user_id": int(self.cfg.owner_id or 0),
                   "group_id": int(gid) if gid.isdigit() else gid,
                   "message": segments}
            msg = IncomingMessage(
                kind="group", user_id=str(self.cfg.owner_id or ""),
                group_id=gid, peer_id=gid, message_id=mid,
                nickname=self.scfg.owner_nickname, text=text,
                mentions_self=False, raw=raw)
            asyncio.create_task(
                self._push_user_message(mid, segments, text, "", group_id=gid))
            asyncio.create_task(self._safe_handle(msg))
            return {"message_id": mid}
        peer_id = str(params.get("user_id") or self.cfg.self_id or "")
        raw = {"message_type": "private", "time": int(time.time()),
               "user_id": int(self.cfg.owner_id or 0) if self.cfg.owner_id else 0,
               "message": segments, "_target_id": peer_id}
        msg = IncomingMessage(
            kind="private", user_id=str(self.cfg.owner_id or ""),
            peer_id=peer_id, group_id="", message_id=mid,
            nickname=self.scfg.owner_nickname, text=text,
            mentions_self=False, raw=raw)
        asyncio.create_task(self._push_user_message(mid, segments, text, peer_id))
        asyncio.create_task(self._safe_handle(msg))
        return {"message_id": mid}

    @staticmethod
    def _reply_id_of(segments: Any) -> str:
        """从消息段里取「引用回复」的目标 mid（没有就返回空串）。"""
        if not isinstance(segments, list):
            return ""
        for seg in segments:
            if not isinstance(seg, dict) or seg.get("type") != "reply":
                continue
            data = seg.get("data") or {}
            rid = str(data.get("id") or data.get("message_id") or "").strip()
            if rid:
                return rid
        return ""

    def _has_group(self, gid: str) -> bool:
        api = self.group_api
        try:
            return bool(api and api.groups.exists(str(gid)))
        except Exception:  # noqa: BLE001
            return False

    async def _send_group_msg(self, group_id: str, message: Any) -> Dict[str, Any]:
        """我在群里发消息 → 落库（由群引擎做）+ 广播 + 进群引擎。

        ★ 我发的消息**先落库、再判禁言**：全员禁言时群友也「看得到」，
        只是不回 —— 这是用户明确要的语义，落库动作在引擎里完成。
        """
        gid = str(group_id or "")
        if not self._has_group(gid):
            print(f"[onebot-server] 收到未知群消息（group_id={gid}），忽略")
            return {"message_id": str(next(self._msg_ids))}
        segments = self._normalize_segments(message)
        text, images, mentioned, img_ids, img_sizes, fwd_ids = parse_message(
            segments, self.cfg.owner_id)
        img_ids = [i for i in img_ids if not str(i).startswith("base64://")]
        # ★ 合并转发：登记内容并把正文并入 text（fwd_ids 清空，理由同私聊）
        text = self._prepare_forwards(segments, text)
        fwd_ids = []
        mid = str(next(self._msg_ids))
        raw = {"message_type": "group", "time": int(time.time()),
               "user_id": int(self.cfg.owner_id or 0),
               "group_id": int(gid) if gid.isdigit() else gid,
               "message": segments,
               # 「引用回复」：段里的 reply.data.id 就是被引用消息的 mid，
               # 群引擎据此把 reply_to 落到库里，历史和实时都能渲染引用块
               "_reply_id": self._reply_id_of(segments)}
        msg = IncomingMessage(
            kind="group",
            user_id=str(self.cfg.owner_id or ""),
            group_id=gid,
            peer_id=gid,                 # 群会话的「对方」就是群
            message_id=mid,
            nickname=self.scfg.owner_nickname,
            text=text,
            images=images,
            raw_image_ids=img_ids,
            raw_image_sizes=img_sizes,
            forward_ids=fwd_ids,
            mentions_self=mentioned,
            raw=raw,
        )
        asyncio.create_task(self._push_user_message(mid, segments, text, "",
                                                   group_id=gid))
        asyncio.create_task(self._safe_handle(msg))
        return {"message_id": mid}

    async def _safe_handle(self, msg: IncomingMessage) -> None:
        try:
            await self.on_message(msg)
        except Exception as e:  # noqa: BLE001
            # ★ 一定要带堆栈：这里以前只 print 一行 repr，于是「我在群里说话
            #   没人理」的真实原因（pick 里 limit 是 float 导致的切片异常）
            #   在日志里完全看不出是哪一行，白白排查了一轮。
            print(f"[onebot-server] 主管线处理出错：{e!r}")
            traceback.print_exc()

    @staticmethod
    def _normalize_segments(message: Any) -> Any:
        """把各种形态的 message 字段归一成 OneBot 段数组。

        兼容三种输入：str（纯文本/CQ 码）、[{type,data}]（标准）、
        以及 Stapxs 偶发的扁平段（{type:'text', text:'...'}）和
        驼峰键（subType → sub_type）。
        """
        if message is None:
            return []
        if isinstance(message, str):
            return [{"type": "text", "data": {"text": message}}]
        if not isinstance(message, list):
            return []
        out: List[Any] = []
        for seg in message:
            if not isinstance(seg, dict):
                continue
            t = seg.get("type")
            if not t:
                continue
            if "data" in seg and isinstance(seg["data"], dict):
                data = dict(seg["data"])
            else:
                data = {k: v for k, v in seg.items() if k != "type"}
            # 驼峰归一
            for camel, snake in (("subType", "sub_type"),):
                if camel in data:
                    data.setdefault(snake, data.pop(camel))
            out.append({"type": t, "data": data})
        return OneBotServerChannel._dedupe_at_text(out)

    @staticmethod
    def _dedupe_at_text(segments: List[Any]) -> List[Any]:
        """削掉「紧跟 at 段之后」那个重复的「@某人 」。

        ★ 客户端 @ 人时会把「@某人 」**同时**写进 at 段和 text 段（输入框里
        插的是纯文本，at 段是发送时另加的）。服务端原样存下来，气泡上就出现
        **两遍** —— 一个 at 芯片 + 文本里又写一遍「@橘雪莉」（用户实测截图：
        看起来像气泡左边多了一段带底色的空白块）。
        在入口削掉，历史回放/多端同步拿到的都是干净的段。
        """
        out: List[Any] = []
        for seg in (segments or []):
            if (isinstance(seg, dict) and seg.get("type") == "text"
                    and out and isinstance(out[-1], dict)
                    and out[-1].get("type") == "at"):
                d = dict(seg.get("data") or {})
                t = str(d.get("text") or "")
                stripped = re.sub(r"^\s*@[^\s@]+[\s\u3000]*", "", t)
                if stripped != t:
                    d["text"] = stripped
                    seg = {"type": "text", "data": d}
            out.append(seg)
        return out

    async def _emit_event(self, event: Dict[str, Any]) -> None:
        """统一出口：没有客户端时进离线队列；有客户端时广播并留一份给新设备。"""
        if not self._clients:
            self._offline_queue.append(event)
            del self._offline_queue[:-200]       # 私聊与群共用，留 200 条
            return
        self._recent_events.append(event)
        cutoff = time.time() - 1800           # 只补最近 30 分钟
        self._recent_events = [e for e in self._recent_events
                               if float(e.get("time") or 0) >= cutoff]
        # 私聊与群共用；活跃群会把私聊事件挤掉，所以留 600 条而不是 200
        del self._recent_events[:-600]
        await self._broadcast(event)

    async def _push_user_message(self, mid: str, segments: Any, text: str,
                                 peer_id: str = "",
                                 group_id: str = "") -> None:
        """用户消息上屏：message_sent 事件（sender=用户）。

        私聊：user_id = 会话对象（＝对方是谁）；群里：user_id 仍是**发送者**
        （＝我自己），会话身份靠 group_id 表达 —— 两种模式语义不同，
        客户端按 message_type 分流。

        Stapxs 收到后：发送端用它替换 fake_msg 占位；其他设备作为
        「自己发的消息」追加（右侧气泡）—— 这就是多端同步。
        """
        try:
            peer_int = int(peer_id or self.cfg.self_id or 0)
        except ValueError:
            peer_int = 0
        gid = str(group_id or "")
        owner_int = int(self.cfg.owner_id or 0)
        event = {
            "time": int(time.time()),
            "self_id": owner_int,
            "post_type": "message_sent",
            "message_type": "group" if gid else "private",
            "sub_type": "normal" if gid else "friend",
            "message_id": mid,
            "user_id": owner_int if gid else peer_int,
            "sender": {"user_id": owner_int,
                       "nickname": self.scfg.owner_nickname},
            "message": segments if isinstance(segments, list) else [],
            "raw_message": text,
        }
        if gid:
            event["group_id"] = int(gid) if gid.isdigit() else gid
            event["sender"].update(self._group_member_meta(gid, owner_int))
            q = self._quoted_of(gid, segments)
            if q:
                event["reply"] = q
        else:
            # ★ 私聊也要挂 reply：Stapxs 在私聊里也能「引用回复」，服务端不把
            #   被引用那条带回去，客户端就只看到自己发的话、看不到引用块
            #   （用户实测「引用回复发出来后依然没有看到引用」）。
            rid = self._reply_id_of(segments)
            q = self._quoted_private(str(peer_int), rid) if rid else None
            if q:
                event["reply"] = q
        self._live_msgs[mid] = {
            "role": "user", "peer_id": str(peer_int),
            "ts": float(event["time"]), "text": text,
            "group_id": gid,
        }
        self._trim_live_msgs()
        await self._emit_event(event)

    def _group_member_meta(self, gid: str, uid: Any) -> Dict[str, Any]:
        """群消息的发送者徽章：群名片 / 角色（群主·管理）/ 头衔 / 等级。

        ★ 实时推送的 sender 以前只有 user_id + nickname —— 客户端画不出来
        「群主 / LV5」这些徽章（只能兜底成 LV1），而右侧成员列表是按真实
        等级算的。于是同一个人在聊天气泡上是 LV1、在成员列表里是 LV2
        （用户实测「群聊里的用户等级和右侧列表对不上」）。这里补齐。
        """
        out: Dict[str, Any] = {"card": "", "role": "member", "title": "",
                               "level": 1}
        api = self.group_api
        if not api or not gid:
            return out
        try:
            detail = api.group_detail(gid)
        except Exception:  # noqa: BLE001
            return out
        for m in detail.get("members") or []:
            if str(m.get("user_id")) == str(uid):
                out["card"] = str(m.get("nickname") or "")
                out["role"] = str(m.get("role") or "member")
                out["title"] = str(m.get("title") or "")
                try:
                    out["level"] = int(m.get("level") or 1)
                except (TypeError, ValueError):
                    out["level"] = 1
                break
        return out

    def _quoted_of(self, gid: str, segments: Any) -> Optional[Dict[str, Any]]:
        """把我「引用回复」的那条消息一并带进事件，别的端也能画出引用块。"""
        return self._quoted_by_mid(gid, self._reply_id_of(segments))

    @staticmethod
    def _base_mid(mid: str) -> str:
        """把「第 N 条气泡」的 mid 还原成那条消息的库内 mid。

        一条 gmsg 可能被拆成多条气泡推送，mid 形如 `g119` / `g119-2` / `g119-3`
        （和私聊历史的 `h<id>-2` 同一套写法）。引用第 2、3 条气泡时，
        要按 `g119` 去查库才找得到。
        """
        rid = str(mid or "").strip()
        if "-" in rid:
            head, _, tail = rid.rpartition("-")
            if head and tail.isdigit():
                return head
        return rid

    def _quoted_by_mid(self, gid: str, mid: str) -> Optional[Dict[str, Any]]:
        """按 mid 取出被引用消息的「昵称 + 摘要」（历史和实时都用它）。

        ★ 先问群引擎：它手里有「我那条消息的**实时随机 id** ↔ 库内 g&lt;id&gt;」
        的对照表。我引用自己刚发的那条群消息时，客户端拿到的 mid 就是那个
        随机 id —— 只按库内 mid 查会查不到，引用块就永远画不出来
        （用户实测：引用自己发的话，发出去看不到引用）。
        """
        rid = self._base_mid(mid)
        if not rid:
            return None
        api = self.group_api
        if not api or not self._has_group(str(gid or "")):
            return None
        q = getattr(api, "group_quoted", None)
        if q:
            try:
                got = q(gid, rid)
            except Exception:  # noqa: BLE001
                got = None
            if got:
                return got
        try:
            src = api.group_store_for(gid).find_gmsg(rid)
        except Exception:  # noqa: BLE001
            src = None
        if not src:
            # ★ 兜底：我那条消息的事件是**先推、后落库**的，推的时候库内 mid
            #   还没生成、群引擎的对照表也是之后才写好 —— 于是「引用自己刚发
            #   的那条」在实时事件里 resolve 不出来（历史回放却是好的，用户
            #   看到的就是「发出来后没有引用」）。这里直接用通道自己记下的
            #   实时消息（_live_msgs）兜底。
            info = self._live_msgs.get(rid)
            if info and str(info.get("group_id") or "") == str(gid or ""):
                role = str(info.get("role") or "")
                if role == "user":
                    name = self.scfg.owner_nickname
                else:
                    char = (self.characters.get(str(info.get("peer_id") or ""))
                            if self.characters else None)
                    name = char.name if char else self.scfg.bot_nickname
                return {"message_id": rid, "name": name,
                        "text": str(info.get("text") or "")[:80].replace("\n", " ")}
            return None
        kind = str(src.get("kind") or "")
        if kind == "user":
            name = self.scfg.owner_nickname
        elif kind == "system":
            name = "系统"
        else:
            name = str(src.get("sender_name") or "成员")
        return {"message_id": str(src.get("mid") or rid), "name": name,
                "text": str(src.get("text") or "")[:80].replace("\n", " ")}

    def _quoted_private(self, peer_id: str,
                        mid: str) -> Optional[Dict[str, Any]]:
        """私聊里按 mid 取「被引用那条」的昵称 + 摘要。

        私聊没有群那样的 `g&lt;id&gt;` 库内 mid：历史回放用 `h&lt;turn id&gt;`，
        实时那条则是一个随机序号（存在 `_live_msgs` 里）。两种都要认。
        """
        rid = self._base_mid(mid)
        if not rid:
            return None
        # ① 实时消息（随机序号 / h<id> 都可能在 _live_msgs 里）
        info = self._live_msgs.get(rid) or self._live_msgs.get(str(mid or ""))
        if info and not str(info.get("group_id") or ""):
            role = str(info.get("role") or "")
            return {"message_id": rid,
                    "name": self._peer_name(str(info.get("peer_id") or peer_id),
                                            role),
                    "text": str(info.get("text") or "")[:80].replace("\n", " ")}
        # ② 历史消息：h<turn id> → transcript 行
        tid = 0
        if rid.startswith("h"):
            try:
                tid = int(rid[1:])
            except ValueError:
                tid = 0
        if not tid:
            return None
        store = self.store_for(peer_id) if self.store_for else self.store
        try:
            turn = store.get_turn(tid) if store else None
        except Exception:  # noqa: BLE001
            turn = None
        if not turn:
            return None
        role = str(turn.get("role") or "")
        return {"message_id": rid, "name": self._peer_name(peer_id, role),
                "text": str(turn.get("text") or "")[:80].replace("\n", " ")}

    def _peer_name(self, peer_id: str, role: str) -> str:
        """私聊引用块里的显示名：我发的是我，角色发的是角色名。"""
        if role == "user":
            return self.scfg.owner_nickname
        char = self.characters.get(str(peer_id)) if self.characters else None
        if char:
            return char.name
        return self.scfg.bot_nickname

    # ---------------- vol → 客户端（Sender 调用的接口） ----------------

    async def send_text(self, text: str, *, user_id: str = "",
                        group_id: str = "", sender_id: str = "",
                        sender_name: str = "", reply_to_mid: str = "",
                        message_id: str = "") -> Dict[str, Any]:
        await self._push_bot_message(
            [{"type": "text", "data": {"text": text}}], text,
            sender_id=sender_id, sender_name=sender_name, group_id=group_id,
            reply_to_mid=reply_to_mid, message_id=message_id)
        return {"status": "ok", "retcode": 0, "data": None}

    async def send_sticker(self, file: str, *, user_id: str = "",
                           group_id: str = "",
                           summary: str = "[表情包]",
                           sender_id: str = "",
                           sender_name: str = "",
                           reply_to_mid: str = "",
                           message_id: str = "") -> Dict[str, Any]:
        """file 是 file_uri() 生成的 HTTP URL（客户端 <img> 直接加载）。"""
        await self._push_bot_message(
            [{"type": "image",
              "data": {"file": file, "summary": summary, "sub_type": 1}}],
            summary, sender_id=sender_id, sender_name=sender_name,
            group_id=group_id, reply_to_mid=reply_to_mid,
            message_id=message_id)
        return {"status": "ok", "retcode": 0, "data": None}

    async def send_segments(self, segments: List[Dict[str, Any]], *,
                            user_id: str = "", group_id: str = "",
                            sender_id: str = "",
                            sender_name: str = "",
                            reply_to_mid: str = "",
                            message_id: str = "") -> Dict[str, Any]:
        raw = "".join(str((s.get("data") or {}).get("text") or "")
                      for s in segments if s.get("type") == "text")
        await self._push_bot_message(
            segments, raw, sender_id=sender_id, sender_name=sender_name,
            group_id=group_id, reply_to_mid=reply_to_mid,
            message_id=message_id)
        return {"status": "ok", "retcode": 0, "data": None}

    async def _push_bot_message(self, segments: List[Dict[str, Any]],
                                raw_text: str, *, sender_id: str = "",
                                sender_name: str = "",
                                group_id: str = "",
                                reply_to_mid: str = "",
                                message_id: str = "") -> None:
        """角色的消息：message 事件（sender=该角色）→ 客户端左侧气泡。

        私聊时 user_id = 发送者（会话对方就是它）；群里则是
        message_type=group + group_id，**user_id 仍然是发送者**
        —— 客户端靠这个区分「谁在群里说话」，别按私聊的语义去理解。

        没有客户端在线时入离线队列（连接建立时重放），
        有客户端在线时直接广播。"""
        try:
            sid = int(sender_id or self.cfg.self_id or 0)
        except ValueError:
            sid = 0
        name = (sender_name or self.scfg.bot_nickname).strip() or "星野"
        # ★ 群里用**群库里的 mid**（g<id>）当 message_id，而不是随机序号 ——
        #   否则「实时收到的那条」和「刷新后历史里的那条」是两套 id，
        #   客户端引用实时消息时后端按 mid 查库查不到 → 引用回复整个失效
        #   （实测：我引用提出的消息，落库 reply_to=0、气泡也没有引用块）。
        mid = str(message_id or next(self._msg_ids))
        gid = str(group_id or "")
        event = {
            "time": int(time.time()),
            "self_id": int(self.cfg.owner_id or 0),
            "post_type": "message",
            "message_type": "group" if gid else "private",
            "sub_type": "normal" if gid else "friend",
            "message_id": mid,
            "user_id": sid,                         # 发送者 = 当前角色
            "sender": {"user_id": sid, "nickname": name},
            "message": segments,
            "raw_message": raw_text,
        }
        if gid:
            event["group_id"] = int(gid) if gid.isdigit() else gid
            event["sender"].update(self._group_member_meta(gid, sid))
            # ★ 角色引用我的某条消息时，把它一并写进事件 —— 否则客户端只有
            #   重新打开群、走历史接口才能画出引用块（实时的那条没有引用）
            q = self._quoted_by_mid(gid, reply_to_mid)
            if q:
                event["reply"] = q
        elif reply_to_mid:
            # 私聊同理：角色引用我上一句时也要把引用块带回去
            q = self._quoted_private(str(sid), reply_to_mid)
            if q:
                event["reply"] = q
        self._live_msgs[mid] = {
            "role": "assistant", "peer_id": str(sid),
            "ts": float(event["time"]), "text": raw_text,
            "group_id": gid,
        }
        self._trim_live_msgs()
        if not self._clients:
            self._offline_queue.append(event)
            # ★ 私聊和群聊共用这一条队列；一个活跃的群很容易把私聊消息挤掉
            #   （原来是 50 条），所以放宽到 200 条再丢最旧的。
            del self._offline_queue[:-200]
            print(f"[onebot-server] 无客户端在线，消息入离线队列"
                  f"（{len(self._offline_queue)} 条待重放）：{raw_text[:30]}")
            return
        await self._emit_event(event)

    def _trim_live_msgs(self) -> None:
        """实时消息 id 表只留最近一小时，避免无限增长。"""
        if len(self._live_msgs) <= 600:
            return
        cutoff = time.time() - 3600
        for mid, info in list(self._live_msgs.items()):
            if float(info.get("ts") or 0) < cutoff:
                self._live_msgs.pop(mid, None)

    async def push_group_system(self, group_id: str, text: str) -> None:
        """群里的系统消息（建群 / 改名 / 入群 / 踢人 / 公告…）。

        不是谁说的，所以 user_id=0、sender.role=system —— 客户端把它渲染成
        居中的提示条（像 QQ 群里的灰字），而不是某个人的气泡。
        """
        gid = str(group_id or "")
        if not gid or not str(text or "").strip():
            return
        body = str(text)
        mid = str(next(self._msg_ids))
        event = {
            "time": int(time.time()),
            "self_id": int(self.cfg.owner_id or 0),
            "post_type": "message",
            "message_type": "group",
            "sub_type": "normal",
            "message_id": mid,
            "user_id": 0,
            "sender": {"user_id": 0, "nickname": "系统", "card": "系统",
                       "role": "system", "level": 0, "title": ""},
            "message": [{"type": "text", "data": {"text": body}}],
            "raw_message": body,
            "group_id": int(gid) if gid.isdigit() else gid,
        }
        self._live_msgs[mid] = {"role": "system", "peer_id": gid,
                                "ts": float(event["time"]), "text": body,
                                "group_id": gid}
        self._trim_live_msgs()
        await self._emit_event(event)

    def file_uri(self, path: str | Path) -> str:
        """本地文件 → 客户端可加载的 HTTP URL（表情包下载走静态路由）。

        与 NapCatChannel.file_uri（file:///）同签名 —— Sender 不用改。
        不在图库目录下的文件返回 file:// 原样（客户端加载不了，
        但日志里能看出来）。
        """
        p = Path(path).resolve()
        if self.sticker_dir:
            try:
                rel = p.relative_to(self.sticker_dir)
                return f"{self.scfg.base_url}/{_ASSET_PREFIX}/{rel.as_posix()}"
            except ValueError:
                pass
        return p.as_uri()

    # ---------------- 合并转发（QQ「聊天记录」） ----------------
    #
    # 自托管链路里 vol 自己就是服务端，所以「合并转发」的内容只能由 vol 保管：
    # 客户端（Stapxs）发合并转发时调 `send_private_forward_msg` /
    # `send_group_forward_msg`（messages = node 列表），点开卡片时调
    # `get_forward_msg` 取内容。这两个 action 以前**都没实现** —— 于是转发被当成
    # 未知 action 静默丢弃、`get_forward_msg` 又永远返回空，客户端只能显示一句
    # 「[聊天记录]」并且点不开（用户实测报障）。

    @staticmethod
    def _seg_flat_text(segs: Any) -> str:
        """把消息段数组拍成一行的可读文本（转发节点内部用）。"""
        parts: List[str] = []
        for s in (segs or []):
            if not isinstance(s, dict):
                continue
            t = s.get("type")
            d = s.get("data") if isinstance(s.get("data"), dict) else {}
            if t == "text":
                parts.append(str(d.get("text") or ""))
            elif t in ("image", "mface", "marketface"):
                sticker = (str(d.get("sub_type") or "") == "1"
                           or "动画表情" in str(d.get("summary") or ""))
                parts.append("[表情包]" if sticker else "[图片]")
            elif t == "face":
                parts.append("[表情]")
            elif t == "record":
                parts.append("[语音]")
            elif t == "at":
                parts.append("@" + str(d.get("qq") or ""))
            else:
                parts.append(str(d.get("text") or ""))
        return "".join(parts).strip()

    def _nodes_of(self, messages: Any) -> List[Dict[str, Any]]:
        """归一「合并转发」节点 → [{user_id, nickname, content:[段]}]。

        兼容两种形态：标准 OneBot `{type:"node", data:{...}}`，以及
        Stapxs 发送时的扁平形态（键直接摊在 node 上）。
        """
        out: List[Dict[str, Any]] = []
        for node in (messages or []):
            if not isinstance(node, dict):
                continue
            d = node.get("data") if isinstance(node.get("data"), dict) else node
            content = d.get("content")
            if content is None:
                content = node.get("content")
            if isinstance(content, str):
                try:
                    content = json.loads(content)
                except (json.JSONDecodeError, ValueError):
                    content = [{"type": "text", "data": {"text": content}}]
            if isinstance(content, dict):
                content = [content]
            if not isinstance(content, list):
                content = []
            out.append({
                "user_id": str(d.get("user_id") or d.get("uin") or ""),
                "nickname": str(d.get("nickname") or d.get("name") or ""),
                "content": content,
                "time": int(d.get("time") or node.get("time") or 0),
            })
        return out

    def _forward_text(self, nodes: List[Dict[str, Any]]) -> str:
        """把转发节点拍平成「昵称：正文」的多行文本。"""
        lines: List[str] = []
        for n in nodes or []:
            who = str(n.get("nickname") or n.get("user_id") or "某人")
            body = self._seg_flat_text(n.get("content"))
            if body:
                lines.append(f"{who}：{body}")
        return "\n".join(lines)

    def _register_forward(self, nodes: List[Dict[str, Any]]) -> str:
        """把一份转发内容存下来，返回本地 id（客户端点开时用它取回）。"""
        fid = "f" + str(next(self._msg_ids))
        if nodes:
            self._forwards[fid] = nodes
            # 落盘：vol 重启后卡片仍能展开（否则就成了只有 id 的空壳）
            try:
                self.store.kv_set(f"forward:{fid}", nodes)
            except Exception:  # noqa: BLE001
                pass
        if len(self._forwards) > 300:
            for k in list(self._forwards)[:-300]:
                self._forwards.pop(k, None)
        return fid

    def _lookup_forward(self, fid: str) -> List[Dict[str, Any]]:
        fid = str(fid or "").strip()
        if not fid:
            return []
        nodes = self._forwards.get(fid)
        if nodes:
            return nodes
        try:
            saved = self.store.kv_get(f"forward:{fid}") if self.store else None
        except Exception:  # noqa: BLE001
            saved = None
        if isinstance(saved, list) and saved:
            self._forwards[fid] = saved
            return saved
        return []

    @staticmethod
    def _forward_seg(fid: str, nodes: List[Dict[str, Any]]) -> Dict[str, Any]:
        """推给客户端的「聊天记录」段（只带 id + 摘要；内容和 QQ 一样另取）。"""
        return {"type": "forward",
                "data": {"id": str(fid),
                         "title": "聊天记录",
                         "summary": f"查看 {len(nodes)} 条转发消息"}}

    def _prepare_forwards(self, segments: Any, text: str) -> str:
        """入站消息带「合并转发」段时：登记内容，并把正文并入 text。

        这样角色（星野和新增角色）读到的是**正文**，而不是一句「[聊天记录]」；
        同时 get_forward_msg 也能把内容交还给客户端。
        """
        for seg in (segments or []):
            if not isinstance(seg, dict):
                continue
            t = seg.get("type")
            d = seg.get("data") if isinstance(seg.get("data"), dict) else {}
            if t == "forward":
                nodes = self._nodes_of(d.get("content") or d.get("messages"))
                fid = str(d.get("id") or d.get("file") or "").strip()
                if not nodes and fid:
                    nodes = self._lookup_forward(fid)     # 别的端发过的旧转发
                if not nodes:
                    continue
                if fid:
                    self._forwards.setdefault(fid, nodes)
                else:
                    fid = self._register_forward(nodes)
                    d["id"] = fid
                    seg["data"] = d
                body = self._forward_text(nodes)
                if body:
                    text = (text + "\n" + body).strip()
            elif t == "json":
                fid = self._multimsg_resid(d)
                body = self._forward_text(self._lookup_forward(fid)) if fid else ""
                if body:
                    text = (text + "\n" + body).strip()
        return text

    @staticmethod
    def _multimsg_resid(d: Dict[str, Any]) -> str:
        """从 QQ 的 multimsg json 卡片里取转发的 resid（取不到返回空串）。"""
        inner = d.get("data") or ""
        if isinstance(inner, dict):
            inner = inner.get("data") or inner.get("resid") or ""
        try:
            j = json.loads(str(inner))
        except (json.JSONDecodeError, ValueError, TypeError):
            return ""
        if not isinstance(j, dict):
            return ""
        det = ((j.get("meta") or {}).get("detail") or {})
        return str(det.get("resid") or det.get("uniseq")
                   or j.get("resid") or "").strip()

    async def fetch_forward(self, fid: str, max_msgs: int = 60) -> str:
        """合并转发正文（自托管链路：从 vol 保管的内容里取）。"""
        nodes = self._lookup_forward(str(fid))
        return self._forward_text(nodes)[:4000] if nodes else ""

    # ---------------- 撤回 ----------------

    @staticmethod
    def _remove_turn_segment(store, turn: Dict[str, Any], *,
                             index: Optional[int] = None,
                             text: str = "") -> None:
        """从一条 transcript 里删掉一个气泡；删空就整条删除。"""
        raw = str(turn.get("text") or "")
        lines = raw.split("\n")
        if index is not None:
            if 0 <= index < len(lines):
                lines.pop(index)
        elif text:
            needle = text.strip()
            found = False
            for i, line in enumerate(lines):
                if line.strip() == needle:
                    lines.pop(i)
                    found = True
                    break
            if not found and needle:
                joined = "\n".join(lines)
                if needle in joined:
                    lines = joined.replace(needle, "", 1).split("\n")
        new = "\n".join(line for line in lines if line.strip())
        tid = int(turn.get("id") or 0)
        if not tid:
            return
        if new.strip():
            store.update_turn_text(tid, new[:800])
        else:
            store.delete_turn(tid)

    async def api_delete_msg(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """撤回消息：删掉 transcript 里的对应内容，并通知所有端移除气泡。"""
        mid = str(params.get("message_id") or params.get("msg_id") or "").strip()
        if not mid:
            raise ValueError("缺少 message_id")
        peer_id = str(params.get("peer_id") or params.get("target_id") or "").strip()
        info = self._live_msgs.get(mid)
        role = ""
        text = str(params.get("text") or "")
        ts = float(params.get("ts") or 0)
        if info:
            peer_id = peer_id or str(info.get("peer_id") or "")
            role = str(info.get("role") or "")
            text = str(info.get("text") or "")
            ts = float(info.get("ts") or 0)
        if not peer_id:
            raise ValueError("缺少 peer_id")

        store = self.store_for(peer_id) if self.store_for else self.store
        turn_id: Optional[int] = None
        index: Optional[int] = None
        whole_turn = False
        if mid.startswith("h"):
            body = mid[1:]
            try:
                if "-" in body:
                    a, b = body.split("-", 1)
                    turn_id = int(a)
                    index = max(0, int(b) - 1)
                else:
                    turn_id = int(body)
                    whole_turn = True
            except ValueError:
                turn_id = None
        if store and turn_id is not None:
            if whole_turn:
                store.delete_turn(turn_id)
            else:
                turn = store.get_turn(turn_id)
                if turn:
                    self._remove_turn_segment(store, turn, index=index, text=text)
                    role = str(turn.get("role") or role)
        elif store and role:
            turn = store.find_turn(role, text, ts)
            if turn:
                self._remove_turn_segment(store, turn, text=text)

        try:
            peer_int = int(peer_id or 0)
        except ValueError:
            peer_int = 0
        notice = {
            "time": int(time.time()),
            "self_id": int(self.cfg.owner_id or 0),
            "post_type": "notice",
            "notice_type": "friend_recall",
            "user_id": peer_int,
            "target_id": peer_int,
            "operator_id": int(self.cfg.owner_id or 0),
            "message_id": mid,
            "recalled_role": role or "unknown",
        }
        await self._emit_event(notice)
        self._live_msgs.pop(mid, None)
        print(f"[onebot-server] 撤回消息 {mid}（{peer_id} / {role or '未知'}）")
        return {"message_id": mid}

    async def api_set_msg_read(self, params: Dict[str, Any]) -> None:
        """同步「已读到哪」：多端打开会话后，其他设备的红点一起清掉。"""
        peer = str(params.get("user_id") or params.get("peer_id") or "").strip()
        if not peer or not self.store:
            return None
        try:
            ts = float(params.get("time") or time.time())
        except (TypeError, ValueError):
            ts = time.time()
        ts = min(ts, time.time())
        self.store.kv_set(f"last_read:{peer}", ts)
        await self._emit_event({
            "time": int(time.time()),
            "self_id": int(self.cfg.owner_id or 0),
            "post_type": "notice",
            "notice_type": "read_state",
            "user_id": int(peer) if peer.isdigit() else 0,
            "target_id": int(peer) if peer.isdigit() else 0,
            "read_time": int(ts),
        })
        return None

    # ---------------- 历史消息 ----------------

    async def api_get_friend_msg_history(
            self, params: Dict[str, Any]) -> Dict[str, Any]:
        """transcript 回放。Stapxs 打开会话 / 上滑加载时调。

        NapCat 返回格式：data.messages[]，字段 message_id / real_seq /
        time / sender / message（段数组）/ raw_message，按时间正序。
        注意 transcript 只存了纯文本（图片以「[表情包]」等占位）——
        历史里的图片暂时还原不出来，文字部分完整。
        """
        try:
            count = int(params.get("count") or 20)
        except (TypeError, ValueError):
            count = 20
        count = max(1, min(count, 100))
        peer_id = str(params.get("user_id") or self.cfg.self_id or "")
        store = self.store_for(peer_id) if self.store_for else self.store
        if not store:
            return {"messages": []}
        char = self.characters.get(peer_id) if self.characters else None
        peer_int = int(char.id) if char else int(self.cfg.self_id or 0)
        peer_name = char.name if char else self.scfg.bot_nickname
        turns = store.recent_turns(max(count, 20) * 2)
        # 只回放私聊（当前也只有私聊），倒着数 count 条再正序
        picked = turns[-count:] if len(turns) > count else turns
        messages = []
        seq = itertools.count(1)
        for t in picked:
            role = t.get("role") or "user"
            is_user = role == "user"
            text = str(t.get("text") or "")
            # ★ assistant 的一轮回复在 transcript 里是「多条气泡用 \n 拼起来」
            #   的。历史里必须拆回多条，否则网页端会先看到分开发的气泡，
            #   重连后又多出一条合并版（实测事故）。
            parts = [text] if is_user else [p for p in text.split("\n") if p.strip()]
            if not parts:
                parts = [text]
            base_ts = int(float(t.get("ts") or time.time()))
            n = len(parts)
            tid = int(t.get("id") or 0)
            for idx, part in enumerate(parts):
                # ★ 稳定 message_id：同一 turn 无论重连几次都返回同一个 id。
                # 多端同步靠它去重；撤回也能直接定位到 transcript.id。
                if tid:
                    mid = f"h{tid}" if n == 1 else f"h{tid}-{idx + 1}"
                else:
                    mid = str(next(self._msg_ids))
                item = {
                    "message_id": mid,
                    "real_seq": next(seq),
                    "target_id": peer_int,
                    "message_type": "private",
                    "post_type": "message",
                    # 每个气泡相差 1 秒，最后一个对齐 turn 时间；这样排序稳定
                    "time": base_ts - (n - 1 - idx),
                    "sender": {
                        "user_id": int(self.cfg.owner_id if is_user else peer_int),
                        "nickname": (self.scfg.owner_nickname if is_user
                                     else peer_name),
                    },
                    "message": [{"type": "text",
                                 "data": {"text": part}}],
                    "raw_message": part,
                }
                # ★ 引用回复：把被引用那条也带出来，刷新/多端同步后才画得出引用块
                rm = str(t.get("reply_mid") or "")
                if rm:
                    q = self._quoted_private(str(peer_id), rm)
                    if q:
                        item["reply"] = q
                messages.append(item)
        return {"messages": messages, "result": None, "echo": None}

    async def api_get_group_msg_history(
            self, params: Dict[str, Any]) -> Dict[str, Any]:
        """群历史回放。一条 gmsg 就是一条消息（不再像私聊那样按 \\n 拆）。"""
        try:
            count = int(params.get("count") or 40)
        except (TypeError, ValueError):
            count = 40
        count = max(1, min(count, 200))
        gid = str(params.get("group_id") or "")
        api = self.group_api
        if not api or not self._has_group(gid):
            return {"messages": []}
        try:
            rows = [r for r in api.group_messages(gid, count)
                    if not int(r.get("revoked") or 0)]
            levels = {str(m["user_id"]): int(m.get("level") or 1)
                      for m in api.group_detail(gid).get("members", [])}
        except Exception as e:  # noqa: BLE001
            print(f"[onebot-server] 取群历史失败：{e!r}")
            return {"messages": []}
        # 引用回复：把被引用的那条消息也带出来（昵称 + 摘要），客户端才能画引用块
        quoted: Dict[int, Dict[str, Any]] = {}
        store = None
        try:
            store = api.group_store_for(gid) if hasattr(api, "group_store_for") else None
        except Exception:  # noqa: BLE001
            store = None
        for r in rows:
            rid = int(r.get("reply_to") or 0)
            if not rid or rid in quoted:
                continue
            src = next((x for x in rows if int(x.get("id") or 0) == rid), None)
            if src is None and store is not None:
                try:
                    src = store.get_gmsg(rid)
                except Exception:  # noqa: BLE001
                    src = None
            if not src:
                continue
            qkind = str(src.get("kind") or "")
            if qkind == "user":
                qname = self.scfg.owner_nickname
            elif qkind == "system":
                qname = "系统"
            else:
                qname = str(src.get("sender_name") or "成员")
            quoted[rid] = {
                "message_id": str(src.get("mid") or f"g{rid}"),
                "name": qname,
                "text": str(src.get("text") or "")[:80].replace("\n", " "),
            }
        messages = []
        seq = itertools.count(1)
        for r in rows:
            kind = str(r.get("kind") or "")
            segs = r.get("segs") or []
            if not isinstance(segs, list) or not segs:
                segs = [{"type": "text", "data": {"text": str(r.get("text") or "")}}]
            sid = str(r.get("sender_id") or "")
            if kind == "user":
                uid, name, role = int(self.cfg.owner_id or 0), self.scfg.owner_nickname, "owner"
            elif kind == "system":
                uid, name, role = 0, "系统", "system"
            else:
                uid = int(sid) if sid.isdigit() else 0
                name = str(r.get("sender_name") or "成员")
                role = "member"
            item = {
                "message_id": str(r.get("mid") or f"g{r.get('id')}"),
                "real_seq": next(seq),
                "message_type": "group",
                "post_type": "message",
                "group_id": int(gid) if gid.isdigit() else gid,
                "time": int(float(r.get("ts") or 0)),
                "sender": {"user_id": uid, "nickname": name, "card": name,
                           "role": role, "level": levels.get(sid, 1), "title": ""},
                "message": segs,
                "raw_message": str(r.get("text") or ""),
            }
            q = quoted.get(int(r.get("reply_to") or 0))
            if q:
                item["reply"] = q
            messages.append(item)
        return {"messages": messages, "result": None, "echo": None}

    # ---------------- 群管理类 API ----------------

    def _gapi(self):
        if not self.group_api:
            raise ValueError("群聊功能不可用")
        return self.group_api

    @staticmethod
    def _gid_of(params: Dict[str, Any]) -> str:
        return str(params.get("group_id") or params.get("group") or "").strip()

    @staticmethod
    def _truthy(v: Any, default: bool = True) -> bool:
        if v is None:
            return default
        if isinstance(v, bool):
            return v
        return str(v).strip().lower() not in ("", "0", "false", "no", "none")

    async def api_get_group_info(self, params: Dict[str, Any]) -> Any:
        gid = self._gid_of(params)
        if not self._has_group(gid):
            return None
        d = self._gapi().group_detail(gid)
        return {
            "group_id": int(gid) if gid.isdigit() else 0,
            "group_name": d["group_name"],
            "member_count": d["member_count"],
            "max_member_count": 200,
            "group_create_time": 0,
            "group_level": 1,
            "group_memo": str((d.get("announce") or {}).get("text") or ""),
        }

    async def api_get_group_member_list(self, params: Dict[str, Any]) -> Any:
        gid = self._gid_of(params)
        if not self._has_group(gid):
            return []
        d = self._gapi().group_detail(gid)
        return [{
            "user_id": int(m["user_id"]) if str(m["user_id"]).isdigit() else 0,
            "nickname": m["nickname"],
            "card": m["nickname"],
            "role": m["role"],
            "level": int(m.get("level") or 1),
            "title": str(m.get("title") or ""),
            "join_time": int(float(m.get("joined_ts") or 0)),
        } for m in d.get("members", [])]

    async def api_set_group_whole_ban(self, params: Dict[str, Any]) -> None:
        """全员禁言。enable=false 解除；解除后引擎会补一次「禁言期间的 backlog」。"""
        gid = self._gid_of(params)
        if not self._has_group(gid):
            raise ValueError("没有这个群")
        on = self._truthy(params.get("enable"), default=True)
        self._gapi().set_group_mute_all(gid, on)

    async def api_set_group_kick(self, params: Dict[str, Any]) -> None:
        gid = self._gid_of(params)
        uid = str(params.get("user_id") or "").strip()
        if not self._has_group(gid) or not uid:
            raise ValueError("缺少 group_id / user_id")
        self._gapi().kick_group_member(gid, uid)

    async def api_set_group_admin(self, params: Dict[str, Any]) -> None:
        gid = self._gid_of(params)
        uid = str(params.get("user_id") or "").strip()
        if not self._has_group(gid) or not uid:
            raise ValueError("缺少 group_id / user_id")
        on = self._truthy(params.get("enable"), default=True)
        self._gapi().set_group_admin(gid, uid, on)

    async def api_set_group_name(self, params: Dict[str, Any]) -> None:
        gid = self._gid_of(params)
        name = str(params.get("group_name") or "").strip()
        if not self._has_group(gid) or not name:
            raise ValueError("缺少 group_id / group_name")
        self._gapi().rename_group(gid, name)

    async def api_send_group_notice(self, params: Dict[str, Any]) -> None:
        """发群公告（每个成员都会记一条 = 她们都看到了）。"""
        gid = self._gid_of(params)
        text = str(params.get("content") or params.get("text") or "").strip()
        if not self._has_group(gid) or not text:
            raise ValueError("缺少 group_id / content")
        self._gapi().set_group_announce(gid, text)

    async def api_get_group_notice(self, params: Dict[str, Any]) -> Any:
        gid = self._gid_of(params)
        if not self._has_group(gid):
            return []
        a = self._gapi().group_detail(gid).get("announce") or {}
        if not a.get("text"):
            return []
        return [{
            "notice_id": f"n{a.get('rev') or 1}",
            "sender_id": int(self.cfg.owner_id or 0),
            "publish_time": int(float(a.get("ts") or 0)),
            "message": {"text": str(a.get("text") or "")},
        }]

    async def api_set_group_add_request(self, params: Dict[str, Any]) -> None:
        """审批入群申请。approve=true 通过。"""
        gid = self._gid_of(params)
        uid = str(params.get("user_id") or params.get("flag") or "").strip()
        if not self._has_group(gid) or not uid:
            raise ValueError("缺少 group_id / user_id")
        approve = str(params.get("approve", True)).lower() in ("true", "1", "yes")
        self._gapi().resolve_group_request(gid, uid, approve)

    async def api_get_group_system_msg(self, _p: Dict[str, Any]) -> Any:
        return {"InvitedRequest": [], "join_requests": []}

    async def api_set_group_card(self, _p: Dict[str, Any]) -> None:
        return None

    async def api_set_group_special_title(self, _p: Dict[str, Any]) -> None:
        return None

    async def api_set_group_portrait(self, _p: Dict[str, Any]) -> None:
        return None

    async def api_upload_group_file(self, params: Dict[str, Any]) -> None:
        """群文件上传（OneBot 口子）。自托管链路里只有 base64:// 能真正落地
        —— NapCat 那种「传本地路径」在这里没有意义（文件不在服务端）。"""
        gid = self._gid_of(params)
        if not self._has_group(gid):
            raise ValueError("没有这个群")
        f = str(params.get("file") or "")
        name = str(params.get("name") or "file")
        if f.startswith("base64://"):
            try:
                blob = base64.b64decode(f[len("base64://"):])
            except Exception as e:  # noqa: BLE001
                raise ValueError(f"base64 解析失败：{e}") from e
            self._gapi().add_group_file(gid, name, blob,
                                        uploader=self.scfg.owner_nickname)
        return None

    # ---------------- 杂项 API ----------------

    async def api_get_msg(self, _p: Dict[str, Any]) -> Any:
        return None

    async def api_get_forward_msg(self, p: Dict[str, Any]) -> Any:
        """合并转发正文：客户端点开「聊天记录」卡片时调。

        返回两份形态，兼容不同客户端：
          - data.messages[*]  （Stapxs 的 NapCat pathMap 取这个）
          - data.message[*].data  （Lagrange pathMap）
        """
        fid = str(p.get("id") or p.get("message_id")
                  or p.get("resid") or "").strip()
        nodes = self._lookup_forward(fid)
        now = int(time.time())
        messages: List[Dict[str, Any]] = []
        for i, n in enumerate(nodes):
            uid = str(n.get("user_id") or "")
            content = n.get("content") if isinstance(n.get("content"), list) else []
            messages.append({
                "message_id": f"{fid}-{i + 1}" if fid else str(i + 1),
                "real_seq": i + 1,
                "target_id": 0,
                "message_type": "group",
                "post_type": "message",
                "time": int(n.get("time") or now),
                "sender": {"user_id": int(uid) if uid.isdigit() else 0,
                           "nickname": str(n.get("nickname") or "某人")},
                "message": content,
                "content": content,
                "raw_message": self._seg_flat_text(content),
            })
        return {
            "messages": messages,
            "message": [{"type": "node",
                         "data": {"user_id": str(n.get("user_id") or ""),
                                  "nickname": str(n.get("nickname") or ""),
                                  "content": n.get("content") or []}}
                        for n in nodes],
        }

    async def api_noop(self, _p: Dict[str, Any]) -> Any:
        return None

    async def api_null(self, _p: Dict[str, Any]) -> Any:
        return None

    async def api_empty_str(self, _p: Dict[str, Any]) -> str:
        return ""

    async def api_can_send(self, _p: Dict[str, Any]) -> Dict[str, Any]:
        return {"yes": True}

    async def api_get_recent_contact(self, _p: Dict[str, Any]) -> List[Dict[str, Any]]:
        """最近会话列表：每个角色一条，按最后一条消息时间倒序。"""
        out: List[Dict[str, Any]] = []
        chars = self.characters.all() if self.characters else []
        for c in chars:
            store = self.store_for(c.id) if self.store_for else self.store
            last_ts = 0.0
            last_msg = ""
            if store:
                turns = store.recent_turns(1)
                if turns:
                    last_ts = float(turns[0].get("ts") or 0)
                    text = str(turns[0].get("text") or "").split("\n")[0]
                    if text:
                        prefix = "我：" if turns[0].get("role") == "user" else ""
                        last_msg = prefix + text[:40]
            out.append({
                "peerUin": int(c.id),
                "peerName": c.name,
                "msgTime": int(last_ts) if last_ts else 0,
                "lastMsg": last_msg,
                "readTime": int(self.store.kv_get(f"last_read:{c.id}", 0))
                if self.store else 0,
                "chatType": 1,
                "senderUin": int(self.cfg.owner_id or 0),
            })
        out.sort(key=lambda x: x["msgTime"], reverse=True)
        return out

    async def api_fetch_custom_face(self, _p: Dict[str, Any]) -> List[str]:
        """收藏表情面板：把 vol 的表情包库喂给它。

        返回 HTTP URL 列表 —— 用户在客户端里就能直接翻星野的图库。
        """
        urls: List[str] = []
        if self.sticker_dir and self.sticker_dir.is_dir():
            exts = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp"}
            files = [p for p in self.sticker_dir.rglob("*")
                     if p.suffix.lower() in exts and p.is_file()]
            files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
            for p in files[:60]:
                urls.append(self.file_uri(p))
        return urls

    # ---------------- 静态文件 / 健康检查 ----------------

    async def _api_stickers(self, _request: web.Request) -> web.Response:
        """自建页面的表情包面板：按图库一级目录分组。

        url     原始文件（动图在 hover 时才加载）
        thumb   服务端生成的首帧缩略图（静态、体积小）
        animated 是否是可能带帧的格式（gif/webp）

        相对路径（/assets/stickers/...）是刻意的 —— 手机用局域网 IP
        打开页面时，绝对 URL 里的 127.0.0.1/base_url 会指向手机自己。
        """
        groups: Dict[str, List[Dict[str, Any]]] = {}
        if self.sticker_dir and self.sticker_dir.is_dir():
            exts = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp"}
            for p in sorted(self.sticker_dir.rglob("*")):
                if p.suffix.lower() not in exts or not p.is_file():
                    continue
                rel = p.relative_to(self.sticker_dir)
                key = rel.parts[0] if len(rel.parts) > 1 else "其他"
                url = f"/{_ASSET_PREFIX}/{rel.as_posix()}"
                groups.setdefault(key, []).append({
                    "url": url,
                    "thumb": self._thumb_url(rel),
                    "animated": p.suffix.lower() in (".gif", ".webp"),
                    "path": rel.as_posix(),
                    "group": key,
                })
        # 用户新建的空分类也要出现（否则建完看不见）
        for cat in self._categories:
            groups.setdefault(cat, [])
        # 自建分类排最前，「其他」（根目录散图）排最后
        ordered = sorted(
            groups.items(),
            key=lambda kv: (kv[0] != "custom", kv[0] == "其他", kv[0].lower()))
        display = {"custom": "我的表情"}
        return web.json_response({
            "groups": [
                {"key": k, "name": display.get(k, k), "items": v}
                for k, v in ordered
            ],
            "total": sum(len(v) for v in groups.values()),
        })

    # ---- 对话级表情包分类 / 自建表情维护 ----

    @staticmethod
    def _sanitize_group(name: Any) -> str:
        """分类名 → 安全的顶层文件夹名（允许中文和空格，不含路径分隔符）。"""
        s = re.sub(r'[\\/:*?"<>|\x00-\x1f]+', "_", str(name or "")).strip()
        s = s.strip(".")
        return s[:24] or "custom"

    def _load_categories(self) -> None:
        if not self.categories_path or not self.categories_path.exists():
            return
        try:
            data = json.loads(self.categories_path.read_text(encoding="utf-8"))
            if isinstance(data, list):
                self._categories = [str(x) for x in data
                                    if isinstance(x, str) and x and x != "其他"]
        except (OSError, json.JSONDecodeError) as e:
            print(f"[onebot-server] 读取表情分类失败：{e!r}")

    def _save_categories(self) -> None:
        if not self.categories_path:
            return
        try:
            self.categories_path.parent.mkdir(parents=True, exist_ok=True)
            self.categories_path.write_text(
                json.dumps(self._categories, ensure_ascii=False, indent=1),
                encoding="utf-8")
        except OSError as e:
            print(f"[onebot-server] 保存表情分类失败：{e!r}")

    async def _api_category_create(self, request: web.Request) -> web.Response:
        if not self._auth_ok(request):
            return web.json_response({"ok": False, "error": "bad access_token"},
                                     status=403)
        if not self.sticker_dir:
            return web.json_response({"ok": False, "error": "no sticker dir"},
                                     status=500)
        try:
            body = await request.json()
        except Exception:  # noqa: BLE001
            return web.json_response({"ok": False, "error": "bad json"}, status=400)
        key = self._sanitize_group(body.get("name"))
        if key == "其他":
            return web.json_response({"ok": False, "error": "分类名不可用"},
                                     status=400)
        target = self.sticker_dir / key
        if target.exists() or key in self._categories:
            return web.json_response({"ok": False, "error": "分类已存在"}, status=409)
        try:
            target.mkdir(parents=True, exist_ok=True)
        except OSError as e:  # noqa: BLE001
            return web.json_response({"ok": False, "error": str(e)}, status=500)
        self._categories.append(key)
        self._save_categories()
        print(f"[onebot-server] 新建表情分类：{key}")
        return web.json_response({"ok": True, "key": key, "name": key})

    async def _api_category_delete(self, request: web.Request) -> web.Response:
        if not self._auth_ok(request):
            return web.json_response({"ok": False, "error": "bad access_token"},
                                     status=403)
        if not self.sticker_dir:
            return web.json_response({"ok": False, "error": "no sticker dir"},
                                     status=500)
        try:
            body = await request.json()
        except Exception:  # noqa: BLE001
            return web.json_response({"ok": False, "error": "bad json"}, status=400)
        key = str(body.get("key") or "").strip()
        if not key or key == "其他" or "/" in key or "\\" in key:
            return web.json_response({"ok": False, "error": "bad category"},
                                     status=400)
        try:
            target = (self.sticker_dir / key).resolve()
            if target.parent != self.sticker_dir:
                raise ValueError("not a top-level category")
        except (ValueError, OSError):
            return web.json_response({"ok": False, "error": "bad category"},
                                     status=403)
        if not target.is_dir():
            return web.json_response({"ok": False, "error": "分类不存在"},
                                     status=404)
        exts = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp"}
        files = [p for p in target.rglob("*")
                 if p.is_file() and p.suffix.lower() in exts]
        try:
            shutil.rmtree(target)
        except OSError as e:  # noqa: BLE001
            return web.json_response({"ok": False, "error": str(e)}, status=500)
        if files:
            if self.sticker_lib is not None:
                self.sticker_lib.remove_items(files)
            else:
                path = self._index_path()
                if path and path.exists():
                    try:
                        data = json.loads(path.read_text(encoding="utf-8"))
                        wants = {str(p.resolve()) for p in files}
                        data = [d for d in data
                                if str(Path(str(d.get("file", ""))).resolve()) not in wants]
                        path.write_text(json.dumps(data, ensure_ascii=False, indent=1),
                                        encoding="utf-8")
                    except (OSError, json.JSONDecodeError) as e:  # noqa: BLE001
                        print(f"[onebot-server] 更新表情索引失败：{e!r}")
        if key in self._categories:
            self._categories.remove(key)
            self._save_categories()
        # 把分类从所有对话的可用列表里移除
        changed = False
        for peer, groups in self._sticker_sets.items():
            if key in groups:
                groups.remove(key)
                changed = True
        if changed:
            self._save_sticker_sets()
            self._apply_sticker_sources()
        print(f"[onebot-server] 删除表情分类：{key}（{len(files)} 张）")
        return web.json_response({"ok": True, "deleted": len(files)})

    def _load_sticker_sets(self) -> None:
        if not self.sets_path or not self.sets_path.exists():
            return
        try:
            data = json.loads(self.sets_path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                self._sticker_sets = {
                    str(k): [str(x) for x in v]
                    for k, v in data.items() if isinstance(v, list)
                }
        except (OSError, json.JSONDecodeError) as e:
            print(f"[onebot-server] 读取表情包分类设置失败：{e!r}")
        self._apply_sticker_sources()

    def _apply_sticker_sources(self) -> None:
        if not self.sticker_lib:
            return
        key = str(self.cfg.self_id or "")
        if key in self._sticker_sets:
            self.sticker_lib.set_allowed_sources(self._sticker_sets[key])
        else:
            self.sticker_lib.set_allowed_sources(None)

    def _save_sticker_sets(self) -> None:
        if not self.sets_path:
            return
        try:
            self.sets_path.parent.mkdir(parents=True, exist_ok=True)
            self.sets_path.write_text(
                json.dumps(self._sticker_sets, ensure_ascii=False, indent=1),
                encoding="utf-8")
        except OSError as e:
            print(f"[onebot-server] 保存表情包分类设置失败：{e!r}")

    def _index_path(self) -> Optional[Path]:
        if self.sticker_lib is not None:
            return Path(self.sticker_lib.index_path)
        if self.sticker_dir:
            return self.sticker_dir / "index.json"
        return None

    def _index_add(self, item: Dict[str, Any]) -> None:
        if self.sticker_lib is not None:
            self.sticker_lib.add_item(item)
            return
        path = self._index_path()
        if not path:
            return
        try:
            data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else []
            data.append(item)
            path.write_text(json.dumps(data, ensure_ascii=False, indent=1),
                            encoding="utf-8")
        except (OSError, json.JSONDecodeError) as e:
            print(f"[onebot-server] 更新表情索引失败：{e!r}")

    def _index_remove(self, src: Path) -> None:
        if self.sticker_lib is not None:
            self.sticker_lib.remove_item(src)
            return
        path = self._index_path()
        if not path or not path.exists():
            return
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            want = str(src.resolve())
            data = [d for d in data
                    if str(Path(str(d.get("file", ""))).resolve()) != want]
            path.write_text(json.dumps(data, ensure_ascii=False, indent=1),
                            encoding="utf-8")
        except (OSError, json.JSONDecodeError) as e:
            print(f"[onebot-server] 更新表情索引失败：{e!r}")

    async def _api_sticker_sets(self, request: web.Request) -> web.Response:
        if not self._auth_ok(request):
            return web.json_response({"ok": False, "error": "bad access_token"},
                                     status=403)
        return web.json_response({"sets": self._sticker_sets})

    async def _api_sticker_sets_save(self, request: web.Request) -> web.Response:
        if not self._auth_ok(request):
            return web.json_response({"ok": False, "error": "bad access_token"},
                                     status=403)
        try:
            body = await request.json()
        except Exception:  # noqa: BLE001
            return web.json_response({"ok": False, "error": "bad json"}, status=400)
        peer = str(body.get("peer_id") or "")
        groups = body.get("groups")
        if not peer or not isinstance(groups, list):
            return web.json_response({"ok": False, "error": "peer_id/groups"},
                                     status=400)
        self._sticker_sets[peer] = [str(g) for g in groups][:100]
        self._save_sticker_sets()
        if peer == str(self.cfg.self_id or ""):
            self._apply_sticker_sources()
        return web.json_response({"ok": True})

    async def _api_sticker_upload(self, request: web.Request) -> web.Response:
        if not self._auth_ok(request):
            return web.json_response({"ok": False, "error": "bad access_token"},
                                     status=403)
        if not self.sticker_dir:
            return web.json_response({"ok": False, "error": "no sticker dir"},
                                     status=500)
        try:
            body = await request.json()
        except Exception:  # noqa: BLE001
            return web.json_response({"ok": False, "error": "bad json"}, status=400)

        raw = str(body.get("data") or "")
        if not raw:
            return web.json_response({"ok": False, "error": "empty data"}, status=400)
        if raw.startswith("data:") and "," in raw:
            header, raw = raw.split(",", 1)
            if "base64" not in header:
                return web.json_response({"ok": False, "error": "need base64"},
                                         status=400)
        try:
            blob = base64.b64decode(raw)
        except Exception:  # noqa: BLE001
            return web.json_response({"ok": False, "error": "bad base64"},
                                     status=400)
        if len(blob) > 8 * 1024 * 1024:
            return web.json_response({"ok": False, "error": "too large"}, status=413)

        group = self._sanitize_group(body.get("group") or "custom")
        name = str(body.get("name") or "sticker")
        ext = Path(name).suffix.lower()
        if ext not in {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp"}:
            ext = ".png"
        stem = re.sub(r"[^\w\u4e00-\u9fff.-]+", "_",
                      Path(name).stem).strip("._")[:48] or "sticker"

        out_dir = self.sticker_dir / group
        out_dir.mkdir(parents=True, exist_ok=True)
        dest = out_dir / f"{stem}{ext}"
        n = 1
        while dest.exists():
            dest = out_dir / f"{stem}_{n}{ext}"
            n += 1
        try:
            dest.write_bytes(blob)
        except OSError as e:  # noqa: BLE001
            return web.json_response({"ok": False, "error": str(e)}, status=500)

        try:
            from ..sticker import normalize_emotion
            emo = normalize_emotion(stem.split("_")[0])
        except Exception:  # noqa: BLE001
            emo = "中性"
        item = {
            "file": str(dest.resolve()),
            "desc": stem.replace("_", " "),
            "emotions": [emo],
            "raw_emotion": emo,
            "tags": [group, "custom", "自建"],
            "source": group,
        }
        self._index_add(item)
        rel = dest.relative_to(self.sticker_dir)
        print(f"[onebot-server] 新增表情：{rel.as_posix()}")
        return web.json_response({
            "ok": True,
            "group": group,
            "item": {
                "url": f"/{_ASSET_PREFIX}/{rel.as_posix()}",
                "thumb": self._thumb_url(rel),
                "animated": ext in (".gif", ".webp"),
                "path": rel.as_posix(),
                "group": group,
            },
        })

    async def _api_sticker_delete(self, request: web.Request) -> web.Response:
        if not self._auth_ok(request):
            return web.json_response({"ok": False, "error": "bad access_token"},
                                     status=403)
        if not self.sticker_dir:
            return web.json_response({"ok": False, "error": "no sticker dir"},
                                     status=500)
        try:
            body = await request.json()
        except Exception:  # noqa: BLE001
            return web.json_response({"ok": False, "error": "bad json"}, status=400)
        rel = str(body.get("path") or "")
        try:
            src = (self.sticker_dir / rel).resolve()
            src.relative_to(self.sticker_dir)
        except (ValueError, OSError):
            return web.json_response({"ok": False, "error": "bad path"}, status=403)
        if not src.is_file():
            return web.json_response({"ok": False, "error": "not found"}, status=404)
        if src.suffix.lower() not in {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp"}:
            return web.json_response({"ok": False, "error": "not an image"}, status=400)
        try:
            src.unlink()
        except OSError as e:  # noqa: BLE001
            return web.json_response({"ok": False, "error": str(e)}, status=500)
        self._index_remove(src)
        print(f"[onebot-server] 删除表情：{rel}")
        return web.json_response({"ok": True})

    @staticmethod
    def _thumb_url(rel: Path) -> str:
        return "/api/sticker-thumb?p=" + quote(rel.as_posix(), safe="")

    def _thumb_cache_path(self, src: Path) -> Optional[Path]:
        if not self.thumb_dir:
            return None
        try:
            st = src.stat()
            key = f"{src}:{st.st_mtime_ns}:{st.st_size}".encode("utf-8")
        except OSError:
            return None
        name = hashlib.sha1(key).hexdigest()[:24] + ".webp"
        return self.thumb_dir / name[:2] / name

    @staticmethod
    def _make_thumb(src: Path, dest: Path, size: int = 128) -> None:
        """生成首帧缩略图（WebP）。Pillow 的阻塞操作由 to_thread 包起来。"""
        from PIL import Image  # 延迟导入：只有打开表情面板才需要

        dest.parent.mkdir(parents=True, exist_ok=True)
        with Image.open(src) as im:
            try:
                im.seek(0)
            except EOFError:
                pass
            frame = im.convert("RGBA")
            frame.thumbnail((size, size), Image.LANCZOS)
            tmp = dest.with_name(dest.name + "." + uuid.uuid4().hex + ".tmp")
            frame.save(tmp, "WEBP", quality=82, method=4)
            tmp.replace(dest)

    async def _sticker_thumb(self, request: web.Request) -> web.StreamResponse:
        rel = request.query.get("p") or ""
        if not self.sticker_dir or not rel:
            return web.Response(status=404)
        try:
            src = (self.sticker_dir / rel).resolve()
            src.relative_to(self.sticker_dir)
        except (ValueError, OSError):
            return web.Response(status=403)
        if not src.is_file():
            return web.Response(status=404)
        dest = self._thumb_cache_path(src)
        if not dest:
            return web.Response(status=500)
        if not dest.is_file():
            try:
                await asyncio.to_thread(self._make_thumb, src, dest)
            except Exception as e:  # noqa: BLE001
                print(f"[onebot-server] 生成缩略图失败 {src.name}: {e!r}")
                return web.Response(status=500)
        return web.FileResponse(dest, headers={
            "Access-Control-Allow-Origin": "*",
            "Cache-Control": "public, max-age=86400, immutable",
        })

    async def _sticker_file(self, request: web.Request) -> web.StreamResponse:
        rel = request.match_info["tail"]
        # 路径穿越防护：解析后的真实路径必须仍在图库目录内
        if not self.sticker_dir:
            return web.Response(status=404)
        try:
            base = (self.sticker_dir / rel).resolve()
            base.relative_to(self.sticker_dir)
        except (ValueError, OSError):
            return web.Response(status=403)
        if not base.is_file():
            return web.Response(status=404)
        return web.FileResponse(base, headers={
            "Access-Control-Allow-Origin": "*",
            "Cache-Control": "public, max-age=3600",
        })

    # ---------------- 全局设置 / 新增角色 ----------------

    async def _api_settings_get(self, _request: web.Request) -> web.Response:
        if not self.settings_get:
            return web.json_response({"ok": False, "error": "no settings"}, status=404)
        try:
            data = self.settings_get()
            if inspect.isawaitable(data):
                data = await data
            return web.json_response({"ok": True, **(data or {})})
        except Exception as e:  # noqa: BLE001
            return web.json_response({"ok": False, "error": str(e)}, status=500)

    async def _api_settings_post(self, request: web.Request) -> web.Response:
        if not self._auth_ok(request):
            return web.json_response({"ok": False, "error": "bad access_token"},
                                     status=403)
        if not self.settings_set:
            return web.json_response({"ok": False, "error": "no settings"}, status=404)
        try:
            body = await request.json()
        except Exception:  # noqa: BLE001
            return web.json_response({"ok": False, "error": "bad json"}, status=400)
        try:
            data = self.settings_set(body if isinstance(body, dict) else {})
            if inspect.isawaitable(data):
                data = await data
            return web.json_response({"ok": True, **(data or {})})
        except Exception as e:  # noqa: BLE001
            return web.json_response({"ok": False, "error": str(e)}, status=400)

    async def _api_character_create(self, request: web.Request) -> web.Response:
        if not self._auth_ok(request):
            return web.json_response({"ok": False, "error": "bad access_token"},
                                     status=403)
        if not self.character_creator:
            return web.json_response({"ok": False, "error": "not supported"},
                                     status=404)
        try:
            body = await request.json()
        except Exception:  # noqa: BLE001
            return web.json_response({"ok": False, "error": "bad json"}, status=400)
        name = str((body or {}).get("name") or "").strip()
        avatar = str((body or {}).get("avatar") or "").strip()
        if not name:
            return web.json_response({"ok": False, "error": "请填写角色名"},
                                     status=400)
        if len(name) > 24:
            return web.json_response({"ok": False, "error": "角色名太长（最多 24 字）"},
                                     status=400)
        if not avatar:
            return web.json_response({"ok": False, "error": "请选择头像"},
                                     status=400)
        try:
            data = self.character_creator(name, avatar)
            if inspect.isawaitable(data):
                data = await data
            return web.json_response({"ok": True, **(data or {})})
        except Exception as e:  # noqa: BLE001
            print(f"[onebot-server] 新增角色失败：{e!r}")
            return web.json_response({"ok": False, "error": str(e)}, status=400)

    # ---------------- 热情 / 好感 ----------------

    async def _api_traits_get(self, request: web.Request) -> web.Response:
        if not self.traits_get:
            return web.json_response({"ok": False, "error": "not supported"},
                                     status=404)
        peer_id = str(request.query.get("peer_id") or "").strip()
        if not peer_id:
            return web.json_response({"ok": False, "error": "缺少 peer_id"},
                                     status=400)
        try:
            data = self.traits_get(peer_id)
            if inspect.isawaitable(data):
                data = await data
            return web.json_response({"ok": True, **(data or {})})
        except Exception as e:  # noqa: BLE001
            return web.json_response({"ok": False, "error": str(e)}, status=400)

    async def _api_traits_post(self, request: web.Request) -> web.Response:
        if not self._auth_ok(request):
            return web.json_response({"ok": False, "error": "bad access_token"},
                                     status=403)
        if not self.traits_set:
            return web.json_response({"ok": False, "error": "not supported"},
                                     status=404)
        try:
            body = await request.json()
        except Exception:  # noqa: BLE001
            return web.json_response({"ok": False, "error": "bad json"}, status=400)
        body = body if isinstance(body, dict) else {}
        peer_id = str(body.get("peer_id") or "").strip()
        if not peer_id:
            return web.json_response({"ok": False, "error": "缺少 peer_id"},
                                     status=400)
        try:
            data = self.traits_set(peer_id, body.get("enthusiasm"),
                                   body.get("affection"))
            if inspect.isawaitable(data):
                data = await data
            return web.json_response({"ok": True, **(data or {})})
        except Exception as e:  # noqa: BLE001
            return web.json_response({"ok": False, "error": str(e)}, status=400)

    # ---------------- 在线状态（QQ 式） ----------------

    async def _api_presence_get(self, request: web.Request) -> web.Response:
        if not self.presence_get:
            return web.json_response({"ok": False, "error": "not supported"},
                                     status=404)
        try:
            data = self.presence_get()
            if inspect.isawaitable(data):
                data = await data
            return web.json_response({"ok": True, **(data or {})})
        except Exception as e:  # noqa: BLE001
            return web.json_response({"ok": False, "error": str(e)}, status=400)

    async def _api_presence_post(self, request: web.Request) -> web.Response:
        if not self._auth_ok(request):
            return web.json_response({"ok": False, "error": "bad access_token"},
                                     status=403)
        if not self.presence_set:
            return web.json_response({"ok": False, "error": "not supported"},
                                     status=404)
        try:
            body = await request.json()
        except Exception:  # noqa: BLE001
            return web.json_response({"ok": False, "error": "bad json"}, status=400)
        body = body if isinstance(body, dict) else {}
        status_key = str(body.get("status") or "").strip()
        if not status_key:
            return web.json_response({"ok": False, "error": "缺少 status"},
                                     status=400)
        try:
            data = self.presence_set(status_key)
            if inspect.isawaitable(data):
                data = await data
            return web.json_response({"ok": True, **(data or {})})
        except Exception as e:  # noqa: BLE001
            return web.json_response({"ok": False, "error": str(e)}, status=400)

    # ---------------- 群聊（HTTP，给自建页面与测试用） ----------------

    async def _api_groups_list(self, request: web.Request) -> web.Response:
        if not self.group_api:
            return web.json_response({"ok": False, "error": "not supported"},
                                     status=404)
        try:
            return web.json_response({
                "ok": True,
                "groups": self.group_api.groups_payload(),
                "requests": self.group_api.group_join_requests(),
            })
        except Exception as e:  # noqa: BLE001
            return web.json_response({"ok": False, "error": str(e)}, status=400)

    async def _api_groups_detail(self, request: web.Request) -> web.Response:
        if not self.group_api:
            return web.json_response({"ok": False, "error": "not supported"},
                                     status=404)
        gid = str(request.query.get("group_id") or "").strip()
        try:
            return web.json_response({"ok": True,
                                      **self.group_api.group_detail(gid)})
        except Exception as e:  # noqa: BLE001
            return web.json_response({"ok": False, "error": str(e)}, status=400)

    async def _api_groups_history(self, request: web.Request) -> web.Response:
        if not self.group_api:
            return web.json_response({"ok": False, "error": "not supported"},
                                     status=404)
        gid = str(request.query.get("group_id") or "").strip()
        try:
            count = int(request.query.get("count") or 40)
        except (TypeError, ValueError):
            count = 40
        try:
            rows = self.group_api.group_messages(gid, count)
            return web.json_response({"ok": True, "messages": rows})
        except Exception as e:  # noqa: BLE001
            return web.json_response({"ok": False, "error": str(e)}, status=400)

    async def _api_groups_create(self, request: web.Request) -> web.Response:
        if not self._auth_ok(request):
            return web.json_response({"ok": False, "error": "bad access_token"},
                                     status=403)
        if not self.group_api:
            return web.json_response({"ok": False, "error": "not supported"},
                                     status=404)
        try:
            body = await request.json()
        except Exception:  # noqa: BLE001
            return web.json_response({"ok": False, "error": "bad json"}, status=400)
        body = body if isinstance(body, dict) else {}
        try:
            data = self.group_api.create_group(
                str(body.get("name") or ""), body.get("members") or [])
            return web.json_response({"ok": True, **data})
        except Exception as e:  # noqa: BLE001
            return web.json_response({"ok": False, "error": str(e)}, status=400)

    async def _api_groups_manage(self, request: web.Request) -> web.Response:
        """一个入口管所有群操作：op 决定动作，避免十几个端点。"""
        if not self._auth_ok(request):
            return web.json_response({"ok": False, "error": "bad access_token"},
                                     status=403)
        if not self.group_api:
            return web.json_response({"ok": False, "error": "not supported"},
                                     status=404)
        try:
            body = await request.json()
        except Exception:  # noqa: BLE001
            return web.json_response({"ok": False, "error": "bad json"}, status=400)
        body = body if isinstance(body, dict) else {}
        op = str(body.get("op") or "").strip()
        gid = str(body.get("group_id") or "").strip()
        uid = str(body.get("user_id") or "").strip()
        try:
            api = self.group_api
            if op == "kick":
                data = api.kick_group_member(gid, uid)
            elif op == "admin":
                data = api.set_group_admin(gid, uid, bool(body.get("on", True)))
            elif op == "announce":
                data = api.set_group_announce(gid, str(body.get("text") or ""))
            elif op == "mute":
                data = api.set_group_mute_all(gid, bool(body.get("on", True)))
            elif op == "rename":
                data = api.rename_group(gid, str(body.get("name") or ""))
            elif op == "searchable":
                data = api.set_group_searchable(gid, bool(body.get("on", True)))
            elif op == "resolve":
                data = api.resolve_group_request(gid, uid,
                                                 bool(body.get("approve", True)))
            elif op == "invite":
                data = api.invite_group_member(gid, uid, str(body.get("name") or ""))
            elif op == "join":
                api.apply_join_group(gid, uid, str(body.get("name") or ""),
                                     str(body.get("note") or ""))
                data = api.group_detail(gid)
            elif op == "limits":
                vals = body.get("values")
                data = api.set_group_limits(gid, vals if isinstance(vals, dict) else {})
            else:
                raise ValueError(f"未知操作 {op!r}")
            return web.json_response({"ok": True, **data})
        except Exception as e:  # noqa: BLE001
            return web.json_response({"ok": False, "error": str(e)}, status=400)

    async def _api_identity(self, _request: web.Request) -> web.Response:
        """登录页要用的身份信息（连接前就能拿到）：我是谁 + 品牌名。

        登录页要显示「我」的头像，但那时还没有 WS 连接、拿不到 get_login_info，
        所以单开一个不需要鉴权的小接口。
        """
        owner = str(self.cfg.owner_id or "")
        return web.json_response({
            "ok": True,
            "owner_id": int(owner) if owner.isdigit() else 0,
            "owner_nickname": self.scfg.owner_nickname,
            "bot_nickname": self.scfg.bot_nickname,
        })

    # ---------------- 群文件 / 群相册 ----------------

    async def _api_groups_files(self, request: web.Request) -> web.Response:
        if not self.group_api:
            return web.json_response({"ok": False, "error": "not supported"},
                                     status=404)
        gid = str(request.query.get("group_id") or "").strip()
        try:
            return web.json_response({"ok": True,
                                      "files": self.group_api.group_files(gid)})
        except Exception as e:  # noqa: BLE001
            return web.json_response({"ok": False, "error": str(e)}, status=400)

    async def _api_groups_upload(self, request: web.Request) -> web.Response:
        if not self._auth_ok(request):
            return web.json_response({"ok": False, "error": "bad access_token"},
                                     status=403)
        if not self.group_api:
            return web.json_response({"ok": False, "error": "not supported"},
                                     status=404)
        try:
            body = await request.json()
        except Exception:  # noqa: BLE001
            return web.json_response({"ok": False, "error": "bad json"}, status=400)
        body = body if isinstance(body, dict) else {}
        raw = str(body.get("data") or "")
        if raw.startswith("data:") and "," in raw:
            raw = raw.split(",", 1)[1]
        try:
            blob = base64.b64decode(raw)
        except Exception:  # noqa: BLE001
            return web.json_response({"ok": False, "error": "bad base64"},
                                     status=400)
        try:
            item = self.group_api.add_group_file(
                str(body.get("group_id") or ""), str(body.get("name") or "file"),
                blob, uploader=self.scfg.owner_nickname)
            return web.json_response({"ok": True, "file": item})
        except Exception as e:  # noqa: BLE001
            return web.json_response({"ok": False, "error": str(e)}, status=400)

    async def _api_groups_file_del(self, request: web.Request) -> web.Response:
        if not self._auth_ok(request):
            return web.json_response({"ok": False, "error": "bad access_token"},
                                     status=403)
        if not self.group_api:
            return web.json_response({"ok": False, "error": "not supported"},
                                     status=404)
        try:
            body = await request.json()
        except Exception:  # noqa: BLE001
            return web.json_response({"ok": False, "error": "bad json"}, status=400)
        body = body if isinstance(body, dict) else {}
        try:
            self.group_api.remove_group_file(str(body.get("group_id") or ""),
                                             str(body.get("file_id") or ""),
                                             by=self.scfg.owner_nickname)
            return web.json_response({"ok": True})
        except Exception as e:  # noqa: BLE001
            return web.json_response({"ok": False, "error": str(e)}, status=400)

    async def _api_groups_file_get(self, request: web.Request) -> web.StreamResponse:
        if not self.group_api:
            return web.Response(status=404)
        gid = str(request.query.get("group_id") or "").strip()
        fid = str(request.query.get("file_id") or "").strip()
        path = None
        try:
            path = self.group_api.group_file_path(gid, fid)
        except Exception:  # noqa: BLE001
            path = None
        if not path:
            return web.Response(status=404)
        name = quote(path.name)
        return web.FileResponse(path, headers={
            "Cache-Control": "public, max-age=86400",
            "Content-Disposition": f"inline; filename*=UTF-8''{name}",
        })

    # ---------------- 自定义聊天头像 ----------------

    @staticmethod
    def _avatar_key(peer_id: Any) -> str:
        """头像文件名只保留安全字符，避免路径穿越。"""
        return re.sub(r"[^0-9A-Za-z_-]", "", str(peer_id or ""))[:32]

    def _avatar_url(self, key: str) -> str:
        if not self.avatar_dir:
            return ""
        try:
            st = (self.avatar_dir / f"{key}.png").stat()
        except OSError:
            return ""
        # 带 mtime 版本号：换头像后浏览器不会继续用旧缓存
        return f"/api/avatar?peer_id={quote(key)}&v={st.st_mtime_ns}"

    async def _api_avatars(self, _request: web.Request) -> web.Response:
        items: Dict[str, str] = {}
        if self.avatar_dir and self.avatar_dir.is_dir():
            for p in self.avatar_dir.glob("*.png"):
                url = self._avatar_url(p.stem)
                if url:
                    items[p.stem] = url
        return web.json_response({"ok": True, "items": items})

    async def _api_avatar_file(self, request: web.Request) -> web.StreamResponse:
        key = self._avatar_key(request.query.get("peer_id"))
        if not key or not self.avatar_dir:
            return web.Response(status=404)
        path = self.avatar_dir / f"{key}.png"
        if not path.is_file():
            return web.Response(status=404)
        return web.FileResponse(path, headers={
            "Cache-Control": "public, max-age=86400",
        })

    async def _api_avatar_save(self, request: web.Request) -> web.Response:
        if not self._auth_ok(request):
            return web.json_response({"ok": False, "error": "bad access_token"},
                                     status=403)
        if not self.avatar_dir:
            return web.json_response({"ok": False, "error": "no avatar dir"},
                                     status=500)
        try:
            body = await request.json()
        except Exception:  # noqa: BLE001
            return web.json_response({"ok": False, "error": "bad json"}, status=400)
        key = self._avatar_key(body.get("peer_id"))
        if not key:
            return web.json_response({"ok": False, "error": "bad peer_id"},
                                     status=400)

        raw = str(body.get("data") or "")
        if not raw:
            return web.json_response({"ok": False, "error": "empty data"}, status=400)
        if raw.startswith("data:") and "," in raw:
            header, raw = raw.split(",", 1)
            if "base64" not in header:
                return web.json_response({"ok": False, "error": "need base64"},
                                         status=400)
        try:
            blob = base64.b64decode(raw)
        except Exception:  # noqa: BLE001
            return web.json_response({"ok": False, "error": "bad base64"},
                                     status=400)
        if len(blob) > 4 * 1024 * 1024:
            return web.json_response({"ok": False, "error": "too large"}, status=413)

        try:
            import io

            from PIL import Image

            with Image.open(io.BytesIO(blob)) as im:
                im = im.convert("RGB")
                # 客户端已经裁成 1:1；这里兜底再裁一次并统一到 256
                if im.width != im.height:
                    side = min(im.width, im.height)
                    left = (im.width - side) // 2
                    top = (im.height - side) // 2
                    im = im.crop((left, top, left + side, top + side))
                if im.width != 256:
                    im = im.resize((256, 256), Image.LANCZOS)
                self.avatar_dir.mkdir(parents=True, exist_ok=True)
                dest = self.avatar_dir / f"{key}.png"
                tmp = dest.with_name(dest.name + "." + uuid.uuid4().hex + ".tmp")
                im.save(tmp, "PNG", optimize=True)
                tmp.replace(dest)
        except Exception as e:  # noqa: BLE001
            return web.json_response({"ok": False, "error": f"bad image: {e}"},
                                     status=400)

        print(f"[onebot-server] 更新聊天头像：{key}")
        return web.json_response({"ok": True, "url": self._avatar_url(key)})

    async def _api_avatar_delete(self, request: web.Request) -> web.Response:
        if not self._auth_ok(request):
            return web.json_response({"ok": False, "error": "bad access_token"},
                                     status=403)
        try:
            body = await request.json()
        except Exception:  # noqa: BLE001
            return web.json_response({"ok": False, "error": "bad json"}, status=400)
        key = self._avatar_key(body.get("peer_id"))
        if not key or not self.avatar_dir:
            return web.json_response({"ok": False, "error": "bad peer_id"},
                                     status=400)
        dest = self.avatar_dir / f"{key}.png"
        # 新增角色有原始头像：恢复默认 = 覆盖回原图，而不是删到只剩文字头像
        pristine = self.avatar_dir.parent / "character_avatars" / f"{key}.png"
        try:
            if pristine.is_file():
                shutil.copyfile(pristine, dest)
                print(f"[onebot-server] 恢复角色原头像：{key}")
            else:
                dest.unlink(missing_ok=True)
                print(f"[onebot-server] 恢复默认头像：{key}")
        except OSError as e:  # noqa: BLE001
            return web.json_response({"ok": False, "error": str(e)}, status=500)
        return web.json_response({"ok": True})

    async def _healthz(self, _request: web.Request) -> web.Response:
        return web.json_response({
            "ok": True, "service": "vol-onebot-server",
            "clients": len(self._clients)})
