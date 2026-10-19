"""三层记忆：画像 / 情节 / 情绪。

关于向量：这里**没有**调用外部 embedding API（DeepSeek 当前不提供 embedding 接口）。
用的是一个本地的字符 n-gram 哈希向量（256 维，L2 归一化）。
它的检索质量不如真正的 embedding 模型，但：
  - 零依赖、零成本、完全离线
  - 对「短句 + 中文关键词」这类记忆条目够用
  - 接口是 `embed(text) -> list[float]`，以后想换真 embedding 只改这一个函数
"""
from __future__ import annotations

import hashlib
import math
import re
import time
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from .store import Store

DIM = 256
_TOKEN_RE = re.compile(r"[\u4e00-\u9fff]|[a-zA-Z0-9]+")


def _tokens(text: str) -> List[str]:
    """中文按字、英文数字按词，再补一层中文 bigram。"""
    units = _TOKEN_RE.findall(text.lower())
    grams = list(units)
    for i in range(len(units) - 1):
        grams.append(units[i] + units[i + 1])
    return grams


def embed(text: str) -> List[float]:
    vec = [0.0] * DIM
    for g in _tokens(text):
        h = int(hashlib.blake2b(g.encode("utf-8"), digest_size=4).hexdigest(), 16)
        idx = h % DIM
        sign = 1.0 if (h >> 31) & 1 == 0 else -1.0
        vec[idx] += sign
    norm = math.sqrt(sum(v * v for v in vec))
    if norm > 0:
        vec = [v / norm for v in vec]
    return vec


def cosine(a: Iterable[float], b: Iterable[float]) -> float:
    return sum(x * y for x, y in zip(a, b))


class Memory:
    def __init__(self, store: Store, interests_file: Optional[Path] = None):
        self.store = store
        self.interests_file = interests_file
        self._seed_interests()

    # ---------- 画像 ----------
    def set_profile(self, key: str, value: str) -> None:
        if not key or not value:
            return
        self.store.profile_set(key.strip(), value.strip())

    def profile(self) -> Dict[str, str]:
        return self.store.profile_all()

    def profile_text(self, limit: int = 40) -> str:
        p = self.profile()
        if not p:
            # 返回空串而不是占位文案 —— 表达通道会整段跳过，
            # 不留一段「还没有画像」的空话干扰模型。
            return ""
        items = list(p.items())[:limit]
        return "\n".join(f"- {k}：{v}" for k, v in items)

    # ---------- 关于自己的事实（跨会话人设一致性的地基） ----------
    SELF_FACT_KEY = "self_facts"

    def set_self_fact(self, key: str, value: str) -> None:
        """固化一条「关于我自己的事实/承诺」。

        对方分析出的（比如「我答应过明天叫他起床」）和表达时自己
        说出口的承诺都会落到这里。下次说话时注入给表达通道，
        防止出现「上午答应的事下午全忘」的人设断裂。
        """
        k, v = (key or "").strip(), (value or "").strip()
        if not k or not v:
            return
        facts = self.store.kv_get(self.SELF_FACT_KEY) or {}
        facts[k] = v
        self.store.kv_set(self.SELF_FACT_KEY, facts)

    def self_facts(self) -> Dict[str, str]:
        return dict(self.store.kv_get(self.SELF_FACT_KEY) or {})

    def self_facts_text(self, limit: int = 20) -> str:
        """给表达通道看的文本形态。新落的事实排前面（更相关）。"""
        facts = self.self_facts()
        if not facts:
            return ""
        items = list(facts.items())[-limit:]
        return "\n".join(f"- {k}：{v}" for k, v in items)

    # ---------- 情节 / 情绪 ----------
    def add_episodic(self, text: str, emotion: Optional[Dict[str, Any]] = None,
                     importance: float = 0.5, weight: float = 1.0) -> None:
        self.store.add_memory(text, embed(text), kind="episodic",
                              emotion=emotion, weight=weight)
        self.store.add_event(text, kind="episodic", emotion=emotion,
                             importance=importance)

    def add_emotional(self, text: str, emotion: Dict[str, Any],
                      weight: float = 1.0) -> None:
        self.store.add_memory(text, embed(text), kind="emotional",
                              emotion=emotion, weight=weight)

    def add_semantic(self, text: str) -> None:
        self.store.add_memory(text, embed(text), kind="semantic")

    def recall(self, query: str, top_k: int = 6) -> List[Dict[str, Any]]:
        q = embed(query)
        scored: List[Tuple[float, Dict[str, Any]]] = []
        for m in self.store.all_memories():
            base = cosine(q, m["vec"])
            # 时间衰减 + 重要度加权：久远的记忆需要更相关才能被取到
            age_days = (time.time() - m["ts"]) / 86400.0
            recency = math.exp(-age_days / 60.0)
            score = base * (0.65 + 0.35 * recency) * (0.7 + 0.3 * float(m.get("weight") or 1.0))
            scored.append((score, m))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [{**m, "score": round(s, 4)} for s, m in scored[:top_k] if s > 0.05]

    def recall_text(self, query: str, top_k: int = 6) -> str:
        hits = self.recall(query, top_k)
        if not hits:
            return "（没有检索到相关记忆）"
        lines = []
        for h in hits:
            when = time.strftime("%m-%d", time.localtime(h["ts"]))
            emo = ""
            if h.get("emotion"):
                emo = f"［情绪：{h['emotion'].get('label', '')}］"
            lines.append(f"- [{when}]（{h['kind']}）{h['text']}{emo}")
        return "\n".join(lines)

    # ---------- 兴趣（驱动自主浏览） ----------
    INTEREST_KEY = "interest_terms"

    def _seed_interests(self) -> None:
        """从 interests.md 播种初始兴趣词。

        只取**标题里含「兴趣」的小节**下的条目。
        早先的版本把文件里所有 `- ` 开头的行都收进来，
        结果把「## 自主浏览配置」下的
        「频率：每天 1~2 次」「每次取 3~5 条候选」也当成兴趣词，
        会让自主浏览去搜这些配置文本。
        """
        terms = self.store.kv_get(self.INTEREST_KEY) or {}
        if terms:
            return
        f = self.interests_file
        if not f or not f.exists():
            return

        in_interest_section = False
        for line in f.read_text(encoding="utf-8").splitlines():
            s = line.strip()
            if s.startswith("#"):
                in_interest_section = "兴趣" in s
                continue
            if in_interest_section and s.startswith("- "):
                term = s[2:].strip()
                if term:
                    terms[term] = 1.0
        self.store.kv_set(self.INTEREST_KEY, terms)

    def interests(self) -> Dict[str, float]:
        return self.store.kv_get(self.INTEREST_KEY) or {}

    def bump_interest(self, term: str, delta: float = 1.0) -> None:
        terms = self.interests()
        terms[term] = round(terms.get(term, 0.0) + delta, 3)
        self.store.kv_set(self.INTEREST_KEY, terms)

    def top_interests(self, n: int = 8) -> List[str]:
        terms = self.interests()
        return [k for k, _ in sorted(terms.items(), key=lambda kv: kv[1], reverse=True)[:n]]

    def decay_interests(self, factor: float = 0.99) -> None:
        terms = self.interests()
        for k in list(terms):
            terms[k] = round(terms[k] * factor, 4)
            if terms[k] < 0.05:
                del terms[k]
        self.store.kv_set(self.INTEREST_KEY, terms)
