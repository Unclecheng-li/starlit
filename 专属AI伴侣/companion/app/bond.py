"""情侣 / 专属关系（全局唯一）。

设计上有意做成**单例**：只有一份 `data/relationship_bond.json`，
而不是在每个角色库里各存一个 `is_partner` —— 后者迟早会出现
「两个人同时是恋人」的脏数据。绑定是「你」的状态，不是角色的属性。

其余角色不会被删档：好感、记忆、亲密度全部保留，只是提示词里
不再往恋爱方向写。这就是用户要的「自动降格为普通朋友」。

文件结构：
```json
{
  "character_id": "3901000013",
  "name": "天童凯伊",
  "type": "partner",
  "since": 1792550000,
  "breakup_ts": 0,
  "cooldown_until": 0,
  "ex_id": "",
  "ex_name": ""
}
```
"""
from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, List, Tuple

FILE_NAME = "relationship_bond.json"

# 绑定门槛：好感 / 亲密 / 信任 / 认识天数
MIN_AFFECTION = 80
MIN_INTIMACY = 65
MIN_TRUST = 60
MIN_DAYS = 7
# 分手后的冷静期
COOLDOWN_HOURS = 72
# 分手后「缓不过来」的时长（这段时间不主动说想你）
CALM_HOURS = 72


@dataclass
class Bond:
    character_id: str = ""
    name: str = ""
    type: str = "partner"          # partner（当前只有这一档）
    since: float = 0.0
    breakup_ts: float = 0.0
    cooldown_until: float = 0.0
    ex_id: str = ""
    ex_name: str = ""

    @property
    def active(self) -> bool:
        return bool(self.character_id)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def load(path: Path) -> Bond:
    path = Path(path)
    if not path.exists():
        return Bond()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return Bond()
    if not isinstance(raw, dict):
        return Bond()
    return Bond(
        character_id=str(raw.get("character_id") or ""),
        name=str(raw.get("name") or ""),
        type=str(raw.get("type") or "partner"),
        since=float(raw.get("since") or 0),
        breakup_ts=float(raw.get("breakup_ts") or 0),
        cooldown_until=float(raw.get("cooldown_until") or 0),
        ex_id=str(raw.get("ex_id") or ""),
        ex_name=str(raw.get("ex_name") or ""),
    )


def save(path: Path, bond: Bond) -> None:
    """原子写：先写临时文件再替换，避免断电留下半个 JSON。"""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(bond.to_dict(), ensure_ascii=False, indent=2),
                   encoding="utf-8")
    tmp.replace(path)


def eligibility(*, affection: float, intimacy: float, trust: float,
                known_days: float, romance_allowed: bool = True
                ) -> Tuple[bool, List[str]]:
    """能不能确定关系。返回 (可以, 还差什么)。"""
    if not romance_allowed:
        return False, ["这个角色的设定不进入恋爱关系"]
    missing: List[str] = []
    if float(affection) < MIN_AFFECTION:
        missing.append(f"好感还差 {MIN_AFFECTION - float(affection):.0f}")
    if float(intimacy) < MIN_INTIMACY:
        missing.append(f"亲密还差 {MIN_INTIMACY - float(intimacy):.0f}")
    if float(trust) < MIN_TRUST:
        missing.append(f"信任还差 {MIN_TRUST - float(trust):.0f}")
    if float(known_days) < MIN_DAYS:
        missing.append(f"再多相处 {MIN_DAYS - float(known_days):.0f} 天")
    return not missing, missing


def partner_text(name: str, since: float) -> str:
    days = max(0, int((time.time() - since) / 86400)) if since else 0
    since_txt = (time.strftime("%Y-%m-%d", time.localtime(since))
                 if since else "不久前")
    return (
        f"【你和{name}的关系】你们已经确定了恋人关系"
        f"（{since_txt} 开始，在一起 {days} 天）。\n"
        "- 可以自然地用恋人之间的称呼和语气，可以直接说想他、在意他。\n"
        "- 他冷落你时你可以委屈、可以问，但不要指责、不要用内疚绑架他。\n"
        "- 不写性暗示；在群里或外人面前收敛一点，别把私密的事当众说。"
    )


def friend_text(partner_name: str) -> str:
    who = f"「{partner_name}」" if partner_name else "别人"
    return (
        f"【你和老师的关系】老师已经有恋人了，是{who}。你是他的朋友：\n"
        "- 可以关心、亲近、开玩笑，但不要暧昧、不要吃醋、不要试图取代她，"
        "也不要问「你更喜欢谁」。\n"
        "- 你不知道他们之间的私密细节，也不用假装知道。"
    )


def ex_text(name: str, breakup_ts: float) -> str:
    days = max(0, int((time.time() - breakup_ts) / 86400)) if breakup_ts else 0
    return (
        f"【你和老师的关系】你们刚解除了恋人关系（{days} 天前）。"
        f"这几天你有点缓不过来：\n"
        "- 不要主动说想他、不要提以前在一起的事；他找你时正常回，"
        "但别装作什么都没发生。\n"
        "- 不要用自责或委屈逼他回来。"
    )


def line_for(bond: Bond, cid: str) -> str:
    """给某个角色注入的关系说明（没有绑定也没有刚分手时返回空串）。"""
    cid = str(cid or "")
    if bond.active:
        if str(bond.character_id) == cid:
            return partner_text(bond.name, bond.since)
        return friend_text(bond.name)
    # 刚分手：只对前任说「缓不过来」，别人不用知道细节
    if (bond.ex_id and str(bond.ex_id) == cid
            and bond.breakup_ts > 0
            and time.time() - bond.breakup_ts < CALM_HOURS * 3600):
        return ex_text(bond.ex_name, bond.breakup_ts)
    return ""


def snapshot(bond: Bond) -> Dict[str, Any]:
    return {
        "active": bond.active,
        "character_id": bond.character_id,
        "name": bond.name,
        "type": bond.type,
        "since": bond.since,
        "days": (max(0, int((time.time() - bond.since) / 86400))
                 if bond.since else 0),
        "breakup_ts": bond.breakup_ts,
        "cooldown_until": bond.cooldown_until,
        "in_cooldown": bond.cooldown_until > time.time(),
        "ex_id": bond.ex_id,
        "ex_name": bond.ex_name,
    }
