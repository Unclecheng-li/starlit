"""手动弹出登录二维码窗口。

什么时候用：
  - 二维码过期了，而启动器弹的那个窗口被误关了
  - NapCat 是单独启动的（没走一键启动）
  - 换了 QQ 号要重新扫码

一般由 vol\\扫码登录.bat 调用。它跑在 companion 的 venv 里（没有 tkinter），
所以自己的活只是「找一个带 tkinter 的解释器」然后把 qr_login.py 拉起来。
"""
from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_COMPANION = _HERE.parent
sys.path[:] = [p for p in sys.path if Path(p or ".").resolve() != _HERE]
if str(_COMPANION) not in sys.path:
    sys.path.insert(0, str(_COMPANION))

from scripts.napcat_api import find_qrcode, find_tk_python, login_state  # noqa: E402

SCRIPT = _COMPANION / "scripts" / "qr_login.py"


def main() -> int:
    # --wait N：等二维码文件出现最多 N 秒（自动修复任务用长等待 ——
    # NapCat 还在启动时文件不存在，短等待会直接退出）
    wait_sec = 30
    if "--wait" in sys.argv:
        try:
            wait_sec = int(sys.argv[sys.argv.index("--wait") + 1])
        except (ValueError, IndexError):
            pass

    online, nick = login_state()
    if online:
        print(f"已经登录了（{nick or '未知昵称'}），不需要扫码。")
        print("要换号的话，先在 NapCat 窗口里退出登录，再跑一次这个。")
        return 0

    qr = find_qrcode()
    if not qr:
        print("还没找到二维码文件 —— NapCat 可能还没启动，等它出现 ...")
        deadline = time.time() + wait_sec
        while time.time() < deadline:
            time.sleep(2)
            qr = find_qrcode()
            if qr and qr.exists():
                break
        if not (qr and qr.exists()):
            print(f"等了 {wait_sec} 秒也没等到二维码文件 —— 可能已是登录状态。")
            return 1

    if qr.exists():
        print(f"二维码文件：{qr}")

    tkpy = find_tk_python()
    if not tkpy:
        print("[!] 没找到带 tkinter 的 Python，不能用自绘窗口。")
        print("    退路：直接用看图工具打开下面这个文件（但**不会自动刷新**，")
        print("    二维码过期了要重新跑一次这个脚本）：")
        print(f"    {qr}")
        return 2

    print(f"用 {tkpy} 打开二维码窗口 …")
    print("窗口会自动刷新过期的码；登录成功后自己关掉。")
    return subprocess.call([tkpy, str(SCRIPT), "--wait", str(max(30, wait_sec))],
                           cwd=str(_COMPANION))


if __name__ == "__main__":
    sys.exit(main())
