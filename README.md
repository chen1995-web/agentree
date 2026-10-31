# Agentree — a minimal multi-agent framework that can spawn sub-agents

A multi-agent orchestration framework written in **pure Python** (FastAPI + a framework-free Agent loop).
Core idea: **a sub-agent = the spawn-tool executor recursively running the same Agent loop**. A parent
only sees a child's final output; all intermediate work stays in the child's context (context isolation),
so the parent's context never grows with recursion depth.

> Positioning: the **main course** of my portfolio. Not a demo — a genuinely runnable, extensible,
> tested framework: recursive spawning, concurrent fan-out, live agent-tree observability, and
> DSH-style persistent team collaboration, with **zero third-party agent-framework dependencies**
> (only the OpenAI-compatible protocol).

---

## Why it holds up

| Capability | What it does |
|------|------|
| **Recursive spawning** | `spawn_subagent` / `spawn_parallel` let an agent break a task apart and delegate; children can spawn further, forming an agent tree |
| **Context isolation** | A child gets a fresh context; the parent receives only the final answer — the key design for controlling token blow-up on long tasks |
| **Three safety limits** | Depth (`max_depth`), steps (`max_steps`), child quota (`max_children`) — hitting any one degrades gracefully and returns an error |
| **Tool-result truncation** | Child intermediate artifacts are clipped to `max_tool_result_chars` before being fed back, protecting the parent context |
| **Persistent team collaboration** | Lead + persistent teammates + inbox (messages injected at step boundaries) + a shared task board (CAS revision + `blocked_by` dependencies) — mirrors DSH Agent Teams semantics |
| **LLM dispatch analysis** | The same LLM first decides solo vs. team, how many agents, and the division of labor; output is strictly sanitized, and any invalid input falls back to solo |
| **Live observability** | SSE event stream (`run_start / llm / tool_call / tool_result / run_end`) + a frontend that renders the agent tree — every step is visible |
| **Zero framework dependency** | The Agent loop does not depend on LangChain / AutoGen et al.; the LLM layer is just an OpenAI-compatible async client |

---

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│  Web frontend (Vue3 + Element Plus)  ── SSE ──►  FastAPI      │
│  agent tree / event stream / roster / task board   (server.py)│
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
        ┌────────────────────────────────────────────────────┐
        │  Team (team.py): lead + persistent teammates + board │
        │  ├─ LLM dispatch analysis (solo / team, 1-4 agents) │
        │  ├─ spawn_teammate / send_message / wait_agents     │
        │  └─ team_task_* (CAS revision + blocked_by)         │
        └───────────────────────┬────────────────────────────┘
                                ▼
        ┌────────────────────────────────────────────────────┐
        │  Agent loop (agent.py): run_agent recursion         │
        │  ├─ Tool registry (tools.py): JSON Schema + async fn│
        │  ├─ spawn_subagent / spawn_parallel (recursive)     │
        │  ├─ three limits + tool-result truncation           │
        │  └─ Tracer (tracer.py): echo / JSONL / sink callback│
        └───────────────────────┬────────────────────────────┘
                                ▼
        ┌────────────────────────────────────────────────────┐
        │  LLM layer (llm.py): OpenAI-compatible async client │
        │  local gateway / DeepSeek / OpenAI — env-var switch │
        └────────────────────────────────────────────────────┘
```

**Recursion model**: `run_agent(task, depth)` runs a `while` loop where each round lets the LLM decide
"keep calling tools" or "give the final answer". When it calls `spawn_subagent(task)`, the tool's handler
**recursively calls `run_agent(task, depth+1)`** — that is the essence of delegation. The child returns its
`output` as a tool result to the parent, and the parent's loop continues.

---

## Quick start

### 1. Environment

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[server]"          # core + FastAPI/uvicorn
# Frontend (optional; without a build the server returns an API info page):
cd frontend && pnpm install && pnpm build && cd ..
```

### 2. Configure the LLM (pick one of three)

Copy `.env.example` to `.env` and fill in a key, or set env vars directly:

```bash
# Local / self-hosted OpenAI-compatible gateway (defaults to 127.0.0.1:3065)
export AGENTREE_API_KEY=sk-your-key
export AGENTREE_BASE_URL=http://127.0.0.1:3065/v1
export AGENTREE_MODEL=deepseek-v4-flash

# or DeepSeek official
export DEEPSEEK_API_KEY=sk-xxxx
# or OpenAI official
export OPENAI_API_KEY=sk-xxxx
```

> ⚠️ Keys are read only from environment variables. The source and `.env.example` contain **no real
> keys**; `.env` is gitignored.

### 3. Start the web server

```bash
export AGENTREE_DEMO_AUTH=on   # demo mode: skip third-party login, enter directly
python3 -m agentree.server --host 127.0.0.1 --port 8765
```

Open `http://127.0.0.1:8765`. With demo mode on, the login page shows a **"Demo mode (no login)"** button;
click it to enter the orchestrator.

> If port 8765 collides with another project in the portfolio (e.g. P1 rag-doc-chat), use `--port 8767`
> and open `http://127.0.0.1:8767`.

> Demo mode `AGENTREE_DEMO_AUTH=on` is for public demos / screenshots / environments without an internal
> login system. Keep it `off` in production and use third-party unified login (slider captcha + internal
> login-system JWT).

### 4. Run a task from the command line

```bash
python3 -m agentree "Research the leading vector databases of 2025 and produce a comparison table"
```

### 5. Run the tests (no network, no API key)

```bash
python3 -m pytest tests/ -q -p no:asyncio
```

Tests inject a fake LLM client and cover 28 cases: context isolation, concurrent fan-out, the three
limits, tool-result truncation, error backfill, task-board CAS, dependency gating, dispatch-analysis
fallback, and more.

---

## Core API

### `run_agent(task, config, *, client, depth, parent_id, tracer, extra_tools, inbox, history)`

Runs an agent until a final answer. When the spawn tools are available, children recurse through this
same function.

- `config.max_depth`: recursion depth limit (top level is `depth=0`)
- `config.max_steps`: max loop rounds for a single agent
- `config.max_children`: max sub-agents a single agent may spawn
- `config.max_tool_result_chars`: truncation length before a tool result is fed back
- `config.enable_web`: whether to attach `web_search` / `web_fetch`
- `inbox`: step-boundary message injection (needs a `take()` method)
- `history`: persistent-agent cross-round session history

Returns `AgentResult(run_id, depth, output, steps, tokens_in/out, children_spawned, error, messages)`.

### Team collaboration

```python
from agentree.team import Team

team = Team(emit=lambda kind, **data: print(kind, data))  # emit pushes events to SSE
await team.run("Research three industries and summarize")  # internally auto-decides solo/team
```

Team tools: `spawn_teammate` / `send_message` / `team_task_create` / `team_task_list` / `team_task_get` /
`team_task_update` (CAS) / `list_agents` / `wait_agents`.

### Custom tools

```python
from agentree import tool

@tool("add", "Add two numbers", {
    "type": "object",
    "properties": {"a": {"type": "integer"}, "b": {"type": "integer"}},
    "required": ["a", "b"],
})
async def add(a, b):
    return str(a + b)

# Pass it to AgentConfig.tools; every level of agent can use it
cfg = AgentConfig(tools=(add,))
```

---

## HTTP API (server)

| Method | Path | Description |
|------|------|------|
| GET | `/api/auth/slider` | Get a slider-captcha challenge |
| POST | `/api/auth/login` | Username + password + slider login (third-party unified auth) |
| POST | `/api/auth/demo` | Demo-mode no-login token (when `AGENTREE_DEMO_AUTH=on`) |
| GET | `/api/auth/status` | Check whether demo mode is enabled |
| POST | `/api/runs` | Start a single-agent run |
| POST | `/api/team/runs` | Start a team run (auto dispatch analysis) |
| GET | `/api/runs` | List runs |
| GET | `/api/runs/{id}` | Run detail |
| PATCH | `/api/runs/{id}` | Edit label |
| DELETE | `/api/runs/{id}` | Delete run |
| POST | `/api/runs/{id}/cancel` | Cancel run |
| GET | `/api/runs/{id}/events` | SSE event stream (live agent tree) |
| GET | `/api/info` | Current model / version |
| GET | `/api/models` | Available model list |

---

## Project layout

```
agentree/
├── agentree/
│   ├── agent.py        # Agent loop + spawn delegation (recursion core)
│   ├── team.py         # Persistent team + task board + LLM dispatch analysis
│   ├── server.py       # FastAPI + SSE + login auth
│   ├── llm.py          # OpenAI-compatible async client (env-var config)
│   ├── tools.py        # Tool / ToolRegistry / @tool decorator
│   ├── builtins.py     # read_file / list_dir / web_search / web_fetch
│   ├── websearch.py    # SearXNG aggregation (failover + SSRF protection)
│   ├── tracer.py       # echo / JSONL / sink traces
│   └── cli.py          # python -m agentree "task"
├── frontend/           # Vue3 + Element Plus orchestrator (built to dist/)
├── examples/           # custom_tools / fanout_poems / recursive_writing
├── tests/              # 28 cases, fake client, no network
├── .env.example        # config template (no real keys)
└── pyproject.toml
```

---

## Design decisions

1. **Why recursion instead of flattening?** Sub-tasks are naturally a tree. Recursion turns "delegate"
   into an ordinary tool call — the parent need not understand the child's internals, only consume the
   final output. This matches how humans hand work to a subordinate and take back results.

2. **Why context isolation?** If every child step were pushed into the parent context, a depth-3,
   30-step-per-level task would explode the token count. With isolation the parent pays only for
   "task description + final answer".

3. **Why CAS revision numbers on the task board?** Multiple teammates edit the same board concurrently;
   optimistic locking (`expected_revision`) prevents clobbering — a distributed-systems staple that applies
   equally well to agent collaboration.

4. **Why sanitize the dispatch analysis and fall back to solo?** LLM output is unreliable (missing fields,
   illegal mode, over-provisioning). Any invalid input falls back to solo so the system "still finishes in
   the worst case" rather than crashing.

5. **Why no keys in source?** The portfolio is public; a hardcoded key is a donated account. All sensitive
   config goes through env vars and `.env` is ignored.

## License

MIT
