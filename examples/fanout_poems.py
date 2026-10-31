"""并发 fan-out：主智能体把 3 个写诗任务并行派给子智能体，再亲自汇总。

运行: python3 examples/fanout_poems.py
"""
from __future__ import annotations

import asyncio

from agentree import AgentConfig, run_agent

TASK = (
    "请用 spawn_parallel 一次性派 3 个子智能体，分别写一首关于「春天」「夏天」「秋天」的"
    "五言绝句。等全部返回后，由你补写一首「冬天」，并按春夏秋冬顺序合并成《四季》组诗"
    "作为最终回答。"
)


async def main() -> None:
    result = await run_agent(TASK, AgentConfig(max_depth=2))
    print("\n最终组诗:\n" + result.output)
    print(f"\n[统计] run={result.run_id} steps={result.steps} "
          f"children={result.children_spawned} "
          f"tokens(in/out)={result.tokens_in}/{result.tokens_out}")


if __name__ == "__main__":
    asyncio.run(main())
