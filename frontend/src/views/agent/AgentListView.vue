<template>
  <div class="page">
    <div class="page-header">
      <h2>Agent 管理</h2>
      <n-space align="center">
        <n-radio-group v-model:value="typeFilter" size="small" @update:value="onFilterChange">
          <n-radio-button value="">全部</n-radio-button>
          <n-radio-button value="simple_rag">简单 RAG</n-radio-button>
          <n-radio-button value="general">综合 Agent</n-radio-button>
        </n-radio-group>
        <n-button type="primary" @click="openCreate">
          <template #icon><n-icon><AddOutline /></n-icon></template>
          新建 Agent
        </n-button>
      </n-space>
    </div>

    <n-card>
      <!-- 批量操作栏 -->
      <div v-if="checkedRowKeys.length > 0" class="batch-bar">
        <span class="batch-tip">已选 {{ checkedRowKeys.length }} 项</span>
        <n-space>
          <n-button size="small" type="primary" @click="batchAction('enable')">批量启用</n-button>
          <n-button size="small" @click="batchAction('disable')">批量禁用</n-button>
          <n-popconfirm @positive-click="batchAction('delete')">
            <template #trigger><n-button size="small" type="error">批量删除</n-button></template>
            确定批量删除所选 Agent？
          </n-popconfirm>
          <n-button size="small" @click="checkedRowKeys = []">取消选择</n-button>
        </n-space>
      </div>

      <n-data-table
        :columns="columns"
        :data="list"
        :loading="loading"
        :pagination="false"
        :row-key="(row: AgentListItem) => row.id"
        :checked-row-keys="checkedRowKeys"
        @update:checked-row-keys="checkedRowKeys = $event"
      />

      <div class="pagination-wrap">
        <n-pagination
          v-model:page="page"
          :page-size="pageSize"
          :item-count="total"
          :page-sizes="[10, 20, 50]"
          show-size-picker
          @update:page="fetchList"
          @update:page-size="onPageSizeChange"
        />
      </div>
    </n-card>

    <!-- 创建/编辑弹窗 -->
    <AgentFormModal v-model:show="modalShow" :editing="editingAgent" @saved="fetchList" />
  </div>
</template>

<script setup lang="ts">
import { h, ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { NButton, NPopconfirm, NSpace, NIcon, NSwitch, NTag } from 'naive-ui'
import { AddOutline, CreateOutline, TrashOutline, ChatbubbleEllipsesOutline } from '@vicons/ionicons5'
import type { DataTableColumns } from 'naive-ui'
import {
  listAgents,
  batchAgents,
  getAgent,
  type AgentListItem,
  type AgentDetail,
  type AgentType,
} from '@/api/agent'
import AgentFormModal from './AgentFormModal.vue'

const router = useRouter()
const message = useMessage()

// ── 列表状态 ────────────────────────────
const loading = ref(false)
const list = ref<AgentListItem[]>([])
const page = ref(1)
const pageSize = ref(20)
const total = ref(0)
const typeFilter = ref<'' | AgentType>('')
const checkedRowKeys = ref<string[]>([])

// ── 弹窗状态 ────────────────────────────
const modalShow = ref(false)
const editingAgent = ref<AgentDetail | null>(null)

// ── 表格列 ──────────────────────────────
const columns: DataTableColumns<AgentListItem> = [
  { type: 'selection' },
  {
    title: '类型',
    key: 'type',
    width: 110,
    render(row) {
      return h(
        NTag,
        { size: 'small', type: row.type === 'simple_rag' ? 'primary' : 'warning', bordered: false },
        { default: () => (row.type === 'simple_rag' ? '简单 RAG' : '综合') },
      )
    },
  },
  { title: '名称', key: 'name', ellipsis: { tooltip: true } },
  {
    title: '知识库',
    key: 'kb',
    ellipsis: { tooltip: true },
    render(row) {
      if (row.type === 'simple_rag') return row.kb_name || '-'
      const names = row.tools.map(t => t.kb_name).filter(Boolean)
      return names.length ? names.join(', ') : '-'
    },
  },
  {
    title: 'LLM 模型',
    key: 'llm_model',
    width: 150,
    ellipsis: { tooltip: true },
    render(row) {
      return row.llm_model || '-'
    },
  },
  {
    title: '启用',
    key: 'status',
    width: 70,
    render(row) {
      return h(NSwitch, {
        value: row.status === 1,
        onUpdateValue: (val: boolean) => handleToggleStatus(row, val),
      })
    },
  },
  {
    title: '创建时间',
    key: 'created_at',
    width: 160,
    render(row) {
      return formatDate(row.created_at)
    },
  },
  {
    title: '操作',
    key: 'actions',
    width: 200,
    render(row) {
      return h(NSpace, {}, {
        default: () => [
          h(
            NButton,
            { size: 'small', type: 'primary', quaternary: true, onClick: () => router.push(`/agent/${row.id}/chat`) },
            { icon: () => h(NIcon, null, { default: () => h(ChatbubbleEllipsesOutline) }), default: () => '对话' },
          ),
          h(
            NButton,
            { size: 'small', quaternary: true, onClick: () => openEdit(row.id) },
            { icon: () => h(NIcon, null, { default: () => h(CreateOutline) }) },
          ),
          h(
            NPopconfirm,
            { onPositiveClick: () => handleDelete(row.id) },
            {
              trigger: () =>
                h(NButton, { size: 'small', quaternary: true, type: 'error' }, {
                  icon: () => h(NIcon, null, { default: () => h(TrashOutline) }),
                }),
              default: () => '确定删除该 Agent？',
            },
          ),
        ],
      })
    },
  },
]

// ── 数据获取 ────────────────────────────
async function fetchList() {
  loading.value = true
  try {
    const res = await listAgents(page.value, pageSize.value, typeFilter.value || undefined)
    list.value = res.items
    total.value = res.total
  } catch (e) {
    message.error((e as Error).message || '获取列表失败')
  } finally {
    loading.value = false
  }
}

function onFilterChange() {
  page.value = 1
  fetchList()
}

function onPageSizeChange(size: number) {
  pageSize.value = size
  page.value = 1
  fetchList()
}

// ── CRUD ────────────────────────────────
function openCreate() {
  editingAgent.value = null
  modalShow.value = true
}

async function openEdit(id: string) {
  try {
    editingAgent.value = await getAgent(id)
    modalShow.value = true
  } catch (e) {
    message.error((e as Error).message || '获取详情失败')
  }
}

async function handleDelete(id: string) {
  try {
    await batchAgents([id], 'delete')
    message.success('已删除')
    fetchList()
  } catch (e) {
    message.error((e as Error).message || '删除失败')
  }
}

async function handleToggleStatus(row: AgentListItem, enabled: boolean) {
  const old = row.status
  row.status = enabled ? 1 : 0
  try {
    await batchAgents([row.id], enabled ? 'enable' : 'disable')
    message.success(enabled ? '已启用' : '已禁用')
  } catch (e) {
    row.status = old
    message.error((e as Error).message || '操作失败')
  }
}

async function batchAction(action: 'enable' | 'disable' | 'delete') {
  if (checkedRowKeys.value.length === 0) return
  try {
    const res = await batchAgents([...checkedRowKeys.value], action)
    const label = { enable: '批量启用', disable: '批量禁用', delete: '批量删除' }[action]
    message.success(`${label}完成：成功 ${res.success_count}，失败 ${res.fail_count}`)
    checkedRowKeys.value = []
    fetchList()
  } catch (e) {
    message.error((e as Error).message || '批量操作失败')
  }
}

// ── 工具函数 ────────────────────────────
function formatDate(dateStr: string): string {
  if (!dateStr) return '-'
  const d = new Date(dateStr)
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`
}

onMounted(fetchList)
</script>

<style scoped>
.page {
  height: 100%;
}
.page-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 16px;
}
.page-header h2 {
  margin: 0;
  font-size: 20px;
}
.pagination-wrap {
  display: flex;
  justify-content: flex-end;
  margin-top: 16px;
}
.batch-bar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 10px 16px;
  margin-bottom: 12px;
  background: var(--n-color-embedded);
  border: 1px solid var(--n-border-color);
  border-radius: 4px;
}
.batch-tip {
  font-size: 14px;
  font-weight: 500;
}
</style>
