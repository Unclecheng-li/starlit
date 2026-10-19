# companion · 可运行代码

Starlit（星伴）的核心实现。项目总览、功能说明和快速开始见[上级 README](../README.md)。
这份文件只讲**怎么跑起来、代码在哪、测试怎么用**。

---

## 目录结构

```
companion/
├── config.example.yaml      # 复制成 config.yaml 后填
├── config.yaml              # 你的配置（含 API Key，已被 .gitignore 排除）
├── analyze_chat_habits.py   # 真实聊天记录 → 人类习惯量化（需 pandas/openpyxl）
├── requirements.txt
├── persona/                 # 人格 · 世界观 · 边界 · 兴趣（纯文本，改完即生效）
│   ├── persona.md           # 主人格卡
│   ├── world.md             # 世界观设定
│   ├── boundaries.md        # 红线
│   ├── interests.md         # 兴趣种子（聊天里会自动扩充）
│   └── characters/<角色>/   # 新增角色各自的人格卡与兴趣
├── app/
│   ├── main.py              # 入口：通道 + 后台调度 + 主管线
│   ├── config.py            # 配置加载与默认值
│   ├── store.py             # SQLite 持久层（kv / 画像 / 事件 / 记忆 / 计数器）
│   ├── llm.py               # OpenAI 兼容客户端（并发限流 + 僵尸连接自愈）
│   ├── perceive.py          # 情绪打标 · 图片理解 · 长截图压缩
│   ├── state.py             # 情绪 / 关系 / 社交电量状态机
│   ├── memory.py            # 三层记忆 + 本地向量检索
│   ├── think.py             # 分析通道 + 表达通道（含气泡协议）
│   ├── act.py               # 发送（文字 / 表情包 / 节奏缩放 / 按会话互斥）
│   ├── sticker.py           # 表情包库检索 · 表情包判定 · 偷图
│   ├── traits.py            # 热情 / 好感 → 主动频率与回复节奏
│   ├── characters.py        # 角色注册表
│   ├── guest.py             # 新增角色的完整运行时
│   ├── persona_builder.py   # 联网搜索 → 人设蒸馏
│   ├── settings.py          # 全局设置（网页里填的 API Key 落在这里）
│   ├── channel/
│   │   ├── napcat.py        # OneBot 11 反向 WS
│   │   ├── onebot_server.py # 自托管 OneBot 11 服务端 + HTTP API + 静态资源
│   │   └── console.py       # 本地终端通道（不连 QQ 也能跑全管线）
│   └── autonomy/
│       ├── suppress.py      # 六层抑制链
│       ├── heartbeat.py     # 心跳调度（四档拟人节奏）
│       ├── conversation.py  # 活跃会话接话 / 话题重启
│       ├── digest.py        # 自主浏览 + 选择性分享
│       └── search.py        # 搜索 Provider 接口
├── data/
│   ├── webclient/           # 自建网页客户端（QQ 风格单页）
│   ├── characters.json      # 角色注册表
│   └── …                    # 运行时生成：DB / 头像 / 图库 / 参数（已被 .gitignore 排除）
├── scripts/
│   ├── preflight.py         # 启动前自检（依赖 / 配置 / 端口，并真测一次识图）
│   ├── checkup.py           # 体检：情绪 / 关系数值、记忆、主动排期、图库规模
│   ├── launch_all.py        # 一键启动（按顺序起：搜索 → 伴侣 → QQ 通道）
│   ├── stop_all.py          # 一键停止
│   ├── napcat_api.py        # NapCat HTTP 接口封装（主动发消息用）
│   ├── qr_login.py          # 二维码登录
│   ├── ingest_stickers.py   # 表情包入库
│   ├── run_searxng.py       # 起本地 SearXNG
│   └── test_search.py       # 搜索服务自检
└── tests/
    ├── mock_llm.py          # 离线假模型
    ├── run_tests.py         # 458 项离线回归测试
    └── acceptance_stage0.py # 44 项端到端集成验收
```

---

## 跑法

| 命令 | 用途 |
|---|---|
| `python -m scripts.preflight` | **启动前自检**：依赖 / 配置 / 端口，并真的测一次识图 |
| `python -m scripts.checkup` | **体检**：情绪 / 关系数值、记忆、主动排期、图库规模 |
| `python -m app.main --console` | **本地终端对话**（不连 QQ）。调人格、看情绪变化，最快 |
| `python tests/run_tests.py` | **离线回归测试**：458 项，不需要 API Key、不联网 |
| `python tests/acceptance_stage0.py` | **端到端验收**：44 项，模拟 NapCat 跑真 socket |
| `python -m app.main` | 正式运行（通道由 `config.yaml` 的 `qq.channel` 决定） |

首次运行：

```bash
python -m venv .venv
.venv\Scripts\activate            # Linux/macOS: source .venv/bin/activate
pip install -r requirements.txt
copy config.example.yaml config.yaml
# 填 llm.api_key 与 qq.self_id / qq.owner_id（或起来后在网页「设置」里填）
```

控制台模式支持 `:img <路径>` 模拟发图、`:quit` 退出。

---

## 测试覆盖什么

离线测试**不需要 API Key、不联网**，测的是**管线接线**而不是模型质量：

| 组 | 覆盖 |
|---|---|
| 状态机 | 事件增量、衰减、互动消耗、长时间无互动后的孤独度、手动改情绪 |
| 记忆 | 向量维度与自相似、检索命中、画像读写、兴趣排序、事件落库 |
| 消息解析 | OneBot 数组格式 + CQ 码格式、`@我` 识别（不误判别人的 @） |
| 消息段 | 表情包 `sub_type=1` / 普通图 `0`、Windows 路径转 `file:///` |
| 抑制链 | 六层**逐层单独验证** + 跨天时段 |
| 完整管线 | `handle()` 全链路：四通道都被走到、状态变化、画像/情节/兴趣落库、风险信号 |
| 指令 | `/state` `/mood` `/why` `/poke` `/next`，以及非主人私聊、群聊未 @ 的忽略 |
| 自主浏览 | 搜索未配置时安全跳过不崩、兴趣抽取写回图谱 |
| 表情包 | 空库降级、索引加载、情绪匹配命中 |
| 多角色 | 路由隔离、独立记忆、互不串台 |
| 关系参数 | 热情/好感 → 频率与节奏的映射、边界值、提示词内容 |
| 撤回 / 多端 | 稳定消息 ID、撤回删库并广播、跨端已读 |

集成验收还会真跑一遍：反向 WS 握手、鉴权、事件解析、权限过滤、视觉通道、
断线重连、出站失败容错、活跃会话接话落库。

---

## 调试指令（私聊里发）

| 指令 | 作用 |
|---|---|
| `/state` | 打印当前情绪 / 关系 / 社交电量 |
| `/why` | 解释上一轮为什么这么回（含分析通道输出） |
| `/poke` | 手动触发一次心跳，看抑制链逐层结果 |
| `/next` | 下一次主动排期、今日额度、当前关系参数 |
| `/mood <词>` | 手动改情绪，用于测试 |

---

## 踩过的坑（改代码前值得一看）

- **别把 `scripts/` 里的文件起成跟标准库同名的名字。** 直接跑
  `python scripts/xxx.py` 时 Python 会把 `scripts/` 放进 `sys.path[0]`，
  同名文件会顶掉标准库（我们踩过：`inspect.py` 让 `asyncio` 直接崩）。
- **`conversation.cfg` / `autonomy.cfg` 是派生副本。** 它们由 `traits.py` 按
  「热情 / 好感」算出来，运行时读的是 `comp.conversation.cfg`；
  直接改 `cfg.conversation` 不会生效。
- **接话参数别调成几十秒。** `followup_delay_sec` 的语义是「对方没回、
  过了一会儿又想起一句」，是分钟级的；调到秒级会变成高频独白引擎。
- **发送延迟是「总延迟目标」不是「额外等待」。** 合并等待与模型推理花掉的时间
  会从目标里扣，不要在处理完之后再叠加固定延迟。
- **LLM 重试前必须重建连接。** 网络抖动的僵尸 TCP 会让重试挂在死连接上，
  一次调用链能拖到分钟级；`llm.py` 里的 close + 重建就是为这个加的。

---

## 配置速查

`config.yaml` 里最常改的几项：

| 键 | 说明 |
|---|---|
| `llm.model` | 必须支持图片输入（DeepSeek 这边是 `deepseek-flash`） |
| `qq.channel` | `napcat`（真 QQ）或 `onebot-server`（自托管，网页客户端） |
| `qq.group_mode` | 群聊策略，默认 `off` |
| `autonomy.quiet_hours` | 免打扰时段 |
| `autonomy.rhythm.*` | 四档主动节奏与权重 |
| `conversation.active_window_min` | 「还在聊」的窗口长度 |
| `behavior.*_delay_ms` | 各类发送延迟（按真实聊天记录校准过，改前先看注释） |
| `sticker.*` | 表情包频率与偷图策略 |
| `search.provider` | 留空则跳过联网，不会返回假数据 |

关系参数（热情 / 好感）不在这个文件里：它们按角色存在
`data/character_traits.json`，网页「聊天设置」里调。

---

## 诚实声明

- `search.provider` 未配置时，自主浏览会**跳过**并在日志里说明，不会返回假数据。
- TTS 接口留好了，**尚未接入**。
- 仓库里**不含**表情包图库，需要自己用 `scripts/ingest_stickers.py` 灌。
