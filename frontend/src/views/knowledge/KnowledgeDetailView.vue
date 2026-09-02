<template>
  <div class="page">
    <!-- 返回 + 标题 -->
    <div class="page-header">
      <n-space align="center">
        <n-button text @click="$router.push('/knowledge')">
          <template #icon><n-icon><ArrowBackOutline /></n-icon></template>
        </n-button>
        <h2>{{ kbName }}</h2>
        <n-tag v-if="kbInfo" :type="kbInfo.status === 1 ? 'success' : 'default'" size="small">
          {{ kbInfo.status === 1 ? '启用' : '禁用' }}
        </n-tag>
      </n-space>
      <n-upload
        :action="uploadUrl"
        :headers="uploadHeaders"
        :multiple="kbInfo?.allow_multiple ?? false"
        :accept="acceptExtensions"
        :max-size="kbInfo?.max_file_size ?? undefined"
        :show-file-list="false"
        @finish="onUploadFinish"
        @error="onUploadError"
      >
        <n-button type="primary">
          <template #icon><n-icon><CloudUploadOutline /></n-icon></template>
          上传文件
        </n-button>
      </n-upload>
    </div>

    <!-- 知识库信息 -->
    <n-card v-if="kbInfo" title="基本信息" size="small" class="info-card">
      <n-descriptions :column="2" label-placement="left">
        <n-descriptions-item label="描述">{{ kbInfo.description || '无' }}</n-descriptions-item>
        <n-descriptions-item label="允许类型">{{ kbInfo.allowed_extensions || '不限制' }}</n-descriptions-item>
        <n-descriptions-item label="文件大小上限">{{ formatFileSize(kbInfo.max_file_size) }}</n-descriptions-item>
        <n-descriptions-item label="允许多次上传">{{ kbInfo.allow_multiple ? '是' : '否' }}</n-descriptions-item>
        <n-descriptions-item label="Embedding 模型">
          <template v-if="kbInfo.user_model_config_id">
            {{ embeddingLabel }}
          </template>
          <template v-else>
            本地默认 ({{ kbInfo.embedding_model }}, {{ kbInfo.embedding_dimension }}维)
          </template>
        </n-descriptions-item>
        <n-descriptions-item label="创建时间">{{ formatDate(kbInfo.created_at) }}</n-descriptions-item>
      </n-descriptions>
    </n-card>

    <!-- 文件列表 -->
    <n-card title="文件列表" class="file-card">
      <!-- 批量操作栏 -->
      <div v-if="checkedFileKeys.length > 0" class="batch-bar">
        <span class="batch-tip">已选 {{ checkedFileKeys.length }} 项</span>
        <n-space>
          <n-button size="small" type="primary" :loading="processing" @click="triggerParse">解析选中</n-button>
          <n-button size="small" type="primary" :loading="processing" @click="triggerChunk">分块选中</n-button>
          <n-button size="small" type="primary" :loading="processing" @click="triggerVectorize">向量化选中</n-button>
          <n-divider vertical />
          <n-popconfirm @positive-click="batchFilesAction">
            <template #trigger><n-button size="small" type="error">批量删除</n-button></template>
            确定批量删除所选文件？
          </n-popconfirm>
          <n-button size="small" @click="checkedFileKeys = []">取消选择</n-button>
        </n-space>
      </div>

      <n-data-table
        :columns="fileColumns"
        :data="fileList"
        :loading="fileLoading"
        :pagination="false"
        :row-key="(row: DocumentListItem) => row.id"
        :checked-row-keys="checkedFileKeys"
        @update:checked-row-keys="checkedFileKeys = $event"
      >
        <template #empty>
          <n-empty description="暂无文件，点击右上角上传" />
        </template>
      </n-data-table>

      <div v-if="fileTotal > 0" class="pagination-wrap">
        <n-pagination
          v-model:page="filePage"
          :page-size="filePageSize"
          :item-count="fileTotal"
          :page-sizes="[10, 20, 50]"
          show-size-picker
          @update:page="() => fetchFiles()"
          @update:page-size="onFilePageSizeChange"
        />
      </div>
    </n-card>
  </div>
</template>

<script setup lang="ts">
import { h, ref, computed, onMounted, onUnmounted } from 'vue'
import { useRoute } from 'vue-router'
import { NButton, NTag, NPopconfirm, NSpace, NIcon, NUpload } from 'naive-ui'
import { ArrowBackOutline, CloudUploadOutline, TrashOutline } from '@vicons/ionicons5'
import type { DataTableColumns } from 'naive-ui'
import {
  getKnowledgeBase,
  listFiles,
  batchFiles,
  parseDocuments,
  chunkDocuments,
  vectorizeDocuments,
  type KnowledgeBaseDetail,
  type DocumentListItem,
} from '@/api/knowledge'
import { listMyConfigs, type UserModelConfigItem } from '@/api/model-config'
import { storage } from '@/utils/storage'
import { TOKEN_KEY } from '@/api/request'

const route = useRoute()
const message = useMessage()
const kbId = computed(() => route.params.id as string)

// ── 知识库信息 ──────────────────────────
const kbInfo = ref<KnowledgeBaseDetail | null>(null)
const kbName = computed(() => kbInfo.value?.name || '知识库详情')
const modelConfigs = ref<UserModelConfigItem[]>([])
const embeddingLabel = computed(() => {
  if (!kbInfo.value?.user_model_config_id) return ''
  const cfg = modelConfigs.value.find(c => c.id === kbInfo.value!.user_model_config_id)
  return cfg ? `${cfg.provider} / ${cfg.model_name}` : kbInfo.value.user_model_config_id
})

// ── 文件列表 ────────────────────────────
const fileLoading = ref(false)
const fileList = ref<DocumentListItem[]>([])
const filePage = ref(1)
const filePageSize = ref(20)
const fileTotal = ref(0)
const checkedFileKeys = ref<any[]>([])
const processing = ref(false)

// ── 上传配置 ────────────────────────────
const uploadUrl = computed(() => `/api/v1/knowledge-bases/${kbId.value}/files`)
const uploadHeaders = computed(() => {
  const token = storage.get<string>(TOKEN_KEY)
  if (!token) return {} as Record<string, string>
  return { Authorization: `Bearer ${token}` } as Record<string, string>
})
const acceptExtensions = computed(() => {
  if (!kbInfo.value?.allowed_extensions) return undefined
  return kbInfo.value.allowed_extensions
    .split(',')
    .map((ext) => '.' + ext.trim().replace(/^\./, ''))
    .join(',')
})

// ── 表格列 ──────────────────────────────
const fileColumns: DataTableColumns<DocumentListItem> = [
  { type: 'selection' },
  { title: '文件名', key: 'filename', ellipsis: { tooltip: true } },
  {
    title: '大小',
    key: 'file_size',
    width: 120,
    render(row) {
      return formatFileSize(row.file_size)
    },
  },
  {
    title: '类型',
    key: 'file_type',
    width: 100,
    render(row) {
      return row.file_type || '-'
    },
  },
  {
    title: '解析',
    key: 'is_parsed',
    width: 90,
    render(row) {
      const map: Record<number, { type: 'default' | 'info' | 'success' | 'warning' | 'error'; label: string }> = {
        [-1]: { type: 'error', label: '失败' },
        0: { type: 'default', label: '未完成' },
        1: { type: 'success', label: '已完成' },
        2: { type: 'info', label: '进行中' },
      }
      const s = map[row.is_parsed] || { type: 'default' as const, label: '未知' }
      return h(NTag, { type: s.type, size: 'small' }, { default: () => s.label })
    },
  },
  {
    title: '切片',
    key: 'is_chunked',
    width: 90,
    render(row) {
      const map: Record<number, { type: 'default' | 'info' | 'success' | 'warning' | 'error'; label: string }> = {
        [-1]: { type: 'error', label: '失败' },
        0: { type: 'default', label: '未完成' },
        1: { type: 'success', label: '已完成' },
        2: { type: 'info', label: '进行中' },
      }
      const s = map[row.is_chunked] || { type: 'default' as const, label: '未知' }
      return h(NTag, { type: s.type, size: 'small' }, { default: () => s.label })
    },
  },
  {
    title: '向量化',
    key: 'is_vectorized',
    width: 90,
    render(row) {
      const map: Record<number, { type: 'default' | 'info' | 'success' | 'warning' | 'error'; label: string }> = {
        [-1]: { type: 'error', label: '失败' },
        0: { type: 'default', label: '未完成' },
        1: { type: 'success', label: '已完成' },
        2: { type: 'info', label: '进行中' },
      }
      const s = map[row.is_vectorized] || { type: 'default' as const, label: '未知' }
      return h(NTag, { type: s.type, size: 'small' }, { default: () => s.label })
    },
  },
  {
    title: '错误信息',
    key: 'last_error',
    width: 200,
    ellipsis: { tooltip: true },
    render(row) {
      if (!row.last_error) return '-'
      return h('span', { style: 'color: #d03050; font-size: 12px;' }, row.last_error)
    },
  },
  {
    title: '上传时间',
    key: 'created_at',
    width: 180,
    render(row) {
      return formatDate(row.created_at)
    },
  },
  {
    title: '操作',
    key: 'actions',
    width: 80,
    render(row) {
      return h(
        NPopconfirm,
        { onPositiveClick: () => handleDeleteFile(row.id) },
        {
          trigger: () =>
            h(
              NButton,
              { size: 'small', quaternary: true, type: 'error' },
              { icon: () => h(NIcon, null, { default: () => h(TrashOutline) }) },
            ),
          default: () => '确定删除该文件？',
        },
      )
    },
  },
]

// ── 数据获取 ────────────────────────────
async function fetchKnowledgeBase() {
  try {
    kbInfo.value = await getKnowledgeBase(kbId.value)
  } catch (e) {
    message.error((e as Error).message || '获取知识库信息失败')
  }
}

async function fetchFiles(silent = false) {
  if (!silent) fileLoading.value = true
  try {
    const res = await listFiles(kbId.value, filePage.value, filePageSize.value)
    fileList.value = res.items
    fileTotal.value = res.total
  } catch (e) {
    if (!silent) message.error((e as Error).message || '获取文件列表失败')
  } finally {
    if (!silent) fileLoading.value = false
  }
}

function onFilePageSizeChange(size: number) {
  filePageSize.value = size
  filePage.value = 1
  fetchFiles()
}

// ── 上传回调 ────────────────────────────

// 上传后自动处理轮询（后台任务执行中，轮询文件列表直到全部终态）
let autoPollTimer: ReturnType<typeof setInterval> | null = null

function hasProcessingFile(): boolean {
  return fileList.value.some(
    f => f.is_parsed === 2 || f.is_chunked === 2 || f.is_vectorized === 2
  )
}

function stopAutoPoll() {
  if (autoPollTimer) {
    clearInterval(autoPollTimer)
    autoPollTimer = null
  }
}

function startAutoPoll() {
  stopAutoPoll()
  autoPollTimer = setInterval(async () => {
    await fetchFiles(true)  // 静默刷新，不闪 loading
    if (!hasProcessingFile()) {
      stopAutoPoll()
    }
  }, 3000)
}

// eslint-disable-next-line @typescript-eslint/no-explicit-any
function onUploadFinish() {
  message.success('上传成功，后台自动处理中…')
  filePage.value = 1
  fetchFiles()
  startAutoPoll()
}

// eslint-disable-next-line @typescript-eslint/no-explicit-any
function onUploadError({ event }: any) {
  const xhr = event?.target as XMLHttpRequest
  let msg = '上传失败'
  if (xhr?.response) {
    try {
      const body = JSON.parse(xhr.response)
      msg = body.message || msg
    } catch { /* ignore */ }
  }
  message.error(msg)
}

// ── 删除文件 ────────────────────────────
async function handleDeleteFile(docId: string) {
  try {
    await batchFiles(kbId.value, [docId], 'delete')
    message.success('已删除')
    fetchFiles()
  } catch (e) {
    message.error((e as Error).message || '删除失败')
  }
}

async function batchFilesAction() {
  if (checkedFileKeys.value.length === 0) return
  const ids = [...checkedFileKeys.value]
  try {
    const res = await batchFiles(kbId.value, ids, 'delete')
    message.success(`批量删除完成：成功 ${res.success_count}，失败 ${res.fail_count}`)
    checkedFileKeys.value = []
    fetchFiles()
  } catch (e) {
    message.error((e as Error).message || '批量删除失败')
  }
}

async function triggerParse() {
  processing.value = true
  try {
    const res = await parseDocuments(kbId.value, checkedFileKeys.value)
    message.success(`解析完成：成功 ${res.processed} / ${res.total}`)
    fetchFiles()
  } catch (e) {
    message.error((e as Error).message || '解析失败')
  } finally {
    processing.value = false
  }
}

async function triggerChunk() {
  // 检查是否都已解析
  const unchecked = fileList.value.filter(
    f => checkedFileKeys.value.includes(f.id) && f.is_parsed !== 1
  )
  if (unchecked.length > 0) {
    message.warning(`有 ${unchecked.length} 个文件未解析，请先点击"解析选中"`)
    return
  }
  processing.value = true
  try {
    const res = await chunkDocuments(kbId.value, checkedFileKeys.value)
    message.success(`分块完成：成功 ${res.processed} / ${res.total}`)
    fetchFiles()
  } catch (e) {
    message.error((e as Error).message || '分块失败')
  } finally {
    processing.value = false
  }
}

async function triggerVectorize() {
  // 检查是否都已解析+分块
  const unchecked = fileList.value.filter(
    f => checkedFileKeys.value.includes(f.id) && (f.is_parsed !== 1 || f.is_chunked !== 1)
  )
  if (unchecked.length > 0) {
    message.warning(`有 ${unchecked.length} 个文件未准备就绪，请先完成"解析"和"分块"`)
    return
  }
  processing.value = true
  try {
    const res = await vectorizeDocuments(kbId.value, checkedFileKeys.value)
    message.success(`向量化完成：成功 ${res.processed} / ${res.total}`)
    fetchFiles()
  } catch (e) {
    message.error((e as Error).message || '向量化失败')
  } finally {
    processing.value = false
  }
}

// ── 工具 ────────────────────────────────
function formatFileSize(bytes: number): string {
  if (!bytes || bytes <= 0) return '-'
  const units = ['B', 'KB', 'MB', 'GB']
  let i = 0
  let size = bytes
  while (size >= 1024 && i < units.length - 1) {
    size /= 1024
    i++
  }
  return `${size.toFixed(i === 0 ? 0 : 2)} ${units[i]}`
}

function formatDate(dateStr: string): string {
  if (!dateStr) return '-'
  const d = new Date(dateStr)
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`
}

onMounted(() => {
  fetchKnowledgeBase()
  fetchFiles()
  listMyConfigs().then(list => { modelConfigs.value = list }).catch(() => {})
})

onUnmounted(() => {
  stopAutoPoll()
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

.info-card {
  margin-bottom: 16px;
}

.file-card {
  flex: 1;
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
