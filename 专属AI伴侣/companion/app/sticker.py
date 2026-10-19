"""表情包库：情绪归一到检索 + 发送频率策略。

## 为什么情绪要先归一

表情包文件名里的情绪词很杂：搞怪、震惊、花痴、不甘心、死亡、酷……
而对话里判定出来的情绪是另一套（开心/难过/生气……）。
两边词不一样就检索不到，所以中间要有一层归一。

`CANON` 是唯一权威的情绪集，**对话判定和表情包标注都用它**。
文件名里的词通过 `FILENAME_EMOTION_MAP` 折进来。
"""
from __future__ import annotations

import hashlib
import json
import random
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .config import StickerConfig
from .memory import cosine, embed
from .store import Store

# ── 权威情绪集（对话判定与表情包标注共用）──────────────────────
CANON: Tuple[str, ...] = (
    "开心", "兴奋", "得意", "害羞", "卖萌", "亲密", "温柔", "感激", "鼓励",
    "平静", "认真", "疑惑", "惊讶", "无语",
    "难过", "低落", "委屈", "焦虑", "慌张", "害怕",
    "生气", "不爽", "愤怒",
    "疲惫", "困倦", "崩溃",
    "中性",
)

# 文件名里的情绪词 → 权威情绪
FILENAME_EMOTION_MAP: Dict[str, str] = {
    # 正面
    "开心": "开心", "满足": "开心", "高兴": "开心", "赞": "开心", "点赞": "开心",
    "兴奋": "兴奋", "得意": "得意", "胜利": "得意", "酷": "得意", "骄傲": "得意",
    "害羞": "害羞", "脸红": "害羞",
    "可爱": "卖萌", "卖萌": "卖萌", "搞怪": "卖萌", "搞笑": "卖萌", "调皮": "卖萌",
    "幽默": "卖萌", "萌": "卖萌",
    "亲密": "亲密", "贴贴": "亲密", "花痴": "亲密", "病娇": "亲密", "hug": "亲密",
    "温柔": "温柔", "摸摸": "温柔",
    "感动": "感激", "感谢": "感激", "谢谢": "感激",
    "加油": "鼓励", "鼓励": "鼓励", "安慰": "鼓励",
    # 中性 / 认知
    "冷静": "平静", "淡定": "平静", "放松": "平静", "平静": "平静",
    "认真": "认真", "严肃": "认真", "专注": "认真",
    "疑惑": "疑惑", "思考": "疑惑", "问号": "疑惑", "懵": "疑惑",
    "惊讶": "惊讶", "震惊": "惊讶", "吃惊": "惊讶",
    "无语": "无语", "尴尬": "无语", "汗": "无语", "沉默": "无语",
    "冷漠": "中性", "日常": "中性", "素材": "中性", "手势": "中性",
    "打招呼": "中性", "角色": "中性", "互动": "中性", "偷窥": "中性",
    # 负面
    "悲伤": "难过", "难过": "难过", "哭泣": "难过", "大哭": "难过", "哭": "难过",
    "低落": "低落", "沮丧": "低落", "消沉": "低落",
    "委屈": "委屈", "可怜": "委屈", "抱怨": "委屈",
    "焦虑": "焦虑", "紧张": "焦虑", "担心": "焦虑",
    "慌张": "慌张", "恳求": "慌张", "求": "慌张", "急": "慌张",
    "害怕": "害怕", "恐惧": "害怕", "惊恐": "害怕",
    "生气": "生气", "不爽": "不爽", "嫌弃": "不爽", "不甘心": "不爽",
    "愤怒": "愤怒", "怒": "愤怒", "暴力": "愤怒", "指责": "愤怒",
    "疲惫": "疲惫", "累": "疲惫", "无力": "疲惫",
    "困倦": "困倦", "困": "困倦", "睡觉": "困倦", "睡": "困倦",
    "崩溃": "崩溃", "死亡": "崩溃", "裂开": "崩溃", "抓狂": "崩溃",
}

# 情绪之间的近似关系：检索时沾边的也参与打分（权重低一些）
EMOTION_ALIASES: Dict[str, List[str]] = {
    "开心": ["开心", "兴奋", "得意"],
    "兴奋": ["兴奋", "开心"],
    "得意": ["得意", "开心"],
    "害羞": ["害羞", "卖萌", "亲密"],
    "卖萌": ["卖萌", "害羞", "亲密"],
    "亲密": ["亲密", "温柔", "害羞", "卖萌"],
    "温柔": ["温柔", "亲密", "鼓励"],
    "感激": ["感激", "开心", "鼓励"],
    "鼓励": ["鼓励", "温柔", "开心"],
    "平静": ["平静", "中性", "温柔"],
    "认真": ["认真", "平静"],
    "疑惑": ["疑惑", "惊讶"],
    "惊讶": ["惊讶", "疑惑"],
    "无语": ["无语", "不爽", "中性"],
    "难过": ["难过", "低落", "委屈", "崩溃"],
    "低落": ["低落", "难过", "疲惫"],
    "委屈": ["委屈", "难过", "低落"],
    "焦虑": ["焦虑", "慌张", "害怕"],
    "慌张": ["慌张", "焦虑", "害怕", "崩溃"],
    "害怕": ["害怕", "慌张", "焦虑"],
    "生气": ["生气", "愤怒", "不爽"],
    "不爽": ["不爽", "无语", "生气"],
    "愤怒": ["愤怒", "生气"],
    "疲惫": ["疲惫", "困倦", "低落"],
    "困倦": ["困倦", "疲惫", "平静"],
    "崩溃": ["崩溃", "慌张", "难过"],
    "中性": [],
}


def normalize_emotion(raw: str) -> str:
    """把任意情绪词折到权威情绪集里的一个。折不进来就返回「中性」。"""
    s = str(raw or "").strip()
    if not s:
        return "中性"
    if s in CANON:
        return s
    if s in FILENAME_EMOTION_MAP:
        return FILENAME_EMOTION_MAP[s]
    head = s.split("_")[0].strip()          # 「害羞_贴贴」这类
    if head in CANON:
        return head
    if head in FILENAME_EMOTION_MAP:
        return FILENAME_EMOTION_MAP[head]
    hits = [k for k in FILENAME_EMOTION_MAP if k in s]
    if hits:
        return FILENAME_EMOTION_MAP[max(hits, key=len)]
    return "中性"


class StickerLibrary:
    def __init__(self, index_path: str | Path):
        self.index_path = Path(index_path)
        self.items: List[Dict[str, Any]] = []
        self._vecs: List[List[float]] = []
        # None = 不限制；set = 只允许这些 source（对话设置里勾选的表情包分类）
        self.allowed_sources: Optional[set] = None
        self.load()

    def load(self) -> None:
        if not self.index_path.exists():
            print(f"[sticker] 索引不存在：{self.index_path}")
            self.items, self._vecs = [], []
            return
        try:
            data = json.loads(self.index_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            print(f"[sticker] 索引解析失败：{e}")
            data = []
        missing = 0
        for d in data:
            if Path(str(d.get("file", ""))).exists():
                self.items.append(d)
            else:
                missing += 1
        self._vecs = [
            embed((str(d.get("desc", "")) + " " + " ".join(d.get("tags", []))).strip())
            for d in self.items
        ]
        msg = f"[sticker] 已加载 {len(self.items)} 张"
        if missing:
            msg += f"（{missing} 张文件已不在，跳过）"
        print(msg)

    @property
    def available(self) -> bool:
        return bool(self.items)

    # ---- 对话级可用分类 / 自建表情维护 ----

    def set_allowed_sources(self, sources: Optional[List[str]]) -> None:
        """限定这个角色能用哪些分类（None = 全部）。"""
        self.allowed_sources = None if sources is None else set(sources)

    def _allowed(self, item: Dict[str, Any]) -> bool:
        return (self.allowed_sources is None
                or item.get("source") in self.allowed_sources)

    def _save_index(self) -> None:
        try:
            self.index_path.parent.mkdir(parents=True, exist_ok=True)
            self.index_path.write_text(
                json.dumps(self.items, ensure_ascii=False, indent=1),
                encoding="utf-8")
        except OSError as e:
            print(f"[sticker] 写索引失败：{e!r}")

    def add_item(self, item: Dict[str, Any], *, persist: bool = True) -> None:
        """新增一张（自建上传）—— 不重启就能被 pick 到。"""
        self.items.append(item)
        text = (str(item.get("desc", "")) + " "
                + " ".join(item.get("tags", []))).strip()
        self._vecs.append(embed(text))
        if persist:
            self._save_index()

    def remove_item(self, file_path: str | Path, *,
                    persist: bool = True) -> bool:
        """按文件路径删掉索引项（文件本身由调用方删）。"""
        want = str(Path(file_path).resolve())
        keep_items: List[Dict[str, Any]] = []
        for it in self.items:
            try:
                same = str(Path(str(it.get("file", ""))).resolve()) == want
            except OSError:
                same = False
            if not same:
                keep_items.append(it)
        if len(keep_items) == len(self.items):
            return False
        self.items = keep_items
        self._vecs = [
            embed((str(d.get("desc", "")) + " " + " ".join(d.get("tags", []))).strip())
            for d in self.items
        ]
        if persist:
            self._save_index()
        return True

    def remove_items(self, paths: List[str | Path], *,
                     persist: bool = True) -> int:
        """一次删掉一批（删整个分类时用），只落盘一次。"""
        wants = set()
        for p in paths:
            try:
                wants.add(str(Path(p).resolve()))
            except OSError:
                continue
        if not wants:
            return 0
        keep_items: List[Dict[str, Any]] = []
        for it in self.items:
            try:
                same = str(Path(str(it.get("file", ""))).resolve()) in wants
            except OSError:
                same = False
            if not same:
                keep_items.append(it)
        removed = len(self.items) - len(keep_items)
        if removed <= 0:
            return 0
        self.items = keep_items
        self._vecs = [
            embed((str(d.get("desc", "")) + " " + " ".join(d.get("tags", []))).strip())
            for d in self.items
        ]
        if persist:
            self._save_index()
        return removed

    def candidates(self, emotion: str, top_k: int = 5) -> List[Dict[str, Any]]:
        if not self.items:
            return []
        want = normalize_emotion(emotion)
        related = set(EMOTION_ALIASES.get(want, [])) | {want}
        scored = []
        for it, vec in zip(self.items, self._vecs):
            if not self._allowed(it):
                continue
            emos = set(it.get("emotions", []))
            exact = 1.0 if want in emos else 0.0
            near = 0.6 if (emos & related) else 0.0
            sim = cosine(embed(want), vec)
            scored.append((exact * 2.0 + near + sim * 0.5, it))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [it for _, it in scored[:top_k]]

    def pick(
        self,
        emotion: str,
        context_text: str = "",
        *,
        avoid: Optional[List[str]] = None,
        prefer_source: str = "",
    ) -> Optional[Dict[str, Any]]:
        """挑一张。带随机扰动，避免每次都发同一张。"""
        if not self.items:
            return None
        avoid = set(avoid or [])
        want = normalize_emotion(emotion)
        related = set(EMOTION_ALIASES.get(want, [])) | {want}
        ctx = embed(context_text) if context_text else None

        scored = []
        for it, vec in zip(self.items, self._vecs):
            if it["file"] in avoid:
                continue
            if not self._allowed(it):
                continue
            emos = set(it.get("emotions", []))
            exact = 1.0 if want in emos else 0.0
            near = 0.6 if (emos & related) else 0.0
            base = exact * 2.0 + near
            if base <= 0:
                continue                        # 情绪完全不搭的直接排除
            sim = cosine(ctx, vec) if ctx else 0.0
            # 偏好来源：source 字段或 tags 里命中都算（比如「星野」是子目录名）
            bonus = 0.0
            if prefer_source and (prefer_source == it.get("source")
                                  or prefer_source in (it.get("tags") or [])):
                bonus = 0.35
            jitter = random.random() * 0.30
            scored.append((base + sim * 0.5 + bonus + jitter, it))

        if not scored:
            return None
        scored.sort(key=lambda x: x[0], reverse=True)
        best = scored[0][0]
        pool = [it for s, it in scored[:5] if s >= best * 0.85]
        return random.choice(pool or [scored[0][1]])

    def pick_many(
        self,
        emotion: str,
        context_text: str = "",
        n: int = 1,
        *,
        prefer_source: str = "",
    ) -> List[Dict[str, Any]]:
        """挑 n 张**互不相同**的。

        真人连发几个表情时不会重复同一张，所以这里逐张调用 `pick`，
        把已选中的传给 `avoid` 排除掉。
        """
        out: List[Dict[str, Any]] = []
        got: List[str] = []
        for _ in range(max(1, n)):
            it = self.pick(emotion, context_text, avoid=got,
                           prefer_source=prefer_source)
            if it is None:
                break
            out.append(it)
            got.append(it["file"])
        return out


# ── 发送频率策略 ──────────────────────────────────────────────


@dataclass
class StickerVerdict:
    send: bool
    reason: str
    probability: float = 0.0


class StickerPolicy:
    """决定「这一轮该不该发表情包」。

    频率挂四件事：
      1. **对话情绪的强度** —— 情绪越强越容易发（平静的闲聊不必配图）
      2. **它自己的心情** —— 心情极差或社交电量低时明显少发（不想卖萌）
      3. **距上次发图多久** —— 既防连发，也**攒势**：
         憋得越久越容易发（原来只有"冷却上限"，结果是一晚上一张都不响）
      4. **这一轮要不要连发 2~3 张** —— 真人聊天偶尔会连甩几个表情

    不是「能发就发」，是让发图这件事**有节奏**。
    """

    def __init__(self, cfg: StickerConfig, store: Store):
        self.cfg = cfg
        self.store = store

    def _last_ts(self) -> float:
        return self.store.counter_get("last_sticker_ts", 0.0)

    def _today(self) -> float:
        return self.store.counter_get(f"sticker_{time.strftime('%Y-%m-%d')}", 0.0)

    def note_sent(self, n: int = 1) -> None:
        self.store.counter_set("last_sticker_ts", time.time())
        key = f"sticker_{time.strftime('%Y-%m-%d')}"
        self.store.counter_set(key, self.store.counter_get(key) + n)

    def gap_minutes(self) -> float:
        ts = self._last_ts()
        return (time.time() - ts) / 60.0 if ts else 1e9

    def remaining_today(self) -> int:
        """今天还能发几张。给模型看，免得它一口气要 5 张但只剩 2 张额度。"""
        return max(0, int(self.cfg.daily_max - self._today()))

    def how_many(self, intensity: float = 0.5, emotion: str = "") -> int:
        """兜底：模型没给出张数时用这个。

        **正常情况下张数由模型按语境决定**（见 `think.judge_sticker`），
        这里只是它漏填时的后备，所以做成「跟情绪强度走」而不是固定比例。

        情绪越强，越可能多给一张。
        """
        strong = max(0.0, min(1.0, intensity))
        r = random.random()
        if r < 0.45 - 0.25 * strong:      # 情绪强 → 这个分支概率变低
            return 1
        if r < 0.85 - 0.15 * strong:
            return 2
        return 3

    def clamp_count(self, want: int, *, room: int = 99) -> int:
        """把想要的张数收进「合理范围」。

        上限来自 **今天还剩多少额度** —— 用户要「多发些」，但也不能
        一口气把当日额度全砸在一轮里（那会变成刷屏且后面没得发）。
        """
        n = max(1, int(want))
        cap = max(1, int(self.cfg.max_per_turn))
        return max(1, min(n, cap, max(1, room)))

    def evaluate(self, *, emotion: str, intensity: float, valence: float,
                 energy: float, last_was_sticker: bool,
                 force: bool = False) -> StickerVerdict:
        if not self.cfg.enabled:
            return StickerVerdict(False, "表情包功能已关闭")

        # 注意：这里**只拦「上一条正好是纯图」**（那种情况没什么可配的）。
        # 不再因为「上一轮发过图」就直接否掉整轮 —— 那会让发图变得极其稀少。
        # 相邻两次之间由 min_gap_min 控制即可。
        if last_was_sticker:
            return StickerVerdict(False, "上一条已经是纯图了")

        gap_min = self.gap_minutes()
        used = self._today()

        if not force:
            if gap_min < self.cfg.min_gap_min:
                return StickerVerdict(
                    False, f"距上次发图仅 {gap_min:.0f} 分钟"
                           f"（最小间隔 {self.cfg.min_gap_min} 分钟）")
            if used >= self.cfg.daily_max:
                return StickerVerdict(
                    False, f"今日已发 {used:.0f} 张，到上限 {self.cfg.daily_max}")

        p = self.cfg.base_probability
        p *= 0.6 + 0.8 * max(0.0, min(1.0, intensity))        # 情绪越强越可能发

        if valence < -40:                                      # 心情极差 → 不想卖萌
            p *= 0.25
        elif valence < -15:
            p *= 0.6
        elif valence > 40:
            p *= 1.25

        if energy < self.cfg.energy_threshold:                 # 电量低 → 懒得找图
            p *= 0.3
        elif energy < self.cfg.energy_threshold + 20:
            p *= 0.7

        if normalize_emotion(emotion) == "中性":               # 中性情绪不太需要配图
            p *= 0.4

        # ★ 攒势：憋得越久越容易发。
        # 没有这一项的话，概率只看情绪和心情，跟"多久没发了"无关，
        # 结果就是聊一晚上一张都不响（或情绪一高就突然刷屏）。
        if gap_min >= 9999:                                    # 从没发过
            p *= 1.5
        elif gap_min >= 30:
            p *= 1.35
        elif gap_min >= 10:
            p *= 1.15

        p = max(0.0, min(1.0, p))
        if force:
            return StickerVerdict(True, f"强制发送（概率 {p:.0%}）", p)

        roll = random.random()
        if roll < p:
            return StickerVerdict(True, f"命中（概率 {p:.0%}，掷 {roll:.2f}）", p)
        return StickerVerdict(False, f"未命中（概率 {p:.0%}，掷 {roll:.2f}）", p)


# ── 偷表情包 ──────────────────────────────────────────────────


STEAL_SYSTEM = """你在看对方发来的一张图，判断「你自己会不会想把它收进自己的表情包库」。
只输出 JSON：
{"keep": true/false, "emotion": "...", "tags": ["..."], "reason": "一句话，用你自己的口吻"}

你的口味：
- 收：好笑的、搞怪卖萌的、无语/崩溃类、海洋或鲸鱼相关、Blue Archive 相关、
      猫猫狗狗小鸟这类小动物
- 不收：太糊看不清的、纯文字截图、露骨或血腥过头的、明显是别人隐私的、
        单纯的风景照或商品图、无聊的

emotion 从这些里选一个：
开心/兴奋/得意/害羞/卖萌/亲密/温柔/感激/鼓励/平静/认真/疑惑/惊讶/无语/
难过/低落/委屈/焦虑/慌张/害怕/生气/不爽/愤怒/疲惫/困倦/崩溃/中性"""


@dataclass
class StealVerdict:
    keep: bool
    reason: str = ""
    emotion: str = "中性"
    tags: List[str] = field(default_factory=list)
    desc: str = ""


class StickerStealer:
    """看到对方发的表情包，按自己的口味决定收不收。

    三层过滤，省钱也省事：
      1. 本地硬门槛（开关 / 每日上限 / 内容去重）
      2. 掷骰子（steal_probability）
      3. 只有过了前两层才去问模型「喜不喜欢」

    收下的图落到 `data/stickers/stolen/`，文件名带情绪前缀
    （`害羞_ab12cd34.gif`），这样下次重建索引时能被文件名模式解析到。
    """

    def __init__(self, cfg: StickerConfig, store: Store,
                 library: StickerLibrary, sticker_dir: Path):
        self.cfg = cfg
        self.store = store
        self.library = library
        self.sticker_dir = Path(sticker_dir)

    # ---- 计数 / 去重 ----
    def _today(self) -> float:
        return self.store.counter_get(f"stolen_{time.strftime('%Y-%m-%d')}", 0.0)

    def _seen(self) -> List[str]:
        return self.store.kv_get("stolen_hashes") or []

    async def consider(self, llm, image: bytes, mime: str,
                       image_desc: str = "", user_text: str = "") -> StealVerdict:
        if not self.cfg.steal_enabled:
            return StealVerdict(False, "偷表情包已关闭")

        used = self._today()
        if used >= self.cfg.steal_daily_max:
            return StealVerdict(False, f"今天已经收了 {used:.0f} 张，够了")

        h = hashlib.md5(image).hexdigest()[:16]
        if h in self._seen():
            return StealVerdict(False, "这张已经有了")

        if random.random() >= self.cfg.steal_probability:
            return StealVerdict(False, "这次没看上")

        prompt = ("看看这张图。"
                  + (f"\n对方同时说：{user_text}" if user_text else "")
                  + (f"\n这张图是：{image_desc}" if image_desc else "")
                  + "\n你收不收？")
        try:
            data = await llm.chat_with_images_json(prompt, [image],
                                                   system=STEAL_SYSTEM, mimes=[mime])
        except Exception as e:  # noqa: BLE001
            return StealVerdict(False, f"判断失败：{e}")

        if not data.get("keep"):
            return StealVerdict(False, str(data.get("reason", "没看上")))

        emo = normalize_emotion(str(data.get("emotion") or "中性"))
        return StealVerdict(
            True, str(data.get("reason", "")), emo,
            [str(t) for t in (data.get("tags") or [])][:6],
            str(data.get("desc") or image_desc)[:80],
        )

    def save(self, image: bytes, mime: str, verdict: StealVerdict) -> Optional[Dict[str, Any]]:
        """把图落到 stolen/ 并追加进索引与内存库。"""
        ext = {"image/png": ".png", "image/jpeg": ".jpg", "image/gif": ".gif",
               "image/webp": ".webp", "image/bmp": ".bmp"}.get(mime, ".png")
        h = hashlib.md5(image).hexdigest()[:8]
        out_dir = self.sticker_dir / "stolen"
        out_dir.mkdir(parents=True, exist_ok=True)
        path = out_dir / f"{verdict.emotion}_{h}{ext}"
        try:
            path.write_bytes(image)
        except OSError as e:
            print(f"[steal] 写文件失败：{e!r}")
            return None

        item = {
            "file": str(path),
            "desc": verdict.desc or verdict.emotion,
            "emotions": [verdict.emotion],
            "raw_emotion": verdict.emotion,
            "tags": (verdict.tags or []) + ["stolen", "对方发的"],
            "source": "stolen",
        }
        # 追加索引
        try:
            idx_path = self.library.index_path
            data = json.loads(idx_path.read_text(encoding="utf-8")) if idx_path.exists() else []
            data.append(item)
            idx_path.parent.mkdir(parents=True, exist_ok=True)
            idx_path.write_text(json.dumps(data, ensure_ascii=False, indent=1),
                                encoding="utf-8")
        except Exception as e:  # noqa: BLE001
            print(f"[steal] 更新索引失败：{e!r}")

        # 追加内存库（不用重启就能用）
        self.library.items.append(item)
        self.library._vecs.append(
            embed((item["desc"] + " " + " ".join(item["tags"])).strip()))

        # 记账
        key = f"stolen_{time.strftime('%Y-%m-%d')}"
        self.store.counter_set(key, self.store.counter_get(key) + 1)
        seen = self._seen()
        seen.append(hashlib.md5(image).hexdigest()[:16])
        self.store.kv_set("stolen_hashes", seen[-500:])   # 只留最近 500 个
        print(f"[steal] 收下了：{path.name}（{verdict.reason}）")
        return item
