"""工具注册：一个 Tool = name + description + JSON Schema 参数 + async handler。"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Awaitable, Callable


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    parameters: dict  # JSON Schema（OpenAI function calling 格式的 parameters）
    handler: Callable[..., Awaitable[str]]


def tool(name: str, description: str, parameters: dict):
    """装饰器：把 async 函数包装成 Tool。函数参数名需与 parameters 中的属性一致。"""

    def deco(fn):
        return Tool(name=name, description=description, parameters=parameters, handler=fn)

    return deco


class ToolRegistry:
    def __init__(self, *tools: Tool) -> None:
        self._tools: dict[str, Tool] = {}
        for t in tools:
            self.add(t)

    def add(self, t: Tool) -> None:
        if t.name in self._tools:
            raise ValueError(f"工具重名: {t.name}")
        self._tools[t.name] = t

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def openai_defs(self) -> list[dict]:
        return [
            {"type": "function",
             "function": {"name": t.name, "description": t.description,
                          "parameters": t.parameters}}
            for t in self._tools.values()
        ]

    async def call(self, name: str, arguments: dict) -> str:
        t = self._tools.get(name)
        if t is None:
            raise KeyError(f"未知工具: {name}")
        arguments.pop("_raw", None)
        return await t.handler(**arguments)
