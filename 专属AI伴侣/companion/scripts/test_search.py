"""搜索 Provider 连通性自检。

用法（在 companion 目录下）：
    python -m scripts.test_search "测试关键词"

因为 app/autonomy/search.py 里的 Provider 是「按文档写的、未经实测」，
首次接入任何一家搜索服务时，先跑这个脚本确认返回结构和字段名对得上。
对不上它会打印原始响应，你照着改字段映射即可。
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
_HERE = Path(__file__).resolve().parent
# 把 scripts/ 自己从 sys.path 摘掉，避免里面的文件名顶掉标准库
sys.path[:] = [p for p in sys.path if Path(p or ".").resolve() != _HERE]
sys.path.insert(0, str(ROOT))

from app.autonomy.search import (  # noqa: E402
    NotConfigured,
    SearchResponseError,
    build_provider,
)
from app.config import load_config  # noqa: E402


async def main() -> None:
    query = sys.argv[1] if len(sys.argv) > 1 else "人工智能 最新进展"
    cfg = load_config()

    print(f"provider = {cfg.search.provider or '(未配置)'}")
    try:
        provider = build_provider(cfg.search)
    except NotConfigured as e:
        print(f"未配置：{e}")
        return

    try:
        results = await provider.search(query, n=3)
    except SearchResponseError as e:
        print("返回结构不符，请按下面原始响应核对字段：")
        print(e)
        return
    except Exception as e:  # noqa: BLE001
        print(f"请求失败：{e!r}")
        return

    print(f"\n查询：{query}\n拿到 {len(results)} 条：")
    for r in results:
        print(r.to_line())


if __name__ == "__main__":
    asyncio.run(main())
