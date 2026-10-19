"""一键停止：把 Vol 相关的**所有**进程和窗口都停下来。

原来只停「伴侣 + 搜索」两个 python（靠 PID 文件，丢了还要 psutil ——
没装就等于失效），NapCat/QQ 一律不动，最后还提示「窗口手动关」。
用户实测：窗口一个都不关，残留一堆。

现在按「路径 + 命令行」圈定后全停：
  1. python（companion venv 里的，或命令行指向 vol 目录下的脚本）
  2. cmd 窗口宿主（一键启动 / start_napcat / 自动修复这些 bat 的窗口）
  3. NapCat / QQ（只限 vol\\napcat 路径下的 —— 绝不碰用户自己的 QQ）

判活靠 PowerShell CIM（查得到命令行），不依赖 psutil、不碰 wmic。
taskkill /IM python.exe / QQ.exe 那种按名字全杀的**禁止使用**。

用法（一般由 vol\\一键停止.bat 调用）：
    .venv\\Scripts\\python.exe -m scripts.stop_all
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]    # vol/  （往上是 4 层，别少算）
_HERE = Path(__file__).resolve().parent
sys.path[:] = [p for p in sys.path if Path(p or ".").resolve() != _HERE]

RUN = ROOT / "run"

# Windows 命令行工具输出按控制台代码页（中文系统 GBK）
CONSOLE_ENC = "gbk" if os.name == "nt" else "utf-8"


def hold() -> None:
    """等回车再关窗口（不用 .bat 的 pause —— 中文提示在 UTF-8 窗口里会乱码）。"""
    try:
        input("\n按回车键关闭这个窗口 ...")
    except (EOFError, KeyboardInterrupt):
        pass


def _sweep() -> list[tuple[int, str, str]]:
    """找出所有 Vol 相关进程：[(pid, name, cmdline)]。

    圈定规则（宁可漏杀、绝不误杀）：
      - 可执行文件在 vol\\ 下（伴侣 venv 的 python、NapCat 自带的 QQ/BootMain）
      - 或 python.exe 且命令行里出现 vol\\ 路径（C:\\Python314 跑的 qr_login 之类）
      - 或 cmd.exe 且命令行里出现 vol\\ 路径（各 bat 的窗口宿主）
    用户自己的 QQ、别的项目的 python 一律不满足上述条件，不会被动。
    """
    vol = str(ROOT).replace("'", "''")
    # PS 双引号里的 TAB 是反引号 t（`t），写成 \t 会被当成字面量两字符
    ps = (
        "(Get-CimInstance Win32_Process "
        "| Where-Object { "
        f"  ($_.ExecutablePath -like '{vol}\\*') "
        f"  -or (($_.Name -like 'python*') -and ($_.CommandLine -like '*{vol}\\*')) "
        f"  -or (($_.Name -eq 'cmd.exe') -and ($_.CommandLine -like '*{vol}\\*')) "
        "} | ForEach-Object { \"$($_.ProcessId)`t$($_.Name)`t$($_.CommandLine)\" })"
    )
    try:
        r = subprocess.run(["powershell", "-NoProfile", "-Command", ps],
                           capture_output=True, text=True,
                           encoding=CONSOLE_ENC, errors="replace", timeout=30)
    except Exception:  # noqa: BLE001
        return []
    out: list[tuple[int, str, str]] = []
    for line in (r.stdout or "").splitlines():
        parts = line.split("\t")
        if len(parts) >= 2 and parts[0].strip().isdigit():
            pid = int(parts[0])
            name = parts[1].strip()
            cmd = "\t".join(parts[2:])[:120]
            out.append((pid, name, cmd))
    return out


def _kind(name: str, cmd: str) -> str:
    """给进程一个可读的分类标签。"""
    n = name.lower()
    if "python" in n:
        if "qr_login" in cmd or "show_qr" in cmd:
            return "二维码窗口"
        if "launch_all" in cmd:
            return "一键启动"
        if "searx" in cmd:
            return "搜索实例"
        if "app.main" in cmd:
            return "伴侣服务"
        return "python"
    if "qq" in n:
        return "QQ（NapCat 专用）"
    if "napcatwinbootmain" in n:
        return "NapCat 启动器"
    if n == "cmd.exe":
        return "命令行窗口"
    return name


def main() -> int:
    bar = "=" * 60
    print(bar)
    print("  Vol 一键停止（全停 + 关窗）")
    print("  范围：伴侣 / 搜索 / NapCat / QQ（bot 专用）/ 所有相关窗口")
    print("  你自己的 QQ 和别的项目不会被碰")
    print(bar)
    print()

    me = os.getpid()
    targets = [(pid, name, cmd) for pid, name, cmd in _sweep() if pid != me]
    if not targets:
        print("  没有找到在跑的 Vol 相关进程 —— 已经是干净的。")
        hold()
        return 0

    stopped, failed = 0, 0
    for pid, name, cmd in targets:
        label = _kind(name, cmd)
        try:
            r = subprocess.run(["taskkill", "/PID", str(pid), "/F"],
                               capture_output=True, timeout=15)
            if r.returncode == 0:
                stopped += 1
                print(f"  已停止 [{label}] PID {pid}")
            else:
                failed += 1
                print(f"  停止失败 [{label}] PID {pid} —— 手动关一下那个窗口")
        except Exception:  # noqa: BLE001
            failed += 1
            print(f"  停止失败 [{label}] PID {pid}")

    # 旧的 PID 记录一并清掉（下次启动会重新写）
    try:
        if RUN.exists():
            for pf in RUN.glob("*.pid"):
                pf.unlink()
    except OSError:
        pass

    print()
    print(f"  共停止 {stopped} 个进程" + (f"，{failed} 个失败" if failed else "")
          + "。所有相关窗口已随之关闭。")
    hold()
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(0)
