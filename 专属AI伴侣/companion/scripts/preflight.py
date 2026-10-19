"""启动前自检：把「还没准备好」的东西一次性列出来。

用法（在 companion 目录下）：
    .venv\\Scripts\\python.exe scripts\\preflight.py

它会检查：
  1. 依赖是否装齐
  2. config.yaml 是否填了 API Key / QQ 号
  3. DeepSeek API 是否连通、模型名是否正确、**识图能力是否真的可用**
     （会发一张程序生成的测试图，验证 deepseek-flash 的多模态返回）
  4. NapCat 是否已安装、OneBot11 配置是否指向本服务、token 是否对得上
  5. 端口 6701 / 3000 / 6099 是否被占用
  6. 表情包库、搜索服务、TTS 的配置状态

退出码 0 = 全部就绪；1 = 有阻塞项。
"""
from __future__ import annotations

import asyncio
import socket
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
_HERE = Path(__file__).resolve().parent
# 直接跑 scripts/xxx.py 时，Python 会把 scripts/ 放进 sys.path[0]。
# 只要里面有跟标准库重名的文件，就会把标准库顶掉 —— 我们踩过一次：
# 曾有个 scripts/inspect.py，导致 `import inspect`（被 asyncio 依赖）拿到它而不是标准库。
# 这里先把 scripts/ 自己摘掉，杜绝这一类问题。
sys.path[:] = [p for p in sys.path if Path(p or ".").resolve() != _HERE]
sys.path.insert(0, str(ROOT))

BLOCKERS: list[str] = []
WARNINGS: list[str] = []
OKS: list[str] = []

NAPCAT_DIR = ROOT.parent.parent / "napcat"


def ok(msg: str) -> None:
    OKS.append(msg)
    print(f"  \u2713 {msg}")


def block(msg: str) -> None:
    BLOCKERS.append(msg)
    print(f"  \u2717 {msg}")


def warn(msg: str) -> None:
    WARNINGS.append(msg)
    print(f"  ! {msg}")


def port_busy(port: int, host: str = "127.0.0.1") -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        return s.connect_ex((host, port)) == 0


def find_napcat_shell() -> Path | None:
    if not NAPCAT_DIR.exists():
        return None
    for p in sorted(NAPCAT_DIR.glob("NapCat.*.Shell")):
        if (p / "napcat.bat").exists():
            return p
    return None


async def check_llm(cfg) -> None:
    from app.llm import LLM
    from app.perceive import describe_image

    llm = LLM(cfg.llm)
    try:
        txt = await llm.chat([{"role": "user", "content": "只回复两个字：在的"}],
                             max_tokens=20, retries=0)
        ok(f"DeepSeek 文本调用正常（返回：{txt.strip()[:20]}）")
    except Exception as e:  # noqa: BLE001
        block(f"DeepSeek 文本调用失败：{e}")
        await llm.close()
        return

    # 生成一张带明确形状的测试图，验证识图能力
    try:
        png = _make_test_png()
    except Exception as e:  # noqa: BLE001
        warn(f"无法生成本地测试图（跳过识图验证）：{e}")
        await llm.close()
        return

    try:
        desc = await describe_image(
            llm, png, "这张图里是什么形状？什么颜色？只回答形状和颜色，不要多说。", "image/png"
        )
        low = desc.lower()
        hit_shape = any(k in desc for k in ("圆", "圆形", "circle"))
        hit_color = any(k in desc for k in ("红", "红心", "red"))
        if desc.startswith("（图片没看成"):
            block(f"DeepSeek 识图失败：{desc}")
        elif hit_shape and hit_color:
            ok(f"DeepSeek 识图正常 —— 它看见了「红色圆形」（原话：{desc.strip()[:40]}）")
        else:
            warn(f"识图有返回但没答对（图是红色圆形，它说：{desc.strip()[:60]}）"
                 "—— 说明接口通了，但识图质量存疑，建议在真实图片上再确认")
    except Exception as e:  # noqa: BLE001
        block(f"DeepSeek 识图失败：{e}")
    finally:
        await llm.close()


def _make_test_png(size: int = 640) -> bytes:
    """手写一张 PNG（不依赖 Pillow）：白底 + 正中间一个红色实心圆。

    尺寸取 640：DeepSeek 图像侧有最小面积限制（约 295,936 px ≈ 544×544），
    太小的图会被放大甚至不被接受，测不出真实识图能力。
    """
    import struct
    import zlib

    cx = cy = size // 2
    r = size // 3
    r2 = r * r
    rows = []
    for y in range(size):
        dy2 = (y - cy) ** 2
        row = bytearray()
        for x in range(size):
            inside = (x - cx) ** 2 + dy2 <= r2
            row += b"\xd8\x28\x28" if inside else b"\xff\xff\xff"
        rows.append(b"\x00" + bytes(row))          # 每行前置 filter 字节 0
    raw = b"".join(rows)

    def chunk(tag: bytes, data: bytes) -> bytes:
        return (struct.pack(">I", len(data)) + tag + data
                + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))

    ihdr = struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0)   # 8bit truecolor
    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", ihdr)
            + chunk(b"IDAT", zlib.compress(raw, 6))
            + chunk(b"IEND", b""))


def check_napcat(cfg) -> None:
    import json

    shell = find_napcat_shell()
    if not shell:
        block(f"没找到 NapCat 安装目录（期望在 {NAPCAT_DIR} 下有 NapCat.*.Shell）")
        return
    ok(f"NapCat 已安装：{shell.name}")

    cfgdir = shell / "versions"
    onebot = None
    for v in cfgdir.glob("*"):
        p = v / "resources" / "app" / "napcat" / "config" / "onebot11.json"
        if p.exists():
            onebot = p
            break
    if not onebot:
        block("没找到 onebot11.json（NapCat 的 OneBot 配置）")
        return

    try:
        data = json.loads(onebot.read_text(encoding="utf-8"))
    except Exception as e:  # noqa: BLE001
        block(f"onebot11.json 解析失败：{e}")
        return

    net = data.get("network") or {}
    clients = net.get("websocketClients") or []
    servers = net.get("httpServers") or []

    rws = next((c for c in clients if c.get("enable")), None)
    if not rws:
        block("onebot11.json 里没有启用任何 websocketClients（反向 WS）")
    elif str(rws.get("url", "")).rstrip("/").endswith(cfg.qq.ws_path.lstrip("/")):
        ok(f"反向 WS 已指向本服务：{rws['url']}")
    else:
        warn(f"反向 WS 地址是 {rws.get('url')}，与 config.yaml 的端口/路径不一致")

    if rws and str(rws.get("token") or "") != str(cfg.qq.ws_token or ""):
        block("反向 WS 的 token 与 companion/config.yaml 的 qq.ws.access_token 不一致")
    elif rws:
        ok("反向 WS token 与伴侣服务一致")

    hs = next((s for s in servers if s.get("enable")), None)
    if not hs:
        block("onebot11.json 里没有启用任何 httpServers（主动发消息要用）")
    else:
        ok(f"HTTP 服务已启用：{hs.get('host')}:{hs.get('port')}")
        if str(hs.get("token") or "") != str(cfg.qq.http_token or ""):
            block("HTTP token 与 companion/config.yaml 的 qq.http.access_token 不一致")
        elif str(hs.get("port")) not in cfg.qq.http_base:
            warn(f"HTTP 端口 {hs.get('port')} 与 config.yaml 的 http.base_url 不一致")
        else:
            ok("HTTP token / 端口与伴侣服务一致")

    if data.get("enableLocalFile2Url") is not True:
        warn("enableLocalFile2Url 未开启，收到图片时不会附带 base64（不影响发送本地表情包）")

    if not (shell / "NapCatWinBootMain.exe").exists():
        warn("缺少 NapCatWinBootMain.exe，无法用 napcat.bat 启动")


def main() -> int:
    print("=" * 60)
    print(" 启动前自检")
    print("=" * 60)

    print("\n[1] Python 依赖")
    missing = []
    for m in ("aiohttp", "yaml"):
        try:
            __import__(m)
            ok(f"{m} 已安装")
        except ImportError:
            missing.append(m)
            block(f"缺少依赖 {m}（pip install -r requirements.txt）")

    print("\n[2] 运行配置")
    try:
        from app.config import load_config
        cfg = load_config()
        ok("config.yaml 可加载")
    except Exception as e:  # noqa: BLE001
        block(f"config.yaml 加载失败：{e}")
        return _report()

    if "待填" in cfg.llm.api_key or not cfg.llm.api_key.strip():
        block("llm.api_key 还没填")
    else:
        ok("llm.api_key 已填")
    if cfg.llm.model != "deepseek-flash":
        warn(f"llm.model = {cfg.llm.model}，建议用 deepseek-flash")

    if "待填" in cfg.qq.self_id or not cfg.qq.self_id.strip():
        block("qq.self_id（机器人 QQ 号）还没填")
    else:
        ok(f"机器人 QQ：{cfg.qq.self_id}")
    if "待填" in cfg.qq.owner_id or not cfg.qq.owner_id.strip():
        block("qq.owner_id（你自己的 QQ 号）还没填")
    else:
        ok(f"主人 QQ：{cfg.qq.owner_id}")

    print("\n[3] NapCat")
    check_napcat(cfg)

    print("\n[4] 端口占用")
    for port, what in ((cfg.qq.ws_port, "伴侣服务反向 WS"),
                       (3000, "NapCat HTTP"),
                       (6099, "NapCat WebUI")):
        if port_busy(port):
            warn(f"{port} 已被占用（{what}）——如果本服务已在运行则正常，否则要排查")
        else:
            ok(f"{port} 空闲（{what}）")

    print("\n[5] 可选功能")
    sp = str(cfg.memory.sticker_index)
    if Path(sp).exists():
        import json
        try:
            n = len(json.loads(Path(sp).read_text(encoding="utf-8")))
            ok(f"表情包库已建，共 {n} 张")
        except Exception:  # noqa: BLE001
            warn("表情包索引存在但解析失败")
    else:
        warn("表情包库未建（可选）。放图到 data/stickers 后跑 scripts/ingest_stickers.py")

    if cfg.search.provider:
        ok(f"搜索服务：{cfg.search.provider}")
    else:
        warn("搜索服务未配置（可选）。自主浏览会跳过联网，不会返回假数据")

    if cfg.tts.provider:
        ok(f"TTS：{cfg.tts.provider}")
    else:
        warn("TTS 未接入（可选）")

    print("\n[6] 大模型连通性")
    if any("llm.api_key 还没填" in b for b in BLOCKERS):
        warn("API Key 未填，跳过连通性测试")
    else:
        try:
            asyncio.run(check_llm(cfg))
        except Exception as e:  # noqa: BLE001
            block(f"连通性测试异常：{e}")

    return _report()


def _report() -> int:
    print("\n" + "=" * 60)
    print(f"通过 {len(OKS)} 项 | 警告 {len(WARNINGS)} 项 | 阻塞 {len(BLOCKERS)} 项")
    if BLOCKERS:
        print("\n需要处理：")
        for b in BLOCKERS:
            print("  ✗ " + b)
        print("\n处理完再跑一次本脚本即可。")
        return 1
    print("\n全部就绪，可以启动了。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
