<template>
  <n-card :title="`Trace · ${traceId}`">
    <template #header-extra>
      <n-space>
        <n-button @click="router.back()">返回</n-button>
        <n-button type="primary" :disabled="!detail" @click="exportTrace">导出安全 JSON</n-button>
      </n-space>
    </template>
    <n-spin :show="loading">
      <template v-if="detail">
        <n-descriptions bordered :column="3" label-placement="left">
          <n-descriptions-item label="状态">{{ detail.summary?.status || '-' }}</n-descriptions-item>
          <n-descriptions-item label="首 Token">{{ formatDuration(detail.summary?.answer_first_token_ms) }}</n-descriptions-item>
          <n-descriptions-item label="总耗时">{{ formatDuration(detail.summary?.total_duration_ms) }}</n-descriptions-item>
          <n-descriptions-item label="Agent">{{ detail.summary?.agent_id || '-' }}</n-descriptions-item>
          <n-descriptions-item label="LLM 调用">{{ detail.summary?.llm_calls || 0 }}</n-descriptions-item>
          <n-descriptions-item label="工具调用">{{ detail.summary?.tool_calls || 0 }}</n-descriptions-item>
        </n-descriptions>
        <h3>阶段瀑布</h3>
        <AgentWaterfall :state="turnState" />
        <AgentDebugPanel :state="turnState" :show="true" />
        <h3>事件日志</h3>
        <div class="events">
          <details v-for="(event, index) in detail.events" :key="String(event.event_id || index)">
            <summary>
              <span class="seq">#{{ event.sequence || '-' }}</span>
              <span>{{ event.event }}</span>
              <span>{{ event.stage }}</span>
              <span class="duration">{{ formatDuration(asNumber(event.duration_ms)) }}</span>
            </summary>
            <pre>{{ JSON.stringify(event, null, 2) }}</pre>
          </details>
        </div>
      </template>
    </n-spin>
  </n-card>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { downloadAgentTrace, getAgentTrace, type AgentTraceDetail } from '@/api/agent'
import { formatDuration } from '@/chat-core/formatters'
import { createTurnState, type TurnState } from '@/chat-core/stage-reducer'
import type { EventStatus } from '@/chat-core/events'
import AgentWaterfall from './components/AgentWaterfall.vue'
import AgentDebugPanel from './components/AgentDebugPanel.vue'

const route = useRoute()
const router = useRouter()
const message = useMessage()
const traceId = route.params.traceId as string
const detail = ref<AgentTraceDetail | null>(null)
const loading = ref(false)

const turnState = computed<TurnState>(() => {
  const state = createTurnState(detail.value?.summary?.turn_id || '')
  state.traceId = traceId
  state.metrics.totalDurationMs = detail.value?.summary?.total_duration_ms ?? null
  state.status = detail.value?.summary?.status === 'completed' ? 'completed'
    : detail.value?.summary?.status === 'cancelled' ? 'cancelled'
      : detail.value?.summary?.status === 'failed' ? 'failed' : 'running'
  for (const raw of detail.value?.events || []) {
    const event = String(raw.event || '')
    const stageId = String(raw.stage_id || '')
    if (!event.startsWith('stage.') || !stageId) continue
    const existed = !!state.stages[stageId]
    state.stages[stageId] = {
      stage: String(raw.stage || 'unknown'),
      stageId,
      status: String(raw.status || 'running') as EventStatus,
      visibility: raw.visibility === 'debug' ? 'debug' : 'public',
      startedAt: String(raw.started_at || raw.timestamp || ''),
      durationMs: asNumber(raw.duration_ms),
      summary: typeof raw.summary === 'string' ? raw.summary : null,
      detail: isRecord(raw.detail) ? raw.detail : {},
    }
    if (!existed) state.stageOrder.push(stageId)
  }
  return state
})

async function load() {
  loading.value = true
  try { detail.value = await getAgentTrace(traceId) }
  catch (error) { message.error((error as Error).message || 'Trace 加载失败') }
  finally { loading.value = false }
}
async function exportTrace() {
  try {
    const blob = await downloadAgentTrace(traceId)
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    link.download = `trace-${traceId}.json`
    link.click()
    URL.revokeObjectURL(url)
  } catch (error) { message.error((error as Error).message || '导出失败') }
}
function asNumber(value: unknown): number | null { return typeof value === 'number' ? value : null }
function isRecord(value: unknown): value is Record<string, unknown> { return !!value && typeof value === 'object' && !Array.isArray(value) }
onMounted(load)
</script>

<style scoped>
h3 { margin: 22px 0 10px; font-size: 15px; }
.events { display: grid; gap: 8px; }
.events details { border: 1px solid var(--n-border-color); border-radius: 6px; padding: 8px 10px; }
.events summary { display: grid; grid-template-columns: 55px 180px 1fr auto; gap: 10px; cursor: pointer; }
.seq, .duration { color: var(--n-text-color-3); }
pre { overflow: auto; max-height: 360px; padding: 10px; background: rgba(128,128,128,.06); white-space: pre-wrap; word-break: break-word; }
</style>
