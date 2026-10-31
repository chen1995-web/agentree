"""递归派生：父级 -> 大纲子智能体 -> 段落子智能体，最后由父级成文。

运行: python3 examples/recursive_writing.py
"""
from __future__ import annotations

import asyncio

from agentree import AgentConfig, run_agent

TASK = (
    "撰写一篇约 300 字的短文《为什么需要子智能体》，步骤：\n"
    "1) 先用 spawn_subagent 派一个子智能体，产出 3 个论点提纲；\n"
    "2) 再用 spawn_parallel 为每个论点各派一个子智能体，展开成 80 字左右的段落；\n"
    "3) 由你把段落串成连贯短文返回。"
)


async def main() -> None:
    result = await run_agent(TASK, AgentConfig(max_depth=2))
    print("\n短文:\n" + result.output)
    print(f"\n[统计] run={result.run_id} steps={result.steps} "
          f"children={result.children_spawned} "
          f"tokens(in/out)={result.tokens_in}/{result.tokens_out}")


if __name__ == "__main__":
    asyncio.run(main())
