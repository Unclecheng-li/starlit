"""DeepSeek V4.1-Flash 客户端。

要点：
- 模型名必须是 `deepseek-flash`（deepseek-v4-flash / deepseek-v4-flash-vision-exp 是兼容名）。
- deepseek-v4-pro 是纯文本模型，不能识图。
- 图片输入支持：Base64 data URL / 外部 http(s) URL / Files API file_id。
  这里实现了前两种。支持格式 JPEG / PNG / GIF / WebP。
- 图像侧限制（NVIDIA NIM model card）：最多 1024 image tokens，最小图像面积 295,936 px。
  所以缩图时短边别低于 ~600px。
"""
from __future__ import annotations

import asyncio
import base64
import json
import mimetypes
import re
from typing import Any, Dict, List, Optional

import aiohttp

from .config import LLMConfig

MIN_IMAGE_SIDE = 600  # px，低于此值的短边会被放大，避免不达模型下限


class LLMError(RuntimeError):
    pass


def _to_data_url(image: bytes, mime: str = "image/png") -> str:
    return f"data:{mime};base64,{base64.b64encode(image).decode()}"


def guess_mime(path: str) -> str:
    mime, _ = mimetypes.guess_type(path)
    return mime or "image/png"


class LLM:
    def __init__(self, cfg: LLMConfig):
        self.cfg = cfg
        self._session: Optional[aiohttp.ClientSession] = None
        # 十个角色同时说话时，别把 API 打爆：排队而不是互相挤掉
        self._sem = asyncio.Semaphore(4)

    async def _sess(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=self.cfg.timeout)
            )
        return self._session

    async def close(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()

    # ---------- 底层调用 ----------
    async def chat(
        self,
        messages: List[Dict[str, Any]],
        *,
        json_mode: bool = False,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        retries: int = 2,
    ) -> str:
        url = self.cfg.base_url.rstrip("/") + "/chat/completions"
        payload: Dict[str, Any] = {
            "model": self.cfg.model,
            "messages": messages,
            "temperature": self.cfg.temperature if temperature is None else temperature,
        }
        if max_tokens:
            payload["max_tokens"] = max_tokens
        if json_mode:
            payload["response_format"] = {"type": "json_object"}

        headers = {
            "Authorization": f"Bearer {self.cfg.api_key}",
            "Content-Type": "application/json",
        }

        last_err: Exception | None = None
        for attempt in range(retries + 1):
            try:
                sess = await self._sess()
                async with self._sem:
                    async with sess.post(url, json=payload, headers=headers) as resp:
                        body = await resp.text()
                        if resp.status != 200:
                            raise LLMError(f"HTTP {resp.status}: {body[:400]}")
                        data = json.loads(body)
                choice = (data.get("choices") or [{}])[0]
                content = (choice.get("message") or {}).get("content") or ""
                finish = str(choice.get("finish_reason") or "")

                # ★ 输出被 max_tokens 截断 —— 必须**显式报错**，不能静默返回半截。
                # 之前是 `return content or ""`，于是截断的 JSON 直接变成空串，
                # 上层宽容解析失败 → 兜底成保守值（"不发"、"中性"），
                # 表现就是「功能时好时坏」，而且完全静默、极难排查。
                if finish == "length":
                    raise LLMError(
                        f"输出被 max_tokens={max_tokens} 截断"
                        f"（已出 {len(content)} 字符）。调大该处的 max_tokens。"
                    )
                if not content.strip():
                    raise LLMError("模型返回了空内容"
                                   + (f"（finish_reason={finish}）" if finish else ""))
                return content
            except Exception as e:  # noqa: BLE001
                last_err = e
                if attempt < retries:
                    # ★ 超时/断连后必须**换一条新连接**重试 —— 连接池里
                    # 那条已经僵死的 TCP（代理切节点后常见）会被复用，
                    # 重试三次等于在死连接上干等三次（2026-10-16 事故：
                    # 表达调用挂 20+ 分钟，消息进来毫无反应）。
                    try:
                        if self._session and not self._session.closed:
                            await self._session.close()
                    except Exception:  # noqa: BLE001
                        pass
                    self._session = None
                    await asyncio.sleep(1.5 * (attempt + 1))
        raise LLMError(f"调用失败（重试 {retries} 次仍失败）：{last_err}")

    async def chat_json(
        self, messages: List[Dict[str, Any]], **kw
    ) -> Dict[str, Any]:
        text = await self.chat(messages, json_mode=True, **kw)
        return _parse_json_loose(text)

    # ---------- Responses API（支持 web_search 工具） ----------

    async def responses(self, payload: Dict[str, Any],
                        *, timeout: int = 180) -> Dict[str, Any]:
        url = self.cfg.base_url.rstrip("/") + "/responses"
        headers = {
            "Authorization": f"Bearer {self.cfg.api_key}",
            "Content-Type": "application/json",
        }
        sess = await self._sess()
        try:
            async with self._sem:
                async with sess.post(url, json=payload, headers=headers,
                                     timeout=aiohttp.ClientTimeout(total=timeout)) as resp:
                    body = await resp.text()
                    if resp.status != 200:
                        raise LLMError(f"Responses API HTTP {resp.status}: {body[:400]}")
                    data = json.loads(body)
        except LLMError:
            raise
        except Exception as e:  # noqa: BLE001
            raise LLMError(f"Responses API 调用失败：{e!r}") from e
        if not isinstance(data, dict):
            raise LLMError("Responses API 返回格式异常")
        if data.get("status") == "failed":
            raise LLMError(f"Responses API failed：{data.get('error')}")
        return data

    # ---------- 多模态 ----------
    @staticmethod
    def image_block(image: bytes | str, mime: str = "image/png") -> Dict[str, Any]:
        """构造 OpenAI 兼容的 image_url 内容块。str 视为 URL。"""
        url = image if isinstance(image, str) else _to_data_url(image, mime)
        return {"type": "image_url", "image_url": {"url": url}}

    async def chat_with_images(
        self,
        text: str,
        images: List[bytes | str],
        *,
        system: str | None = None,
        mimes: List[str] | None = None,
    ) -> str:
        content: List[Dict[str, Any]] = [{"type": "text", "text": text}]
        for i, img in enumerate(images):
            mime = (mimes[i] if mimes and i < len(mimes) else "image/png")
            content.append(self.image_block(img, mime))
        messages: List[Dict[str, Any]] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": content})
        return await self.chat(messages)

    async def chat_with_images_json(
        self,
        text: str,
        images: List[bytes | str],
        *,
        system: str | None = None,
        mimes: List[str] | None = None,
    ) -> Dict[str, Any]:
        """看图并返回解析好的 JSON。"""
        txt = await self.chat_with_images(text, images, system=system, mimes=mimes)
        return _parse_json_loose(txt)


def _salvage_flat_json(text: str) -> Optional[Dict[str, Any]]:
    """从**被截断的**扁平 JSON 里抢救出已完整的字段。

    为什么需要：推理模型偶尔会在 `reason` 那种长文本字段中间被截断，
    而 provider 有时并不把 finish_reason 报成 "length"，
    于是截断检测漏掉、整条判定失败、降级成保守值（"不发"）。
    判定用的 JSON 都是扁平的少量字段，所以按字段抢救是可行且安全的。
    """
    if not text or "{" not in text:
        return None
    out: Dict[str, Any] = {}
    # 字符串字段：允许右引号缺失（截断的情形）
    for k, v in re.findall(r'"(\w+)"\s*:\s*"([^"]*)"?', text):
        out[k] = v
    # 数字字段
    for k, v in re.findall(r'"(\w+)"\s*:\s*(-?\d+(?:\.\d+)?)', text):
        try:
            out[k] = int(v) if "." not in v else float(v)
        except ValueError:
            pass
    # 布尔字段
    for k, v in re.findall(r'"(\w+)"\s*:\s*(true|false)', text):
        out[k] = (v == "true")
    return out or None


def _parse_json_loose(text: str) -> Dict[str, Any]:
    """模型偶尔会包 ```json 或加前后缀，做一次宽容解析。"""
    t = text.strip()
    if t.startswith("```"):
        t = re.sub(r"^```[a-zA-Z]*\s*", "", t)
        t = re.sub(r"\s*```$", "", t)
    try:
        return json.loads(t)
    except json.JSONDecodeError:
        m = re.search(r"\{[\s\S]*\}", t)
        if m:
            try:
                return json.loads(m.group(0))
            except json.JSONDecodeError:
                pass
    # 最后一招：按字段抢救（应对被截断的扁平 JSON）
    salvaged = _salvage_flat_json(t)
    if salvaged:
        return salvaged
    raise LLMError(f"无法解析为 JSON：{text[:300]}")
