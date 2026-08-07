<template>
  <div class="page">
    <div class="page-header">
      <h2>知识库管理</h2>
      <n-button type="primary" @click="openCreate">
        <template #icon><n-icon><AddOutline /></n-icon></template>
        新建知识库
      </n-button>
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
            确定批量删除所选知识库？
          </n-popconfirm>
          <n-button size="small" @click="checkedRowKeys = []">取消选择</n-button>
        </n-space>
      </div>

      <n-data-table
        :columns="columns"
        :data="list"
        :loading="loading"
        :pagination="false"
        :row-key="(row: KnowledgeBaseListItem) => row.id"
        :row-props="rowProps"
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
    <n-modal
      v-model:show="modalShow"
      :title="modalTitle"
      preset="card"
      style="width: 560px"
      :mask-closable="false"
      @after-leave="resetForm"
    >
      <n-form
        ref="formRef"
        :model="formData"
        :rules="rules"
        label-placement="left"
        label-width="110"
        require-mark-placement="right-hanging"
      >
        <n-form-item label="名称" path="name">
          <n-input v-model:value="formData.name" placeholder="请输入知识库名称" />
        </n-form-item>
        <n-form-item label="描述" path="description">
          <n-input
            v-model:value="formData.description"
            type="textarea"
            placeholder="可选，输入知识库描述"
            :autosize="{ minRows: 2, maxRows: 4 }"
          />
        </n-form-item>
        <n-form-item label="允许的文件类型" path="allowed_extensions">
          <n-input
            v-model:value="formData.allowed_extensions"
            placeholder="如 .pdf,.txt,.docx，留空表示不限制"
          />
        </n-form-item>
        <n-form-item label="单文件大小上限(MB)" path="max_file_size">
          <n-input-number
            v-model:value="maxFileSizeMB"
            :min="1"
            :max="1024"
            placeholder="留空使用默认值"
            style="width: 100%"
          />
        </n-form-item>
        <n-form-item label="允许多次上传" path="allow_multiple">
          <n-switch v-model:value="formData.allow_multiple" />
        </n-form-item>
        <n-form-item label="Embedding 模型" path="embedding">
          <n-select
            v-model:value="formData.user_model_config_id"
            :options="embeddingOptions"
            placeholder="选择向量化模型"
          />
        </n-form-item>
      </n-form>

      <template #footer>
        <n-space justify="end">
          <n-button @click="modalShow = false">取消</n-button>
          <n-button type="primary" :loading="submitting" @click="handleSubmit">
            确定
          </n-button>
        </n-space>
      </template>
    </n-modal>
  </div>
</template>

<script setup lang="ts">
import { h, ref, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { NButton, NPopconfirm, NSpace, NIcon, NSwitch } from 'naive-ui'
import { AddOutline, CreateOutline, TrashOutline } from '@vicons/ionicons5'
import type { FormInst, FormRules, DataTableColumns } from 'naive-ui'
import {
  listKnowledgeBases,
  getKnowledgeBase,
  createKnowledgeBase,
  updateKnowledgeBase,
  batchKnowledgeBases,
  type KnowledgeBaseListItem,
  type KnowledgeBaseDetail,
  type KnowledgeBaseCreate,
  type BatchAction,
} from '@/api/knowledge'
import { listMyConfigs, type UserModelConfigItem } from '@/api/model-config'

const router = useRouter()
const message = useMessage()

// ── Embedding 模型选项 ──────────────────
const userModelConfigs = ref<UserModelConfigItem[]>([])

const embeddingOptions = computed(() => {
  return userModelConfigs.value
    .filter(c => c.model_type === 1 && c.is_active)
    .map(c => ({
      label: `${c.provider} / ${c.model_name}`,
      value: c.id,
    }))
})

// ── 列表状态 ────────────────────────────
const loading = ref(false)
const list = ref<KnowledgeBaseListItem[]>([])
const page = ref(1)
const pageSize = ref(20)
const total = ref(0)
const checkedRowKeys = ref<any[]>([])

// ── 行点击跳转 ──────────────────────────
function rowProps(row: KnowledgeBaseListItem) {
  return {
    style: 'cursor: pointer',
    onClick: (e: MouseEvent) => {
      const target = e.target as HTMLElement
      // 点击复选框/选择框时不跳转
      if (target.closest('.n-checkbox') || target.closest('.n-data-table-checkbox')) return
      router.push(`/knowledge/${row.id}`)
    },
  }
}

// ── 表格列定义 ──────────────────────────
const columns: DataTableColumns<KnowledgeBaseListItem> = [
  { type: 'selection' },
  { title: '名称', key: 'name', ellipsis: { tooltip: true } },
  {
    title: '允许类型',
    key: 'allowed_extensions',
    width: 180,
    ellipsis: { tooltip: true },
    render(row) {
      return row.allowed_extensions || '不限制'
    },
  },
  {
    title: '供应商',
    key: 'provider',
    width: 80,
    render(row) {
      if (!row.user_model_config_id) return '-'
      const cfg = userModelConfigs.value.find(c => c.id === row.user_model_config_id)
      return cfg?.provider || '-'
    },
  },
  {
    title: '向量模型',
    key: 'model',
    width: 180,
    ellipsis: { tooltip: true },
    render(row) {
      if (!row.user_model_config_id) return row.embedding_model || '-'
      const cfg = userModelConfigs.value.find(c => c.id === row.user_model_config_id)
      return cfg?.model_name || '-'
    },
  },
  {
    title: '启用',
    key: 'status',
    width: 80,
    render(row) {
      return h(NSwitch, {
        value: row.status === 1,
        onUpdateValue: (val: boolean) => handleToggleStatus(row.id, val),
        onClick: (e: Event) => e.stopPropagation(),
      })
    },
  },
  {
    title: '创建时间',
    key: 'created_at',
    width: 180,
    render(row) {
      return formatDate(row.created_at)
    },
  },
  {
    title: '操作',
    key: 'actions',
    width: 180,
    render(row) {
      return h(NSpace, { onClick: (e: Event) => e.stopPropagation() }, {
        default: () => [
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
                h(
                  NButton,
                  { size: 'small', quaternary: true, type: 'error' },
                  { icon: () => h(NIcon, null, { default: () => h(TrashOutline) }) },
                ),
              default: () => '确定删除该知识库？所有文件将被一并删除。',
            },
          ),
        ],
      })
    },
  },
]

// ── 表单状态 ────────────────────────────
const formRef = ref<FormInst>()
const modalShow = ref(false)
const submitting = ref(false)
const editingId = ref<string | null>(null)

const formData = ref<KnowledgeBaseCreate & { description: string; allowed_extensions: string; user_model_config_id: string | null }>({
  name: '',
  description: '',
  allowed_extensions: '',
  max_file_size: null,
  allow_multiple: true,
  user_model_config_id: null,
})

const maxFileSizeMB = ref<number | null>(null)

const rules: FormRules = {
  name: { required: true, message: '请输入知识库名称', trigger: 'blur' },
}

const modalTitle = computed(() => (editingId.value ? '编辑知识库' : '新建知识库'))

// ── 数据获取 ────────────────────────────
async function fetchList() {
  loading.value = true
  try {
    const res = await listKnowledgeBases(page.value, pageSize.value)
    list.value = res.items
    total.value = res.total
  } catch (e) {
    message.error((e as Error).message || '获取列表失败')
  } finally {
    loading.value = false
  }
}

function onPageSizeChange(size: number) {
  pageSize.value = size
  page.value = 1
  fetchList()
}

// ── CRUD 操作 ──────────────────────────
function openCreate() {
  editingId.value = null
  formData.value = {
    name: '', description: '', allowed_extensions: '',
    max_file_size: null, allow_multiple: true,
    user_model_config_id: userModelConfigs.value[0]?.id || null,
  }
  maxFileSizeMB.value = null
  modalShow.value = true
}

async function openEdit(id: string) {
  editingId.value = id
  try {
    const detail: KnowledgeBaseDetail = await getKnowledgeBase(id)
    formData.value = {
      name: detail.name,
      description: detail.description || '',
      allowed_extensions: detail.allowed_extensions || '',
      max_file_size: detail.max_file_size,
      allow_multiple: detail.allow_multiple,
      user_model_config_id: detail.user_model_config_id,
    }
    maxFileSizeMB.value = detail.max_file_size ? +(detail.max_file_size / 1048576).toFixed(2) : null
    modalShow.value = true
  } catch (e) {
    message.error((e as Error).message || '获取详情失败')
  }
}

async function handleSubmit() {
  try {
    await formRef.value?.validate()
  } catch {
    return
  }

  submitting.value = true
  try {
    const payload = {
      ...formData.value,
      max_file_size: maxFileSizeMB.value ? Math.round(maxFileSizeMB.value * 1048576) : null,
    }

    if (editingId.value) {
      await updateKnowledgeBase(editingId.value, payload)
      message.success('更新成功')
    } else {
      await createKnowledgeBase(payload)
      message.success('创建成功')
    }
    modalShow.value = false
    fetchList()
  } catch (e) {
    message.error((e as Error).message || '操作失败')
  } finally {
    submitting.value = false
  }
}

async function handleDelete(id: string) {
  try {
    await batchKnowledgeBases([id], 'delete')
    message.success('已删除')
    fetchList()
  } catch (e) {
    message.error((e as Error).message || '删除失败')
  }
}

async function handleToggleStatus(id: string, enabled: boolean) {
  const item = list.value.find(kb => kb.id === id)
  if (!item) return

  const oldStatus = item.status
  item.status = enabled ? 1 : 0

  try {
    await updateKnowledgeBase(id, { status: enabled ? 1 : 0 })
    message.success(enabled ? '已启用' : '已禁用')
  } catch (e) {
    item.status = oldStatus
    message.error((e as Error).message || '操作失败')
  }
}

async function batchAction(action: BatchAction) {
  if (checkedRowKeys.value.length === 0) return
  const ids = [...checkedRowKeys.value]
  try {
    const res = await batchKnowledgeBases(ids, action)
    const label = { enable: '批量启用', disable: '批量禁用', delete: '批量删除' }[action]
    message.success(`${label}完成：成功 ${res.success_count}，失败 ${res.fail_count}`)
    checkedRowKeys.value = []
    fetchList()
  } catch (e) {
    message.error((e as Error).message || '批量操作失败')
  }
}

function resetForm() {
  formRef.value?.restoreValidation()
  editingId.value = null
}

// ── 工具函数 ────────────────────────────
function formatDate(dateStr: string): string {
  if (!dateStr) return '-'
  const d = new Date(dateStr)
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`
}

async function fetchModelConfigs() {
  try { userModelConfigs.value = await listMyConfigs() } catch { /* */ }
}

onMounted(() => {
  fetchList()
  fetchModelConfigs()
})
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
