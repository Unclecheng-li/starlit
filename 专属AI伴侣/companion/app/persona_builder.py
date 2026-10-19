"""根据角色名联网搜集资料，蒸馏成 vol 用的人格卡。

优先走 DeepSeek Responses API 的 `web_search` 工具：
- `web_search` 目前只在 deepseek-v4-pro 下支持
- 如果用户的 key/服务商不支持，自动退回「用模型已有知识蒸馏」
- 再失败就抛错，由调用方提示用户手动填写

输出统一为：
    {"name", "series", "aliases", "summary", "persona_md", "interests"}
"""
from __future__ import annotations

import json
import re
from typing import Any, Dict, List

from .llm import LLM, LLMError

_JSON_RE = re.compile(r"\{[\s\S]*\}")


def _extract_text(data: Dict[str, Any]) -> str:
    out: List[str] = []
    for item in data.get("output") or []:
        if not isinstance(item, dict) or item.get("type") != "message":
            continue
        for part in item.get("content") or []:
            if isinstance(part, dict) and part.get("type") == "output_text":
                out.append(str(part.get("text") or ""))
    return "\n".join(x for x in out if x)


def _parse_json(text: str) -> Dict[str, Any]:
    t = (text or "").strip()
    if t.startswith("```"):
        t = re.sub(r"^```[a-zA-Z]*\s*", "", t)
        t = re.sub(r"\s*```$", "", t)
    try:
        data = json.loads(t)
        return data if isinstance(data, dict) else {}
    except json.JSONDecodeError:
        m = _JSON_RE.search(t)
        if not m:
            return {}
        try:
            data = json.loads(m.group(0))
            return data if isinstance(data, dict) else {}
        except json.JSONDecodeError:
            return {}


def _normalize(name: str, data: Dict[str, Any]) -> Dict[str, Any]:
    persona = str(data.get("persona_md") or data.get("persona") or "").strip()
    if len(persona) < 200:
        return {}
    interests = data.get("interests")
    if not isinstance(interests, list):
        interests = []
    interests = [str(x).strip() for x in interests if str(x).strip()][:8]
    return {
        "name": str(data.get("name") or name).strip() or name,
        "series": str(data.get("series") or "").strip(),
        "aliases": [str(x) for x in (data.get("aliases") or []) if str(x)][:8],
        "summary": str(data.get("summary") or "").strip(),
        "persona_md": persona[:12000],
        "interests": interests,
    }


def _prompt(name: str, searched: bool) -> str:
    how = (
        "请先联网搜索这个角色的官方资料、百科条目和玩家整理，再蒸馏。"
        "如果搜到多个同名角色，选最知名的那个，并在 series 里写清作品。"
        if searched else
        "请根据你已有的知识整理这个角色。不确定的地方不要编造。"
    )
    return f"""角色名：{name}

{how}

只输出一个 JSON 对象，不要输出任何解释或 Markdown 代码块：
{{
  "found": true,
  "name": "角色名",
  "series": "作品名",
  "aliases": ["别名"],
  "summary": "一句话概括",
  "interests": ["她自己的兴趣1", "兴趣2", "兴趣3", "兴趣4", "兴趣5"],
  "persona_md": "完整的人格卡 Markdown"
}}

persona_md 必须是中文，并使用下面这些小标题（没有资料的小节可以省略）：
# 人格卡 · 角色名
## 是谁
## 说话方式
## 性格
## 喜欢 / 讨厌
## 聊天习惯
## 情绪表现
## 红线
## 主体性
## 不要出现的句式

写作要求：
- 忠于原作，保留角色的自称、口癖、语气、身份、人际关系
- 重点是「她在聊天软件里怎么说话」，不是维基百科式生平
- 不要编造没把握的设定；不确定的细节宁可不写
- 不要写成客服腔、不要大段抒情、不要使用「作为AI」这类句子
- 红线统一包含：不聊政治、不涉露骨色情、不提供违法犯罪操作、不做情绪绑架
- 被认真追问「你是不是 AI」时坦率承认，不编谎
"""


async def _try_responses(llm: LLM, name: str,
                         model: str, use_search: bool) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "model": model,
        "instructions": "你是角色设定整理器。只输出合法 JSON。",
        "input": _prompt(name, use_search),
        "reasoning": {"effort": "low"},
        "max_output_tokens": 6000,
        "stream": False,
        "text": {"format": {"type": "json_object"}},
    }
    if use_search:
        payload["tools"] = [{"type": "web_search"}]
        payload["tool_choice"] = "auto"
    data = await llm.responses(payload, timeout=180)
    parsed = _parse_json(_extract_text(data))
    return _normalize(name, parsed)


async def build_persona(llm: LLM, name: str) -> Dict[str, Any]:
    """返回规范化后的人格卡；全部失败时抛 LLMError。"""
    errors: List[str] = []

    # 1) 当前模型 + 联网（部分服务商可能已支持）
    try:
        out = await _try_responses(llm, name, llm.cfg.model, True)
        if out:
            print(f"[persona] {name}：使用 {llm.cfg.model} + web_search 蒸馏成功")
            return out
    except Exception as e:  # noqa: BLE001
        errors.append(f"{llm.cfg.model}+search: {e!r}")

    # 2) deepseek-v4-pro + web_search（官方文档里 web_search 只在这个模型下支持）
    if llm.cfg.model != "deepseek-v4-pro":
        try:
            out = await _try_responses(llm, name, "deepseek-v4-pro", True)
            if out:
                print(f"[persona] {name}：使用 deepseek-v4-pro + web_search 蒸馏成功")
                return out
        except Exception as e:  # noqa: BLE001
            errors.append(f"deepseek-v4-pro+search: {e!r}")

    # 3) 不联网，用模型已有知识蒸馏
    try:
        data = await llm.chat_json(
            [
                {"role": "system",
                 "content": "你是角色设定整理器。只输出合法 JSON。"},
                {"role": "user", "content": _prompt(name, False)},
            ],
            temperature=0.3,
            max_tokens=5000,
        )
        out = _normalize(name, data if isinstance(data, dict) else {})
        if out:
            print(f"[persona] {name}：联网失败，改用模型知识蒸馏")
            return out
    except Exception as e:  # noqa: BLE001
        errors.append(f"knowledge: {e!r}")

    raise LLMError("角色资料蒸馏失败：" + "；".join(errors[-2:]))
