<!-- 作者：LHF；时间：2026-10-25；作用：展示链路原始记录，隔离记录标题和输入输出折叠布局。 -->
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
      <h3>操作记录（完成后显示完整输入输出）</h3>
      <n-empty v-if="!records.length" description="操作仍在执行，结束后显示记录" />
      <div class="events">
        <details v-for="(record, index) in records" :key="String(record.operation_id || index)">
          <summary><span>#{{ index + 1 }}</span>
            <span>{{ record.summary || STAGE_LABELS[String(record.kind)] || record.kind }}</span>
            <span>{{ STATUS_LABELS[String(record.status)] || '已结束' }}</span>
            <span>{{ record.duration_ms == null ? '未记录' : formatDuration(Number(record.duration_ms)) }}</span>
          </summary>
          <p v-if="isLegacy(record)" class="legacy-note">历史日志仅合并已有数据，缺失内容为历史未采集。</p>
          <details class="payload">
            <summary>原始数据</summary>
            <AgentDetailFields :detail="recordMetadata(record)" />
          </details>
          <details class="payload"><summary>完整输入</summary><pre class="context-json">{{ payloadText(record, 'input') }}</pre></details>
          <details class="payload"><summary>完整输出</summary><pre class="context-json">{{ payloadText(record, 'output') }}</pre></details>
          <details v-if="record.error" class="payload"><summary>错误信息</summary><pre class="context-json">{{ JSON.stringify(record.error, null, 2) }}</pre></details>
        </details>
      </div>
    </template>
    <n-empty v-else description="等待操作完成并写入日志；历史日志也可能已过期" />
  </n-spin>
</template>
<script setup lang="ts">
import { computed, onUnmounted, ref, watch } from 'vue'
import { downloadAgentTrace, getAgentTrace, type AgentTraceDetail } from '@/api/agent'
import { formatDuration } from '@/chat-core/formatters'
import { buildTraceState, completedTraceRecords, STAGE_LABELS, STATUS_LABELS } from '@/chat-core/trace-view'
import AgentWaterfall from './AgentWaterfall.vue'
import AgentDetailFields from './AgentDetailFields.vue'
const props = defineProps<{ traceId: string }>()
const message = useMessage()
const detail = ref<AgentTraceDetail | null>(null)
const loading = ref(false)
let timer: ReturnType<typeof setTimeout> | undefined
let generation = 0
let requestVersion = 0
const turnState = computed(() => buildTraceState(props.traceId, detail.value?.summary as unknown as Record<string, unknown> || null, detail.value?.records || detail.value?.events || []))
// 作者：LHF；2026-10-25；新日志使用独立终态记录，旧日志仅合并已有事件。
const records = computed(() => completedTraceRecords(detail.value?.records, detail.value?.events || []))
function metricText(value: number | null) { return value == null ? (turnState.value.terminalReceived ? '未记录' : '等待结果') : formatDuration(value) }
/** 判断记录是否来自历史日志兼容转换。 */
function isLegacy(record: Record<string, unknown>): boolean {
  return Boolean((record.metadata as Record<string, unknown> | undefined)?.legacy)
}
/** 汇总操作身份及元数据，直接以原始字段名和值展示 JSON。 */
function recordMetadata(record: Record<string, unknown>): Record<string, unknown> {
  return { operation_id: record.operation_id, parent_id: record.parent_id,
    started_at: record.started_at, ended_at: record.ended_at,
    ...(record.metadata as Record<string, unknown> || {}) }
}
/** 保留空数组与空对象的真实含义，只有历史缺失字段标记未采集。 */
function payloadText(record: Record<string, unknown>, key: string): string {
  if (record[key] == null) return isLegacy(record) ? '历史未采集' : key === 'output' && record.status !== 'completed' ? '未生成结果；已收到的部分数据会显示在此处' : '无'
  return JSON.stringify(record[key], null, 2)
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
    // 操作完成前没有落盘记录属于正常等待状态，避免每次刷新都弹出 404。
    const text = (error as Error).message || '链路加载失败'
    if (current === generation && version === requestVersion && !detail.value && !text.includes('Trace 不存在或已过期')) message.error(text)
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
.legacy-note { color: var(--n-text-color-3); }
.payload { min-width: 0; margin: 10px 0; }
.payload > summary { cursor: pointer; }
.context-json { white-space: pre-wrap; overflow-wrap: anywhere; max-height: 65vh; overflow: auto; font-size: 12px; margin: 0; padding: 12px; }
.events { display: grid; min-width: 0; gap: 8px; }
.events > details { min-width: 0; border: 1px solid var(--n-border-color); border-radius: 6px; padding: 8px 10px; }
/* 仅外层操作标题使用四列布局，内层输入输出保留原生折叠标题布局。 */
.events > details > summary { display: grid; grid-template-columns: 55px minmax(0, 1fr) 70px 55px; gap: 8px; cursor: pointer; }
.events > details > summary > span { min-width: 0; overflow-wrap: anywhere; }
</style>
