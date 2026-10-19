"""离线测试用的假模型。

继承真 LLM，只覆写 chat / chat_with_images，让整条管线能在**没有 API Key、
不联网**的情况下跑完。这样管线接线错误（字段名、调用顺序、异常分支）
可以在本地被测出来，而不是等到接上 QQ 才暴露。

注意：它不验证「模型回答得好不好」，只验证「代码接线对不对」。
"""
from __future__ import annotations

import json
from typing import Any, Dict, List

from app.config import LLMConfig
from app.llm import LLM


class MockLLM(LLM):
    def __init__(self, reply: str = "嗯，我在听", **overrides: Any):
        super().__init__(LLMConfig(api_key="mock", model="deepseek-flash"))
        self.reply = reply
        self.overrides = overrides
        self.calls: List[str] = []
        self.last_express_prompt: str = ""     # 供测试断言「图的内容有没有传进表达通道」

    # 便于测试断言「某条通道被走到了」
    def _tag(self, kind: str) -> None:
        self.calls.append(kind)

    async def chat(self, messages: List[Dict[str, Any]], **kw: Any) -> str:
        # 把 system 和 user 的内容都拼起来判断，因为有些调用（如送出前复核）
        # 只带 user 消息，不带 system。
        blobs: List[str] = []
        for m in messages:
            c = m.get("content")
            blobs.append(c if isinstance(c, str) else json.dumps(c, ensure_ascii=False))
        system = "\n".join(blobs)

        if "情绪标注器" in system:
            self._tag("emotion")
            return json.dumps(
                self.overrides.get(
                    "emotion",
                    {
                        "label": "开心", "intensity": 0.8, "valence": 0.7,
                        "arousal": 0.6, "need": "想陪伴", "quality": 0.85,
                        "risk": "none", "note": "语气轻快",
                    },
                ),
                ensure_ascii=False,
            )

        if "对话分析器" in system:
            self._tag("analyze")
            return json.dumps(
                self.overrides.get(
                    "analyze",
                    {
                        "intent": "分享今天的事",
                        "emotion_label": "开心",
                        "latent_need": "想陪伴",
                        "relation_signal": 0.6,
                        "risk": "none",
                        "reply_strategy": "顺着接话，问一个细节",
                        "quality": 0.85,
                        "profile_updates": [{"key": "喜欢喝的饮料", "value": "冰美式"}],
                        "interest_terms": ["咖啡"],
                        "memory_worthy": True,
                        "memory_summary": "对方提到今天喝到一杯很好喝的冰美式",
                    },
                ),
                ensure_ascii=False,
            )

        # 匹配串要够稳 —— 提示词改措辞不该让路由失配（曾被改坏过一次）
        if "要不要配表情包" in system:
            self._tag("sticker_judge")
            return json.dumps(
                self.overrides.get("sticker", {"send": True, "count": 1,
                                               "emotion": "开心", "reason": "日常接梗"}),
                ensure_ascii=False,
            )

        if "内容把关人" in system:
            self._tag("digest_judge")
            return json.dumps(
                self.overrides.get(
                    "digest_judge",
                    {"index": 1, "score": 8, "angle": "有意思的动态，值得聊两句"}),
                ensure_ascii=False,
            )

        if "现在要不要再说一句" in system:
            self._tag("followup_judge")
            return json.dumps(
                self.overrides.get(
                    "followup",
                    {"speak": True, "kind": "probe", "topic": "追问一个细节", "reason": "想接着问"},
                ),
                ensure_ascii=False,
            )

        if "这次想说的属于哪一类" in system:
            self._tag("proactive_judge")
            return json.dumps(
                self.overrides.get(
                    "proactive",
                    {"speak": True, "kind": "miss", "topic": "想到你昨天说的咖啡", "reason": "有想说的"},
                ),
                ensure_ascii=False,
            )

        if "发出去还成立吗" in system:
            self._tag("revalidate")
            return json.dumps(
                self.overrides.get("revalidate", {"send": True, "reason": "还成立"}),
                ensure_ascii=False,
            )

        if "抽取" in system and "关键词" in system:
            self._tag("extract")
            return json.dumps({"keywords": ["咖啡", "剪辑"]}, ensure_ascii=False)

        # 其余（表达通道）
        self._tag("express")
        self.last_express_prompt = system
        # reply 是列表时依次轮换：测试需要「每次接话内容都不同」，
        # 否则第⑦层重复拦截会把和上一条一模一样的草稿拦掉（假失败）。
        if isinstance(self.reply, list):
            idx = self.calls.count("express") - 1
            return str(self.reply[idx % len(self.reply)])
        return self.reply

    async def chat_with_images(
        self, text: str, images: List[Any], *, system: str | None = None, mimes: List[str] | None = None
    ) -> str:
        # 偷表情包的判定走的是同一个多模态入口，要用 prompt 区分开
        blob = (system or "") + (text or "")
        if "收进自己的表情包库" in blob:
            self._tag("steal_judge")
            return json.dumps(
                self.overrides.get(
                    "steal",
                    {"keep": True, "emotion": "卖萌", "tags": ["搞笑"],
                     "reason": "挺好笑的，收了", "desc": "一张搞怪表情包"},
                ),
                ensure_ascii=False,
            )
        self._tag("vision")
        return self.overrides.get("vision", "一张熊猫头表情包，配文「还有这种操作」，用来表达震惊和无语。")
