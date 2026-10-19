"""搜索 Provider。给「自主浏览」用。

⚠️ 诚实声明：
本文件的 Provider 实现**按各家公开文档的请求/响应结构编写，但未经实测**。
原因：本项目发版时无法验证第三方搜索服务当前的线上返回格式。
所以：
  - `provider` 留空 → 直接抛 `NotConfigured`，**不会返回假数据**（默认状态）
  - 选了一家后，`search()` 会严格校验返回结构；结构不符会抛 `SearchResponseError`
    并把原始响应前 500 字打出来，方便你对着文档一眼看出字段名差异
  - 首次接入建议：跑 `python -m scripts.test_search "测试关键词"` 验证

想换别家（Bing / 谷歌 CSE / 自建 SearXNG 等），实现一个 `SearchProvider` 子类加进
`build_provider` 即可，其余代码不用动。
"""
from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import aiohttp

from ..config import SearchConfig


class NotConfigured(RuntimeError):
    """搜索服务未配置。这是默认状态，不是错误。"""


class SearchResponseError(RuntimeError):
    """返回结构与预期不符。"""


@dataclass
class SearchResult:
    title: str
    url: str
    snippet: str = ""

    def to_line(self) -> str:
        return f"- {self.title}｜{self.snippet[:120]}｜{self.url}"


class SearchProvider:
    name = "base"

    async def search(self, query: str, n: int = 5) -> List[SearchResult]:
        raise NotImplementedError


class NullProvider(SearchProvider):
    name = "null"

    async def search(self, query: str, n: int = 5) -> List[SearchResult]:
        raise NotConfigured(
            "搜索服务未配置（config.yaml 里 search.provider 为空）。\n"
            "自主浏览功能需要你选一家搜索 API：tavily / serper / bocha。\n"
            "不配置的话，digest 会跳过联网，只使用已有记忆。"
        )


class TavilyProvider(SearchProvider):
    name = "tavily"
    ENDPOINT = "https://api.tavily.com/search"

    def __init__(self, api_key: str):
        self.api_key = api_key

    async def search(self, query: str, n: int = 5) -> List[SearchResult]:
        payload = {"api_key": self.api_key, "query": query, "max_results": n}
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=30)) as s:
            async with s.post(self.ENDPOINT, json=payload) as r:
                raw = await r.text()
                if r.status != 200:
                    raise SearchResponseError(f"tavily HTTP {r.status}: {raw[:500]}")
                data = _load(raw, "tavily")
        items = data.get("results")
        if not isinstance(items, list):
            raise SearchResponseError(f"tavily 响应缺少 results 字段：{raw[:500]}")
        return [
            SearchResult(
                title=str(it.get("title", "")),
                url=str(it.get("url", "")),
                snippet=str(it.get("content", ""))[:400],
            )
            for it in items
        ]


class SerperProvider(SearchProvider):
    name = "serper"
    ENDPOINT = "https://google.serper.dev/search"

    def __init__(self, api_key: str):
        self.api_key = api_key

    async def search(self, query: str, n: int = 5) -> List[SearchResult]:
        headers = {"X-API-KEY": self.api_key, "Content-Type": "application/json"}
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=30)) as s:
            async with s.post(self.ENDPOINT, json={"q": query, "num": n}, headers=headers) as r:
                raw = await r.text()
                if r.status != 200:
                    raise SearchResponseError(f"serper HTTP {r.status}: {raw[:500]}")
                data = _load(raw, "serper")
        items = data.get("organic")
        if not isinstance(items, list):
            raise SearchResponseError(f"serper 响应缺少 organic 字段：{raw[:500]}")
        return [
            SearchResult(
                title=str(it.get("title", "")),
                url=str(it.get("link", "")),
                snippet=str(it.get("snippet", ""))[:400],
            )
            for it in items
        ]


class BochaProvider(SearchProvider):
    name = "bocha"
    ENDPOINT = "https://api.bochaai.com/v1/web-search"

    def __init__(self, api_key: str):
        self.api_key = api_key

    async def search(self, query: str, n: int = 5) -> List[SearchResult]:
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        payload = {"query": query, "count": n, "summary": True}
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=30)) as s:
            async with s.post(self.ENDPOINT, json=payload, headers=headers) as r:
                raw = await r.text()
                if r.status != 200:
                    raise SearchResponseError(f"bocha HTTP {r.status}: {raw[:500]}")
                data = _load(raw, "bocha")
        try:
            items = data["data"]["webPages"]["value"]
        except (KeyError, TypeError):
            raise SearchResponseError(f"bocha 响应结构不符（期望 data.webPages.value）：{raw[:500]}")
        return [
            SearchResult(
                title=str(it.get("name", "")),
                url=str(it.get("url", "")),
                snippet=str(it.get("snippet", ""))[:400],
            )
            for it in items[:n]
        ]


class GoogleCseProvider(SearchProvider):
    """Google Custom Search JSON API。

    唯一一条**有免费额度**的路：每天 100 次查询免费，超出才计费。
    需要两个值：API key 和搜索引擎 ID(cx)。见文末说明。
    响应结构：items[{title, link, snippet}]
    """

    name = "google"
    ENDPOINT = "https://www.googleapis.com/customsearch/v1"

    def __init__(self, api_key: str, cx: str = ""):
        self.api_key = api_key
        self.cx = cx

    async def search(self, query: str, n: int = 5) -> List[SearchResult]:
        if not self.cx:
            raise NotConfigured(
                "google 需要 search.cx（搜索引擎 ID）。\n"
                "去 https://programmablesearchengine.google.com/ 建一个"
                "「搜索整个网络」的引擎，把它的 cx 填进 config.yaml 的 search.cx。"
            )
        params = {"key": self.api_key, "cx": self.cx, "q": query,
                  "num": max(1, min(10, n))}
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=30)) as s:
            async with s.get(self.ENDPOINT, params=params) as r:
                raw = await r.text()
                if r.status != 200:
                    raise SearchResponseError(f"google HTTP {r.status}: {raw[:500]}")
                data = _load(raw, "google")
        items = data.get("items")
        if items is None:
            # 没有结果时 Google 不返回 items 字段，这不是错误
            return []
        if not isinstance(items, list):
            raise SearchResponseError(f"google 响应 items 不是数组：{raw[:500]}")
        return [
            SearchResult(
                title=str(it.get("title", "")),
                url=str(it.get("link", "")),
                snippet=str(it.get("snippet", ""))[:400],
            )
            for it in items
        ]


class SearxProvider(SearchProvider):
    """SearXNG —— **完全免 key** 的那条路。

    SearXNG 是开源的元搜索引擎：它自己去聚合 Google / Bing / 百度等的结果，
    再暴露一个本地 HTTP JSON 接口给我们。因为是自己的服务，所以不需要任何密钥。

    前提：你得自己跑一个实例，并且它的 settings.yml 里开着 json 格式。
    响应结构：{"results": [{"title", "url", "content"}]}
    """

    name = "searx"

    def __init__(self, endpoint: str):
        self.endpoint = (endpoint or "").rstrip("/")

    async def search(self, query: str, n: int = 5) -> List[SearchResult]:
        if not self.endpoint:
            raise NotConfigured(
                "searx 需要 search.endpoint，指向你自己跑的 SearXNG 地址，"
                "例如 http://127.0.0.1:8888"
            )
        url = self.endpoint + "/search"
        params = {"q": query, "format": "json", "language": "zh-CN"}
        # 本机地址必须绕开系统代理：否则环境里的 http_proxy 会把请求劫走，
        # 代理再回头连 127.0.0.1 就是「连接被拒绝」。
        local = any(h in self.endpoint for h in
                    ("127.0.0.1", "localhost", "0.0.0.0", "[::1]"))
        try:
            async with aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=30),
                trust_env=not local,
            ) as s:
                async with s.get(url, params=params) as r:
                    raw = await r.text()
                    if r.status != 200:
                        raise SearchResponseError(f"searx HTTP {r.status}: {raw[:300]}")
        except aiohttp.ClientConnectorError as e:
            raise NotConfigured(
                f"连不上 SearXNG（{self.endpoint}）：{e}\n"
                "确认实例已经在跑，且地址/端口填对。"
            ) from e

        # 不走通用 _load：SearXNG 最常见的失败是「没开 json 格式」，
        # 那时返回的是 HTML，要给针对性的提示而不是一句 "不是 JSON"。
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            raise SearchResponseError(
                "searx 返回的不是 JSON —— 通常是因为实例没开 json 输出格式。\n"
                "修法：打开 SearXNG 的 settings.yml，在 search 段里加一行\n"
                "    formats:\n      - html\n      - json\n"
                "然后重启实例。\n"
                f"（原始响应前 200 字：{raw[:200]}）"
            ) from None

        items = data.get("results")
        if not isinstance(items, list):
            raise SearchResponseError(
                f"searx 响应缺少 results 字段：{raw[:300]}\n"
                "★ 最常见原因：SearXNG 的 settings.yml 里没开 json 格式。"
                "加上：search: formats: [html, json] 然后重启实例。"
            )

        return [
            SearchResult(
                title=str(it.get("title", "")),
                url=str(it.get("url", "")),
                snippet=str(it.get("content") or it.get("snippet") or "")[:400],
            )
            for it in items[:n]
        ]


def _load(raw: str, who: str) -> Dict[str, Any]:
    try:
        return json.loads(raw)
    except json.JSONDecodeError as e:
        raise SearchResponseError(f"{who} 返回的不是 JSON：{e}｜{raw[:300]}") from e


def build_provider(cfg: SearchConfig) -> SearchProvider:
    p = (cfg.provider or "").strip().lower()
    if not p:
        return NullProvider()
    # searx 不需要 key，先于 key 校验处理
    if p == "searx":
        return SearxProvider(getattr(cfg, "endpoint", "") or "")
    if not cfg.api_key:
        raise NotConfigured(f"search.provider = {p}，但 search.api_key 为空。")
    if p == "google":
        return GoogleCseProvider(cfg.api_key, getattr(cfg, "cx", "") or "")
    table = {
        "tavily": TavilyProvider,
        "serper": SerperProvider,
        "bocha": BochaProvider,
    }
    if p not in table:
        raise NotConfigured(
            f"未知的搜索 provider：{p}"
            "（可选：searx / google / tavily / serper / bocha）"
        )
    return table[p](cfg.api_key)
