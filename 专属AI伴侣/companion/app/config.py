"""配置加载。"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List

import yaml

ROOT = Path(__file__).resolve().parent.parent


@dataclass
class LLMConfig:
    base_url: str = "https://api.deepseek.com"
    api_key: str = ""
    model: str = "deepseek-flash"
    timeout: int = 90
    temperature: float = 0.9


@dataclass
class QQServerConfig:
    """onebot-server 通道：vol 自己当 OneBot 11 服务端。

    给 Stapxs QQ Lite 等第三方 OneBot 客户端直连用的 —— 彻底脱离
    QQ 协议（NapCat/腾讯），零封号风险。客户端把 vol 当成「NapCat」
    连接：WS 上双向调用（action/params/echo）+ 事件推送。

    - listen/port：WS + HTTP API + 表情包静态文件，同一个端口全包了
    - token：access_token 鉴权（客户端 URL 上带 ?access_token=...）；
      留空 = 不鉴权（仅限本机测试，上公网必须填）
    - base_url：对外可达地址（生成表情包的下载 URL 用）。
      本机跑 = http://127.0.0.1:port；上云后改成公网域名/局域网 IP
    - owner_nickname：用户在客户端里的显示名（登录者）
    - bot_nickname：好友列表里「星野」的显示名
    """

    listen: str = "0.0.0.0"
    port: int = 8080
    token: str = ""
    base_url: str = "http://127.0.0.1:8080"
    heartbeat_sec: int = 25
    owner_nickname: str = "老师"
    bot_nickname: str = "星野"


@dataclass
class QQConfig:
    self_id: str = ""
    owner_id: str = ""
    # 通道选择：napcat = 走 QQ（NapCat 反向 WS）；onebot-server = 自托管
    # （Stapxs 等客户端直连 vol，不再依赖 QQ）。默认 napcat 保持旧行为。
    channel: str = "napcat"
    server: QQServerConfig = field(default_factory=QQServerConfig)
    # 群聊响应策略（默认最保守）：
    #   off       任何群消息都不回
    #   mention   被 @ 时回
    #   allowlist 仅 group_allowlist 列出的群，且被 @ 时回
    group_mode: str = "off"
    group_allowlist: List[str] = field(default_factory=list)
    ws_host: str = "0.0.0.0"
    ws_port: int = 6701
    ws_path: str = "/onebot/v11/ws"
    ws_token: str = ""
    http_base: str = "http://127.0.0.1:3000"
    http_token: str = ""


@dataclass
class BehaviorConfig:
    # ── 以下延迟按真实聊天记录校准：真人回复中位 14s / P25 5s ──
    outbound_delay_ms: List[int] = field(default_factory=lambda: [5000, 20000])
    # 长回复拆条时，两条之间的间隔（真人连发间隔中位 8~10s）
    chunk_delay_ms: List[int] = field(default_factory=lambda: [5000, 20000])
    # 文字发完后、补一张表情包之前的间隔
    sticker_delay_ms: List[int] = field(default_factory=lambda: [4000, 9000])
    split_long_reply: bool = True
    # 超过这个字数就考虑拆成多条（真人单条中位 8~9 字、P90 17~22 字）
    split_threshold: int = 28
    # 一条回复最多拆成几条消息，防止刷屏
    max_chunks: int = 5
    # 拆出来的短消息之间的间隔
    bubble_delay_ms: List[int] = field(default_factory=lambda: [5000, 20000])
    # ★ 长度分档间隔：表达通道直接给出气泡列表时用（碎片短条 vs 完整长句）。
    # 真人连发间隔 P25 5s / 中位 8~10s：打字需要时间，零间隔是破绽。
    short_bubble_delay_ms: List[int] = field(default_factory=lambda: [4000, 12000])
    long_bubble_delay_ms: List[int] = field(default_factory=lambda: [7000, 22000])
    # ── 多条消息合并 ─────────────────────────────────────────
    # 用户连发几条时，等一小段再一起理解，而不是逐条回。
    # 真人也是这样：对方噼里啪啦发完，你读完再一次性接。
    # 用户连发间隔中位 9s，窗口必须接得住（原 3s 会把一轮连发拆成几次处理）
    merge_window_sec: float = 9.0      # 最后一条之后等这么久
    # 第一条最多等这么久。原 14s 会把长连发切成两批 → 逐批回（机械感来源）
    merge_max_wait_sec: float = 30.0   # 追时逻辑兜住总延迟，等久也不亏
    merge_max_msgs: int = 10           # 一次最多合并几条
    # 对方只发了一个表情包（没文字）时，回复的概率。
    # 全量数据：真人 28~40% 的消息是纯图 —— 跟一张图比硬凑文字更真实。
    sticker_only_reply_prob: float = 0.35


@dataclass
class StickerConfig:
    """表情包发送频率策略。

    目标不是「能发就发」，而是让发图这件事**有节奏** ——
    跟对话情绪的强度、它自己的心情、距上次发图多久都挂钩。
    """

    enabled: bool = True
    # 基础概率（会再乘上情绪强度与心情系数）
    # 全量数据：真人 28~40% 的消息是纯图，用图说话是常态
    base_probability: float = 0.50
    # 两次发图之间的最小间隔（分钟）
    # 每天最多发几张
    daily_max: int = 15
    # 社交电量低于此值时明显少发
    energy_threshold: int = 40
    # 额外图库目录（除 data/stickers 之外）
    extra_dirs: List[str] = field(default_factory=list)

    # 一次最多连发几张。张数本身**由模型按语境定**，这里只是硬上限，
    # 防止一轮把当日额度全砸出去（那就成刷屏了）。
    # ★ 拟人度修正：默认收紧为 2 —— 真人极少 1 秒连甩三四张图，
    # 最多「情绪炸了」时补一张。绝大多数时候 1 张就够。
    max_per_turn: int = 2

    # ── 发图节奏（防「一次刷五六张」也防「一晚上不响」）────────
    # 最小间隔，同时充当**攒图**：距上次发图越久，概率越高
    # （原来只有冷却上限，导致「要么不发、要么连发」）
    min_gap_min: int = 6

    # ── 偷表情包 ──────────────────────────────────────────────
    # 看到对方发的图，按自己的口味决定要不要收进图库
    steal_enabled: bool = True
    steal_probability: float = 0.55   # 先掷一次骰子，过了才去问「喜不喜欢」
    steal_daily_max: int = 8          # 每天最多收几张
    steal_from_groups: bool = False   # 群里别人发的图要不要收（默认不收）


@dataclass
class ConversationConfig:
    """对话连贯性：让聊天像真的一样能持续，而不是一问一答就断。"""

    enabled: bool = True
    # 用户最后一条消息之后，多久内算「还在聊天」。
    # 在这个窗口内它会像真人一样继续把话接下去，窗口外才走那套慢节奏的主动机制。
    active_window_min: int = 15
    # 自己回完之后，隔多久考虑再说一句（秒）。
    # ★ 接话 =「对方没回，过了一会儿又想起一句」，分钟级才像真人；
    # 连发那一下的 8~10s 间隔由气泡协议在**一次回复内**完成，
    # 不要把那个数字挪到这里（实测 10~70s 会变成高频独白引擎）
    followup_delay_sec: List[int] = field(default_factory=lambda: [60, 180])
    # 一直没等到回复时，最多连续说几条就必须停下
    max_bot_turns_without_reply: int = 5
    # 同一个话题内最多主动补几次
    max_followups_per_topic: int = 3
    # ── 情绪深聊场景的放宽 ───────────────────────────────────
    # 用户在倾诉 / 需要安慰时，「三轮」明显不够（用户明确反馈）。
    # 识别为深聊时，上面两个上限放到 deep_* 那组。
    deep_max_bot_turns: int = 8
    deep_max_followups: int = 8
    # 深夜（免打扰时段）里，活跃会话还允许补几条（比白天更克制）
    quiet_hours_max_turns: int = 1
    # 社交电量低于这个值就不再主动接话
    energy_threshold: int = 25
    # ── 拟人度收紧（对比真实聊天记录后的修正）────────────────────
    # ★ 连发上限改按「气泡」（一条消息）计，不再按「轮」计 ——
    # 真实数据：好友单轮连发中位 3 条、P75 5~7 条、5+ 条占 29~38%。
    # 一口气拆成多条本来就是真人常态，收紧要收在「没人回应时」而不是「单轮条数」。
    max_burst_bubbles: int = 5
    deep_max_burst_bubbles: int = 9
    # ★ 无回应阶梯退避：第 1 次接话用 followup_delay_sec，
    # 之后按这个表递增（[下限,上限]秒）；表耗尽 = 不再接话，等用户先开口。
    # 档位要和 followup_delay_sec 拉开差距，否则「补话」退成「连发」。
    followup_backoff_sec: List[List[int]] = field(
        default_factory=lambda: [[120, 300], [600, 2400]])
    # ★ 追问（probe）每个话题最多几次 —— 每轮都问会变成查户口
    max_probes_per_topic: int = 1
    # ── 话题重启（数据驱动的新机制）──────────────────────────
    # 全量数据（1.6 万次静默边界）：话题死在自己手里时，真人好友
    # **59% 会自己重新开口**找新话题，中位 176 分钟；用户要求参考
    # **最快的一批**：P5 = 19 分钟、最快 10% 集中在 15~25 分钟 ——
    # 下限按这条线压到 20 分钟，上限取 90 分钟（偏快的批次）。
    reopen_delay_sec: List[int] = field(default_factory=lambda: [1200, 5400])
    # 每个话题死亡周期最多重启几次（配额用完就安静等对方/心跳）
    max_reopens: int = 2


@dataclass
class AutonomyConfig:
    enabled: bool = True
    # ── 拟人节奏：四档混合分布（单位：分钟）────────────────────
    # 真人的主动是**不规则**的：可能你刚放下手机她就冒一句，
    # 也可能一整天不吭声。所以最低那档必须能低到「几乎立刻」。
    rhythm_instant: List[int] = field(default_factory=lambda: [1, 8])      # 1~8 分钟：马上就来
    rhythm_near: List[int] = field(default_factory=lambda: [20, 120])      # 20分钟~2小时
    rhythm_normal: List[int] = field(default_factory=lambda: [120, 480])   # 2~8小时
    rhythm_long: List[int] = field(default_factory=lambda: [720, 2880])    # 12~48小时
    #           马上   近    常    远
    rhythm_weights: List[float] = field(
        default_factory=lambda: [0.30, 0.32, 0.27, 0.11])
    # 情绪对节奏的影响强度（0 = 完全不受影响，1 = 影响明显）
    state_influence: float = 0.5
    # 到点后仍有这个概率选择「这一轮先不开口」，直接顺延一轮
    skip_probability: float = 0.15
    # 冷启动：从没主动说过话时，第一次不要抽到「远」档（不然会像死了一样）。
    # 设为 0 表示关闭这个特殊处理，完全按上面的分布来。
    first_contact_max_min: int = 120
    # 兜底：rhythm_weights 为空时用这个固定间隔（向后兼容旧配置）
    base_interval_min: int = 210
    jitter_min: int = 60

    quiet_hours: List[str] = field(default_factory=lambda: ["00:30", "08:30"])
    min_gap_min: int = 45
    # 单次主动间隔的硬上限（0 = 不限制）。由「热情」派生，防止抽到
    # 「远」档后一整天甚至两天不出现。
    max_gap_min: int = 0
    cold_streak_limit: int = 3
    energy_threshold: int = 30
    daily_max: int = 5

    # ── 冷场后的「静默→回来关心」循环 ────────────────────────
    # 用户明确要求：不要因为「发了几条没回」就**永久**停掉。
    # 真人会：先收一收，静默久一点，然后回来问一句「你还好吗」，
    # 之后再继续分享。而且**越久不回越不安**。
    #
    # 原来 cold_streak >= limit+2 是**永久拦截**（只在用户开口时重置），
    # 结果就是「她再也不会主动找我」，与预期相反。
    # ★ 2026-10-20 用户要求「更黏人」：冷场后的静默放软很多。
    #   原来 60 分钟起、每轮 ×1.6、上限 8 小时 —— 冷场 5 次就变成
    #   「要 245 分钟才回来」，日志里出现过 480 分钟，晚上等于完全消失。
    #   现在 25 分钟起、×1.2、上限 60 分钟：最多安静一小时就会回来关心你。
    silence_min: int = 25          # 第一次静默至少这么久（分钟）
    silence_growth: float = 1.2    # 每多一轮静默，时长乘这个系数
    silence_max_min: int = 60      # 静默时长的上限（1 小时）
    # 静默期满后，回来第一句是「关心状态」而不是继续分享
    # ── 你没空回消息时的「自动宽限」─────────────────────────
    # 你忙起来一整天没回，她的焦虑/孤独/委屈会一路涨到爆（实测有角色焦虑 90、
    # 效价 -60）。真人不会因为对方上班没回就崩溃 —— 所以：距你上次说话超过
    # 这么多分钟，就当她理解成「他在忙」，**暂停**负面情绪的增长；你一开口
    # 立刻恢复正常（该撒娇撒娇、该委屈委屈）。0 = 关闭这条宽限。
    busy_grace_min: int = 45

    checkin_kinds: List[str] = field(
        default_factory=lambda: ["miss", "mood", "miss", "miss"])

    # ── 自主浏览（自己上网找东西，然后分享）────────────────────
    # 用户明确要求：自己去搜 BlueArchive / 二次元二游 / 现实世界的东西，
    # 主要是**和用户兴趣相关**的，然后分享给他。
    digest_enabled: bool = True
    digest_interval_min: int = 90     # 至少隔这么久才跑一轮（分钟）
    digest_max_share_per_day: int = 3  # 每天最多分享几次
    digest_threshold: float = 0.42    # 分享阈值（越低越爱分享）

    # ── 上线问候：每次启动都一定主动发一条 ────────────────────
    # 用户明确要求。不等心跳抽签 —— 那个可能几小时都不开口，
    # 体感就是「她从来不主动找我」。
    greet_on_start: bool = True
    greet_delay_sec: int = 20          # 启动后等这么久（留出连 NapCat 的时间）
    # NapCat 要弹 UAC + 扫码，可能很久才连上。原来给 60 秒超时就放弃，
    # 结果上线问候几乎永远发不出去。这里给足时间（默认 60 分钟）。
    greet_wait_max_sec: int = 3600


@dataclass
class GroupConfig:
    """群聊引擎。**核心目标：让群像有人的群，但绝不让 AI 之间无限互相接话。**

    群聊是跨角色对话 —— 10 个角色同一个模型、同一套口癖，如果不设硬上限，
    必然演变成「两个人互相接梗刷屏」。所以这里的参数分四类：
    防循环链、频率预算、单次发言规模、以及转发/吃醋的节流。
    """
    enabled: bool = True

    # ── 防 AI-AI 无限循环（最重要的一组）──────────────────────
    # ★ 2026-10-19 上调：实测真群里一条消息之后 60 秒内平均 2.59 个不同的人
    #   开口、我发言后 10 分钟内平均 7.8 人接话。原来的 3/6 会在**我这一轮
    #   回应中途**就触发冷却，日志里能看到「本轮说满 → 冷却 15 分钟」紧跟着
    #   「橘雪莉 不开口：上一轮说满了」——挑了 5 个人只说出 3 个，剩下被静默
    #   丢弃。放宽到 5/8 既容得下一轮完整回应，又仍然封住 AI 互相刷屏。
    ai_chain_max: int = 5            # 距我上条消息以来，连续非我发言 ≤ 这个数
    ai_no_owner_max: int = 8         # 一轮里的总发言上限（含我自己）
    chain_cooldown_min: int = 15     # 触顶后冷却；期间只有我发言能重开
    round_gap_reset_min: int = 6     # 静默这么久 → 算新的一轮，预算重置

    # ── 频率预算（与私聊配额完全隔离，计数带 g: 前缀存在群库）──
    msgs_per_hour: int = 18
    msgs_per_hour_burst: int = 5
    daily_max_total: int = 600
    daily_max_per_member: int = 10
    # ★ 90 秒太长：实测同一个人 30.8% 的发言是**紧接着自己上一条**补一句
    #   （间隔 0 条别人的消息 → 秒级），相邻全体消息中位间隔只有 9 秒。
    #   90 秒会把「我刚说完想再补一句」直接掐死，也让群里变成严格轮播。
    min_gap_member_sec: int = 20

    # ── 单次发言规模 ─────────────────────────────────────────
    # ★ 2026-10-19 按真实群聊数据校准（1366 人群 / 57 万条样本）：
    #   相邻两条消息里 69% 是换人说的，同一人的「一口气」中位 **1** 条、
    #   P75 2 条（单条占 70%）—— 真人在群里几乎不连发，所以一次最多 2 条。
    bubbles_per_turn: int = 2
    bubbles_when_mentioned: int = 3
    # 我发言时挑几个人回。真群里「我发言后 10 分钟内平均 7.8 个不同的人接话」，
    # 但那是千人散去中心；小群取 4 —— 关键是这些人**并发开口**而不是排队。
    responders: int = 4
    responders_all_mention: int = 5  # @全体时最多几个
    # ★ 每个回应者**各自的**开口延迟（秒），不再串行排队。
    #   实测换人接话的间隔：34% 在 5 秒内、60% 在 15 秒内。
    responder_gap_sec: List[int] = field(default_factory=lambda: [2, 18])

    # ── 环境自发话题（群里自己聊起来）────────────────────────
    ambient_enabled: bool = True
    ambient_gap_min: List[int] = field(default_factory=lambda: [8, 25])
    # 有人说完话之后，让另一个人过一小会儿接一句（否则群里「A 说完没人理，
    # 等我开口才有人接 A」——用户实测反馈）。仍受链长/预算/复读拦截约束。
    # ★ 实测「一条消息之后 60 秒内 88% 会有人接」→ 概率拉到 0.8。
    chain_reply_probability: float = 0.80
    chain_reply_gap_sec: List[int] = field(default_factory=lambda: [10, 50])

    # ── 跨角色复读拦截 ───────────────────────────────────────
    dedupe_window: int = 15          # 与最近 N 条群消息比对
    dedupe_overlap: float = 0.5      # 4-gram 重合超过这个 → 丢弃并换人

    # ── 全员禁言解除后的补话 ─────────────────────────────────
    backlog_responders: int = 5
    backlog_span_sec: List[int] = field(default_factory=lambda: [20, 90])

    # ── 私聊转发 / 争宠 ──────────────────────────────────────
    share_probability: float = 0.25
    share_daily_max: int = 1
    jealousy_cooldown_min: int = 30
    jealousy_min_affection: int = 50

    # ── 群里「抖私聊」/「私聊讲群里的动静」──────────────────
    # 用户要的：好友在群里转发/分享我和她的私聊内容；
    # 也会把群里好玩的事单独私聊讲给我听。两者都走群自己的节奏，
    # 各带自己的每日上限，避免变成刷屏。
    ambient_share_probability: float = 0.30   # 自发节奏里改走「抖私聊」的概率
    dm_share_probability: float = 0.15        # 改走「私聊讲群里的动静」的概率
    dm_share_daily_max: int = 1               # 每人每天最多私聊分享几次

    # ── 建群 / 入群 ──────────────────────────────────────────
    max_members: int = 20
    join_request_cooldown_h: int = 24

    # ── 落盘位置（和 memory.* 一样走 cfg.resolve，测试才能改到临时目录）──
    # 不配置的话测试会往用户真实的 data/ 里灌群数据。
    index_path: str = "./data/groups.json"
    dir_path: str = "./data/groups"


@dataclass
class MemoryConfig:
    db_path: str = "./data/companion.db"
    sticker_dir: str = "./data/stickers"
    sticker_index: str = "./data/stickers/index.json"
    recall_top_k: int = 6
    # 排查「图片/表情收不到」时，把原始消息结构落到这里。
    # 单独拎出来是因为测试必须能改到临时目录 ——
    # 否则跑一次验收就会往用户的真实诊断文件里灌一堆测试噪音。
    debug_dir: str = "./data"


@dataclass
class SearchConfig:
    provider: str = ""
    api_key: str = ""
    # 只有 google 需要：Custom Search 引擎 ID
    cx: str = ""
    # 只有 searx 需要：你自己跑的 SearXNG 地址（免 key）
    endpoint: str = ""


@dataclass
class TTSConfig:
    provider: str = ""
    endpoint: str = ""


@dataclass
class Config:
    llm: LLMConfig = field(default_factory=LLMConfig)
    qq: QQConfig = field(default_factory=QQConfig)
    behavior: BehaviorConfig = field(default_factory=BehaviorConfig)
    conversation: ConversationConfig = field(default_factory=ConversationConfig)
    sticker: StickerConfig = field(default_factory=StickerConfig)
    autonomy: AutonomyConfig = field(default_factory=AutonomyConfig)
    group: GroupConfig = field(default_factory=GroupConfig)
    memory: MemoryConfig = field(default_factory=MemoryConfig)
    search: SearchConfig = field(default_factory=SearchConfig)
    tts: TTSConfig = field(default_factory=TTSConfig)
    root: Path = ROOT

    def persona_path(self, name: str) -> Path:
        return self.root / "persona" / name

    def read_persona(self, name: str) -> str:
        p = self.persona_path(name)
        return p.read_text(encoding="utf-8") if p.exists() else ""

    def resolve(self, rel: str) -> Path:
        p = Path(rel)
        return p if p.is_absolute() else (self.root / p)


def _get(d: Dict[str, Any], *keys, default=None):
    cur: Any = d
    for k in keys:
        if not isinstance(cur, dict) or k not in cur:
            return default
        cur = cur[k]
    return cur


def load_config(path: str | os.PathLike | None = None) -> Config:
    p = Path(path) if path else (ROOT / "config.yaml")
    if not p.exists():
        raise FileNotFoundError(
            f"未找到配置文件 {p}。请先 `cp config.example.yaml config.yaml` 并填写。"
        )
    raw = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    cfg = Config(root=ROOT)

    cfg.llm = LLMConfig(
        base_url=_get(raw, "llm", "base_url", default=cfg.llm.base_url),
        api_key=_get(raw, "llm", "api_key", default=""),
        model=_get(raw, "llm", "model", default="deepseek-flash"),
        timeout=int(_get(raw, "llm", "timeout", default=180)),
        temperature=float(_get(raw, "llm", "temperature", default=0.9)),
    )
    # 网页「设置」里保存的覆盖项优先于 config.yaml（开源用户不用改 YAML）
    try:
        from .settings import llm_overrides

        ov = llm_overrides()
        if ov.get("base_url"):
            cfg.llm.base_url = str(ov["base_url"]).rstrip("/")
        if ov.get("api_key"):
            cfg.llm.api_key = str(ov["api_key"])
        if ov.get("model"):
            cfg.llm.model = str(ov["model"])
        if ov.get("timeout"):
            cfg.llm.timeout = int(ov["timeout"])
    except Exception as e:  # noqa: BLE001
        print(f"[config] 读取 data/settings.json 失败：{e!r}")
    cfg.qq = QQConfig(
        self_id=str(_get(raw, "qq", "self_id", default="")),
        owner_id=str(_get(raw, "qq", "owner_id", default="")),
        channel=str(_get(raw, "qq", "channel", default="napcat") or "napcat").lower(),
        server=QQServerConfig(
            listen=str(_get(raw, "qq", "server", "listen", default="0.0.0.0")),
            port=int(_get(raw, "qq", "server", "port", default=8080)),
            token=str(_get(raw, "qq", "server", "token", default="") or ""),
            base_url=str(_get(raw, "qq", "server", "base_url",
                              default="http://127.0.0.1:8080") or "").rstrip("/"),
            heartbeat_sec=int(_get(raw, "qq", "server", "heartbeat_sec", default=25)),
            owner_nickname=str(_get(raw, "qq", "server", "owner_nickname", default="老师")),
            bot_nickname=str(_get(raw, "qq", "server", "bot_nickname", default="星野")),
        ),
        group_mode=str(_get(raw, "qq", "group_mode", default="off") or "off").lower(),
        group_allowlist=[str(g) for g in (_get(raw, "qq", "group_allowlist", default=[]) or [])],
        ws_host=_get(raw, "qq", "ws", "host", default="0.0.0.0"),
        ws_port=int(_get(raw, "qq", "ws", "port", default=6701)),
        ws_path=_get(raw, "qq", "ws", "path", default="/onebot/v11/ws"),
        ws_token=_get(raw, "qq", "ws", "access_token", default="") or "",
        http_base=_get(raw, "qq", "http", "base_url", default="http://127.0.0.1:3000"),
        http_token=_get(raw, "qq", "http", "access_token", default="") or "",
    )
    cfg.behavior = BehaviorConfig(
        outbound_delay_ms=_get(raw, "behavior", "outbound_delay_ms", default=[5000, 20000]),
        chunk_delay_ms=_get(raw, "behavior", "chunk_delay_ms", default=[5000, 20000]),
        sticker_delay_ms=_get(raw, "behavior", "sticker_delay_ms", default=[4000, 9000]),
        split_long_reply=bool(_get(raw, "behavior", "split_long_reply", default=True)),
        split_threshold=int(_get(raw, "behavior", "split_threshold", default=28)),
        max_chunks=int(_get(raw, "behavior", "max_chunks", default=3)),
        bubble_delay_ms=_get(raw, "behavior", "bubble_delay_ms", default=[5000, 20000]),
        short_bubble_delay_ms=_get(raw, "behavior", "short_bubble_delay_ms",
                                    default=[4000, 12000]),
        long_bubble_delay_ms=_get(raw, "behavior", "long_bubble_delay_ms",
                                  default=[7000, 22000]),
        merge_window_sec=float(_get(raw, "behavior", "merge_window_sec", default=9.0)),
        merge_max_wait_sec=float(_get(raw, "behavior", "merge_max_wait_sec", default=30.0)),
        merge_max_msgs=int(_get(raw, "behavior", "merge_max_msgs", default=10)),
        sticker_only_reply_prob=float(_get(raw, "behavior", "sticker_only_reply_prob",
                                           default=0.35)),
    )
    cfg.conversation = ConversationConfig(
        enabled=bool(_get(raw, "conversation", "enabled", default=True)),
        active_window_min=int(_get(raw, "conversation", "active_window_min", default=15)),
        followup_delay_sec=_get(raw, "conversation", "followup_delay_sec", default=[60, 180]),
        max_bot_turns_without_reply=int(
            _get(raw, "conversation", "max_bot_turns_without_reply", default=5)),
        max_followups_per_topic=int(
            _get(raw, "conversation", "max_followups_per_topic", default=3)),
        deep_max_bot_turns=int(
            _get(raw, "conversation", "deep_max_bot_turns", default=8)),
        deep_max_followups=int(
            _get(raw, "conversation", "deep_max_followups", default=8)),
        quiet_hours_max_turns=int(
            _get(raw, "conversation", "quiet_hours_max_turns", default=1)),
        energy_threshold=int(_get(raw, "conversation", "energy_threshold", default=25)),
        max_burst_bubbles=int(
            _get(raw, "conversation", "max_burst_bubbles", default=5)),
        deep_max_burst_bubbles=int(
            _get(raw, "conversation", "deep_max_burst_bubbles", default=9)),
        followup_backoff_sec=[
            [int(x) for x in (step if isinstance(step, list) else [120, 300])]
            for step in (_get(raw, "conversation", "followup_backoff_sec",
                              default=[[120, 300], [600, 2400]]) or [])
        ] or [[120, 300], [600, 2400]],
        max_probes_per_topic=int(
            _get(raw, "conversation", "max_probes_per_topic", default=1)),
        reopen_delay_sec=_get(raw, "conversation", "reopen_delay_sec",
                              default=[1200, 5400]),
        max_reopens=int(_get(raw, "conversation", "max_reopens", default=2)),
    )
    cfg.sticker = StickerConfig(
        enabled=bool(_get(raw, "sticker", "enabled", default=True)),
        base_probability=float(_get(raw, "sticker", "base_probability", default=0.50)),
        daily_max=int(_get(raw, "sticker", "daily_max", default=15)),
        energy_threshold=int(_get(raw, "sticker", "energy_threshold", default=40)),
        extra_dirs=[str(d) for d in (_get(raw, "sticker", "extra_dirs", default=[]) or [])],
        min_gap_min=int(_get(raw, "sticker", "min_gap_min", default=6)),
        max_per_turn=int(_get(raw, "sticker", "max_per_turn", default=4)),
        steal_enabled=bool(_get(raw, "sticker", "steal_enabled", default=True)),
        steal_probability=float(_get(raw, "sticker", "steal_probability", default=0.55)),
        steal_daily_max=int(_get(raw, "sticker", "steal_daily_max", default=8)),
        steal_from_groups=bool(_get(raw, "sticker", "steal_from_groups", default=False)),
    )
    cfg.autonomy = AutonomyConfig(
        enabled=bool(_get(raw, "autonomy", "enabled", default=True)),
        base_interval_min=int(_get(raw, "autonomy", "heartbeat", "base_interval_min", default=210)),
        jitter_min=int(_get(raw, "autonomy", "heartbeat", "jitter_min", default=60)),
        rhythm_instant=_get(raw, "autonomy", "rhythm", "instant", default=[1, 8]),
        rhythm_near=_get(raw, "autonomy", "rhythm", "near", default=[20, 120]),
        rhythm_normal=_get(raw, "autonomy", "rhythm", "normal", default=[120, 480]),
        rhythm_long=_get(raw, "autonomy", "rhythm", "long", default=[720, 2880]),
        # 权重按「马上/近/常/远」四档
        rhythm_weights=_get(raw, "autonomy", "rhythm", "weights",
                            default=[0.30, 0.32, 0.27, 0.11]),
        state_influence=float(_get(raw, "autonomy", "state_influence", default=0.5)),
        skip_probability=float(_get(raw, "autonomy", "skip_probability", default=0.15)),
        first_contact_max_min=int(
            _get(raw, "autonomy", "first_contact_max_min", default=120)),
        quiet_hours=_get(raw, "autonomy", "quiet_hours", default=["00:30", "08:30"]),
        min_gap_min=int(_get(raw, "autonomy", "min_gap_min", default=45)),
        cold_streak_limit=int(_get(raw, "autonomy", "cold_streak_limit", default=3)),
        energy_threshold=int(_get(raw, "autonomy", "energy_threshold", default=30)),
        daily_max=int(_get(raw, "autonomy", "daily_max", default=5)),
        silence_min=int(_get(raw, "autonomy", "silence_min", default=25)),
        silence_growth=float(_get(raw, "autonomy", "silence_growth", default=1.2)),
        silence_max_min=int(_get(raw, "autonomy", "silence_max_min", default=60)),
        busy_grace_min=int(_get(raw, "autonomy", "busy_grace_min", default=45)),
        checkin_kinds=[str(x) for x in (_get(raw, "autonomy", "checkin_kinds",
                                             default=["miss", "mood", "miss", "miss"]) or [])],
        digest_enabled=bool(_get(raw, "autonomy", "digest_enabled", default=True)),
        digest_interval_min=int(_get(raw, "autonomy", "digest_interval_min", default=90)),
        digest_max_share_per_day=int(_get(raw, "autonomy", "digest_max_share_per_day",
                                          default=3)),
        digest_threshold=float(_get(raw, "autonomy", "digest_threshold", default=0.42)),
        greet_on_start=bool(_get(raw, "autonomy", "greet_on_start", default=True)),
        greet_delay_sec=int(_get(raw, "autonomy", "greet_delay_sec", default=20)),
        greet_wait_max_sec=int(_get(raw, "autonomy", "greet_wait_max_sec", default=3600)),
    )
    cfg.group = GroupConfig(
        enabled=bool(_get(raw, "group", "enabled", default=True)),
        ai_chain_max=int(_get(raw, "group", "ai_chain_max", default=5)),
        ai_no_owner_max=int(_get(raw, "group", "ai_no_owner_max", default=8)),
        chain_cooldown_min=int(_get(raw, "group", "chain_cooldown_min", default=15)),
        round_gap_reset_min=int(_get(raw, "group", "round_gap_reset_min", default=6)),
        msgs_per_hour=int(_get(raw, "group", "msgs_per_hour", default=18)),
        msgs_per_hour_burst=int(_get(raw, "group", "msgs_per_hour_burst", default=5)),
        daily_max_total=int(_get(raw, "group", "daily_max_total", default=600)),
        daily_max_per_member=int(_get(raw, "group", "daily_max_per_member", default=10)),
        min_gap_member_sec=int(_get(raw, "group", "min_gap_member_sec", default=20)),
        bubbles_per_turn=int(_get(raw, "group", "bubbles_per_turn", default=2)),
        bubbles_when_mentioned=int(_get(raw, "group", "bubbles_when_mentioned", default=3)),
        responders=int(_get(raw, "group", "responders", default=4)),
        responders_all_mention=int(_get(raw, "group", "responders_all_mention", default=5)),
        responder_gap_sec=_get(raw, "group", "responder_gap_sec", default=[2, 18]),
        ambient_enabled=bool(_get(raw, "group", "ambient_enabled", default=True)),
        ambient_gap_min=_get(raw, "group", "ambient_gap_min", default=[8, 25]),
        chain_reply_probability=float(
            _get(raw, "group", "chain_reply_probability", default=0.80)),
        chain_reply_gap_sec=_get(raw, "group", "chain_reply_gap_sec",
                                 default=[10, 50]),
        dedupe_window=int(_get(raw, "group", "dedupe_window", default=15)),
        dedupe_overlap=float(_get(raw, "group", "dedupe_overlap", default=0.5)),
        backlog_responders=int(_get(raw, "group", "backlog_responders", default=5)),
        backlog_span_sec=_get(raw, "group", "backlog_span_sec", default=[20, 90]),
        share_probability=float(_get(raw, "group", "share_probability", default=0.25)),
        share_daily_max=int(_get(raw, "group", "share_daily_max", default=1)),
        jealousy_cooldown_min=int(_get(raw, "group", "jealousy_cooldown_min", default=30)),
        jealousy_min_affection=int(_get(raw, "group", "jealousy_min_affection", default=50)),
        ambient_share_probability=float(
            _get(raw, "group", "ambient_share_probability", default=0.30)),
        dm_share_probability=float(
            _get(raw, "group", "dm_share_probability", default=0.15)),
        dm_share_daily_max=int(
            _get(raw, "group", "dm_share_daily_max", default=1)),
        max_members=int(_get(raw, "group", "max_members", default=20)),
        join_request_cooldown_h=int(_get(raw, "group", "join_request_cooldown_h", default=24)),
        index_path=str(_get(raw, "group", "index_path", default="./data/groups.json")),
        dir_path=str(_get(raw, "group", "dir_path", default="./data/groups")),
    )
    cfg.memory = MemoryConfig(
        db_path=_get(raw, "memory", "db_path", default="./data/companion.db"),
        sticker_dir=_get(raw, "memory", "sticker_dir", default="./data/stickers"),
        sticker_index=_get(raw, "memory", "sticker_index", default="./data/stickers/index.json"),
        recall_top_k=int(_get(raw, "memory", "recall_top_k", default=6)),
        debug_dir=_get(raw, "memory", "debug_dir", default="./data") or "./data",
    )
    cfg.search = SearchConfig(
        provider=_get(raw, "search", "provider", default="") or "",
        api_key=_get(raw, "search", "api_key", default="") or "",
        cx=_get(raw, "search", "cx", default="") or "",
        endpoint=_get(raw, "search", "endpoint", default="") or "",
    )
    cfg.tts = TTSConfig(
        provider=_get(raw, "tts", "provider", default="") or "",
        endpoint=_get(raw, "tts", "endpoint", default="") or "",
    )

    if not cfg.llm.api_key:
        raise ValueError("config.yaml 里 llm.api_key 未填写。")
    # 模型名提示：只有「官方 DeepSeek 直连」才必须叫 deepseek-flash；
    # 走自建网关（OpenCode-Go-Proxy 等）时上游只认自己的小写 id，
    # 这时候再念叨 deepseek-flash 只是噪音。
    _official = "api.deepseek.com" in str(cfg.llm.base_url or "")
    if _official and cfg.llm.model != "deepseek-flash":
        print(
            f"[warn] llm.model = {cfg.llm.model!r}。官方直连推荐 'deepseek-flash'。"
        )
    if cfg.llm.model == "deepseek-v4-pro":
        print("[warn] deepseek-v4-pro 是纯文本模型，不支持识图。")
    return cfg
