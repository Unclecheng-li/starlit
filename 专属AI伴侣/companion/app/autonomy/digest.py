"""自主浏览 + 静默学习 + 选择性分享。

核心参考《AI 需要有自己的人生》的 DailyDigest 思路：
  - 后台定时任务独立运行，不靠用户触发
  - 读什么由它自己决定（基于「你和它共同的兴趣点」）
  - **过程是静默的**：学到的东西向量化后静默入库，不跑来邀功
  - 分享是**选择性**的：相关度 + 新鲜度 + 距上次分享间隔，三加权过了才说
  - 「在场与缺席的艺术」：你偶尔聊到相关话题时，它自然地"也知道"

质量三关（2026-10-16 实测事故后加的，之前搜出来全是垃圾）：
  1. 搜索词模板池 —— 固定加「 最新」会踩满 SEO 下载站（「日服 v1.72 下载」）
  2. SEO 垃圾黑名单 —— 下载站/素材站/内容农场一律不进候选
  3. LLM 终审 —— 本地字符向量分不出「广告页」和「新活动公告」，
     实测「表情包大全下载」以 0.51 高分通过，发给用户一眼广告
"""
from __future__ import annotations

import json
import random
import re
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from ..config import AutonomyConfig, MemoryConfig
from ..llm import LLM
from ..memory import Memory, cosine, embed
from ..store import Store
from ..state import StateMachine
from .search import NotConfigured, SearchProvider, SearchResponseError

# 阈值与上限都从配置读（见 AutonomyConfig.digest_*）。
# 原来的硬编码 0.55 / 每天 1 次太保守 —— 实测从来没分享成功过。
DEFAULT_SHARE_SCORE_THRESHOLD = 0.42
DEFAULT_DAILY_SHARE_MAX = 3

EXTRACT_SYSTEM = """从这段内容里抽取 3~6 个关键词（中文优先），用于判断它和谁的兴趣相关。
只输出 JSON：{"keywords": ["...", "..."]}"""

# 搜索词模板池：每次随机换一种搜法（固定「{w} 最新」会踩满下载站）
QUERY_TEMPLATES = ("{w} 最新消息", "{w} 新闻", "{w} 新活动 公告", "{w} 趣闻")

# SEO 垃圾特征：下载站/素材站/内容农场 —— 一律不进候选
SPAM_PAT = re.compile(
    r"(下载|安装包|apk|正版|破解|大全|素材|壁纸|官网|网盘|免费|"
    r"3dm|87g|17173|游民|百科|词条)", re.IGNORECASE)

# 功能词：聊天里抽出来的 vol 日常用词，不是对方的真实兴趣 ——
# 拿它们去搜只会搜出「表情包大全下载」这种垃圾页
FUNCTIONAL_INTERESTS = {"表情包", "表情", "图片", "截图", "二维码", "语音", "翻译"}

SHARE_JUDGE_SYSTEM = """你是内容把关人。判断哪条搜索结果最值得分享给一位喜欢「{topics}」的朋友。
只输出 JSON：{"index": 序号(从1开始), "score": 1~10, "angle": "一句话：这条有意思在哪、值得聊在哪"}

评分标准：
- 8~10：新闻、新公告、趣闻、有讨论度的事 —— 看到会想聊两句
- 5~7：还行，勉强能聊
- 1~4：下载页/广告页/内容农场/与兴趣无关 —— 不值得分享"""


@dataclass
class ShareItem:
    text: str
    url: str
    score: float
    topic: str
    # 终审给的「值得聊的点」—— 给表达通道用，让分享像真人随口聊，
    # 而不是把搜索摘要原文甩出去
    angle: str = field(default="")


class Digest:
    def __init__(
        self,
        cfg: AutonomyConfig,
        mcfg: MemoryConfig,
        llm: LLM,
        memory: Memory,
        state: StateMachine,
        store: Store,
        search: SearchProvider,
    ):
        self.cfg = cfg
        self.mcfg = mcfg
        self.llm = llm
        self.memory = memory
        self.state = state
        self.store = store
        self.search = search
        self._last_run = 0.0

    # ---------- 主流程 ----------
    @property
    def _threshold(self) -> float:
        return float(getattr(self.cfg, "digest_threshold",
                             DEFAULT_SHARE_SCORE_THRESHOLD))

    @property
    def _daily_max(self) -> int:
        return int(getattr(self.cfg, "digest_max_share_per_day",
                           DEFAULT_DAILY_SHARE_MAX))

    async def run_once(self, force: bool = False) -> Optional[ShareItem]:
        if not getattr(self.cfg, "digest_enabled", True):
            return None

        # ★ 有「产出但还没发出去」的，先把它交出去，别再搜一遍。
        # 否则每 90 分钟搜一次、每次覆盖掉上一条没发成功的，
        # 结果一条都发不出去。
        pending = self.store.kv_get("digest_pending") or {}
        if pending.get("url"):
            if self._today_shared() >= self._daily_max:
                return None
            print(f"[digest] 用上次未发出的分享（{pending.get('ts')}）："
                  f"{str(pending.get('text'))[:40]}…")
            return ShareItem(text=str(pending.get("text") or ""),
                             url=str(pending.get("url") or ""),
                             score=float(pending.get("score") or 0.0),
                             topic=str(pending.get("topic") or ""),
                             angle=str(pending.get("angle") or ""))

        if self._today_shared() >= self._daily_max:
            print(f"[digest] 今日分享已达上限 {self._daily_max} 次，只静默学习")
            return None

        now = time.time()
        interval_s = max(60, int(getattr(self.cfg, "digest_interval_min", 90))) * 60
        if not force and now - self._last_run < interval_s:
            return None
        self._last_run = now

        topics = [t for t in self.memory.top_interests(12)
                  if t not in FUNCTIONAL_INTERESTS]
        if not topics:
            print("[digest] 没有可用的兴趣词（全是功能词），跳过")
            return None

        # 每次多抽几路（原来只抽 2 路、每路 5 条，命中面太窄）
        picked = random.sample(topics, k=min(3, len(topics)))
        print(f"[digest] 本轮关注：{picked}")

        candidates: List[ShareItem] = []
        seen_urls = set()
        for topic in picked:
            # ★ 查询词从模板池随机换 —— 固定「{topic} 最新」搜出来的
            # 全是「XX下载站」「XX大全」这种 SEO 页（实测翻车现场）
            query = random.choice(QUERY_TEMPLATES).format(w=topic)
            try:
                results = await self.search.search(query, n=6)
            except NotConfigured as e:
                print(f"[digest] 搜索未配置，跳过联网：{e}")
                return None
            except SearchResponseError as e:
                print(f"[digest] 搜索返回异常：{e}")
                return None

            for r in results:
                if not r.title or not r.url or r.url in seen_urls:
                    continue
                # ★ 垃圾过滤：下载/素材/内容农场 —— 本地打分分不出这些，
                # 实测「表情包大全下载」拿了 0.51 还被当成最佳分享出去
                if SPAM_PAT.search(f"{r.title} {r.url}"):
                    continue
                seen_urls.add(r.url)
                # 1) 静默学习：入库，不打扰
                self.memory.add_semantic(f"[{topic}] {r.title}：{r.snippet}（{r.url}）")
                # 2) 初筛评分
                score = await self._score(topic, r.title, r.snippet)
                if score >= self._threshold:
                    candidates.append(ShareItem(
                        text=f"{r.title}。{r.snippet[:160]}",
                        url=r.url, score=score, topic=topic))

        if not candidates:
            print(f"[digest] 初筛后没有候选（阈值 {self._threshold}），静默入库完毕")
            return None

        # ★ LLM 终审：本地字符向量只会看「字重合」，分不出广告和新闻。
        # 从初筛候选里挑最值得分享的一条，还要它说出「值得聊的点」。
        candidates.sort(key=lambda c: c.score, reverse=True)
        best = await self._judge(candidates[:6], picked)
        if best is None:
            print("[digest] 终审没看上任何一条，静默入库完毕")
            return None

        # ★ 只在这里**暂存**，不扣额度。
        # 原来是在这里就把「今日已分享 N 次」+1，而这只是「产出」——
        # 万一后面发送被拦/心跳没到点，额度就白扣了，
        # 结果是「搜到了、额度没了、你永远收不到」。
        # 现在额度只在真的发出去之后才扣（见 mark_shared）。
        prev = self.store.kv_get("digest_pending") or {}
        if not prev or prev.get("url") != best.url:
            self.store.kv_set("digest_pending", {
                "ts": time.strftime("%Y-%m-%d %H:%M:%S"),
                "score": best.score, "topic": best.topic, "angle": best.angle,
                "text": best.text[:400], "url": best.url,
            })
        print(f"[digest] ✅ 产出可分享项（终审分 {best.score:.1f}，"
              f"话题「{best.topic}」）：{best.text[:50]}…")
        return best

    async def _judge(self, cands: List[ShareItem],
                     topics: List[str]) -> Optional[ShareItem]:
        """LLM 终审：从候选里挑最值得分享的一条。

        只挑不打分每条 —— 一轮只发一条分享，批量打分是浪费调用。
        分数 <8 分（满分 10）就干脆别发 —— 宁可静默，不发广告。
        """
        lines = [f"{i + 1}. [{c.topic}] {c.text[:120]} ｜ {c.url}"
                 for i, c in enumerate(cands)]
        try:
            data = await self.llm.chat_json(
                [
                    {"role": "system", "content": SHARE_JUDGE_SYSTEM.replace(
                        "{topics}", "、".join(topics))},
                    {"role": "user", "content": "\n".join(lines)},
                ],
                # 推理模型的思维链会先吃掉一批 token，500 实测全被
                # 思考耗尽、正文 0 字符直接截断 —— 给足余量
                temperature=0.3, max_tokens=1500,
            )
        except Exception as e:  # noqa: BLE001
            print(f"[digest] 终审调用失败：{e!r}")
            return None
        try:
            idx = int(data.get("index") or 0)
            score = float(data.get("score") or 0)
        except (TypeError, ValueError):
            return None
        if not (1 <= idx <= len(cands)) or score < 8:
            return None
        pick = cands[idx - 1]
        pick.angle = str(data.get("angle") or "")[:120]
        pick.score = score / 10.0        # 归一成 0~1，展示和存档格式不变
        return pick

    async def _score(self, topic: str, title: str, snippet: str) -> float:
        text = f"{title} {snippet}"
        # 相关度：与兴趣词的语义相似
        relevance = max(0.0, cosine(embed(topic), embed(text)))
        # 新鲜度：与已有记忆的最大相似度越低越新鲜
        existing = self.memory.recall(text, top_k=3)
        max_sim = max((e["score"] for e in existing), default=0.0)
        novelty = max(0.0, 1.0 - max_sim)
        # 间隔：距上次分享越久，分数越高
        last = self.store.counter_get("last_share_ts", 0.0)
        gap_h = (time.time() - last) / 3600.0 if last else 999.0
        gap = min(1.0, gap_h / 24.0)
        score = 0.45 * relevance + 0.35 * novelty + 0.20 * gap
        return round(score, 3)

    async def extract_and_bump_interests(self, text: str) -> List[str]:
        """从对话里抽兴趣词，喂给兴趣图谱。"""
        try:
            data = await self.llm.chat_json(
                [
                    {"role": "system", "content": EXTRACT_SYSTEM},
                    {"role": "user", "content": text[:1500]},
                ],
                temperature=0.3,
                max_tokens=800,
            )
        except Exception:  # noqa: BLE001
            return []
        words = [str(w).strip() for w in (data.get("keywords") or []) if str(w).strip()]
        for w in words:
            self.memory.bump_interest(w, 1.0)
        self.memory.decay_interests(0.995)
        return words

    def _today_shared(self) -> float:
        return self.store.counter_get(f"digest_share_{time.strftime('%Y-%m-%d')}", 0.0)

    def mark_shared(self) -> None:
        """**真的发出去了**才调这个：扣额度、清掉待发、记时间。

        额度必须在这里扣 —— 在「产出」时扣的话，
        发送一旦失败额度就白费了（实测踩过这个坑：
        digest_share 已经是 1，last_share_ts 还是 0，一条都没发出去）。
        """
        key = f"digest_share_{time.strftime('%Y-%m-%d')}"
        self.store.counter_set(key, self.store.counter_get(key) + 1)
        self.store.counter_set("last_share_ts", time.time())
        # 记一份「已分享」的历史，方便事后看它到底分享过什么
        item = self.store.kv_get("digest_pending") or {}
        if item.get("url"):
            hist = self.store.kv_get("digest_history") or []
            if isinstance(hist, list):
                hist.append({**item, "sent_at": time.strftime("%Y-%m-%d %H:%M:%S")})
                self.store.kv_set("digest_history", hist[-30:])
        self.store.kv_set("digest_pending", None)
