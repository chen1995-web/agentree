<script setup>
import { computed } from 'vue'
import { useI18n } from '@/i18n'

const { t } = useI18n()

const props = defineProps({ node: { type: Object, required: true } })
defineEmits(['select'])

const statusText = computed(() =>
  t('node.' + ({ running: 'running', done: 'done', error: 'error' }[props.node.status] || props.node.status)))
const lastCalls = computed(() => {
  const calls = props.node.currentCalls || []
  return calls.length ? t('node.calls', { calls: calls.join(', ') }) : (props.node.status === 'running' ? t('node.thinking') : '')
})
</script>

<template>
  <div class="agent" :class="[node.status, 'd' + node.depth]">
    <div class="card" @click="$emit('select', node)">
      <div class="head">
        <span class="dot" :class="node.status"></span>
        <span class="rid">{{ node.run_id }}</span>
        <el-tag size="small" effect="plain" type="info">d{{ node.depth }}</el-tag>
        <span class="st">{{ statusText }}</span>
        <span class="stats">{{ t('node.stats', { steps: node.steps, tin: node.tokensIn, tout: node.tokensOut }) }}</span>
      </div>
      <div class="task" :title="node.task">{{ node.task }}</div>
      <div v-if="lastCalls" class="calls">{{ lastCalls }}</div>
      <div v-if="node.tools.length" class="tools">
        <span v-for="(tool, i) in node.tools" :key="i" class="tool" :class="{ pending: tool.chars === null }">
          🔧 {{ tool.name }}<template v-if="tool.chars !== null">{{ t('node.toolChars', { chars: tool.chars, secs: tool.secs }) }}</template>
        </span>
      </div>
    </div>
    <div v-if="node.children.length" class="children">
      <AgentNode v-for="c in node.children" :key="c.run_id" :node="c" @select="$emit('select', $event)" />
    </div>
  </div>
</template>
