<template>
  <n-space justify="space-between" class="toolbar">
    <span>{{ turnState.terminalReceived ? '链路已结束' : '每 2 秒刷新执行进度' }}</span>
    <n-space><n-button size="small" :loading="loading" @click="load">刷新</n-button>
      <n-button size="small" :disabled="!detail" @click="exportTrace">导出安全 JSON</n-button></n-space>
  </n-space>
  <n-spin :show="loading && !detail">
    <template v-if="detail">
      <n-descriptions bordered :column="2" label-placement="left">
        <n-descriptions-item label="状态">{{ STATUS_LABELS[turnState.status] }}</n-descriptions-item>
        <n-descriptions-item label="首答案 Token">{{ metricText(turnState.metrics.answerFirstTokenMs) }}</n-descriptions-item>
        <n-descriptions-item label="总耗时">{{ metricText(turnState.metrics.totalDurationMs) }}</n-descriptions-item>
        <n-descriptions-item label="调用次数">LLM {{ detail.summary?.llm_calls ?? '未汇总' }} / 工具 {{ detail.summary?.tool_calls ?? '未汇总' }}</n-descriptions-item>
      </n-descriptions>
      <h3>阶段与耗时</h3><AgentWaterfall :state="turnState" />
      <AgentDebugPanel :state="turnState" :show="true" />
      <h3>事件日志（连续回答增量已合并）</h3>
      <div class="events">
        <details v-for="(event, index) in events" :key="String(event.event_id || index)">
          <summary><span>#{{ event.sequence || '-' }}</span>
            <span>{{ event.summary || STAGE_LABELS[String(event.stage)] || event.event }}</span>
            <span>{{ event.event === 'answer.delta' ? '增量记录' : event.event === 'stage.started' || event.event === 'turn.started' ? '开始记录' : event.event === 'stage.progress' ? '进度记录' : STATUS_LABELS[String(event.status)] || '事件记录' }}</span>
            <span>{{ event.duration_ms == null ? '—' : formatDuration(Number(event.duration_ms)) }}</span>
          </summary>
          <AgentDetailFields :detail="eventDetail(event)" />
        </details>
      </div>
    </template>
    <n-empty v-else description="等待链路日志写入" />
  </n-spin>
</template>
<script setup lang="ts">
import { computed, onUnmounted, ref, watch } from 'vue'
import { downloadAgentTrace, getAgentTrace, type AgentTraceDetail } from '@/api/agent'
import { formatDuration } from '@/chat-core/formatters'
import { buildTraceState, compactTraceEvents, STAGE_LABELS, STATUS_LABELS } from '@/chat-core/trace-view'
import AgentWaterfall from './AgentWaterfall.vue'
import AgentDebugPanel from './AgentDebugPanel.vue'
import AgentDetailFields from './AgentDetailFields.vue'
const props = defineProps<{ traceId: string }>()
const message = useMessage()
const detail = ref<AgentTraceDetail | null>(null)
const loading = ref(false)
let timer: ReturnType<typeof setTimeout> | undefined
let generation = 0
let requestVersion = 0
const turnState = computed(() => buildTraceState(props.traceId, detail.value?.summary as unknown as Record<string, unknown> || null, detail.value?.events || []))
const events = computed(() => compactTraceEvents(detail.value?.events || []))
function metricText(value: number | null) { return value == null ? (turnState.value.terminalReceived ? '未记录' : '等待结果') : formatDuration(value) }
function eventDetail(event: Record<string, unknown>): Record<string, unknown> {
  return event.detail && typeof event.detail === 'object' ? event.detail as Record<string, unknown> : {}
}
async function load() {
  if (timer) clearTimeout(timer)
  const current = generation
  const version = ++requestVersion
  loading.value = true
  try {
    const result = await getAgentTrace(props.traceId)
    if (current === generation && version === requestVersion) detail.value = result
  } catch (error) {
    if (current === generation && version === requestVersion && !detail.value) message.error((error as Error).message || '链路加载失败')
  } finally {
    if (current === generation && version === requestVersion) {
      loading.value = false
      if (!turnState.value.terminalReceived) timer = setTimeout(load, 2000)
    }
  }
}
async function exportTrace() {
  try {
    const blob = await downloadAgentTrace(props.traceId)
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    link.download = `trace-${props.traceId}.json`
    link.click()
    URL.revokeObjectURL(url)
  } catch (error) { message.error((error as Error).message || '导出失败') }
}
watch(() => props.traceId, () => { generation += 1; detail.value = null; load() }, { immediate: true })
onUnmounted(() => { generation += 1; if (timer) clearTimeout(timer) })
</script>
<style scoped>
.toolbar { margin-bottom: 16px; } h3 { margin: 20px 0 10px; font-size: 15px; }
.events { display: grid; gap: 8px; } .events details { border: 1px solid var(--n-border-color); border-radius: 6px; padding: 8px 10px; }
.events summary { display: grid; grid-template-columns: 55px minmax(0, 1fr) 70px 55px; gap: 8px; cursor: pointer; }
</style>
