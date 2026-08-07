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
      <n-descriptions :column="3" label-placement="left">
        <n-descriptions-item label="描述">{{ kbInfo.description || '无' }}</n-descriptions-item>
        <n-descriptions-item label="允许类型">{{ kbInfo.allowed_extensions || '不限制' }}</n-descriptions-item>
        <n-descriptions-item label="文件大小上限">{{ formatFileSize(kbInfo.max_file_size) }}</n-descriptions-item>
        <n-descriptions-item label="允许多次上传">{{ kbInfo.allow_multiple ? '是' : '否' }}</n-descriptions-item>
        <n-descriptions-item label="创建时间">{{ formatDate(kbInfo.created_at) }}</n-descriptions-item>
      </n-descriptions>
    </n-card>

    <!-- 文件列表 -->
    <n-card title="文件列表" class="file-card">
      <n-data-table
        :columns="fileColumns"
        :data="fileList"
        :loading="fileLoading"
        :pagination="false"
        :row-key="(row: DocumentListItem) => row.id"
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
          @update:page="fetchFiles"
          @update:page-size="onFilePageSizeChange"
        />
      </div>
    </n-card>
  </div>
</template>

<script setup lang="ts">
import { h, ref, computed, onMounted } from 'vue'
import { useRoute } from 'vue-router'
import { NButton, NTag, NPopconfirm, NSpace, NIcon, NUpload } from 'naive-ui'
import { ArrowBackOutline, CloudUploadOutline, TrashOutline } from '@vicons/ionicons5'
import type { DataTableColumns } from 'naive-ui'
import {
  getKnowledgeBase,
  listFiles,
  deleteFile,
  type KnowledgeBaseDetail,
  type DocumentListItem,
} from '@/api/knowledge'
import { storage } from '@/utils/storage'
import { TOKEN_KEY } from '@/api/request'

const route = useRoute()
const message = useMessage()
const kbId = computed(() => route.params.id as string)

// ── 知识库信息 ──────────────────────────
const kbInfo = ref<KnowledgeBaseDetail | null>(null)
const kbName = computed(() => kbInfo.value?.name || '知识库详情')

// ── 文件列表 ────────────────────────────
const fileLoading = ref(false)
const fileList = ref<DocumentListItem[]>([])
const filePage = ref(1)
const filePageSize = ref(20)
const fileTotal = ref(0)

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

async function fetchFiles() {
  fileLoading.value = true
  try {
    const res = await listFiles(kbId.value, filePage.value, filePageSize.value)
    fileList.value = res.items
    fileTotal.value = res.total
  } catch (e) {
    message.error((e as Error).message || '获取文件列表失败')
  } finally {
    fileLoading.value = false
  }
}

function onFilePageSizeChange(size: number) {
  filePageSize.value = size
  filePage.value = 1
  fetchFiles()
}

// ── 上传回调 ────────────────────────────
// eslint-disable-next-line @typescript-eslint/no-explicit-any
function onUploadFinish() {
  message.success('上传成功')
  filePage.value = 1
  fetchFiles()
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
    await deleteFile(kbId.value, docId)
    message.success('已删除')
    fetchFiles()
  } catch (e) {
    message.error((e as Error).message || '删除失败')
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
</style>
