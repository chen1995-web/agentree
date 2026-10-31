"""DSH 风格的多智能体团队：常驻 teammate + 消息收件箱 + 共享任务板。

与一次性 spawn_subagent 的区别（对齐 DeepSeek Harness 的 Agent Teams 语义）：
- teammate 常驻：按名字创建，跨多轮持续存在，收件箱里的消息唤醒/注入新回合；
- 消息传递：send_message 投递到目标收件箱；对方空闲则唤醒新回合，运行中则在
  下一个步边界注入（见 agent.run_agent 的 inbox 钩子）；
- 共享任务板：team_task_* 工具，带修订号 CAS（防并发互踩）与 blocked_by 依赖；
- Lead 协调：lead 负责拆解、建队、跟进，收尾前 wait_agents 等全员空闲。
"""
from __future__ import annotations

import asyncio
import json
import re
import time
from dataclasses import dataclass, field
from uuid import uuid4

from .agent import AgentConfig, run_agent
from .tools import Tool
from .tracer import Tracer

LEAD_PROMPT = (
    "你是团队 Lead，负责把用户目标拆解并协调 teammate 完成。\n"
    "协作规则：\n"
    "1. 用 spawn_teammate 创建常驻 teammate 并立刻交给它首个任务（name 用小写英文连字符，全队唯一）；"
    "简单的活不必建队，自己做完即可。\n"
    "2. 用 send_message 与 teammate 沟通：补充上下文、催促进度、下达新指令。消息必须自包含。\n"
    "3. 用 team_task_create 在共享任务板登记工作项，teammate 认领完成；依赖用 blocked_by 表达。\n"
    "4. 收尾前用 wait_agents 等所有 teammate 空闲，确认没有遗留工作，再输出最终总结作为最后回答。\n"
    "5. list_agents 可随时查看花名册与各自状态。联网查资料用 web_search（一次多条查询词）→ "
    "web_fetch 读原文，引用必须带 markdown 来源链接。"
)

TEAMMATE_PROMPT = (
    "你是团队中的常驻 teammate。收件箱里的每条消息就是当前要处理的任务，直接执行，"
    "并在最终回答里给出完整结果。\n"
    "协作规则：\n"
    "1. 用 team_task_list/team_task_get 了解任务板；动手前先 team_task_update(action=claim) 认领"
    "（需要 expected_revision，先 list 拿最新修订号）。\n"
    "2. 完成后 team_task_update(action=complete)，并用 send_message 向 lead 汇报结果。\n"
    "3. 缺上下文就 send_message 问 lead；有独立子任务可派 spawn_subagent/spawn_parallel。"
    "联网查资料用 web_search → web_fetch，引用必须带 markdown 来源链接。"
)

# ---------------- LLM 调度分析器：先判断 solo 还是 team、派几个人 ----------------

_PLAN_PROMPT = (
    "你是智能体团队的调度分析器。分析用户任务，判断由单个智能体直接完成更合适，"
    "还是组建小团队协作完成，并给出组建方案。\n"
    "判断标准：\n"
    "- 任务单一、连贯、没有可以并行拆分的独立子任务（如：写一段话、回答一个问题、总结一篇文章）"
    "→ solo，一个智能体直接完成即可\n"
    "- 任务包含多个相互独立的子任务（如：多主题调研、调研+写作、批量处理多个对象）→ team，"
    "成员数按独立子任务数定（1-4 个，宁少勿多，能两人完成就不要三人）\n"
    "- 拿不准就选 solo（团队协作有沟通成本，只有并行收益明显时才组队）\n\n"
    "只输出一个 JSON 对象，不要 markdown 代码块，不要任何多余文字：\n"
    '{"mode": "solo 或 team", "reason": "一句话理由", '
    '"agents": [{"name": "小写英文-连字符", "description": "一句话职责", "task": "给该成员的首个自包含任务"}], '
    '"tasks": [{"subject": "任务板标题", "description": "任务详情"}]}\n'
    "team 模式时 agents 必填（1-4 个）；solo 模式时 agents 与 tasks 都是空数组。\n\n"
    "用户任务："
)


def _sanitize_plan(raw_plan, task: str) -> dict:
    """校验/清洗 LLM 给出的计划；任何不合法都回退 solo。"""
    fallback = {"mode": "solo", "reason": "Dispatch unavailable; falling back to single agent",
                "agents": [], "tasks": []}
    if not isinstance(raw_plan, dict):
        return fallback
    mode = raw_plan.get("mode")
    if mode not in ("solo", "team"):
        return fallback

    agents, seen = [], set()
    for a in (raw_plan.get("agents") or [])[:4]:
        if not isinstance(a, dict):
            continue
        name = re.sub(r"[^a-z0-9-]+", "-", str(a.get("name") or "").lower()).strip("-")[:31]
        if not name or name in seen:
            continue
        seen.add(name)
        desc = str(a.get("description") or name)
        t = str(a.get("task") or "").strip() or desc
        agents.append({"name": name, "description": desc, "task": t})

    tasks = []
    for t in (raw_plan.get("tasks") or [])[:8]:
        if isinstance(t, dict) and str(t.get("subject") or "").strip():
            tasks.append({"subject": str(t["subject"])[:120],
                          "description": str(t.get("description") or "")[:800]})

    if mode == "team" and not agents:
        return fallback
    return {"mode": mode,
            "reason": str(raw_plan.get("reason") or "")[:200],
            "agents": agents, "tasks": tasks}


def parse_plan(raw: str, task: str = "") -> dict:
    """从 LLM 输出中稳健地抠出计划 JSON；失败一律回退 solo。"""
    try:
        text = re.sub(r"```(?:json)?", "", str(raw or "")).strip()
        m = re.search(r"\{.*\}", text, re.S)
        if not m:
            return _sanitize_plan(None, task)
        raw_plan = json.loads(m.group(0))
        plan = _sanitize_plan(raw_plan, task)
        if not plan.get("reason"):
            plan["reason"] = "（模型未给出理由）"
        return plan
    except Exception:
        return _sanitize_plan(None, task)


@dataclass
class Inbox:
    items: list = field(default_factory=list)

    def push(self, sender: str, content: str) -> None:
        self.items.append({"sender": sender, "content": content, "t": time.time()})

    def take(self) -> list:
        out, self.items = self.items, []
        return out

    def __bool__(self) -> bool:
        return bool(self.items)


@dataclass
class TeamAgent:
    name: str
    description: str
    is_lead: bool = False
    status: str = "idle"  # idle | running（scheduled 为内部防重复调度的瞬态）
    inbox: Inbox = field(default_factory=Inbox)
    last_output: str = ""
    turns: int = 0
    history: list = field(default_factory=list)  # 跨轮会话历史（常驻成员的记忆）
    handle: object = None


@dataclass
class TeamTask:
    id: str
    subject: str
    description: str
    status: str = "pending"  # pending | in_progress | completed
    owner: str | None = None
    blocked_by: list = field(default_factory=list)
    revision: int = 1
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    def summary(self) -> dict:
        return {"id": self.id, "subject": self.subject, "description": self.description,
                "status": self.status, "owner": self.owner, "blocked_by": self.blocked_by,
                "revision": self.revision}


class Team:
    """一次团队运行：lead + 若干常驻 teammate + 一块共享任务板。"""

    def __init__(self, emit, client=None):
        self.emit = emit  # emit(kind, **data)
        self.client = client
        self.agents: dict[str, TeamAgent] = {}
        self.tasks: dict[str, TeamTask] = {}
        self._cancelled = False

    # ---------- 生命周期 ----------

    async def run(self, task: str) -> str:
        # ① LLM 调度分析：solo 还是 team、派几个人、怎么分工
        plan = await self._make_plan(task)
        self.emit("plan", plan=plan)

        lead = TeamAgent(name="lead", is_lead=True,
                         description=(f"Dispatch: {plan['reason']}" if plan["mode"] == "team"
                                      else "Dispatch: single agent will complete directly"))
        self.agents["lead"] = lead
        self.emit("agent_upsert", agent=self._roster(lead))

        # ② solo：单智能体直接完成（保留派临时子智能体的能力，不带团队协作工具）
        if plan["mode"] != "team" or not plan["agents"]:
            await self._turn(lead, text=task, team_tools=False, config=AgentConfig())
            return lead.last_output

        # ③ team：物化计划——建成员、预填任务板，再让 lead 跟进协调
        for a in plan["agents"]:
            mate = TeamAgent(name=a["name"], description=a["description"])
            self.agents[mate.name] = mate
            self.emit("agent_upsert", agent=self._roster(mate))
            mate.inbox.push("lead", a["task"])
        for t in plan["tasks"]:
            item = TeamTask(id="t" + uuid4().hex[:6], subject=t["subject"],
                            description=t["description"])
            self.tasks[item.id] = item
            self.emit("task_created", task=item.summary())
        for a in plan["agents"]:
            self._schedule(self.agents[a["name"]])

        lead_text = (
            f"用户目标：{task}\n\n"
            f"调度分析已完成并落地：{plan['reason']}\n"
            "已创建的成员与分工："
            + "；".join(f"{a['name']}（{a['description']}）" for a in plan["agents"])
            + "。\n各成员已收到首个任务（在各自收件箱），共享任务板已按计划预填。\n"
            "你的职责是跟进协调：用 send_message 补充上下文、查漏催办，用 team_task_list 核对进度，"
            "发现分工缺口再 spawn_teammate 补位；全部完成后 wait_agents，"
            "汇总各成员产出并输出团队总结。不要重复成员已完成的工作。")
        await self._turn(lead, text=lead_text)

        # ④ lead 收尾前持续唤醒有消息的成员，直到全员空闲且收件箱清空
        deadline = time.time() + 900
        while time.time() < deadline:
            await asyncio.sleep(1.0)
            for a in list(self.agents.values()):
                if a.status == "idle" and a.inbox:
                    self._schedule(a)
            if all(a.status == "idle" and not a.inbox for a in self.agents.values()):
                break
        return lead.last_output

    async def _make_plan(self, task: str) -> dict:
        """用同一个 LLM 做调度分析：solo / team + 分工计划（任何失败回退 solo）。"""
        config = AgentConfig(system_prompt=_PLAN_PROMPT, temperature=0.2,
                             max_depth=0, max_steps=1, enable_web=False)
        try:
            result = await run_agent(task, config, client=self.client,
                                     tracer=self._tracer_for("planner"))
            return parse_plan(result.output, task)
        except Exception as e:
            return {"mode": "solo",
                    "reason": f"Dispatch failed ({type(e).__name__}); falling back to single agent",
                    "agents": [], "tasks": []}

    def cancel(self) -> None:
        self._cancelled = True
        for a in self.agents.values():
            if a.handle is not None and hasattr(a.handle, "done") and not a.handle.done():
                a.handle.cancel()

    def _schedule(self, agent: TeamAgent) -> None:
        if self._cancelled or agent.status != "idle":
            return  # 运行中：消息会在本轮步边界注入，或轮次结束后再调度
        agent.status = "scheduled"  # 防重复调度的瞬态占位
        agent.handle = asyncio.create_task(self._turn(agent))

    async def _turn(self, agent: TeamAgent, text: str | None = None,
                    team_tools: bool = True, config: AgentConfig | None = None) -> None:
        if text is None:
            pending = agent.inbox.take()
            if not pending:
                return
            text = "\n\n".join(f"【来自 {m['sender']}】{m['content']}" for m in pending)
        agent.status = "running"
        agent.handle = asyncio.current_task()
        self.emit("agent_status", agent=agent.name, status="running")
        cfg = config or AgentConfig(system_prompt=LEAD_PROMPT if agent.is_lead else TEAMMATE_PROMPT,
                                    max_depth=1)
        try:
            result = await run_agent(text, cfg, client=self.client,
                                     tracer=self._tracer_for(agent.name),
                                     extra_tools=self.tools_for(agent) if team_tools else (),
                                     inbox=agent.inbox if team_tools else None,
                                     history=agent.history or None)
            agent.turns += 1
            # 持久化会话记忆：下一轮在同一上下文上续接（截断防膨胀）
            if result.messages:
                agent.history = result.messages[-60:]
            if result.output:
                agent.last_output = result.output
            self.emit("agent_final", agent=agent.name, output=result.output, error=result.error)
        except asyncio.CancelledError:
            raise
        except Exception as e:  # 回合失败不能让成员卡死在 running
            self.emit("agent_final", agent=agent.name, output="", error=f"{type(e).__name__}: {e}")
        finally:
            agent.status = "idle"
            self.emit("agent_status", agent=agent.name, status="idle")
            if agent.inbox:
                self._schedule(agent)

    def _tracer_for(self, name: str):
        """把该成员每个回合的标准事件（llm/tool_call/...）以 turn_* 前缀转发到团队事件流。"""

        def sink(rec: dict) -> None:
            rec = dict(rec)
            rec["agent"] = name
            self.emit("turn_" + str(rec.get("kind", "event")), **rec)

        return Tracer(echo=False, sink=sink)

    # ---------- 花名册 / 任务板 ----------

    def _roster(self, a: TeamAgent) -> dict:
        return {"name": a.name, "description": a.description, "is_lead": a.is_lead,
                "status": a.status if a.status != "scheduled" else "running",
                "turns": a.turns, "inbox": len(a.inbox.items)}

    def roster_summary(self) -> list:
        return [self._roster(a) for a in self.agents.values()]

    def _task_ready(self, t: TeamTask) -> bool:
        return all(b in self.tasks and self.tasks[b].status == "completed"
                   for b in t.blocked_by)

    # ---------- 团队工具（闭包绑定当前发言成员） ----------

    def tools_for(self, agent: TeamAgent) -> tuple:
        me = agent.name

        async def send_message(target: str, message: str) -> str:
            mate = self.agents.get(target)
            if not mate:
                names = ", ".join(self.agents) or "(空)"
                return f"ERROR: 不存在 teammate「{target}」，当前花名册：{names}"
            mate.inbox.push(me, message)
            self.emit("message_sent", **{"from": me, "to": target, "preview": message[:150]})
            if mate.status == "idle":
                self._schedule(mate)
                return f"已投递给 {target}（对方空闲，已唤醒处理）"
            return f"已投递给 {target}（对方执行中，将在下一个步边界收到）"

        async def spawn_teammate(name: str, description: str, task: str) -> str:
            name = name.strip().lower()
            if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,30}", name):
                return "ERROR: name 需为小写字母/数字/连字符，1-31 位"
            if name in self.agents:
                return f"ERROR: teammate「{name}」已存在，直接 send_message 即可"
            mate = TeamAgent(name=name, description=description)
            self.agents[name] = mate
            self.emit("agent_upsert", agent=self._roster(mate))
            mate.inbox.push(me, task)
            self._schedule(mate)
            return f"已创建 teammate「{name}」并交付首个任务"

        async def team_task_create(subject: str, description: str, blocked_by=None) -> str:
            blocked_by = [b for b in (blocked_by or []) if b in self.tasks]
            task = TeamTask(id="t" + uuid4().hex[:6], subject=subject, description=description,
                            blocked_by=blocked_by)
            self.tasks[task.id] = task
            self.emit("task_created", task=task.summary())
            note = f" (deps: {', '.join(blocked_by)})" if blocked_by else ""
            return f"Created task {task.id}: {subject}{note}"

        async def team_task_list(status: str = "") -> str:
            rows = [t for t in self.tasks.values() if not status or t.status == status]
            if not rows:
                return "Task board is empty"
            return "\n".join(
                f"{t.id} [{t.status}] r{t.revision} owner={t.owner or '-'} "
                f"blocked_by={','.join(t.blocked_by) or '-'} | {t.subject}"
                for t in rows)

        async def team_task_get(task_id: str) -> str:
            t = self.tasks.get(task_id)
            return json.dumps(t.summary(), ensure_ascii=False) if t else f"ERROR: no task {task_id}"

        async def team_task_update(task_id: str, action: str, expected_revision: int,
                                   owner: str = "", subject: str = "", description: str = "",
                                   blocked_by=None) -> str:
            t = self.tasks.get(task_id)
            if not t:
                return f"ERROR: no task {task_id}"
            if int(expected_revision) != t.revision:
                return (f"ERROR: stale revision (task is at r{t.revision}, you submitted r{expected_revision}); "
                        "call team_task_list to get the latest revision and retry")
            if action == "claim":
                if t.status == "completed":
                    return f"ERROR: task {task_id} is already completed; cannot claim"
                if not self._task_ready(t):
                    waiting = [b for b in t.blocked_by
                               if b in self.tasks and self.tasks[b].status != "completed"]
                    return f"ERROR: dependencies not complete ({', '.join(waiting)}); cannot claim yet"
                t.status = "in_progress"
                t.owner = owner or me
            elif action == "complete":
                t.status = "completed"
            elif action == "reopen":
                t.status = "pending"
                t.owner = None
            elif action == "edit":
                if subject:
                    t.subject = subject
                if description:
                    t.description = description
                if blocked_by is not None:
                    t.blocked_by = [b for b in blocked_by if b in self.tasks and b != task_id]
            else:
                return f"ERROR: unknown action {action} (use claim/complete/reopen/edit)"
            t.revision += 1
            t.updated_at = time.time()
            self.emit("task_updated", task=t.summary())
            return f"Task {task_id} updated via {action} (new revision r{t.revision}, owner={t.owner or '-'})"

        async def list_agents() -> str:
            return "\n".join(
                f"{a.name}{'（lead）' if a.is_lead else ''} [{self._roster(a)['status']}] "
                f"turns={a.turns} inbox={len(a.inbox.items)} — {a.description}"
                for a in self.agents.values())

        async def wait_agents(names=None, timeout: float = 600) -> str:
            targets = [self.agents[n] for n in (names or list(self.agents)) if n in self.agents]
            if not targets:
                return "Roster is empty"
            deadline = time.time() + min(float(timeout), 900)
            busy = []
            while time.time() < deadline:
                busy = [a.name for a in targets if a.status != "idle" or a.inbox]
                if not busy:
                    return "所有相关 teammate 均已空闲"
                await asyncio.sleep(1.0)
            return f"等待超时，仍在忙碌：{', '.join(busy)}。可继续等待或直接收尾。"

        return (
            Tool(name="send_message",
                 description="给另一个 teammate 发消息。对方空闲会立刻被唤醒新回合；"
                             "运行中则在下一个步边界收到。消息必须自包含。",
                 parameters={"type": "object",
                             "properties": {"target": {"type": "string", "description": "对方名字"},
                                            "message": {"type": "string", "description": "自包含的消息"}},
                             "required": ["target", "message"]},
                 handler=send_message),
            Tool(name="spawn_teammate",
                 description="创建一个常驻 teammate 并立刻交付首个任务。全队名字唯一。",
                 parameters={"type": "object",
                             "properties": {"name": {"type": "string", "description": "小写英文/数字/连字符"},
                                            "description": {"type": "string", "description": "一句话职责"},
                                            "task": {"type": "string", "description": "首个任务（自包含）"}},
                             "required": ["name", "description", "task"]},
                 handler=spawn_teammate),
            Tool(name="team_task_create",
                 description="在共享任务板上创建任务项。",
                 parameters={"type": "object",
                             "properties": {"subject": {"type": "string"},
                                            "description": {"type": "string"},
                                            "blocked_by": {"type": "array", "items": {"type": "string"},
                                                           "description": "依赖的任务 id 列表"}},
                             "required": ["subject", "description"]},
                 handler=team_task_create),
            Tool(name="team_task_list",
                 description="列出任务板（可按状态过滤），返回含修订号，修改前必须先取最新修订号。",
                 parameters={"type": "object",
                             "properties": {"status": {"type": "string",
                                                       "description": "pending/in_progress/completed，留空全部"}}},
                 handler=team_task_list),
            Tool(name="team_task_get",
                 description="查看单个任务详情。",
                 parameters={"type": "object",
                             "properties": {"task_id": {"type": "string"}}, "required": ["task_id"]},
                 handler=team_task_get),
            Tool(name="team_task_update",
                 description="更新任务：claim（认领，需依赖已完成）/ complete / reopen / edit。"
                             "必须带最新 expected_revision（CAS 防互踩）。",
                 parameters={"type": "object",
                             "properties": {"task_id": {"type": "string"},
                                            "action": {"type": "string",
                                                       "enum": ["claim", "complete", "reopen", "edit"]},
                                            "expected_revision": {"type": "integer"},
                                            "owner": {"type": "string"},
                                            "subject": {"type": "string"},
                                            "description": {"type": "string"},
                                            "blocked_by": {"type": "array", "items": {"type": "string"}}},
                             "required": ["task_id", "action", "expected_revision"]},
                 handler=team_task_update),
            Tool(name="list_agents",
                 description="查看团队花名册：名字、状态、回合数、收件箱堆积。",
                 parameters={"type": "object", "properties": {}},
                 handler=list_agents),
            Tool(name="wait_agents",
                 description="等待 teammate 全部空闲（收尾前用），可指定名字与超时秒数。",
                 parameters={"type": "object",
                             "properties": {"names": {"type": "array", "items": {"type": "string"}},
                                            "timeout": {"type": "number", "description": "秒，默认 600"}},
                             "required": []},
                 handler=wait_agents),
        )
