"""群聊的持久层：群索引 + 群库（每条消息一行）。

为什么不让群消息复用 `transcript`：
`transcript(id,ts,role,text)` 只够喂提示词 —— 它撑不住 UI 回放（私聊历史
假设一条 turn 的多段气泡是同一个发送者、按 `\\n` 拆条）、撑不住按消息 id
撤回（`find_turn` 靠 role+文本模糊匹配）、也不存图片/表情包/引用段。
所以群消息单独一张 `gmsg`：**每条消息一行**，段结构原样存 JSON。

`transcript` 仍然用 —— 但只作为「喂给提示词的群上下文」，角色编码成
`user` / `char:<uid>`，和真正的 UI 数据分开。
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from .config import Config
from .store import Store

# 群库额外两张表。独立成表而不是给 transcript 加列 ——
# `CREATE TABLE IF NOT EXISTS` 无法给已存在的旧库加列。
GROUP_SCHEMA = """
CREATE TABLE IF NOT EXISTS gmsg (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts REAL NOT NULL,
    kind TEXT NOT NULL,               -- user | char | system
    sender_id TEXT DEFAULT '',
    sender_name TEXT DEFAULT '',
    text TEXT DEFAULT '',
    segs TEXT DEFAULT '',             -- JSON 段数组（图片/表情/引用）
    reply_to INTEGER DEFAULT 0,       -- 引用哪条 gmsg.id
    mid TEXT DEFAULT '',              -- 对外消息 id：g<id>
    revoked INTEGER DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_gmsg_ts ON gmsg(ts DESC);
CREATE TABLE IF NOT EXISTS gres (
    uid TEXT PRIMARY KEY,             -- 成员的已读游标（禁言 backlog 靠它）
    last_gid INTEGER DEFAULT 0,
    last_ts REAL DEFAULT 0
);
"""

ROLE_OWNER = "owner"
ROLE_ADMIN = "admin"
ROLE_MEMBER = "member"

KIND_USER = "user"
KIND_CHAR = "char"
KIND_SYSTEM = "system"


class GroupStore(Store):
    """群库：gmsg（每条消息一行）+ gres（已读游标）+ 一堆 kv。"""

    def __init__(self, path: str | Path):
        super().__init__(path)
        # ⚠️ 必须用 executescript：_exec() 走的 conn.execute() 一次只能一条语句，
        # 多语句的建表脚本会直接抛 "You can only execute one statement at a time"。
        with self._lock:
            self.conn.executescript(GROUP_SCHEMA)
            self.conn.commit()

    # ---------------- 群消息 ----------------

    def add_gmsg(self, *, kind: str, sender_id: str = "",
                 sender_name: str = "", text: str = "",
                 segs: Optional[List[Dict[str, Any]]] = None,
                 reply_to: int = 0, ts: Optional[float] = None,
                 pre_id: int = 0) -> Dict[str, Any]:
        """插一条群消息，返回完整行（含 mid=g<id>）。

        ★ ts 单调递增：客户端时间戳只到秒，同一秒两条 + 客户端
        「20 秒窗口同方向同文本」去重会静默吞掉一条 —— 群里两个角色
        同时开口时非常容易撞上。所以这里至少比上一条大 1ms。
        """
        t = float(ts) if ts else time.time()
        t = max(t, self.last_gmsg_ts() + 0.001)
        cur = self._exec(
            "INSERT INTO gmsg(ts,kind,sender_id,sender_name,text,segs,reply_to,mid)"
            " VALUES(?,?,?,?,?,?,?,?)",
            (t, kind, str(sender_id or ""), str(sender_name or ""),
             str(text or ""),
             json.dumps(segs, ensure_ascii=False) if segs else "",
             int(reply_to or 0), ""),
        )
        gid = int(cur.lastrowid or 0)
        mid = f"g{gid}" if not pre_id else f"g{pre_id}"
        self._exec("UPDATE gmsg SET mid=? WHERE id=?", (mid, gid))
        row = self.get_gmsg(gid) or {}
        row["mid"] = mid
        return row

    def last_gmsg_ts(self) -> float:
        with self._lock:
            row = self.conn.execute(
                "SELECT ts FROM gmsg ORDER BY id DESC LIMIT 1").fetchone()
        return float(row["ts"]) if row else 0.0

    def _row_to_msg(self, r: Any) -> Dict[str, Any]:
        d = dict(r)
        try:
            d["segs"] = json.loads(d["segs"]) if d.get("segs") else []
        except json.JSONDecodeError:
            d["segs"] = []
        return d

    def get_gmsg(self, gid: int) -> Optional[Dict[str, Any]]:
        with self._lock:
            row = self.conn.execute(
                "SELECT * FROM gmsg WHERE id=?", (int(gid),)).fetchone()
        return self._row_to_msg(row) if row else None

    def find_gmsg(self, mid: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            row = self.conn.execute(
                "SELECT * FROM gmsg WHERE mid=?", (str(mid or ""),)).fetchone()
        return self._row_to_msg(row) if row else None

    def recent_gmsgs(self, limit: int = 40,
                     include_revoked: bool = True) -> List[Dict[str, Any]]:
        sql = "SELECT * FROM gmsg"
        if not include_revoked:
            sql += " WHERE revoked=0"
        sql += " ORDER BY id DESC LIMIT ?"
        with self._lock:
            rows = self.conn.execute(sql, (int(limit),)).fetchall()
        return [self._row_to_msg(r) for r in reversed(rows)]

    def gmsgs_before(self, before_ts: float, limit: int = 40) -> List[Dict[str, Any]]:
        """比 before_ts 更早的最近 limit 条未撤回消息（「加载更早」翻页用）。"""
        with self._lock:
            rows = self.conn.execute(
                "SELECT * FROM gmsg WHERE ts<? AND revoked=0 "
                "ORDER BY id DESC LIMIT ?",
                (float(before_ts), int(limit))).fetchall()
        return [self._row_to_msg(r) for r in reversed(rows)]

    def msgs_since(self, after_id: int, limit: int = 200) -> List[Dict[str, Any]]:
        """取 id 大于游标的消息（禁言 backlog 用）。"""
        with self._lock:
            rows = self.conn.execute(
                "SELECT * FROM gmsg WHERE id>? AND revoked=0 "
                "ORDER BY id ASC LIMIT ?", (int(after_id), int(limit))).fetchall()
        return [self._row_to_msg(r) for r in rows]

    def revoke_gmsg(self, mid: str) -> Optional[Dict[str, Any]]:
        row = self.find_gmsg(mid)
        if not row:
            return None
        self._exec("UPDATE gmsg SET revoked=1 WHERE id=?", (int(row["id"]),))
        row["revoked"] = 1
        return row

    def count_since(self, since_ts: float, uid: str = "") -> int:
        """从某个时间点起，群里（或某个成员）说了几条。

        直接数 `gmsg` 而不是维护计数器 —— 计数器和真实消息一旦不同步
        （重启、撤回、异常退出）就会算错配额，而配额是防刷屏的最后一道闸。
        """
        sql = "SELECT COUNT(*) AS n FROM gmsg WHERE ts>=? AND kind=?"
        args: List[Any] = [float(since_ts), KIND_CHAR]
        if uid:
            sql += " AND sender_id=?"
            args.append(str(uid))
        with self._lock:
            row = self.conn.execute(sql, tuple(args)).fetchone()
        return int(row["n"] or 0) if row else 0

    def count_gmsgs(self, uid: str = "", date: Optional[str] = None) -> int:
        """某成员（或全群）今天说了几条 —— 等级/配额都用它。"""
        day = date or time.strftime("%Y-%m-%d")
        start = time.mktime(time.strptime(day, "%Y-%m-%d"))
        sql = "SELECT COUNT(*) AS n FROM gmsg WHERE ts>=? AND ts<? AND kind=?"
        args: List[Any] = [start, start + 86400, KIND_CHAR]
        if uid:
            sql += " AND sender_id=?"
            args.append(str(uid))
        with self._lock:
            row = self.conn.execute(sql, tuple(args)).fetchone()
        return int(row["n"] or 0) if row else 0

    def last_spoke_ts(self, uid: str) -> float:
        with self._lock:
            row = self.conn.execute(
                "SELECT ts FROM gmsg WHERE sender_id=? AND kind=? "
                "ORDER BY id DESC LIMIT 1", (str(uid), KIND_CHAR)).fetchone()
        return float(row["ts"]) if row else 0.0

    # ---------------- 已读游标 ----------------

    def cursor(self, uid: str) -> int:
        with self._lock:
            row = self.conn.execute(
                "SELECT last_gid FROM gres WHERE uid=?", (str(uid),)).fetchone()
        return int(row["last_gid"] or 0) if row else 0

    def set_cursor(self, uid: str, last_gid: int) -> None:
        self._exec(
            "INSERT INTO gres(uid,last_gid,last_ts) VALUES(?,?,?) "
            "ON CONFLICT(uid) DO UPDATE SET last_gid=excluded.last_gid,"
            " last_ts=excluded.last_ts",
            (str(uid), int(last_gid), time.time()),
        )

    def advance_cursors(self, uids: List[str], last_gid: int) -> None:
        for u in uids or []:
            self.set_cursor(u, last_gid)

    # ---------------- 群设置 / 成员 / 公告 ----------------

    def meta(self) -> Dict[str, Any]:
        m = self.kv_get("meta") or {}
        if not isinstance(m, dict):
            m = {}
        m.setdefault("id", "")
        m.setdefault("name", "新群")
        m.setdefault("avatar", "")
        m.setdefault("created_ts", 0.0)
        m.setdefault("searchable", True)
        return m

    def set_meta(self, **kw: Any) -> Dict[str, Any]:
        m = self.meta()
        m.update({k: v for k, v in kw.items() if v is not None})
        self.kv_set("meta", m)
        return m

    def members(self) -> Dict[str, Dict[str, Any]]:
        m = self.kv_get("members") or {}
        return m if isinstance(m, dict) else {}

    def member(self, uid: str) -> Optional[Dict[str, Any]]:
        return self.members().get(str(uid))

    def add_member(self, uid: str, nickname: str = "", role: str = ROLE_MEMBER,
                   title: str = "", level: int = 1) -> Dict[str, Any]:
        m = self.members()
        key = str(uid)
        if key in m:
            m[key].update({"nickname": nickname or m[key].get("nickname", "")})
        else:
            m[key] = {
                "nickname": nickname or key,
                "role": role,
                "joined_ts": time.time(),
                "level": int(level),
                "title": title,
                "muted_until": 0.0,
            }
        self.kv_set("members", m)
        return m[key]

    def remove_member(self, uid: str) -> bool:
        m = self.members()
        if str(uid) not in m:
            return False
        m.pop(str(uid), None)
        self.kv_set("members", m)
        # 游标也清掉，避免重新入群时误判「已读到最新」
        self._exec("DELETE FROM gres WHERE uid=?", (str(uid),))
        return True

    def set_member(self, uid: str, **kw: Any) -> Optional[Dict[str, Any]]:
        m = self.members()
        key = str(uid)
        if key not in m:
            return None
        m[key].update({k: v for k, v in kw.items() if v is not None})
        self.kv_set("members", m)
        return m[key]

    def count_gmsgs_total(self, uid: str = "") -> int:
        """群内**累计**发言数（等级用；撤回的不算）。

        ⚠️ 不能拿 count_gmsgs（按当天算）来算等级 —— 那会让等级每天午夜
        归零，而且上午和下午看到的等级不一样，实测就表现为「聊天气泡上的
        LV 跟右侧成员列表对不上」。
        """
        sql = "SELECT COUNT(*) AS n FROM gmsg WHERE revoked=0"
        args: List[Any] = []
        if uid:
            sql += " AND sender_id=?"
            args.append(str(uid))
        else:
            sql += " AND kind=?"
            args.append(KIND_CHAR)
        with self._lock:
            row = self.conn.execute(sql, tuple(args)).fetchone()
        return int(row["n"] or 0) if row else 0

    def member_level(self, uid: str) -> int:
        """等级按群内**累计**发言数算（QQ 的 LV 就是活跃度）。"""
        n = self.count_gmsgs_total(uid=uid)
        return max(1, min(99, 1 + n // 10))

    def announcement(self) -> Dict[str, Any]:
        a = self.kv_get("announcement") or {}
        if not isinstance(a, dict):
            a = {}
        a.setdefault("text", "")
        a.setdefault("ts", 0.0)
        a.setdefault("by", "")
        a.setdefault("rev", 0)
        return a

    def set_announcement(self, text: str, by: str = "") -> Dict[str, Any]:
        a = self.announcement()
        a.update({"text": str(text or ""), "ts": time.time(),
                  "by": str(by or ""), "rev": int(a.get("rev") or 0) + 1})
        self.kv_set("announcement", a)
        return a

    def mute_all(self) -> Dict[str, Any]:
        """全员禁言状态。存**绝对时间戳**而不是 bool —— 重启不会静默解禁。"""
        s = self.kv_get("mute_all") or {}
        if not isinstance(s, dict):
            s = {}
        s.setdefault("on", False)
        s.setdefault("ts", 0.0)
        s.setdefault("by", "")
        return s

    def set_mute_all(self, on: bool, by: str = "") -> Dict[str, Any]:
        s = {"on": bool(on), "ts": time.time(), "by": str(by or "")}
        self.kv_set("mute_all", s)
        return s

    def join_requests(self) -> List[Dict[str, Any]]:
        r = self.kv_get("join_requests") or []
        return r if isinstance(r, list) else []

    def add_join_request(self, uid: str, name: str = "",
                         note: str = "") -> Optional[Dict[str, Any]]:
        reqs = self.join_requests()
        key = str(uid)
        if any(str(x.get("uid")) == key and x.get("status") == "pending"
               for x in reqs):
            return None                      # 已有的 pending 不重复加
        item = {"uid": key, "name": str(name or key), "note": str(note or ""),
                "ts": time.time(), "status": "pending"}
        reqs.append(item)
        self.kv_set("join_requests", reqs)
        return item

    def resolve_join_request(self, uid: str, approve: bool) -> Optional[Dict[str, Any]]:
        reqs = self.join_requests()
        hit = None
        for x in reqs:
            if str(x.get("uid")) == str(uid) and x.get("status") == "pending":
                x["status"] = "approved" if approve else "rejected"
                hit = x
                break
        if not hit:
            return None
        self.kv_set("join_requests", reqs)
        return hit

    def pending_requests(self) -> List[Dict[str, Any]]:
        return [x for x in self.join_requests() if x.get("status") == "pending"]


# ---------------------------------------------------------------- 群索引

@dataclass
class Group:
    """群的元数据（列表页要的字段，避免为了列表去开 N 个 DB）。"""
    id: str
    name: str
    avatar: str = ""
    created_ts: float = 0.0
    extra: Dict[str, Any] = field(default_factory=dict)


class GroupRegistry:
    """群清单：`data/groups.json` + `data/groups/<id>/companion.db`。

    和 `CharacterRegistry` 同构 —— 只是群比角色多一个「每个群一个库」。
    """

    def __init__(self, cfg: Config):
        self.cfg = cfg
        # 走 cfg.resolve：测试可以把群数据改到临时目录，
        # 不污染用户真实的 data/（否则跑一次测试就多出几个群）
        self._dir = cfg.resolve(cfg.group.dir_path)
        self._index_path = cfg.resolve(cfg.group.index_path)
        self._groups: Dict[str, Group] = {}
        self._order: List[str] = []
        self._stores: Dict[str, GroupStore] = {}
        self._load()

    # ---------- 索引 ----------

    def _load(self) -> None:
        if not self._index_path.exists():
            return
        try:
            raw = json.loads(self._index_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as e:
            print(f"[groups] 读取 {self._index_path} 失败：{e!r}")
            return
        for entry in raw.get("groups", []) if isinstance(raw, dict) else []:
            if not isinstance(entry, dict):
                continue
            gid = str(entry.get("id") or "").strip()
            if not gid:
                continue
            self._groups[gid] = Group(
                id=gid,
                name=str(entry.get("name") or "群聊"),
                avatar=str(entry.get("avatar") or ""),
                created_ts=float(entry.get("created_ts") or 0.0),
            )
            self._order.append(gid)
        if self._order:
            print(f"[groups] 已加载 {len(self._order)} 个群："
                  + "、".join(self._groups[g].name for g in self._order))

    def _save_index(self) -> None:
        data = {"groups": [
            {"id": g.id, "name": g.name, "avatar": g.avatar,
             "created_ts": g.created_ts}
            for g in self.all()
        ]}
        self._index_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._index_path.with_name(self._index_path.name + ".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2),
                       encoding="utf-8")
        tmp.replace(self._index_path)

    def reload(self) -> None:
        self._groups, self._order = {}, []
        self._load()

    # ---------- 查询 ----------

    def all(self) -> List[Group]:
        return [self._groups[g] for g in self._order if g in self._groups]

    def get(self, gid: str) -> Optional[Group]:
        return self._groups.get(str(gid or ""))

    def exists(self, gid: str) -> bool:
        return str(gid or "") in self._groups

    def db_path(self, gid: str) -> Path:
        return self._dir / str(gid) / "companion.db"

    def files_dir(self, gid: str) -> Path:
        """群文件/群相册的落盘目录（和群库同层，便于整体备份/清理）。"""
        return self._dir / str(gid) / "files"

    def store_for(self, gid: str) -> GroupStore:
        """群库句柄（懒加载 + 缓存）。★ 群 id 绝不能走 Companion.store_for。"""
        key = str(gid or "")
        st = self._stores.get(key)
        if st is None:
            st = GroupStore(self.db_path(key))
            self._stores[key] = st
        return st

    def stores(self) -> List[GroupStore]:
        return [self.store_for(g.id) for g in self.all()]

    # ---------- 建群 / 增删 ----------

    def next_id(self) -> str:
        nums = []
        for g in self.all():
            try:
                nums.append(int(g.id))
            except ValueError:
                continue
        return str(max(nums + [8800000]) + 1)

    def create(self, name: str, owner_id: str, owner_name: str = "",
               member_ids: Optional[List[str]] = None,
               member_names: Optional[Dict[str, str]] = None,
               avatar: str = "") -> Group:
        """建群：写索引 + 建库 + 群主入群 + 拉人。"""
        gid = self.next_id()
        name = (name or "").strip() or f"{owner_name or '我'}的群"
        g = Group(id=gid, name=name, avatar=avatar, created_ts=time.time())
        self._groups[gid] = g
        self._order.append(gid)
        self._save_index()

        st = self.store_for(gid)
        st.set_meta(id=gid, name=name, avatar=avatar,
                    created_ts=g.created_ts, searchable=True)
        st.add_member(owner_id, owner_name or "我", role=ROLE_OWNER, level=99)
        names = member_names or {}
        for cid in (member_ids or []):
            st.add_member(cid, names.get(str(cid), str(cid)), role=ROLE_MEMBER)
        st.add_gmsg(kind=KIND_SYSTEM, text=f"群「{name}」创建了", sender_id="")
        print(f"[groups] 已建群：{name}（{gid}）"
              f"，成员 {len(st.members())} 人")
        return g

    def rename(self, gid: str, name: str) -> bool:
        g = self.get(gid)
        if not g or not (name or "").strip():
            return False
        g.name = name.strip()
        self._save_index()
        self.store_for(gid).set_meta(name=g.name)
        return True

    def set_avatar(self, gid: str, url: str) -> bool:
        g = self.get(gid)
        if not g:
            return False
        g.avatar = url or ""
        self._save_index()
        self.store_for(gid).set_meta(avatar=g.avatar)
        return True

    def close(self) -> None:
        for st in self._stores.values():
            try:
                st.close()
            except Exception:  # noqa: BLE001
                pass
        self._stores.clear()
