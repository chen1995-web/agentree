"""命令行入口：python -m agentree "任务描述"。"""
from __future__ import annotations

import argparse
import asyncio
import sys

from .agent import AgentConfig, run_agent
from .llm import LLMClient


def _parse(argv=None):
    p = argparse.ArgumentParser(
        prog="agentree",
        description="agentree — 能派生子智能体的极简智能体框架",
    )
    p.add_argument("task", nargs="*", help="任务描述（留空则进入交互输入）")
    p.add_argument("--model", help="模型名，默认取 AGENTREE_MODEL / 内置默认模型")
    p.add_argument("--max-depth", type=int, default=2, help="递归深度上限（默认 2）")
    p.add_argument("--max-steps", type=int, default=30, help="单智能体最大循环轮数（默认 30）")
    p.add_argument("--max-children", type=int, default=8, help="单智能体子智能体配额（默认 8）")
    p.add_argument("--trace", metavar="FILE", help="把运行轨迹追加写入 JSONL 文件")
    p.add_argument("--quiet", action="store_true", help="不在终端回显运行轨迹")
    return p.parse_args(argv)


def main(argv=None) -> int:
    args = _parse(argv)
    task = " ".join(args.task).strip()
    if not task:
        try:
            task = input("请输入任务: ").strip()
        except EOFError:
            task = ""
    if not task:
        print("任务为空，退出。", file=sys.stderr)
        return 1

    try:
        client = LLMClient(model=args.model)
    except RuntimeError as e:
        print(f"错误: {e}", file=sys.stderr)
        return 1

    config = AgentConfig(
        max_depth=args.max_depth,
        max_steps=args.max_steps,
        max_children=args.max_children,
        trace_echo=not args.quiet,
        trace_file=args.trace,
    )
    result = asyncio.run(run_agent(task, config, client=client))
    print("\n" + "─" * 60)
    print(result.output or "(无输出)")
    print("─" * 60)
    stats = (f"[agentree] run={result.run_id} steps={result.steps} "
             f"children={result.children_spawned} "
             f"tokens(in/out)={result.tokens_in}/{result.tokens_out}")
    if result.error:
        stats += f" error={result.error}"
    print(stats)
    return 0 if result.error is None else 2


if __name__ == "__main__":
    raise SystemExit(main())
