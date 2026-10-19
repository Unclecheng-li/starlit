"""感知层：情绪打标 + 图片理解。

情绪打标用**便宜快的方式**：一次 JSON 模式的 LLM 调用，拿到结构化结果。
结果不直接塞进 prompt 就完事，而是转成事件增量喂给状态机（见 state.py）。
"""
from __future__ import annotations

import base64
import hashlib
import io
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

import aiohttp

from .llm import LLM

EMOTION_SYSTEM = """你是一个情绪标注器。只输出 JSON，不要任何解释。

字段：
- label: 主要情绪，从这些里选一个最贴的：开心/平静/难过/生气/焦虑/疲惫/兴奋/温柔/感激/吃醋/依恋/中性
- intensity: 0~1，情绪强度
- valence: -1~1，情绪效价（负=不好受，正=舒服）
- arousal: 0~1，唤醒度（越高越激动）
- need: 对方此刻最想要什么，从这些里选一个：被看见/被安慰/被认可/想倾诉/想陪伴/只是闲聊/想解决问题/想安静
- quality: 0~1，这一轮互动的质量（敷衍、冷淡、冲突 → 低；投入、真诚 → 高）
- risk: 从这些里选一个：none/低落/自伤倾向/极端情绪
- note: 一句话说明判断依据（不超过 20 字）

判断依据只看文本本身，不要脑补。信息不足时宁可给「中性」。"""


async def tag_emotion(
    llm: LLM,
    text: str,
    recent: Optional[List[str]] = None,
) -> Dict[str, Any]:
    ctx = ""
    if recent:
        ctx = "最近几条对话（仅作上下文，不要标注它们）：\n" + "\n".join(recent[-6:]) + "\n\n"
    user = f"{ctx}现在要标注的这句：\n{text}"
    try:
        data = await llm.chat_json(
            [
                {"role": "system", "content": EMOTION_SYSTEM},
                {"role": "user", "content": user},
            ],
            temperature=0.2,
            max_tokens=700,
        )
    except Exception:  # noqa: BLE001 —— 打标失败不该让整轮对话崩掉
        return {
            "label": "中性", "intensity": 0.3, "valence": 0.0, "arousal": 0.3,
            "need": "只是闲聊", "quality": 0.5, "risk": "none", "note": "打标失败，回退默认值",
        }

    return {
        "label": _norm_label(data.get("label")),
        "intensity": _f(data.get("intensity"), 0.5),
        "valence": _f(data.get("valence"), 0.0),
        "arousal": _f(data.get("arousal"), 0.3),
        "need": str(data.get("need", "只是闲聊")),
        "quality": _f(data.get("quality"), 0.5),
        "risk": str(data.get("risk", "none")),
        "note": str(data.get("note", ""))[:60],
    }


# 允许的标签，用来把模型输出归一到确定值
KNOWN_LABELS = (
    "开心", "平静", "难过", "生气", "焦虑", "疲惫",
    "兴奋", "温柔", "感激", "吃醋", "依恋", "中性",
)


def _norm_label(raw: Any) -> str:
    """归一化情绪标签。

    模型偶尔会输出「中性/平淡」「开心（有点得意）」这类复合值。
    不归一化的话，EMOTION_TO_EVENT 查不到，事件会**静默失配**——
    状态机不动，但没有任何报错，很难发现。
    """
    s = str(raw or "").strip()
    if not s:
        return "中性"
    # 先试完整匹配，再试按分隔符切
    if s in KNOWN_LABELS:
        return s
    head = re.split(r"[/／、,，|（(【\s]", s)[0].strip()
    if head in KNOWN_LABELS:
        return head
    # 再退一步：看已知标签谁出现在串里（取最长匹配，避免「开心」命中「开心果」这类误判优先）
    hits = [lab for lab in KNOWN_LABELS if lab in s]
    if hits:
        return max(hits, key=len)
    return "中性"


VISION_SYSTEM = """你要读懂对方发来的图片。可能是一张表情包、梗图、截图、照片。
用中文回答，直接说图里是什么、在表达什么情绪或梗。
如果是表情包/梗图，只说明画面和它传递的情绪（调侃、无语、崩溃、卖萌……），
不要评价它适不适合收藏，也不要提"斗图/收下/存图"这类用法建议。
不要客套，不要"这张图片展示了"，直接说。控制在 60 字以内。
如果图里文字看不清，就说看不清，不要猜。"""


async def describe_image(
    llm: LLM,
    image: bytes | str,
    user_text: str = "",
    mime: str = "image/png",
    dump_dir: Optional[Path] = None,
) -> str:
    """看图。失败时**不静默**：打日志、把图落盘、换真实 mime 再试一次。

    为什么要这么啰嗦：
      - 失败原来是吞成一个字符串，真正的异常信息丢了，用户只看到
        「打不开的图」，我也没法定位
      - mime 报错时模型**不会报错**，会一本正经描述另一张图 —— 这种更坏，
        因为它会假装看见了
    """
    raw = image if isinstance(image, bytes) else b""
    real = sniff_mime(raw) if raw else ""

    # 数据本身就不完整的话，先把话说清楚 —— 报错是「unsupported image」，
    # 很容易被当成格式问题去查，实际是数据被截断了。
    if raw:
        ok, why = image_complete(raw)
        if not ok:
            print(f"[perceive] ⚠️ 图片数据不完整（{len(raw)} bytes）：{why}")
            print("[perceive]    这不是格式问题，是数据没传全 —— 报错却会说 unsupported image")
            if len(raw) == TRUNCATION_SUSPECT_BYTES:
                print(f"[perceive]    正好 {TRUNCATION_SUSPECT_BYTES} 字节，"
                      "基本可以断定是上游按 32K 块截断了。")
                print("[perceive]    不再传给模型（必被 400 拒收，还白烧一次调用）。")
                return f"（图片数据只有 {len(raw)} 字节、被截断了，看不到内容）"

    # ★ 送模型前先缩到接口能接受的尺寸。
    # 超大/超长的图会被 400 拒收，而报错说的是 "unsupported image"
    # —— 看起来像格式问题，其实是尺寸（实测 1220x19152 被拒）。
    send_data, send_mime = (raw, "") if not raw else fit_for_vision(raw)

    async def _call(m: str) -> str:
        prompt = "看看这张图，说说它是什么、想表达什么。"
        if user_text.strip():
            prompt += f"\n对方同时说的话：「{user_text.strip()}」"
        payload = send_data if send_data else image
        use_mime = m
        if send_data is not raw and send_mime:
            use_mime = send_mime          # 缩放后是 JPEG
        return (await llm.chat_with_images(prompt, [payload], system=VISION_SYSTEM,
                                           mimes=[use_mime])).strip()

    # 第一优先用嗅探出的真实类型；拿不到才用调用方给的
    first = real or mime
    if send_mime and send_data is not raw:
        first = send_mime
    elif real and real != mime:
        print(f"[perceive] mime 不符：调用方说 {mime}，实际是 {real} —— 按 {real} 发")
    try:
        out = (await _call(first)).strip()
        if not out:
            # 空回复是个坑：上层拿不到内容，就会以为「图打不开」然后自己编。
            # 这里必须给个明确的非空标记。
            print(f"[perceive] ⚠️ 模型返回了空内容（mime={first}, {len(raw)} bytes）")
            return "（图看到了，但没能描述出来）"
        return out
    except Exception as e1:  # noqa: BLE001
        print(f"[perceive] 识图失败（{first}）：{e1!r}")
        if raw and dump_dir is not None:
            try:
                d = Path(dump_dir) / "failed_images"
                d.mkdir(parents=True, exist_ok=True)
                ext = {"image/png": ".png", "image/jpeg": ".jpg", "image/gif": ".gif",
                       "image/webp": ".webp", "image/bmp": ".bmp"}.get(real, ".bin")
                h = hashlib.md5(raw).hexdigest()[:8]
                p = d / f"{h}{ext}"
                p.write_bytes(raw)
                print(f"[perceive]   图片已落盘：{p}（{len(raw)} bytes, 真实类型 {real or '未知'}）")
            except OSError as e2:
                print(f"[perceive]   落盘失败：{e2!r}")

        # 换个 mime 再试一次（有两成的失败确实是类型传错）
        alt = "image/png" if first != "image/png" else "image/jpeg"
        try:
            out = (await _call(alt)).strip()
            if not out:
                return "（图看到了，但没能描述出来）"
            print(f"[perceive] 换 {alt} 重试成功")
            return out
        except Exception as e3:  # noqa: BLE001
            print(f"[perceive] 换 {alt} 重试也失败：{e3!r}")
            return f"（图片没看成：{type(e1).__name__}: {e1}）"


def _f(v: Any, default: float) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


MAX_IMAGE_BYTES = 10 * 1024 * 1024   # NapCat 图片上限 10MB

# ── 送模型前的缩放阈值 ───────────────────────────────────────
# 实测：1220x19152（1.39MB / 23.4M 像素）被接口 400 拒收，
# 而报的还是 "unsupported image"（看不出真实原因）。
# 逐档实测下来 **4M 像素仍然正常**（甚至字也读得清）：
#     1.0M 像素 → 能读
#     1.6M 像素 → 能读（还读出了人名）
#     2.5M 像素 → 能读
#     4.0M 像素 → 能读
#    23.4M 像素 → 400 拒收
# 所以上限取 4M（已验证），别卡太小 —— 卡到 1M 会让长截图缩成
# 99x1568 那种宽度，字全糊了，等于白看。
#
# 两个上限都要：
#   - 总像素：真正的约束（长截图动辄 20M+）
#   - 最长边：兜住「很宽但不高」之类的极端情况
VV_MAX_SIDE = 8192
VV_MAX_PIXELS = 4_000_000

# 实测：NapCat 给过来的图**所有来源都只有 32768 字节且不完整**
# （PNG 无 IEND / GIF 无 0x3B，声明长度都超实际）。
# 32768 正好 32K，怀疑某处按 32K 块截断。遇到这种情况不再白费力气传给模型
# （会被 400 拒收、还浪费一次调用），而是直接把话说明白。
TRUNCATION_SUSPECT_BYTES = 32768
_EXT_MIME = {
    ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
    ".gif": "image/gif", ".webp": "image/webp", ".bmp": "image/bmp",
}

# 图片格式的「魔数」—— 开头几个字节就写死了真实类型。
# 为什么需要：QQ 给的 mime 靠不住（Content-Type 常是 octet-stream、URL 没扩展名、
# NapCat 的 file_name 可能缺失）。而 mime 报错时**模型不会报错，会描述出另一张图**
# （实测：同一张 GIF 传 image/png，模型改口说"一只猫娘被摸头"，与真实内容无关）。
# 所以按字节判定，别信声明。
_MAGIC: list[tuple[bytes, str]] = [
    (b"\x89PNG\r\n\x1a\n", "image/png"),
    (b"\xff\xd8\xff", "image/jpeg"),
    (b"GIF87a", "image/gif"),
    (b"GIF89a", "image/gif"),
    (b"BM", "image/bmp"),
]


def fit_for_vision(data: bytes) -> tuple[bytes, str]:
    """把图缩到视觉接口能接受的大小。返回 (新数据, 新 mime)。

    为什么必须做：接口对**超大/超长**的图会直接 400，报的却是
    "unsupported image"（看起来像格式问题，其实是尺寸）。
    实测 1220x19152 被拒、缩到 255x4000 就能正常识别。

    Pillow 不可用时原样返回（不因为缺依赖就把功能弄挂）。
    """
    try:
        from PIL import Image
    except ImportError:
        return data, ""
    try:
        im = Image.open(io.BytesIO(data))
        im.load()
        w, h = im.size
        if w <= 0 or h <= 0:
            return data, ""
        # 两个约束取更严的那个缩放比
        scale = 1.0
        if max(w, h) > VV_MAX_SIDE:
            scale = min(scale, VV_MAX_SIDE / float(max(w, h)))
        if w * h > VV_MAX_PIXELS:
            scale = min(scale, (VV_MAX_PIXELS / float(w * h)) ** 0.5)
        if scale >= 0.999:
            return data, ""

        nw, nh = max(1, int(w * scale)), max(1, int(h * scale))
        im = im.convert("RGB") if im.mode not in ("RGB", "L") else im
        out = im.resize((nw, nh), Image.LANCZOS)
        buf = io.BytesIO()
        out.save(buf, "JPEG", quality=85, optimize=True)
        b = buf.getvalue()
        if not b:
            return data, ""
        print(f"[perceive] 图太大，已缩放：{w}x{h} → {nw}x{nh}"
              f"（{len(data) / 1024:.0f}KB → {len(b) / 1024:.0f}KB）")
        return b, "image/jpeg"
    except Exception as e:  # noqa: BLE001
        print(f"[perceive] 缩放失败（原图照发）：{e!r}")
        return data, ""


def sniff_mime(data: bytes) -> str:
    """按文件头判真实图片类型。认不出来返回空串。"""
    if not data:
        return ""
    for magic, mime in _MAGIC:
        if data.startswith(magic):
            return mime
    # WEBP: RIFF....WEBP
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return ""


def image_complete(data: bytes) -> tuple[bool, str]:
    """判断图片数据是不是**完整的**（没有中途被截断）。

    为什么必须查这个：
      NapCat 的 `base64` 字段对大图可能只给前 32KB（实测收到一个 32768 字节的
      PNG，IHDR 声明 IDAT 有 32768 字节但文件总共就 32768 字节，连 IEND 都没有）。
      这种半截图传给模型，OpenAI 兼容接口会回 400
      "You have uploaded an unsupported image" —— 报的是**格式**问题，
      很容易被误导成 mime 传错，其实是**数据不全**。

    判定原则：**只在有确凿证据时才判为不完整**。
    认不出的格式一律放行（我们不能凭空说它坏了），避免误杀。
    """
    if not data:
        return False, "空数据"
    kind = sniff_mime(data)

    if kind == "image/png":
        # PNG 必须以 IEND 块收尾
        if b"IEND" in data[-32:] or b"IEND" in data:
            return True, ""
        # IDAT 声明的长度超过实际可读字节 → 肯定被截断
        i, need, got = 8, 0, 0
        while i + 8 <= len(data):
            ln = int.from_bytes(data[i:i + 4], "big")
            tag = data[i + 4:i + 8]
            if tag == b"IDAT":
                need += ln
                got += max(0, min(ln, len(data) - (i + 12)))
            i += 12 + ln
        if need and got < need:
            return False, f"PNG 被截断：IDAT 声明 {need} 字节，实际只有 {got} 字节"
        return False, "PNG 缺少 IEND 结束标记"

    if kind == "image/jpeg":
        if data.endswith(b"\xff\xd9"):
            return True, ""
        return False, "JPEG 缺少结束标记 FFD9（被截断）"

    if kind == "image/gif":
        if data.endswith(b"\x3b"):
            return True, ""
        return False, "GIF 缺少结束标记 0x3B（被截断）"

    if kind == "image/webp":
        if len(data) >= 8:
            declared = int.from_bytes(data[4:8], "little") + 8
            if declared > len(data):
                return False, f"WEBP 被截断：声明 {declared} 字节，实际 {len(data)}"
        return True, ""

    # 认不出的格式不拦 —— 没有证据就别乱判
    return True, ""



def _typed(data: bytes, declared: str) -> tuple[bytes, str]:
    """按字节修正 mime —— 声明的那份不可信。

    NapCat 的 file_name 可能缺失、QQ 的 Content-Type 常是 octet-stream、
    CDN 链接经常没扩展名。这三条路都会让 mime 猜错，而 mime 猜错的代价是
    **模型描述出一张完全不相干的图**（不报错，只是胡说），比失败更坏。
    """
    real = sniff_mime(data)
    if real and real != declared:
        print(f"[perceive] mime 修正：{declared or '(空)'} → {real}")
        return data, real
    return data, (real or declared or "image/png")


async def load_image(src: str) -> tuple[Optional[bytes], str]:
    """把图片 URL / 本地路径 读成 (bytes, mime)。

    为什么要自己下载而不是直接把 URL 丢给模型：
    QQ 的图片 CDN 链接常带时效签名、且部分需要 Referer，
    模型侧去取容易 403/超时。自己取一次再以 base64 传，稳得多。
    失败返回 (None, "")，调用方回退为「直接把 URL 交给模型」。
    """
    if not src:
        return None, ""

    # 磁盘上真实存在的路径（含相对路径）—— 放在最前面，最直白
    if not src.startswith(("http://", "https://", "data:", "base64://")):
        try:
            p = Path(src[8:] if src.startswith("file:///") and os.name == "nt"
                     else src[7:] if src.startswith("file://") else src)
            if p.exists() and p.is_file():
                return _typed(p.read_bytes(), _EXT_MIME.get(p.suffix.lower(), "image/png"))
        except (OSError, ValueError):
            pass

    # data: URL（NapCat 直接把本地文件读成 base64 时走这里，零网络）
    if src.startswith("data:"):
        try:
            header, b64 = src.split(",", 1)
            mime = header[5:].split(";")[0].strip() or "image/png"
            raw = base64.b64decode(b64, validate=False)
            if 0 < len(raw) <= MAX_IMAGE_BYTES:
                return _typed(raw, mime)
        except Exception as e:  # noqa: BLE001
            print(f"[perceive] data URL 解码失败：{e!r}")
        return None, ""

    # base64:// 形式
    if src.startswith("base64://"):
        try:
            raw = base64.b64decode(src[9:], validate=False)
            if 0 < len(raw) <= MAX_IMAGE_BYTES:
                return _typed(raw, "image/jpeg")
        except Exception:
            pass
        return None, ""

    # 本地文件 / file://
    if src.startswith("file://"):
        p = Path(src[8:] if src.startswith("file:///") and os.name == "nt" else src[7:])
        try:
            return _typed(p.read_bytes(), _EXT_MIME.get(p.suffix.lower(), "image/png"))
        except OSError:
            return None, ""
    if re.match(r"^[a-zA-Z]:[\\/]", src) or src.startswith("/"):
        p = Path(src)
        if p.exists():
            try:
                return _typed(p.read_bytes(), _EXT_MIME.get(p.suffix.lower(), "image/png"))
            except OSError:
                pass

    # http(s)
    if src.startswith("http://") or src.startswith("https://"):
        try:
            # 显式设 sock_connect：TCP 建连超时要可控。
            # 实测在 Windows 上连一个拒绝连接的端口，不设这个会等 2 秒才失败。
            timeout = aiohttp.ClientTimeout(total=20, sock_connect=8)
            async with aiohttp.ClientSession(timeout=timeout) as s:
                # QQ 的图片 CDN 普遍要带 Referer（和浏览器里能打开、程序里 403 同理），
                # User-Agent 用移动端 UA 更稳。
                async with s.get(src, headers={
                    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                                   "AppleWebKit/537.36 (KHTML, like Gecko) "
                                   "Chrome/120.0 Safari/537.36"),
                    "Referer": "https://im.qq.com/",
                }) as r:
                    if r.status != 200:
                        return None, ""
                    data = await r.content.read(MAX_IMAGE_BYTES + 1)
                    if len(data) > MAX_IMAGE_BYTES:
                        print(f"[perceive] 图片超过 {MAX_IMAGE_BYTES // 1024 // 1024}MB，放弃下载")
                        return None, ""
                    mime = (r.headers.get("Content-Type") or "").split(";")[0].strip()
                    if not mime.startswith("image/"):
                        guess = _EXT_MIME.get(Path(src.split("?")[0]).suffix.lower(), "")
                        mime = guess or "image/png"
                    return _typed(data, mime)
        except Exception as e:  # noqa: BLE001
            print(f"[perceive] 下载图片失败：{e!r}")
            return None, ""

    return None, ""


def to_data_url(raw: bytes, mime: str = "image/png") -> str:
    return f"data:{mime};base64,{base64.b64encode(raw).decode()}"


def _short(src: str) -> str:
    """给日志用的来源缩写，base64 别整个打出来。"""
    if src.startswith("data:"):
        return f"data URL（约 {len(src) // 1024} KB）"
    return src if len(src) <= 80 else src[:77] + "..."


def _short(src: str, n: int = 70) -> str:
    return src if len(src) <= n else src[:n - 3] + "..."


async def _napcat_get_image(file_id: str, http_base: str, http_token: str
                            ) -> tuple[Optional[bytes], str]:
    """调 NapCat 的 /get_image，用图片标识换出真实路径 / URL。

    **这是官方推荐的做法**（不是兜底）：消息里的图片段只给个 `file` 标识，
    真正取图要拿它去问 NapCat。实测这个接口给出的 `file` 是**本地完整路径**，
    `url` 是网络地址 —— 两者都比消息段里的 `base64` 可靠。

    `file` 和 `file_id` 在 NapCat 2.2.30+ 起可传同一个值，这里两个都试。
    """
    if not (file_id and http_base):
        return None, ""
    url = http_base.rstrip("/") + "/get_image"
    headers = {"Authorization": f"Bearer {http_token}"} if http_token else {}
    payload = None
    try:
        timeout = aiohttp.ClientTimeout(total=20, sock_connect=8)
        async with aiohttp.ClientSession(timeout=timeout, trust_env=False) as s:
            for key in ("file", "file_id"):
                async with s.post(url, json={key: file_id}, headers=headers) as r:
                    if r.status != 200:
                        print(f"[perceive] get_image HTTP {r.status}")
                        continue
                    data = await r.json(content_type=None)
                if isinstance(data, dict) and data.get("status") == "ok":
                    payload = data.get("data") or {}
                    break
            else:
                return None, ""
    except Exception as e:  # noqa: BLE001
        print(f"[perceive] get_image 调用失败：{e!r}")
        return None, ""

    # 返回里可能有 file(本地路径) / url(网络) / base64，逐个试
    # 顺序：本地路径 > url > base64（理由同 load_first_image）
    ordered = [payload.get("file"), payload.get("url"), payload.get("base64")]
    for idx, v in enumerate(ordered):
        v = str(v or "").strip()
        if not v:
            continue
        if idx == 2:                       # base64
            src = v if v.startswith("data:") else "base64://" + v
        else:
            src = v
        raw, mime = await load_image(src)
        if raw:
            return raw, mime
    return None, ""


async def load_first_image(candidates: List[str],
                           file_id: str = "",
                           http_base: str = "",
                           http_token: str = "") -> tuple[Optional[bytes], str, str, str]:
    """取图片，返回 (bytes, mime, 命中的来源, 失败原因)。

    ## 顺序（这是关键，之前排错了）

    查 NapCat 源码 + 官方文档后确认的**标准做法**是：
    **拿消息里的 `file`（图片标识）去调 `get_image`，换出真实路径/URL**，
    而不是去啃那个 `base64` 字段。

    之前我把顺序排成 `base64 → 本地路径 → 远程URL`，理由是「base64 零网络、
    必然可用」—— 这个假设是错的，实测它会给到被截断的数据。正确顺序：

        1. file → NapCat `get_image` 换出的路径/URL   ← 官方做法，最可靠
        2. 本地路径（file/path/url 里装的）
        3. 远程 URL
        4. base64                                     ← 最不可靠，放最后

    ## 完整性校验

    每个来源都要过 `image_complete()`。因为「取到非空数据」≠「取到完整图片」，
    而残缺图片传给模型会被 400 拒收（报错还说是格式问题，很误导）。
    不完整就继续试下一个候选。
    """
    fallback: tuple[Optional[bytes], str, str, str] = (None, "", "", "")
    fallback_len = -1

    # ---- 1) NapCat get_image（官方标准路径，优先）----
    if file_id and http_base:
        raw, mime = await _napcat_get_image(file_id, http_base, http_token)
        if raw:
            ok, why = image_complete(raw)
            tag = f"napcat/get_image ({_short(file_id)})"
            if ok:
                print(f"[perceive] get_image 拿到完整图（{len(raw)} bytes）")
                return raw, mime, tag, ""
            print(f"[perceive] get_image 拿到的也不完整（{len(raw)} bytes）：{why}")
            fallback, fallback_len = (raw, mime, tag, why), len(raw)
        else:
            print(f"[perceive] get_image 没取到（file={_short(file_id)}），"
                  "改用消息段里的候选")

    # ---- 2~4) 消息段里的候选 ----
    for i, src in enumerate(candidates, 1):
        data, mime = await load_image(src)
        if not data:
            print(f"[perceive] 候选 {i}/{len(candidates)} 取不到：{_short(src)}")
            continue

        ok, why = image_complete(data)
        tag = "base64" if src.startswith("data:") else src[:60]
        if ok:
            if i > 1 or fallback_len > 0:
                print(f"[perceive] 候选 {i}/{len(candidates)} 可用（{tag}，{len(data)} bytes）")
            return data, mime, src, ""
        print(f"[perceive] 候选 {i}/{len(candidates)} 不完整（{tag}，{len(data)} bytes）：{why}")

        if len(data) > fallback_len:
            fallback, fallback_len = (data, mime, src, why), len(data)

    if fallback[0] is not None:
        print(f"[perceive] 所有来源都不完整，拿最长的那个试（{fallback_len} bytes）：{fallback[3]}")
        return fallback

    return None, "", "", "所有候选都取不到"
