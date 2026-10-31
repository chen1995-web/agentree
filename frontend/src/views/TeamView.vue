<script setup>
import { computed, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { store, connectRun, refreshRuns, startTeamRun, cancelRun } from '@/store'
import { useAutoScroll } from '@/composables/useAutoScroll'
import { useI18n } from '@/i18n'

const { t, locale } = useI18n()

const task = ref('')
const starting = ref(false)
const feedEl = ref(null)
// 团队动态：默认跟随底部；用户上滚即暂停，滚回底部自动恢复
const { pinned: feedPinned, scrollToBottom: feedToBottom } =
  useAutoScroll(() => feedEl.value?.parentElement, () => store.events.length)
const selectedRun = ref('')

const teamRuns = computed(() => store.runs)

function replay(runId) {
  const r = store.runs.find(x => x.run_id === runId)
  if (!r) return
  task.value = r.task
  connectRun(runId)
}

const tagText = s => t('tag.' + ({ idle: 'idle', running: 'running', done: 'done', error: 'error', cancelled: 'cancelled' }[s] || s))
const tagType = s => ({ running: 'primary', done: 'success', error: 'danger', cancelled: 'info', idle: 'info' }[s] || 'info')

const esc = s => String(s ?? '').replace(/[&<>]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;' }[c]))
const fmtT = ts => new Date((ts || 0) * 1000).toLocaleTimeString(locale.value === 'zh' ? 'zh-CN' : 'en-US', { hour12: false })

function renderMd(s) {
  return esc(s)
    .replace(/\*\*([^*]+)\*\*/g, '<b>$1</b>')
    .replace(/`([^`]+)`/g, '<code>$1</code>')
    .replace(/\n/g, '<br>')
}

const CLS = {
  run_queued: 'run_queued', run_start: 'run_start', run_final: 'run_final',
  message_sent: 'msg', task_created: 'task-new', task_updated: 'task-done',
  agent_final: 'agent-final', turn_tool_call: 'tool_call', turn_tool_result: 'tool_result',
}

function fmtLine(e) {
  const id = `<b>${esc(e.run_id || e.agent || '')}</b>`
  switch (e.kind) {
    case 'run_queued': return `☰ ${t('ev.goal')}：${esc(e.task)}`
    case 'plan': {
      const p = e.plan || {}
      return p.mode === 'team'
        ? `🧭 ${t('ev.dispatchTeam', { n: p.agents.length })} —— ${esc(p.reason)}`
        : `🧭 ${t('ev.dispatchSolo')} —— ${esc(p.reason)}`
    }
    case 'agent_upsert': return `👥 ${t('ev.rosterAdd')} <b>${esc(e.agent.name)}</b>（${esc(e.agent.description)}）`
    case 'agent_status': return `${e.status === 'running' ? '▶' : '⏸'} <b>${esc(e.agent)}</b> ${e.status === 'running' ? t('ev.roundStart') : t('ev.roundIdle')}`
    case 'message_sent': return `📨 ${esc(e.from)} → <b>${esc(e.to)}</b>：${esc(e.preview)}`
    case 'task_created': return `📌 ${t('ev.newTask')} ${esc(e.task.id)} ${esc(e.task.subject)}${e.task.blocked_by?.length ? t('ev.deps', { ids: esc(e.task.blocked_by.join(', ')) }) : ''}`
    case 'task_updated': return `✔ ${t('ev.taskLabel')} ${esc(e.task.id)} → ${esc(e.task.status)}${e.task.owner ? `（${esc(e.task.owner)}）` : ''}`
    case 'agent_final': return `🗣 <b>${esc(e.agent)}</b> ${t('ev.agentFinal')}${e.error ? t('ev.agentErr', { err: esc(e.error) }) : ''}`
    case 'turn_run_start': return `┌ [${id}] ${esc(String(e.task || '').slice(0, 80))}`
    case 'turn_tool_call': return `│ 🔧 [${id}] ${esc(e.name)}(${esc(String(e.args || '').slice(0, 90))})`
    case 'turn_tool_result': return `│ ✔ [${id}] ${esc(e.name)} → ${e.chars} ${t('ev.chars')}`
    case 'turn_run_end': return `└ [${id}] ${t('ev.roundEnd')}`
    case 'run_final': return `★ ${t('ev.wrap')} ${esc(e.status)}${e.error ? `（${esc(e.error)}）` : ''}`
    default: return '' // turn_llm / llm 等噪音事件不进团队动态
  }
}

const lines = computed(() =>
  store.events
    .map(e => ({ t: e.t, html: fmtLine(e), cls: CLS[e.kind] || 'run_start' }))
    .filter(l => l.html))

const avatarStyle = n => {
  const h = (n.charCodeAt(0) * 37) % 360
  return { background: `linear-gradient(135deg, hsl(${h} 62% 46%), hsl(${(h + 46) % 360} 62% 54%))` }
}

const cols = [
  { key: 'pending', title: 'team.colPending' },
  { key: 'in_progress', title: 'team.colInProgress' },
  { key: 'completed', title: 'team.colCompleted' },
]
const byCol = k => store.team.tasks.filter(t => t.status === k)

async function start() {
  const tg = task.value.trim()
  if (!tg) return ElMessage.warning(t('team.msgNoGoal'))
  starting.value = true
  try {
    await startTeamRun({ task: tg })
  } catch (e) {
    ElMessage.error(t('team.msgStartFail') + e.message)
  } finally {
    starting.value = false
  }
}

async function onCancel() {
  await cancelRun(store.currentRun)
  ElMessage.info(t('console.msgCancelRequested'))
}

// （滚动跟随已由 useAutoScroll 接管）
</script>

<template>
  <el-container class="team-page">
    <el-header class="team-top" height="auto">
      <el-input v-model="task" size="large" clearable
                :placeholder="t('team.goalPh')"
                @keyup.enter="start" />
      <el-button type="primary" size="large" :loading="starting" @click="start">{{ t('team.start') }}</el-button>
      <el-tag :type="tagType(store.status)" effect="dark">{{ tagText(store.status) }}</el-tag>
      <el-button v-if="store.status === 'running'" size="small" type="danger" plain @click="onCancel">{{ t('team.cancel') }}</el-button>
      <span class="topnav-spacer" />
      <el-select v-model="selectedRun" clearable :placeholder="t('team.replay')"
                 style="width: 230px" @change="v => v && replay(v)">
        <el-option v-for="r in teamRuns" :key="r.run_id" :value="r.run_id"
                   :label="`${r.task.slice(0, 26)}（${r.status === 'done' ? t('team.replayDone') : r.status}）`" />
      </el-select>
    </el-header>

    <el-main class="team-main">
      <el-card v-if="store.team.plan" shadow="never" class="team-answer">
        <template #header>
          <div class="answer-head">
            <b>{{ t('team.plan') }}</b>
            <el-tag size="small" round effect="dark"
                    :type="store.team.plan.mode === 'team' ? 'primary' : 'info'">
              {{ store.team.plan.mode === 'team'
                ? t('team.teamMode', { n: store.team.plan.agents.length }) : t('team.soloMode') }}
            </el-tag>
          </div>
        </template>
        <div class="plan-reason">{{ store.team.plan.reason }}</div>
        <div v-if="store.team.plan.agents.length" class="plan-row">
          <el-tag v-for="a in store.team.plan.agents" :key="a.name" size="small"
                  effect="plain" class="plan-agent">
            {{ a.name }} · {{ a.description }}
          </el-tag>
        </div>
      </el-card>

      <el-card v-if="store.answer && store.answer.output" shadow="never" class="team-answer">
        <template #header><b>{{ t('team.summary') }}</b></template>
        <div class="answer-body" v-html="renderMd(store.answer.output)"></div>
      </el-card>

      <el-row :gutter="12">
        <el-col :span="7">
          <el-card shadow="never" class="fill">
            <template #header><b>{{ t('team.roster') }}</b></template>
            <el-empty v-if="!store.team.agents.length" :description="t('team.rosterEmpty')"
                      :image-size="60" />
            <div v-for="a in store.team.agents" :key="a.name" class="agent-card" :class="a.status">
              <div class="ahead">
                <el-avatar :size="30" class="agent-avatar" :style="avatarStyle(a.name)">
                  {{ a.name[0].toUpperCase() }}
                </el-avatar>
                <b class="aname">{{ a.name }}</b>
                <el-tag v-if="a.is_lead" size="small" type="warning" effect="plain" round>{{ t('team.lead') }}</el-tag>
                <el-tag size="small" round effect="light" :type="a.status === 'running' ? 'primary' : 'info'">
                  {{ a.status === 'running' ? t('team.running') : t('team.idle') }}
                </el-tag>
                <span class="muted astats">{{ t('team.turns', { n: a.turns, in: a.inbox }) }}</span>
              </div>
              <div class="adesc">{{ a.description }}</div>
            </div>
          </el-card>
        </el-col>
        <el-col :span="10">
          <el-card shadow="never" class="fill">
            <template #header><b>{{ t('team.board') }}</b></template>
            <el-empty v-if="!store.team.tasks.length" :description="t('team.noTasks')" :image-size="60" />
            <div class="board">
              <div v-for="c in cols" :key="c.key" class="board-col">
                <div class="board-title">{{ t(c.title) }}<span class="muted"> {{ byCol(c.key).length }}</span></div>
                <div v-for="tk in byCol(c.key)" :key="tk.id" class="task-card" :class="tk.status">
                  <div class="tid muted">
                    {{ tk.id }} · r{{ tk.revision }}<template v-if="tk.owner"> · {{ tk.owner }}</template>
                  </div>
                  <div class="tsubject">{{ tk.subject }}</div>
                  <div v-if="tk.blocked_by && tk.blocked_by.length" class="muted tdeps">
                    {{ t('team.deps', { ids: tk.blocked_by.join(', ') }) }}
                  </div>
                </div>
              </div>
            </div>
          </el-card>
        </el-col>
        <el-col :span="7">
          <el-card shadow="never" class="fill scroll-host">
            <template #header><b>{{ t('team.feed') }}</b></template>
            <div ref="feedEl" class="feed">
              <div v-for="(l, i) in lines" :key="i" class="line" :class="l.cls">
                <span class="t">{{ fmtT(l.t) }}</span><span v-html="l.html"></span>
              </div>
            </div>
            <button v-show="!feedPinned" class="scroll-btn" @click="feedToBottom">{{ t('console.backBottom') }}</button>
          </el-card>
        </el-col>
      </el-row>
    </el-main>
  </el-container>
</template>
