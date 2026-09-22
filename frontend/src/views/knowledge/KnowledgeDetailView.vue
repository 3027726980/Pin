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

    <n-card v-if="kbInfo" title="上传处理策略" size="small" class="strategy-summary-card">
      <n-space justify="space-between" align="center">
        <span>上传后自动处理</span>
        <n-switch v-model:value="strategyDraft.auto_process" @update:value="() => saveStrategy()" />
      </n-space>
      <p class="strategy-summary-hint">
        此开关只控制当前知识库；清洗与切片策略请点击任意文件，在预览中调整并对照效果。
      </p>
    </n-card>

    <!-- 文件列表 -->
    <n-card title="文件列表" class="file-card">
      <!-- 批量操作栏 -->
      <div v-if="checkedFileKeys.length > 0" class="batch-bar">
        <span class="batch-tip">已选 {{ checkedFileKeys.length }} 项</span>
        <n-space>
          <n-dropdown :options="processOptions" trigger="click" @select="handleProcessSelect">
            <n-button size="small" type="primary" :loading="processing">
              处理选中
              <template #icon><n-icon><ChevronDownOutline /></n-icon></template>
            </n-button>
          </n-dropdown>
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

    <n-drawer v-model:show="previewVisible" :width="1120">
      <n-drawer-content :title="preview ? `${preview.filename} · 清洗与切片预览` : '文件预览'" closable>
        <n-spin :show="previewLoading">
          <template v-if="preview">
            <n-alert type="info" :show-icon="false" class="preview-notice">
              本预览只在内存中运行，确认效果后再点击“一键处理选中”写入知识库。
            </n-alert>
            <n-alert v-for="warning in preview.warnings" :key="warning" type="warning" :show-icon="false" class="preview-notice">
              {{ warning }}
            </n-alert>
            <div class="preview-layout">
              <section class="preview-strategy">
                <h3>当前知识库策略</h3>
                <n-form label-placement="top" size="small">
                  <n-form-item label="上传后自动处理">
                    <n-switch v-model:value="strategyDraft.auto_process" />
                  </n-form-item>
                  <n-form-item label="单片长度（字符）">
                    <n-input-number v-model:value="strategyDraft.chunk_size" :min="50" :max="10000" style="width: 100%" />
                  </n-form-item>
                  <n-form-item label="相邻片重叠（字符）">
                    <n-input-number
                      v-model:value="strategyDraft.chunk_overlap"
                      :min="0"
                      :max="Math.max(0, strategyDraft.chunk_size - 1)"
                      style="width: 100%"
                    />
                  </n-form-item>
                  <n-form-item label="分隔符优先级（逗号分隔）">
                    <n-input
                      v-model:value="strategyDraft.chunk_separators"
                      class="separator-input"
                      type="textarea"
                      :autosize="false"
                      :resizable="false"
                      :rows="6"
                      placeholder="例如：标题、换行、句号、空格"
                    />
                  </n-form-item>
                  <n-form-item label="清洗规则">
                    <div class="cleaning-rules">
                      <n-space v-for="(rule, index) in strategyDraft.cleaning_config.rules" :key="index" vertical size="small" class="cleaning-rule-row">
                        <n-space align="center">
                          <n-select v-model:value="rule.type" :options="cleaningRuleOptions" style="width: 190px" />
                          <n-switch v-model:value="rule.enabled" size="small" />
                          <n-button quaternary type="error" @click="removeCleaningRule(index)">删除</n-button>
                        </n-space>
                        <n-input
                          v-if="rule.type === 'replace_text' || rule.type === 'regex_remove'"
                          v-model:value="rule.value"
                          :placeholder="rule.type === 'regex_remove' ? '要删除的正则' : '要替换的文本'"
                        />
                        <n-input
                          v-if="rule.type === 'replace_text' || rule.type === 'regex_remove'"
                          v-model:value="rule.replacement"
                          placeholder="替换为（留空即删除）"
                        />
                        <n-input-number
                          v-if="rule.type === 'collapse_blank_lines'"
                          v-model:value="rule.max_consecutive"
                          :min="1"
                          :max="5"
                          style="width: 100%"
                        />
                      </n-space>
                      <n-button dashed size="small" @click="addCleaningRule">添加清洗规则</n-button>
                    </div>
                  </n-form-item>
                  <n-button type="primary" block :loading="strategySaving" @click="() => saveStrategy()">保存策略并刷新预览</n-button>
                </n-form>
              </section>
              <section class="preview-results">
                <n-tabs type="line" animated>
                  <n-tab-pane name="comparison" tab="原文与清洗对照">
                    <div class="text-comparison">
                      <section class="comparison-pane">
                        <h4>刚解析的原文</h4>
                        <pre class="preview-content comparison-content">{{ preview.raw_content }}</pre>
                      </section>
                      <section class="comparison-pane">
                        <h4>清洗后的文本</h4>
                        <pre class="preview-content comparison-content">{{ preview.cleaned_content }}</pre>
                      </section>
                    </div>
                  </n-tab-pane>
                  <n-tab-pane name="chunks" :tab="`切片（${preview.chunks.length}）`">
                    <n-empty v-if="preview.chunks.length === 0" description="清洗后没有可展示的切片" />
                    <n-collapse v-else>
                      <n-collapse-item
                        v-for="chunk in pagedPreviewChunks"
                        :key="chunk.index"
                        :title="`片段 ${chunk.index + 1} · ${chunk.char_count} 字符 · ${chunk.index === 0 ? '不与前片重叠' : `与上一片重叠 ${chunk.overlap_char_count} 字符`}`"
                        :name="String(chunk.index)"
                      >
                        <pre class="preview-content">{{ chunk.content }}</pre>
                      </n-collapse-item>
                    </n-collapse>
                    <div v-if="preview.chunks.length > chunkPreviewPageSize" class="chunk-pagination-wrap">
                      <n-pagination
                        v-model:page="chunkPreviewPage"
                        :page-size="chunkPreviewPageSize"
                        :item-count="preview.chunks.length"
                        :page-sizes="[5, 10, 20]"
                        show-size-picker
                        @update:page-size="onChunkPreviewPageSizeChange"
                      />
                    </div>
                  </n-tab-pane>
                </n-tabs>
              </section>
            </div>
          </template>
        </n-spin>
      </n-drawer-content>
    </n-drawer>
  </div>
</template>

<script setup lang="ts">
import { h, ref, computed, onMounted, onUnmounted } from 'vue'
import { useRoute } from 'vue-router'
import { NButton, NTag, NPopconfirm, NSpace, NIcon, NUpload } from 'naive-ui'
import { ArrowBackOutline, ChevronDownOutline, CloudUploadOutline, TrashOutline } from '@vicons/ionicons5'
import type { DataTableColumns } from 'naive-ui'
import {
  getKnowledgeBase,
  listFiles,
  batchFiles,
  previewDocument,
  processDocuments,
  updateKnowledgeBase,
  type CleaningConfig,
  type CleaningRule,
  type CleaningRuleType,
  type KnowledgeBaseDetail,
  type DocumentListItem,
  type DocumentPreview,
  type ProcessTarget,
} from '@/api/knowledge'
import { listMyConfigs, type UserModelConfigItem } from '@/api/model-config'
import { storage } from '@/utils/storage'
import { TOKEN_KEY } from '@/api/request'
import { useProcessingStore } from '@/stores/processing'

const route = useRoute()
const message = useMessage()
const procStore = useProcessingStore()
const kbId = computed(() => route.params.id as string)

// ── 知识库信息 ──────────────────────────
const kbInfo = ref<KnowledgeBaseDetail | null>(null)
const kbName = computed(() => kbInfo.value?.name || '知识库详情')
const strategySaving = ref(false)
const strategyDraft = ref({
  auto_process: false,
  chunk_size: 800,
  chunk_overlap: 150,
  chunk_separators: '',
  cleaning_config: { rules: [] } as CleaningConfig,
})
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
const previewVisible = ref(false)
const previewLoading = ref(false)
const preview = ref<DocumentPreview | null>(null)
const previewDocumentId = ref<string | null>(null)
let previewLoadSeq = 0
const chunkPreviewPage = ref(1)
const chunkPreviewPageSize = ref(10)
const pagedPreviewChunks = computed(() => {
  const chunks = preview.value?.chunks || []
  const start = (chunkPreviewPage.value - 1) * chunkPreviewPageSize.value
  return chunks.slice(start, start + chunkPreviewPageSize.value)
})

function cloneCleaningConfig(config: CleaningConfig): CleaningConfig {
  // Vue 的响应式 Proxy 不能直接 structuredClone；清洗规则本身是受限 JSON 数据。
  return JSON.parse(JSON.stringify(config)) as CleaningConfig
}

function buildSavedStrategyKey() {
  return {
    chunk_size: strategyDraft.value.chunk_size,
    chunk_overlap: strategyDraft.value.chunk_overlap,
    chunk_separators: strategyDraft.value.chunk_separators,
    cleaning_config: strategyDraft.value.cleaning_config,
  }
}

function buildSavedStrategyFingerprint() {
  return JSON.stringify(buildSavedStrategyKey())
}

const cleaningRuleOptions: Array<{ label: string; value: CleaningRuleType }> = [
  { label: 'Unicode 规范化', value: 'normalize_unicode' },
  { label: '移除控制字符', value: 'remove_control_chars' },
  { label: '折叠连续空行', value: 'collapse_blank_lines' },
  { label: '去除行首尾空白', value: 'trim_lines' },
  { label: '折叠重复标点', value: 'collapse_punctuation' },
  { label: '文本替换', value: 'replace_text' },
  { label: '正则删除', value: 'regex_remove' },
]

const processOptions: Array<{ label: string; key: ProcessTarget }> = [
  { label: '完整处理（至向量化）', key: 'vectorize' },
  { label: '处理至切片（自动先解析、清洗）', key: 'chunk' },
  { label: '处理至清洗（自动先解析）', key: 'clean' },
  { label: '仅解析', key: 'parse' },
]

// fetch 竞态守卫：只有最新一次请求的结果能更新列表（旧响应到达时丢弃）
let fileFetchSeq = 0
// loading 控制：仅非静默请求参与（静默轮询不得抢 loading 控制权，也不得使非静默请求的复位失效）
let visibleFetchSeq = 0

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
  {
    title: '文件名',
    key: 'filename',
    ellipsis: { tooltip: true },
    render(row) {
      return h(NButton, {
        text: true,
        type: 'primary',
        onClick: () => openPreview(row),
      }, { default: () => row.filename })
    },
  },
  {
    title: '状态',
    key: 'status_summary',
    width: 90,
    render(row) {
      const { is_parsed: p, is_cleaned: clean, is_chunked: c, is_vectorized: v } = row
      if (p === -1 || clean === -1 || c === -1 || v === -1) {
        return h(NTag, { type: 'error', size: 'small' }, { default: () => '失败' })
      }
      if (p === 2 && clean === 2 && c === 2 && v === 2) {
        return h(NTag, { type: 'default', size: 'small' }, { default: () => '排队中' })
      }
      if (p === 2 || clean === 2 || c === 2 || v === 2) {
        return h(NTag, { type: 'info', size: 'small' }, { default: () => '处理中' })
      }
      if (p === 1 && clean === 1 && c === 1 && v === 1) {
        return h(NTag, { type: 'success', size: 'small' }, { default: () => '已完成' })
      }
      return h(NTag, { size: 'small', bordered: false }, { default: () => '未处理' })
    },
  },
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
    title: '清洗',
    key: 'is_cleaned',
    width: 90,
    render(row) {
      return renderProcessState(row.is_cleaned)
    },
  },
  {
    title: '切片',
    key: 'is_chunked',
    width: 90,
    render(row) {
      return renderProcessState(row.is_chunked)
    },
  },
  {
    title: '向量化',
    key: 'is_vectorized',
    width: 90,
    render(row) {
      return renderProcessState(row.is_vectorized)
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
    const detail = await getKnowledgeBase(kbId.value)
    kbInfo.value = detail
    strategyDraft.value = {
      auto_process: detail.auto_process,
      chunk_size: detail.chunk_size,
      chunk_overlap: detail.chunk_overlap,
      chunk_separators: detail.chunk_separators,
      cleaning_config: structuredClone(detail.cleaning_config || { rules: [] }),
    }
  } catch (e) {
    message.error((e as Error).message || '获取知识库信息失败')
  }
}

function createCleaningRule(type: CleaningRuleType = 'trim_lines'): CleaningRule {
  return { type, enabled: true, replacement: '', max_consecutive: 1 }
}

function addCleaningRule() {
  strategyDraft.value.cleaning_config.rules.push(createCleaningRule())
}

function removeCleaningRule(index: number) {
  strategyDraft.value.cleaning_config.rules.splice(index, 1)
}

async function saveStrategy() {
  if (strategyDraft.value.chunk_overlap >= strategyDraft.value.chunk_size) {
    message.warning('切片重叠必须小于单片长度')
    return
  }
  const requestedStrategyKey = buildSavedStrategyFingerprint()
  const payload = {
    auto_process: strategyDraft.value.auto_process,
    ...buildSavedStrategyKey(),
    cleaning_config: cloneCleaningConfig(strategyDraft.value.cleaning_config),
  }
  strategySaving.value = true
  try {
    const updated = await updateKnowledgeBase(kbId.value, payload)
    kbInfo.value = updated
    const draftChangedDuringSave = buildSavedStrategyFingerprint() !== requestedStrategyKey
    if (!draftChangedDuringSave) {
      strategyDraft.value = {
        auto_process: updated.auto_process,
        chunk_size: updated.chunk_size,
        chunk_overlap: updated.chunk_overlap,
        chunk_separators: updated.chunk_separators,
        cleaning_config: structuredClone(updated.cleaning_config || { rules: [] }),
      }
    }
    message.success('处理策略已保存')
    if (!draftChangedDuringSave && previewDocumentId.value) await loadPreview(previewDocumentId.value)
  } catch (e) {
    message.error((e as Error).message || '保存处理策略失败')
  } finally {
    strategySaving.value = false
  }
}

function onChunkPreviewPageSizeChange(size: number) {
  chunkPreviewPageSize.value = size
  chunkPreviewPage.value = 1
}

async function fetchFiles(silent = false) {
  const seq = ++fileFetchSeq
  if (!silent) {
    visibleFetchSeq = seq
    fileLoading.value = true
  }
  try {
    const res = await listFiles(kbId.value, filePage.value, filePageSize.value)
    if (seq !== fileFetchSeq) return  // 过期响应丢弃（如上传后立即刷新 vs 轮询刷新 的竞态）
    fileList.value = res.items
    fileTotal.value = res.total
  } catch (e) {
    if (seq === fileFetchSeq && !silent) message.error((e as Error).message || '获取文件列表失败')
  } finally {
    // 非静默请求负责关闭 loading；仅当没有更新的非静默请求时（旧的非静默响应不得关掉新请求的 loading）
    if (!silent && seq === visibleFetchSeq) fileLoading.value = false
  }
}

function onFilePageSizeChange(size: number) {
  filePageSize.value = size
  filePage.value = 1
  fetchFiles()
}

// ── 上传回调 ────────────────────────────

// 手动或自动入队后的本页静默轮询。
let processPollTimer: ReturnType<typeof setInterval> | null = null

function hasProcessingFile(): boolean {
  return fileList.value.some(
    f => f.is_parsed === 2 || f.is_cleaned === 2 || f.is_chunked === 2 || f.is_vectorized === 2
  )
}

function stopProcessPoll() {
  if (processPollTimer) {
    clearInterval(processPollTimer)
    processPollTimer = null
  }
}

function startProcessPoll() {
  stopProcessPoll()
  processPollTimer = setInterval(async () => {
    await fetchFiles(true)  // 静默刷新，不闪 loading
    if (!hasProcessingFile()) {
      stopProcessPoll()
    }
  }, 2000)
}

// eslint-disable-next-line @typescript-eslint/no-explicit-any
function onUploadFinish() {
  void refreshAfterUpload()
}

async function refreshAfterUpload() {
  message.success('上传成功，点击文件可预览并调整处理策略')
  filePage.value = 1
  await fetchFiles()
  if (kbInfo.value?.auto_process) {
    procStore.startPolling()
    startProcessPoll()
  }
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

async function openPreview(row: DocumentListItem) {
  previewVisible.value = true
  previewDocumentId.value = row.id
  preview.value = null
  await loadPreview(row.id)
}

async function loadPreview(docId: string) {
  const seq = ++previewLoadSeq
  previewLoading.value = true
  try {
    const result = await previewDocument(kbId.value, docId)
    if (seq !== previewLoadSeq) return
    preview.value = result
    chunkPreviewPage.value = 1
  } catch (e) {
    if (seq === previewLoadSeq) message.error((e as Error).message || '预览生成失败')
  } finally {
    if (seq === previewLoadSeq) previewLoading.value = false
  }
}

function handleProcessSelect(key: string | number) {
  void triggerProcess(key as ProcessTarget)
}

async function triggerProcess(targetStage: ProcessTarget = 'vectorize') {
  if (checkedFileKeys.value.length === 0) return
  processing.value = true
  try {
    const res = await processDocuments(kbId.value, checkedFileKeys.value as string[], targetStage)
    const label = processOptions.find(option => option.key === targetStage)?.label || '处理'
    message.success(`已加入“${label}”队列：${res.processed} 个文件`)
    checkedFileKeys.value = []
    fetchFiles()
    procStore.startPolling()
    startProcessPoll()
  } catch (e) {
    message.error((e as Error).message || '一键处理入队失败')
  } finally {
    processing.value = false
  }
}

function renderProcessState(value: number) {
  const map: Record<number, { type: 'default' | 'info' | 'success' | 'warning' | 'error'; label: string }> = {
    [-1]: { type: 'error', label: '失败' },
    0: { type: 'default', label: '未完成' },
    1: { type: 'success', label: '已完成' },
    2: { type: 'info', label: '进行中' },
  }
  const state = map[value] || { type: 'default' as const, label: '未知' }
  return h(NTag, { type: state.type, size: 'small' }, { default: () => state.label })
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
  stopProcessPoll()
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

.strategy-summary-card {
  margin-bottom: 16px;
}

.strategy-summary-hint {
  margin: 10px 0 0;
  color: var(--n-text-color-3);
  font-size: 13px;
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

.preview-notice {
  margin-bottom: 12px;
}

.preview-content {
  margin: 0;
  white-space: pre-wrap;
  word-break: break-word;
  font-family: var(--n-font-family-mono);
  line-height: 1.65;
}

.preview-layout {
  display: flex;
  gap: 16px;
  min-height: 560px;
}

.preview-strategy {
  flex: 0 0 330px;
  overflow-y: auto;
  padding-right: 16px;
  border-right: 1px solid var(--n-border-color);
}

.preview-strategy h3 {
  margin: 0 0 12px;
  font-size: 15px;
}

.preview-results {
  min-width: 0;
  flex: 1;
}

.separator-input :deep(textarea) {
  overflow-y: auto !important;
  resize: none;
}

.text-comparison {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px;
}

.comparison-pane {
  min-width: 0;
  overflow: hidden;
  border: 1px solid var(--n-border-color);
  border-radius: 4px;
}

.comparison-pane h4 {
  margin: 0;
  padding: 10px 12px;
  font-size: 14px;
  background: var(--n-color-embedded);
  border-bottom: 1px solid var(--n-border-color);
}

.comparison-content {
  max-height: 560px;
  overflow: auto;
  padding: 12px;
}

.chunk-pagination-wrap {
  display: flex;
  justify-content: flex-end;
  margin-top: 16px;
}

.cleaning-rules {
  width: 100%;
}

.cleaning-rule-row {
  width: 100%;
  margin-bottom: 10px;
  padding: 8px;
  border: 1px solid var(--n-border-color);
  border-radius: 4px;
}

@media (max-width: 900px) {
  .preview-layout {
    flex-direction: column;
  }

  .preview-strategy {
    flex-basis: auto;
    padding-right: 0;
    padding-bottom: 16px;
    border-right: 0;
    border-bottom: 1px solid var(--n-border-color);
  }

  .text-comparison {
    grid-template-columns: 1fr;
  }
}
</style>
