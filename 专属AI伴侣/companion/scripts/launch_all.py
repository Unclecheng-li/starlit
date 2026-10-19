"""一键启动：按顺序把三个东西拉起来，已经在跑的自动跳过。

顺序很重要：
    1. 搜索实例 SearXNG   —— vol 要靠它上网搜
    2. 伴侣服务           —— 反向 WS 服务端，NapCat 要连它
    3. QQ 通道 NapCat     —— 最后起，会弹管理员权限 + 扫码

每一步都会先探测端口，已经在跑就跳过 —— 避免「又开了一个」导致端口冲突。

关于扫码窗口的时机：NapCat 的 HTTP 接口**登录成功后才会起来**，
所以不能用「等接口应答」来决定什么时候弹二维码窗口（等不到的）。
正确姿势是 NapCat 一拉起就立刻弹窗 —— 窗口自己会等新码、自动刷新、
登录成功后自动关闭（见 qr_login.py）。

注意路径层级：本脚本在 vol/专属AI伴侣/companion/scripts/ 下。
vol 是往上 **4 层**（parents[3]）—— 少算一层就会去 专属AI伴侣/ 下面找
searxng 和 start_napcat.bat，然后找不到（这个坑真踩过）。

用法（一般由 vol\\一键启动.bat 调用）：
    .venv\\Scripts\\python.exe -m scripts.launch_all
"""
from __future__ import annotations

import glob
import os
import shutil
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]                # vol/
COMPANION = Path(__file__).resolve().parents[1]           # companion/
_HERE = Path(__file__).resolve().parent
sys.path[:] = [p for p in sys.path if Path(p or ".").resolve() != _HERE]
sys.path.insert(0, str(COMPANION))

from app.config import load_config  # noqa: E402
from scripts.napcat_api import (  # noqa: E402
    find_napcat_config, find_qrcode, find_tk_python, login_state,
)

PY = COMPANION / ".venv" / "Scripts" / "python.exe"

# Windows 命令行工具（tasklist 等）输出是控制台代码页的编码（中文系统通常是 GBK），
# 而 subprocess(text=True) 默认按 UTF-8 解 —— 会直接抛 UnicodeDecodeError。
# 我们要读的只有 PID 和 "QQ.exe" 这类 ASCII，所以用 GBK + replace 最稳。
CONSOLE_ENC = "gbk" if os.name == "nt" else "utf-8"

# 探测本机端口必须绕开系统代理：urllib 默认读 http_proxy 环境变量，
# 有代理时会把 127.0.0.1 的请求也转出去，拿回 502，于是误判成「没在跑」。
_NO_PROXY = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def probe(url: str, timeout: float = 3.0) -> bool:
    try:
        with _NO_PROXY.open(url, timeout=timeout) as r:
            return r.status == 200
    except Exception:  # noqa: BLE001
        return False


def spawn(title: str, cmd: list[str]) -> None:
    """开一个新控制台窗口跑命令。"""
    flags = getattr(subprocess, "CREATE_NEW_CONSOLE", 0)
    subprocess.Popen(cmd, creationflags=flags, cwd=str(COMPANION))
    print(f"      已在新窗口启动：{title}")


def qq_running() -> bool:
    try:
        out = subprocess.run(["tasklist", "/fi", "imagename eq QQ.exe"],
                             capture_output=True, text=True,
                             encoding=CONSOLE_ENC, errors="replace", timeout=10).stdout
        return "QQ.exe" in out
    except Exception:  # noqa: BLE001
        return False


def napcat_running() -> bool:
    """NapCat 启动器进程是否在跑。

    注意：这只说明 BootMain 进程活着，**不代表通道能用** ——
    NapCat 是注入进 QQ 进程里的，QQ 半夜自我重启会把注入弄丢，
    BootMain 却还挂着（僵尸）。通道是否真的活着要看 ws_established。
    """
    try:
        out = subprocess.run(["tasklist", "/fi", "imagename eq NapCatWinBootMain.exe"],
                             capture_output=True, text=True,
                             encoding=CONSOLE_ENC, errors="replace", timeout=10).stdout
        return "NapCatWinBootMain.exe" in out
    except Exception:  # noqa: BLE001
        return False


def ws_established(port: int) -> bool:
    """伴侣的 WS 端口上有没有一条已建立的连接 —— NapCat 真正连着才算通道活着。

    ★ 为什么必须查这个：实测 NTQQ 会夜里自我回收进程树（无崩溃记录、
    无更新痕迹），NapCat 注入随旧 QQ 进程死亡；BootMain 进程却还在 ——
    光看进程会误判「通道正常」，NapCat 永远不会再回连（新 QQ 没有注入）。
    """
    try:
        out = subprocess.run(["netstat", "-ano", "-p", "tcp"],
                             capture_output=True, text=True,
                             encoding=CONSOLE_ENC, errors="replace", timeout=20).stdout
    except Exception:  # noqa: BLE001
        return False
    for line in out.splitlines():
        parts = line.split()
        if (len(parts) >= 4 and parts[3] == "ESTABLISHED"
                and parts[1].endswith(f":{port}") and "127.0.0.1" in parts[2]):
            return True
    return False


def napcat_scope_pids() -> list:
    """vol\\napcat 目录下的 QQ / BootMain 进程 PID。

    ★ 只按**可执行文件路径**圈定 —— 用户自己的 QQ 主客户端跑在别处，
    taskkill /IM QQ.exe 那种按名字全杀的禁用，会误杀。
    """
    pat = str(ROOT / "napcat") + "*"
    ps = ("(Get-CimInstance Win32_Process "
          "-Filter \"Name='QQ.exe' or Name='NapCatWinBootMain.exe'\" "
          f"| Where-Object {{ $_.ExecutablePath -like '{pat}' }} "
          "| ForEach-Object { $_.ProcessId })")
    try:
        out = subprocess.run(["powershell", "-NoProfile", "-Command", ps],
                              capture_output=True, text=True,
                              encoding=CONSOLE_ENC, errors="replace", timeout=20).stdout.split()
        return [int(x) for x in out if x.isdigit()]
    except Exception:  # noqa: BLE001
        return []


def kill_napcat_scope() -> None:
    """停掉失联的（vol\\napcat 范围内的）QQ / BootMain，给重启腾地方。"""
    pids = napcat_scope_pids()
    for pid in pids:
        subprocess.run(["taskkill", "/PID", str(pid), "/F"],
                        capture_output=True, timeout=15)
    if pids:
        print(f"      已停掉失联进程：{pids}")
        time.sleep(3)


def qr_window_running() -> bool:
    """是否已经有一个二维码窗口在跑（防重复启动越积越多）。

    tasklist 看不到命令行，得用 PowerShell 查 Win32_Process。
    查不到（超时/异常）就当没有 —— 宁可多弹一个窗口，不能一个不弹。
    """
    ps = ("(Get-CimInstance Win32_Process -Filter \"Name like 'python%'\" "
          "| Where-Object {$_.CommandLine -like '*qr_login.py*'} "
          "| Measure-Object).Count")
    try:
        out = subprocess.run(["powershell", "-NoProfile", "-Command", ps],
                              capture_output=True, text=True,
                              encoding=CONSOLE_ENC, errors="replace",
                              timeout=20).stdout.strip()
        return out.isdigit() and int(out) > 0
    except Exception:  # noqa: BLE001
        return False


def pop_qr_window() -> bool:
    """弹出二维码登录窗口（qr_login.py：等新码出现、过期自动刷新、登录自动关）。"""
    script = COMPANION / "scripts" / "qr_login.py"
    tkpy = find_tk_python()
    if tkpy and script.exists():
        print("      已弹出二维码窗口 —— 它自己会等 NapCat 出新码；")
        print("      扫码并在手机上确认后，窗口会自动关闭")
        subprocess.Popen([tkpy, str(script), "--wait", "180"],
                         cwd=str(COMPANION),
                         creationflags=getattr(subprocess, "CREATE_NEW_CONSOLE", 0))
        return True

    # 退路：没有 tkinter 就用系统看图器打开（不会自动刷新，也不会自动关）
    qr = find_qrcode()
    if qr and qr.exists():
        print("      [注意] 没找到带 tkinter 的 Python，改用系统看图器打开二维码。")
        print("             这样**不会自动刷新过期二维码**，也**不会自动关闭**，")
        print("             看到「二维码已过期」就在 NapCat 窗口里重新触发一次登录。")
        try:
            os.startfile(str(qr))            # noqa: S606
        except Exception as e:  # noqa: BLE001
            print(f"      打开失败：{e!r}  二维码在：{qr}")
    else:
        print("      没找到二维码文件。去 NapCat 窗口看看是否需要手动触发登录。")
    return False


def ensure_login() -> None:
    """让 QQ 通道处于「已登录」状态：没登录就**立刻**弹二维码窗口。

    实测（2026-10-15 复现）：NapCat 的 HTTP 接口**要扫码登录成功后才会起来**，
    登录前怎么探测都是「没应答」。旧逻辑「先等接口 50 秒、没等到再弹窗」
    等于把扫码窗口无谓推迟一分钟 —— 用户在这段时间里看不到任何窗口，
    体感就是「启动了但没弹码」。

    所以改成：
      1. 先问一次接口（通道本来就在跑且已登录的场景，一步到位）
      2. 没登录就**立刻**弹二维码窗口（窗口自己会盯着新码出现并自动刷新）
      3. 控制台这边只做确认性轮询，报「扫码成功」的回执，不再当闸门
    """
    host, port, token = find_napcat_config()

    online, nick = login_state(host, port, token)
    if online:
        print(f"      已登录（{nick or '未知昵称'}），不需要扫码")
        return

    if qr_window_running():
        print("      还没登录 —— 二维码窗口已经开着，直接扫就行")
    else:
        pop_qr_window()

    # 确认性轮询：扫码成功后 NapCat 的接口才会起来，这时才轮得到「已登录」。
    # 只等 3 分钟，等不到也不影响 —— 二维码窗口自己会继续盯（7 分钟）并自动关。
    for i in range(90):
        time.sleep(2)
        online, nick = login_state(host, port, token)
        if online:
            print(f"      ✓ 登录成功（{nick or '未知昵称'}），QQ 通道就绪")
            return
        if i in (15, 45, 75):
            print("      还没检测到登录成功（接口要登录后才起来），二维码窗口还开着 ...")
    print("      （3 分钟内没等到登录确认 —— 窗口还在自己盯，扫完码就好）")


def main() -> int:
    cfg = load_config()
    ws_port = cfg.qq.ws_port
    searx_url = (cfg.search.endpoint or "http://127.0.0.1:8888").rstrip("/")
    # ★ onebot-server 模式：没有 QQ/NapCat，伴侣监听的是 server.port
    # （Stapxs 等客户端直连），健康检查和第 3 步都要跟着换。
    channel_kind = (getattr(cfg.qq, "channel", "napcat") or "napcat").lower()
    ob_server = channel_kind == "onebot-server"
    hb_port = cfg.qq.server.port if ob_server else ws_port

    bar = "=" * 60
    print(bar)
    print("  Vol 一键启动")
    print("  顺序：搜索实例  ->  伴侣服务  ->  "
          + ("聊天客户端指引" if ob_server else "QQ 通道"))
    print(bar)
    print()

    if not PY.exists():
        print(f"[x] 找不到虚拟环境：{PY}")
        print("    先在 companion 目录跑：python -m venv .venv && "
              ".venv\\Scripts\\pip install -r requirements.txt")
        return 1

    # ---- 1/3 搜索实例 ----
    print("[1/3] 搜索实例 SearXNG ...")
    if probe(searx_url + "/"):
        print("      已经在跑，跳过")
    else:
        spawn("Vol - 搜索", [str(PY), "-m", "scripts.run_searxng"])
        for _ in range(20):
            time.sleep(1)
            if probe(searx_url + "/"):
                break
        print("      " + ("已就绪" if probe(searx_url + "/") else "还没起来，看那个窗口的日志"))
    print()

    # ---- 2/3 伴侣服务 ----
    print("[2/3] 伴侣服务 ...")
    hb = f"http://127.0.0.1:{hb_port}/healthz"
    if probe(hb):
        print("      已经在跑，跳过")
        print("      ⚠ 如果那是之前留下的旧实例，先双击「一键停止.bat」再来一次")
    else:
        spawn("Vol - 伴侣", [str(PY), "-m", "app.main"])
        # 冷启动要加载 688 张表情包索引 + 起 WS 服务，15 秒可能不够；
        # 探测太短会误报「还没起来」，用户重复双击就会撞端口（实测）
        for _ in range(40):
            time.sleep(1)
            if probe(hb):
                break
        print("      " + ("已就绪" if probe(hb) else "还没起来，看那个窗口的日志"))
    print()

    if ob_server:
        # ---- 3/3（自托管模式）：没有 QQ，给出使用指引 ----
        print("[3/3] 聊天页面...")
        webapp = ROOT / "data" / "webclient"
        if webapp.is_dir():
            print(f"      ★ 浏览器打开 http://127.0.0.1:{cfg.qq.server.port}/ 直接聊")
            print("        手机（同一 WiFi）：http://<电脑局域网IP>:"
                  f"{cfg.qq.server.port}/")
            print("        备用旧版页面（Stapxs）：http://127.0.0.1:"
                  f"{cfg.qq.server.port}/stapxs/")
        else:
            print("      聊天页面未部署（companion/data/webclient 不存在）")
            print("      备选：浏览器打开 https://stapxs.github.io/Stapxs-QQ-Lite-2.0/")
        print("      桌面/手机客户端（可选）：GitHub Releases 下载")
        print("        https://github.com/Stapxs/Stapxs-QQ-Lite-2.0/releases")
        if not cfg.qq.server.token:
            print("      ⚠ 当前未启用鉴权 —— 只在本机/家用网络可这样，上公网前")
            print("         务必在 config.yaml 的 qq.server.token 里填一个密钥")
        print()
        print(bar)
        print("  两个窗口：Vol - 搜索 / Vol - 伴侣")
        print("  都别关。要全停就双击「一键停止.bat」")
        print(bar)
        hold()
        return 0

    # ---- 3/3 QQ 通道（含扫码登录）----
    print("[3/3] QQ 通道 NapCat 与扫码登录 ...")
    bat = ROOT / "start_napcat.bat"
    boot_up = napcat_running()
    ws_up = ws_established(ws_port)
    if boot_up and ws_up:
        print("      NapCat 通道正常（已连接），跳过启动")
    elif boot_up and not ws_up:
        # BootMain 在、但通道没连上。两种可能：
        #  ① 伴侣服务刚重启（第 2 步），NapCat 的反向 WS 正在自动重连 → 给它几秒
        #  ② QQ 半夜自我重启把注入弄丢了（僵尸通道）→ 清掉重启
        #     实测事故：NTQQ 23:29 无声回收进程树，NapCat 随旧进程死亡，
        #     BootMain 还挂着，新 QQ 没有注入 → 永远不会再回连
        reconnected = False
        for _ in range(4):
            time.sleep(3)
            if ws_established(ws_port):
                reconnected = True
                break
        if reconnected:
            print("      NapCat 自动重连成功，跳过启动")
        else:
            print("      [!] NapCat 进程在，但通道是死的（QQ 自我重启弄丢了注入）")
            print("          自动修复：停掉失联进程，重新启动 NapCat")
            kill_napcat_scope()
            if bat.exists():
                print("      启动中 —— 会弹管理员权限窗口，点「是」")
                spawn("Vol - QQ通道", ["cmd", "/c", "call", str(bat)])
            else:
                print(f"      [x] 找不到 {bat}")
    else:
        if bat.exists():
            if qq_running():
                # QQ.exe 挂着但 NapCat 没挂上 —— 多半是上次没停干净。
                # 这时候直接启动可能注入失败，但 NapCat 控制台会说明原因，
                # 二维码窗口也会继续等新码，所以照样往下走。
                print("      [!] QQ 在跑但 NapCat 没挂上 —— 建议关掉 QQ 再启动一次")
            print("      启动中 —— 会弹管理员权限窗口，点「是」")
            spawn("Vol - QQ通道", ["cmd", "/c", "call", str(bat)])
        else:
            print(f"      [x] 找不到 {bat}")
    # 登录检查是这一步的一部分：拉了 NapCat 还得让它处于已登录状态才算完成
    ensure_login()
    print()

    print(bar)
    print("  三个窗口：Vol - 搜索 / Vol - 伴侣 / Vol - QQ通道")
    print("  都别关。要全停就双击「一键停止.bat」")
    print(bar)
    hold()
    return 0


def hold() -> None:
    """等回车再关窗口。

    为什么不用 .bat 里的 pause：中文 Windows 上即使 chcp 65001，
    pause 的提示仍按原代码页输出，在 UTF-8 窗口里就是乱码。
    让 Python 打印并等待，编码才一致。
    """
    try:
        input("\n按回车键关闭这个窗口 ...")
    except (EOFError, KeyboardInterrupt):
        pass


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(0)
