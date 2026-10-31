"""agentree — 一个能派生子智能体的极简智能体框架。

核心思想：子智能体 = spawn 工具的执行器里递归跑同一个 Agent 主循环，
用全新上下文，把任务描述喂进去，把最终回答作为工具结果返回给父级。
"""
from __future__ import annotations

from .agent import DEFAULT_SYSTEM_PROMPT, AgentConfig, AgentResult, run_agent
from .llm import LLMClient
from .tools import Tool, ToolRegistry, tool
from .tracer import Tracer

__version__ = "0.1.0"

__all__ = [
    "run_agent",
    "AgentConfig",
    "AgentResult",
    "DEFAULT_SYSTEM_PROMPT",
    "Tool",
    "ToolRegistry",
    "tool",
    "LLMClient",
    "Tracer",
    "__version__",
]
