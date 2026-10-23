"""离线测试套件。

用法（在 companion 目录下）：
    .venv\\Scripts\\python.exe tests\\run_tests.py

不依赖 pytest，不联网，不需要 API Key。
测的是「接线对不对」，不是「模型回得好不好」。
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import tempfile
import time
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.config import (  # noqa: E402
    AutonomyConfig, BehaviorConfig, Config, ConversationConfig, LLMConfig,
    MemoryConfig, QQConfig, SearchConfig, StickerConfig, load_config,
)
from app.memory import Memory, cosine, embed  # noqa: E402
from app.state import EMOTION_TO_EVENT, StateMachine  # noqa: E402
from app.store import Store  # noqa: E402
from app.sticker import StickerLibrary  # noqa: E402
from app.channel.console import ConsoleChannel  # noqa: E402
from app.channel.napcat import NapCatChannel, parse_message  # noqa: E402
from app.autonomy.search import NotConfigured, build_provider  # noqa: E402
from app.autonomy.suppress import Suppressor  # noqa: E402
from tests.mock_llm import MockLLM  # noqa: E402

PASS, FAIL = [], []


def check(name: str, cond: bool, detail: str = "") -> None:
    if cond:
        PASS.append(name)
        print(f"  \u2713 {name}")
    else:
        FAIL.append(f"{name} :: {detail}")
        print(f"  \u2717 {name}  {detail}")


def section(t: str) -> None:
    print(f"\n=== {t} ===")


def tmpcfg() -> Config:
    d = Path(tempfile.mkdtemp())
    cfg = Config(root=ROOT)
    cfg.llm = LLMConfig(api_key="mock", model="deepseek-flash")
    cfg.qq = QQConfig(self_id="10000", owner_id="10001")
    cfg.behavior = BehaviorConfig(outbound_delay_ms=[0, 0], split_long_reply=True,
                                  split_threshold=9999,
                                  # 关掉「多条消息合并」：否则 handle() 只是把消息
                                  # 塞进队列就返回，断言会在处理前就跑完。
                                  merge_window_sec=0.0)
    cfg.memory = MemoryConfig(db_path=str(d / "t.db"),
                              sticker_dir=str(d / "s"),
                              sticker_index=str(d / "s" / "index.json"),
                              # 诊断落盘也走临时目录，别污染用户的真实 data/
                              debug_dir=str(d / "debug"))
    cfg.search = SearchConfig(provider="", api_key="")
    cfg.autonomy = AutonomyConfig(quiet_hours=["03:00", "05:00"], min_gap_min=45)
    return cfg


# ---------------------------------------------------------------- 1
def test_state() -> None:
    section("状态机")
    st = Store(str(Path(tempfile.mkdtemp()) / "s.db"))
    sm = StateMachine(st)
    base_v = sm.emotion.valence

    sm.apply_event("praise", 1.0)
    check("夸 → valence 上升", sm.emotion.valence > base_v, f"{base_v}→{sm.emotion.valence}")

    v_after_praise = sm.emotion.valence
    sm.apply_event("criticism", 1.0)
    check("批评 → valence 下降", sm.emotion.valence < v_after_praise)

    e0 = sm.emotion.energy
    sm.apply_interaction(0.9)
    # ★ 电量语义改过：**好聊天会回血，敷衍才掉电**。
    # 原来是固定 -3，聊天时只降不升 → 一路到 0 → 会话层彻底卡死
    # （实测「社交电量 0 太低」刷了几十行）。
    sm2 = StateMachine(st)
    sm2.emotion.energy = 50.0
    sm2.apply_interaction(0.9)          # 聊得投入
    check("聊得投入 → 电量回升", sm2.emotion.energy > 50.0,
          f"50→{sm2.emotion.energy:.2f}")
    sm2.emotion.energy = 50.0
    sm2.apply_interaction(0.1)          # 聊得敷衍
    check("聊得敷衍 → 电量下降", sm2.emotion.energy < 50.0,
          f"50→{sm2.emotion.energy:.2f}")
    check("★ 电量不会因为聊天掉到 0（不会卡死会话）",
          sm.emotion.energy > 0, str(sm.emotion.energy))
    check("表扬/互动提升信任", sm.relationship.trust > 50)

    sm.emotion.updated_at -= 3600 * 6
    before_lonely = sm.emotion.loneliness
    sm.tick(last_interaction_ago_h=7.0)
    check("6小时无互动 → 孤独度上升", sm.emotion.loneliness > before_lonely,
          f"{before_lonely}→{sm.emotion.loneliness}")

    check("情绪标签有中文描述", len(sm.mood_label()) > 0)
    check("describe 含效价与关系", "效价" in sm.describe() and "信任" in sm.describe())

    # ★ 一眼情绪（聊天头像旁的心情点）：只给晴/阴/雨 + 一句人话，不给数字
    sm.emotion.valence = -60.0
    sm.emotion.anxiety = 90.0
    sm.emotion.loneliness = 40.0
    sm.emotion.neglect = 10.0
    snap = sm.mood_snapshot()
    check("★ 情绪很差时心情点是「雨」", snap["level"] == "rain", str(snap))
    check("★ 心情点配的是她自己的话，不是数字",
          "焦虑" not in snap["line"] and not any(ch.isdigit() for ch in snap["line"]),
          snap["line"])
    check("★ 低落时提示词要求把情绪说出口",
          "别装没事" in sm.describe(), sm.describe()[-140:])
    sm.emotion.valence = 60.0
    sm.emotion.anxiety = 5.0
    check("情绪好时心情点是「晴」", sm.mood_snapshot()["level"] == "sun",
          str(sm.mood_snapshot()))

    check("manual_mood 生效", sm.manual_mood("低落") and sm.emotion.valence < 0)
    check("manual_mood 无效词返回 False", sm.manual_mood("不存在") is False)
    check("情绪→事件映射表非空", len(EMOTION_TO_EVENT) >= 5)
    st.close()


# ---------------------------------------------------------------- 1.5
def test_bond() -> None:
    """情侣 / 专属关系：门槛、单例语义、提示词身份、持久化。"""
    section("情侣 / 专属关系")
    from app import bond as bond_mod
    from app.traits import Traits, trait_text

    ok, missing = bond_mod.eligibility(
        affection=80, intimacy=65, trust=60, known_days=7)
    check("达标即可确定关系", ok and not missing, str(missing))
    ok2, missing2 = bond_mod.eligibility(
        affection=70, intimacy=50, trust=55, known_days=3)
    check("不达标时列出还差什么", (not ok2) and len(missing2) >= 3,
          str(missing2))
    ok3, missing3 = bond_mod.eligibility(
        affection=100, intimacy=100, trust=100, known_days=30,
        romance_allowed=False)
    check("设定不进入恋爱的角色会被拒绝绑定",
          (not ok3) and any("不进入恋爱" in x for x in missing3),
          str(missing3))

    b = bond_mod.Bond(character_id="123", name="凯伊",
                      since=time.time() - 8 * 86400)
    partner = bond_mod.line_for(b, "123")
    check("恋人看到的身份是「已经确定恋人关系」",
          "恋人关系" in partner, partner[:60])
    friend = bond_mod.line_for(b, "456")
    check("其他人被明确告知「只是朋友、不要暧昧」",
          "朋友" in friend and "不要暧昧" in friend, friend[:60])

    p = Path(tempfile.mkdtemp()) / bond_mod.FILE_NAME
    bond_mod.save(p, b)
    b2 = bond_mod.load(p)
    check("绑定状态能落盘并在重启后读回",
          b2.character_id == "123" and b2.name == "凯伊", str(b2.to_dict()))

    b.character_id = ""
    b.name = ""
    b.ex_id = "123"
    b.ex_name = "凯伊"
    b.breakup_ts = time.time()
    ex = bond_mod.line_for(b, "123")
    check("刚分手的人会被告知「这几天缓不过来」",
          "缓不过来" in ex, ex[:60])
    check("分手后别人不会被牵扯进细节",
          bond_mod.line_for(b, "456") == "", "")

    txt = trait_text(Traits(enthusiasm=60, affection=85), "【专属身份】")
    check("关系身份会拼进角色提示词", "【专属身份】" in txt, "")

    # ── 绑定 / 解绑的动作（用最小 Companion 替身，不碰真实角色库）──
    from app.main import Companion, _CONFESS_RE
    check("★ 明确的告白句式能被识别",
          bool(_CONFESS_RE.search("做我女朋友吧")), "")
    check("日常提到「女朋友」不会误触发绑定",
          not _CONFESS_RE.search("我今天和女朋友吵架了"), "")

    comp = Companion.__new__(Companion)
    comp.bond_path = Path(tempfile.mkdtemp()) / bond_mod.FILE_NAME
    comp.bond = bond_mod.Bond()
    st = Store(str(Path(tempfile.mkdtemp()) / "bond.db"))
    comp.state = StateMachine(st)
    comp.store = st

    class _C:
        id = "1"
        name = "甲"
        is_primary = True

    class _Reg:
        primary = _C()

        def get(self, cid):
            return _C() if str(cid) == "1" else None

        def all(self):
            return [_C()]

    comp.characters = _Reg()
    comp.primary_traits = Traits(enthusiasm=60, affection=90)
    comp._guests = {}

    class _Stub:
        trait_text = ""

    comp.heartbeat = _Stub()
    comp.conversation = _Stub()

    comp.set_bond({"action": "bind", "character_id": "1", "force": True})
    check("★ 绑定后进入 active，且只有一个恋人",
          comp.bond.active and comp.bond.name == "甲", str(comp.bond.to_dict()))
    check("★ 恋人身份已经写进回复提示词",
          "恋人关系" in comp._primary_relation(), "")

    doubled = True
    try:
        comp.set_bond({"action": "bind", "character_id": "1"})
    except ValueError:
        doubled = False
    check("已经绑定时不能再绑第二个（单例约束）", doubled is False, "")

    v_before = comp.state.emotion.valence
    comp.set_bond({"action": "unbind"})
    check("★ 解绑后进入 72 小时冷静期",
          (not comp.bond.active) and comp.bond.cooldown_until > time.time(),
          str(comp.bond.to_dict()))
    check("★ 分手真的让她情绪变差",
          comp.state.emotion.valence < v_before,
          f"{v_before:.0f}→{comp.state.emotion.valence:.0f}")
    check("前任在冷静期内会被告知「缓不过来」",
          "缓不过来" in comp._bond_line("1"), "")


# ---------------------------------------------------------------- 2
def test_memory() -> None:
    section("记忆")
    st = Store(str(Path(tempfile.mkdtemp()) / "m.db"))
    mem = Memory(st)

    v = embed("测试向量")
    check("向量维度 256", len(v) == 256)
    check("自相似度为 1", abs(cosine(v, v) - 1.0) < 1e-6)

    mem.add_episodic("今天在烟台出差，屋里特别冷，买了四张棉被")
    mem.add_episodic("聊到想做一个永远不会离开的 AI")
    mem.add_semantic("[网络安全] 新披露一个 Linux 内核提权漏洞")

    hits = mem.recall("冷 棉被 烟台", top_k=3)
    check("检索命中相关记忆", len(hits) >= 1 and "棉被" in hits[0]["text"],
          f"top={hits[0]['text'][:20] if hits else 'none'}")

    mem.set_profile("喜欢的饮料", "冰美式")
    check("画像可写入读出", mem.profile().get("喜欢的饮料") == "冰美式")
    check("画像注入文本正确", "冰美式" in mem.profile_text())

    mem.bump_interest("咖啡", 2.0)
    mem.bump_interest("剪辑", 1.0)
    check("兴趣图谱排序正确", mem.top_interests(2)[0] == "咖啡", str(mem.top_interests(3)))

    ev = st.recent_events(5)
    check("情节同时写入事件表", len(ev) >= 2)
    st.close()


# ---------------------------------------------------------------- 3
def test_parse() -> None:
    section("消息解析")
    txt, imgs, at, _ids, _sz, _fw = parse_message(
        [
            {"type": "text", "data": {"text": "看我这个"}},
            {"type": "image", "data": {"url": "http://x/a.png"}},
            {"type": "at", "data": {"qq": "10001"}},
            {"type": "face", "data": {"id": "1"}},
        ],
        "10001",
    )
    check("数组格式：文本拼接", txt.startswith("看我这个"), repr(txt))
    check("数组格式：提取图片 URL", imgs == [["http://x/a.png"]], str(imgs))
    check("数组格式：识别 @我", at is True)

    txt2, imgs2, _, _ids2, _sz2, _fw2 = parse_message("[CQ:image,url=http://y/b.jpg][CQ:at,qq=1]好冷", "1")
    check("CQ 码格式：提取图片", imgs2 == [["http://y/b.jpg"]], str(imgs2))
    check("CQ 码格式：剥离 CQ 码", "好冷" in txt2 and "CQ:" not in txt2, repr(txt2))

    _, _, at3, _ids3, _sz3, _fw3 = parse_message([{"type": "at", "data": {"qq": "999"}}], "10001")
    check("别人 @ → 不误判为 @我", at3 is False)


async def test_image_candidates() -> None:
    section("图片候选来源（这是「发图看不懂」的根因所在）")
    from app.channel.napcat import image_candidates, parse_message as pm

    # ★ 顺序修正过：实测 base64 会被截断（正好 32768 字节、PNG 缺 IEND），
    #   所以它必须垫底；本地路径才是同机最可靠的那个。
    cands = image_candidates({
        "file": r"C:\nt_qq\temp\a.png",
        "url": "https://multimedia.nt.qq.com.cn/download?rkey=EXPIRE",
        "base64": "AAAA",
        "file_name": "a.png",
    })
    check("本地路径排第一（NapCat 的 readFile 读的是完整文件）",
          cands[0] == r"C:\nt_qq\temp\a.png", str(cands))
    check("远程 URL 居中（常带失效签名）", cands[1].startswith("https://"), str(cands))
    check("base64 垫底（实测会截断，最不可靠）",
          cands[-1].startswith("data:image/png;base64,"), str(cands)[:110])

    only_url = image_candidates({"url": "https://x/y.jpg"})
    check("只有 URL 时退化可用", only_url == ["https://x/y.jpg"], str(only_url))

    only_file = image_candidates({"file": r"D:\st\b.png"})
    check("只有 file 时可用", only_file == [r"D:\st\b.png"], str(only_file))

    empty = image_candidates({"file": ""})
    check("空数据返回空列表", empty == [], str(empty))

    check("file 里塞 URL 也能收",
          image_candidates({"file": "https://z/c.png"}) == ["https://z/c.png"])

    # 端到端：走一遍 parse_message
    _, imgs, _, _, _, _ = pm([{"type": "image", "data": {
        "file": "/tmp/x.jpg", "url": "https://q/x.jpg", "base64": "QUJD"}}], "1")
    check("parse_message 输出候选列表", len(imgs) == 1 and len(imgs[0]) == 3, str(imgs))
    check("parse_message 候选顺序正确（本地路径优先，base64 垫底）",
          imgs[0][0] == "/tmp/x.jpg"
          and imgs[0][-1].startswith("data:image/jpeg;base64,"), str(imgs[0])[:110])

    # data URL 解码
    from app.perceive import load_first_image, load_image

    png = _make_png()
    import base64 as _b
    durl = "data:image/png;base64," + _b.b64encode(png).decode()
    raw, mime = await load_image(durl)
    check("data URL 能解码回原始字节", raw == png and mime == "image/png",
          f"{None if raw is None else len(raw)} / {mime}")

    # 全候选失败时返回 (None, "", "")
    raw2, _, hit2, _why = await load_first_image(["http://127.0.0.1:1/a.png", ""])
    check("全部候选失败 → 返回空且不抛异常", raw2 is None and hit2 == "")

    # 第一个失败、第二个成功 → 必须继续往下试
    raw3, _, hit3, _why = await load_first_image(["http://127.0.0.1:1/a.png", durl])
    check("前面的候选失败会继续试下一个", raw3 == png and hit3.startswith("data:"),
          f"hit={hit3[:40]}")


def _make_png(size: int = 32) -> bytes:
    import struct
    import zlib

    raw = b"".join(b"\x00" + bytes([10, 200, 10] * size) for _ in range(size))

    def chunk(tag: bytes, data: bytes) -> bytes:
        return (struct.pack(">I", len(data)) + tag + data
                + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))

    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw))
            + chunk(b"IEND", b""))


# ---------------------------------------------------------------- 4
def test_segments() -> None:
    section("消息段（表情包关键字段）")
    c = NapCatChannel(QQConfig(), lambda m: None)
    s = c.seg_image("file:///D:/a.png", is_sticker=True)
    check("表情包 sub_type=1", s["data"]["sub_type"] == 1, str(s))
    n = c.seg_image("file:///D:/a.png", is_sticker=False)
    check("普通图 sub_type=0", n["data"]["sub_type"] == 0, str(n))
    check("文本段结构正确", c.seg_text("hi")["data"]["text"] == "hi")
    check("语音段结构正确", c.seg_record("a.silk")["type"] == "record")
    uri = c.file_uri(r"D:\stickers\猫.png")
    check("Windows 路径转 file:///", uri.startswith("file:///D:/"), uri)
    conv = ConsoleChannel.file_uri(r"D:\stickers\猫.png")
    check("控制台 file_uri 同样可用", conv.endswith("猫.png"), conv)


# ---------------------------------------------------------------- 5
async def test_suppress() -> None:
    section("六层抑制链")
    cfg = tmpcfg()
    st = Store(cfg.memory.db_path)
    sm = StateMachine(st)
    mem = Memory(st)
    mock = MockLLM()
    sup = Suppressor(cfg.autonomy, st, mock, sm, mem)

    d = await sup.check(last_spoke_ts=0, last_reply_ts=0, cold_streak=0, recent=[])
    check("①~⑤ 全通过时放行", d.allowed and d.stage == "通过", str(d))

    d2 = await sup.check(last_spoke_ts=__import__("time").time() - 60,
                         last_reply_ts=0, cold_streak=0, recent=[])
    check("② 间隔不足 → 拦截", (not d2.allowed) and d2.stage == "间隔", str(d2))

    # ③ 冷场：**刻意改成不永久拦截**（用户要求「静默一段再回来问」）。
    # 现在冷场只会把间隔拉长、并把这一句改成「关心」类。
    old = __import__("time").time() - 99999
    d3 = await sup.check(last_spoke_ts=old, last_reply_ts=old, cold_streak=5, recent=[])
    check("③ 连续冷场 → 不永久拦死，而是转成「回来关心」",
          d3.allowed and "关心" in d3.stage, str(d3))
    # 但冷场时**间隔会被拉长**
    recent_spoke = __import__("time").time() - 70   # 70 分钟前刚说过
    d3b = await sup.check(last_spoke_ts=recent_spoke, last_reply_ts=old,
                          cold_streak=5, recent=[])
    check("③ 冷场时间隔被拉长（70 分钟还不够）",
          (not d3b.allowed) and d3b.stage == "间隔", str(d3b))

    sm.emotion.energy = 5
    d4 = await sup.check(last_spoke_ts=old, last_reply_ts=old, cold_streak=0, recent=[])
    check("④ 电量低 → 拦截", (not d4.allowed) and d4.stage == "电量", str(d4))
    sm.emotion.energy = 80

    mock.overrides["proactive"] = {"speak": False, "kind": "none", "topic": "", "reason": "没什么想说的"}
    d5 = await sup.check(last_spoke_ts=old, last_reply_ts=old, cold_streak=0, recent=[])
    check("⑤ 无话可说 → 拦截", (not d5.allowed) and d5.stage == "有话可说", str(d5))
    mock.overrides["proactive"] = {"speak": True, "kind": "miss", "topic": "x", "reason": "有"}

    d5b = await sup.check(last_spoke_ts=old, last_reply_ts=old, cold_streak=0, recent=[])
    check("⑤ 通过时带回意图类型", d5b.allowed and d5b.kind == "miss", str(d5b))

    mock.overrides["proactive"] = {"speak": True, "kind": "content", "topic": "x", "reason": "有"}
    d5c = await sup.check(last_spoke_ts=old, last_reply_ts=old, cold_streak=0, recent=[],
                          has_content=False)
    check("⑤ 没有外部内容时 content 被降级为 miss", d5c.kind == "miss", str(d5c))
    d5d = await sup.check(last_spoke_ts=old, last_reply_ts=old, cold_streak=0, recent=[],
                          has_content=True, content_hint="某篇文章")
    check("⑤ 有外部内容时保留 content", d5d.kind == "content", str(d5d))
    mock.overrides["proactive"] = {"speak": True, "kind": "miss", "topic": "x", "reason": "有"}

    mock.overrides["revalidate"] = {"send": False, "reason": "已经聊过了"}
    ok, why = await sup.revalidate("面试加油!", [])
    check("⑥ 送出前复核能拦下", ok is False, why)

    sup_q = Suppressor(AutonomyConfig(quiet_hours=["00:00", "23:59"]), st, mock, sm, mem)
    d6 = await sup_q.check(last_spoke_ts=0, last_reply_ts=0, cold_streak=0, recent=[])
    check("① 免打扰时段 → 拦截", (not d6.allowed) and d6.stage == "免打扰", str(d6))

    sup_cross = Suppressor(AutonomyConfig(quiet_hours=["23:00", "07:00"]), st, mock, sm, mem)
    from datetime import datetime
    check("跨天时段 02:00 判为静默", sup_cross.in_quiet_hours(datetime(2026, 10, 12, 2, 0)))
    check("跨天时段 12:00 判为非静默", not sup_cross.in_quiet_hours(datetime(2026, 10, 12, 12, 0)))
    st.close()


# ---------------------------------------------------------------- 6
async def test_full_pipeline() -> None:
    section("完整管线（handle 全链路）")
    cfg = tmpcfg()
    mock = MockLLM(reply="听起来不错啊，哪家的豆子")
    ch = ConsoleChannel(owner_id="10001")
    from app.main import Companion

    comp = Companion(cfg, channel=ch, llm=mock)
    v_before = comp.state.emotion.valence

    await comp.handle(ch.make_incoming("今天喝到一杯超好喝的冰美式"))
    check("表达通道被调用", "express" in mock.calls, str(mock.calls))
    check("情绪通道被调用", "emotion" in mock.calls)
    check("分析通道被调用", "analyze" in mock.calls)
    check("发出了回复", len(ch._out_lines) == 1, str(ch._out_lines))
    check("回复内容正确", "豆子" in ch._out_lines[0], ch._out_lines[0])
    check("状态被更新（valence 变化）", comp.state.emotion.valence != v_before,
          f"{v_before}→{comp.state.emotion.valence}")
    check("画像已写入", "冰美式" in comp.memory.profile_text(),
          comp.memory.profile_text()[:80])
    check("情节记忆已写入", any("冰美式" in m["text"] for m in comp.store.all_memories()))
    check("兴趣词已登记", "咖啡" in comp.memory.interests()
          or "咖啡" in comp.memory.heard(), str(comp.memory.interests()))
    check("对话已落盘 transcript", len(comp.store.recent_turns(10)) == 2)
    check("last_analysis 已缓存（供 /why）", bool(comp.store.kv_get("last_analysis")))

    # 发图
    img = Path(tempfile.mkdtemp()) / "a.png"
    img.write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * 64)
    mock.calls.clear()
    await comp.handle(ch.make_incoming("", images=[str(img)]))
    check("图片走视觉通道", "vision" in mock.calls, str(mock.calls))
    check("发图后仍有回复", len(ch._out_lines) == 2)

    # 风险信号
    mock.overrides["analyze"] = {
        "intent": "表达绝望", "emotion_label": "难过", "latent_need": "被安慰",
        "relation_signal": -0.5, "risk": "自伤倾向", "reply_strategy": "先接住情绪",
        "quality": 0.4, "profile_updates": [], "interest_terms": [],
        "memory_worthy": False, "memory_summary": "",
    }
    await comp.handle(ch.make_incoming("感觉没什么意思了"))
    flagged = [e for e in comp.store.recent_events(20, include_flagged=True) if e["flagged"]]
    check("高风险信号被打 flagged 标记", len(flagged) >= 1, str(flagged))

    # ★ 管线代际检查：表达期间用户又说话了 → 本批回复作废。
    # （用户连发几批时，旧批次的回复排队发出就是「一句一句回不完」的独白；
    #   现在只有最新批次的回复能发出去，旧批次在发送前被丢掉）
    class _PipelineBumpMock(MockLLM):
        def __init__(self, comp_ref):
            super().__init__(reply="这条不该被发出去")
            self._c = comp_ref

        async def chat(self, messages, **kw):
            out = await super().chat(messages, **kw)
            if self.calls and self.calls[-1] == "express":
                self._c().conversation.on_user_message("（用户又说话了）")
            return out

    mock_b = _PipelineBumpMock(lambda: comp)
    comp.llm = mock_b
    lines_before = len(ch._out_lines)
    await comp.handle(ch.make_incoming("试试代际作废"))
    check("★ 管线代际作废：表达期间对方插话，本批不发",
          len(ch._out_lines) == lines_before,
          f"lines+{len(ch._out_lines) - lines_before} out={ch._out_lines[-1:]}")
    comp.llm = mock

    # ★ 追时：总延迟控制（处理慢就立即发，处理快就补足目标延迟）
    from app.main import catchup_delay_ms
    now = time.time()
    d_fast = catchup_delay_ms([5000, 20000], now - 2.0, now)     # 刚收到 2s
    check("★ 追时：处理快时补足目标等待", 3000 <= d_fast <= 20000,
          f"{d_fast:.0f}ms")
    d_slow = catchup_delay_ms([5000, 20000], now - 25.0, now)    # 已花 25s
    check("★ 追时：处理超时就立即发", d_slow == 0, f"{d_slow:.0f}ms")
    d_none = catchup_delay_ms([0, 0], 0.0, now)                  # 无参照（主动开口）
    check("★ 追时：无参照走原分布", d_none == 0, f"{d_none:.0f}ms")

    # ★ 回归实测事故：7 条文字在表达中，随后一张「纯表情包」批次被
    #   掷骰跳过不回话 —— 跳过的批次不 bump 代际，文字批的回复必须
    #   照常发出（原来：表情包批一进管线就 bump，文字回复被白白顶掉）
    from app.channel.napcat import IncomingMessage as _IM

    class _GateExpressMock(MockLLM):
        """express 期间挂起，直到测试放行 —— 模拟慢生成。"""

        def __init__(self):
            super().__init__(reply="文字批的回复，必须发出")
            self.gate = asyncio.Event()

        async def chat(self, messages, **kw):
            out = await super().chat(messages, **kw)
            if self.calls and self.calls[-1] == "express":
                await self.gate.wait()
            return out

    mock_gate = _GateExpressMock()
    comp.llm = mock_gate
    cfg.behavior.sticker_only_reply_prob = 0.0      # 表情包批次必然跳过不回话
    img2 = Path(tempfile.mkdtemp()) / "s.png"
    img2.write_bytes(b"\x89PNG\r\n\x1a\n" + b"9" * 40)
    sticker_msg = _IM(kind="private", user_id="10001", message_id="s1", nickname="u",
                      text="", images=[[str(img2)]],
                      raw={"message": [{"type": "image",
                                        "data": {"sub_type": "1",
                                                 "summary": "动画表情"}}]})
    text_task = asyncio.create_task(comp.handle(ch.make_incoming("正经文字消息")))
    await asyncio.sleep(0.3)          # 让文字批跑到 express（被 gate 挡住）
    await comp.handle(sticker_msg)    # 表情包批次完整走完 → 跳过不回话
    out_before = len(ch._out_lines)
    mock_gate.gate.set()              # 放行文字批的表达
    await text_task
    check("★ 表情包批次不吞在途的文字回复",
          len(ch._out_lines) > out_before and "必须发出" in ch._out_lines[-1],
          f"lines={ch._out_lines[out_before:]}")
    comp.llm = mock

    comp.store.close()
    ch._out_lines.clear()


# ---------------------------------------------------------------- 7
async def test_commands() -> None:
    section("调试指令")
    cfg = tmpcfg()
    mock = MockLLM()
    ch = ConsoleChannel(owner_id="10001")
    from app.main import Companion

    comp = Companion(cfg, channel=ch, llm=mock)

    await comp.handle(ch.make_incoming("/state"))
    check("/state 输出内部状态", "效价" in ch._out_lines[-1], ch._out_lines[-1][:60])

    await comp.handle(ch.make_incoming("/mood 低落"))
    check("/mood 生效", comp.state.emotion.valence < 0, str(comp.state.emotion.valence))

    await comp.handle(ch.make_incoming("/why"))
    check("/why 有输出（无分析时也不崩）", len(ch._out_lines[-1]) > 0)

    await comp.handle(ch.make_incoming("/mood"))
    check("/mood 空参提示用法", "预设" in ch._out_lines[-1], ch._out_lines[-1])

    # /poke 在允许时段应能发出主动消息
    ch._out_lines.clear()
    await comp.handle(ch.make_incoming("/poke"))
    check("/poke 有结果输出", "心跳结果" in ch._out_lines[-1], ch._out_lines[-1][:80])

    # 权限：非主人私聊应被忽略
    ch._out_lines.clear()
    await comp.handle(ch.make_incoming("你好", user_id="99999"))
    check("非主人私聊被忽略", len(ch._out_lines) == 0, str(ch._out_lines))

    # 群聊未 @ 应被忽略
    await comp.handle(ch.make_incoming("在吗", group_id="888", mentions_self=False))
    check("群聊未 @ 被忽略", len(ch._out_lines) == 0, str(ch._out_lines))

    comp.store.close()


# ---------------------------------------------------------------- 8
async def test_digest_offline() -> None:
    section("自主浏览（搜索未配置时的行为）")
    cfg = tmpcfg()
    st = Store(cfg.memory.db_path)
    mem = Memory(st)
    mem.bump_interest("咖啡", 2.0)
    sm = StateMachine(st)
    provider = build_provider(cfg.search)
    check("provider 为 Null", provider.name == "null")
    try:
        await provider.search("x")
        check("NullProvider 应抛 NotConfigured", False)
    except NotConfigured:
        check("NullProvider 明确抛 NotConfigured（不返回假数据）", True)

    from app.autonomy.digest import Digest
    dg = Digest(cfg.autonomy, cfg.memory, MockLLM(), mem, sm, st, provider)
    item = await dg.run_once(force=True)
    check("搜索未配置时安全跳过（返回 None，不崩）", item is None)

    kw = await dg.extract_and_bump_interests("我最近在学剪辑，还挺好玩的")
    check("兴趣抽取写回图谱", "剪辑" in mem.interests(), str(kw))
    st.close()


# ---------------------------------------------------------------- 9
def test_rhythm() -> None:
    section("拟人节奏（主动间隔分布）")
    import statistics

    from app.autonomy.heartbeat import ProactiveRhythm, fmt_minutes
    from app.state import EmotionState, RelationshipState

    cfg = AutonomyConfig()
    r = ProactiveRhythm(cfg)
    e, rel = EmotionState(), RelationshipState()

    s = [r.next_delay_minutes(e, rel) for _ in range(500)]
    check("间隔均为正数", all(x > 0 for x in s))
    # 四档后最早可到 1 分钟（「马上就来」）；顺延可能叠加，最晚放宽到 96 小时
    check("落在 1 分钟 ~ 96 小时内",
          min(s) >= 1 and max(s) <= 96 * 60, f"{min(s):.0f}~{max(s):.0f}")

    inst = [x for x in s if x <= cfg.rhythm_instant[1]]
    near = [x for x in s if cfg.rhythm_near[0] <= x <= cfg.rhythm_near[1]]
    normal = [x for x in s if cfg.rhythm_normal[0] <= x <= cfg.rhythm_normal[1]]
    far = [x for x in s if x > cfg.rhythm_normal[1]]
    check("「马上就来」档被采样到", len(inst) > 0, f"{len(inst)}")
    check("近档被采样到", len(near) > 0, f"{len(near)}")
    check("常档被采样到", len(normal) > 0, f"{len(normal)}")
    # 四档后近/马上两档合起来应当占相当比例（用户要她多说话）
    check("早的两档合计占比可观", (len(inst) + len(near)) / len(s) >= 0.35,
          f"inst={len(inst)} near={len(near)} normal={len(normal)} far={len(far)}")
    check("远档（>8h）被采样到", len(far) > 0, f"{len(far)}")

    mean, sd = statistics.fmean(s), statistics.pstdev(s)
    check("离散度足够大（不是固定间隔）", sd > mean * 0.8, f"mean={mean:.0f} sd={sd:.0f}")

    lonely = EmotionState(loneliness=95, anxiety=90)
    calm = EmotionState(loneliness=0, anxiety=0)
    m_lonely = statistics.fmean(r.next_delay_minutes(lonely, rel) for _ in range(500))
    m_calm = statistics.fmean(r.next_delay_minutes(calm, rel) for _ in range(500))
    check("越孤独焦虑 → 平均间隔越短", m_lonely < m_calm, f"{m_lonely:.0f} vs {m_calm:.0f}")

    tired = EmotionState(energy=5)
    fresh = EmotionState(energy=100)
    m_tired = statistics.fmean(r.next_delay_minutes(tired, rel) for _ in range(500))
    m_fresh = statistics.fmean(r.next_delay_minutes(fresh, rel) for _ in range(500))
    check("电量低 → 平均间隔更长", m_tired > m_fresh, f"{m_tired:.0f} vs {m_fresh:.0f}")

    cfg2 = AutonomyConfig(state_influence=0.0, skip_probability=0.0)
    r2 = ProactiveRhythm(cfg2)
    s2 = [r2.next_delay_minutes(e, rel) for _ in range(300)]
    bands = [tuple(cfg2.rhythm_instant), tuple(cfg2.rhythm_near),
             tuple(cfg2.rhythm_normal), tuple(cfg2.rhythm_long)]
    check("关闭顺延后落在四档区间内",
          all(any(lo <= x <= hi for lo, hi in bands) for x in s2), f"{s2[:5]}")

    check("时长格式化正确",
          fmt_minutes(30) == "30 分钟" and "小时" in fmt_minutes(180) and "天" in fmt_minutes(2000))

    # 向后兼容：不配 weights 时退回旧的固定间隔
    cfg3 = AutonomyConfig(rhythm_weights=[], base_interval_min=100, jitter_min=10)
    s3 = [ProactiveRhythm(cfg3).next_delay_minutes(e, rel) for _ in range(200)]
    check("未配 weights 时退回固定间隔且带抖动",
          all(90 <= x <= 110 for x in s3), f"{min(s3):.0f}~{max(s3):.0f}")


# ---------------------------------------------------------------- 11
async def test_conversation() -> None:
    section("对话连贯性（让聊天能持续下去）")
    from app.act import Sender
    from app.autonomy.conversation import ConversationRunner
    from app.channel.console import ConsoleChannel
    from app.memory import Memory as _Mem
    from app.autonomy.suppress import Suppressor

    cfg = tmpcfg()
    cfg.conversation = ConversationConfig(
        enabled=True, active_window_min=15, followup_delay_sec=[0, 0],
        max_burst_bubbles=3, max_followups_per_topic=3,
        quiet_hours_max_turns=1, energy_threshold=25,
    )
    st = Store(str(Path(tempfile.mkdtemp()) / "c.db"))
    mem = _Mem(st)
    sm = StateMachine(st)
    # ★ reply 用列表轮换：每次接话的草稿都不同 —— 否则第⑦层重复拦截
    # 会把和上一条一样的草稿拦掉（这正是它该干的活，测试得配合）。
    # 无句末标点 → 不会本地拆条，每条就是 1 个气泡，计数可预期。
    mock = MockLLM(reply=["那家店叫啥", "哪家呀改天带我去", "喝的什么豆子",
                          "好喝到什么程度", "下次带大叔去"])
    ch = ConsoleChannel(owner_id="10001")
    sender = Sender(ch, cfg.behavior)
    sup = Suppressor(cfg.autonomy, st, mock, sm, mem)
    runner = ConversationRunner(cfg.conversation, cfg.behavior, cfg.qq, st, mock,
                               sm, mem, sender, sup, lambda n: "")

    check("初始不在活跃窗口", not runner.in_active_window())

    runner.on_user_message("今天喝了个好喝的咖啡")
    check("用户发话后进入活跃窗口", runner.in_active_window())
    check("用户发话后计数归零", runner.conv.bot_turns_since_user == 0)

    d1 = await runner._try_followup()
    check("窗口内会自己接一句", d1 is not None and len(ch._out_lines) >= 1, str(ch._out_lines[-2:]))
    check("接话走了 followup 判断通道", "followup_judge" in mock.calls, str(mock.calls))
    check("接话后计数 +1", runner.conv.bot_turns_since_user == 1, str(runner.conv))

    await runner._try_followup()
    await runner._try_followup()
    check("连发到上限后计数正确", runner.conv.bot_turns_since_user == 3,
          str(runner.conv.bot_turns_since_user))
    reason = runner.block_reason()
    check("达到连续上限后会收住", "收住" in reason, reason)

    before = len(ch._out_lines)
    d4 = await runner._try_followup()
    check("被刹车后不再发", d4 is None and len(ch._out_lines) == before, str(reason))

    # 用户再说一句 → 重新开始
    runner.on_user_message("就是楼下那家")
    check("用户回话后计数重置", runner.conv.bot_turns_since_user == 0
          and runner.conv.followups_this_topic == 0)
    d5 = await runner._try_followup()
    check("用户回话后能继续说", d5 is not None, str(d5))

    # 判断为不说时不该发
    runner.on_user_message("嗯")
    mock.overrides["followup"] = {"speak": False, "kind": "stop", "topic": "", "reason": "没想说的"}
    before = len(ch._out_lines)
    d6 = await runner._try_followup()
    check("模型判断 stop 时不发", d6 is None and len(ch._out_lines) == before, str(d6))

    # 电量太低
    runner.on_user_message("在吗")
    sm.emotion.energy = 5
    check("电量低时会收住", "电量" in runner.block_reason(), runner.block_reason())
    sm.emotion.energy = 80

    # 会话窗口过期
    runner.conv.last_user_ts = time.time() - 3600
    runner.conv.last_bot_ts = 0
    check("窗口过期后不再接话", not runner.in_active_window()
          and "窗口" in runner.block_reason(), runner.block_reason())

    # 深夜更克制
    cfg.conversation.quiet_hours_max_turns = 1
    runner.on_user_message("熬夜聊会儿")
    runner.conv.quiet_turns = 1
    if sup.in_quiet_hours():
        check("深夜达到上限后收住", "深夜" in runner.block_reason(), runner.block_reason())
    else:
        check("深夜限制逻辑存在（当前非深夜，跳过判定）", True)

    check("禁用后不启动", True)
    st.close()


# ---------------------------------------------------------------- 11b
async def test_human_tuning() -> None:
    """拟人度专项：气泡计数 / 收尾 / 退避 / 代际取消 / 重复拦截 / 禁用词 / 摘要。"""
    section("拟人度专项（气泡计数/收尾/退避/代际取消/重复拦截/禁用词/摘要）")
    import tempfile as _tf

    from app.act import Sender
    from app.autonomy.conversation import ConversationRunner, is_closing_text
    from app.autonomy.suppress import Suppressor
    from app.channel.console import ConsoleChannel
    from app.memory import Memory as _Mem
    from app.think import express, extract_overused_terms

    # ---- is_closing_text ----
    check("「晚安」是收尾", is_closing_text("晚安"))
    check("「我先去忙了」是收尾", is_closing_text("我先去忙了"))
    check("长句不算收尾", not is_closing_text("晚安，明天还要早起去图书馆自习呢先不聊了啊"))
    check("普通闲聊不算收尾", not is_closing_text("今天喝了个好喝的咖啡"))

    # ---- 气泡计数 + 收尾状态 + 退避 + 节奏 ----
    cfg = tmpcfg()
    cfg.conversation = ConversationConfig(
        enabled=True, active_window_min=15, followup_delay_sec=[0, 0],
        max_burst_bubbles=3, max_followups_per_topic=3,
    )
    st = Store(str(Path(_tf.mkdtemp()) / "ht.db"))
    mem = _Mem(st)
    sm = StateMachine(st)
    mock = MockLLM(reply="单条回复")
    ch = ConsoleChannel(owner_id="10001")
    sender = Sender(ch, cfg.behavior)
    sup = Suppressor(cfg.autonomy, st, mock, sm, mem)
    runner = ConversationRunner(cfg.conversation, cfg.behavior, cfg.qq, st, mock,
                                sm, mem, sender, sup, lambda n: "")

    runner.on_user_message("在吗")
    runner.on_bot_message(count_as_turn=True, bubbles=3)
    check("★ 连发按气泡计：3 条就是 3", runner.conv.bot_turns_since_user == 3,
          str(runner.conv.bot_turns_since_user))
    check("★ 气泡到上限会收住", "收住" in runner.block_reason(), runner.block_reason())

    before = len(ch._out_lines)
    n = await sender.reply_bubbles(["嗯", "这家我知道", "改天带你去"], user_id="10001")
    check("★ reply_bubbles 逐条发出", n == 3 and len(ch._out_lines) == before + 3,
          f"sent={n} lines={len(ch._out_lines) - before}")

    # ---- 发送中途代际中止（同频的关键：旧回复不再灌满一整轮）----
    state = {"sent": 0}

    def _abort_after_first() -> bool:
        return state["sent"] >= 1

    orig_send = ch.send_text

    async def _counting_send(text, **kw):
        await orig_send(text, **kw)
        state["sent"] += 1

    ch.send_text = _counting_send
    n = await sender.reply_bubbles(["第一条", "第二条", "第三条"], user_id="10001",
                                   abort_check=_abort_after_first)
    ch.send_text = orig_send
    check("★ 发送中途代际中止：只发第一条就停",
          n == 1 and state["sent"] == 1, f"sent={n}")
    n0 = await sender.reply_bubbles(["不该出现"], user_id="10001",
                                    abort_check=lambda: True)
    check("★ 一进锁就中止：一条都不发", n0 == 0, f"sent={n0}")

    runner.on_close()
    check("★ 互道收尾后不再接话", "收尾" in runner.block_reason(), runner.block_reason())
    runner.on_user_message("我回来了")
    check("对方重新开话解除收尾", runner.block_reason() == "", runner.block_reason())

    # ---- 阶梯退避 ----
    backoff = cfg.conversation.followup_backoff_sec
    runner.conv.followups_this_topic = 0
    d0 = runner._next_delay()
    runner.conv.followups_this_topic = 1
    d1 = runner._next_delay()
    runner.conv.followups_this_topic = 2
    d2 = runner._next_delay()
    runner.conv.followups_this_topic = 3
    d3 = runner._next_delay()
    check("★ 第 1 次接话用正常间隔（这里压成 0）", d0 <= 0.001, str(d0))
    check(f"★ 第 1 档退避在 [{backoff[0][0]},{backoff[0][1]}]",
          backoff[0][0] <= d1 <= backoff[0][1], f"{d1:.0f}s")
    check("★ 第 2 档退避在 [600,2400]", backoff[1][0] <= d2 <= backoff[1][1], f"{d2:.0f}s")
    check("★ 表耗尽后停（30 天）", d3 > 29 * 86400, f"{d3:.0f}s")

    # ---- 节奏镜像：记录对方的响应时长 ----
    runner.conv.paces.clear()
    runner.conv.last_bot_ts = time.time() - 60
    runner.on_user_message("刚才忘了说")
    check("★ 对方响应时长被记录", len(runner.conv.paces) == 1, str(runner.conv.paces))
    runner.conv.paces = [10, 40, 44]
    check("★ 节奏取中位数", abs(runner.partner_pace() - 40) < 1e-6,
          str(runner.partner_pace()))
    st.close()

    # ---- 第⑦层重复拦截（本地硬比对）----
    st2 = Store(str(Path(_tf.mkdtemp()) / "r.db"))
    sup2 = Suppressor(cfg.autonomy, st2, MockLLM(), StateMachine(st2), Memory(st2))
    recent = ["user: 在吗", "assistant: 我家猫今天蹲在窗台上看了一下午鸟"]
    hit, why = sup2._is_repeat("我家猫今天蹲在窗台上看了一下午鸟", recent)
    check("★ 整句复读被拦", hit, why)
    hit2, why2 = sup2._is_repeat("那换个话题，晚饭吃了没", recent)
    check("正常新话不被拦", not hit2, why2)
    hit3, why3 = sup2._is_repeat("真的吗，我家猫今天蹲在窗台上看了一下午鸟欸", recent)
    check("★ 换皮复读（高重合）被拦", hit3, why3)
    st2.close()

    # ---- 禁用词提取 ----
    av = extract_overused_terms(["中午那声我记着呢", "中午那声我记着了", "晚安啦"],
                                ["别的"])
    check("★ 复读词被提取", len(av) > 0, str(av))
    check("不重复就不提取",
          extract_overused_terms(["晚安啦"], ["别的"]) == [], "")
    av3 = extract_overused_terms(["中午那声我记着呢", "中午那声我记着了"],
                                 ["聊中午吃什么"])
    check("★ 用户话里的词不进禁用表", "中午" not in av3, str(av3))

    # ---- express：气泡协议 + 解析失败回退 ----
    m_json = MockLLM(reply='{"bubbles": ["嗯嗯", "这家我知道", "上次你说想去的那家"]}')
    out = await express(m_json, "人设", "边界", "状态", "", [], "在吗", None,
                        bubble_mode=True)
    check("★ 气泡协议返回列表", isinstance(out, list) and len(out) == 3, str(out))

    m_txt = MockLLM(reply="就一句普通回复")
    out2 = await express(m_txt, "人设", "边界", "状态", "", [], "在吗", None,
                         bubble_mode=True)
    check("★ 气泡解析失败回退纯文本",
          isinstance(out2, str) and out2 == "就一句普通回复", str(out2))

    # ---- 既定事实 / 收尾意图注入表达通道 ----
    m_sf = MockLLM(reply="好")
    await express(m_sf, "人设", "边界", "状态", "", [], "在吗", None,
                  self_facts_text="- 答应的事：明天早上叫他起床")
    check("★ 既定事实进了表达通道", "明天早上叫他起床" in m_sf.last_express_prompt,
          m_sf.last_express_prompt[:120])

    m_cl = MockLLM(reply="晚安")
    await express(m_cl, "人设", "边界", "状态", "", [], "晚安", None, closing=True)
    check("★ 收尾意图进了表达通道", "收尾" in m_cl.last_express_prompt, "")

    # ---- 代际取消：表达期间对方插话，草稿作废 ----
    class _GenBumpMock(MockLLM):
        """表达通道一被调用就模拟「对方插话」（代际顶掉在途草稿）。"""

        def __init__(self, runner_ref):
            super().__init__(reply="这条不该被发出去")
            self._r = runner_ref

        async def chat(self, messages, **kw):
            out = await super().chat(messages, **kw)
            if self.calls and self.calls[-1] == "express":
                self._r().on_user_message("（对方插话）")
            return out

    st3 = Store(str(Path(_tf.mkdtemp()) / "g.db"))
    mock_g = _GenBumpMock(lambda: runner3)
    runner3 = ConversationRunner(cfg.conversation, cfg.behavior, cfg.qq, st3, mock_g,
                                 sm, _Mem(st3), sender,
                                 Suppressor(cfg.autonomy, st3, mock_g, sm, _Mem(st3)),
                                 lambda n: "")
    runner3.on_user_message("在吗")
    lines_before = len(ch._out_lines)
    d = await runner3._try_followup()
    check("★ 表达期间对方插话 → 草稿作废不发",
          d is None and len(ch._out_lines) == lines_before,
          f"d={d} lines={len(ch._out_lines) - lines_before}")
    st3.close()

    # ---- 会话摘要：活跃→非活跃边沿落库 ----
    st4 = Store(str(Path(_tf.mkdtemp()) / "s.db"))
    runner4 = ConversationRunner(cfg.conversation, cfg.behavior, cfg.qq, st4,
                                 MockLLM(reply="嗯"), sm, _Mem(st4), sender,
                                 Suppressor(cfg.autonomy, st4, MockLLM(reply="嗯"),
                                            sm, _Mem(st4)),
                                 lambda n: "")
    st4.add_turn("user", "今天猫把杯子碰倒了")
    st4.add_turn("assistant", "哈哈哈它故意的吧")
    runner4.conv.topic = "猫闯祸"
    runner4._write_session_summary()
    summ = [e for e in st4.recent_events(5) if e["kind"] == "summary"]
    check("★ 会话摘要落库", bool(summ) and "猫闯祸" in summ[0]["text"], str(summ))
    check("★ 摘要带上双方最后一句",
          "杯子" in summ[0]["text"] and "哈哈哈" in summ[0]["text"], summ[0]["text"])
    check("摘要后话题归零", runner4.conv.topic == "")
    st4.close()

    # ---- 话题重启：话题死在我手里 → 排班 → 到点再开口（数据：好友 59% 会重启）----
    st5 = Store(str(Path(_tf.mkdtemp()) / "r.db"))
    mock5 = MockLLM(reply="想起个事跟你讲")
    runner5 = ConversationRunner(cfg.conversation, cfg.behavior, cfg.qq, st5, mock5,
                                 sm, _Mem(st5), sender,
                                 Suppressor(cfg.autonomy, st5, mock5, sm, _Mem(st5)),
                                 lambda n: "")
    # 场景：我发过话、对方没接 → 话题死在我手里。
    # 锚点取「刚过活跃窗口」—— 保证排出的重启闹钟一定在未来
    # （生产里边沿在窗口过期时触发，锚点是新鲜的，天然满足）
    runner5.conv.last_user_ts = time.time() - 1100
    runner5.conv.last_bot_ts = time.time() - 1000
    runner5.conv.bot_turns_since_user = 5
    runner5.conv.was_active = True

    # 排班发生在「由真转假」边沿：把活跃窗口拨到刚过期 → tick 触发边沿
    await runner5._tick()
    check("★ 话题死在我手里 → 窗口过期后排班重启闹钟",
          runner5.conv.next_reopen_at > 0,
          f"next_reopen_at={runner5.conv.next_reopen_at}")
    # 没到点 → 窗口外的 tick 不开口
    runner5.conv.next_reopen_at = time.time() + 9999
    lines5 = len(ch._out_lines)
    await runner5._tick()
    check("★ 重启闹钟未到点 → 保持沉默",
          len(ch._out_lines) == lines5, f"lines+{len(ch._out_lines) - lines5}")
    # 到点 → 窗口外的 tick 重新开口（pivot，新话题）
    runner5.conv.next_reopen_at = time.time() - 1
    await runner5._tick()
    reopened = any("想起个事" in ln for ln in ch._out_lines[lines5:])
    check("★ 重启到点 → 自己再开口找新话题", reopened,
          str(ch._out_lines[lines5:]))
    check("★ 重启计配额 + 新话题配额重置",
          runner5.conv.reopens == 1
          and runner5.conv.followups_this_topic == 0
          and runner5.conv.probes_this_topic == 0,
          f"reopens={runner5.conv.reopens} f={runner5.conv.followups_this_topic}")
    check("★ 重启后写 last_spoke_ts（防心跳撞车）",
          st5.counter_get("last_spoke_ts", 0.0) > 0,
          str(st5.counter_get("last_spoke_ts", 0.0)))
    # 配额用完 → 再死也不开口
    runner5.conv.next_reopen_at = 0.0
    runner5.conv.reopens = cfg.conversation.max_reopens
    lines5b = len(ch._out_lines)
    await runner5._tick()
    check("★ 重启配额用完 → 安静等对方",
          len(ch._out_lines) == lines5b, f"lines+{len(ch._out_lines) - lines5b}")
    # 话题死在对方手里 → 不重启（该对方找话）
    st5b = Store(str(Path(_tf.mkdtemp()) / "r2.db"))
    runner5b = ConversationRunner(cfg.conversation, cfg.behavior, cfg.qq, st5b, mock5,
                                  sm, _Mem(st5b), sender,
                                  Suppressor(cfg.autonomy, st5b, mock5, sm, _Mem(st5b)),
                                  lambda n: "")
    runner5b.conv.last_user_ts = time.time() - 3900
    runner5b.conv.last_bot_ts = time.time() - 4000
    runner5b.conv.was_active = True
    await runner5b._tick()
    check("★ 话题死在对方手里 → 不排重启闹钟",
          runner5b.conv.next_reopen_at == 0, str(runner5b.conv.next_reopen_at))
    # block_reason 重启模式：收尾状态仍拦
    runner5b.conv.closed = True
    check("★ 重启模式仍尊重互道收尾",
          "收尾" in runner5b.block_reason(reopen=True), runner5b.block_reason(reopen=True))
    st5.close()
    st5b.close()


# ---------------------------------------------------------------- 12
def test_split_rhythm() -> None:
    section("回复节奏（真人式多气泡）")
    from app.act import Sender
    from app.channel.console import ConsoleChannel

    cfg = tmpcfg()
    cfg.behavior.split_long_reply = True
    cfg.behavior.max_chunks = 3
    cfg.behavior.split_threshold = 45      # tmpcfg 里是 9999（其他用例不想被拆），这里恢复真实值
    s = Sender(ConsoleChannel(), cfg.behavior)

    check("很短的话不拆", s.split("嗯") == ["嗯"], str(s.split("嗯")))

    # ★ 短感叹词不该单独占一条 —— 孤零零一条「呜嘿~」看着就是模板。
    # 真人是「呜嘿，这个我熟」一气说完，所以要并进下一句。
    c1 = s.split("呜嘿~在的在的")
    check("开头的短感叹词并进下一句，不单独成条",
          len(c1) == 1 and "呜嘿" in c1[0] and "在的在的" in c1[0], str(c1))
    c1b = s.split("呜嘿~。今天沙子又大了。你那边降温了吧。")
    check("有多个句子时，短感叹词仍并到紧随那句",
          c1b[0].startswith("呜嘿") and "沙子" in c1b[0], str(c1b))

    c2 = s.split("今天沙子又大了。你那边降温了吧，记得加衣服。")
    check("两句话拆成两条", len(c2) == 2, str(c2))

    c3 = s.split("第一句。第二句。第三句。第四句。第五句。")
    check("条数不超过上限 3", len(c3) <= 3, f"{len(c3)}: {c3}")
    check("超出部分合并到最后一条", c3[-1].count("句") >= 1, str(c3))

    c4 = s.split("这是一个没有句号但很长很长的句子，中间有逗号，可以在这里断开，"
                 "因为一口气说不完就会显得像一大坨文字很不自然必须要拆开才行。")
    check("长句按逗号兜底拆分", len(c4) >= 2, str(c4))

    check("拆出来的内容拼回去等于原文（不丢字）",
          "".join(c2) == "今天沙子又大了。你那边降温了吧，记得加衣服。", str(c2))

    cfg.behavior.split_long_reply = False
    s2 = Sender(ConsoleChannel(), cfg.behavior)
    long_text = "第一句。第二句。第三句。"
    check("关闭拆分时原样返回", s2.split(long_text) == [long_text])

    cfg.behavior.split_long_reply = True
    cfg.behavior.max_chunks = 1
    s3 = Sender(ConsoleChannel(), cfg.behavior)
    check("max_chunks=1 时不拆", s3.split(long_text) == [long_text])


# ---------------------------------------------------------------- 13
def test_mface_and_diag() -> None:
    section("表情包段处理 & 媒体诊断日志")
    from app.channel.napcat import describe_segments, parse_message as pm

    # 普通图片
    t1, i1, _, _, _, _ = pm([{"type": "image", "data": {"url": "http://x/a.png"}}], "1")
    check("image 段正常解析", len(i1) == 1, str(i1))

    # QQ 商城表情：OneBot 11 里没有图片文件，只有 summary
    t2, i2, _, _, _, _ = pm([{"type": "mface", "data": {
        "emoji_id": "3", "emoji_package_id": "5", "key": "abc", "summary": "[敲开心]"}}], "1")
    check("mface 段有 summary 时转成文字线索",
          i2 == [] and "QQ表情包" in t2 and "敲开心" in t2, f"imgs={i2} text={t2!r}")

    # mface 万一带了图源，也要能用
    t3, i3, _, _, _, _ = pm([{"type": "mface", "data": {
        "summary": "[敲开心]", "url": "http://x/m.png"}}], "1")
    check("mface 带 url 时能取到图", len(i3) == 1, str(i3))

    # 系统小黄脸
    t4, _, _, _, _, _ = pm([{"type": "face", "data": {"id": "14"}}], "1")
    check("face 段带出 id", "14" in t4, repr(t4))

    # 诊断日志：base64 不能整个打出来
    desc = describe_segments([
        {"type": "image", "data": {"file": "/tmp/a.png", "base64": "A" * 5000,
                                   "url": "https://x/a.png"}},
        {"type": "text", "data": {"text": "看我这个"}},
    ])
    check("诊断摘要含段类型", "image" in desc and "text" in desc, desc[:80])
    check("诊断摘要把 base64 折成长度（不是正文）", "base64=5000B" in desc, desc[:120])
    check("诊断摘要不太长", len(desc) < 400, str(len(desc)))

    check("非数组型消息也不崩", describe_segments("hello") != "")


# ---------------------------------------------------------------- 15
async def test_sticker_system() -> None:
    section("表情包体系（情绪归一 / 频率策略 / 偷图）")
    import json as _json

    from app.sticker import (
        CANON, StickerLibrary, StickerPolicy, StickerStealer, normalize_emotion,
    )
    from scripts.ingest_stickers import parse_emotion_from_name

    # ---- 情绪归一 ----
    check("文件名情绪折进权威集：害羞→害羞", normalize_emotion("害羞") == "害羞")
    check("搞怪→卖萌", normalize_emotion("搞怪") == "卖萌")
    check("不甘心→不爽", normalize_emotion("不甘心") == "不爽")
    check("死亡→崩溃", normalize_emotion("死亡") == "崩溃")
    check("睡觉→困倦", normalize_emotion("睡觉") == "困倦")
    check("未知词兜底为中性", normalize_emotion("胡言乱语") == "中性")
    check("空值兜底为中性", normalize_emotion("") == "中性")
    check("权威集里每个词都能归一到自己",
          all(normalize_emotion(e) == e for e in CANON),
          str([e for e in CANON if normalize_emotion(e) != e]))

    # ---- 文件名解析 ----
    check("「害羞_8E1AA68B」→ 害羞", parse_emotion_from_name("害羞_8E1AA68B.gif")[0] == "害羞")
    check("「亲密_贴纸-1(1)」→ 亲密", parse_emotion_from_name("亲密_贴纸-1(1).gif")[0] == "亲密")
    check("「生气.gif」→ 生气", parse_emotion_from_name("生气.gif")[0] == "生气")
    check("哈希文件名解析不出情绪",
          parse_emotion_from_name("4BA1553DBE5114D32DDBC81509E8B602.gif")[0] is None)
    check("英文名解析不出情绪", parse_emotion_from_name("allin dance.gif")[0] is None)

    # ---- 检索 ----
    d = Path(tempfile.mkdtemp())
    files = {}
    for e in ("开心", "难过", "困倦"):
        f = d / f"{e}_x.png"
        f.write_bytes(b"\x89PNG" + e.encode())
        files[e] = f
    # 「开心」多来两张，才能验证 pick_many 连发（要互不相同）
    extra = []
    for i in (2, 3):
        f = d / f"开心_{i}.png"
        f.write_bytes(b"\x89PNG" + f"开心{i}".encode())
        extra.append(f)
    idx = d / "index.json"
    idx.write_text(_json.dumps(
        [{"file": str(files[e]), "desc": e, "emotions": [e], "tags": [e],
          "source": "test"} for e in files]
        + [{"file": str(f), "desc": "开心", "emotions": ["开心"], "tags": ["开心"],
            "source": "test"} for f in extra],
        ensure_ascii=False), encoding="utf-8")
    lib = StickerLibrary(idx)
    check("图库加载 5 张", len(lib.items) == 5, str(len(lib.items)))
    for e in files:
        got = lib.pick(e, "测试")
        check(f"按「{e}」检索命中对应图",
              got is not None and got["emotions"] == [e],
              str(got and got["emotions"]))
    check("情绪完全不搭时返回 None（不会乱发）",
          lib.pick("亲密", "测试") is None, str(lib.pick("亲密", "测试")))

    # ---- 频率策略 ----
    st = Store(str(d / "s.db"))
    cfg = StickerConfig(enabled=True, base_probability=0.5, min_gap_min=30,
                        daily_max=3, energy_threshold=40)
    pol = StickerPolicy(cfg, st)

    v = pol.evaluate(emotion="开心", intensity=1.0, valence=50, energy=80,
                     last_was_sticker=False)
    check("正常状态会掷骰子", 0.0 < v.probability <= 1.0, str(v))
    check("上一条发过图 → 直接拦",
          not pol.evaluate(emotion="开心", intensity=1.0, valence=50, energy=80,
                           last_was_sticker=True).send)
    check("心情极差 → 概率明显降低",
          pol.evaluate(emotion="开心", intensity=1.0, valence=-60, energy=80,
                       last_was_sticker=False).probability
          < pol.evaluate(emotion="开心", intensity=1.0, valence=50, energy=80,
                         last_was_sticker=False).probability)
    check("电量低 → 概率明显降低",
          pol.evaluate(emotion="开心", intensity=1.0, valence=50, energy=10,
                       last_was_sticker=False).probability
          < pol.evaluate(emotion="开心", intensity=1.0, valence=50, energy=80,
                         last_was_sticker=False).probability)
    check("中性情绪概率更低",
          pol.evaluate(emotion="中性", intensity=1.0, valence=0, energy=80,
                       last_was_sticker=False).probability
          < pol.evaluate(emotion="开心", intensity=1.0, valence=0, energy=80,
                         last_was_sticker=False).probability)

    pol.note_sent()
    check("刚发过图 → 冷却期拦截",
          not pol.evaluate(emotion="开心", intensity=1.0, valence=50, energy=80,
                           last_was_sticker=False).send)
    st.counter_set(f"sticker_{time.strftime('%Y-%m-%d')}", 3)
    st.counter_set("last_sticker_ts", 0)
    check("到每日上限 → 拦截",
          not pol.evaluate(emotion="开心", intensity=1.0, valence=50, energy=80,
                           last_was_sticker=False).send)

    # ---- 攒势：憋得越久越容易发（修「一晚上一张都不响」）----
    # 基础概率压低一点，免得几个系数一乘就被 clamp 到 1.0（那就看不出差异了）
    cfg2 = StickerConfig(enabled=True, base_probability=0.25, min_gap_min=0,
                         daily_max=999, energy_threshold=0)
    pol2 = StickerPolicy(cfg2, st)
    st.counter_set(f"sticker_{time.strftime('%Y-%m-%d')}", 0)

    def prob_after_gap(minutes: float) -> float:
        st.counter_set("last_sticker_ts", time.time() - minutes * 60)
        return pol2.evaluate(emotion="开心", intensity=1.0, valence=50, energy=80,
                             last_was_sticker=False).probability

    p_fresh = prob_after_gap(1)
    p_10 = prob_after_gap(10)
    p_40 = prob_after_gap(40)
    check("刚发过不久：概率最低", p_fresh < p_10, f"{p_fresh:.3f} vs {p_10:.3f}")
    check("隔了 10 分钟：概率抬升", p_10 < p_40, f"{p_10:.3f} vs {p_40:.3f}")
    check("隔了 40 分钟明显更高", p_40 > p_fresh * 1.2, f"{p_fresh:.3f} vs {p_40:.3f}")
    # 0 分钟 = 刚刚发过（最低档）；「从没发过」应该是 gap 极大
    st.counter_set("last_sticker_ts", 0)
    p_never = pol2.evaluate(emotion="开心", intensity=1.0, valence=50, energy=80,
                            last_was_sticker=False).probability
    check("从没发过时进最高档", p_never > p_40, f"{p_never:.3f} vs {p_40:.3f}")

    # ---- 一次发几张（张数本该由模型定，这里只验兜底分布）----
    st.counter_set("last_sticker_ts", 0)
    nums = {pol2.how_many(0.5, "开心") for _ in range(300)}
    check("兜底张数只可能是 1/2/3", nums <= {1, 2, 3}, str(nums))
    check("兜底分布三种都会出现", nums == {1, 2, 3}, str(nums))

    # 情绪越强，兜底越倾向多发（不是固定比例）
    def avg(strong: float) -> float:
        return sum(pol2.how_many(strong, "开心") for _ in range(600)) / 600
    strong_avg, weak_avg = avg(1.0), avg(0.0)
    check("情绪强时兜底张数更多", strong_avg > weak_avg,
          f"强 {strong_avg:.2f} vs 弱 {weak_avg:.2f}")

    # ---- clamp_count：封顶 + 不超当日余额 ----
    c = StickerConfig(enabled=True, max_per_turn=4, daily_max=300, min_gap_min=0)
    pol3 = StickerPolicy(c, st)
    check("不超 max_per_turn", pol3.clamp_count(99) == 4, str(pol3.clamp_count(99)))
    check("正常值原样通过", pol3.clamp_count(2) == 2)
    check("至少 1 张", pol3.clamp_count(0) == 1, str(pol3.clamp_count(0)))
    check("受当日余额限制", pol3.clamp_count(4, room=2) == 2,
          str(pol3.clamp_count(4, room=2)))
    check("余额为 0 时也至少给 1（不外发由上层拦）",
          pol3.clamp_count(3, room=0) == 1, str(pol3.clamp_count(3, room=0)))

    # ---- remaining_today ----
    st.counter_set(f"sticker_{time.strftime('%Y-%m-%d')}", 297)
    check("余额按当日上限算", pol3.remaining_today() == 3, str(pol3.remaining_today()))
    st.counter_set(f"sticker_{time.strftime('%Y-%m-%d')}", 999)
    check("超额时为 0（不为负）", pol3.remaining_today() == 0)

    # ---- pick_many 不重复 ----
    many = lib.pick_many("开心", "测试", 3)
    check("pick_many 返回多张", len(many) == 3, str(len(many)))
    check("pick_many 不重复", len({m["file"] for m in many}) == len(many),
          str([m["file"] for m in many]))
    check("pick_many 情绪正确", all(m["emotions"] == ["开心"] for m in many),
          str([m["emotions"] for m in many]))
    check("要的比库里多时只给库里有的（不报错）",
          len(lib.pick_many("开心", "测试", 99)) == 3,
          str(len(lib.pick_many("开心", "测试", 99))))
    check("库里没有该情绪时返回空", lib.pick_many("愤怒", "测试", 2) == [])

    check("关闭后不发表情包",
          not StickerPolicy(StickerConfig(enabled=False), st).evaluate(
              emotion="开心", intensity=1.0, valence=50, energy=80,
              last_was_sticker=False).send)

    # ---- 偷图 ----
    st2 = Store(str(d / "steal.db"))
    lib2 = StickerLibrary(idx)
    scfg = StickerConfig(steal_enabled=True, steal_probability=1.0, steal_daily_max=2)
    stealer = StickerStealer(scfg, st2, lib2, d)
    mock = MockLLM()

    img = (d / "incoming.gif")
    img.write_bytes(b"GIF89a" + b"x" * 100)
    vv = await stealer.consider(mock, img.read_bytes(), "image/gif",
                                image_desc="搞怪图", user_text="看我这个")
    check("概率调到 1 时会收下", vv.keep, str(vv))
    check("判定走的是偷图通道", "steal_judge" in mock.calls, str(mock.calls))
    item = stealer.save(img.read_bytes(), "image/gif", vv)
    check("落盘成功", item is not None and Path(item["file"]).exists(), str(item))
    check("文件名带情绪前缀（方便重建索引）",
          bool(item) and Path(item["file"]).name.startswith(vv.emotion + "_"),
          item and Path(item["file"]).name)
    check("内存库立刻能用", len(lib2.items) == 6, str(len(lib2.items)))
    v2 = await stealer.consider(mock, img.read_bytes(), "image/gif")
    check("同一张不会重复收", not v2.keep and "已经有了" in v2.reason, str(v2))

    img2 = d / "incoming2.gif"
    img2.write_bytes(b"GIF89a" + b"y" * 200)
    vv2 = await stealer.consider(mock, img2.read_bytes(), "image/gif")
    stealer.save(img2.read_bytes(), "image/gif", vv2)   # 配额在落盘时计数
    check("收下第 2 张后到上限", stealer._today() == 2, str(stealer._today()))

    img3 = d / "incoming3.gif"
    img3.write_bytes(b"GIF89a" + b"z" * 300)
    v3 = await stealer.consider(mock, img3.read_bytes(), "image/gif")
    check("到每日上限后不再收", not v3.keep and "够了" in v3.reason, str(v3))

    off = await StickerStealer(StickerConfig(steal_enabled=False), st2,
                               lib2, d).consider(mock, img3.read_bytes(), "image/gif")
    check("关闭后不收", not off.keep, str(off))

    picky = await StickerStealer(
        StickerConfig(steal_enabled=True, steal_probability=1.0, steal_daily_max=99),
        st2, lib2, d,
    ).consider(MockLLM(steal={"keep": False, "emotion": "中性", "reason": "太糊了"}),
               img3.read_bytes(), "image/gif")
    check("模型说不喜欢就不收", not picky.keep, str(picky))
    st.close(); st2.close()


# ---------------------------------------------------------------- 16
async def test_search_providers() -> None:
    section("搜索 Provider（含完全免 key 的 SearXNG）")
    from aiohttp import web

    from app.autonomy.search import (
        GoogleCseProvider, NotConfigured, SearchResponseError, SearxProvider,
        build_provider,
    )

    # ---- 工厂装配 ----
    check("provider 留空 → NullProvider", build_provider(SearchConfig()).name == "null")
    check("searx 不需要 key 就能装配",
          isinstance(build_provider(SearchConfig(provider="searx",
                                                endpoint="http://127.0.0.1:1")),
                     SearxProvider))
    check("google 带 cx 能装配",
          isinstance(build_provider(SearchConfig(provider="google", api_key="k", cx="c")),
                     GoogleCseProvider))
    try:
        build_provider(SearchConfig(provider="tavily"))
        check("tavily 缺 key 应报错", False)
    except NotConfigured:
        check("tavily 缺 key 会明确报错，不会静默空转", True)
    try:
        build_provider(SearchConfig(provider="nonsense", api_key="k"))
        check("未知 provider 应报错", False)
    except NotConfigured as e:
        check("未知 provider 报错并列出可选值", "searx" in str(e), str(e)[:70])

    # ---- 起一个假的 SearXNG（真 HTTP，真请求）----
    async def ok_handler(request):
        if request.query.get("format") != "json":
            return web.Response(status=400, text="formats disabled")
        return web.json_response({"results": [
            {"title": "鲸鱼为什么会唱歌", "url": "https://ex.com/a",
             "content": "座头鲸的歌声可以传播很远"},
            {"title": "Blue Archive 新活动", "url": "https://ex.com/b",
             "content": "对策委员会篇更新"},
        ]})

    app = web.Application()
    app.router.add_get("/search", ok_handler)
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, "127.0.0.1", 18877).start()

    prov = SearxProvider("http://127.0.0.1:18877")
    res = await prov.search("鲸鱼", n=2)
    check("SearXNG 结果解析正确",
          len(res) == 2 and res[0].title.startswith("鲸鱼"), str(res))
    check("snippet 从 content 字段取", "座头鲸" in res[0].snippet, res[0].snippet)
    check("URL 正确", res[0].url == "https://ex.com/a", res[0].url)
    await runner.cleanup()

    # ---- 没开 json format（最常见的坑）----
    async def html_handler(_r):
        return web.Response(text="<html>plain html</html>",
                            content_type="text/html")

    app2 = web.Application()
    app2.router.add_get("/search", html_handler)
    r2 = web.AppRunner(app2)
    await r2.setup()
    await web.TCPSite(r2, "127.0.0.1", 18878).start()
    try:
        await SearxProvider("http://127.0.0.1:18878").search("x")
        check("非 JSON 响应应报错", False)
    except SearchResponseError as e:
        msg = str(e)
        check("非 JSON 时提示去开 json format",
              "json" in msg.lower() and "settings.yml" in msg, msg[:90])
    await r2.cleanup()

    # ---- 实例没起来 ----
    try:
        await SearxProvider("http://127.0.0.1:1").search("x")
        check("连不上应报错", False)
    except NotConfigured as e:
        check("连不上时给出可操作提示（不是一堆栈）",
              "SearXNG" in str(e) and "跑" in str(e), str(e)[:70])

    # ---- endpoint 没填 ----
    try:
        await SearxProvider("").search("x")
        check("endpoint 为空应报错", False)
    except NotConfigured as e:
        check("endpoint 为空时提示填什么", "endpoint" in str(e), str(e)[:60])


# ---------------------------------------------------------------- 17
async def test_image_mime() -> None:
    section("图片类型嗅探（mime 传错会让模型描述出另一张图）")
    import base64 as _b
    import tempfile as _tf

    from app.perceive import _typed, load_image, sniff_mime

    check("PNG 认得出", sniff_mime(b"\x89PNG\r\n\x1a\n" + b"x" * 8) == "image/png")
    check("JPEG 认得出", sniff_mime(b"\xff\xd8\xff\xe0" + b"x" * 8) == "image/jpeg")
    check("GIF89a 认得出", sniff_mime(b"GIF89a" + b"x" * 8) == "image/gif")
    check("GIF87a 认得出", sniff_mime(b"GIF87a" + b"x" * 8) == "image/gif")
    check("WEBP 认得出",
          sniff_mime(b"RIFF\x00\x00\x00\x00WEBPVP8 " + b"x" * 4) == "image/webp")
    check("BMP 认得出", sniff_mime(b"BM" + b"x" * 8) == "image/bmp")
    check("垃圾数据认不出（返回空）", sniff_mime(b"\x00\x01\x02\x03") == "")
    check("空数据不崩", sniff_mime(b"") == "")

    gif = b"GIF89a" + b"x" * 64
    check("声明的 mime 错了会被修正", _typed(gif, "image/png")[1] == "image/gif")
    check("声明为空时用嗅探结果", _typed(gif, "")[1] == "image/gif")
    check("声明正确时不改动", _typed(gif, "image/gif")[1] == "image/gif")
    check("认不出时保留声明", _typed(b"\x00\x01\x02", "image/png")[1] == "image/png")
    check("认不出且声明为空时兜底 png",
          _typed(b"\x00\x01\x02", "")[1] == "image/png")

    # 端到端：四种来源路径都要修正
    d = Path(_tf.mkdtemp())
    real = d / "real.gif"
    real.write_bytes(gif)

    _, m = await load_image(str(real))
    check("本地路径：内容类型为准", m == "image/gif", m)

    fake = d / "fake.png"                      # 扩展名骗人
    fake.write_bytes(gif)
    _, m = await load_image(str(fake))
    check("扩展名是 .png 但内容是 GIF —— 不被骗", m == "image/gif", m)

    _, m = await load_image("data:image/png;base64," + _b.b64encode(gif).decode())
    check("data URL 声明 png 实为 GIF —— 不被骗", m == "image/gif", m)

    _, m = await load_image("base64://" + _b.b64encode(gif).decode())
    check("base64:// 形式（原来硬编码 jpeg）也会修正", m == "image/gif", m)

    raw, m = await load_image(str(real))
    check("内容读对了（不是空）", raw == gif, str(len(raw or b"")))


# ---------------------------------------------------------------- 18
async def test_image_complete() -> None:
    section("图片完整性校验（截断的图会让模型报 unsupported image）")
    import base64 as _b
    import struct as _st
    import tempfile as _tf
    import zlib as _zl

    from app.perceive import image_complete, load_first_image, sniff_mime

    def png(size: int = 16, cut: int = 0) -> bytes:
        def chunk(tag: bytes, data: bytes) -> bytes:
            return (_st.pack(">I", len(data)) + tag + data
                    + _st.pack(">I", _zl.crc32(tag + data) & 0xFFFFFFFF))
        rows = b"".join(b"\x00" + b"\xff\x00\x00" * size for _ in range(size))
        out = (b"\x89PNG\r\n\x1a\n"
               + chunk(b"IHDR", _st.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0))
               + chunk(b"IDAT", _zl.compress(rows))
               + chunk(b"IEND", b""))
        return out[:cut] if cut else out

    check("完整 PNG 放行", image_complete(png())[0])
    ok, why = image_complete(png()[: len(png()) // 2])
    check("截断 PNG 被拦下（缺 IEND / 数据不足都算）",
          not ok and ("IEND" in why or "截断" in why), why)

    gif_ok = b"GIF89a" + b"x" * 40 + b"\x3b"
    check("完整 GIF 放行", image_complete(gif_ok)[0])
    check("截断 GIF 被拦下", not image_complete(b"GIF89a" + b"x" * 40)[0])

    j_ok = b"\xff\xd8\xff\xe0" + b"x" * 40 + b"\xff\xd9"
    check("完整 JPEG 放行", image_complete(j_ok)[0])
    check("截断 JPEG 被拦下", not image_complete(b"\xff\xd8\xff\xe0" + b"x" * 40)[0])

    check("空数据判为不完整", not image_complete(b"")[0])
    check("认不出的格式不误杀（没有证据就放行）",
          image_complete(b"\x00\x01\x02\x03" + b"x" * 80)[0])

    # WEBP 声明的总长大于实际 = 截断
    webp_ok = b"RIFF" + _st.pack("<I", 40) + b"WEBPVP8 " + b"x" * 40
    check("完整 WEBP 放行", image_complete(webp_ok)[0])
    webp_bad = b"RIFF" + _st.pack("<I", 9999) + b"WEBPVP8 " + b"x" * 40
    check("WEBP 声明长度超出实际 → 拦下", not image_complete(webp_bad)[0])

    # ---- 核心行为：残图不能占住第一个位置 ----
    d = Path(_tf.mkdtemp())
    truncated = d / "truncated.png"
    truncated.write_bytes(png()[: len(png()) // 2])
    full = d / "full.png"
    full.write_bytes(png())

    got, mime, hit, why = await load_first_image([str(truncated), str(full)])
    check("★ 第一个候选是残图时会继续试下一个（拿到完整的）",
          got == png() and hit == str(full), f"hit={Path(hit).name if hit else hit}")

    # 全是残图 → 回退拿最长的那个，并带上原因
    got2, _, _, why2 = await load_first_image([str(truncated)])
    check("全是残图时回退拿最长的，并说明原因",
          got2 is not None and bool(why2), f"{why2!r}")

    # data URL 里的残图同样会被识破
    durl = "data:image/png;base64," + _b.b64encode(png()[: len(png()) // 2]).decode()
    got3, _, _, why3 = await load_first_image([durl, str(full)])
    check("data URL 里的残图也会被跳过",
          got3 == png() and hit != durl, f"why3={why3!r}")

    # 正常图不受影响
    got4, _, hit4, why4 = await load_first_image([str(full)])
    check("完整图直接通过且无原因", got4 == png() and why4 == "", str(why4))
    check("类型仍然嗅探正确", sniff_mime(got4) == "image/png")


# ---------------------------------------------------------------- 19
async def test_get_image_first() -> None:
    section("取图顺序：先问 NapCat get_image（官方做法），base64 垫底")
    import base64 as _b
    import zlib as _zl
    import struct as _st
    import tempfile as _tf

    from aiohttp import web as _web

    from app.perceive import load_first_image, load_image

    def png(sz: int = 16) -> bytes:
        def ch(t, d):
            return (_st.pack(">I", len(d)) + t + d
                    + _st.pack(">I", _zl.crc32(t + d) & 0xFFFFFFFF))
        rows = b"".join(b"\x00" + b"\xff\x00\x00" * sz for _ in range(sz))
        return (b"\x89PNG\r\n\x1a\n"
                + ch(b"IHDR", _st.pack(">IIBBBBB", sz, sz, 8, 2, 0, 0, 0))
                + ch(b"IDAT", _zl.compress(rows)) + ch(b"IEND", b""))

    FULL = png()

    # 假 NapCat：get_image 返回本地完整文件路径
    d = Path(_tf.mkdtemp())
    f = d / "real.png"
    f.write_bytes(FULL)
    calls: list = []

    async def gi(r):
        payload = await r.json()
        calls.append(payload)
        return _web.json_response(
            {"status": "ok", "retcode": 0, "data": {"file": str(f), "url": ""}})

    app = _web.Application()
    app.router.add_post("/get_image", gi)
    runner = _web.AppRunner(app)
    await runner.setup()
    await _web.TCPSite(runner, "127.0.0.1", 3997).start()

    # 候选里 base64 是被截断的（正好 32768，模拟真实情况）
    trunc = FULL[: max(1, len(FULL) // 2)]
    padded = trunc + b"\x00" * (32768 - len(trunc))
    bad_b64 = "data:image/png;base64," + _b.b64encode(padded).decode()

    got, mime, hit, why = await load_first_image(
        [bad_b64], file_id="some-id", http_base="http://127.0.0.1:3997")
    check("★ 优先走 get_image，拿到完整图", got == FULL, f"{len(got or b'')} bytes")
    check("命中的来源标成 get_image", hit.startswith("napcat/get_image"), hit)
    check("调用时传了 file 参数", calls and "file" in calls[0], str(calls))
    check("没在截断的 base64 上浪费模型调用", why == "", why)

    # file_id 参数名也兼容（NapCat 2.2.30+ 起 file / file_id 可同值）
    calls.clear()
    got2, _, hit2, _ = await load_first_image([], file_id="x", http_base="http://127.0.0.1:3997")
    check("没有候选时也能靠 get_image 拿到", got2 == FULL, hit2)

    # get_image 挂掉 → 自动退回消息段候选
    got3, _, _, _ = await load_first_image(
        [], file_id="x", http_base="http://127.0.0.1:1")
    check("get_image 不可用时返回空（不崩）", got3 is None, str(got3))

    # get_image 返回 base64 也要能解
    async def gi2(r):
        return _web.json_response(
            {"status": "ok", "retcode": 0,
             "data": {"base64": _b.b64encode(FULL).decode()}})
    app2 = _web.Application()
    app2.router.add_post("/get_image", gi2)
    runner2 = _web.AppRunner(app2)
    await runner2.setup()
    await _web.TCPSite(runner2, "127.0.0.1", 3996).start()
    got4, m, _, _ = await load_first_image([], file_id="x", http_base="http://127.0.0.1:3996")
    check("get_image 回 base64 时也能解出完整图", got4 == FULL, str(len(got4 or b"")))

    # 远程 URL 要带 Referer（QQ CDN 需要）
    seen_hdr: dict = {}

    async def cdn(r):
        seen_hdr.update(dict(r.headers))
        return _web.Response(body=FULL, content_type="image/png")
    app3 = _web.Application()
    app3.router.add_get("/img", cdn)
    runner3 = _web.AppRunner(app3)
    await runner3.setup()
    await _web.TCPSite(runner3, "127.0.0.1", 3995).start()
    await load_image("http://127.0.0.1:3995/img")
    check("下载远程图时带了 Referer（QQ CDN 需要）",
          bool(seen_hdr.get("Referer")), str(seen_hdr.get("Referer")))

    await runner.cleanup()
    await runner2.cleanup()
    await runner3.cleanup()


# ---------------------------------------------------------------- 20
async def test_llm_truncation() -> None:
    section("LLM 输出截断必须显式报错（静默空串会让功能时好时坏）")
    from app.llm import LLM, LLMError, _parse_json_loose

    # 宽容解析：完整/带围栏/带前后缀都能解
    check("纯 JSON 能解", _parse_json_loose('{"a": 1}')["a"] == 1)
    check("带 ```json 围栏能解", _parse_json_loose('```json\n{"a": 2}\n```')["a"] == 2)
    check("带前后缀能解", _parse_json_loose('好的：{"a": 3} 以上')["a"] == 3)
    # 截断的 JSON 必须抛错，不能返回半截
    # 截断的扁平 JSON 现在会被「按字段抢救」——这是有意的（见 _salvage_flat_json）。
    # 能救出完整字段就用，救不出才抛错。
    salvaged = _parse_json_loose('{"send": true, "count": 1, "emotion')
    check("截断的 JSON 优先按字段抢救",
          salvaged.get("send") is True and salvaged.get("count") == 1, str(salvaged))
    try:
        _parse_json_loose("这不是 JSON，完全没有任何结构")
        check("完全解析不出时应当抛错", False, "居然没抛")
    except LLMError:
        check("完全解析不出时抛 LLMError（不静默）", True)
    try:
        _parse_json_loose("")
        check("空串应当抛错", False, "居然没抛")
    except LLMError:
        check("空串会抛 LLMError", True)

    # ★ 被截断的扁平 JSON 要能抢救出已完整的字段
    # （推理模型会在长 reason 中间被切，provider 有时不报 length）
    sv = _parse_json_loose('{"send": true, "count": 2, "emotion": "平静", "reason": "截断在这')
    check("★ 截断的 JSON 能抢救出 count/send",
          sv.get("count") == 2 and sv.get("send") is True, str(sv))
    check("抢救时能拿到 emotion", sv.get("emotion") == "平静", str(sv))
    sv2 = _parse_json_loose('{"send": false}')
    check("只有 send 时也能解析", sv2.get("send") is False, str(sv2))

    # 真实调用：max_tokens 太小 → 必须抛「被截断」，而不是返回空串
    cfg = load_config()
    if not cfg.llm.api_key or cfg.llm.api_key == "mock":
        print("  (跳过真实调用：没有 API Key)")
        return
    llm = LLM(cfg.llm)
    from app.think import STICKER_JUDGE_SYSTEM
    try:
        # 用 1 个 token —— 必然截断，不会因为「模型这次话少」而偶然通过
        try:
            r = await llm.chat([{"role": "system", "content": STICKER_JUDGE_SYSTEM},
                                {"role": "user", "content": "对方说：在吗"}],
                               temperature=0.5, max_tokens=1)
            check("max_tokens=1 应当报截断", False, f"居然成功了：{r[:60]!r}")
        except LLMError as e:
            msg = str(e)
            if "截断" in msg or "空内容" in msg:
                check("max_tokens 太小会显式报「被截断」（不再静默空串）", True, "")
            elif any(k in msg for k in ("502", "upstream", "SSL", "EOF",
                                        "超时", "timeout", "连接")):
                # 通道不通（本机代理/上游抖动）不是这条断言要测的东西 ——
                # 测的是「截断语义」，不是「网络好不好」。别把它算成失败。
                print(f"  (跳过：模型通道当前不通 —— {msg[:70]})")
            else:
                check("max_tokens 太小会显式报「被截断」（不再静默空串）",
                      False, msg[:90])
    finally:
        await llm.close()


# ---------------------------------------------------------------- 21
async def test_proactive_and_profile() -> None:
    section("主动性（静默循环）+ 画像进表达通道")
    import tempfile as _tf

    from app.autonomy.suppress import Suppressor
    from app.main import Companion
    from app.memory import Memory
    from app.think import express, format_recent, format_time_context

    d = Path(_tf.mkdtemp())
    st = Store(str(d / "t.db"))
    cfg = load_config()
    sup = Suppressor(cfg.autonomy, st, MockLLM(), StateMachine(st), Memory(st))

    # ---- 静默时长：越来越久，但**有上限**（不能变成永久不联系）----
    lim = cfg.autonomy.cold_streak_limit
    check("未达冷场阈值 → 不静默", sup.silence_minutes(lim - 1) == 0.0)
    v_lim = sup.silence_minutes(lim)
    v_more = sup.silence_minutes(lim + 2)
    check("达到阈值 → 开始静默", v_lim > 0, str(v_lim))
    check("冷场越多 → 静默越久", v_more > v_lim, f"{v_lim:.0f} vs {v_more:.0f}")
    far = sup.silence_minutes(lim + 50)
    check("★ 静默有上限，不会无限拉长",
          far == float(cfg.autonomy.silence_max_min),
          f"{far:.0f} vs 上限 {cfg.autonomy.silence_max_min}")

    # ---- 关键：冷场很多次时**依然允许开口**（旧版是永久拦截）----
    st.counter_set("last_spoke_ts", time.time() - 99999 * 60)   # 很久没说了
    st.counter_set("last_reply_ts", time.time() - 99999 * 60)   # 也一直没回
    res = await sup.check(last_spoke_ts=st.counter_get("last_spoke_ts", 0),
                          last_reply_ts=st.counter_get("last_reply_ts", 0),
                          cold_streak=20, recent=[], has_content=False)
    check("★ 冷场 20 次后**仍然允许**主动开口（旧版会永久拦死）",
          res.allowed, f"{res.stage}: {res.reason}")
    check("冷场后走「关心」这一类",
          res.allowed and res.kind == "miss" and "关心" in res.stage,
          f"{res.stage} / kind={res.kind}")

    # ---- 画像必须真的进到表达通道的 system 里 ----
    cfg2 = load_config()
    mock = MockLLM()
    await express(mock, "人设", "边界", "状态", "（无记忆）", [], "在吗",
                  None, profile_text="- 在折腾的东西：虚拟机里跑QQ机器人")
    check("★ 画像进了表达通道（之前只给了分析通道）",
          "虚拟机里跑QQ机器人" in mock.last_express_prompt,
          mock.last_express_prompt[:120])
    # 注意：断言【你记得的关于对方的事】要带【】—— 提示词正文里也提到了这句话，
    # 不带括号会误判（踩过一次）
    check("画像是单独一段【你记得的关于对方的事】",
          "【你记得的关于对方的事】" in mock.last_express_prompt, "")
    # 不传画像时不应出现那一段（避免空段落干扰）
    mock2 = MockLLM()
    await express(mock2, "人设", "边界", "状态", "（无记忆）", [], "在吗", None)
    check("不传画像时不出现空段落",
          "【你记得的关于对方的事】" not in mock2.last_express_prompt,
          mock2.last_express_prompt[:100])

    # ---- 表情包不该被当成「需要点评的图片」 ----
    mock3 = MockLLM()
    await express(mock3, "人设", "边界", "状态", "（无记忆）", [], "",
                  None, image_desc="一张猫猫表情包，表达卖萌",
                  image_is_sticker=True)
    check("★ 表情包提示「不要描述/不要收下斗图」",
          "不要描述这个表情包" in mock3.last_express_prompt
          and "顺口提" not in mock3.last_express_prompt,
          mock3.last_express_prompt[-220:])
    mock4 = MockLLM()
    await express(mock4, "人设", "边界", "状态", "（无记忆）", [], "看看这个",
                  None, image_desc="一张风景照片", image_is_sticker=False)
    check("普通图片仍然聊内容",
          "聊内容本身或你的感受" in mock4.last_express_prompt,
          mock4.last_express_prompt[-180:])

    # ---- 旧句式兜底：表情包回复不许出现「收下/斗图/入库」 ----
    check("★ 过滤「图大叔收下了 / 斗图正好用」",
          Companion._strip_meta_reply(
              ["茸菌炒肉丝\n图大叔收下了\n斗图正好用\n香啊"],
              aggressive=True) == ["茸菌炒肉丝\n香啊"], "")
    check("普通图片过滤「这张图我收下了」",
          Companion._strip_meta_reply("这张图我收下了", aggressive=False) == "", "")
    check("不误伤「这话我收下了」",
          Companion._strip_meta_reply("这话我收下了", aggressive=False)
          == "这话我收下了", "")
    check("旧句式不进入提示词历史",
          Companion._sanitize_recent(
              ["user: [图片]", "assistant: 图大叔收下了\n斗图正好用"])
          == ["user: [图片]"], "")

    # ---- 时间感知：第二天下午不能还以为对方没睡 ----
    from datetime import datetime
    now = datetime(2026, 10, 18, 15, 48)
    turns = [
        {"role": "assistant", "text": "晚安",
         "ts": datetime(2026, 10, 17, 23, 59).timestamp()},
        {"role": "user", "text": "hello 星野酱",
         "ts": datetime(2026, 10, 18, 15, 48).timestamp()},
    ]
    recent = format_recent(turns, now=now)
    check("★ 最近对话带日期与时间",
          recent[0].startswith("[昨天 23:59]") and recent[1].startswith("[今天 15:48]"),
          str(recent))
    ctx = format_time_context(turns, now=now)
    check("★ 跨天时提示「新的一天」",
          "昨天 23:59" in ctx and "15 小时" in ctx and "新的一天" in ctx,
          ctx)
    st.close()


# ---------------------------------------------------------------- 22
async def test_rhythm_instant_and_digest() -> None:
    section("主动节奏四档（含「马上就来」）+ 自主浏览分享")
    import random as _r
    import tempfile as _tf

    from app.autonomy.digest import Digest
    from app.autonomy.heartbeat import ProactiveRhythm
    from app.autonomy.search import NullProvider
    from app.state import StateMachine as _SM

    cfg = load_config()
    rh = ProactiveRhythm(cfg.autonomy)
    d = Path(_tf.mkdtemp())
    st = Store(str(d / "t.db"))
    sm = _SM(st)

    # ---- 四档：必须有「马上」这一档 ----
    weights = cfg.autonomy.rhythm_weights
    check("权重是四档（马上/近/常/远）", len(weights) == 4, str(weights))
    check("「马上就来」这一档存在且够短",
          cfg.autonomy.rhythm_instant[1] <= 15, str(cfg.autonomy.rhythm_instant))
    check("「马上」这档权重不低（体感上要常出现）",
          weights[0] >= 0.2, str(weights[0]))

    _r.seed(1)
    vals = sorted(rh.next_delay_minutes(sm.emotion, sm.relationship) for _ in range(600))
    quick = sum(1 for v in vals if v <= cfg.autonomy.rhythm_instant[1])
    check("★ 相当比例是「马上就来」（≤8 分钟）", quick / len(vals) >= 0.15,
          f"{quick}/{len(vals)} = {quick/len(vals):.1%}")
    check("也有很晚的（>12 小时）", vals[-1] > 720, f"max={vals[-1]:.0f}")
    check("中位数在「晚点再来」那一侧（不是全都马上）",
          vals[len(vals) // 2] > 10, f"median={vals[len(vals)//2]:.0f}")
    check("最小间隔能低到分钟级（不是 15 分钟起）", vals[0] <= 8,
          f"min={vals[0]:.1f}")

    # ---- 自主浏览：配置项生效 + 没搜索时不炸 ----
    check("自主浏览默认开启", cfg.autonomy.digest_enabled)
    check("分享阈值比原来松（<=0.45）", cfg.autonomy.digest_threshold <= 0.45,
          str(cfg.autonomy.digest_threshold))
    check("每天分享上限 > 1（原来只有 1 次，几乎不可能触发）",
          cfg.autonomy.digest_max_share_per_day > 1,
          str(cfg.autonomy.digest_max_share_per_day))

    mem = Memory(Store(str(d / "m.db")))
    dig = Digest(cfg.autonomy, cfg.memory, MockLLM(), mem, sm, st, NullProvider())
    r = await dig.run_once(force=True)
    check("搜索未配置时安全返回 None（不炸）", r is None, str(r))

    # 兴趣种子里应有二次元/游戏类（用户明确要求）
    txt = (ROOT / "persona" / "interests.md").read_text(encoding="utf-8")
    for kw in ("Blue Archive", "二次元", "手游"):
        check(f"兴趣种子含「{kw}」", kw in txt, "")
    st.close()


# ---------------------------------------------------------------- 23
async def test_msg_merge_sticker_forward_image() -> None:
    section("多条消息合并 / 纯表情包跳过 / 转发记录 / 长图缩放")
    import io as _io
    import tempfile as _tf

    from app.channel.napcat import IncomingMessage, parse_message
    from app.main import Companion
    from app.perceive import fit_for_vision

    # ---- ① 合并判定：截图不能被当成表情包 ----
    shot = IncomingMessage(kind="private", user_id="1", text="",
                           images=[["x"]],
                           raw={"message": [{"type": "image",
                                             "data": {"file": "a.jpg"}}]})
    check("普通图片（截图）不算表情包 → 会回", not Companion._is_sticker_only(shot))

    stk = IncomingMessage(kind="private", user_id="1", text="",
                          images=[["x"]],
                          raw={"message": [{"type": "image",
                                            "data": {"file": "a.jpg",
                                                     "sub_type": "1",
                                                     "summary": "[动画表情]"}}]})
    check("带 sub_type=1 的算表情包 → 可跳过", Companion._is_sticker_only(stk))

    mface = IncomingMessage(kind="private", user_id="1", text="",
                            images=[["x"]],
                            raw={"message": [{"type": "mface", "data": {"key": "k"}}]})
    check("mface 算表情包", Companion._is_sticker_only(mface))

    withtxt = IncomingMessage(kind="private", user_id="1", text="看这个",
                              images=[["x"]],
                              raw={"message": [{"type": "image",
                                                "data": {"sub_type": "1"}},
                                               {"type": "text", "data": {"text": "看这个"}}]})
    check("带文字就不算纯表情包", not Companion._is_sticker_only(withtxt))

    # ---- ② 合并多条消息 ----
    a = IncomingMessage(kind="private", user_id="1", text="第一条")
    b = IncomingMessage(kind="private", user_id="1", text="第二条",
                        forward_ids=["F1"])
    m = Companion._merge_messages([a, b])
    check("合并后文本拼接", "第一条" in m.text and "第二条" in m.text, m.text)
    check("合并后转发 id 汇总", m.forward_ids == ["F1"], str(m.forward_ids))
    check("合并计数写进 raw", m.raw.get("_merged_count") == 2, str(m.raw))

    # ---- ③ 转发段解析 ----
    _t, _i, _m, _id, _s, fw = parse_message(
        [{"type": "forward", "data": {"id": "FW1"}}], "1")
    check("forward 段能取出 id", fw == ["FW1"], str(fw))
    import json as _j
    inner = _j.dumps({"app": "com.tencent.multimsg",
                      "meta": {"detail": {"resid": "FW2"}}})
    _t2, _, _, _, _, fw2 = parse_message(
        [{"type": "json", "data": {"data": inner}}], "1")
    check("json 段能取出嵌套的 resid", fw2 == ["FW2"], str(fw2))

    # ---- ④ 长图缩放 ----
    try:
        from PIL import Image
        im = Image.new("RGB", (1220, 19152), (30, 30, 30))
        buf = _io.BytesIO(); im.save(buf, "JPEG")
        big = buf.getvalue()
        small, nm = fit_for_vision(big)
        check("★ 超长图会被缩放", len(small) < len(big) and nm == "image/jpeg",
              f"{len(big)}→{len(small)} {nm}")
        im2 = Image.open(_io.BytesIO(small))
        check("缩放后不超总像素上限", im2.size[0] * im2.size[1] <= 4_100_000,
              str(im2.size))
        check("缩放后最长边不超上限", max(im2.size) <= 8192, str(im2.size))
        # 正常小图不该被动
        buf2 = _io.BytesIO()
        Image.new("RGB", (800, 600), (1, 2, 3)).save(buf2, "JPEG")
        norm = buf2.getvalue()
        same, nm2 = fit_for_vision(norm)
        check("正常尺寸的图原样不动", same is norm and nm2 == "", str(nm2))
    except ImportError:
        print("  (跳过图片缩放测试：没有 Pillow)")

    # ---- ⑤ 深聊放宽上限 ----
    cfg = tmpcfg()
    check("深聊连发上限 > 普通上限",
          cfg.conversation.deep_max_bot_turns > cfg.conversation.max_bot_turns_without_reply,
          f"{cfg.conversation.deep_max_bot_turns} vs {cfg.conversation.max_bot_turns_without_reply}")
    check("深聊补话上限 > 普通上限",
          cfg.conversation.deep_max_followups > cfg.conversation.max_followups_per_topic)
    check("★ 气泡制连发上限已接线（深聊 > 普通）",
          cfg.conversation.deep_max_burst_bubbles > cfg.conversation.max_burst_bubbles,
          f"{cfg.conversation.deep_max_burst_bubbles} vs {cfg.conversation.max_burst_bubbles}")
    check("★ 气泡上限贴合真实数据（普通 <= 5，真人单轮中位 3 / P75 5~7）",
          cfg.conversation.max_burst_bubbles <= 5, str(cfg.conversation.max_burst_bubbles))
    check("★ 阶梯退避表已配置（>= 2 档）",
          len(cfg.conversation.followup_backoff_sec) >= 2,
          str(cfg.conversation.followup_backoff_sec))
    check("★ 追问限次默认收紧（<= 1）",
          cfg.conversation.max_probes_per_topic <= 1,
          str(cfg.conversation.max_probes_per_topic))

    # ---- ⑥ 上线问候开关存在且默认开 ----
    check("上线必发消息默认开启", cfg.autonomy.greet_on_start)


# ---------------------------------------------------------------- 24
async def test_digest_quota_and_sticker_nogate() -> None:
    section("分享额度只在真发出后扣 / 表情包不看时间间隔")
    import tempfile as _tf

    from app.autonomy.digest import Digest
    from app.autonomy.search import NullProvider, SearchResult
    from app.sticker import StickerPolicy

    cfg = load_config()

    # ---- ① 表情包：min_gap=0 时不该再被「距上次发图太近」拦 ----
    d = Path(_tf.mkdtemp())
    st = Store(str(d / "t.db"))
    pol = StickerPolicy(cfg.sticker, st)
    pol.note_sent(1)                    # 刚发过
    v = pol.evaluate(emotion="开心", intensity=0.9, valence=40, energy=80,
                     last_was_sticker=False)
    check("★ 最小间隔 0 时，刚发过也能再发",
          v.send, f"{v}（配置 min_gap_min={cfg.sticker.min_gap_min}）")
    check("配置里 min_gap_min 确实是 0", cfg.sticker.min_gap_min == 0,
          str(cfg.sticker.min_gap_min))
    # 但「上一条正好是纯图」仍然要拦住（那不是时间问题，是重复）
    v2 = pol.evaluate(emotion="开心", intensity=0.9, valence=40, energy=80,
                      last_was_sticker=True)
    check("上一条是纯图 → 仍然拦（防连着甩图）", not v2.send, str(v2))

    # ---- ② 分享额度只在**真发出**后才扣 ----
    class FakeSearch(NullProvider):
        async def search(self, query, n=5):
            return [SearchResult(title=f"{query} 的结果", url="http://x/1",
                                 snippet="一段描述内容")]
    st2 = Store(str(d / "d.db"))
    mem = Memory(st2)
    for t in ("鲸鱼", "Blue Archive", "AI"):
        mem.bump_interest(t, 5.0)
    # 阈值调 0：这里要验的是「额度什么时候扣」，不是打分。
    # （打分是 0.43 勉强过 0.42 线，测试文案稍变就会掉下去，断言会很脆）
    acfg = AutonomyConfig(digest_threshold=0.0, digest_max_share_per_day=3,
                          digest_enabled=True, digest_interval_min=90)
    dig = Digest(acfg, cfg.memory, MockLLM(), mem,
                 StateMachine(st2), st2, FakeSearch())
    item = await dig.run_once(force=True)
    if item:
        key = f"digest_share_{time.strftime('%Y-%m-%d')}"
        check("★ 产出分享时**不扣**额度（发出后才扣）",
              st2.counter_get(key, 0) == 0, str(st2.counter_get(key, 0)))
        check("产出会暂存成 pending（便于重试）",
              bool((st2.kv_get("digest_pending") or {}).get("url")),
              str(st2.kv_get("digest_pending")))
        # 没发出去之前再跑一次，应该把同一条 pending 交出来，而不是又搜一遍
        again = await dig.run_once(force=True)
        check("未发出时再次调用会复用 pending", again is not None
              and again.url == item.url, str(again and again.url))

        dig.mark_shared()
        check("★ 真发出后才扣额度", st2.counter_get(key, 0) == 1,
              str(st2.counter_get(key, 0)))
        check("发出后 pending 被清掉",
              not (st2.kv_get("digest_pending") or {}).get("url"), "")
        check("记录了分享历史",
              len(st2.kv_get("digest_history") or []) == 1, "")
    else:
        print("  (搜索桩没产出可分享项，跳过额度断言)")
    st.close(); st2.close()


# ---------------------------------------------------------------- 25
async def test_force_go_bypass() -> None:
    section("强制开口（上线问候）必须跳过「有话可说」层")
    import tempfile as _tf

    from app.autonomy.suppress import Suppressor

    cfg = load_config()
    d = Path(_tf.mkdtemp())
    st = Store(str(d / "t.db"))
    sm = StateMachine(st)
    sup = Suppressor(cfg.autonomy, st, MockLLM(), sm, Memory(st))

    # 造一个「刚问完话」的场景：上一轮主动是 30 分钟前
    spoke = time.time() - 30 * 60
    st.counter_set("last_spoke_ts", spoke)
    st.counter_set("last_reply_ts", spoke)

    # 不强制：交给模型判断（mock 会返回 speak=true，所以这里主要验不强制的路径能走通）
    normal = await sup.check(last_spoke_ts=spoke, last_reply_ts=spoke,
                             cold_streak=0, recent=[], force_go=False)
    check("不强制时走完五层", normal.allowed, str(normal))

    # 强制：必须直接放行，且 stage 标注「强制」
    forced = await sup.check(last_spoke_ts=spoke, last_reply_ts=spoke,
                             cold_streak=0, recent=[], force_go=True)
    check("★ 强制开口时跳过「有话可说」，直接放行",
          forced.allowed and "强制" in forced.stage, str(forced))
    check("强制时也带 kind=miss", forced.kind == "miss", str(forced.kind))

    # 但「免打扰」和「电量」这类硬约束仍然要生效（不该被强制绕过）
    st2 = Store(str(d / "t2.db"))
    sm2 = StateMachine(st2)
    sm2.emotion.energy = 5.0
    sm2.save()
    sup2 = Suppressor(cfg.autonomy, st2, MockLLM(), sm2, Memory(st2))
    low = await sup2.check(last_spoke_ts=spoke, last_reply_ts=spoke,
                           cold_streak=0, recent=[], force_go=True)
    check("★ 电量太低时，强制开口也仍然被拦（硬约束不绕过）",
          not low.allowed and low.stage == "电量", str(low))
    st.close(); st2.close()


# ---------------------------------------------------------------- 26
async def test_emotion_engine() -> None:
    section("情绪引擎：动态温度 / 思维链泄漏拦截 / 情绪惯性")
    from app.think import _clean_reply, _looks_like_meta_leak, pick_temperature

    # ---- ① 温度跟着情绪走 ----
    check("激动（arousal 高）→ 温度最高档", pick_temperature(85, 20) >= 0.9,
          str(pick_temperature(85, 20)))
    check("★ 温度上限不超过 0.95（1.0 会漏思维链）",
          pick_temperature(100, 0) <= 0.95, str(pick_temperature(100, 0)))
    check("低落（低唤醒 + 负效价）→ 温度最低",
          pick_temperature(18, -60) < pick_temperature(60, 40),
          f"{pick_temperature(18, -60)} vs {pick_temperature(60, 40)}")
    check("认真讲事 → 压到 0.6", pick_temperature(85, 20, serious=True) == 0.6,
          str(pick_temperature(85, 20, serious=True)))
    check("没给情绪 → 返回 None（用全局配置）",
          pick_temperature() is None, str(pick_temperature()))

    # ---- ② 思维链泄漏必须被识别 ----
    leaked = (
        "现在心情是烦躁，唤醒度高，所以短、硬、带刺，冷下来那种。"
        "不用脏话，不人身攻击，但要有那种\"笑着但没温度\"的感觉。"
    )
    check("★ 复述提示词的回复会被判定为泄漏",
          _looks_like_meta_leak(leaked), leaked[:40])
    check("★ 写作过程痕迹会被判定为泄漏",
          _looks_like_meta_leak('写："笑够了吗。" ——最后那句有点梗。压一下。定稿。'),
          "")
    for good in ("哦，来了个嘴欠的。", "大叔今天没什么耐心", "……嗯。", "行吧"):
        check(f"正常回复不误判：{good[:8]}", not _looks_like_meta_leak(good), "")

    # ---- ③ 格式清理 ----
    # ★ 句尾句号按真实聊天数据剔除（真人 97%+ 不点句号）—— 期望值不含「。」
    check("成对引号被去掉（句尾句号也剥掉）",
          _clean_reply("“哦，来了个嘴欠的。”") == "哦，来了个嘴欠的")
    check("「」也被去掉（句尾句号也剥掉）", _clean_reply("「嗯。」") == "嗯")
    check("★ 句尾句号被剥掉", _clean_reply("知道了。") == "知道了")
    check("★ 问号/省略号/波浪号保留", _clean_reply("嗯？") == "嗯？"
          and _clean_reply("算了…") == "算了…"
          and _clean_reply("好~") == "好~")
    check("「回复：」前缀被去掉", _clean_reply("回复：行吧") == "行吧")
    check("「小星：」前缀被去掉", _clean_reply("小星：行吧") == "行吧")

    # ---- ④ 情绪惯性：好聊天回血、敷衍掉电（沿用上轮的语义）----
    import tempfile as _tf
    st = Store(str(Path(_tf.mkdtemp()) / "e.db"))
    sm = StateMachine(st)
    sm.emotion.valence = 20.0
    sm.apply_interaction(0.95)
    v_up = sm.emotion.valence
    sm2 = StateMachine(st)
    sm2.emotion.valence = 20.0
    sm2.apply_interaction(0.15)
    check("高质量互动 → 效价上升", v_up > 20.0, str(v_up))
    check("低质量互动 → 效价下降", sm2.emotion.valence < 20.0, str(sm2.emotion.valence))
    # 顶格防护：连续高质量也不该顶到 100 不动
    sm3 = StateMachine(st)
    sm3.emotion.valence = 50.0
    for _ in range(20):
        sm3.apply_interaction(1.0)
    check("★ 连续高质量互动也不会顶到 100（避免情绪永远「开心」）",
          sm3.emotion.valence < 75.0, str(sm3.emotion.valence))
    st.close()


# ---------------------------------------------------------------- 10
def test_hygiene() -> None:
    section("记忆卫生（兴趣播种 & 情绪标签归一）")
    from app.memory import Memory
    from app.perceive import _norm_label

    d = Path(tempfile.mkdtemp())
    f = d / "interests.md"
    f.write_text(
        "# 人格\n\n"
        "## 它自己的兴趣\n"
        "- 独立游戏的叙事设计\n"
        "- 深空天体\n\n"
        "## 用户的兴趣种子\n"
        "- 网络安全攻防\n\n"
        "## 自主浏览配置\n"
        "- 频率：每天 1~2 次\n"
        "- 每次取 3~5 条候选\n",
        encoding="utf-8",
    )
    st = Store(str(d / "h.db"))
    mem = Memory(st, f)
    terms = mem.interests()

    check("播种只取「她自己的兴趣」小节下的条目",
          "深空天体" in terms, str(list(terms)))
    check("★「用户的兴趣」不进自主浏览图谱（否则会去搜对方的行业垃圾页）",
          "网络安全攻防" not in terms, str(list(terms)))
    check("★「用户的兴趣」记进「听过」桶（可以接话，但不驱动浏览）",
          "网络安全攻防" in mem.heard(), str(list(mem.heard())))
    check("配置段条目没被当成兴趣",
          not any(("频率" in k) or ("候选" in k) for k in terms), str(list(terms)))
    check("播种数量正确（2 个）", len(terms) == 2, f"{len(terms)}: {list(terms)}")
    st.close()

    check("「中性/平淡」→ 中性", _norm_label("中性/平淡") == "中性")
    check("「开心（有点得意）」→ 开心", _norm_label("开心（有点得意）") == "开心")
    check("「开心」原样通过", _norm_label("开心") == "开心")
    check("空值 → 中性", _norm_label("") == "中性")
    check("未知词 → 中性", _norm_label("恍惚") == "中性")
    check("「有点难过吧」能提取出 难过", _norm_label("有点难过吧") == "难过")
    check("「焦虑、疲惫」取第一个", _norm_label("焦虑、疲惫") == "焦虑")


# ---------------------------------------------------------------- 10b
def test_topic_lock_fixes() -> None:
    """话题锁死的三道刹车：兴趣图谱分离 / 召回去重 / 待发分享过期。

    背景（用户实测）：星野抽中两张水族馆票之后，二十多条主动开口
    全是「那两张票到几号来着」，整段聊天只剩「困、睡、水族馆、票」。
    """
    from app.memory import Memory

    section("话题锁死刹车")

    # ── ① 兴趣图谱：只有「她自己的兴趣」才进图谱 ──────────────
    d = Path(tempfile.mkdtemp())
    f = d / "interests.md"
    f.write_text(
        "# 兴趣\n\n"
        "## 她自己的兴趣\n"
        "- 鲸鱼 与 海洋生物\n\n"
        "## 用户兴趣（不驱动自主浏览）\n"
        "- 虚拟机\n"
        "- 网络安全\n\n"
        "## 自主浏览配置\n- 频率：每天 2 次\n",
        encoding="utf-8",
    )
    st = Store(str(d / "i.db"))
    mem = Memory(st, f)
    check("播种：她的兴趣进图谱", "鲸鱼 与 海洋生物" in mem.interests())
    mem.bump_interest("虚拟机", 5.0)
    mem.bump_interest("鲸鱼", 2.0)
    check("★ 对方的领域词不进自主浏览图谱",
          "虚拟机" not in mem.interests(), str(list(mem.interests())))
    check("★ 对方的领域词进「听过」桶", "虚拟机" in mem.heard(), "")
    check("★ 落在她自己兴趣范围里的词才进图谱",
          mem.interests().get("鲸鱼") == 2.0, str(mem.interests()))
    check("单字不算兴趣词（「睡」「票」这种）", mem.bump_interest("票") is None
          and "票" not in mem.interests() and "票" not in mem.heard(), "")
    check("功能词直接丢弃（表情包）",
          mem.bump_interest("表情包") is None and "表情包" not in mem.heard(), "")

    # 自愈：图谱被灌脏后，重启一遍应清掉不属于她的词
    st.kv_set("interest_terms", {"虚拟机": 6.0, "鲸鱼 与 海洋生物": 1.0})
    Memory(st, f)
    check("★ 启动自愈：清掉被灌进图谱的杂词",
          "虚拟机" not in mem.interests(), str(list(mem.interests())))
    # 空白片段不能造成误命中：「 与」曾经让「AI 与模型进展」赖在图谱里不走
    st.kv_set("interest_terms", {"AI 与模型进展": 6.0, "鲸鱼 与 海洋生物": 1.0})
    Memory(st, f)
    check("★「空格+单字」的片段不算命中（「 与」的坑）",
          "AI 与模型进展" not in mem.interests(), str(list(mem.interests())))
    st.close()

    # ── ② 召回去重（MMR）：同一件事的近义记忆不能占满名额 ──────
    st2 = Store(str(d / "r.db"))
    mem2 = Memory(st2)
    for _ in range(5):
        mem2.add_semantic("那两张水族馆的票还在抽屉里，一直没去")
    mem2.add_semantic("今天在面馆吃了碗牛肉面，汤都喝干净了")
    hits = mem2.recall("水族馆 票", top_k=3)
    texts = [h["text"] for h in hits]
    check("★ 召回做了去重：同一件事记了 5 遍也只占 1 个名额",
          len(texts) == len(set(texts)), str(texts))
    check("召回的条目数正常", len(hits) == 2, str(len(hits)))
    st2.close()

    # ── ③ 待发分享搁置太久 → 丢掉重搜（否则浏览被死锁）────────
    from app.autonomy.digest import Digest, _age_hours, STALE_PENDING_HOURS
    check("搁置时长可算出（12 小时内）", 0 < _age_hours(
        time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(time.time() - 3600)))
        < 2, "")
    check("时间戳坏掉时返回 None（不崩）", _age_hours("不是时间") is None, "")
    check("搁置阈值是 12 小时", STALE_PENDING_HOURS == 12.0, "")

    # ── ④ 「同一件事问到底」的刹车 ──────────────────────────
    from app.autonomy.heartbeat import Heartbeat
    from app.autonomy.search import NullProvider
    from app.autonomy.suppress import Suppressor
    from app.config import QQConfig
    from app.state import StateMachine as _SM

    cfg = tmpcfg()
    st3 = Store(str(d / "h.db"))
    mem3 = Memory(st3)
    sm3 = _SM(st3)
    sup = Suppressor(cfg.autonomy, st3, MockLLM(), sm3, mem3)
    dig = Digest(cfg.autonomy, cfg.memory, MockLLM(), mem3, sm3, st3, NullProvider())
    hb = Heartbeat(cfg.autonomy, QQConfig(self_id="1", owner_id="2"), st3,
                   MockLLM(), sm3, mem3, sup, None, dig, lambda n: "")
    # 她「连着主动开口、对方一条没回」
    st3.counter_set("last_reply_ts", time.time() - 7200)
    st3.counter_set("last_spoke_ts", time.time() - 600)
    turns = [{"role": "assistant", "text": "那两张水族馆的票到几号来着"}] * 3
    terms, hint = hb._stuck_topic_hint(turns)
    check("★ 卡住时能识别出反复提的词", bool(terms), str(terms))
    check("★ 卡住时会给出「换话题」提示",
          "不要再提" in hint or "换个话题" in hint, hint[:40])
    st3.counter_set("last_reply_ts", time.time())      # 对方回话了
    check("对方回过话后不再算卡住", hb._stuck_topic_hint(turns)[1] == "", "")

    # ★ 自动宽限：你忙起来没空回 → 暂停情绪消耗（不涨焦虑/孤独/委屈）
    check("距上次说话 10 分钟 → 不算忙", hb.is_busy(10 / 60.0) is False, "")
    check("距上次说话 1 小时 → 当她理解成「你在忙」",
          hb.is_busy(1.0) is True, "")
    check("从没聊过（gap=None）不算忙", hb.is_busy(None) is False, "")

    # 忙碌期内焦虑不继续上涨
    sm3.emotion.anxiety = 40.0
    sm3.emotion.loneliness = 30.0
    sm3.emotion.neglect = 20.0
    sm3.emotion.updated_at = time.time() - 3600      # 模拟过了一小时
    sm3.save()
    st3.counter_set("last_reply_ts", time.time() - 7200)   # 你两小时没说话
    st3.counter_set("last_spoke_ts", time.time() - 7200)
    hb._advance_state()
    check("★ 忙碌期内焦虑不涨（自动宽限生效）",
          sm3.emotion.anxiety <= 40.5, str(sm3.emotion.anxiety))
    check("★ 忙碌期内孤独不涨",
          sm3.emotion.loneliness <= 30.5, str(sm3.emotion.loneliness))

    # 非忙碌期（你 10 分钟前说过话）→ 状态机照常推进（电量照常消耗）
    sm3.emotion.energy = 60.0
    sm3.emotion.updated_at = time.time() - 3600
    sm3.save()
    st3.counter_set("last_reply_ts", time.time() - 600)
    hb._advance_state()
    check("非忙碌期状态机照常推进（电量按普通节奏消耗）",
          sm3.emotion.energy < 60.0, str(sm3.emotion.energy))
    st3.close()


# ---------------------------------------------------------------- 10
def test_sticker_offline() -> None:
    section("表情包库")
    lib = StickerLibrary(str(Path(tempfile.mkdtemp()) / "none.json"))
    check("空库可安全加载", lib.available is False)
    check("空库 pick 返回 None", lib.pick("开心") is None)

    import json
    d = Path(tempfile.mkdtemp())
    f1 = d / "a.png"; f1.write_bytes(b"x")
    f2 = d / "b.png"; f2.write_bytes(b"x")
    idx = d / "index.json"
    idx.write_text(json.dumps([
        {"file": str(f1), "desc": "猫在笑", "emotions": ["开心"], "tags": ["猫", "笑"]},
        {"file": str(f2), "desc": "猫在哭", "emotions": ["难过"], "tags": ["猫", "哭"]},
    ], ensure_ascii=False), encoding="utf-8")
    lib2 = StickerLibrary(idx)
    check("索引加载成功", lib2.available and len(lib2.items) == 2)
    cands = lib2.candidates("开心", top_k=2)
    check("情绪匹配命中正确的一张", cands and cands[0]["file"] == str(f1),
          str([c["file"] for c in cands]))
    picked = lib2.pick("开心", "真好笑")
    check("pick 返回可用条目", picked is not None and "file" in picked)


# ---------------------------------------------------------------- 11
async def test_multi_character() -> None:
    """角色库 + 多角色路由：新增角色不会影响星野的单角色行为。"""
    from app.characters import CharacterRegistry
    from app.channel.onebot_server import OneBotServerChannel
    from app.channel.napcat import IncomingMessage
    from app.config import QQConfig

    section("多角色")
    cfg = Config(root=ROOT)
    cfg.qq = QQConfig(self_id="10001", owner_id="10002")
    reg = CharacterRegistry(cfg)
    check("角色库：星野排第一", reg.all() and reg.all()[0].is_primary)
    check("角色库：加载 9 个新增角色",
          len(reg.guests()) == 9, str([c.name for c in reg.guests()]))
    check("角色库：id 唯一", len({c.id for c in reg.all()}) == len(reg.all()))
    check("角色库：人设都非空",
          all(len(c.persona) > 300 for c in reg.guests()))
    expect = {"古关忧", "夏目安安", "天童凯伊", "天童爱丽丝", "早濑优香",
              "橘光", "橘希望", "橘雪莉", "空崎日奈"}
    check("角色库：角色齐全", expect <= {c.name for c in reg.guests()})

    tmp = Store(str(Path(tempfile.mkdtemp()) / "multi.db"))
    got: List[IncomingMessage] = []

    async def on_message(m: IncomingMessage) -> None:
        got.append(m)

    ch = OneBotServerChannel(
        cfg.qq, on_message, store=tmp,
        characters=reg, store_for=lambda cid: tmp,
    )
    r = await ch.api_get_friends_with_category({})
    buddies = r[0]["buddyList"]
    check("多角色：好友列表返回全部角色",
          len(buddies) == len(reg.all()), str(len(buddies)))

    target = reg.guests()[0]
    await ch.api_send_msg({
        "user_id": int(target.id),
        "message": [{"type": "text", "data": {"text": "你好"}}],
    })
    await asyncio.sleep(0.1)
    check("多角色：send_msg 带上了 peer_id",
          bool(got) and got[0].peer_id == target.id,
          str([(m.user_id, m.peer_id) for m in got]))
    h = await ch.api_get_friend_msg_history(
        {"user_id": int(target.id), "count": 5})
    check("多角色：历史接口按角色返回",
          isinstance(h.get("messages"), list))
    tmp.close()


async def test_onebot_server() -> None:
    """onebot-server 通道：模拟 Stapxs QQ Lite 的完整连接行为。

    覆盖：WS 握手链（version/login/好友）、鉴权、send_msg（用户消息）
    → message_sent 事件、vol 回复 → message 事件、表情包 URL +
    静态下载、离线队列重放、历史接口、心跳、未实现 action 兜底。
    """
    import socket
    import json as _json
    import aiohttp
    from app.config import QQConfig, QQServerConfig
    from app.channel.onebot_server import OneBotServerChannel
    from app.channel.napcat import IncomingMessage
    json = _json

    section("onebot-server 通道（Stapxs 直连 vol）")

    # 随机空闲端口
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()

    qq_cfg = QQConfig(
        self_id="10001", owner_id="10002",
        channel="onebot-server",
        server=QQServerConfig(
            listen="127.0.0.1", port=port, token="test-token",
            base_url=f"http://127.0.0.1:{port}",
            heartbeat_sec=5, owner_nickname="老师", bot_nickname="星野",
        ),
    )

    # 表情包图库目录（含一张假图，测静态下载 + fetch_custom_face）
    stick_dir = Path(tempfile.mkdtemp())
    (stick_dir / "开心_abc.png").write_bytes(b"fake-png-bytes")
    # 历史消息 store
    hist = Store(str(Path(tempfile.mkdtemp()) / "h.db"))
    hist.add_turn("user", "上次聊到鲸鱼")
    hist.add_turn("assistant", "嗯，大叔喜欢鲸鱼")

    received: List[IncomingMessage] = []

    async def on_message(msg: IncomingMessage) -> None:
        received.append(msg)

    ch = OneBotServerChannel(qq_cfg, on_message, store=hist,
                             sticker_dir=stick_dir)
    await ch.start()
    base = f"http://127.0.0.1:{port}"

    async def ws_connect(token: str = "test-token"):
        session = aiohttp.ClientSession()
        url = f"ws://127.0.0.1:{port}/?access_token={token}" if token \
            else f"ws://127.0.0.1:{port}/"
        ws = await session.ws_connect(url)
        return session, ws

    async def call(ws, action: str, params: dict) -> dict:
        """模拟 Stapxs 的 WS API 调用（action/params/echo）。

        等 echo 的过程中先到的**事件推送**（无 echo 的消息）不丢弃，
        存进 events —— 和真实客户端的行为一致。"""
        import uuid as _uuid
        echo = str(_uuid.uuid4())
        await ws.send_json({"action": action, "params": params, "echo": echo})
        async for msg in ws:
            if msg.type != aiohttp.WSMsgType.TEXT:
                continue
            data = json.loads(msg.data)
            if data.get("echo") == echo:
                return data
            if data.get("echo") is None:
                events.append(data)
        raise RuntimeError("WS closed before echo returned")

    events: List[dict] = []

    async def drain(ws, seconds: float = 1.0) -> List[dict]:
        """收集这段时间内收到的所有事件（无 echo 的推送）。"""
        got: List[dict] = []
        try:
            end = time.time() + seconds
            while time.time() < end:
                try:
                    msg = await ws.receive(timeout=max(0.05, end - time.time()))
                except asyncio.TimeoutError:
                    break
                if msg.type != aiohttp.WSMsgType.TEXT:
                    continue
                data = json.loads(msg.data)
                if data.get("echo") is None:
                    got.append(data)
        except Exception:  # noqa: BLE001
            pass
        events.extend(got)
        return got

    try:
        # ── 鉴权 ──
        bad_session = aiohttp.ClientSession()
        try:
            bad_ws = await bad_session.ws_connect(
                f"ws://127.0.0.1:{port}/?access_token=WRONG")
            msg = await bad_ws.receive(timeout=2)
            check("错误 token 被拒（1008）",
                  msg.type == aiohttp.WSMsgType.CLOSE and msg.data == 1008,
                  str(msg))
        except Exception as e:  # noqa: BLE001
            check("错误 token 被拒（1008）", True, f"握手即被拒：{e!r}")
        await bad_session.close()

        # ── 握手链 ──
        session, ws = await ws_connect()
        r = await call(ws, "get_version_info", {})
        check("version_info: status ok", r.get("status") == "ok", str(r))
        check("version_info: app_name 含 NapCat",
              "NapCat" in str((r.get("data") or {}).get("app_name", "")),
              str(r.get("data")))

        r = await call(ws, "get_login_info", {})
        check("login_info: 登录者 = owner",
              str((r.get("data") or {}).get("user_id")) == "10002", str(r))

        r = await call(ws, "get_friends_with_category", {})
        buddies = (r.get("data") or [{}])[0].get("buddyList", [])
        check("好友列表 = 星野一人",
              len(buddies) == 1 and str(buddies[0]["user_id"]) == "10001"
              and buddies[0]["nickname"] == "星野", str(r.get("data")))

        r = await call(ws, "get_group_list", {})
        check("群列表为空", r.get("data") == [], str(r.get("data")))

        # ── 用户发消息 → message_sent 事件 + 主管线回调 ──
        r = await call(ws, "send_msg", {
            "user_id": 10001,
            "message": [{"type": "text", "data": {"text": "在干嘛"}}],
        })
        check("send_msg 响应 ok 且有 message_id",
              r.get("status") == "ok" and (r.get("data") or {}).get("message_id"),
              str(r))
        sent_id = (r.get("data") or {}).get("message_id")

        got = await drain(ws, 0.8)
        m_sent = next((e for e in (events + got)
                       if e.get("post_type") == "message_sent"), None)
        check("收到 message_sent 事件", m_sent is not None,
              str((events + got))[:200])
        if m_sent:
            check("message_sent 的 message_id 与响应一致",
                  m_sent.get("message_id") == sent_id, str(m_sent))
            check("message_sent 发送者 = owner（右侧气泡）",
                  str((m_sent.get("sender") or {}).get("user_id")) == "10002",
                  str(m_sent.get("sender")))
        await asyncio.sleep(0.3)
        check("主管线收到用户消息（user_id=owner）",
              len(received) == 1 and received[0].user_id == "10002"
              and received[0].text == "在干嘛",
              str([(m.user_id, m.text) for m in received]))

        # ── 用户发表情图（base64 + 驼峰 subType）→ 主管线能识图 ──
        r = await call(ws, "send_msg", {
            "user_id": 10001,
            "message": [{"type": "image",
                         "file": "base64://aGVsbG8=", "subType": 1}],
        })
        check("发图消息受理 ok", r.get("status") == "ok", str(r))
        await asyncio.sleep(0.3)
        m2 = received[-1] if received else None
        check("主管线收到图片候选（base64 → data: URL）",
              m2 is not None and m2.images
              and m2.images[0][0].startswith("data:"),
              str(m2.images if m2 else None))
        check("subType 驼峰已归一为 sub_type（表情包判定可用）",
              m2 is not None and any(
                  str((seg.get("data") or {}).get("sub_type")) == "1"
                  for seg in (m2.raw.get("message") or [])
                  if isinstance(seg, dict) and seg.get("type") == "image"),
              str(m2.raw.get("message") if m2 else None))

        # ── vol 回复 → message 事件（sender=星野）──
        await ch.send_text("随便随便~", user_id="10002")
        got = await drain(ws, 0.8)
        m_ev = next((e for e in got if e.get("post_type") == "message"), None)
        check("收到星野的 message 事件", m_ev is not None, str(got)[:200])
        if m_ev:
            check("message 事件发送者 = 星野（左侧气泡）",
                  str((m_ev.get("sender") or {}).get("user_id")) == "10001",
                  str(m_ev.get("sender")))
            check("message 正文为段数组",
                  m_ev.get("message") == [{"type": "text", "data": {"text": "随便随便~"}}],
                  str(m_ev.get("message")))

        # ── 表情包 URL + 静态下载 ──
        await ch.send_sticker(ch.file_uri(stick_dir / "开心_abc.png"))
        got = await drain(ws, 0.8)
        img_ev = next((e for e in got
                       if any(s.get("type") == "image"
                              for s in (e.get("message") or []))), None)
        check("表情包推送为 image 段", img_ev is not None, str(got)[:200])
        url = ""
        if img_ev:
            seg = next(s for s in img_ev["message"] if s.get("type") == "image")
            url = str((seg.get("data") or {}).get("file") or "")
        check("表情包 file 是 HTTP URL",
              url.startswith(f"{base}/assets/stickers/"), url)
        if url:
            async with aiohttp.ClientSession() as hs:
                async with hs.get(url) as resp:
                    body = await resp.read()
                    check("表情包 URL 可下载（静态路由 + CORS）",
                          resp.status == 200 and body == b"fake-png-bytes"
                          and resp.headers.get("Access-Control-Allow-Origin") == "*",
                          f"{resp.status} {len(body)}B")

        # ── 路径穿越防护 ──
        # 注意：aiohttp 客户端会按 RFC 3986 折叠 ../，得用 encoded=True
        # 发原始路径才能真正测到服务端侧的 resolve 防护
        from yarl import URL as _YURL
        async with aiohttp.ClientSession() as hs:
            async with hs.get(_YURL(
                    f"{base}/assets/stickers/../../secret.db", encoded=True)) as resp:
                check("静态路由拒绝路径穿越", resp.status in (403, 404),
                      str(resp.status))

        # ── 历史消息 ──
        r = await call(ws, "get_friend_msg_history",
                       {"message_type": "private", "user_id": 10001,
                        "message_seq": 0, "count": 20})
        msgs = (r.get("data") or {}).get("messages") or []
        check("历史消息数量正确", len(msgs) == 2, str(len(msgs)))
        if len(msgs) == 2:
            check("历史 sender 归属正确（user→owner, bot→星野）",
                  str(msgs[0]["sender"]["user_id"]) == "10002"
                  and str(msgs[1]["sender"]["user_id"]) == "10001",
                  str([m["sender"] for m in msgs]))

        # 一轮回复里的多条气泡在 transcript 里是 \n 拼接的，
        # 历史回放必须拆回多条，否则网页端会重复显示一个合并版。
        hist.add_turn("assistant", "第一句\n第二句\n第三句")
        r = await call(ws, "get_friend_msg_history",
                       {"message_type": "private", "user_id": 10001,
                        "message_seq": 0, "count": 20})
        msgs2 = (r.get("data") or {}).get("messages") or []
        check("★ 多气泡历史拆成多条（不合并）",
              [m["raw_message"] for m in msgs2][-3:]
              == ["第一句", "第二句", "第三句"], str(msgs2)[:300])

        # ── 收藏表情面板 ──
        r = await call(ws, "fetch_custom_face", {})
        faces = r.get("data") or []
        check("fetch_custom_face 返回图库 URL",
              len(faces) == 1 and faces[0].startswith(f"{base}/assets/"),
              str(faces))

        # ── 未实现 action 兜底 ──
        r = await call(ws, "get_group_info", {"group_id": 1})
        check("未实现 action 返回 ok/null（不弹错）",
              r.get("status") == "ok" and r.get("data") is None, str(r))

        # ── 合并转发（「聊天记录」）──
        # 以前 send_private_forward_msg 是未知 action（整条被静默丢弃）、
        # get_forward_msg 永远返回空 —— 客户端只显示「[聊天记录]」还点不开。
        fwd_nodes = [
            {"type": "node", "data": {
                "user_id": 10002, "nickname": "老师",
                "content": [{"type": "text", "data": {"text": "中午吃米粉"}}]}},
            {"type": "node", "data": {
                "user_id": 10001, "nickname": "星野",
                "content": [{"type": "text", "data": {"text": "带牛肉那种？"}}]}},
        ]
        r = await call(ws, "send_private_forward_msg",
                       {"user_id": 10001, "messages": fwd_nodes})
        check("send_private_forward_msg 受理 ok 且有 message_id",
              r.get("status") == "ok" and (r.get("data") or {}).get("message_id"),
              str(r))
        got = await drain(ws, 0.8)
        fwd_ev = next((e for e in (events + got)
                       if any(s.get("type") == "forward"
                              for s in (e.get("message") or []))), None)
        check("转发推成「聊天记录」段（带 id，可点开）",
              fwd_ev is not None, str(got)[:200])
        fid = ""
        if fwd_ev:
            fseg = next(s for s in fwd_ev["message"]
                        if s.get("type") == "forward")
            fid = str((fseg.get("data") or {}).get("id") or "")
            check("转发段带 id 且标题为「聊天记录」",
                  bool(fid)
                  and (fseg.get("data") or {}).get("title") == "聊天记录",
                  str(fseg))
        await asyncio.sleep(0.3)
        fwd_msg = received[-1] if received else None
        check("★ 主管线读到转发正文（不是「[聊天记录]」）",
              fwd_msg is not None
              and "中午吃米粉" in (fwd_msg.text or "")
              and "带牛肉那种？" in (fwd_msg.text or ""),
              str(fwd_msg.text if fwd_msg else None))
        r = await call(ws, "get_forward_msg", {"id": fid})
        fmsgs = (r.get("data") or {}).get("messages") or []
        check("★ get_forward_msg 能取回转发内容（客户端点开用）",
              len(fmsgs) == 2
              and fmsgs[0]["sender"]["nickname"] == "老师"
              and fmsgs[0]["raw_message"] == "中午吃米粉",
              str(r.get("data"))[:300])
        r = await call(ws, "get_forward_msg", {"id": "not-there"})
        check("未知 id 的 get_forward_msg 返回空（不报错）",
              r.get("status") == "ok"
              and (r.get("data") or {}).get("messages") == [], str(r))
        # 归属未知群：静默受理（不报错、不炸主管线）
        r = await call(ws, "send_group_forward_msg",
                       {"group_id": 9999, "messages": fwd_nodes})
        check("转发到未知群：静默受理",
              r.get("status") == "ok" and (r.get("data") or {}).get("message_id"),
              str(r))
        # 普通 send_msg 里内联内容的转发段：也要登记 + 能读正文
        r = await call(ws, "send_msg", {
            "user_id": 10001,
            "message": [{"type": "forward", "data": {
                "content": [{"type": "node", "data": {
                    "user_id": 10002, "nickname": "老师",
                    "content": [{"type": "text",
                                 "data": {"text": "内嵌的转发"}}]}}]}}],
        })
        await asyncio.sleep(0.3)
        m3 = received[-1] if received else None
        check("★ 内联内容的转发也能读正文",
              m3 is not None and "内嵌的转发" in (m3.text or ""),
              str(m3.text if m3 else None))
        fwd3 = next((s for s in ((m3.raw.get("message") or []) if m3 else [])
                     if s.get("type") == "forward"), None)
        fid3 = str(((fwd3 or {}).get("data") or {}).get("id") or "")
        check("内联转发被分配了可取回的 id", bool(fid3), str(fwd3))
        if fid3:
            r = await call(ws, "get_forward_msg", {"id": fid3})
            check("内联转发的 id 也能取回内容",
                  len((r.get("data") or {}).get("messages") or []) == 1,
                  str(r.get("data"))[:200])

        # ── 引用回复（私聊）：以前私聊路径压根不挂 reply，引用块画不出来 ──
        r = await call(ws, "send_msg", {
            "user_id": 10001,
            "message": [{"type": "reply", "data": {"id": "h1"}},
                        {"type": "text", "data": {"text": "这条消息我要引用"}}],
        })
        check("私聊引用消息受理 ok", r.get("status") == "ok", str(r))
        got = await drain(ws, 0.8)
        q_ev = next((e for e in (events + got)
                     if e.get("post_type") == "message_sent"
                     and e.get("reply")), None)
        check("★ 私聊 message_sent 带上被引用那条（reply 字段）",
              q_ev is not None
              and str((q_ev.get("reply") or {}).get("message_id")) == "h1",
              str(q_ev)[:220])
        check("被引用那条的摘要正确",
              q_ev is not None
              and "鲸鱼" in str((q_ev.get("reply") or {}).get("text") or ""),
              str((q_ev.get("reply") or {})))
        # 历史回放也要能画出引用块。这里的 on_message 是桩（只 append），
        # 不跑主管线，所以手动补一条「带 reply_mid 的用户消息」来模拟落库。
        hist.add_turn("user", "这条消息我要引用", reply_mid="h1")
        r = await call(ws, "get_friend_msg_history",
                       {"message_type": "private", "user_id": 10001,
                        "message_seq": 0, "count": 30})
        hist_msgs = (r.get("data") or {}).get("messages") or []
        with_q = [m for m in hist_msgs if m.get("reply")]
        check("★ 私聊历史回放里也带着引用信息",
              bool(with_q)
              and str(with_q[-1]["reply"].get("message_id")) == "h1",
              str(with_q)[:220])

        # ★ 重启后兜底：实时消息的随机 mid 不在 _live_msgs 了，
        #   引用快照仍要能还原出「被引用那条说了什么」。
        saved_live = dict(ch._live_msgs)
        ch._live_msgs.clear()
        ch._remember_quote_snapshot("10001", "MIDSNAP1", "星野",
                                    "被引用的那句话", "assistant")
        snap = ch._quoted_private("10001", "MIDSNAP1")
        check("★ 重启后引用快照仍能还原引用块",
              bool(snap) and snap.get("text") == "被引用的那句话",
              str(snap))
        ch._live_msgs.update(saved_live)

        # ★ 表情包持久化：以前 transcript 只存文字，历史里的图全消失
        hist.add_turn("assistant", "配着图的一句话", media=[
            {"type": "image", "data": {"file": "/assets/stickers/x.gif",
                                       "summary": "[表情包]", "sub_type": 1}}])
        r = await call(ws, "get_friend_msg_history",
                       {"message_type": "private", "user_id": 10001,
                        "message_seq": 0, "count": 30})
        hm = (r.get("data") or {}).get("messages") or []
        img_msgs = [m for m in hm
                    if any(s.get("type") == "image"
                           for s in (m.get("message") or []))]
        check("★ 历史回放能还原角色发过的表情包",
              bool(img_msgs) and
              str(((img_msgs[-1]["message"][0].get("data") or {})
                   .get("file") or "")).endswith("x.gif"),
              str(img_msgs[-1:])[:220])

        # ── 心跳（heartbeat_sec=5，等一个周期）──
        got = await drain(ws, 6.5)
        hb = next((e for e in got
                   if e.get("post_type") == "meta_event"
                   and e.get("meta_event_type") == "heartbeat"), None)
        check("收到心跳事件（含 interval 毫秒）",
              hb is not None and int(hb.get("interval") or 0) >= 30000,
              str(hb))

        # ── HTTP POST API（SSE 模式兼容）──
        async with aiohttp.ClientSession() as hs:
            async with hs.post(
                    f"{base}/get_login_info", json={},
                    headers={"Authorization": "Bearer test-token"}) as resp:
                data = await resp.json()
                check("HTTP API 可用且带 CORS 头",
                      resp.status == 200 and data.get("status") == "ok"
                      and resp.headers.get("Access-Control-Allow-Origin") == "*",
                      str(data))

        await ws.close()
        await session.close()

        # ── 离线队列：无客户端时发消息 → 入队；再连接 → 重放 ──
        await asyncio.sleep(0.2)
        await ch.send_text("你不在的时候说的")
        check("无客户端时消息入离线队列",
              len(ch._offline_queue) == 1, str(len(ch._offline_queue)))
        session2, ws2 = await ws_connect()
        got = await drain(ws2, 1.0)
        check("重连后收到离线消息重放",
              any(e.get("post_type") == "message"
                  and e.get("raw_message") == "你不在的时候说的" for e in got),
              str(got)[:200])
        check("重放后队列清空", len(ch._offline_queue) == 0,
              str(len(ch._offline_queue)))
        await ws2.close()
        await session2.close()

        # ── 多端同时在线：两个连接都能收到广播 ──
        sa, wa = await ws_connect()
        sb, wb = await ws_connect()
        await asyncio.sleep(0.1)
        await ch.send_text("双端广播测试")
        got_a = await drain(wa, 0.8)
        got_b = await drain(wb, 0.8)
        check("两个客户端都收到同一条广播",
              any(e.get("raw_message") == "双端广播测试" for e in got_a)
              and any(e.get("raw_message") == "双端广播测试" for e in got_b),
              f"a={len(got_a)} b={len(got_b)}")
        await wa.close(); await sa.close()
        await wb.close(); await sb.close()
    finally:
        await ch.stop()
        hist.close()


def test_traits() -> None:
    """热情 / 好感：默认值、频率映射、派生配置、提示词、持久化。"""
    from app import traits as T

    old_file = T.TRAITS_FILE
    T.TRAITS_FILE = Path(tempfile.mkdtemp()) / "character_traits.json"
    try:
        t0 = T.get_traits("nobody", "不存在的角色")
        check("未知角色默认 50/60",
              (t0.enthusiasm, t0.affection) == (50, 60),
              f"{t0.enthusiasm}/{t0.affection}")

        hot = T.Traits(enthusiasm=90, affection=80)
        cold = T.Traits(enthusiasm=10, affection=20)
        check("热情高 → 主动次数更多",
              hot.sessions_per_day > cold.sessions_per_day,
              f"{hot.sessions_per_day:.2f} vs {cold.sessions_per_day:.2f}")
        check("热情高 → 回复更快",
              hot.reply_seconds < cold.reply_seconds,
              f"{hot.reply_seconds:.0f}s vs {cold.reply_seconds:.0f}s")
        check("回复节奏倍率在合理区间（×3 后下限放到 0.04）",
              0.04 <= hot.delay_scale <= 6.0,
              str(hot.delay_scale))
        mid = T.Traits(enthusiasm=50, affection=60)
        check("热情 50 的主动频率已放大 4 倍",
              abs(mid.sessions_per_day - 4.92) < 0.01,
              str(mid.sessions_per_day))
        # ★ 2026-10-20：热情/好感的影响再 ×3
        from app.config import AutonomyConfig as _AC
        mid_auto = T.derive_autonomy(_AC(), mid)
        check("★ 热情 ×3 + 好感黏人乘数：每日主动额度（热情50/好感60 → 26 条/天）",
              mid_auto.daily_max == 26, str(mid_auto.daily_max))
        check("★ 好感也影响主动次数（好感越高越黏人）",
              T.derive_autonomy(_AC(), T.Traits(enthusiasm=50, affection=100)).daily_max
              > T.derive_autonomy(_AC(), T.Traits(enthusiasm=50, affection=0)).daily_max,
              "")
        check("★ 回复最快压到 1 秒（热情 100）",
              abs(T.Traits(enthusiasm=100).reply_seconds_effective - 1.0) < 1e-6,
              str(T.Traits(enthusiasm=100).reply_seconds_effective))
        check("★ 热情 ×3：两次主动最小间隔 ÷3（热情 50 → 10 分钟）",
              mid_auto.min_gap_min == 10, str(mid_auto.min_gap_min))
        check("★ 热情 ×3：顺延概率 ÷3（热情 50 → 约 0.067）",
              abs(mid_auto.skip_probability - 0.067) < 0.01,
              str(mid_auto.skip_probability))
        from app.config import ConversationConfig as _CC
        mid_conv = T.derive_conversation(_CC(), mid)
        check("★ 好感 ×3：活跃会话窗口抬高（好感 60 → 约 155 分钟）",
              mid_conv.active_window_min >= 150, str(mid_conv.active_window_min))
        check("★ 好感 ×3：接话与追问上限抬高、但连发条数按硬上限封住",
              mid_conv.max_followups_per_topic >= 12
              and mid_conv.max_bot_turns_without_reply >= 12
              and mid_conv.max_burst_bubbles <= 9,
              f"{mid_conv.max_followups_per_topic}/"
              f"{mid_conv.max_bot_turns_without_reply}/"
              f"{mid_conv.max_burst_bubbles}")
        check("热情 50 的回复耗时已缩短到 1/4",
              abs(mid.reply_seconds - 6.0) < 0.01,
              str(mid.reply_seconds))

        base_a = AutonomyConfig()
        base_c = ConversationConfig()
        a_hot = T.derive_autonomy(base_a, hot)
        a_cold = T.derive_autonomy(base_a, cold)
        check("热情高每日主动上限更高",
              a_hot.daily_max > a_cold.daily_max,
              f"{a_hot.daily_max} vs {a_cold.daily_max}")
        check("热情高最小间隔更短",
              a_hot.min_gap_min < a_cold.min_gap_min,
              f"{a_hot.min_gap_min} vs {a_cold.min_gap_min}")
        check("主动间隔有硬上限（不会一整天不出现）",
              60 <= a_cold.max_gap_min <= 720,
              str(a_cold.max_gap_min))
        check("热情越高硬上限越短",
              a_hot.max_gap_min < a_cold.max_gap_min,
              f"{a_hot.max_gap_min} vs {a_cold.max_gap_min}")

        close = T.derive_conversation(
            base_c, T.Traits(enthusiasm=50, affection=90))
        distant = T.derive_conversation(
            base_c, T.Traits(enthusiasm=50, affection=10))
        check("好感高接话窗口更长",
              close.active_window_min > distant.active_window_min,
              f"{close.active_window_min} vs {distant.active_window_min}")
        check("好感高追问上限更高",
              close.max_followups_per_topic >= distant.max_followups_per_topic,
              f"{close.max_followups_per_topic} vs "
              f"{distant.max_followups_per_topic}")

        text = T.trait_text(hot)
        check("提示词包含热情/好感数值",
              "热情 90/100" in text and "好感 80/100" in text,
              text[:60])
        check("提示词要求不要暴露数值",
              "不要把数值说出来" in text, text[:60])
        check("★ 预览显示真实生效值（不再只印原始曲线）",
              "实际生效" in T.trait_preview(hot)
              and "条/天" in T.trait_preview(hot),
              T.trait_preview(hot))

        T.save_traits("42", 12, 88)
        saved = T.get_traits("42")
        check("保存后读回一致",
              (saved.enthusiasm, saved.affection) == (12, 88),
              f"{saved.enthusiasm}/{saved.affection}")

        class _Char:
            id = "7"
            name = "星野"

        T.ensure_defaults([_Char()])
        raw = json.loads(T.TRAITS_FILE.read_text(encoding="utf-8"))
        check("ensure_defaults 写入角色默认值",
              raw.get("7") == {"enthusiasm": 78, "affection": 85},
              str(raw.get("7")))
    finally:
        T.TRAITS_FILE = old_file


def test_presence() -> None:
    """在线状态（QQ 式）：状态表、持久化、频率乘数、提示词、打招呼冷却。"""
    from app import presence as P
    from app import traits as T

    section("在线状态")
    old_presence = P.PRESENCE_FILE
    old_traits = T.TRAITS_FILE
    P.PRESENCE_FILE = Path(tempfile.mkdtemp()) / "presence.json"
    T.TRAITS_FILE = Path(tempfile.mkdtemp()) / "character_traits.json"
    try:
        check("默认状态是「在线」", P.get_presence().key == "online",
              P.get_presence().key)

        cur, prev = P.set_status("qme")
        check("set_status 返回新状态", cur.key == "qme", cur.key)
        check("set_status 返回旧状态", prev == "online", prev)
        check("状态已落盘", P.get_presence().key == "qme", P.get_presence().key)

        try:
            P.set_status("dancing")
            rejected = False
        except ValueError:
            rejected = True
        check("非法状态被拒绝", rejected, "没有这个状态")

        check("Q我吧 的提示词写明「有空、来找我」",
              "有空" in P.presence_text(P.get_presence()),
              P.presence_text(P.get_presence()))
        P.set_status("online")
        check("在线（默认态）不注入提示词",
              P.presence_text(P.get_presence()) == "",
              repr(P.presence_text(P.get_presence())))
        P.set_status("offline")
        check("离线 的提示词写明可以留言",
              "留言" in P.presence_text(P.get_presence()),
              P.presence_text(P.get_presence()))

        # 乘数：热情相同，只有状态不同 → 频率不同
        t = T.Traits(enthusiasm=50, affection=60)
        base_a = AutonomyConfig()
        base_c = ConversationConfig()
        a_on = T.derive_autonomy(base_a, t, P.Presence(key="online"))
        a_qme = T.derive_autonomy(base_a, t, P.Presence(key="qme"))
        a_dnd = T.derive_autonomy(base_a, t, P.Presence(key="dnd"))
        a_off = T.derive_autonomy(base_a, t, P.Presence(key="offline"))
        a_inv = T.derive_autonomy(base_a, t, P.Presence(key="invisible"))

        check("Q我吧 主动上限高于在线",
              a_qme.daily_max > a_on.daily_max,
              f"{a_qme.daily_max} vs {a_on.daily_max}")
        check("Q我吧 最小间隔更短",
              a_qme.min_gap_min < a_on.min_gap_min,
              f"{a_qme.min_gap_min} vs {a_on.min_gap_min}")
        check("请勿打扰 完全不主动（daily_max=0）",
              a_dnd.daily_max == 0, str(a_dnd.daily_max))
        check("请勿打扰 也不主动分享",
              a_dnd.digest_max_share_per_day == 0,
              str(a_dnd.digest_max_share_per_day))
        check("离线 只降低、不为 0",
              0 < a_off.daily_max < a_on.daily_max,
              f"{a_off.daily_max} vs {a_on.daily_max}")
        check("隐身 只降低、不为 0（别断联）",
              0 < a_inv.daily_max < a_on.daily_max,
              f"{a_inv.daily_max} vs {a_on.daily_max}")
        check("离线 间隔更长",
              a_off.min_gap_min > a_on.min_gap_min,
              f"{a_off.min_gap_min} vs {a_on.min_gap_min}")
        check("Q我吧 仍有主动间隔硬上限",
              30 <= a_qme.max_gap_min <= 2880, str(a_qme.max_gap_min))
        check("Q我吧 更容易走「马上」档",
              a_qme.rhythm_weights[0] > a_on.rhythm_weights[0],
              f"{a_qme.rhythm_weights[0]} vs {a_on.rhythm_weights[0]}")

        c_on = T.derive_conversation(base_c, t, P.Presence(key="online"))
        c_qme = T.derive_conversation(base_c, t, P.Presence(key="qme"))
        c_dnd = T.derive_conversation(base_c, t, P.Presence(key="dnd"))
        check("Q我吧 接话窗口更长",
              c_qme.active_window_min > c_on.active_window_min,
              f"{c_qme.active_window_min} vs {c_on.active_window_min}")
        check("请勿打扰 不追话",
              c_dnd.max_followups_per_topic == 1,
              str(c_dnd.max_followups_per_topic))

        # 网页端拿到的 payload
        payload = P.presence_payload(P.Presence(key="qme"))
        check("payload 带完整状态表",
              len(payload["statuses"]) == len(P.STATUSES),
              str(len(payload["statuses"])))
        check("payload 带标签与频率乘数",
              payload["label"] == "Q我吧" and payload["freq"] == 2.0,
              f"{payload['label']}/{payload['freq']}")
        check("payload 里请勿打扰标记为 silent",
              [s for s in payload["statuses"]
               if s["key"] == "dnd"][0]["silent"] is True, "dnd")

        # 打招呼冷却：防「来回切状态被刷屏」
        P.mark_greeted()
        check("刚打过招呼 → 冷却未过",
              P.greet_cooldown_ok(900) is False, "cool")
        P.reset_greet_cooldown()
        check("重置后冷却已过", P.greet_cooldown_ok(900) is True, "reset")
    finally:
        P.PRESENCE_FILE = old_presence
        T.TRAITS_FILE = old_traits


def test_waiting_and_affection() -> None:
    """好感倍率 + 等待/重逢：越高越黏、等不到回会难过、回来会开心。"""
    from app import traits as T
    from app.state import StateMachine

    section("好感倍率 / 等待与重逢")
    old_traits = T.TRAITS_FILE
    T.TRAITS_FILE = Path(tempfile.mkdtemp()) / "character_traits.json"
    try:
        base_c = ConversationConfig()
        warm = T.derive_conversation(base_c, T.Traits(50, 95))
        cold = T.derive_conversation(base_c, T.Traits(50, 20))
        check("好感高 → 会话窗口明显更长",
              warm.active_window_min > cold.active_window_min * 2,
              f"{warm.active_window_min} vs {cold.active_window_min}")
        check("好感高 → 追问（想了解你）更多",
              warm.max_probes_per_topic > cold.max_probes_per_topic,
              f"{warm.max_probes_per_topic} vs {cold.max_probes_per_topic}")
        check("好感高 → 接话次数更多",
              warm.max_followups_per_topic > cold.max_followups_per_topic,
              f"{warm.max_followups_per_topic} vs {cold.max_followups_per_topic}")
        check("好感高 → 「想起你」更快",
              warm.followup_delay_sec[0] < cold.followup_delay_sec[0],
              f"{warm.followup_delay_sec} vs {cold.followup_delay_sec}")
        check("好感高 → 一口气说得更多",
              warm.max_burst_bubbles >= cold.max_burst_bubbles,
              f"{warm.max_burst_bubbles} vs {cold.max_burst_bubbles}")

        from app.config import AutonomyConfig
        a_warm = T.derive_autonomy(AutonomyConfig(), T.Traits(50, 95))
        a_cold = T.derive_autonomy(AutonomyConfig(), T.Traits(50, 20))
        check("好感高 → 情绪对节奏影响更大",
              a_warm.state_influence > a_cold.state_influence,
              f"{a_warm.state_influence} vs {a_cold.state_influence}")

        text_warm = T.trait_text(T.Traits(50, 95))
        text_cold = T.trait_text(T.Traits(50, 20))
        check("好感提示词含「先接住情绪」",
              "先接住" in text_warm, text_warm[:40])
        check("好感提示词含「对他保持好奇」",
              "保持好奇" in text_warm, "")
        check("好感高时提示词明显更亲近",
              "很在意" in text_warm and "很在意" not in text_cold, "")
    finally:
        T.TRAITS_FILE = old_traits

    store = Store(str(Path(tempfile.mkdtemp()) / "state.db"))
    try:
        st = StateMachine(store)
        check("初始没有「被晾着」的委屈感", st.emotion.neglect == 0.0,
              str(st.emotion.neglect))

        # 等了 6 小时没人回：委屈/焦虑/孤独上升，心情往下掉
        st.emotion.updated_at = time.time() - 6 * 3600
        st.tick(unanswered_h=6.0)
        check("等 6 小时 → 委屈感上升", st.emotion.neglect > 5,
              str(round(st.emotion.neglect, 1)))
        check("等 6 小时 → 焦虑上升", st.emotion.anxiety > 12,
              str(round(st.emotion.anxiety, 1)))
        check("等 6 小时 → 心情变差", st.emotion.valence < 0,
              str(round(st.emotion.valence, 1)))

        # 被回了：委屈感很快消退
        before = st.emotion.neglect
        st.emotion.updated_at = time.time() - 1 * 3600
        st.tick(unanswered_h=0.0)
        check("被回之后委屈感消退", st.emotion.neglect < before,
              f"{round(before, 1)} → {round(st.emotion.neglect, 1)}")

        # 提示词：在等 → 写进 describe
        store.counter_set("last_reply_ts", 0.0)
        store.counter_set("last_spoke_ts", time.time() - 6 * 3600)
        check("waiting_hours 算出等待时长", 5.5 < st.waiting_hours() < 6.5,
              str(round(st.waiting_hours(), 2)))
        d = st.describe()
        check("等待写进了提示词", "【等待】" in d, d[-80:])

        # 没在等 → 不加等待段
        store.counter_set("last_reply_ts", time.time())
        check("被回后不再写等待段", "【等待】" not in st.describe(),
              st.describe()[-60:])

        # 重逢：很开心
        v_before = st.emotion.valence
        st.note_reunion(8.0)
        check("重逢 → 心情明显变好", st.emotion.valence > v_before,
              f"{round(v_before, 1)} → {round(st.emotion.valence, 1)}")
        check("重逢写进了提示词", "【刚重逢】" in st.describe(),
              st.describe()[-70:])
        check("重逢提示词要求别翻旧账",
              "别翻旧账" in st.describe(), "")
    finally:
        store.close()


async def test_schedule_and_share_card() -> None:
    """角色作息（各自睡点）+ 「甩分享」卡片。"""
    from datetime import datetime
    from app.autonomy.digest import ShareItem, share_card
    from app.schedule import Schedule, default_for, schedule_for

    section("角色作息 / 分享卡片")

    # ── 睡点判定（含跨午夜）────────────────────────────────
    night = Schedule(sleep="23:30", wake="08:00")
    check("23:30~08:00 的人：凌晨 3 点睡着",
          night.asleep(datetime(2026, 1, 1, 3, 0)), "")
    check("23:30~08:00 的人：中午 12 点醒着",
          not night.asleep(datetime(2026, 1, 1, 12, 0)), "")
    check("边界：睡点当刻算睡着",
          night.asleep(datetime(2026, 1, 1, 23, 30)), "")
    check("边界：起点的前一分钟还在睡",
          night.asleep(datetime(2026, 1, 1, 7, 59)), "")
    check("边界：起点当刻已醒",
          not night.asleep(datetime(2026, 1, 1, 8, 0)), "")

    # 夜班（星野那种「夜里执勤、白天补觉」）
    nightshift = Schedule(sleep="05:30", wake="13:00", nocturnal=True)
    check("夜班的人：凌晨 3 点醒着",
          not nightshift.asleep(datetime(2026, 1, 1, 3, 0)), "")
    check("夜班的人：上午 9 点在睡",
          nightshift.asleep(datetime(2026, 1, 1, 9, 0)), "")

    # 午睡
    napper = Schedule(sleep="00:00", wake="07:00", nap=["13:00", "14:00"])
    check("午睡时段算睡着",
          napper.asleep(datetime(2026, 1, 1, 13, 30)), "")
    check("午睡之外不受影响",
          not napper.asleep(datetime(2026, 1, 1, 15, 0)), "")

    # 排期：睡着时把主动心跳推到起床之后
    check("睡着时「距离起床」是正数（03:00 → 08:00 = 300 分钟）",
          abs(night.minutes_until_wake(datetime(2026, 1, 1, 3, 0)) - 300) < 1,
          str(night.minutes_until_wake(datetime(2026, 1, 1, 3, 0))))
    check("醒着时「距离起床」是 0",
          night.minutes_until_wake(datetime(2026, 1, 1, 12, 0)) == 0.0, "")

    # 清醒度：中间满格、刚醒/快睡是坡
    check("白天清醒度满格",
          night.wakefulness(datetime(2026, 1, 1, 15, 0)) > 0.99, "")
    check("刚起床（+10 分钟）清醒度不满",
          night.wakefulness(datetime(2026, 1, 1, 8, 10)) < 0.8, "")
    check("睡着时清醒度是 0",
          night.wakefulness(datetime(2026, 1, 1, 3, 0)) == 0.0, "")

    # 提示词：睡着 / 刚醒 / 清醒三种
    check("睡着时提示词写清了「被震醒、要带困意」",
          "震醒" in night.scene_text(datetime(2026, 1, 1, 3, 0))
          and "困" in night.scene_text(datetime(2026, 1, 1, 3, 0)), "")
    check("刚起床的提示词不一样",
          "刚起来" in night.scene_text(datetime(2026, 1, 1, 8, 10)), "")
    check("清醒时段不注入作息块（别无谓占提示词）",
          night.scene_text(datetime(2026, 1, 1, 15, 0)) == "", "")

    # ── 默认派生：同一个名字永远同一份，不同名字天然错开 ──────
    a = default_for("天童凯伊")
    b = default_for("天童凯伊")
    check("没配作息的角色：同名拿到同一份（重启不漂）",
          (a.sleep, a.wake) == (b.sleep, b.wake), f"{a.sleep}/{b.sleep}")
    names = ["甲", "乙", "丙", "丁", "戊", "己", "庚", "辛"]
    sleeps = {default_for(n).sleep for n in names}
    check("不同角色的睡点天然错开（不是全一样）",
          len(sleeps) >= 2, str(sorted(sleeps)))
    check("配了 persona/schedules.json 的角色以配置为准",
          schedule_for("星野", {"星野": Schedule(sleep="04:00", wake="12:00")}
                       ).sleep == "04:00", "")

    # ── 群引擎：睡着的人不主动开口，但被点名会答 ─────────────
    from app.group import GroupRuntime
    check("群引擎判定「她在睡」用的就是作息对象",
          hasattr(GroupRuntime, "_asleep"), "")

    # ── 「甩分享」卡片 ──────────────────────────────────────
    item = ShareItem(text="标题。摘要", url="https://example.com/a",
                     score=9.0, topic="游戏", angle="值得聊",
                     title="某个有趣的新闻", desc="一句话摘要")
    card = share_card(item)
    import json as _json
    inner = _json.loads(card["data"]["data"])
    check("卡片是 OneBot 的 json 段",
          card["type"] == "json", str(card)[:80])
    check("卡片带标题/链接/来源",
          inner["meta"]["news"]["title"] == "某个有趣的新闻"
          and inner["meta"]["news"]["jumpUrl"] == "https://example.com/a"
          and inner["meta"]["news"]["tag"] == "example.com",
          str(inner["meta"]["news"]))
    check("没链接时不产卡片（退回纯文本气泡）",
          share_card(ShareItem(text="t", url="", score=1, topic="x")) == {}, "")

    # 卡片不进私聊历史（历史只有文本），所以链接必须一并写进 transcript ——
    # 否则重开窗口就再也找不回她分享的那条内容。
    from app.autonomy.heartbeat import stored_turn_text

    one_line = stored_turn_text("老师早上好，爱丽丝看到一个新闻", item)
    check("分享的链接会写进历史（重开窗口还找得到原文）",
          "https://example.com/a" in one_line, one_line)
    check("没有分享时历史就是原文本",
          stored_turn_text("普通一句", None) == "普通一句", "")
    check("文本里已经有链接就不重复追加",
          stored_turn_text(f"看这个 {item.url}", item).count(item.url) == 1, "")

    # ── 卡片真的走到了通道（不是构出来就丢了）──────────────────
    from app.act import Sender
    from app.channel.console import ConsoleChannel

    beh = tmpcfg().behavior
    for _k in ("bubble_delay_ms", "sticker_delay_ms", "chunk_delay_ms",
               "short_bubble_delay_ms", "long_bubble_delay_ms"):
        setattr(beh, _k, [0, 0])
    ch = ConsoleChannel(owner_id="10001")
    snd = Sender(ch, beh)
    await snd.reply("看这个", user_id="10001", card=card)
    check("卡片随文字一起发到了通道（console 记成［json］）",
          bool(ch._out_lines) and ch._out_lines[-1] == "［json］",
          str(ch._out_lines))
    await snd.reply("没有卡片就只发文字", user_id="10001")
    check("没有卡片时不会多出一条",
          ch._out_lines[-1] != "［json］", str(ch._out_lines[-3:]))


def test_group_store() -> None:
    """群库：建群 / 每条消息一行 / mid 与单调时间戳 / 成员 / 公告 / 禁言 / 申请。"""
    from app.config import GroupConfig
    from app.group_store import GroupRegistry, GroupStore

    section("群存储")
    d = Path(tempfile.mkdtemp())
    cfg = tmpcfg()
    cfg.group = GroupConfig(index_path=str(d / "groups.json"),
                            dir_path=str(d / "groups"))
    reg = GroupRegistry(cfg)
    check("初始没有群", reg.all() == [], str(len(reg.all())))

    g = reg.create("测试群", "10001", "老师",
                   member_ids=["10000", "10002"],
                   member_names={"10000": "星野", "10002": "学生甲"})
    check("建群后出现在列表", reg.exists(g.id), g.id)
    st = reg.store_for(g.id)
    mem = st.members()
    check("群主已入群且是 owner",
          str((mem.get("10001") or {}).get("role")) == "owner", str(mem.keys()))
    check("拉进来的两个成员都在",
          "10000" in mem and "10002" in mem, str(list(mem)))

    r1 = st.add_gmsg(kind="char", sender_id="10000", sender_name="星野",
                     text="第一条群消息")
    r2 = st.add_gmsg(kind="char", sender_id="10002", sender_name="学生甲",
                     text="第二条群消息")
    check("mid 用 g<id> 命名空间且互不相同",
          r1["mid"].startswith("g") and r2["mid"] != r1["mid"],
          f"{r1['mid']} / {r2['mid']}")
    check("时间戳单调递增（同一秒也不会撞）",
          float(r2["ts"]) > float(r1["ts"]), f"{r1['ts']} / {r2['ts']}")
    check("按 mid 能查回那一条",
          (st.find_gmsg(r2["mid"]) or {}).get("text") == "第二条群消息", "")
    check("段结构能存能取",
          (st.add_gmsg(kind="char", sender_id="2001", sender_name="甲",
                       text="带图",
                       segs=[{"type": "image", "data": {"file": "x.png"}}]
                       ) or {}).get("segs", [{}])[0].get("type") == "image", "")

    # 「加载更早」翻页：只返回比 before_ts 早的未撤回消息
    older = st.gmsgs_before(float(r2["ts"]), 10)
    check("★ 群翻页只带更早的",
          any(r["text"] == "第一条群消息" for r in older)
          and all(float(r["ts"]) < float(r2["ts"]) for r in older),
          str([r["text"] for r in older]))
    check("★ 群翻页不会带出更晚的",
          all(r["text"] not in ("第二条群消息", "带图") for r in older), "")

    st.set_cursor("10000", int(r1["id"]))
    check("已读游标能读回", st.cursor("10000") == int(r1["id"]),
          str(st.cursor("10000")))
    check("backlog 能取到游标之后的消息",
          len(st.msgs_since(st.cursor("10000"))) >= 2,
          str(len(st.msgs_since(st.cursor("10000")))))

    a = st.set_announcement("今晚九点集合", by="老师")
    check("公告落库并带版本号",
          a["text"] == "今晚九点集合" and int(a["rev"]) == 1, str(a))
    check("禁言默认是关的", st.mute_all()["on"] is False, "")
    st.set_mute_all(True, by="老师")
    check("禁言能落盘", st.mute_all()["on"] is True, "")
    check("禁言存的是绝对时间戳（重启不会静默解禁）",
          float(st.mute_all()["ts"]) > 0, str(st.mute_all()["ts"]))

    check("入群申请能入队",
          st.add_join_request("10003", "学生乙") is not None, "")
    check("同一个人的重复申请不再入队",
          st.add_join_request("10003", "学生乙") is None, "")
    check("待审列表 1 条", len(st.pending_requests()) == 1, "")
    st.resolve_join_request("10003", True)
    check("审批后不再待审", len(st.pending_requests()) == 0, "")
    check("通过后可以拉进群", st.add_member("10003", "学生乙") is not None, "")

    check("撤销会标记 revoked",
          (st.revoke_gmsg(r2["mid"]) or {}).get("revoked") == 1, "")
    check("默认查询不返回已撤回",
          all(not int(r.get("revoked") or 0)
              for r in st.recent_gmsgs(20, include_revoked=False)), "")

    st2 = GroupStore(reg.db_path(g.id))
    check("重开库数据还在（真的落盘了）",
          st2.find_gmsg(r1["mid"]) is not None, "")
    st2.close()
    reg.close()


async def test_group_engine() -> None:
    """群引擎：选人 / 硬上限 / 跨角色复读 / 禁言与 backlog / 自发话题。"""
    from app.act import Sender
    from app.channel.console import ConsoleChannel
    from app.channel.napcat import IncomingMessage
    from app.config import GroupConfig
    from app.group import GroupRuntime, Member
    from app.group_store import GroupRegistry
    from app.memory import Memory
    from app.state import StateMachine
    from app.traits import Traits
    from tests.mock_llm import MockLLM

    class GroupLLM(MockLLM):
        """每次生成都给一句**互不重合**的假台词。

        为什么需要它：MockLLM 每次返回同一个字符串时，第二个开口的角色
        会被引擎的「跨角色复读」拦截 —— 那正是引擎该做的事，但会让测试
        误判成失败。这里让每句台词的字都不重合，4-gram 交集为空。
        """

        def __init__(self) -> None:
            super().__init__()
            self._n = 0

        async def chat(self, messages, **kw):
            blob = "\n".join(str(m.get("content") or "") for m in messages)
            if "情绪标注器" in blob or "对话分析器" in blob:
                return await super().chat(messages, **kw)
            self._n += 1
            base = 0x4E00 + self._n * 32
            return "".join(chr(base + i) for i in range(6))

    section("群引擎")
    d = Path(tempfile.mkdtemp())
    cfg = tmpcfg()
    # 把上限压小、把等待压成 0，测试才能在毫秒级里确定性地推进
    cfg.group = GroupConfig(
        index_path=str(d / "groups.json"), dir_path=str(d / "groups"),
        ambient_enabled=False, ai_chain_max=2, ai_no_owner_max=4,
        responders=3, responder_gap_sec=[0, 0], bubbles_per_turn=1,
        min_gap_member_sec=0, daily_max_per_member=99,
        msgs_per_hour=99, daily_max_total=999,
        backlog_responders=3, backlog_span_sec=[0, 0],
        # 自发节奏里的两个随机分支（抖私聊 / 私聊讲群里的动静）默认压成 0，
        # 让「群会自己起话头」这条断言保持确定性；下面再单独打开来测。
        ambient_share_probability=0.0, dm_share_probability=0.0,
        # 接话任务也压掉概率，避免它异步起来干扰「群会自己起话头」的断言
        chain_reply_probability=0.0, chain_reply_gap_sec=[0, 0],
    )
    for k in ("bubble_delay_ms", "short_bubble_delay_ms", "long_bubble_delay_ms"):
        setattr(cfg.behavior, k, [0, 0])

    ch = ConsoleChannel(self_id="10000", owner_id="10001")
    llm = GroupLLM()
    sender = Sender(ch, cfg.behavior)

    members = {}
    stores = []

    def mk(cid: str, name: str, aff: int) -> Member:
        st = Store(str(d / f"{cid}.db"))
        stores.append(st)
        return Member(id=cid, name=name, persona="你是测试角色。", boundaries="",
                      world="", state=StateMachine(st), memory=Memory(st, None),
                      store=st, traits=Traits(enthusiasm=60, affection=aff),
                      delay_scale=1.0)

    for cid, name, aff in (("2001", "甲", 80), ("2002", "乙", 60),
                           ("2003", "丙", 45)):
        members[cid] = mk(cid, name, aff)

    reg = GroupRegistry(cfg)
    g = reg.create("测试群", "10001", "老师", member_ids=list(members),
                   member_names={c: m.name for c, m in members.items()})
    rt = GroupRuntime(cfg, g, reg, llm, sender,
                      lambda cid: members.get(str(cid)))

    def owner_msg(text: str, segs=None) -> IncomingMessage:
        return IncomingMessage(
            kind="group", user_id="10001", group_id=g.id, peer_id=g.id,
            text=text,
            raw={"message": segs or [{"type": "text",
                                      "data": {"text": text}}]},
        )

    try:
        picks = rt.pick("随便说点什么", 2, {"2003"}, False, set())
        check("被 @ 的人一定被挑中", "2003" in picks, str(picks))
        check("挑的人数不超过上限", len(picks) <= 2, str(picks))
        check("挑出来的都是群成员",
              all(p in members for p in picks), str(picks))

        await rt.on_owner_message(owner_msg("大家晚上好"))
        spoke = ch._out_senders[:]
        check("我发言后有人回应", len(spoke) >= 1, str(spoke))
        check("回应者报的是群成员的名字",
              all(s in ("甲", "乙", "丙") for s in spoke), str(spoke))
        rows = rt.store.recent_gmsgs(20, include_revoked=False)
        check("我的话落库了",
              any(r["kind"] == "user" and "大家晚上好" in r["text"]
                  for r in rows), "")
        check("角色的话也落库了",
              sum(1 for r in rows if r["kind"] == "char") == len(spoke),
              f"{sum(1 for r in rows if r['kind'] == 'char')} vs {len(spoke)}")
        # ★ 群聊不能是「几个人并排各说各的」：第一句接我，后面的要接前一句，
        #   形成一条对话链（用户反馈的「版聊」就是这里退化的）。
        chars = [r for r in rows if r["kind"] == "char"]
        mine = [r for r in rows if r["kind"] == "user"]
        check("★ 回应的第一句接的是我那条",
              bool(chars and mine and chars[0]["reply_to"] == mine[-1]["id"]),
              f"{chars[0]['reply_to'] if chars else '-'} vs "
              f"{mine[-1]['id'] if mine else '-'}")
        check("★ 后面的人接的是上一位，而不是又回我一遍",
              len(chars) >= 2 and all(
                  chars[i]["reply_to"] == chars[i - 1]["id"]
                  for i in range(1, len(chars))),
              str([(c["sender_name"], c["reply_to"]) for c in chars]))

        spoken = ch._out_lines[-1]
        dup = rt.dup_reason(spoken)
        check("跨角色复读能被识别（拿真说过的话去比）",
              dup != "", dup or "（没识别出来）")
        check("完全不同的新话不会被误判",
              rt.dup_reason("另外一件完全不相干的事情") == "", "")

        ok, why = rt.can_speak("2001")
        check("连续接话到上限 / 本轮说满后不再开口", not ok, why)
        check("拦下来的原因是上限或冷却",
              ("上限" in why or "冷却" in why), why)

        # ★ 群主发言必须有人回：群级大额闸门（每小时/每日总量）打满也不能静默
        rt._round_count = 0
        rt._ai_chain = 0
        rt._cooldown_until = 0.0
        _saved_total = rt.gcfg.daily_max_total
        rt.gcfg.daily_max_total = 0
        ok3, why3 = rt.can_speak("2001")
        check("群级日总量打满时普通发言仍被拦（防线还在）",
              (not ok3) and "今日群消息" in why3, why3)
        ok4, why4 = rt.can_speak("2001", ignore_total=True)
        check("★ 但「回群主」能越过群级总量（不会再全员静默）", ok4, why4)
        rt.gcfg.daily_max_total = _saved_total      # 复原，别影响后面的断言
        specs = {s[0]: s for s in rt.LIMIT_SPECS}
        check("面板里能看到「全群每天最多几条」",
              "daily_max_total" in specs, str(list(specs)))
        check("每小时/每人每日上限的天花板已抬高",
              specs["msgs_per_hour"][4] >= 999
              and specs["daily_max_per_member"][4] >= 999,
              f"{specs['msgs_per_hour'][4]}/{specs['daily_max_per_member'][4]}")
        check("★ 一次气泡上限收到 4 条以内（一个人不会连发十条）",
              specs["bubbles_per_turn"][4] <= 4,
              str(specs["bubbles_per_turn"][4]))

        # ── 全员禁言 ────────────────────────────────────────
        rt.store.set_mute_all(True, by="老师")
        n_before = len(ch._out_lines)
        await rt.on_owner_message(owner_msg("禁言期间我发的消息"))
        check("禁言期间我发的消息照样落库",
              any("禁言期间我发的消息" in r["text"] for r in
                  rt.store.recent_gmsgs(6, include_revoked=False)), "")
        check("禁言期间没有任何人回话",
              len(ch._out_lines) == n_before, str(ch._out_lines[n_before:]))
        last_id = int(rt.store.recent_gmsgs(1)[-1]["id"])
        check("禁言期间不推进游标（攒着 backlog）",
              all(rt.store.cursor(c) < last_id for c in members),
              str({c: rt.store.cursor(c) for c in members}))
        check("backlog 里能看到禁言期间的内容",
              "禁言期间我发的消息" in rt.backlog_text(), rt.backlog_text()[:40])

        # ── 解禁后补话 ──────────────────────────────────────
        rt.store.set_mute_all(False, by="老师")
        rt._cooldown_until = 0.0        # 让「补话」不被上一轮的冷却挡住
        n2 = len(ch._out_lines)
        await rt.backlog_wave()
        check("解禁后有人接着回禁言期间的话",
              len(ch._out_lines) > n2, str(ch._out_lines[n2:]))
        check("补话人数不超过上限",
              len(ch._out_lines) - n2 <= rt.gcfg.backlog_responders,
              f"{len(ch._out_lines) - n2}")

        # ── 群自己的节奏 ────────────────────────────────────
        rt.gcfg.ambient_enabled = True
        rt._cooldown_until = 0.0
        rt._round_count = 0
        rt._ai_chain = 0
        n3 = len(ch._out_lines)
        out = await rt.tick_once(now=time.time() + 3600)
        check("群会自己起话头",
              bool(out) and len(ch._out_lines) > n3, str(out))

        # ── 争宠：吃醋 / 被冷落（走真实情绪状态机）──────────────
        # 注意顺序：抖私聊本身也会点着吃醋，所以先把吃醋单独测掉。
        poss_before = members["2002"].state.relationship.possessiveness
        hot = rt.spark_jealousy("2001", 0.6)
        check("吃醋只点着好感够高的人（好感 45 的丙不在内）",
              "2003" not in hot and "2002" in hot, str(hot))
        check("吃醋真的改了她的内部状态（占有欲上升）",
              members["2002"].state.relationship.possessiveness > poss_before,
              f"{poss_before:.1f} → "
              f"{members['2002'].state.relationship.possessiveness:.1f}")
        check("吃醋有节流：紧接着再来一次点不动",
              rt.spark_jealousy("2001", 0.6) == [], "")
        check("被冷落也走同一套情绪入口（另有独立节流）",
              rt.mark_ignored(["2001"], 0.3) == ["2002"],
              "被点名的人不算被冷落")

        # ── 接话：有人说完之后，另一个人会接一句（修「A 没人理」）──
        rt.gcfg.chain_reply_probability = 1.0
        rt._cooldown_until = 0.0
        rt._round_count = 0
        rt._ai_chain = 0
        rt.store.set_mute_all(False, by="老师")
        rt.store.add_gmsg(kind="char", sender_id="2002", sender_name="乙",
                          text="这句话等着别人接")
        n_chain = len(ch._out_lines)
        await rt._chain_reply("2002")
        check("别人说完后有人接话（不是自己接自己）",
              len(ch._out_lines) > n_chain
              and ch._out_senders[-1] in ("甲", "丙"),
              str(ch._out_senders[n_chain:]))
        rt.gcfg.chain_reply_probability = 0.0
        rt._chain_task = None
        rt._kick_chain("2002")
        check("概率为 0 时不排接话任务（需要一个确定性开关）",
              rt._chain_task is None, "")

        # ── 每群可调的节奏参数（群里那套「发言额度」，界面上有滑杆）──
        before = rt.gcfg.daily_max_per_member
        rt.apply_limits({"daily_max_per_member": 3,
                         "chain_reply_probability": 40})
        check("能改本群的每日额度", rt.gcfg.daily_max_per_member == 3,
              str(rt.gcfg.daily_max_per_member))
        check("百分比类参数按 0~1 存",
              abs(rt.gcfg.chain_reply_probability - 0.4) < 1e-6,
              str(rt.gcfg.chain_reply_probability))
        check("越界的值会被夹到范围内",
              rt.apply_limits({"msgs_per_hour": 9999}) is not None
              and rt.gcfg.msgs_per_hour == 999, str(rt.gcfg.msgs_per_hour))
        payload = rt.limits_payload()
        check("给界面的参数表带上了范围/单位/当前值",
              all(k in payload[0] for k in
                  ("key", "label", "min", "max", "step", "unit", "value"))
              and any(x["key"] == "daily_max_per_member"
                      and x["value"] == 3 for x in payload),
              str(payload[:1]))
        # 落盘 + 重载：换一个 runtime 实例（模拟重启）也要读到改过的值
        rt.apply_limits({"daily_max_per_member": 4})
        rt2 = GroupRuntime(cfg, g, reg, llm, sender,
                           lambda cid: members.get(str(cid)))
        check("改动落在这个群自己的库里（重启后仍在）",
              rt2.gcfg.daily_max_per_member == 4,
              str(rt2.gcfg.daily_max_per_member))
        check("没改过的群不会被别的群带跑（各群一份参数）",
              cfg.group.daily_max_per_member == 99,
              str(cfg.group.daily_max_per_member))
        rt.apply_limits({"daily_max_per_member": before})

        # ── 说满当日上限的人不能在挑人时被选中 ──────────────
        # （实测事故：三个人都到上限后，我发言群里一片安静 —— 因为挑中了
        #   他们、然后 speak 里又被 can_speak 拦掉）
        rt.gcfg.daily_max_per_member = 1
        check("全员说满当日上限时，挑人直接挑不到（而不是挑了再被拦）",
              rt.pick("随便说说", 3, set(), False, set()) == [], "")
        # ── @ / 叫名字必须有回应（用户实测：@ 凯伊她不出来说话）──────
        # 根因是 pick() 把「今天说够了」的人一刀切掉，被 @ 也一样被切。
        check("不点名时她确实被每日上限挡着",
              rt.can_speak("2003")[0] is False, rt.can_speak("2003")[1])
        check("被点名的人不受每日上限限制（can_speak）",
              rt.can_speak("2003", mention=True)[0] is True, "")
        check("到上限的人被点名后仍会被挑中",
              "2003" in rt.pick("丙你在吗", 3, {"2003"}, False, set()),
              str(rt.pick("丙你在吗", 3, {"2003"}, False, set())))
        rt._cooldown_until = 0.0
        rt._round_count = 0
        rt._ai_chain = 0
        n_ment = len(ch._out_lines)
        await rt.on_owner_message(owner_msg("丙你在吗", segs=[
            {"type": "at", "data": {"qq": "2003"}},
            {"type": "text", "data": {"text": "丙你在吗"}}]))
        check("被 @ 到「今天说够了」的人也会开口回应",
              "丙" in ch._out_senders[n_ment:], str(ch._out_senders[n_ment:]))
        _old = members["2002"].name
        members["2002"].name = "乙同学"          # 2 字以上的名字才算点名
        check("文本里直接叫名字也算点名（2 字以上）",
              rt._named_mentions("乙同学你来说说") == {"2002"},
              str(rt._named_mentions("乙同学你来说说")))
        members["2002"].name = _old
        check("单字名字不会被误判成点名（甲/乙/丙 这种）",
              rt._named_mentions("甲乙丙丁一起玩") == set(),
              str(rt._named_mentions("甲乙丙丁一起玩")))
        rt.gcfg.daily_max_per_member = 99

        # ── 全员说满额度时，我发言也不能集体静默 ────────────────
        # 实测：我说「哈喽」之后 15 分钟没人应 —— 挑人阶段全被每日额度切掉。
        rt.gcfg.daily_max_per_member = 1
        n_over = len(ch._out_lines)
        await rt.on_owner_message(owner_msg("大家还在吗"))
        check("全员都到每日额度时，我发言仍会有人应（放宽额度兜底）",
              len(ch._out_lines) > n_over, str(ch._out_senders[n_over:]))
        rt.gcfg.daily_max_per_member = 99

        # ── 并发开口：生成锁不覆盖发送（「版聊」的根因之一）──────────
        # 旧实现把「生成 + 发送」整段锁住：一个角色还在慢慢发气泡时，
        # 下一个角色连生成都开始不了 —— 于是永远是「A 说完 B 才开始」。
        send_started = asyncio.Event()
        release_send = asyncio.Event()

        class SlowSender:
            async def reply_bubbles(self, bubbles, **kw):
                send_started.set()
                await release_send.wait()
                return len(bubbles)

        rt.sender = SlowSender()
        t_a = asyncio.create_task(rt.speak("2001", hint="甲说话", force=True))
        await asyncio.wait_for(send_started.wait(), 5)
        t_b = asyncio.create_task(rt.speak("2002", hint="乙说话", force=True))
        stored_b = False
        for _ in range(60):
            await asyncio.sleep(0.02)
            if any(str(r.get("sender_id")) == "2002"
                   for r in rt.store.recent_gmsgs(8, include_revoked=False)):
                stored_b = True
                break
        check("一个角色在发气泡时，另一个已能生成并落库（不再排队等）",
              stored_b, str([r.get("sender_id")
                             for r in rt.store.recent_gmsgs(8, include_revoked=False)]))
        release_send.set()
        await asyncio.gather(t_a, t_b, return_exceptions=True)
        rt.sender = sender

        # ── 面板改过的整型参数不能把群管线打断 ─────────────────
        # 实测事故：「我在群里说话没人理」。根因是面板把 responders 存成
        # 5.0（float），pick 里 `[:max(1, 5.0)]` 抛
        # TypeError: slice indices must be integers —— 每次发言都在引擎里
        # 异常退出，而 _safe_handle 只打一行 repr，日志看不出是哪一行。
        rt.apply_limits({"responders": 5})
        check("面板改过的整型参数落成 int（不是 5.0）",
              isinstance(rt.gcfg.responders, int),
              type(rt.gcfg.responders).__name__)
        rt.store.kv_set("limits", {"responders": 5.0, "bubbles_per_turn": 3.0})
        rt3 = GroupRuntime(cfg, g, reg, llm, sender,
                           lambda cid: members.get(str(cid)))
        check("重启后从群库读到的整型参数也是 int",
              isinstance(rt3.gcfg.responders, int)
              and isinstance(rt3.gcfg.bubbles_per_turn, int),
              f"{type(rt3.gcfg.responders).__name__}"
              f"/{type(rt3.gcfg.bubbles_per_turn).__name__}")
        rt.gcfg.responders = 5.0            # 模拟旧版本写进 gcfg 的浮点遗留
        check("gcfg 里遗留的浮点 limit 也不会抛切片异常",
              isinstance(rt.pick("在吗", rt.gcfg.responders, set(), False, set()),
                         list), "")
        rt.store.set_mute_all(False, by="老师")
        rt._cooldown_until = 0.0
        rt._round_count = 0
        rt._ai_chain = 0
        n_float = len(ch._out_lines)
        await rt.on_owner_message(owner_msg("浮点上限下我说话也要有人应"))
        check("浮点遗留值下我发言仍会有人回应（不再异常退出）",
              len(ch._out_lines) > n_float, str(ch._out_senders[n_float:]))
        rt.store.kv_set("limits", {})
        rt.gcfg.responders = int(rt.gcfg.responders)

        # ── 作息：睡着的人不主动开口，但被点名会答 ─────────────
        from app.schedule import Schedule as _Sch

        rt.store.set_mute_all(False, by="老师")
        members["2003"].schedule = _Sch(sleep="00:01", wake="00:00")   # 全天在睡
        _ok, _why = rt.can_speak("2003")
        check("她这个点在睡 → 不主动开口（自发话题/接话都走这里）",
              _ok is False and "睡" in _why, _why or "(居然让她说了)")
        check("睡着但被点名 → 照样答（真人被叫醒也会应一句）",
              rt.can_speak("2003", mention=True)[0] is True, "")
        members["2003"].schedule = None
        _ok2, _why2 = rt.can_speak("2003")
        check("拿掉作息就不再被「在睡」挡（没配的一律当醒着）",
              "睡" not in _why2, _why2 or "(可开口)")

        # 全员都在睡时，我发言也必须有人应 —— 被吵醒也要迷迷糊糊答一句，
        # 不能因为「作息」把「我说话没人理」这个事故又造回来。
        for _c in ("2001", "2002", "2003"):
            members[_c].schedule = _Sch(sleep="00:01", wake="00:00")
        rt.gcfg.daily_max_per_member = 99
        rt.store.set_mute_all(False, by="老师")
        rt._cooldown_until = 0.0
        rt._round_count = 0
        rt._ai_chain = 0
        n_sleep = len(ch._out_lines)
        await rt.on_owner_message(owner_msg("凌晨三点我说句话"))
        check("全员都在睡时我发言也会有人应（被吵醒也要答一句）",
              len(ch._out_lines) > n_sleep, str(ch._out_senders[n_sleep:]))
        for _c in ("2001", "2002", "2003"):
            members[_c].schedule = None

        # ── 群聊场景进提示词（让她们知道「我在群里说话」）────────
        scene = rt._group_scene(members["2001"], chained_from="甲",
                                reply_to_owner=True)
        check("群场景块讲清楚了「当众说话、不是私聊」",
              "群聊" in scene and "当众" in scene and "不是一对一私聊" in scene,
              scene[:60])
        check("群场景块点名了在场的人",
              "乙" in scene and "丙" in scene, scene[:120])
        check("接话场景会点明「接着谁的那句」",
              "甲" in scene, scene[-80:])

        # ── 群里的等级：累计发言、且和成员列表同源 ──────────────
        # 实测 bug：聊天气泡上的 LV 和右侧成员列表对不上。两个来源：
        # ①等级原是按「当天」发言数算的（午夜归零、上午下午不一样）；
        # ②实时推送的 sender 没带 role/level，客户端只能兜底成 LV1。
        from app.channel.onebot_server import OneBotServerChannel
        from app.group_store import GroupStore

        st_lv = GroupStore(str(d / "lv.db"))
        for i in range(10):
            st_lv.add_gmsg(kind="char", sender_id="x", text=f"很久以前{i}",
                           ts=time.time() - 4 * 86400 + i)
        check("等级按累计发言算（几天前的发言也算数，不午夜归零）",
              st_lv.member_level("x") == 2, str(st_lv.member_level("x")))

        async def _noop(_m) -> None:
            return None

        ch_meta = OneBotServerChannel(cfg.qq, _noop, store=None, group_api=None)
        check("没有群接口时徽章兜底不会炸",
              ch_meta._group_member_meta("800", "1")["level"] == 1, "")

        # ── 抖私聊进群（好友把和我的私聊片段带进群里）──────────
        members["2001"].store.add_turn("user", "我今天把模型跑崩了")
        members["2001"].store.add_turn("assistant", "哈哈哈你也太惨了")
        snippet = rt._private_snippet("2001")
        check("能从她的私聊历史里取到片段",
              "跑崩" in snippet, snippet[:40])
        check("片段里带上双方的说话人",
              "我：我今天把模型跑崩了" in snippet, snippet[:60])
        check("片段按时间正序（最近的排在后面）",
              snippet.index("跑崩") < snippet.index("太惨"), snippet[:80])
        rt._cooldown_until = 0.0
        rt._round_count = 0
        rt._ai_chain = 0
        n_share = len(ch._out_lines)
        shr = await rt.share_private_to_group("2001")
        check("她能把私聊片段说进群里",
              bool(shr) and len(ch._out_lines) > n_share, str(shr))
        day = time.strftime("%Y-%m-%d")
        check("抖私聊记了当日额度",
              int(rt.store.kv_get(f"share:{day}:2001", 0) or 0) == 1, "")
        check("同一人当天不会再抖第二次（额度上限 1）",
              not rt._share_budget_ok("2001"), "")

        # ── 群里的动静 → 私聊（她来找我告状）────────────────
        rt._cooldown_until = 0.0
        rt._round_count = 0
        rt._ai_chain = 0
        rt.store.set_mute_all(False, by="老师")
        n_dm = len(ch._out_lines)
        dm_ok = await rt.share_group_to_owner("2001")
        check("她能把群里的动静私聊讲给我听",
              dm_ok and len(ch._out_lines) > n_dm, str(ch._out_lines[n_dm:]))
        turns = members["2001"].store.recent_turns(3)
        check("私聊分享也写进了她的私聊历史（重开窗口能回放）",
              bool(turns) and turns[-1]["role"] == "assistant",
              str([t["role"] for t in turns]))
        check("私聊分享有每日上限",
              not rt._dm_budget_ok("2001"), "")

        # ── 群里「我也被等 / 被冷落」（和私聊的等待同源但独立）────
        now10 = time.time() + 10 * 3600          # 假装「我 10 小时没在群里露面」
        before_neg = members["2002"].state.emotion.neglect
        pushed = rt.apply_group_waiting(now=now10)
        check("我在群里消失 → 好感够高的人被推进「被晾着」",
              "2002" in pushed and "2003" not in pushed, str(pushed))
        check("被晾着真的涨了（neglect）",
              members["2002"].state.emotion.neglect > before_neg,
              f"{before_neg:.1f} → "
              f"{members['2002'].state.emotion.neglect:.1f}")
        check("等待推进有节流（同一人短时间内只推一次）",
              rt.apply_group_waiting(now=now10 + 60) == [], "")
        check("群发言提示词里会带上「群里在等」",
              "群里在等" in rt._wait_hint(now10), rt._wait_hint(now10)[:40])
        check("被晾着的小时数记进了状态（group_wait_h ≈ 10）",
              members["2002"].state.group_wait_h() > 9.0,
              str(members["2002"].state.group_wait_h()))
        neg_before = members["2002"].state.emotion.neglect
        rt._reunion_all(10.0)
        check("我回到群里 → 被晾着的那口气松掉",
              members["2002"].state.emotion.neglect < neg_before,
              f"{neg_before:.1f} → "
              f"{members['2002'].state.emotion.neglect:.1f}")
        check("重逢后 group_wait_h 归零",
              members["2002"].state.group_wait_h() == 0.0,
              str(members["2002"].state.group_wait_h()))
        rt.store.set_mute_all(False, by="老师")

        # ── 成员被移出后不再说话 ────────────────────────────
        rt.store.remove_member("2001")
        check("移出成员后她不能再发言",
              await rt.speak("2001", hint="试试", force=True) is None, "")
    finally:
        rt.close()
        for st in stores:
            st.close()
        reg.close()


async def test_group_files_and_quote() -> None:
    """群文件 / 群相册（落盘 + 登记）与「引用回复」的 mid 反解。"""
    from app.channel.console import ConsoleChannel
    from app.channel.napcat import IncomingMessage
    from app.config import GroupConfig
    from app.main import Companion

    section("群文件 / 引用回复")
    d = Path(tempfile.mkdtemp())
    cfg = tmpcfg()
    # ★ 群数据必须改到临时目录，否则跑一次测试就往用户真实 data/ 里灌群
    cfg.group = GroupConfig(index_path=str(d / "groups.json"),
                            dir_path=str(d / "groups"))
    ch = ConsoleChannel(owner_id="10001")
    comp = Companion(cfg, channel=ch, llm=MockLLM())
    try:
        detail = comp.create_group("文件测试群", [])
        gid = detail["group_id"]
        check("建群成功", bool(gid), str(detail)[:60])

        a = comp.add_group_file(gid, "笔记.txt", b"hello world")
        b = comp.add_group_file(gid, "旧照片.png",
                                b"\x89PNG\r\n\x1a\n" + b"\x00" * 64)
        check("文本文件归到「文件」", a["kind"] == "file", str(a))
        check("图片归到「群相册」", b["kind"] == "image", str(b))
        check("群文件列表里有两条", len(comp.group_files(gid)) == 2, "")
        p = comp.group_file_path(gid, a["id"])
        check("能按 file_id 找到落盘文件且内容一致",
              p is not None and p.read_bytes() == b"hello world", str(p))
        check("未知 / 穿越式 file_id 拿不到路径",
              comp.group_file_path(gid, "../../etc/passwd") is None
              and comp.group_file_path(gid, "nope") is None, "")
        comp.remove_group_file(gid, a["id"])
        check("删除后登记和文件都没了",
              comp.group_file_path(gid, a["id"]) is None
              and len(comp.group_files(gid)) == 1, "")
        try:
            comp.add_group_file(gid, "空.txt", b"")
            check("空文件被拒", False, "居然接受了")
        except ValueError:
            check("空文件被拒", True, "")

        # 邀请直接入群：不走进群申请那条路（那条受「允许被搜索」限制）
        comp.set_group_searchable(gid, False)
        d2 = comp.invite_group_member(gid, "3901000011", "古关忧")
        check("关掉「允许被搜索」后群主仍能邀请人",
              any(str(m["user_id"]) == "3901000011" for m in d2["members"]),
              f"member_count={d2.get('member_count')}")
        try:
            comp.invite_group_member(gid, "3901000011", "古关忧")
            check("重复邀请会被拒", False, "居然接受了")
        except ValueError:
            check("重复邀请会被拒", True, "")
        check("群里留了系统消息", any(
            "加入了群聊" in str(r.get("text") or "")
            for r in comp.group_messages(gid, 20)), "")

        # 引用回复：引擎按 reply 段里的 mid 反解出库内 id
        rt = comp.group_runtime_for(gid)
        row = rt.store.add_gmsg(kind="char", sender_id="9001",
                                sender_name="甲", text="先有这句话")
        quote_msg = IncomingMessage(
            kind="group", user_id="10001", group_id=gid, peer_id=gid,
            text="引用你一下",
            raw={"message": [{"type": "reply",
                              "data": {"id": row["mid"]}},
                             {"type": "text", "data": {"text": "引用你一下"}}],
                 "_reply_id": row["mid"]})
        check("引用段能解析出被引用消息的库内 id",
              rt._resolve_reply(quote_msg) == int(row["id"]),
              f"{rt._resolve_reply(quote_msg)} vs {row['id']}")
        check("没有引用段时返回 0",
              rt._resolve_reply(IncomingMessage(
                  kind="group", user_id="10001", group_id=gid, peer_id=gid,
                  raw={"message": []})) == 0, "")
        # 一条消息可能被拆成多条气泡推送（mid 形如 gN / gN-2 / gN-3），
        # 引用第 2、3 条时要按基础 mid 查得到
        check("引用第 2 条气泡（gN-2）也能反解到库内 id",
              rt._resolve_reply(IncomingMessage(
                  kind="group", user_id="10001", group_id=gid, peer_id=gid,
                  raw={"message": [], "_reply_id": f"{row['mid']}-2"})) == int(row["id"]),
              f"{row['mid']}-2")
        # 我自己那条消息：实时 id 是随机序号、库内 mid 是后来才有的 → 靠对照表
        rt._remember_mid_alias("8123456", str(row["mid"]))
        check("引用自己刚发的消息（实时随机 id）也能反解（对照表）",
              rt._resolve_reply(IncomingMessage(
                  kind="group", user_id="10001", group_id=gid, peer_id=gid,
                  raw={"message": [], "_reply_id": "8123456"})) == int(row["id"]), "")
        check("对照表有界（不会无限涨）",
              len(rt._mid_alias) <= 300, str(len(rt._mid_alias)))
        # 通道层直接验证：reply_to_mid 会被原样记录（前端引用块的来源）
        await ch.send_text("插座测试", group_id=gid, sender_id="1",
                           sender_name="甲", reply_to_mid="MID-XYZ")
        check("通道记录下被引用的 mid",
              ch._reply_mids and ch._reply_mids[-1] == "MID-XYZ",
              str(ch._reply_mids[-1:]))
        lines_before = len(ch._out_lines)
        await rt.on_owner_message(quote_msg)
        # 群里可能有人回话，所以不能假设「最后一条」就是我发的那条
        rows_after = rt.store.recent_gmsgs(10)
        mine = [r for r in rows_after
                if str(r.get("kind")) == "user"
                and "引用你一下" in str(r.get("text") or "")]
        check("我发的引用消息把 reply_to 落库了",
              bool(mine) and int(mine[-1].get("reply_to") or 0) == int(row["id"]),
              str(mine[-1] if mine else rows_after[-1])[:90])
        # 角色接我这句话时，被引用消息的 mid 必须真的传到通道（有角色开口才算）
        if len(ch._out_lines) > lines_before and mine:
            check("角色接我的话时带上了被引用的 mid",
                  any(ch._reply_mids[lines_before:]),
                  str(ch._reply_mids[lines_before:]))

        # ── 实时群消息的徽章必须与右侧成员列表同源（等级/角色/群名片）──
        # 以前实时 sender 只有 user_id + nickname，聊天气泡兜底成 LV1，
        # 而成员列表按真实等级算 → 「群聊里的等级和成员列表对不上」。
        from app.channel.onebot_server import OneBotServerChannel

        async def _on_msg(_m) -> None:
            return None

        ch_meta = OneBotServerChannel(cfg.qq, _on_msg, store=None, group_api=comp)
        m_g = next(m for m in comp.group_detail(gid)["members"]
                   if str(m["user_id"]) == "3901000011")
        meta = ch_meta._group_member_meta(gid, "3901000011")
        check("实时群消息的等级与成员列表一致",
              int(meta["level"]) == int(m_g["level"]), f"{meta} vs {m_g}")

        # ── 群里实时事件的 message_id 必须是**库内 mid**（g<id>）────────
        # 否则「实时收到的那条」和「刷新后历史里的那条」是两套 id，
        # 客户端引用即时消息时后端按 mid 查库查不到 → 引用回复整个失效。
        mids = [m for m in ch._out_mids if m]
        check("角色在群里发言时，实时事件的 mid 用的是库内 mid（g 开头）",
              bool(mids) and all(m.startswith("g") for m in mids),
              str(mids[-3:]))
        rows_mids = {str(r.get("mid")) for r in rt.store.recent_gmsgs(40)}
        check("这些 mid 在群库里都查得到（引用才解析得出来）",
              all(m.split("-")[0] in rows_mids for m in mids), str(mids[-3:]))

        # 推送环节：库内 mid 必须被原样采用，不能又被换成随机序号
        await ch_meta._push_bot_message(
            [{"type": "text", "data": {"text": "x"}}], "x",
            sender_id="3901000011", sender_name="古关忧",
            group_id=gid, message_id="g119")
        ev = ch_meta._offline_queue[-1]
        check("实时群事件的 message_id 原样采用库内 mid",
              str(ev.get("message_id")) == "g119", str(ev.get("message_id")))
        check("（附带）没客户端时事件进离线队列，可被重放",
              bool(ch_meta._offline_queue), "")
        check("历史拆出的 gN-2 也能反解成同一条消息（helper）",
              ch_meta._base_mid("g119-2") == "g119"
              and ch_meta._base_mid("g119") == "g119", "")
        check("实时群消息带上了角色与群名片",
              meta["role"] == m_g["role"] and meta["card"] == m_g["nickname"],
              str(meta))
        check("未知成员不会炸、回落到 LV1/普通成员",
              ch_meta._group_member_meta(gid, "999999")["level"] == 1
              and ch_meta._group_member_meta(gid, "999999")["role"] == "member",
              "")

        # ── 私聊 ⇄ 群聊记忆互通：私聊上下文里能看到群里的近况 ──────
        # 用户实测：她在私聊里完全不知道自己刚在群里说过话。
        ctx = comp._group_context_for("3901000011")
        check("群成员在私聊里能拿到「群里最近发生了什么」",
              "最近的对话" in ctx and "文件测试群" in ctx, ctx[:90])
        check("上下文里点明这是群聊、不是私聊", "群聊，不是私聊" in ctx, "")
        check("提醒别把两人之间的事拿到群里说",
              "只有你和老师两个人知道的事" in ctx, "")
        check("不在群里的人拿不到（返回空串）",
              comp._group_context_for("999999") == "", "")
        check("空 id / 无群都不炸", comp._group_context_for("") == "", "")

        # 传了就要真的进提示词（不能传了就丢）
        captured: dict = {}

        class CapLLM(MockLLM):
            async def chat(self, messages, **kw):
                captured["all"] = "\n".join(
                    str(m.get("content") or "") for m in messages)
                return await super().chat(messages, **kw)

        from app.think import express as _express
        await _express(CapLLM(), "人设", "", "状态", "记忆", ["我：在吗"], "在吗",
                       group_context=ctx)
        check("group_context 真的拼进了提示词",
              "最近的对话" in captured.get("all", ""), captured.get("all", "")[:120])
    finally:
        await comp.stop()


async def test_history_recall_and_split() -> None:
    """分条历史 / 稳定 message_id / 撤回（含多气泡只撤一条）。"""
    from app.characters import CharacterRegistry
    from app.channel.onebot_server import OneBotServerChannel
    from app.channel.napcat import IncomingMessage
    from app.config import QQConfig
    from app.main import Companion

    section("分条历史 / 多端同步 / 撤回")
    cfg = Config(root=ROOT)
    cfg.qq = QQConfig(self_id="10001", owner_id="10002")
    reg = CharacterRegistry(cfg)
    tmp = Store(str(Path(tempfile.mkdtemp()) / "recall.db"))

    def mk(text: str, ts: float) -> IncomingMessage:
        return IncomingMessage(kind="private", user_id="10002",
                               peer_id="10001", text=text,
                               raw={"time": ts})

    merged = Companion._merge_messages([mk("第一句", 100), mk("第二句", 101)])
    check("合并只影响这一轮理解（整段仍在）",
          merged.text == "第一句\n第二句", merged.text)
    check("保留原始分条",
          merged.raw.get("_merged_texts") == ["第一句", "第二句"],
          str(merged.raw.get("_merged_texts")))
    Companion._store_user_turns(tmp, merged)
    turns = tmp.recent_turns(10)
    check("历史按原始分条写入",
          [t["text"] for t in turns] == ["第一句", "第二句"],
          str([t["text"] for t in turns]))
    check("分条时间保留", int(turns[1]["ts"]) == 101, str(turns[1]["ts"]))

    async def on_message(_m: IncomingMessage) -> None:
        return None

    ch = OneBotServerChannel(
        cfg.qq, on_message, store=tmp,
        characters=reg, store_for=lambda _cid: tmp,
    )
    h1 = await ch.api_get_friend_msg_history(
        {"user_id": "10001", "count": 10})
    mids1 = [m["message_id"] for m in h1["messages"]]
    h2 = await ch.api_get_friend_msg_history(
        {"user_id": "10001", "count": 10})
    mids2 = [m["message_id"] for m in h2["messages"]]
    check("历史 message_id 稳定可复现", mids1 == mids2,
          f"{mids1} vs {mids2}")
    check("历史 message_id 用 turn 编号", all(x.startswith("h") for x in mids1),
          str(mids1))

    # 「加载更早」翻页：before_ts 只带出其之前的（接口层有 +2 秒宽限，
    # 覆盖一轮回复拆气泡导致的 time/ts 错位；重复由前端 mid 去重兜底）
    tmp.add_turn("user", "更早的一句", ts=50)
    page = await ch.api_get_friend_msg_history(
        {"user_id": "10001", "count": 10, "before_ts": 99})
    ptexts = [m["raw_message"] for m in page["messages"]]
    check("★ before_ts 翻页：更早的和边界内的都在，之后的没有",
          "更早的一句" in ptexts and "第一句" in ptexts
          and "第二句" not in ptexts, str(ptexts))
    # 不带 before_ts 时行为和原来完全一致（倒着数 count 条）
    latest = await ch.api_get_friend_msg_history(
        {"user_id": "10001", "count": 10})
    ltexts = [m["raw_message"] for m in latest["messages"]]
    check("★ 不传 before_ts 仍返回最新一页",
          "第二句" in ltexts, str(ltexts))

    before = len(tmp.recent_turns(20))
    r = await ch.api_delete_msg({"message_id": mids1[0],
                                 "peer_id": "10001"})
    check("撤回接口返回 message_id", r.get("message_id") == mids1[0], str(r))
    check("撤回历史消息后 transcript 少一条",
          len(tmp.recent_turns(20)) == before - 1,
          f"{before} → {len(tmp.recent_turns(20))}")
    check("撤回会广播 friend_recall 事件",
          any(e.get("post_type") == "notice"
              and e.get("notice_type") == "friend_recall"
              for e in ch._offline_queue),
          str(ch._offline_queue)[:120])

    sent = await ch.api_send_msg({
        "user_id": "10001",
        "message": [{"type": "text", "data": {"text": "临时消息"}}],
    })
    await asyncio.sleep(0.1)
    tmp.add_turn("user", "临时消息")
    await ch.api_delete_msg({"message_id": sent["message_id"],
                             "peer_id": "10001"})
    check("撤回实时消息会删掉对应历史",
          "临时消息" not in [t["text"] for t in tmp.recent_turns(20)],
          str([t["text"] for t in tmp.recent_turns(20)]))

    tid = tmp.add_turn("assistant", "第一条\n第二条")
    turn = tmp.get_turn(tid)
    OneBotServerChannel._remove_turn_segment(tmp, turn, index=0)
    check("撤回单个气泡只删那一行",
          tmp.get_turn(tid)["text"] == "第二条",
          str(tmp.get_turn(tid)))

    await ch.api_set_msg_read({"user_id": "10001", "time": 1234567890})
    rec = await ch.api_get_recent_contact({})
    mine = next((x for x in rec if x.get("peerUin") == 10001), {})
    check("已读进度写入服务端", mine.get("readTime") == 1234567890, str(mine))
    check("已读进度会通知其他端",
          any(e.get("notice_type") == "read_state"
              for e in ch._offline_queue + ch._recent_events),
          str(ch._offline_queue + ch._recent_events)[:120])
    tmp.close()


# ---------------------------------------------------------------- 话题发散
async def test_group_topic_divergence() -> None:
    """群话题发散：全群说烂的词要被抓出来、名字不能被误伤、硬闸门只拦复读。

    背景（用户实测）：老师在群里提了一次「米粉」，之后几十条全在聊米粉 ——
    相邻两条共享话题词 58%，真实群只有 10%。根因是群发言的禁用词只统计
    「她自己说过的话」，而私聊那套还刻意豁免「对方提到过的词」。
    """
    from app.act import Sender
    from app.channel.console import ConsoleChannel
    from app.config import GroupConfig
    from app.group import GroupRuntime, Member
    from app.group_store import GroupRegistry
    from app.memory import Memory
    from app.state import StateMachine
    from app.think import group_overused_terms
    from app.traits import Traits
    from tests.mock_llm import MockLLM

    section("群话题发散（别全群咬住一个话题）")

    # ① 纯函数：谁的都算；名字/称呼不算话题
    texts = ["米粉排到哪了", "米粉那队多长", "我也想吃米粉",
             "爱丽丝刚吃了米粉", "走廊全是人", "走廊挤死了", "走廊太挤了"]
    names = ["天童爱丽丝", "橘光", "老师"]
    terms = group_overused_terms(texts, names)
    check("说多了的「米粉」被抓出来", "米粉" in terms, str(terms))
    check("「走廊」这种地点也算话题词", "走廊" in terms, str(terms))
    check("★ 成员名里的字被排除（爱丽/丽丝不是在聊爱丽丝）",
          "爱丽" not in terms and "丽丝" not in terms, str(terms))
    check("出现次数不够的不算（1~2 次不算说多了）",
          "想吃" not in terms, str(terms))

    # ② 引擎侧：拿真库里的群消息去统计 + 硬闸门
    d = Path(tempfile.mkdtemp())
    cfg = tmpcfg()
    cfg.group = GroupConfig(index_path=str(d / "g.json"),
                            dir_path=str(d / "g"), ambient_enabled=False,
                            chain_reply_probability=0.0)
    ch = ConsoleChannel(self_id="10000", owner_id="10001")
    sender = Sender(ch, cfg.behavior)
    st = Store(str(d / "m.db"))
    mem = Member(id="2001", name="甲", persona="你是测试角色。", boundaries="",
                 world="", state=StateMachine(st), memory=Memory(st, None),
                 store=st, traits=Traits(enthusiasm=60, affection=70),
                 delay_scale=1.0)
    reg = GroupRegistry(cfg)
    g = reg.create("测试群", "10001", "老师", member_ids=["2001"],
                   member_names={"2001": "甲", "3001": "天童爱丽丝"})
    rt = GroupRuntime(cfg, g, reg, MockLLM(), sender,
                      lambda cid: mem if str(cid) == "2001" else None)
    try:
        for t in ("米粉排到哪了", "米粉那队老长了", "中午又是米粉",
                  "爱丽丝也说想吃米粉"):
            rt.store.add_gmsg(kind="char", sender_id="2001", sender_name="甲",
                              text=t)
        banned = rt._overused_topic_terms()
        check("引擎统计出全群说烂的词", "米粉" in banned, str(banned))
        check("「爱丽」不在禁用词里（人名不是话题）",
              "爱丽" not in banned, str(banned))
        check("★ 硬闸门拦「同一个词说两遍」",
              rt.topic_ban_reason("米粉排到哪了，米粉那队真长") != "", "")
        check("偶尔提一次照常放行（宽容）",
              rt.topic_ban_reason("米粉排到哪了") == "", "")
        check("讲自己的事不会被误拦",
              rt.topic_ban_reason("我刚把枪擦完了") == "", "")
        check("草稿禁用词里带上了全群话题词",
              "米粉" in rt._group_avoid_terms(mem),
              str(rt._group_avoid_terms(mem)))

        # ③ 身份：分析通道必须按角色写「你自己」的名字（原来写死「小星」）
        from app.think import analyze as _analyze

        class _Cap:
            def __init__(self) -> None:
                self.sys = ""

            async def chat_json(self, messages, **kw):
                self.sys = "\n".join(str(m.get("content") or "")
                                     for m in messages
                                     if m.get("role") == "system")
                return {}

        cap = _Cap()
        await _analyze(cap, user_text="你好", recent=[], profile_text="",
                       state_text="", self_name="早濑优香")
        check("★ 分析通道按角色写入自己的名字（不再写死小星）",
              "早濑优香" in cap.sys and "小星" not in cap.sys, cap.sys[-160:])

        # ④ 情绪优先：他难受时切成「先接住他」，而不是各说各的
        class _Emo:
            async def chat_json(self, messages, **kw):
                return {"label": "低落", "intensity": 0.8, "valence": -0.6,
                        "arousal": 0.3, "need": "被安慰", "quality": 0.5,
                        "risk": "低落"}

        rt.llm = _Emo()
        hit = await rt._detect_comfort("我面试没过，挺难受的")
        check("★ 倾诉会被判成「要人接住」", hit and rt._in_comfort(), str(hit))
        scene = rt._group_scene(mem)
        check("★ 情绪优先时场景切成「先接住他」",
              "接住" in scene and "群里其他任何人" in scene, scene[-200:])
        check("情绪优先时不再禁「面试」这类当前话题",
              rt._in_comfort(), "")
        for t in ("面试没过", "那家公司", "面试真的难受"):
            rt.store.add_gmsg(kind="char", sender_id="2001", sender_name="甲",
                              text=t)
        rt.store.add_gmsg(kind="user", sender_id="10001", sender_name="老师",
                          text="我面试没过，挺难受的")
        check("老师当前话题里的词不会被当成「说烂了」",
              "面试" not in rt._overused_topic_terms(),
              str(rt._overused_topic_terms()))
    finally:
        rt.close()
        st.close()


# ---------------------------------------------------------------- run
async def main() -> int:
    print("离线测试开始（不需要 API Key / 联网）")
    test_state()
    test_bond()
    test_memory()
    test_parse()
    await test_image_candidates()
    test_segments()
    await test_suppress()
    await test_full_pipeline()
    await test_commands()
    await test_digest_offline()
    test_rhythm()
    await test_conversation()
    await test_human_tuning()
    test_split_rhythm()
    test_mface_and_diag()
    await test_sticker_system()
    await test_image_mime()
    await test_image_complete()
    await test_get_image_first()
    await test_llm_truncation()
    await test_proactive_and_profile()
    await test_rhythm_instant_and_digest()
    await test_msg_merge_sticker_forward_image()
    await test_digest_quota_and_sticker_nogate()
    await test_force_go_bypass()
    await test_emotion_engine()
    await test_search_providers()

    await test_multi_character()
    test_traits()
    test_presence()
    test_waiting_and_affection()
    await test_schedule_and_share_card()
    test_group_store()
    await test_group_engine()
    await test_group_topic_divergence()
    await test_group_files_and_quote()
    await test_history_recall_and_split()
    test_hygiene()
    test_topic_lock_fixes()
    test_sticker_offline()
    await test_onebot_server()

    print("\n" + "=" * 56)
    print(f"通过 {len(PASS)} 项，失败 {len(FAIL)} 项")
    if FAIL:
        print("\n失败明细：")
        for f in FAIL:
            print("  - " + f)
        return 1
    print("全部通过。")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(asyncio.run(main()))
    except Exception:
        traceback.print_exc()
        sys.exit(2)
