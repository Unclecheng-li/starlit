"""启动 SearXNG（带 PID 记录 + 必要的环境变量）。

为什么不直接 `python -m searx.webapp`：
  1. `CURL_CA_BUNDLE` 必须指向本机根证书，否则所有引擎都报
     "SSL certificate validation failed"（这是实测踩过的坑）
  2. 要把 PID 写下来，「一键停止」才能精确地只停我们自己的进程，
     而不是粗暴地 taskkill /IM python.exe
"""
from __future__ import annotations

import os
import runpy
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]    # vol/  （往上是 4 层，别少算）
_HERE = Path(__file__).resolve().parent
sys.path[:] = [p for p in sys.path if Path(p or ".").resolve() != _HERE]

SEARX_HOME = ROOT / "searxng"
SRC = SEARX_HOME / "src"
RUN = ROOT / "run"


def main() -> None:
    if not (SRC / "searx" / "webapp.py").exists():
        print(f"[x] 找不到 SearXNG 源码：{SRC}")
        print("    应该由 vol\\start_all.bat 安装流程准备好；缺失的话需要重新 git clone。")
        sys.exit(1)

    os.environ.setdefault("CURL_CA_BUNDLE", str(SEARX_HOME / "system-ca.pem"))
    os.environ.setdefault("SEARXNG_SETTINGS_PATH", str(SEARX_HOME / "settings.yml"))

    RUN.mkdir(parents=True, exist_ok=True)
    (RUN / "searxng.pid").write_text(str(os.getpid()), encoding="ascii")

    print(f"[searx] 启动中，配置 {os.environ['SEARXNG_SETTINGS_PATH']}")
    print(f"[searx] 证书 {os.environ['CURL_CA_BUNDLE']}")
    print(f"[searx] PID {os.getpid()} 已记录到 run/searxng.pid")

    os.chdir(SRC)
    sys.path.insert(0, str(SRC))
    runpy.run_module("searx.webapp", run_name="__main__")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
