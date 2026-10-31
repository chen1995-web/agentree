"""agentree 测试套件：用假 LLM 客户端注入，全程无网络、无真实 API。

运行：python3 -m pytest tests/ -q -p no:asyncio
（本环境 pytest-asyncio 损坏，故所有 async 用例用 asyncio.run 包裹，不依赖插件。）
"""
from __future__ import annotations

import asyncio

import pytest

from agentree.agent import AgentConfig, run_agent, _clip, _spawn_one
from agentree.tools import Tool, ToolRegistry, tool
from agentree.tracer import Tracer
from agentree.team import (Inbox, Team, TeamAgent, _sanitize_plan, parse_plan)
from agentree.websearch import merge_results


# ---------------- 假客户端 + 构造辅助 ----------------

def resp(content="", tool_calls=None, tin=1, tout=1):
    return {"content": content, "tool_calls": tool_calls or [],
            "usage": {"in": tin, "out": tout}}


def tc(cid, name, args):
    return {"id": cid, "name": name, "arguments": args}


class FakeClient:
    """按队列依次返回响应，并记录每次 chat 调用的消息上下文。"""

    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = []  # [{"messages":..., "tools":...}]

    async def chat(self, messages, tools=None, temperature=0.7):
        self.calls.append({"messages": list(messages), "tools": tools})
        if not self._responses:
            return resp("(假客户端已无预置响应)")
        return self._responses.pop(0)

    async def aclose(self):
        pass


def run(coro):
    return asyncio.run(coro)


def quiet_tracer():
    return Tracer(echo=False)


# ---------------- 纯函数：_clip / merge_results ----------------

def test_clip_short_passthrough():
    assert _clip("short", 100) == "short"


def test_clip_truncates_with_marker():
    out = _clip("X" * 300, 100)
    assert out.startswith("X" * 100)
    assert "truncated" in out
    assert len(out) < 300


def test_merge_results_dedup_and_drop_nourl():
    rs = [{"url": "a", "title": "A"}, {"url": "b"}, {"url": "a", "title": "dup"},
          {"title": "no url"}]
    out = merge_results(rs, max_results=8)
    assert [r["url"] for r in out] == ["a", "b"]


def test_merge_results_respects_max():
    rs = [{"url": f"u{i}"} for i in range(10)]
    assert len(merge_results(rs, max_results=3)) == 3


# ---------------- 调度分析器：_sanitize_plan / parse_plan ----------------

def test_sanitize_plan_fallback_on_bad_input():
    assert _sanitize_plan(None, "t")["mode"] == "solo"
    assert _sanitize_plan({"mode": "weird"}, "t")["mode"] == "solo"
    # team 但没有成员 → 回退 solo
    assert _sanitize_plan({"mode": "team", "agents": []}, "t")["mode"] == "solo"


def test_sanitize_plan_normalizes_names():
    plan = _sanitize_plan({"mode": "team",
                           "agents": [{"name": "  Research/Agent  ", "description": "x", "task": "t"}]},
                          "t")
    assert plan["agents"][0]["name"] == "research-agent"


def test_sanitize_plan_dedup_names():
    plan = _sanitize_plan({"mode": "team", "agents": [
        {"name": "research-agent", "description": "a", "task": "t1"},
        {"name": "RESEARCH AGENT", "description": "b", "task": "t2"},
    ]}, "t")
    assert len(plan["agents"]) == 1


def test_sanitize_plan_caps_agents_and_tasks():
    plan = _sanitize_plan({"mode": "team",
                           "agents": [{"name": f"a{i}", "description": "d", "task": "t"} for i in range(10)],
                           "tasks": [{"subject": f"s{i}", "description": "d"} for i in range(20)]},
                          "t")
    assert len(plan["agents"]) == 4
    assert len(plan["tasks"]) == 8


def test_parse_plan_extracts_json_from_markdown():
    raw = '```json\n{"mode":"solo","reason":"简单","agents":[],"tasks":[]}\n```'
    assert parse_plan(raw)["mode"] == "solo"


def test_parse_plan_garbage_falls_back_solo():
    assert parse_plan("这不是 JSON")["mode"] == "solo"


# ---------------- 工具注册表 ----------------

def test_registry_duplicate_name_raises():
    async def h():
        return "x"
    t = Tool("f", "d", {"type": "object"}, h)
    reg = ToolRegistry(t)
    with pytest.raises(ValueError):
        reg.add(Tool("f", "d2", {"type": "object"}, h))


def test_registry_call_unknown_raises():
    async def _():
        reg = ToolRegistry()
        with pytest.raises(KeyError):
            await reg.call("nope", {})
    run(_())


def test_registry_openai_defs_shape():
    async def h():
        return "x"
    reg = ToolRegistry(Tool("f", "d", {"type": "object"}, h))
    defs = reg.openai_defs()
    assert defs[0]["type"] == "function"
    assert defs[0]["function"]["name"] == "f"


# ---------------- run_agent：基础循环 ----------------

def test_run_agent_simple_final_answer():
    async def _():
        cfg = AgentConfig(enable_web=False, max_depth=0)
        client = FakeClient([resp(content="答案")])
        return await run_agent("问题", cfg, client=client)
    result = run(_())
    assert result.output == "答案"
    assert result.steps == 1
    assert result.error is None
    assert result.children_spawned == 0


def test_run_agent_executes_tool_then_answers():
    @tool("add", "两数相加", {"type": "object",
                              "properties": {"a": {"type": "integer"}, "b": {"type": "integer"}},
                              "required": ["a", "b"]})
    async def add(a, b):
        return str(a + b)

    async def _():
        cfg = AgentConfig(tools=(add,), enable_web=False, max_depth=0)
        client = FakeClient([resp(tool_calls=[tc("c1", "add", {"a": 2, "b": 3})]),
                             resp(content="和是 5")])
        return await run_agent("算一下", cfg, client=client)
    result = run(_())
    assert result.output == "和是 5"
    # 第二次 chat 的消息里应含工具结果
    tool_msgs = [m for m in client_calls(result) if m.get("role") == "tool"]
    assert tool_msgs and tool_msgs[0]["content"] == "5"


def client_calls(result):
    # run_agent 返回 messages；从里面找 tool 角色
    return result.messages


def test_run_agent_tool_error_backfilled_and_recovered():
    @tool("boom", "必失败", {"type": "object", "properties": {}, "required": []})
    async def boom():
        raise ValueError("kaboom")

    async def _():
        cfg = AgentConfig(tools=(boom,), enable_web=False, max_depth=0)
        client = FakeClient([resp(tool_calls=[tc("c1", "boom", {})]), resp(content="done")])
        return await run_agent("t", cfg, client=client)
    result = run(_())
    tool_msgs = [m for m in result.messages if m.get("role") == "tool"]
    assert "TOOL_ERROR" in tool_msgs[0]["content"]
    assert "kaboom" in tool_msgs[0]["content"]
    assert result.output == "done"  # 错误回填后模型仍能收尾


def test_run_agent_tool_result_clipped():
    @tool("big", "返回长串", {"type": "object", "properties": {}, "required": []})
    async def big():
        return "X" * 500

    async def _():
        cfg = AgentConfig(tools=(big,), enable_web=False, max_depth=0,
                          max_tool_result_chars=100)
        client = FakeClient([resp(tool_calls=[tc("c1", "big", {})]), resp(content="done")])
        return await run_agent("t", cfg, client=client)
    result = run(_())
    tool_msgs = [m for m in result.messages if m.get("role") == "tool"]
    assert len(tool_msgs[0]["content"]) < 200
    assert "truncated" in tool_msgs[0]["content"]


def test_run_agent_max_steps_triggers_error():
    class LoopClient:
        async def chat(self, messages, tools=None, temperature=0.7):
            return resp(tool_calls=[tc("c", "noop", {})])  # 未知工具 → 错误回填后继续
        async def aclose(self):
            pass

    async def _():
        cfg = AgentConfig(enable_web=False, max_depth=0, max_steps=3)
        return await run_agent("t", cfg, client=LoopClient())
    result = run(_())
    assert result.error and "max steps" in result.error


# ---------------- run_agent：递归派生 / 上下文隔离 / 配额 ----------------

def test_spawn_subagent_context_isolation():
    """子智能体看不到父级上下文，父级只收到子级最终输出。"""
    async def _():
        cfg = AgentConfig(enable_web=False)  # max_depth=2 默认
        client = FakeClient([
            resp(tool_calls=[tc("c1", "spawn_subagent", {"task": "CHILD_TASK"})], tin=10, tout=5),
            resp(content="CHILD_FINAL", tin=7, tout=3),   # 子级第 1 步即最终回答
            resp(content="PARENT_FINAL", tin=4, tout=2),  # 父级第 2 步
        ])
        return await run_agent("PARENT_TASK", cfg, client=client), client
    result, client = run(_())

    assert result.output == "PARENT_FINAL"
    assert result.children_spawned == 1
    # 父级第 1 步上下文含父任务
    parent_msgs = client.calls[0]["messages"]
    assert any("PARENT_TASK" in m.get("content", "") for m in parent_msgs)
    # 子级上下文：system + CHILD_TASK，且不含父任务
    child_msgs = client.calls[1]["messages"]
    assert child_msgs[0]["role"] == "system"
    assert child_msgs[1]["content"] == "CHILD_TASK"
    assert not any("PARENT_TASK" in m.get("content", "") for m in child_msgs)
    # 父级第 2 步只收到子级最终输出，不含子级中间上下文
    parent_step2 = client.calls[2]["messages"]
    assert any(m.get("content") == "CHILD_FINAL" for m in parent_step2)
    assert not any("CHILD_TASK" in m.get("content", "") for m in parent_step2)


def test_spawn_parallel_fanout_order_and_limit():
    async def _():
        cfg = AgentConfig(enable_web=False, max_children=2)
        client = FakeClient([
            resp(tool_calls=[tc("c1", "spawn_parallel",
                                {"tasks": ["T1", "T2", "T3", "T4"]})], tin=10, tout=5),
            resp(content="C1", tin=1, tout=1),   # T1 子级
            resp(content="C2", tin=1, tout=1),   # T2 子级
            resp(content="汇总", tin=2, tout=2),  # 父级收尾
        ])
        return await run_agent("并行", cfg, client=client), client
    result, client = run(_())
    assert result.output == "汇总"
    assert result.children_spawned == 2  # max_children=2，只派前 2 个
    # 父级收尾消息含两个子结果，且提示跳过
    final_msgs = client.calls[3]["messages"]
    joined = "\n".join(m.get("content", "") for m in final_msgs)
    assert "C1" in joined and "C2" in joined
    assert "per-call limit" in joined or "not dispatched" in joined


def test_spawn_depth_limit():
    async def _():
        cfg = AgentConfig(max_depth=0, enable_web=False)
        state = {"children": 0, "tin": 0, "tout": 0}
        return await _spawn_one("t", cfg, FakeClient([resp("x")]), depth=0,
                                run_id="r", state=state, tracer=quiet_tracer())
    out = run(_())
    assert out.startswith("ERROR_DEPTH_LIMIT")


def test_spawn_child_limit():
    async def _():
        cfg = AgentConfig(max_depth=2, max_children=1, enable_web=False)
        state = {"children": 1, "tin": 0, "tout": 0}  # 已达配额
        return await _spawn_one("t", cfg, FakeClient([resp("x")]), depth=0,
                                run_id="r", state=state, tracer=quiet_tracer())
    out = run(_())
    assert out.startswith("ERROR_CHILD_LIMIT")


def test_token_aggregation_includes_subtree():
    async def _():
        cfg = AgentConfig(enable_web=False)
        client = FakeClient([
            resp(tool_calls=[tc("c1", "spawn_subagent", {"task": "子"})], tin=10, tout=5),
            resp(content="子完成", tin=7, tout=3),
            resp(content="父完成", tin=4, tout=2),
        ])
        return await run_agent("父", cfg, client=client)
    result = run(_())
    assert result.output == "父完成"
    assert result.tokens_in == 10 + 7 + 4
    assert result.tokens_out == 5 + 3 + 2


# ---------------- 收件箱：步边界注入 ----------------

def test_inbox_injected_before_first_llm_call():
    async def _():
        inbox = Inbox()
        inbox.push("lead", "补充：用中文回答")
        cfg = AgentConfig(enable_web=False, max_depth=0)
        client = FakeClient([resp(content="ok")])
        result = await run_agent("主任务", cfg, client=client, inbox=inbox)
        assert result.output == "ok"
        msgs = client.calls[0]["messages"]
        injected = [m for m in msgs if "补充：用中文回答" in m.get("content", "")]
        assert injected, "收件箱消息应在首个 LLM 调用前注入"
        assert "[NEW MESSAGE] lead" in injected[0]["content"]
        assert any("主任务" in m.get("content", "") for m in msgs)
    run(_())


# ---------------- 团队任务板：CAS / 依赖 / 花名册 ----------------

def make_team():
    team = Team(emit=lambda *a, **k: None, client=FakeClient([]))
    lead = TeamAgent(name="lead", description="调度", is_lead=True)
    tools = {t.name: t for t in team.tools_for(lead)}
    return team, tools


def test_team_task_cas_lifecycle():
    async def _():
        team, tools = make_team()
        await tools["team_task_create"].handler("任务A", "描述A")
        tid = list(team.tasks.keys())[0]
        assert team.tasks[tid].revision == 1
        # 错误修订号
        r = await tools["team_task_update"].handler(tid, "claim", 99, owner="lead")
        assert "stale revision" in r
        assert team.tasks[tid].status == "pending"
        # 正确修订号 claim
        r = await tools["team_task_update"].handler(tid, "claim", 1, owner="lead")
        assert "claim" in r
        assert team.tasks[tid].status == "in_progress"
        assert team.tasks[tid].owner == "lead"
        assert team.tasks[tid].revision == 2
        # complete
        await tools["team_task_update"].handler(tid, "complete", 2)
        assert team.tasks[tid].status == "completed"
        # 已完成不能再 claim
        r = await tools["team_task_update"].handler(tid, "claim", 3, owner="lead")
        assert "already completed" in r
    run(_())


def test_team_task_blocked_by_gating():
    async def _():
        team, tools = make_team()
        await tools["team_task_create"].handler("A", "da")
        tidA = list(team.tasks.keys())[0]
        await tools["team_task_create"].handler("B", "db", blocked_by=[tidA])
        tidB = [k for k in team.tasks if k != tidA][0]
        # B 依赖未完成 → 不能认领
        r = await tools["team_task_update"].handler(tidB, "claim", team.tasks[tidB].revision,
                                                     owner="lead")
        assert "dependencies not complete" in r
        # 完成 A 后 B 可认领
        await tools["team_task_update"].handler(tidA, "complete", team.tasks[tidA].revision)
        r = await tools["team_task_update"].handler(tidB, "claim", team.tasks[tidB].revision,
                                                     owner="lead")
        assert "claim" in r
        assert team.tasks[tidB].status == "in_progress"
    run(_())


def test_team_task_list_and_get():
    async def _():
        team, tools = make_team()
        await tools["team_task_create"].handler("A", "da")
        tid = list(team.tasks.keys())[0]
        listing = await tools["team_task_list"].handler("")
        assert "A" in listing and "pending" in listing
        detail = await tools["team_task_get"].handler(tid)
        assert "任务A" in detail or "A" in detail
    run(_())


def test_team_roster_summary():
    team = Team(emit=lambda *a, **k: None, client=FakeClient([]))
    team.agents["lead"] = TeamAgent(name="lead", description="调度", is_lead=True)
    team.agents["worker"] = TeamAgent(name="worker", description="干活")
    roster = team.roster_summary()
    names = {r["name"] for r in roster}
    assert names == {"lead", "worker"}
    assert roster[0]["is_lead"] is True
