<script setup>
import { computed, reactive, ref, onMounted, onBeforeUnmount } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import AgentNode from '@/components/AgentNode.vue'
import { store, api, connectRun, refreshRuns, startRun, cancelRun, deleteRun, editRunLabel, clearCurrentRun } from '@/store'
import { useAutoScroll } from '@/composables/useAutoScroll'
import { useI18n } from '@/i18n'

const { t, locale } = useI18n()

const task = ref('')
const model = ref('')
const models = ref([])
const maxDepth = ref(2)
const maxSteps = ref(30)
const maxChildren = ref(8)
const starting = ref(false)
const drawer = ref(false)
const detail = ref(null)
const feedEl = ref(null)
const treeEl = ref(null)
const info = ref({ model: '', base_url: '', version: '' })

// 事件流 / 代理树：默认跟随底部；用户上滚即暂停，滚回底部自动恢复
const { pinned: feedPinned, scrollToBottom: feedToBottom } =
  useAutoScroll(() => feedEl.value?.parentElement, () => store.events.length)
const { pinned: treePinned, scrollToBottom: treeToBottom } =
  useAutoScroll(() => treeEl.value?.parentElement, () => store.events.length)

const tagText = s => t('tag.' + ({ idle: 'idle', running: 'running', done: 'done', error: 'error', cancelled: 'cancelled' }[s] || s))
const tagType = s => ({ running: 'primary', done: 'success', error: 'danger', cancelled: 'info', idle: 'info' }[s] || 'info')

const esc = s => String(s ?? '').replace(/[&<>]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;' }[c]))
const fmtT = ts => new Date((ts || 0) * 1000).toLocaleTimeString(locale.value === 'zh' ? 'zh-CN' : 'en-US', { hour12: false })

function fmtLine(e) {
  const id = `<b>${e.run_id || ''}</b>`
  switch (e.kind) {
    case 'run_queued': return `☰ ${e.mode === 'team' ? t('ev.newTeamRun') : t('ev.newRun')} ${id}`
    case 'run_start': return `▶ ${id} d${e.depth} ${esc(String(e.task || '').slice(0, 90))}`
    case 'llm': return `● ${id} ${(e.tool_calls || []).length ? '→ ' + esc(e.tool_calls.join(', ')) : '→ ' + t('ev.generate')}`
    case 'tool_call': return `🔧 ${id} ${esc(e.name)}(${esc(String(e.args || '').slice(0, 100))})`
    case 'tool_result': return `✔ ${id} ${esc(e.name)} → ${e.chars} ${t('ev.chars')} / ${e.secs}s`
    case 'run_end': return `■ ${id} ${e.error ? t('ev.error') + ': ' + esc(e.error) : t('ev.done')}`
    case 'run_final': return `★ ${e.status === 'done' ? t('ev.allDone') : t('ev.ended') + '(' + e.status + ')'}${e.error ? ': ' + esc(e.error) : ''}`
    // ---- 团队模式事件（在编排台回放团队运行时给出可读摘要） ----
    case 'agent_upsert': return `👥 ${t('ev.rosterAdd')} <b>${esc(e.agent.name)}</b>（${esc(e.agent.description)}）`
    case 'agent_status': return `${e.status === 'running' ? '▶' : '⏸'} <b>${esc(e.agent)}</b> ${e.status === 'running' ? t('ev.roundStart') : t('ev.roundIdle')}`
    case 'message_sent': return `📨 ${esc(e.from)} → <b>${esc(e.to)}</b>：${esc(e.preview)}`
    case 'task_created': return `📌 ${t('ev.newTask')} ${esc(e.task.id)} ${esc(e.task.subject)}${e.task.blocked_by && e.task.blocked_by.length ? t('ev.deps', { ids: e.task.blocked_by.join(', ') }) : ''}`
    case 'task_updated': return `✔ ${t('ev.taskLabel')} ${esc(e.task.id)} → ${esc(e.task.status)}${e.task.owner ? ` (${esc(e.task.owner)})` : ''}`
    case 'agent_final': return `🗣 <b>${esc(e.agent)}</b> ${t('ev.agentFinal')}${e.error ? t('ev.agentErr', { err: esc(e.error) }) : ''}`
    case 'turn_run_start': return `┌ [${id}] ${esc(String(e.task || '').slice(0, 80))}`
    case 'turn_tool_call': return `│ 🔧 [${id}] ${esc(e.name)}(${esc(String(e.args || '').slice(0, 90))})`
    case 'turn_tool_result': return `│ ✔ [${id}] ${esc(e.name)} → ${e.chars} ${t('ev.chars')}`
    case 'turn_run_end': return `└ [${id}] ${t('ev.roundEnd')}`
    default: return '' // 未识别事件不在事件流展示
  }
}

const feedLines = computed(() =>
  store.events.map(e => ({ e, html: fmtLine(e) })).filter(x => x.html))

function renderMd(s) {
  return esc(s)
    .replace(/\*\*([^*]+)\*\*/g, '<b>$1</b>')
    .replace(/`([^`]+)`/g, '<code>$1</code>')
    .replace(/\n/g, '<br>')
}

async function start() {
  const tk = task.value.trim()
  if (!tk) return ElMessage.warning(t('console.msgNoTask'))
  starting.value = true
  try {
    await startRun({
      task: tk,
      model: model.value || null,
      max_depth: maxDepth.value,
      max_steps: maxSteps.value,
      max_children: maxChildren.value,
    })
  } catch (e) {
    ElMessage.error(t('console.msgStartFail') + e.message)
  } finally {
    starting.value = false
  }
}

function openRun(r) {
  task.value = r.task
  connectRun(r.run_id)
}

async function cancel() {
  await cancelRun(store.currentRun)
  ElMessage.info(t('console.msgCancelRequested'))
}

function openDetail(node) {
  detail.value = node
  drawer.value = true
}

function copyAnswer() {
  navigator.clipboard.writeText(store.answer?.output || '')
  ElMessage.success(t('console.msgCopied'))
}

// ---- 历史运行：右键菜单（重命名 / 复制任务 / 删除） ----
const ctxMenu = reactive({ show: false, x: 0, y: 0, run: null })
const renameDlg = ref(false)
const renameText = ref('')

function openRunMenu(e, r) {
  ctxMenu.show = true
  ctxMenu.run = r
  ctxMenu.x = Math.min(e.clientX, window.innerWidth - 170)
  ctxMenu.y = Math.min(e.clientY, window.innerHeight - 130)
}
function closeRunMenu() { ctxMenu.show = false }

function startRename() {
  closeRunMenu()
  renameText.value = ctxMenu.run?.label || ''
  renameDlg.value = true
}
async function saveRename() {
  // 只改列表显示名，原始任务与运行数据保持不变
  await editRunLabel(ctxMenu.run.run_id, renameText.value)
  renameDlg.value = false
  ElMessage.success(t('console.msgRenamed'))
}
function copyRunTask() {
  closeRunMenu()
  navigator.clipboard.writeText(ctxMenu.run?.task || '')
  ElMessage.success(t('console.msgTaskCopied'))
}
async function confirmDelete() {
  const r = ctxMenu.run
  closeRunMenu()
  const name = (r.label || r.task || '').slice(0, 30)
  try {
    await ElMessageBox.confirm(t('console.msgDeleteConfirm', { name }),
      t('console.msgDeleteTitle'), { type: 'warning', confirmButtonText: t('console.msgDeleteOk'), cancelButtonText: t('console.dlgCancel') })
  } catch { return }
  try {
    await deleteRun(r.run_id)
    ElMessage.success(t('console.msgDeleted'))
  } catch (e) {
    ElMessage.error(t('console.msgDeleteFail') + e.message)
  }
}

onMounted(async () => {
  window.addEventListener('click', closeRunMenu)
  refreshRuns()
  try {
    info.value = await api('/api/info')
    models.value = await api('/api/models')
  } catch { /* 后端未就绪时忽略 */ }
})
onBeforeUnmount(() => window.removeEventListener('click', closeRunMenu))
</script>

<template>
  <el-container class="app">
    <el-aside width="300px" class="aside">
      <el-card shadow="never" class="panel">
        <template #header><b>{{ t('console.newRun') }}</b></template>
        <el-form label-position="top" @submit.prevent>
          <el-form-item :label="t('console.task')">
            <el-input v-model="task" type="textarea" :rows="5"
                      :placeholder="t('console.taskPh')" />
          </el-form-item>
          <el-form-item :label="t('console.model')">
            <el-select v-model="model" filterable allow-create clearable
                       :placeholder="t('console.modelPh')" style="width: 100%">
              <el-option v-for="m in models" :key="m" :label="m" :value="m" />
            </el-select>
          </el-form-item>
          <el-row :gutter="8">
            <el-col :span="8">
              <el-form-item :label="t('console.depth')">
                <el-input-number v-model="maxDepth" :min="0" :max="3" controls-position="right" style="width: 100%" />
              </el-form-item>
            </el-col>
            <el-col :span="8">
              <el-form-item :label="t('console.steps')">
                <el-input-number v-model="maxSteps" :min="1" :max="100" controls-position="right" style="width: 100%" />
              </el-form-item>
            </el-col>
            <el-col :span="8">
              <el-form-item :label="t('console.children')">
                <el-input-number v-model="maxChildren" :min="1" :max="32" controls-position="right" style="width: 100%" />
              </el-form-item>
            </el-col>
          </el-row>
          <el-button type="primary" :loading="starting" style="width: 100%" @click="start">{{ t('console.start') }}</el-button>
        </el-form>
      </el-card>

      <el-card shadow="never" class="panel history">
        <template #header><b>{{ t('console.history') }}</b></template>
        <el-empty v-if="!store.runs.length" :description="t('console.noRuns')" :image-size="60" />
        <div v-for="r in store.runs" :key="r.run_id" class="run-item"
             :class="{ active: r.run_id === store.currentRun }"
             @click="openRun(r)" @contextmenu.prevent="openRunMenu($event, r)">
          <el-tag :type="tagType(r.status)" size="small" effect="dark">{{ tagText(r.status) }}</el-tag>
          <span class="htask" :title="r.label ? `Original task: ${r.task}` : r.task">{{ r.label || r.task }}</span>
        </div>
      </el-card>

      <div class="server muted">{{ info.base_url }} · {{ info.model }}</div>
    </el-aside>

    <el-container>
      <el-header class="runbar" height="auto">
        <div class="run-task" :title="store.task">{{ store.task || t('console.runPh') }}</div>
        <div class="run-meta">
          <span v-if="store.currentRun" class="rid-chip">{{ store.currentRun }}</span>
          <el-tag :type="tagType(store.status)" effect="dark">{{ tagText(store.status) }}</el-tag>
          <span v-if="store.answer" class="muted">
            steps {{ store.answer.steps }} · {{ t('console.children') }} {{ store.answer.children }}
            · tokens {{ store.answer.tokens_in }}/{{ store.answer.tokens_out }}
          </span>
          <el-button v-if="store.status === 'running'" size="small" type="danger" plain @click="cancel">{{ t('console.cancel') }}</el-button>
        </div>
      </el-header>

      <el-main class="content">
        <el-card v-if="store.answer && store.answer.output" shadow="never" class="answer">
          <template #header>
            <div class="answer-head"><b>{{ t('console.answer') }}</b><el-button size="small" text @click="copyAnswer">{{ t('console.copy') }}</el-button></div>
          </template>
          <div class="answer-body" v-html="renderMd(store.answer.output)"></div>
        </el-card>

        <el-row :gutter="12" class="workspace">
          <el-col :span="14">
            <el-card shadow="never" class="fill scroll-host">
              <template #header><b>{{ t('console.tree') }}</b></template>
              <el-empty v-if="!store.roots.length" :description="t('console.noAgents')" :image-size="70" />
              <div ref="treeEl" class="tree">
                <AgentNode v-for="n in store.roots" :key="n.run_id" :node="n" @select="openDetail" />
              </div>
              <button v-show="!treePinned" class="scroll-btn" @click="treeToBottom">{{ t('console.backBottom') }}</button>
            </el-card>
          </el-col>
          <el-col :span="10">
            <el-card shadow="never" class="fill scroll-host">
              <template #header><b>{{ t('console.feed') }}</b></template>
              <div ref="feedEl" class="feed">
                <div v-for="(x, i) in feedLines" :key="i" class="line" :class="x.e.kind">
                  <span class="t">{{ fmtT(x.e.t) }}</span><span v-html="x.html"></span>
                </div>
              </div>
              <button v-show="!feedPinned" class="scroll-btn" @click="feedToBottom">{{ t('console.backBottom') }}</button>
            </el-card>
          </el-col>
        </el-row>
      </el-main>
    </el-container>

    <el-drawer v-model="drawer" :title="t('console.detailTitle', { id: detail?.run_id || '' })" size="440px">
      <template v-if="detail">
        <el-descriptions :column="1" border size="small">
          <el-descriptions-item :label="t('console.detailRunId')">{{ detail.run_id }}</el-descriptions-item>
          <el-descriptions-item :label="t('console.detailDepth')">depth {{ detail.depth }}</el-descriptions-item>
          <el-descriptions-item :label="t('console.detailStatus')">
            <el-tag size="small" :type="tagType(detail.status)">{{ tagText(detail.status) }}</el-tag>
          </el-descriptions-item>
          <el-descriptions-item :label="t('console.detailSteps')">
            {{ detail.steps }} · {{ detail.tokensIn }}/{{ detail.tokensOut }}
          </el-descriptions-item>
          <el-descriptions-item :label="t('console.detailTask')">{{ detail.task }}</el-descriptions-item>
        </el-descriptions>
        <h4>{{ t('console.detailTools') }}</h4>
        <div v-for="(tool, i) in detail.tools" :key="i" class="tool-row">
          <el-tag size="small">{{ tool.name }}</el-tag>
          <span class="muted">{{ tool.chars === null ? t('console.toolRunning') : t('console.toolChars', { chars: tool.chars, secs: tool.secs }) }}</span>
          <div class="args">{{ tool.args }}</div>
        </div>
        <el-empty v-if="!detail.tools.length" :description="t('console.noTools')" :image-size="60" />
      </template>
    </el-drawer>

    <!-- 历史运行右键菜单 -->
    <teleport to="body">
      <div v-if="ctxMenu.show" class="ctx-menu" :style="{ left: ctxMenu.x + 'px', top: ctxMenu.y + 'px' }">
        <div class="ctx-item" @click="startRename">{{ t('console.ctxRename') }}</div>
        <div class="ctx-item" @click="copyRunTask">{{ t('console.ctxCopy') }}</div>
        <div class="ctx-item danger" @click="confirmDelete">{{ t('console.ctxDelete') }}</div>
      </div>
    </teleport>

    <el-dialog v-model="renameDlg" :title="t('console.renameTitle')" width="460px">
      <el-input v-model="renameText" maxlength="80" show-word-limit
                :placeholder="t('console.renamePh')" @keyup.enter="saveRename" />
      <div class="muted" style="margin-top: 8px">{{ t('console.renameHint') }}</div>
      <template #footer>
        <el-button @click="renameDlg = false">{{ t('console.dlgCancel') }}</el-button>
        <el-button type="primary" @click="saveRename">{{ t('console.dlgSave') }}</el-button>
      </template>
    </el-dialog>
  </el-container>
</template>
