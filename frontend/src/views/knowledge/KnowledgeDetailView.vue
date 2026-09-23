<template>
  <div class="page">
    <div class="page-header">
      <n-space align="center">
        <n-button text @click="$router.push('/knowledge')"><template #icon><n-icon><ArrowBackOutline /></n-icon></template></n-button>
        <h2>{{ kbName }}</h2>
        <n-tag v-if="kbInfo" :type="kbInfo.status === 1 ? 'success' : 'default'" size="small">{{ kbInfo.status === 1 ? '启用' : '禁用' }}</n-tag>
      </n-space>
      <n-upload :action="uploadUrl" :headers="uploadHeaders" :multiple="kbInfo?.allow_multiple ?? false" :accept="acceptExtensions" :max-size="kbInfo?.max_file_size" :show-file-list="false" @finish="onUploadFinish" @error="onUploadError">
        <n-button type="primary"><template #icon><n-icon><CloudUploadOutline /></n-icon></template>上传文件</n-button>
      </n-upload>
    </div>

    <n-card v-if="kbInfo" title="基本信息" size="small" class="section-card">
      <n-descriptions :column="2" label-placement="left">
        <n-descriptions-item label="描述">{{ kbInfo.description || '无' }}</n-descriptions-item>
        <n-descriptions-item label="允许类型">{{ kbInfo.allowed_extensions || '不限制' }}</n-descriptions-item>
        <n-descriptions-item label="文件大小上限">{{ formatFileSize(kbInfo.max_file_size) }}</n-descriptions-item>
        <n-descriptions-item label="允许多次上传">{{ kbInfo.allow_multiple ? '是' : '否' }}</n-descriptions-item>
        <n-descriptions-item label="Embedding 模型">{{ embeddingLabel }}</n-descriptions-item>
        <n-descriptions-item label="创建时间">{{ formatDate(kbInfo.created_at) }}</n-descriptions-item>
      </n-descriptions>
    </n-card>

    <n-card v-if="kbInfo" size="small" class="section-card strategy-summary">
      <div class="strategy-summary-content">
        <div>
          <strong>默认处理策略</strong>
          <n-space size="small" align="center" class="strategy-summary-meta">
            <n-tag :type="kbInfo.auto_process ? 'success' : 'default'" size="small">自动处理：{{ kbInfo.auto_process ? '开启' : '关闭' }}</n-tag>
            <span>单片 {{ kbInfo.chunk_size }} 字符</span>
            <span>重叠 {{ kbInfo.chunk_overlap }} 字符</span>
            <n-tag v-if="strategyLocked" type="warning" size="small">处理中，暂不可修改</n-tag>
          </n-space>
        </div>
        <n-button type="primary" secondary @click="openStrategyDrawer">查看/设置</n-button>
      </div>
    </n-card>

    <n-card title="文件列表">
      <div v-if="checkedFileKeys.length" class="batch-bar">
        <span>已选 {{ checkedFileKeys.length }} 项</span>
        <n-space>
          <n-dropdown :options="processOptions" trigger="click" @select="handleProcessSelect"><n-button size="small" type="primary" :loading="processing">处理选中</n-button></n-dropdown>
          <n-popconfirm @positive-click="batchFilesAction"><template #trigger><n-button size="small" type="error">批量删除</n-button></template>确定批量删除所选文件？</n-popconfirm>
          <n-button size="small" @click="checkedFileKeys = []">取消选择</n-button>
        </n-space>
      </div>
      <n-data-table :columns="fileColumns" :data="fileList" :loading="fileLoading" :pagination="false" :row-key="(row: DocumentListItem) => row.id" :checked-row-keys="checkedFileKeys" @update:checked-row-keys="checkedFileKeys = $event">
        <template #empty><n-empty description="暂无文件，点击右上角上传" /></template>
      </n-data-table>
      <div v-if="fileTotal" class="pagination"><n-pagination v-model:page="filePage" :page-size="filePageSize" :item-count="fileTotal" :page-sizes="[10, 20, 50]" show-size-picker @update:page="() => fetchFiles()" @update:page-size="onFilePageSizeChange" /></div>
    </n-card>

    <n-drawer v-model:show="strategyDrawerVisible" :width="520" @after-leave="resetKnowledgeStrategy">
      <n-drawer-content title="知识库默认处理策略" closable>
        <n-alert v-if="strategyLocked" type="warning" :show-icon="false" class="notice">当前知识库有文件正在处理，任务结束前不能修改处理策略。</n-alert>
        <div class="auto-row">
          <div><strong>上传后自动处理</strong><p>新上传文件会继承此策略并自动处理至向量化。</p></div>
          <n-switch v-model:value="autoProcessDraft" :disabled="strategyLocked" />
        </div>
        <ProcessingStrategyForm v-model="knowledgeStrategyDraft" :disabled="strategyLocked" />
        <p class="hint strategy-drawer-hint">保存不会重建已有索引；文件会标记为“待重新处理”，处理成功后才替换旧切片。</p>
        <template #footer>
          <n-space justify="end">
            <n-button :disabled="strategyLocked || strategySaving" @click="resetKnowledgeStrategy">放弃修改</n-button>
            <n-button type="primary" :loading="strategySaving" :disabled="strategyLocked" @click="saveKnowledgeStrategyFromDrawer">保存默认策略</n-button>
          </n-space>
        </template>
      </n-drawer-content>
    </n-drawer>

    <n-drawer v-model:show="previewVisible" width="min(1180px, 100vw)">
      <n-drawer-content
        :title="previewRow ? `${previewRow.filename} · 预览与重新处理` : '文件预览'"
        body-content-class="preview-drawer-body"
        body-content-style="height: 100%; overflow: hidden;"
        closable
      >
        <n-spin :show="previewLoading" class="preview-spin">
          <n-alert v-if="previewVersionError" type="error" :show-icon="false" class="notice">{{ previewVersionError }}</n-alert>
          <n-alert v-for="warning in previewSource?.warnings || []" :key="warning" type="warning" :show-icon="false" class="notice">{{ warning }}</n-alert>
          <n-alert v-if="previewError" type="error" :show-icon="false" class="notice">本地预览计算失败：{{ previewError }}。已保留上一次成功结果。</n-alert>
          <div v-if="previewRow && previewSource" class="preview-layout">
            <section class="preview-strategy">
              <h3>当前文件策略</h3>
              <n-radio-group :value="fileStrategyMode" :disabled="strategyLocked" @update:value="setFileStrategyMode">
                <n-space vertical><n-radio value="inherit">继承知识库默认策略</n-radio><n-radio value="custom">仅此文件使用独立策略</n-radio></n-space>
              </n-radio-group>
              <n-alert type="info" :show-icon="false" class="scope-notice">{{ fileStrategyMode === 'inherit' ? '修改会同步到知识库默认策略草稿。' : '修改只影响当前文件。' }}</n-alert>
              <ProcessingStrategyForm v-model="activePreviewStrategy" :disabled="strategyLocked || !!previewVersionError" />
              <n-space vertical class="drawer-actions">
                <n-button block :loading="strategySaving" :disabled="strategyLocked || !!previewVersionError" @click="saveCurrentFileStrategy">仅保存策略</n-button>
                <n-button block type="primary" :loading="processing" :disabled="strategyLocked || !!previewVersionError" @click="saveAndReprocessCurrentFile">保存并重新处理此文件</n-button>
              </n-space>
            </section>
            <section class="preview-source-column">
              <h3>原文</h3>
              <pre class="preview-content text-pane">{{ previewSource.raw_content }}</pre>
            </section>
            <section class="preview-result-column">
              <n-tabs type="line" animated default-value="cleaned">
                <n-tab-pane name="cleaned" tab="清洗结果"><pre class="preview-content text-pane">{{ localPreview?.cleanedText || '' }}</pre></n-tab-pane>
                <n-tab-pane name="draft" :tab="`草稿切片（${localPreview?.chunks.length || 0}）`">
                  <n-empty v-if="!localPreview?.chunks.length" description="清洗后没有可展示的草稿切片" />
                  <n-collapse v-else><n-collapse-item v-for="chunk in pagedDraftChunks" :key="chunk.index" :title="draftChunkTitle(chunk)" :name="`draft-${chunk.index}`"><pre class="preview-content">{{ chunk.content }}</pre></n-collapse-item></n-collapse>
                  <div v-if="(localPreview?.chunks.length || 0) > draftPageSize" class="pagination"><n-pagination v-model:page="draftPage" :page-size="draftPageSize" :item-count="localPreview?.chunks.length || 0" /></div>
                </n-tab-pane>
                <n-tab-pane name="stored" :tab="`当前生效切片（${storedChunkTotal}）`">
                  <n-empty v-if="!storedChunkTotal" description="该文件尚无已落库切片" />
                  <n-collapse v-else><n-collapse-item v-for="chunk in storedChunks" :key="chunk.id" :title="`片段 ${chunk.index + 1} · ${chunk.char_count} 字符`" :name="`stored-${chunk.id}`"><pre class="preview-content">{{ chunk.content }}</pre></n-collapse-item></n-collapse>
                  <div v-if="storedChunkTotal > storedChunkPageSize" class="pagination"><n-pagination v-model:page="storedChunkPage" :page-size="storedChunkPageSize" :item-count="storedChunkTotal" @update:page="loadStoredChunks" /></div>
                </n-tab-pane>
              </n-tabs>
            </section>
          </div>
        </n-spin>
      </n-drawer-content>
    </n-drawer>
  </div>
</template>

<script setup lang="ts">
import { computed, h, onMounted, onUnmounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { NButton, NIcon, NPopconfirm, NTag } from 'naive-ui'
import { ArrowBackOutline, CloudUploadOutline, TrashOutline } from '@vicons/ionicons5'
import type { DataTableColumns } from 'naive-ui'
import { batchFiles, getDocumentPreviewSource, getKnowledgeBase, listDocumentChunks, listFiles, processDocuments, updateDocumentProcessingStrategy, updateKnowledgeBase, type DocumentListItem, type DocumentPreviewSource, type KnowledgeBaseDetail, type ProcessingConfig, type ProcessTarget, type StoredChunk } from '@/api/knowledge'
import { listMyConfigs, type UserModelConfigItem } from '@/api/model-config'
import { storage } from '@/utils/storage'
import { TOKEN_KEY } from '@/api/request'
import { useProcessingStore } from '@/stores/processing'
import { buildDocumentPreview, PROCESSING_ALGORITHM_VERSION, type LocalDocumentPreview, type LocalPreviewChunk } from '@/utils/document-processing'
import ProcessingStrategyForm from './ProcessingStrategyForm.vue'

const route = useRoute()
const message = useMessage()
const procStore = useProcessingStore()
const kbId = computed(() => route.params.id as string)
const blankStrategy = (): ProcessingConfig => ({ cleaning_config: { rules: [] }, chunk_size: 800, chunk_overlap: 150, chunk_separators: '' })
const cloneStrategy = (value: ProcessingConfig): ProcessingConfig => JSON.parse(JSON.stringify(value)) as ProcessingConfig
const strategyFromKb = (value: KnowledgeBaseDetail): ProcessingConfig => ({ cleaning_config: JSON.parse(JSON.stringify(value.cleaning_config || { rules: [] })), chunk_size: value.chunk_size, chunk_overlap: value.chunk_overlap, chunk_separators: value.chunk_separators })

const kbInfo = ref<KnowledgeBaseDetail | null>(null)
const kbName = computed(() => kbInfo.value?.name || '知识库详情')
const knowledgeStrategyDraft = ref<ProcessingConfig>(blankStrategy())
const autoProcessDraft = ref(false)
const strategySaving = ref(false)
const strategyDrawerVisible = ref(false)
const modelConfigs = ref<UserModelConfigItem[]>([])
const embeddingLabel = computed(() => {
  if (!kbInfo.value) return '-'
  const config = modelConfigs.value.find(item => item.id === kbInfo.value!.user_model_config_id)
  return config ? `${config.provider} / ${config.model_name}` : `${kbInfo.value.embedding_model}，${kbInfo.value.embedding_dimension} 维`
})

const fileLoading = ref(false)
const fileList = ref<DocumentListItem[]>([])
const filePage = ref(1)
const filePageSize = ref(20)
const fileTotal = ref(0)
const checkedFileKeys = ref<Array<string | number>>([])
const processing = ref(false)
const isProcessing = (row: DocumentListItem) => [row.is_parsed, row.is_cleaned, row.is_chunked, row.is_vectorized].includes(2)
const strategyLocked = computed(() => fileList.value.some(isProcessing) || procStore.tasks.some(task => task.kb_id === kbId.value))

const previewVisible = ref(false)
const previewLoading = ref(false)
const previewRow = ref<DocumentListItem | null>(null)
const previewSource = ref<DocumentPreviewSource | null>(null)
const previewVersionError = ref('')
const previewError = ref('')
const fileStrategyMode = ref<'inherit' | 'custom'>('inherit')
const fileStrategyDraft = ref<ProcessingConfig>(blankStrategy())
const localPreview = ref<LocalDocumentPreview | null>(null)
const draftPage = ref(1)
const draftPageSize = 10
const storedChunks = ref<StoredChunk[]>([])
const storedChunkTotal = ref(0)
const storedChunkPage = ref(1)
const storedChunkPageSize = 20
let previewTimer: ReturnType<typeof setTimeout> | null = null
const activePreviewStrategy = computed<ProcessingConfig>({ get: () => fileStrategyMode.value === 'inherit' ? knowledgeStrategyDraft.value : fileStrategyDraft.value, set: value => { if (fileStrategyMode.value === 'inherit') knowledgeStrategyDraft.value = value; else fileStrategyDraft.value = value } })
const pagedDraftChunks = computed(() => (localPreview.value?.chunks || []).slice((draftPage.value - 1) * draftPageSize, draftPage.value * draftPageSize))
watch([previewSource, activePreviewStrategy], () => schedulePreview(), { deep: true })

const processOptions: Array<{ label: string; key: ProcessTarget }> = [
  { label: '完整处理（至向量化）', key: 'vectorize' }, { label: '处理至切片', key: 'chunk' },
  { label: '处理至清洗', key: 'clean' }, { label: '仅解析', key: 'parse' },
]
const renderState = (value: number) => {
  const states: Record<number, { type: 'default' | 'info' | 'success' | 'error'; label: string }> = { [-1]: { type: 'error', label: '失败' }, 0: { type: 'default', label: '未完成' }, 1: { type: 'success', label: '已完成' }, 2: { type: 'info', label: '进行中' } }
  const state = states[value] || { type: 'default' as const, label: '未知' }
  return h(NTag, { type: state.type, size: 'small' }, { default: () => state.label })
}
const fileColumns: DataTableColumns<DocumentListItem> = [
  { type: 'selection' },
  { title: '文件名', key: 'filename', ellipsis: { tooltip: true }, render: row => h(NButton, { text: true, type: 'primary', onClick: () => openPreview(row) }, { default: () => row.filename }) },
  { title: '策略来源', key: 'strategy_mode', width: 110, render: row => h(NTag, { type: row.strategy_mode === 'custom' ? 'warning' : 'info', size: 'small' }, { default: () => row.strategy_mode === 'custom' ? '独立策略' : '继承默认' }) },
  { title: '索引策略', key: 'strategy_outdated', width: 130, render: row => row.chunk_count ? h(NTag, { type: row.strategy_outdated ? 'warning' : 'success', size: 'small' }, { default: () => row.strategy_outdated ? '待重新处理' : '已同步' }) : h(NTag, { size: 'small' }, { default: () => '尚无切片' }) },
  { title: '解析', key: 'is_parsed', width: 75, render: row => renderState(row.is_parsed) }, { title: '清洗', key: 'is_cleaned', width: 75, render: row => renderState(row.is_cleaned) },
  { title: '切片', key: 'is_chunked', width: 75, render: row => renderState(row.is_chunked) }, { title: '向量化', key: 'is_vectorized', width: 85, render: row => renderState(row.is_vectorized) },
  { title: '大小', key: 'file_size', width: 100, render: row => formatFileSize(row.file_size) },
  { title: '错误信息', key: 'last_error', width: 160, ellipsis: { tooltip: true }, render: row => row.last_error || '-' },
  { title: '操作', key: 'actions', width: 70, render: row => h(NPopconfirm, { onPositiveClick: () => deleteFile(row.id) }, { trigger: () => h(NButton, { size: 'small', quaternary: true, type: 'error' }, { icon: () => h(NIcon, null, { default: () => h(TrashOutline) }) }), default: () => '确定删除该文件？' }) },
]

const uploadUrl = computed(() => `/api/v1/knowledge-bases/${kbId.value}/files`)
const uploadHeaders = computed<Record<string, string>>(() => {
  const headers: Record<string, string> = {}
  const token = storage.get<string>(TOKEN_KEY)
  if (token) headers.Authorization = `Bearer ${token}`
  return headers
})
const acceptExtensions = computed(() => kbInfo.value?.allowed_extensions?.split(',').map(ext => `.${ext.trim().replace(/^\./, '')}`).join(','))

async function fetchKnowledgeBase() {
  try { const detail = await getKnowledgeBase(kbId.value); kbInfo.value = detail; autoProcessDraft.value = detail.auto_process; knowledgeStrategyDraft.value = strategyFromKb(detail) }
  catch (error) { message.error(errorText(error, '获取知识库信息失败')) }
}
function resetKnowledgeStrategy() { if (kbInfo.value) { autoProcessDraft.value = kbInfo.value.auto_process; knowledgeStrategyDraft.value = strategyFromKb(kbInfo.value) } }
function openStrategyDrawer() { resetKnowledgeStrategy(); strategyDrawerVisible.value = true }
function validStrategy(value: ProcessingConfig) {
  if (value.chunk_overlap >= value.chunk_size) { message.warning('切片重叠必须小于单片长度'); return false }
  if (value.cleaning_config.rules.some(rule => rule.type === 'regex_remove' && (rule.replacement || '').includes('\\'))) {
    message.warning('正则删除的替换内容不支持反向引用或反斜杠转义')
    return false
  }
  return true
}
async function saveKnowledgeStrategy(show = true): Promise<boolean> {
  if (!validStrategy(knowledgeStrategyDraft.value)) return false
  strategySaving.value = true
  try { const updated = await updateKnowledgeBase(kbId.value, { auto_process: autoProcessDraft.value, ...cloneStrategy(knowledgeStrategyDraft.value) }); kbInfo.value = updated; autoProcessDraft.value = updated.auto_process; knowledgeStrategyDraft.value = strategyFromKb(updated); if (show) message.success('知识库默认策略已保存'); await fetchFiles(true); return true }
  catch (error) { message.error(errorText(error, '保存默认策略失败')); return false }
  finally { strategySaving.value = false }
}
async function saveKnowledgeStrategyFromDrawer() { if (await saveKnowledgeStrategy()) strategyDrawerVisible.value = false }

let fetchSeq = 0
async function fetchFiles(silent = false) {
  const seq = ++fetchSeq; if (!silent) fileLoading.value = true
  try { const result = await listFiles(kbId.value, filePage.value, filePageSize.value); if (seq === fetchSeq) { fileList.value = result.items; fileTotal.value = result.total } }
  catch (error) { if (!silent) message.error(errorText(error, '获取文件列表失败')) }
  finally { if (!silent && seq === fetchSeq) fileLoading.value = false }
}
function onFilePageSizeChange(size: number) { filePageSize.value = size; filePage.value = 1; void fetchFiles() }
function onUploadFinish() { void (async () => { message.success('上传成功，点击文件可实时预览处理效果'); filePage.value = 1; await fetchFiles(); if (kbInfo.value?.auto_process) { procStore.startPolling(); startPoll() } })() }
// eslint-disable-next-line @typescript-eslint/no-explicit-any
function onUploadError({ event }: any) { let text = '上传失败'; try { text = JSON.parse((event?.target as XMLHttpRequest)?.response || '{}').message || text } catch { /* ignore */ } message.error(text) }

async function openPreview(row: DocumentListItem) {
  previewVisible.value = true; previewLoading.value = true; previewRow.value = row; previewSource.value = null; localPreview.value = null; previewVersionError.value = ''; previewError.value = ''
  fileStrategyMode.value = row.strategy_mode; fileStrategyDraft.value = cloneStrategy(row.processing_config || row.effective_processing_config); draftPage.value = 1; storedChunkPage.value = 1
  try { const [source] = await Promise.all([getDocumentPreviewSource(kbId.value, row.id), loadStoredChunks(1)]); previewSource.value = source; if (source.algorithm_version !== PROCESSING_ALGORITHM_VERSION) { previewVersionError.value = '处理算法已更新，请刷新页面后重新预览。' } else computePreview() }
  catch (error) { message.error(errorText(error, '加载文件预览失败')) }
  finally { previewLoading.value = false }
}
function setFileStrategyMode(mode: 'inherit' | 'custom') { if (mode !== fileStrategyMode.value) { if (mode === 'custom') fileStrategyDraft.value = cloneStrategy(activePreviewStrategy.value); fileStrategyMode.value = mode } }
function schedulePreview() { if (previewTimer) clearTimeout(previewTimer); previewTimer = setTimeout(computePreview, 300) }
function computePreview() { if (!previewSource.value || previewVersionError.value) return; try { localPreview.value = buildDocumentPreview(previewSource.value.raw_content, activePreviewStrategy.value); previewError.value = ''; draftPage.value = 1 } catch (error) { previewError.value = error instanceof Error ? error.message : String(error) } }
async function loadStoredChunks(page = storedChunkPage.value) { if (!previewRow.value) return; storedChunkPage.value = page; const result = await listDocumentChunks(kbId.value, previewRow.value.id, page, storedChunkPageSize); storedChunks.value = result.items; storedChunkTotal.value = result.total }

async function saveCurrentFileStrategy(): Promise<boolean> {
  if (!previewRow.value || !validStrategy(activePreviewStrategy.value)) return false
  strategySaving.value = true
  try { if (fileStrategyMode.value === 'inherit') { if (!await saveKnowledgeStrategy(false)) return false; await updateDocumentProcessingStrategy(kbId.value, previewRow.value.id, { mode: 'inherit' }) } else { await updateDocumentProcessingStrategy(kbId.value, previewRow.value.id, { mode: 'custom', ...cloneStrategy(fileStrategyDraft.value) }) } message.success('文件处理策略已保存'); await fetchFiles(true); return true }
  catch (error) { message.error(errorText(error, '保存文件处理策略失败')); return false }
  finally { strategySaving.value = false }
}
async function saveAndReprocessCurrentFile() {
  if (!previewRow.value || !await saveCurrentFileStrategy()) return
  processing.value = true
  try { await processDocuments(kbId.value, [previewRow.value.id], PROCESSING_ALGORITHM_VERSION, 'vectorize'); message.success('策略已保存，文件已加入完整处理队列'); procStore.startPolling(); await fetchFiles(true); startPoll() }
  catch (error) { message.error(errorText(error, '策略已保存，但处理任务提交失败，请重试')) }
  finally { processing.value = false }
}
const draftChunkTitle = (chunk: LocalPreviewChunk) => `片段 ${chunk.index + 1} · ${chunk.char_count} 字符 · ${chunk.index ? `与上一片重叠 ${chunk.overlap_char_count} 字符` : '不与前片重叠'}`
function handleProcessSelect(key: string | number) { void triggerProcess(key as ProcessTarget) }
async function triggerProcess(target: ProcessTarget) { if (!checkedFileKeys.value.length) return; processing.value = true; try { const result = await processDocuments(kbId.value, checkedFileKeys.value.map(String), PROCESSING_ALGORITHM_VERSION, target); message.success(`已加入处理队列：${result.processed} 个文件`); checkedFileKeys.value = []; await fetchFiles(true); procStore.startPolling(); startPoll() } catch (error) { message.error(errorText(error, '处理任务入队失败')) } finally { processing.value = false } }
async function deleteFile(id: string) { try { await batchFiles(kbId.value, [id], 'delete'); message.success('已删除'); await fetchFiles() } catch (error) { message.error(errorText(error, '删除失败')) } }
async function batchFilesAction() { if (!checkedFileKeys.value.length) return; try { const result = await batchFiles(kbId.value, checkedFileKeys.value.map(String), 'delete'); message.success(`批量删除完成：成功 ${result.success_count}，失败 ${result.fail_count}`); checkedFileKeys.value = []; await fetchFiles() } catch (error) { message.error(errorText(error, '批量删除失败')) } }

let pollTimer: ReturnType<typeof setInterval> | null = null
function stopPoll() { if (pollTimer) clearInterval(pollTimer); pollTimer = null }
function startPoll() { stopPoll(); pollTimer = setInterval(async () => { await fetchFiles(true); if (!fileList.value.some(isProcessing)) { stopPoll(); if (previewVisible.value && previewRow.value) await loadStoredChunks() } }, 2000) }
function formatFileSize(bytes: number) { if (!bytes) return '-'; const units = ['B', 'KB', 'MB', 'GB']; let value = bytes; let i = 0; while (value >= 1024 && i < units.length - 1) { value /= 1024; i += 1 } return `${value.toFixed(i ? 2 : 0)} ${units[i]}` }
function formatDate(value: string) { return value ? new Date(value).toLocaleString('zh-CN', { hour12: false }) : '-' }
function errorText(error: unknown, fallback: string) { return error instanceof Error && error.message ? error.message : fallback }
onMounted(() => { void fetchKnowledgeBase(); void fetchFiles(); void listMyConfigs().then(items => { modelConfigs.value = items }) })
onUnmounted(() => { stopPoll(); if (previewTimer) clearTimeout(previewTimer) })
</script>

<style scoped>
.page { height: 100%; }
.page-header, .auto-row, .actions, .batch-bar, .pagination, .strategy-summary-content { display: flex; align-items: center; }
.page-header { justify-content: space-between; margin-bottom: 16px; }
.page-header h2 { margin: 0; font-size: 20px; }
.section-card { margin-bottom: 16px; }
.strategy-summary-content { justify-content: space-between; gap: 16px; }
.strategy-summary-meta { margin-top: 8px; color: var(--n-text-color-3); font-size: 13px; }
.notice { margin-bottom: 12px; }
.auto-row { justify-content: space-between; margin-bottom: 14px; }
.auto-row p, .hint { margin: 4px 0 0; color: var(--n-text-color-3); font-size: 13px; }
.actions, .pagination { justify-content: flex-end; gap: 8px; }
.hint { text-align: right; }
.strategy-drawer-hint { margin-top: 4px; text-align: left; }
.batch-bar { justify-content: space-between; padding: 10px 16px; margin-bottom: 12px; background: var(--n-color-embedded); border: 1px solid var(--n-border-color); border-radius: 4px; }
.pagination { margin-top: 16px; }
.preview-spin { height: 100%; min-height: 0; }
.preview-spin :deep(.n-spin-content) { display: flex; flex-direction: column; height: 100%; min-height: 0; }
.preview-layout { display: grid; grid-template-columns: minmax(280px, 320px) minmax(0, 1fr) minmax(0, 1fr); flex: 1; gap: 16px; min-height: 0; }
.preview-strategy { min-width: 0; min-height: 0; overflow-y: auto; padding-right: 16px; border-right: 1px solid var(--n-border-color); }
.preview-strategy h3, .preview-source-column h3 { margin: 0 0 12px; }
.scope-notice { margin: 12px 0; }
.drawer-actions { width: 100%; margin-top: 12px; }
.preview-source-column, .preview-result-column { min-width: 0; min-height: 0; }
.preview-source-column { display: flex; flex-direction: column; }
.preview-result-column :deep(.n-tabs) { height: 100%; }
.preview-result-column :deep(.n-tabs-pane-wrapper), .preview-result-column :deep(.n-tab-pane) { min-height: 0; }
.preview-result-column :deep(.n-tab-pane) { height: 100%; overflow: auto; }
.preview-content { margin: 0; white-space: pre-wrap; word-break: break-word; font-family: var(--n-font-family-mono); line-height: 1.65; }
.text-pane { min-height: 0; box-sizing: border-box; overflow: auto; padding: 12px; border: 1px solid var(--n-border-color); border-radius: 4px; }
.preview-source-column .text-pane { flex: 1; }
@media (max-width: 1000px) {
  :deep(.preview-drawer-body) { height: auto !important; overflow: auto !important; }
  .preview-spin, .preview-spin :deep(.n-spin-content) { height: auto; }
  .preview-layout { grid-template-columns: 1fr; flex: none; }
  .preview-strategy { min-height: auto; padding-right: 0; padding-bottom: 16px; border-right: 0; border-bottom: 1px solid var(--n-border-color); }
  .preview-source-column, .preview-result-column { min-height: auto; }
  .preview-source-column .text-pane { flex: none; }
  .preview-result-column :deep(.n-tabs), .preview-result-column :deep(.n-tab-pane) { height: auto; }
}
</style>
