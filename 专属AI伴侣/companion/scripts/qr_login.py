"""QQ 登录二维码窗口：自动弹出、过期自动刷新、**登录成功后自动关闭**。

为什么不用系统看图器打开 qrcode.png：
    NapCat 的二维码**约 2 分钟就会过期**，它会重新生成同一个文件。
    系统看图器只是打开了一张静态图片，缓存不清就一直显示旧码 ——
    你一扫发现是失效的，还得自己找文件重新打开。所以这里自己画窗口，
    **监听文件变化自动重载**。

为什么用系统 Python 而不是 companion 的 venv：
    venv 里没有 tkinter（它是标准库的 C 扩展，不能 pip 装）。
    而 tkinter 只有标准库依赖，用系统 Python 跑没有副作用。
    companion 侧会自己探测哪个解释器能用（见 launch_all.py）。

单独跑：
    python scripts/qr_login.py
"""
from __future__ import annotations

import argparse
import sys
import time
import tkinter as tk
from pathlib import Path
from tkinter import font as tkfont
from typing import Optional

# 让 `from scripts.napcat_api import ...` 可用（本脚本可能用系统 Python 单独跑）。
# scripts/ 自己要从 sys.path 摘掉 —— 否则里面的文件名会顶掉标准库。
_HERE = Path(__file__).resolve().parent
_COMPANION = _HERE.parent
sys.path[:] = [p for p in sys.path if Path(p or ".").resolve() != _HERE]
if str(_COMPANION) not in sys.path:
    sys.path.insert(0, str(_COMPANION))

from scripts.napcat_api import (  # noqa: E402
    find_napcat_config, find_qrcode, login_state,
)

ZOOM = 3                      # 147px 的码在屏幕上看不清，放大 3 倍
POLL_MS = 2000                # 登录状态轮询间隔
SUCCESS_HOLD_MS = 2500        # 登录成功后窗口停留多久再关
# 超过这个秒数的码基本一定过期了。**不显示旧码** ——
# 否则用户扫到的是一个死的，只会更困惑。
STALE_SECONDS = 150
# 一直没等到登录就自己收尾。不设这个的话，窗口会无限轮询接口变成孤儿窗口。
DEFAULT_TIMEOUT_SEC = 420


# ── 窗口 ─────────────────────────────────────────────────────


class QrWindow:
    def __init__(self, qr: Path, host: str, port: int, token: str,
                 timeout_sec: int = DEFAULT_TIMEOUT_SEC) -> None:
        self.qr = qr
        self.host, self.port, self.token = host, port, token
        self.last_mtime = 0.0
        self.refresh_count = 0
        self.done = False
        self.started_at = time.time()
        self.timeout_sec = max(0, timeout_sec)

        self.root = tk.Tk()
        self.root.title("Vol · QQ 登录")
        self.root.configure(bg="#1e1f22")
        self.root.resizable(False, False)
        self.root.attributes("-topmost", True)

        pad = 18
        big = tkfont.Font(family="Microsoft YaHei UI", size=11, weight="bold")
        small = tkfont.Font(family="Microsoft YaHei UI", size=9)

        self.status = tk.Label(self.root, text="等待扫码 …", font=big,
                               fg="#e6e6e6", bg="#1e1f22")
        self.status.pack(padx=pad, pady=(pad, 6))

        # 固定大小的白色方块占位：这样没图的时候窗口也不会缩成一团、跳来跳去
        side = 147 * ZOOM
        holder = tk.Frame(self.root, width=side, height=side, bg="#ffffff")
        holder.pack(padx=pad)
        holder.pack_propagate(False)
        self.canvas = tk.Label(holder, bg="#ffffff", bd=0)
        self.canvas.pack(expand=True)

        self.hint = tk.Label(
            self.root,
            text="用手机 QQ 扫码登录 · 二维码约 2 分钟过期，会自动刷新\n"
                 "登录成功后这个窗口会自己关掉",
            font=small, fg="#9aa0a6", bg="#1e1f22", justify="center")
        self.hint.pack(padx=pad, pady=(8, 4))

        tk.Button(self.root, text="关 闭", font=small, width=10,
                  command=self.close, bg="#2b2d31", fg="#e6e6e6",
                  activebackground="#3a3d42", activeforeground="#ffffff",
                  relief="flat", bd=0).pack(pady=(0, pad))

        self._photo: Optional[tk.PhotoImage] = None
        self.reload_qr(force=True)
        self.root.after(POLL_MS, self.tick)
        self.center()
        self.root.protocol("WM_DELETE_WINDOW", self.close)

    def center(self) -> None:
        self.root.update_idletasks()
        w, h = self.root.winfo_width(), self.root.winfo_height()
        x = (self.root.winfo_screenwidth() - w) // 2
        y = max(40, (self.root.winfo_screenheight() - h) // 3)
        self.root.geometry(f"+{x}+{y}")

    def reload_qr(self, force: bool = False) -> None:
        """文件变了就重新加载 —— 这是「过期自动刷新」的关键。

        另外：**旧码不显示**。启动时目录里往往还留着上次登录留下的
        qrcode.png，那是失效的；直接显示出来会让用户扫一个死码，
        比什么都不显示更糟。所以 mtime 太老就先不画，等 NapCat 写出新的。
        """
        try:
            st = self.qr.stat()
        except OSError:
            self.status.config(text="等 NapCat 生成二维码 …", fg="#ffcc66")
            return

        age = time.time() - st.st_mtime
        if age > STALE_SECONDS:
            if self._photo is not None:            # 已显示的旧图撤掉
                self._photo = None
                self.canvas.config(image="")
            self.status.config(
                text=f"上次的码已经 {int(age / 60)} 分钟了，等 NapCat 出新码 …",
                fg="#ffcc66")
            self.hint.config(text="如果你已经登录过，NapCat 可能不需要重新扫码\n"
                                  "需要重新登录的话，去 NapCat 窗口里触发一次")
            return

        if not force and st.st_mtime == self.last_mtime:
            return
        try:
            img = tk.PhotoImage(file=str(self.qr))
        except Exception:  # 文件可能正写到一半，下轮再试
            return
        self.last_mtime = st.st_mtime
        self._photo = img.zoom(ZOOM, ZOOM)
        self.canvas.config(image=self._photo)
        self.refresh_count += 1
        if self.refresh_count > 1:
            self.status.config(text=f"二维码已刷新（第 {self.refresh_count} 次）",
                               fg="#ffcc66")
        self.center()

    def tick(self) -> None:
        if self.done:
            return
        try:
            self._tick_inner()
        except tk.TclError:
            # 窗口已经被销毁，但排队里的 after 回调又跑了一次 —— 无害，忽略即可
            self.done = True

    def _tick_inner(self) -> None:
        self.reload_qr()

        online, nick = login_state(self.host, self.port, self.token)
        if online:
            self.done = True
            who = f"（{nick}）" if nick else ""
            self.status.config(text=f"✅ 登录成功{who}，窗口即将关闭", fg="#5ddc7a")
            self.hint.config(text="可以把这个窗口忘了，它自己会关")
            self.root.after(SUCCESS_HOLD_MS, self.close)
            return

        # 等太久了就自己收尾，别变成一直在后台轮询的孤儿窗口
        waited = time.time() - self.started_at
        if self.timeout_sec and waited > self.timeout_sec:
            print(f"[qr] {int(waited)} 秒都没等到登录，先关掉窗口了。")
            print("[qr] 想继续扫码就再跑一次 vol\\扫码登录.bat")
            self.close()
            return

        if 0 < self.timeout_sec and waited > self.timeout_sec - 60:
            self.hint.config(text=f"再过 {int(self.timeout_sec - waited)} 秒就自动关掉了\n"
                                  "需要的话可以再跑一次 扫码登录.bat")
        self.root.after(POLL_MS, self.tick)

    def close(self) -> None:
        self.done = True
        try:
            self.root.destroy()
        except tk.TclError:
            pass

    def run(self) -> None:
        self.root.mainloop()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--image", default="", help="二维码路径（默认自动找）")
    ap.add_argument("--host", default="")
    ap.add_argument("--port", type=int, default=0)
    ap.add_argument("--token", default="")
    ap.add_argument("--wait", type=int, default=60,
                    help="最多等多少秒让二维码出现（默认 60）")
    ap.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT_SEC,
                    help="一直没登录的话，多少秒后自动关窗（0 = 永不超时）")
    args = ap.parse_args()

    host, port, token = find_napcat_config()
    host = args.host or host
    port = args.port or port
    token = args.token or token

    online, nick = login_state(host, port, token)
    if online:
        print(f"[qr] 已经登录了（{nick}），不需要扫码")
        return 0

    qr = Path(args.image) if args.image else find_qrcode()
    # 等二维码文件出现（NapCat 可能还没写出）
    deadline = time.time() + args.wait
    while (qr is None or not qr.exists()) and time.time() < deadline:
        time.sleep(1)
        qr = find_qrcode()

    if qr is None or not qr.exists():
        print("[qr] 没找到二维码文件，也没等到它出现。")
        print("     可能 NapCat 还没启动，或者已经是登录状态。")
        return 1

    print(f"[qr] 二维码：{qr}")
    print(f"[qr] 状态接口：http://{host}:{port}/（token {'已配置' if token else '为空'}）")
    print(f"[qr] {args.timeout} 秒内没登录的话这个窗口会自己关掉。")
    print("[qr] 窗口已打开 —— 扫码后在手机确认，窗口会自动关闭。")
    try:
        QrWindow(qr, host, port, token, timeout_sec=args.timeout).run()
    except tk.TclError as e:
        print(f"[qr] 无法创建窗口：{e}")
        return 2
    print("[qr] 窗口已关闭")
    return 0


if __name__ == "__main__":
    sys.exit(main())
