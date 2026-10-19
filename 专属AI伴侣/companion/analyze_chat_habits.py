"""从真实聊天记录（QQ 导出的 xlsx）里提取「人类聊天习惯」的量化特征。

用法（在 companion 目录下）：
    .venv\\Scripts\\python.exe analyze_chat_habits.py            # 全量聚合分析
    .venv\\Scripts\\python.exe analyze_chat_habits.py --per-chat # 逐会话明细

兼容两种导出格式：
  旧版列：时间 / 消息内容（回复类内嵌 [回复消息]@xx 前缀）
  新版列：时间（北京时间）/ 消息内容 / 引用原文（引用分离，正文干净）

分析对象（聚合）：
  - 私聊·真人伙伴（全部好友合并）—— vol 要模仿的对象
  - 私聊·用户 —— vol 的对话对象
  - 群聊·全体 —— 整体人类基线
"""
from __future__ import annotations

import glob
import os
import re
import sys
from collections import Counter
from pathlib import Path

import pandas as pd

# 聊天记录导出目录（QQ 导出的 xlsx）。默认取桌面的 data，可用环境变量覆盖。
DATA_DIR = Path(os.environ.get("VOL_CHAT_DATA")
                or Path.home() / "Desktop" / "data")
# 你自己的 QQ：用来区分「我」和「好友」。与 config.yaml 的 qq.owner_id 保持一致。
USER_QQ = os.environ.get("VOL_OWNER_QQ", "10002")

# 媒体占位符（[图片:xxx] / [image: xxx] 之类），文本分析前剥掉
_MEDIA_PAT = re.compile(
    r"\[(?:图片|表情|视频|文件|语音|转发消息|image|flash|face):[^\]]*\]",
    re.IGNORECASE,
)
_REPLY_PAT = re.compile(r"^\[回复消息\]@\S+\s*")
_EMOJI_PAT = re.compile(
    "[" "\U0001F300-\U0001FAFF" "\U00002600-\U000027BF" "\u2764\u2763\u2728\u2757\u2753\u2755]+"
)


def clean_text(s: str) -> str:
    if not isinstance(s, str):
        return ""
    s = _REPLY_PAT.sub("", s)
    s = _MEDIA_PAT.sub("", s)
    return s.strip()


def pct(x: float) -> str:
    return f"{x * 100:.0f}%"


def quantiles(xs, q):
    if not xs:
        return float("nan")
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(q * len(xs)))]


class Side:
    """一方（聚合角色）的习惯统计。"""

    def __init__(self, name: str):
        self.name = name
        self.msgs = []          # (time, text) 按时间排好（跨会话拼接）
        self.media_only = 0
        self.total_rows = 0

    def add(self, t, text: str, media_only: bool):
        self.msgs.append((t, text))
        self.total_rows += 1
        if media_only:
            self.media_only += 1

    # ---------- 跨会话：burst 只在同一会话内统计 ----------
    def add_burst_frame(self, t):
        self.msgs.append((t, None))     # None = 会话边界，切断 burst

    def _segments(self):
        """按会话边界切段。"""
        seg, out = [], []
        for t, text in self.msgs:
            if text is None:
                if seg:
                    out.append(seg)
                seg = []
            else:
                seg.append((t, text))
        if seg:
            out.append(seg)
        return out

    def len_stats(self) -> str:
        lens = [len(t) for _, t in self.msgs if t]
        if not lens:
            return "无文本"
        return (f"中位 {quantiles(lens, 0.5):.0f} 字 | P75 {quantiles(lens, 0.75):.0f} | "
                f"P90 {quantiles(lens, 0.90):.0f} | ≤3字 {pct(sum(1 for l in lens if l <= 3) / len(lens))} | "
                f"≥30字 {pct(sum(1 for l in lens if l >= 30) / len(lens))}")

    def burst_stats(self, gap_sec: float = 90.0) -> str:
        bursts, cur, last_t = [], 0, None
        for seg in self._segments():
            cur, last_t = 0, None
            for t, _ in seg:
                if last_t is not None and (t - last_t).total_seconds() <= gap_sec:
                    cur += 1
                else:
                    if cur:
                        bursts.append(cur)
                    cur = 1
                last_t = t
            if cur:
                bursts.append(cur)
        if not bursts:
            return "无"
        n = len(bursts)
        dist = Counter(min(b, 5) for b in bursts)
        return (f"中位 {quantiles(bursts, 0.5):.0f} 条 | P75 {quantiles(bursts, 0.75):.0f} | "
                f"1条 {pct(dist[1] / n)} | 2条 {pct(dist[2] / n)} | 3条 {pct(dist[3] / n)} | "
                f"4条 {pct(dist[4] / n)} | 5+条 {pct(dist[5] / n)}")

    def bubble_gap(self) -> str:
        gaps, last_t = [], None
        for seg in self._segments():
            last_t = None
            for t, _ in seg:
                if last_t is not None:
                    d = (t - last_t).total_seconds()
                    if 0 <= d <= 90:
                        gaps.append(d)
                last_t = t
        if not gaps:
            return "无"
        return (f"中位 {quantiles(gaps, 0.5):.0f}s | P25 {quantiles(gaps, 0.25):.0f}s | "
                f"P75 {quantiles(gaps, 0.75):.0f}s")

    def question_rate(self) -> str:
        texts = [t for _, t in self.msgs if t]
        if not texts:
            return "-"
        return pct(sum(1 for t in texts if t.rstrip().endswith(("？", "?"))) / len(texts))

    def tail_marks(self) -> str:
        texts = [t for _, t in self.msgs if t]
        if not texts:
            return "-"
        c = Counter()
        for t in texts:
            t = t.rstrip()
            if not t:
                continue
            for mark in ("。", "！", "？", "?", "~", "～", "…", "，", "了", "吧", "呢", "啊", "哈"):
                if t.endswith(mark):
                    c[mark] += 1
                    break
            else:
                c["无标点"] += 1
        return " ".join(f"{k}{pct(v / len(texts))}" for k, v in c.most_common(6))

    def emoji_stats(self) -> str:
        texts = [t for _, t in self.msgs if t]
        if not texts:
            return "-"
        c = Counter()
        for t in texts:
            for e in _EMOJI_PAT.findall(t):
                c[e] += 1
        hit = sum(1 for t in texts if _EMOJI_PAT.search(t))
        top = " ".join(f"{k}×{v}" for k, v in c.most_common(8))
        return f"出现率 {pct(hit / len(texts))} | 高频: {top}"

    def top_phrases(self, n: int = 15) -> str:
        short = [t for _, t in self.msgs if t and len(t) <= 8]
        c = Counter(short)
        return " | ".join(f"{k}×{v}" for k, v in c.most_common(n))

    def openers(self, n: int = 10) -> str:
        """开场白：同一会话内隔 >2h 之后的第一条（重新开话）。"""
        c = Counter()
        for seg in self._segments():
            last_t = None
            for t, text in seg:
                if last_t is not None and (t - last_t).total_seconds() > 7200:
                    if text and len(text) <= 12:
                        c[text] += 1
                last_t = t
        return " | ".join(f"{k}×{v}" for k, v in c.most_common(n))

    def hourly(self) -> str:
        c = Counter(t.hour for t, _ in self.msgs if _)
        total = sum(c.values())
        if not total:
            return "-"
        peak = c.most_common(3)
        night = sum(v for h, v in c.items() if h < 6)
        return (f"高峰 {[(f'{h}点', pct(v/total)) for h, v in peak]} | "
                f"0-6点占比 {pct(night/total)}")

    def report(self) -> str:
        lines = [f"── {self.name}（{self.total_rows} 条）"]
        lines.append(f"  长度: {self.len_stats()}")
        lines.append(f"  连发: {self.burst_stats()}")
        lines.append(f"  连发内部间隔: {self.bubble_gap()}")
        lines.append(f"  疑问句占比: {self.question_rate()}")
        lines.append(f"  结尾习惯: {self.tail_marks()}")
        lines.append(f"  纯媒体占比: {pct(self.media_only / max(1, self.total_rows))}")
        lines.append(f"  时段: {self.hourly()}")
        lines.append(f"  高频短句: {self.top_phrases()}")
        lines.append(f"  重开话开场: {self.openers()}")
        return "\n".join(lines)


def load(fp: Path) -> pd.DataFrame:
    df = pd.read_excel(fp)
    tcol = "时间（北京时间）" if "时间（北京时间）" in df.columns else "时间"
    ts = pd.to_datetime(df[tcol])
    # 旧导出是 UTC（带 Z）→ tz-aware；新导出是本地时间 → naive。
    # 全部统一成 naive，否则跨文件做时间差会炸。
    if getattr(ts.dt, "tz", None) is not None:
        ts = ts.dt.tz_localize(None)
    df["时间"] = ts
    if "是否撤回" in df.columns:
        col = df["是否撤回"]
        # 旧导出是「是/否」字符串；新导出整列为空（NaN = 没撤回）
        if col.notna().any():
            df = df[col.isna() | (col.astype(str) == "否")]
    df = df.sort_values("时间").reset_index(drop=True)
    return df


def qq_str(v) -> str:
    try:
        return str(int(float(v)))
    except (TypeError, ValueError):
        return ""


def topic_reopen_report(timeline) -> None:
    """话题重启分析：话题聊死后，真人怎么把它救活 / 重新开口。

    对应 vol 的问题：她说完、用户没接 → 话题死 → 她永远不再开口。
    真人是「双方都会找话题」的 —— 这里量化：
      1. 静默边界之后，谁先重新开口（user vs friend）？
      2. ★ 专项：话题死在 friend 手里（friend 说完、user 没回）→
         friend 会不会自己再开口？多久之后？第一条说什么？
    timeline: [(t, role, text)] 私聊双流（含文本）。
    """
    BOUNDARY = 15 * 60          # 双方静默超过 15 分钟 → 一段对话结束
    events = [(t, r, x) for t, r, x in timeline if r in ("user", "friend")]
    opens = []                       # (opener_role, gap_sec, text, last_role)
    for i in range(1, len(events)):
        prev_t, prev_r = events[i - 1][0], events[i - 1][1]
        t, r, x = events[i]
        gap = (t - prev_t).total_seconds()
        if gap > BOUNDARY:
            opens.append((r, gap, x, prev_r))

    if not opens:
        print("  （没有静默边界样本）")
        return
    n = len(opens)
    friend_open = [o for o in opens if o[0] == "friend"]
    user_open = [o for o in opens if o[0] == "user"]
    print(f"  静默 >15min 的边界共 {n} 次："
          f"好友先开口 {pct(len(friend_open) / n)} | 用户先开口 {pct(len(user_open) / n)}")

    # ★ 专项：话题死在 friend 手里（friend 说完 → 用户沉默）→ friend 自救率
    dead_on_friend = [o for o in opens if o[3] == "friend"]
    rescued = [o for o in dead_on_friend if o[0] == "friend"]
    print(f"  话题死在好友手里（他说完用户没接）共 {len(dead_on_friend)} 次：")
    if dead_on_friend:
        print(f"    好友自己重新开口（找新话题）：{pct(len(rescued) / len(dead_on_friend))}"
              f"（{len(rescued)} 次）")
        if rescued:
            gaps = sorted(o[1] for o in rescued)
            print(f"    重新开口的等待时长：中位 {quantiles(gaps, 0.5) / 60:.0f} 分钟 | "
                  f"P5 {quantiles(gaps, 0.05) / 60:.0f} 分钟 | "
                  f"P10 {quantiles(gaps, 0.10) / 60:.0f} 分钟 | "
                  f"P25 {quantiles(gaps, 0.25) / 60:.0f} 分钟 | "
                  f"最短 {gaps[0] / 60:.0f} 分钟 | "
                  f"P75 {quantiles(gaps, 0.75) / 60:.0f} 分钟")
            # 「最短的一批」：好友重启里最快的那 10%，供 reopen_delay 下限参考
            fastest = [g for g in gaps if g <= quantiles(gaps, 0.10)]
            print(f"    最快 10% 的重启集中在 {min(fastest) / 60:.0f}"
                  f"~{max(fastest) / 60:.0f} 分钟之间")
    dead_on_user = [o for o in opens if o[3] == "user"]
    rescued_u = [o for o in dead_on_user if o[0] == "user"]
    if dead_on_user:
        print(f"  对照——话题死在用户手里 {len(dead_on_user)} 次，"
              f"用户自救 {pct(len(rescued_u) / len(dead_on_user))}")
    gaps = sorted(o[1] for o in opens)
    print(f"  沉默→重新开口的时长（全部）：中位 {quantiles(gaps, 0.5) / 60:.0f} 分钟 | "
          f"P25 {quantiles(gaps, 0.25) / 60:.0f} 分钟 | P75 {quantiles(gaps, 0.75) / 60:.0f} 分钟")

    # 好友重新开口的第一条说了什么（形态 + 高频样本）
    if friend_open:
        q = sum(1 for o in friend_open if o[2].rstrip().endswith(("？", "?")))
        media = sum(1 for o in friend_open if not o[2])
        selfref = sum(1 for o in friend_open if o[2].startswith(("我", "刚", "今天", "刚")))
        print(f"  好友重新开口的首条形态：问句 {pct(q / len(friend_open))} | "
              f"纯媒体 {pct(media / len(friend_open))} | "
              f"以我/刚/今天开头（自述） {pct(selfref / len(friend_open))}")
        c = Counter(o[2][:20] for o in friend_open if 0 < len(o[2]) <= 20)
        print("  好友重开话开场样本：" + " | ".join(f"{k}×{v}" for k, v in c.most_common(12)))


def interleave_report(timeline) -> None:
    """交错接话分析：对方单条/多条时，真人到底怎么接话。

    timeline: [(t, role, text)] 按时间排好；role: 'user' | 'friend'（私聊合并双流）。
    想回答的问题（vol 对齐用）：
      1. 对方连发时，真人是「等全部说完再回」还是「中途就插话」？
      2. 真人开口的时机（距对方段末/段首各多久）？
      3. 回应密度：对方发 N 条，真人回几条？（逐条回应 vs 抓重点）
    """
    GAP = 90.0        # 静默超时 → 一段结束
    # 把双流切成「段」：同一人连续发，间隔 >GAP 或被对方插入就算新段。
    # (None, "boundary") 是文件边界 —— 两个不同会话的消息不能拼成假段。
    segs = []         # (role, [ts], ) 一段 = 同一人的一串消息
    for t, role, _text in timeline:
        if role == "boundary":
            segs.append(("boundary", []))
            continue
        if segs and segs[-1][0] == role and (t - segs[-1][1][-1]).total_seconds() <= GAP:
            segs[-1][1].append(t)
        else:
            segs.append((role, [t]))
    # 只看「user 段 → friend 段」的衔接（friend 回应 user）
    pairs = []
    for i in range(len(segs) - 1):
        if segs[i][0] == "user" and segs[i + 1][0] == "friend":
            pairs.append((segs[i][1], segs[i + 1][1]))

    if not pairs:
        print("  （没有可分析的用户→好友衔接段）")
        return
    n = len(pairs)
    run_lens = [len(u) for u, _ in pairs]
    dist = Counter(min(l, 5) for l in run_lens)
    print(f"  用户连发段长分布（共 {n} 段）: " + " | ".join(
        f"{k}条 {pct(v / n)}" for k, v in sorted(dist.items())))

    # 段末/段首起的第一响应延迟
    from_end = [ (f[0] - u[-1]).total_seconds() for u, f in pairs
                 if 0 <= (f[0] - u[-1]).total_seconds() < 3600 * 6 ]
    from_start = [ (f[0] - u[0]).total_seconds() for u, f in pairs
                   if 0 <= (f[0] - u[0]).total_seconds() < 3600 * 6 ]
    print(f"  好友第一响应·距段末: 中位 {quantiles(from_end, 0.5):.0f}s | "
          f"P25 {quantiles(from_end, 0.25):.0f}s | P75 {quantiles(from_end, 0.75):.0f}s")
    print(f"  好友第一响应·距段首: 中位 {quantiles(from_start, 0.5):.0f}s | "
          f"P25 {quantiles(from_start, 0.25):.0f}s | P75 {quantiles(from_start, 0.75):.0f}s")

    # 分段长看响应延迟：孤发 1 条 vs 连发多条
    one = [ (f[0] - u[-1]).total_seconds() for u, f in pairs
            if len(u) == 1 and 0 <= (f[0] - u[-1]).total_seconds() < 3600 * 6 ]
    many = [ (f[0] - u[-1]).total_seconds() for u, f in pairs
             if len(u) >= 2 and 0 <= (f[0] - u[-1]).total_seconds() < 3600 * 6 ]
    print(f"  孤发1条时好友响应: 中位 {quantiles(one, 0.5):.0f}s | P75 {quantiles(one, 0.75):.0f}s")
    print(f"  连发多条时好友响应(距段末): 中位 {quantiles(many, 0.5):.0f}s | "
          f"P75 {quantiles(many, 0.75):.0f}s")

    # 交错率：好友开口时，用户段的最后一条距其 <10s
    # （说明好友没等用户「停下来」，在连发节奏里就接了话）
    inter = [ 1 for u, f in pairs
             if len(u) >= 2 and 0 <= (f[0] - u[-1]).total_seconds() < 10 ]
    print(f"  好友在用户连发节奏内(<10s)就接话: "
          f"{pct(len(inter) / max(1, sum(1 for u, _ in pairs if len(u) >= 2)))}"
          f"（限段长≥2，共 {sum(1 for u, _ in pairs if len(u) >= 2)} 段）")

    # 回应密度：好友段条数 / 用户段条数（逐条回应 vs 抓重点）
    density = [ len(f) / len(u) for u, f in pairs if len(u) >= 2 ]
    if density:
        print(f"  回应密度(好友条数/用户条数, 用户段≥2): 中位 "
              f"{quantiles(density, 0.5):.2f} | P25 {quantiles(density, 0.25):.2f} | "
              f"P75 {quantiles(density, 0.75):.2f}")
        print(f"  密度≤0.5(挑一半不到) 占比 {pct(sum(1 for d in density if d <= 0.5) / len(density))}"
              f" | ≥1.0(至少逐条) 占比 {pct(sum(1 for d in density if d >= 1.0) / len(density))}")


def main() -> None:
    per_chat = "--per-chat" in sys.argv
    files = sorted(glob.glob(str(DATA_DIR / "*.xlsx")))
    print(f"共 {len(files)} 个文件\n")

    friend = Side("私聊·真人伙伴（全部好友聚合）")
    user_p = Side("私聊·用户（全部私聊聚合）")
    grp_all = Side("群聊·全体群友聚合")
    user_g = Side("群聊·用户")
    lat_f2u, lat_u2f = [], []       # 私聊回复延迟
    timeline = []                    # [(t, role)] 私聊合并双流（交错分析用）

    for fp in files:
        name = Path(fp).stem
        df = load(Path(fp))
        if df.empty:
            continue
        is_friend = name.startswith("friend_")
        is_group = name.startswith("group_")
        if not (is_friend or is_group):
            continue

        qq_col = [qq_str(v) for v in df["发送者QQ号"]]
        rows = list(zip(df["时间"], df["消息内容"], df["消息类型"]))

        if is_friend:
            fs, us = (Side(name.split("_")[1]), Side("user")) if per_chat else (None, None)
            last_by, last_t = None, {}
            seg_f, seg_u = [], []
            for (t, content, mtype), qq in zip(rows, qq_col):
                if mtype in ("系统消息",):
                    continue
                who = "user" if qq == USER_QQ else "friend"
                txt = clean_text(content)
                media_only = (not txt) or mtype in ("图片", "表情", "视频", "文件", "转发", "卡片")
                target = user_p if who == "user" else friend
                target.add(t, txt, media_only)
                timeline.append((t, who, txt))
                if per_chat:
                    (us if who == "user" else fs).add(t, txt, media_only)
                other = "friend" if who == "user" else "user"
                if last_by == other:
                    d = (t - last_t[other]).total_seconds()
                    if d < 3600 * 12:
                        (lat_u2f if who == "user" else lat_f2u).append(d)
                last_by = who
                last_t[who] = t
            # 会话边界（供 burst 切分）
            friend.add_burst_frame(None)
            user_p.add_burst_frame(None)
            timeline.append((None, "boundary", ""))
            if per_chat:
                print(fs.report())
                print(us.report())
                print()
        else:
            for (t, content, mtype), qq in zip(rows, qq_col):
                if mtype in ("系统消息",):
                    continue
                txt = clean_text(content)
                media_only = (not txt) or mtype in ("图片", "表情", "视频", "文件", "转发", "卡片")
                grp_all.add(t, txt, media_only)
                if qq == USER_QQ:
                    user_g.add(t, txt, media_only)
            grp_all.add_burst_frame(None)
            user_g.add_burst_frame(None)

    def lat_str(xs, label):
        if not xs:
            return f"{label}: 无数据"
        return (f"{label}: 中位 {quantiles(xs, 0.5):.0f}s | P25 {quantiles(xs, 0.25):.0f}s | "
                f"P75 {quantiles(xs, 0.75):.0f}s | P90 {quantiles(xs, 0.90):.0f}s")

    print("=" * 66)
    print("聚合分析（全量数据）")
    print("=" * 66)
    print(friend.report())
    print()
    print(user_p.report())
    print()
    print(grp_all.report())
    print()
    print(user_g.report())
    print()
    print("  ◆ 私聊回复延迟（在聊状态，半天内）")
    print("   " + lat_str(lat_f2u, "好友→用户"))
    print("   " + lat_str(lat_u2f, "用户→好友"))
    print()
    print("=" * 66)
    print("交错接话分析（好友如何接用户的单条/多条）")
    print("=" * 66)
    interleave_report(timeline)
    print()
    print("=" * 66)
    print("话题重启分析（话题聊死后谁先开口）")
    print("=" * 66)
    topic_reopen_report(timeline)


if __name__ == "__main__":
    main()
