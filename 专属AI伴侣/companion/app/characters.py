"""角色库：星野 + 网页端可切换的其他角色。

角色是纯数据，不依赖运行中的 Companion：

- `persona/characters/<名字>/persona.md`：人设正文（必需）
- `data/characters.json`：角色清单（id / name / slug）
- `data/avatars/<id>.png`：头像（复用现有的头像接口）

星野不在这里重复登记，她的 id/nickname 仍来自 config.yaml；
这里只负责新增角色，保证老的单角色逻辑完全不受影响。
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

from .config import Config
from .schedule import Schedule, load_schedules, schedule_for


@dataclass
class Character:
    id: str
    name: str
    slug: str
    persona: str
    is_primary: bool = False
    source: str = ""
    # 角色自己的作息（睡点/起点）。没在 persona/schedules.json 里配的，
    # 按名字派生一份稳定的默认作息 —— 不同角色天然错开，不会「一起困」。
    schedule: Optional[Schedule] = None

    @property
    def is_guest(self) -> bool:
        return not self.is_primary


class CharacterRegistry:
    """按配置加载角色清单；星野永远排第一。"""

    def __init__(self, cfg: Config):
        self.cfg = cfg
        # 角色作息表（persona/schedules.json），星野也走这套
        self.schedules = load_schedules(cfg)
        pid = str(cfg.qq.self_id or "").strip() or "10000000"
        pname = (cfg.qq.server.bot_nickname or "星野").strip() or "星野"
        self.primary = Character(
            id=pid,
            name=pname,
            slug="",
            persona=cfg.read_persona("persona.md"),
            is_primary=True,
            schedule=schedule_for(pname, self.schedules),
        )
        self._items: Dict[str, Character] = {self.primary.id: self.primary}
        self._order: List[str] = [self.primary.id]
        self._load()

    # ---------- 加载 ----------

    def _load(self) -> None:
        path = self.cfg.root / "data" / "characters.json"
        if not path.exists():
            return
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as e:
            print(f"[characters] 读取 {path} 失败：{e!r}")
            return
        for entry in raw.get("characters", []) if isinstance(raw, dict) else []:
            if not isinstance(entry, dict):
                continue
            cid = str(entry.get("id") or "").strip()
            name = str(entry.get("name") or "").strip()
            slug = str(entry.get("slug") or name).strip()
            if not cid or not name or cid == self.primary.id:
                continue
            persona_path = (self.cfg.root / "persona" / "characters"
                            / slug / "persona.md")
            if not persona_path.exists():
                print(f"[characters] 跳过 {name}：找不到 {persona_path}")
                continue
            try:
                persona = persona_path.read_text(encoding="utf-8").strip()
            except OSError as e:
                print(f"[characters] 跳过 {name}：读取人设失败 {e!r}")
                continue
            if not persona:
                continue
            self._items[cid] = Character(
                id=cid,
                name=name,
                slug=slug,
                persona=persona,
                source=str(entry.get("source") or ""),
                schedule=schedule_for(name, self.schedules),
            )
            self._order.append(cid)
        if len(self._order) > 1:
            print(f"[characters] 已加载 {len(self._order) - 1} 个新增角色："
                  + "、".join(self._items[i].name for i in self._order[1:]))

    # ---------- 查询 ----------

    def reload(self) -> None:
        """从 data/characters.json 重新加载（网页里新增角色后调用）。"""
        self._items = {self.primary.id: self.primary}
        self._order = [self.primary.id]
        self._load()

    def all(self) -> List[Character]:
        return [self._items[i] for i in self._order if i in self._items]

    def guests(self) -> List[Character]:
        return [c for c in self.all() if not c.is_primary]

    def get(self, cid: str) -> Optional[Character]:
        return self._items.get(str(cid or ""))

    def is_guest(self, cid: str) -> bool:
        c = self.get(cid)
        return bool(c and not c.is_primary)

    def buddy(self, c: Character) -> Dict[str, object]:
        """NapCat / Stapxs 好友结构（多给几个字段不影响兼容）。"""
        try:
            uid = int(c.id)
        except ValueError:
            uid = 0
        return {
            "user_id": uid,
            "nickname": c.name,
            "remark": "",
            "longNick": "",
            "q_id": "",
            "sex": "unknown",
        }
