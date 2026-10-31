import { reactive } from 'vue'
import { getToken, clearAuth } from './utils/auth'

// 全局状态：运行列表 / 当前运行的代理树 / 事件流 / 最终回答 / 团队（花名册+任务板）
export const store = reactive({
  runs: [],
  currentRun: null,
  status: 'idle', // idle | running | done | error | cancelled
  task: '',
  config: null,
  roots: [], // 顶层智能体节点（children 挂在各自节点下）
  agents: {}, // run_id -> node
  events: [], // 事件流（截断保存）
  answer: null, // run_final 汇总
  team: { plan: null, agents: [], tasks: [] }, // 团队模式：作战计划 + 花名册 + 共享任务板
})

let es = null

export async function api(path, opts = {}) {
  const headers = { ...(opts.headers || {}) }
  const token = getToken()
  if (token) headers.Authorization = `Bearer ${token}`
  const r = await fetch(path, { ...opts, headers })
  if (r.status === 401) {
    // 与 http.js 同策略：登录态失效，清掉凭证并弹回登录页
    clearAuth()
    if (location.hash.indexOf('/login') === -1) {
      const from = location.hash.replace(/^#/, '') || '/'
      location.hash = `#/login?redirect=${encodeURIComponent(from)}`
    }
    throw new Error('Session expired')
  }
  if (!r.ok) throw new Error(`${r.status} ${await r.text()}`)
  return r.json()
}

function resetRun() {
  store.roots = []
  store.agents = {}
  store.events = []
  store.answer = null
  store.status = 'running'
  store.team = { plan: null, agents: [], tasks: [] }
}

function upsertAgent(a) {
  const i = store.team.agents.findIndex(x => x.name === a.name)
  if (i >= 0) Object.assign(store.team.agents[i], a)
  else store.team.agents.push(a)
}

function upsertTask(t) {
  const i = store.team.tasks.findIndex(x => x.id === t.id)
  if (i >= 0) Object.assign(store.team.tasks[i], t)
  else store.team.tasks.push(t)
}

export function handleEvent(rec) {
  store.events.push(rec)
  if (store.events.length > 600) store.events.splice(0, store.events.length - 600)
  switch (rec.kind) {
    case 'run_queued':
      store.task = rec.task
      store.config = rec.config
      break
    case 'plan':
      store.team.plan = rec.plan
      break
    case 'run_start': {
      // eslint-disable-next-line no-case-declarations
      const node = reactive({
        run_id: rec.run_id, parent: rec.parent || null, depth: rec.depth,
        task: rec.task, status: 'running', steps: 0,
        tokensIn: 0, tokensOut: 0, tools: [], children: [],
        currentCalls: [], error: null,
      })
      store.agents[rec.run_id] = node
      const parent = rec.parent && store.agents[rec.parent]
      if (parent) parent.children.push(node)
      else store.roots.push(node)
      break
    }
    case 'llm': {
      const n = store.agents[rec.run_id]
      if (n) {
        n.steps += 1
        n.tokensIn += rec.tokens_in || 0
        n.tokensOut += rec.tokens_out || 0
        n.currentCalls = rec.tool_calls || []
      }
      break
    }
    case 'tool_call': {
      const n = store.agents[rec.run_id]
      if (n) n.tools.push({ name: rec.name, args: rec.args || '', chars: null, secs: null })
      break
    }
    case 'tool_result': {
      const n = store.agents[rec.run_id]
      if (n) {
        // eslint-disable-next-line no-case-declarations
        const t = [...n.tools].reverse().find(t => t.name === rec.name && t.chars === null)
        if (t) { t.chars = rec.chars; t.secs = rec.secs }
      }
      break
    }
    case 'run_end': {
      const n = store.agents[rec.run_id]
      if (n) { n.status = rec.error ? 'error' : 'done'; n.error = rec.error || null }
      break
    }
    case 'agent_upsert':
      upsertAgent(rec.agent)
      break
    case 'agent_status': {
      // eslint-disable-next-line no-case-declarations
      const a = store.team.agents.find(x => x.name === rec.agent)
      if (a) a.status = rec.status
      break
    }
    case 'task_created':
    case 'task_updated':
      upsertTask(rec.task)
      break
    case 'run_final': {
      store.status = rec.status
      store.answer = {
        output: rec.output ?? null, steps: rec.steps, tokens_in: rec.tokens_in,
        tokens_out: rec.tokens_out, children: rec.children, error: rec.error, status: rec.status,
      }
      break
    }
  }
}

export function connectRun(runId, taskText) {
  if (es) { es.close(); es = null }
  resetRun()
  store.currentRun = runId
  if (taskText !== undefined && taskText !== null) store.task = taskText
  // EventSource 带不了 Authorization 头，token 走 query 参数（后端兼容）
  es = new EventSource(`/api/runs/${runId}/events?token=${encodeURIComponent(getToken())}`)
  es.onmessage = e => { try { handleEvent(JSON.parse(e.data)) } catch { /* 忽略坏帧 */ } }
  es.addEventListener('end', () => { es.close(); es = null; refreshRuns() })
}

export async function refreshRuns() {
  try { store.runs = await api('/api/runs') } catch { /* 忽略 */ }
}

export async function startRun(body) {
  const { run_id } = await api('/api/runs', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  connectRun(run_id)
  refreshRuns()
  return run_id
}

export async function startTeamRun(body) {
  const { run_id } = await api('/api/team/runs', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  connectRun(run_id)
  refreshRuns()
  return run_id
}

export async function cancelRun(runId) {
  if (!runId) return
  try { await api(`/api/runs/${runId}/cancel`, { method: 'POST' }) } catch { /* 忽略 */ }
}

export function clearCurrentRun() {
  if (es) { es.close(); es = null }
  store.currentRun = null
  store.roots = []
  store.agents = {}
  store.events = []
  store.answer = null
  store.team = { plan: null, agents: [], tasks: [] }
  store.status = 'idle'
  store.task = ''
}

export async function deleteRun(runId) {
  if (!runId) return
  await api(`/api/runs/${runId}`, { method: 'DELETE' })
  if (store.currentRun === runId) clearCurrentRun()
  refreshRuns()
}

export async function editRunLabel(runId, label) {
  const r = await api(`/api/runs/${runId}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ label }),
  })
  refreshRuns()
  return r
}
