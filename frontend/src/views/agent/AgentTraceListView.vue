<template>
  <n-card title="Agent Trace">
    <div class="filters">
      <n-input v-model:value="filters.date_from" placeholder="开始日期 YYYY-MM-DD" clearable />
      <n-input v-model:value="filters.date_to" placeholder="结束日期 YYYY-MM-DD" clearable />
      <n-input v-model:value="filters.agent_id" placeholder="Agent ID" clearable />
      <n-select v-model:value="filters.status" :options="statusOptions" placeholder="状态" clearable />
      <n-input v-model:value="filters.model" placeholder="模型" clearable />
      <n-button type="primary" :loading="loading" @click="search">查询</n-button>
    </div>
    <n-table striped :single-line="false" class="trace-table">
      <thead><tr><th>时间</th><th>Trace ID</th><th>Agent</th><th>状态</th><th>首 Token</th><th>总耗时</th><th>调用</th></tr></thead>
      <tbody>
        <tr v-for="row in rows" :key="row.trace_id" @click="openTrace(row.trace_id)">
          <td>{{ formatTime(row.timestamp) }}</td>
          <td class="trace-id">{{ row.trace_id }}</td>
          <td>{{ row.agent_id || '-' }}</td>
          <td><n-tag size="small" :type="statusType(row.status)">{{ row.status }}</n-tag></td>
          <td>{{ formatDuration(row.answer_first_token_ms) }}</td>
          <td>{{ formatDuration(row.total_duration_ms) }}</td>
          <td>LLM {{ row.llm_calls || 0 }} / Tool {{ row.tool_calls || 0 }}</td>
        </tr>
        <tr v-if="!loading && rows.length === 0"><td colspan="7" class="empty">暂无 Trace</td></tr>
      </tbody>
    </n-table>
    <n-pagination v-model:page="page" :page-size="20" :item-count="total" @update:page="load" />
  </n-card>
</template>

<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { listAgentTraces, type AgentTraceSummary } from '@/api/agent'
import { formatDuration } from '@/chat-core/formatters'

const router = useRouter()
const message = useMessage()
const today = new Date().toISOString().slice(0, 10)
const filters = reactive({ date_from: today, date_to: today, agent_id: '', status: null as string | null, model: '' })
const statusOptions = ['completed', 'failed', 'cancelled'].map(value => ({ label: value, value }))
const rows = ref<AgentTraceSummary[]>([])
const loading = ref(false)
const page = ref(1)
const total = ref(0)

async function load() {
  loading.value = true
  try {
    const result = await listAgentTraces({
      date_from: filters.date_from || undefined,
      date_to: filters.date_to || undefined,
      agent_id: filters.agent_id || undefined,
      status: filters.status || undefined,
      model: filters.model || undefined,
      page: page.value,
      page_size: 20,
    })
    rows.value = result.items
    total.value = result.total
  } catch (error) {
    message.error((error as Error).message || 'Trace 加载失败')
  } finally {
    loading.value = false
  }
}
function search() { page.value = 1; load() }
function openTrace(traceId: string) { router.push(`/agent-traces/${encodeURIComponent(traceId)}`) }
function formatTime(value?: string | null) { return value ? new Date(value).toLocaleString() : '-' }
function statusType(status: string) { return status === 'completed' ? 'success' : status === 'failed' ? 'error' : 'warning' }
onMounted(load)
</script>

<style scoped>
.filters { display: grid; grid-template-columns: repeat(5, minmax(130px, 1fr)) auto; gap: 10px; margin-bottom: 16px; }
.trace-table { margin-bottom: 16px; }
tbody tr { cursor: pointer; }
.trace-id { max-width: 220px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-family: monospace; }
.empty { text-align: center; color: var(--n-text-color-3); padding: 32px; }
@media (max-width: 1000px) { .filters { grid-template-columns: repeat(2, 1fr); } }
</style>
