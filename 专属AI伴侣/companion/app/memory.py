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

# 功能词：从聊天里抽出来的是 vol 的日常用词，不是「兴趣」——
# 拿它们去联网搜只会搜出「表情包大全下载」「XX素材网」这种垃圾页。
# （digest.py 也从这里 import，两边共用一份，别各写各的）
FUNCTIONAL_INTERESTS = {
    "表情包", "表情", "图片", "截图", "二维码", "语音", "翻译",
    "喵", "机器人", "群", "频道", "好友", "聊天记录",
}


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
            if score > 0.05:
                scored.append((score, m))
        scored.sort(key=lambda x: x[0], reverse=True)
        # ★ MMR 去重：按分数贪心取，但每取到一条就把「和已取的重合」的压下去。
        #   为什么必须有：实测星野的 6 条召回里 4 条是「水族馆门票」的近义重复
        #   —— 名额被一件事占满之后，每轮回复都只能绕回那两张票，
        #   看起来就是「除了票不会聊别的」。
        picked: List[Dict[str, Any]] = []
        while scored and len(picked) < top_k:
            best_i, best_val = None, None
            for i, (s, m) in enumerate(scored):
                dup = max((cosine(m["vec"], p["vec"]) for p in picked), default=0.0)
                if dup >= 0.9:
                    # 近似重复（同一件事被记了好几遍）：**不占名额**，
                    # 直接跳过。星野库里「水族馆那两张票」被记了四遍，
                    # 不去掉的话 6 个名额里一半是同一句话。
                    continue
                val = s - 0.7 * dup              # λ=0.7 的 MMR
                if best_val is None or val > best_val:
                    best_val, best_i = val, i
            if best_i is None:
                break
            s, m = scored.pop(best_i)
            picked.append({**m, "score": round(s, 4)})
        return picked

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
    # ★ 两个桶必须分开（2026-10-20 实测事故）：
    #     interest_terms = 她**自己**的兴趣（人格的一部分）→ 决定自主浏览去搜什么
    #     heard_terms    = 聊天里听到的词（对方在聊什么）→ 只用于对话相关度
    #   混在一起的后果：星野的兴趣图谱被聊天灌成
    #   {AI 与模型进展:6, 表情包:4, QQ机器人:3, 虚拟机:3}，
    #   于是她「自主浏览」去搜「AI 模型最新消息」「QQ表情包大全」，
    #   搜回来全是下载站/广告页 → 一条都发不出去 → 她永远没有新话题可说，
    #   只能反复嚼「困、睡、水族馆、票」。
    INTEREST_KEY = "interest_terms"
    SEED_KEY = "interest_seed"
    HEARD_KEY = "heard_terms"
    HEARD_MAX = 40

    def _seed_interests(self) -> None:
        """从 interests.md 播种兴趣。

        分两类读：
        - **标题含「兴趣」、不含「用户」**的小节 → 她自己的兴趣，进 `interest_terms`
          （驱动自主浏览）
        - **标题含「兴趣」、同时也含「用户」**的小节 → 对方常聊的领域，
          进 `heard_terms`（只用于对话相关度，**不驱动她联网去搜**）——
          实测拿对方的行业词去搜只会搜出「AI 模型最新消息」「猎聘求职网」这种垃圾页
        """
        f = self.interests_file
        seed: Dict[str, float] = {}
        heard: Dict[str, float] = {}
        if f and f.exists():
            in_own = False
            in_user = False
            for line in f.read_text(encoding="utf-8").splitlines():
                s = line.strip()
                if s.startswith("#"):
                    has = "兴趣" in s
                    in_own = has and ("用户" not in s)
                    in_user = has and ("用户" in s)
                    continue
                if not s.startswith("- "):
                    continue
                term = s[2:].strip()
                if not term:
                    continue
                if in_own:
                    seed[term] = 1.0
                elif in_user:
                    heard[term] = 1.0
        if not seed and not heard:
            return
        # 种子每次都从文件刷新：改了 interests.md 重启就生效
        self.store.kv_set(self.SEED_KEY, dict(seed))
        if heard:
            cur = self.heard()
            cur.update(heard)
            self.store.kv_set(self.HEARD_KEY, cur)

        terms = self.store.kv_get(self.INTEREST_KEY) or {}
        if not terms:
            self.store.kv_set(self.INTEREST_KEY, dict(seed))
            return
        if not seed:
            # 这个角色没有「她自己的兴趣」清单 → 没有可用来过滤的基准，
            # 只能沿用旧行为（对话抽到的词都进图谱）。给他配一份
            # persona/characters/<slug>/interests.md 就会自动切到新规则。
            return
        # ★ 自愈：启动时把「不属于她的领域」的杂词清出去。
        #   这些杂词是被旧版 bump_interest 灌进来的（见上面注释），
        #   不清掉就一直污染自主浏览。
        changed = False
        for k, v in seed.items():
            if k not in terms:
                terms[k] = v
                changed = True
        for k in list(terms):
            if k not in seed and not self._matches_seed(k, seed):
                del terms[k]
                changed = True
        if changed:
            self.store.kv_set(self.INTEREST_KEY, terms)

    @staticmethod
    def _matches_seed(term: str, seed: Dict[str, float]) -> bool:
        """对话里抽到的词，是不是落在这个角色自己的兴趣范围里。

        判据：与种子词互为子串（「鲸鱼」 vs 「鲸鱼与海洋生物」），
        或共享一段 2 字以上的中文片段（「海洋生物」vs「深海 与 海洋生物 新发现」）。
        比对前先把空白去掉 —— 否则「 与」这种「空格+单字」的片段会把
        任何带「与」的种子都算成命中（实测让「AI 与模型进展」赖在图谱里不走）。
        单字不算（「睡」「票」这种不该被当成兴趣词）。
        """
        t = "".join((term or "").split())
        if len(t) < 2:
            return False
        for s in seed:
            s2 = "".join(str(s).split())
            if not s2:
                continue
            if t in s2 or s2 in t:
                return True
            for i in range(len(t) - 1):
                if t[i:i + 2] in s2:
                    return True
        return False

    def interests(self) -> Dict[str, float]:
        """她自己的兴趣图谱（驱动自主浏览的那一份）。"""
        return self.store.kv_get(self.INTEREST_KEY) or {}

    def heard(self) -> Dict[str, float]:
        """聊天里听到的词（只用于对话相关度，不驱动自主浏览）。"""
        return self.store.kv_get(self.HEARD_KEY) or {}

    def bump_interest(self, term: str, delta: float = 1.0) -> None:
        """对话里抽到的词：只有**落回她自己兴趣范围**的才进兴趣图谱，
        其余进「听过」桶 —— 对方聊什么，不等于她自己去搜什么。
        """
        term = (term or "").strip()
        if len(term) < 2:
            return          # 单字（「睡」「票」）太泛，当兴趣词毫无意义
        if term in FUNCTIONAL_INTERESTS:
            return
        seed = self.store.kv_get(self.SEED_KEY) or {}
        # seed 为空 = 这个角色没配「她自己的兴趣」，没有过滤基准 → 沿用旧行为
        if not seed or self._matches_seed(term, seed):
            terms = self.interests()
            terms[term] = round(terms.get(term, 0.0) + delta, 3)
            self.store.kv_set(self.INTEREST_KEY, terms)
            return
        heard = self.heard()
        heard[term] = round(heard.get(term, 0.0) + delta, 3)
        if len(heard) > self.HEARD_MAX:      # 有界：超了就把最弱的丢掉
            for k, _ in sorted(heard.items(), key=lambda kv: kv[1])[
                    :len(heard) - self.HEARD_MAX]:
                del heard[k]
        self.store.kv_set(self.HEARD_KEY, heard)

    def top_interests(self, n: int = 8) -> List[str]:
        terms = self.interests()
        return [k for k, _ in sorted(terms.items(), key=lambda kv: kv[1], reverse=True)[:n]]

    def decay_interests(self, factor: float = 0.99) -> None:
        """衰减：她自己的固定兴趣不衰减（那是人格的一部分）；
        「听过」桶衰减快得多，久不聊就自然消失。"""
        seed = self.store.kv_get(self.SEED_KEY) or {}
        terms = self.interests()
        for k in list(terms):
            if k in seed:
                continue
            terms[k] = round(terms[k] * factor, 4)
            if terms[k] < 0.05:
                del terms[k]
        self.store.kv_set(self.INTEREST_KEY, terms)
        heard = self.heard()
        for k in list(heard):
            heard[k] = round(heard[k] * factor, 4)
            if heard[k] < 0.05:
                del heard[k]
        self.store.kv_set(self.HEARD_KEY, heard)
