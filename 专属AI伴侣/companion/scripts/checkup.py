"""伴侣体检：把内部状态打出来看。

用法（在 companion 目录下）：
    .venv\\Scripts\\python.exe -m scripts.checkup
    .venv\\Scripts\\python.exe -m scripts.checkup --turns 30   # 多看几条对话

看什么：
  - 情绪 / 关系数值有没有跟着对话动（这是「感性」是否真在工作的唯一证据）
  - 画像、情节记忆、兴趣图谱有没有在长
  - 主动消息的计数器状态 + 下一次排期
  - 表情包库规模

⚠️ 这个文件以前叫 inspect.py —— **跟标准库的 inspect 撞名了**。
直接跑 `python scripts/preflight.py` 时 Python 会把 scripts/ 放进 sys.path[0]，
于是 asyncio 想 import 标准库 inspect 却拿到这个文件，直接崩。
改名的同时也给所有脚本加了防御，见下面的 sys.path 处理。
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
_HERE = Path(__file__).resolve().parent
# 把 scripts/ 自己从 sys.path 里摘掉，避免它里面的文件名顶掉标准库
sys.path[:] = [p for p in sys.path if Path(p or ".").resolve() != _HERE]
sys.path.insert(0, str(ROOT))

from app.config import load_config  # noqa: E402
from app.store import Store  # noqa: E402


def ts(v: float) -> str:
    return datetime.fromtimestamp(v).strftime("%m-%d %H:%M")


def ago(v: float) -> str:
    if not v:
        return "从未"
    d = time.time() - v
    if d < 60:
        return f"{d:.0f} 秒前"
    if d < 3600:
        return f"{d / 60:.0f} 分钟前"
    if d < 86400:
        return f"{d / 3600:.1f} 小时前"
    return f"{d / 86400:.1f} 天前"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--turns", type=int, default=12, help="显示多少条对话")
    ap.add_argument("--memories", type=int, default=10, help="显示多少条记忆")
    args = ap.parse_args()

    cfg = load_config()
    st = Store(cfg.resolve(cfg.memory.db_path))

    print("=" * 62)
    print(" 伴侣体检")
    print("=" * 62)

    # ---- 身份 ----
    print(f"\n机器人 QQ : {cfg.qq.self_id}")
    print(f"主人 QQ   : {cfg.qq.owner_id}")
    print(f"群聊策略  : {cfg.qq.group_mode}"
          + (f"（白名单 {cfg.qq.group_allowlist}）" if cfg.qq.group_mode == "allowlist" else ""))
    print(f"模型      : {cfg.llm.model}")

    # ---- 情绪 / 关系 ----
    e = st.kv_get("emotion_state")
    r = st.kv_get("relationship_state")
    print("\n--- 情绪状态 ---")
    if not e:
        print("  （还没有数据，说明还没聊过）")
    else:
        print(f"  效价 valence    : {e.get('valence', 0):+.1f}   (-100 低落 ~ +100 开心)")
        print(f"  唤醒 arousal    : {e.get('arousal', 0):.1f}")
        print(f"  社交电量 energy : {e.get('energy', 0):.1f}")
        print(f"  焦虑 anxiety    : {e.get('anxiety', 0):.1f}")
        print(f"  孤独 loneliness : {e.get('loneliness', 0):.1f}")
        print(f"  最后更新        : {ago(e.get('updated_at', 0))}")

    print("\n--- 关系状态（只增为主）---")
    if not r:
        print("  （还没有数据）")
    else:
        names = {
            "trust": "信任", "security": "安全感", "intimacy": "亲密",
            "attachment": "依恋", "possessiveness": "占有欲",
        }
        for k, label in names.items():
            print(f"  {label:<6}: {r.get(k, 0):.1f}")

    # ---- 画像 ----
    prof = st.profile_all()
    print(f"\n--- 画像（{len(prof)} 条，自动从对话里抽）---")
    if not prof:
        print("  （还没有。多聊几轮，它会开始记你的偏好）")
    for k, v in list(prof.items())[:20]:
        print(f"  {k}：{v}")

    # ---- 记忆 ----
    mems = st.all_memories(limit=args.memories)
    total_mem = len(st.all_memories(limit=5000))
    print(f"\n--- 记忆（共 {total_mem} 条，显示最近 {len(mems)} 条）---")
    if not mems:
        print("  （还没有）")
    for m in mems:
        emo = f"［{m['emotion'].get('label', '')}］" if m.get("emotion") else ""
        print(f"  [{ts(m['ts'])}] ({m['kind']}) {m['text'][:56]}{emo}")

    # ---- 兴趣图谱 ----
    terms = st.kv_get("interest_terms") or {}
    top = sorted(terms.items(), key=lambda kv: kv[1], reverse=True)[:10]
    print(f"\n--- 兴趣图谱（共 {len(terms)} 个词）---")
    if not top:
        print("  （还没有。它靠这个去自主浏览）")
    for k, w in top:
        print(f"  {k}  ({w:.1f})")

    # ---- 事件 ----
    evs = st.recent_events(8, include_flagged=True)
    flagged = [x for x in evs if x["flagged"]]
    print(f"\n--- 最近事件（显示 {len(evs)} 条）---")
    for x in evs:
        mark = "  ⚠️ 风险标记" if x["flagged"] else ""
        print(f"  [{ts(x['ts'])}] ({x['kind']}) {x['text'][:50]}{mark}")

    # ---- 对话 ----
    turns = st.recent_turns(args.turns)
    print(f"\n--- 最近对话（{len(turns)} 条）---")
    for t in turns:
        who = "你" if t["role"] == "user" else "它"
        body = t["text"].replace("\n", " ")[:70]
        print(f"  {ts(t['ts'])} {who} > {body}")

    # ---- 主动消息计数 ----
    print("\n--- 主动性 ---")
    print(f"  上次主动开口 : {ago(st.counter_get('last_spoke_ts', 0))}")
    print(f"  上次收到回复 : {ago(st.counter_get('last_reply_ts', 0))}")
    print(f"  连续冷场次数 : {int(st.counter_get('cold_streak', 0))}"
          f"  (达到 {cfg.autonomy.cold_streak_limit} 次会自动拉长间隔)")
    today = f"proactive_{datetime.now():%Y-%m-%d}"
    print(f"  今日主动次数 : {int(st.counter_get(today, 0))} / {cfg.autonomy.daily_max}")
    print(f"  免打扰时段   : {cfg.autonomy.quiet_hours[0]} ~ {cfg.autonomy.quiet_hours[1]}")

    # 真实节奏：读心跳写下来的排期，别再显示那个已经废弃的固定间隔
    nxt = st.counter_get("next_proactive_at", 0.0)
    print("\n  节奏（三档混合，不是固定间隔）")
    print(f"    近 {cfg.autonomy.rhythm_near} 分钟 × 权重 {cfg.autonomy.rhythm_weights[0]}")
    print(f"    常 {cfg.autonomy.rhythm_normal} 分钟 × 权重 {cfg.autonomy.rhythm_weights[1]}")
    print(f"    远 {cfg.autonomy.rhythm_long} 分钟 × 权重 {cfg.autonomy.rhythm_weights[2]}")
    print(f"    情绪影响 {cfg.autonomy.state_influence}｜顺延概率 {cfg.autonomy.skip_probability:.0%}")
    if nxt:
        left = (nxt - time.time()) / 60.0
        when = datetime.fromtimestamp(nxt).strftime("%m-%d %H:%M")
        if left <= 0:
            print(f"  下次主动     : 已到点（{when}）—— 心跳下一轮就会判断要不要开口")
        else:
            print(f"  下次主动     : {left:.0f} 分钟后（{when}）")
    else:
        print("  下次主动     : 未排期 —— 服务没在跑，或心跳没启动")

    # ---- 表情包库 ----
    from app.sticker import StickerLibrary
    lib = StickerLibrary(cfg.resolve(cfg.memory.sticker_index))
    print("\n--- 表情包库 ---")
    if lib.available:
        from collections import Counter
        emos = Counter(e for it in lib.items for e in it.get("emotions", []))
        print(f"  已入库 {len(lib.items)} 张，覆盖 {len(emos)} 种情绪")
        print(f"  最多的几种：{dict(emos.most_common(8))}")
    else:
        print("  未建库（不影响聊天，只是不会发表情包）")

    print("\n" + "=" * 62)
    st.close()


if __name__ == "__main__":
    main()
