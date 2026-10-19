"""查 NapCat 的状态 / 登录信息。只依赖标准库，谁都能 import。

为什么单独一个模块：
    qr_login.py 依赖 tkinter，而 companion 的 venv 里**没有** tkinter。
    launch_all.py 跑在 venv 里，如果直接 import qr_login 会炸。
    所以把不含 GUI 依赖的这部分拆出来共用。
"""
from __future__ import annotations

import glob
import json
import os
from pathlib import Path
from typing import Optional, Tuple
from urllib.request import ProxyHandler, Request, build_opener

# 探测本机端口必须绕开系统代理（urllib 默认读 http_proxy 环境变量，
# 有代理时会把 127.0.0.1 的请求也转出去，拿回 502 → 误判成「没在跑」）
_OPENER = build_opener(ProxyHandler({}))

VOL = Path(__file__).resolve().parents[3]
NAPCAT = VOL / "napcat"


def find_napcat_config() -> Tuple[str, int, str]:
    """从 NapCat 的配置里读出 HTTP 接口的 host / port / token。

    这样 token 变了也不用改代码。
    """
    pat = str(NAPCAT / "**" / "onebot11_*.json")
    for f in sorted(glob.glob(pat, recursive=True)):
        try:
            d = json.loads(Path(f).read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        for s in (d.get("network", {}).get("httpServers") or []):
            if s.get("enable"):
                return (str(s.get("host") or "127.0.0.1"),
                        int(s.get("port") or 3000),
                        str(s.get("token") or ""))
    return ("127.0.0.1", 3000, "")


def api(host: str, port: int, token: str, action: str, timeout: float = 4.0):
    """调一个 OneBot HTTP 接口。失败返回 None（不抛异常）。"""
    req = Request(f"http://{host}:{port}/{action}")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with _OPENER.open(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8"))
    except Exception:  # noqa: BLE001
        return None


def login_state(host: str = "", port: int = 0, token: str = "") -> Tuple[bool, str]:
    """返回 (是否已登录, 昵称)。未登录或接口不可用都算 False。"""
    if not host or not port:
        host, port, token = find_napcat_config()
    st = api(host, port, token, "get_status")
    if not st or st.get("status") != "ok":
        return False, ""
    if not (st.get("data") or {}).get("online"):
        return False, ""
    info = api(host, port, token, "get_login_info")
    nick = str(((info or {}).get("data") or {}).get("nickname") or "")
    return True, nick


def find_qrcode() -> Optional[Path]:
    """当前二维码文件。版本号目录会随更新变化，所以通配找，不写死路径。

    同名文件可能有多个（旧版本目录里残留），取**最近修改**的那个。
    """
    hits = glob.glob(str(NAPCAT / "**" / "qrcode*.png"), recursive=True)
    if not hits:
        return None
    hits.sort(key=lambda p: os.path.getmtime(p) if os.path.exists(p) else 0,
              reverse=True)
    return Path(hits[0])


def find_tk_python() -> Optional[str]:
    """找一个带 tkinter 的 Python 解释器。

    为什么需要：companion 的 venv 里**没有 tkinter**（它是标准库里的 C 扩展，
    不能 pip 装），而二维码窗口要用它画。所以去系统里找一个。

    顺序：当前解释器 → PATH 上的 python → C:\\Python3* → 用户目录下的 Python3*
    """
    import shutil
    import subprocess
    import sys

    cands: list[str] = [sys.executable]
    for name in ("python", "python3"):
        p = shutil.which(name)
        if p:
            cands.append(p)
    cands += sorted(glob.glob(r"C:\Python3*\python.exe"), reverse=True)
    cands += sorted(glob.glob(os.path.expanduser(
        r"~\AppData\Local\Programs\Python\Python3*\python.exe")), reverse=True)

    seen: set[str] = set()
    for c in cands:
        if not c or c in seen:
            continue
        seen.add(c)
        try:
            r = subprocess.run([c, "-c", "import tkinter"],
                               capture_output=True, timeout=20)
            if r.returncode == 0:
                return c
        except Exception:  # noqa: BLE001
            continue
    return None
