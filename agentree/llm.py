"""OpenAI 兼容的极简异步客户端（内置默认指向本地网关，可用环境变量切到任何兼容端点）。"""
from __future__ import annotations

import asyncio
import json
import os

# 内置默认：本地 OpenAI 兼容网关（可用 AGENTREE_* 环境变量覆盖；
# 公开环境请改用 DEEPSEEK_API_KEY / OPENAI_API_KEY，切勿把密钥写进源码）。
_DEFAULT_BASE = "http://127.0.0.1:3065/v1"
_DEFAULT_MODEL = "deepseek-v4-flash"
_RETRY_STATUS = {408, 409, 429, 500, 502, 503, 504}


def _resolve(base_url, api_key, model):
    """解析优先级：显式参数 > AGENTREE_* > DEEPSEEK_* / OPENAI_* > 内置默认（本地网关）。"""
    base_url = base_url or os.environ.get("AGENTREE_BASE_URL")
    model = model or os.environ.get("AGENTREE_MODEL")
    api_key = api_key or os.environ.get("AGENTREE_API_KEY")

    if not api_key and os.environ.get("DEEPSEEK_API_KEY"):
        api_key = os.environ["DEEPSEEK_API_KEY"]
        base_url = base_url or "https://api.deepseek.com"
        model = model or "deepseek-chat"

    if not api_key and os.environ.get("OPENAI_API_KEY"):
        api_key = os.environ["OPENAI_API_KEY"]
        base_url = base_url or os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1")
        model = model or os.environ.get("OPENAI_MODEL", "gpt-4o-mini")

    if not api_key:
        raise RuntimeError(
            "No LLM API key configured. Set one of AGENTREE_API_KEY (self-hosted/local gateway), "
            "DEEPSEEK_API_KEY, or OPENAI_API_KEY."
        )
    return (base_url or _DEFAULT_BASE, api_key, model or _DEFAULT_MODEL)


class LLMClient:
    def __init__(self, base_url=None, api_key=None, model=None, timeout: float = 120.0):
        import httpx  # 懒加载：核心循环不依赖 httpx，测试可注入假客户端

        base_url, api_key, model = _resolve(base_url, api_key, model)
        self.base_url = base_url.rstrip("/")
        self.model = model
        self._http = httpx.AsyncClient(
            base_url=self.base_url,
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=timeout,
        )

    async def chat(self, messages, tools=None, temperature: float = 0.7) -> dict:
        payload = {"model": self.model, "messages": messages, "temperature": temperature}
        if tools:
            payload["tools"] = tools
        data = await self._post(payload)

        msg = (data.get("choices") or [{}])[0].get("message", {})
        tool_calls = []
        for tc in msg.get("tool_calls") or []:
            fn = tc.get("function", {})
            raw = fn.get("arguments") or "{}"
            try:
                args = json.loads(raw)
                if not isinstance(args, dict):
                    args = {"_raw": raw}
            except json.JSONDecodeError:
                args = {"_raw": raw}
            tool_calls.append({
                "id": tc.get("id") or f"call_{len(tool_calls)}",
                "name": fn.get("name", ""),
                "arguments": args,
            })
        usage = data.get("usage") or {}
        return {
            "content": msg.get("content") or "",
            "tool_calls": tool_calls,
            "usage": {"in": usage.get("prompt_tokens", 0),
                      "out": usage.get("completion_tokens", 0)},
        }

    async def _post(self, payload) -> dict:
        last_err = None
        for attempt in range(3):
            try:
                resp = await self._http.post("/chat/completions", json=payload)
                if resp.status_code in _RETRY_STATUS:
                    last_err = f"HTTP {resp.status_code}: {resp.text[:200]}"
                else:
                    resp.raise_for_status()
                    return resp.json()
            except Exception as e:  # 网络错误同样退避重试
                last_err = f"{type(e).__name__}: {e}"
            await asyncio.sleep(2 ** attempt)
        raise RuntimeError(f"LLM 请求失败（重试 3 次）: {last_err}")

    async def list_models(self) -> list[str]:
        """GET /models，返回模型 id 列表（OpenAI 兼容端点）。"""
        resp = await self._http.get("/models")
        resp.raise_for_status()
        data = resp.json()
        return [m.get("id") for m in data.get("data", []) if m.get("id")]

    async def aclose(self) -> None:
        await self._http.aclose()
