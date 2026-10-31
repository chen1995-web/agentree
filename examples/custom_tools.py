"""自定义工具：注册 read_file / list_dir，批量摘要一个目录下的 Markdown 文件。

运行: python3 examples/custom_tools.py [目录]
"""
from __future__ import annotations

import asyncio
import sys

from agentree import AgentConfig, run_agent
from agentree.builtins import list_dir, read_file


async def main() -> None:
    directory = sys.argv[1] if len(sys.argv) > 1 else "."
    task = (
        f"1) 用 list_dir 查看 {directory} 目录下有哪些文件；\n"
        f"2) 对其中每个 Markdown(.md) 文件，派一个子智能体用 read_file 读取并写出一句话摘要；\n"
        f"3) 汇总所有摘要返回。若没有 .md 文件，直接说明。"
    )
    config = AgentConfig(tools=(read_file, list_dir), max_depth=2)
    result = await run_agent(task, config)
    print("\n摘要汇总:\n" + result.output)
    print(f"\n[统计] run={result.run_id} steps={result.steps} "
          f"children={result.children_spawned} "
          f"tokens(in/out)={result.tokens_in}/{result.tokens_out}")


if __name__ == "__main__":
    asyncio.run(main())
