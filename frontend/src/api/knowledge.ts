/**
 * 知识库 + 文件管理 API
 */
import request from './request'

// ── 类型定义 ────────────────────────────

export type CleaningRuleType =
  | 'normalize_unicode'
  | 'remove_control_chars'
  | 'collapse_blank_lines'
  | 'trim_lines'
  | 'collapse_punctuation'
  | 'replace_text'
  | 'regex_remove'

export interface CleaningRule {
  type: CleaningRuleType
  enabled?: boolean
  value?: string | null
  replacement?: string
  max_consecutive?: number
}

export interface CleaningConfig {
  rules: CleaningRule[]
}

export interface ProcessingConfig {
  cleaning_config: CleaningConfig
  chunk_size: number
  chunk_overlap: number
  chunk_separators: string
}

export interface KnowledgeBaseListItem {
  id: string
  name: string
  allowed_extensions: string | null
  user_model_config_id: string | null
  embedding_model: string
  status: number
  created_at: string
}

export interface KnowledgeBaseDetail {
  id: string
  name: string
  description: string | null
  allowed_extensions: string | null
  max_file_size: number
  allow_multiple: boolean
  auto_process: boolean
  chunk_size: number
  chunk_overlap: number
  chunk_separators: string
  cleaning_config: CleaningConfig
  embedding_model: string
  embedding_dimension: number
  user_model_config_id: string | null
  status: number
  created_at: string
}

export interface KnowledgeBaseCreate {
  name: string
  description?: string | null
  allowed_extensions?: string | null
  max_file_size?: number | null
  allow_multiple?: boolean
  auto_process?: boolean | null
  chunk_size?: number | null
  chunk_overlap?: number | null
  chunk_separators?: string | null
  cleaning_config?: CleaningConfig | null
  embedding_model?: string | null
  embedding_dimension?: number | null
  user_model_config_id?: string | null
}

export interface KnowledgeBaseUpdate {
  name?: string | null
  description?: string | null
  allowed_extensions?: string | null
  max_file_size?: number | null
  allow_multiple?: boolean | null
  auto_process?: boolean | null
  chunk_size?: number | null
  chunk_overlap?: number | null
  chunk_separators?: string | null
  cleaning_config?: CleaningConfig | null
  embedding_model?: string | null
  embedding_dimension?: number | null
  user_model_config_id?: string | null
  status?: number | null
}

export interface DocumentListItem {
  id: string
  filename: string
  file_size: number
  file_type: string | null
  status: number
  is_parsed: number
  is_cleaned: number
  is_chunked: number
  is_vectorized: number
  processing_config?: ProcessingConfig | null
  strategy_mode: 'inherit' | 'custom'
  effective_processing_config: ProcessingConfig
  strategy_outdated: boolean
  applied_algorithm_version?: number | null
  chunk_count: number
  last_error?: string | null
  created_at: string
}

export interface DocumentDetail {
  id: string
  knowledge_base_id: string
  user_id: string
  filename: string
  file_path: string
  file_size: number
  file_type: string | null
  status: number
  is_parsed: number
  is_cleaned: number
  is_chunked: number
  is_vectorized: number
  cleaned_content?: string | null
  cleaning_config_hash?: string | null
  last_error?: string | null
  created_at: string
  updated_at: string
}

export interface PaginatedResponse<T> {
  items: T[]
  total: number
  page: number
  page_size: number
}

// ── 知识库 CRUD ────────────────────────

/** 获取知识库列表 */
export function listKnowledgeBases(page = 1, pageSize = 20): Promise<PaginatedResponse<KnowledgeBaseListItem>> {
  return request.get('/v1/knowledge-bases', {
    params: { page: String(page), page_size: String(pageSize) },
  })
}

/** 获取知识库详情 */
export function getKnowledgeBase(id: string): Promise<KnowledgeBaseDetail> {
  return request.get(`/v1/knowledge-bases/${id}`)
}

/** 获取新建知识库时使用的服务端默认处理策略。 */
export function getKnowledgeBaseDefaults(): Promise<{
  cleaning_config: CleaningConfig
  auto_process?: boolean
  chunk_size?: number
  chunk_overlap?: number
  chunk_separators?: string
}> {
  return request.get('/v1/knowledge-bases/defaults')
}

/** 创建知识库 */
export function createKnowledgeBase(data: KnowledgeBaseCreate): Promise<KnowledgeBaseDetail> {
  return request.post('/v1/knowledge-bases', data)
}

/** 编辑知识库 */
export function updateKnowledgeBase(id: string, data: KnowledgeBaseUpdate): Promise<KnowledgeBaseDetail> {
  return request.put(`/v1/knowledge-bases/${id}`, data)
}

/** 删除知识库 */
export function deleteKnowledgeBase(id: string): Promise<void> {
  return request.delete(`/v1/knowledge-bases/${id}`)
}

// ── 文件管理 ────────────────────────────

/** 获取文件列表 */
export function listFiles(kbId: string, page = 1, pageSize = 20): Promise<PaginatedResponse<DocumentListItem>> {
  return request.get(`/v1/knowledge-bases/${kbId}/files`, {
    params: { page: String(page), page_size: String(pageSize) },
  })
}

/** 上传文件 */
export function uploadFile(kbId: string, file: File): Promise<DocumentDetail> {
  const formData = new FormData()
  formData.append('file', file)
  return request.post(`/v1/knowledge-bases/${kbId}/files`, formData, {
    headers: { 'Content-Type': 'multipart/form-data' },
  })
}

/** 删除文件 */
export function deleteFile(kbId: string, docId: string): Promise<void> {
  return request.delete(`/v1/knowledge-bases/${kbId}/files/${docId}`)
}

export interface PreviewChunk {
  index: number
  content: string
  char_count: number
  overlap_char_count: number
}

export interface DocumentPreview {
  document_id: string
  filename: string
  raw_content: string
  cleaned_content: string
  chunks: PreviewChunk[]
  cleaning_config_hash: string
  warnings: string[]
}

export interface DocumentPreviewSource {
  document_id: string
  filename: string
  raw_content: string
  algorithm_version: number
  truncated: boolean
  warnings: string[]
}

export interface StoredChunk {
  id: string
  index: number
  content: string
  char_count: number
  metadata?: Record<string, unknown> | null
  is_vectorized: number
}

export type DocumentStrategyPayload =
  | { mode: 'inherit' }
  | ({ mode: 'custom' } & ProcessingConfig)

/** 在内存中预览文件的清洗文本和切片，不写入知识库 */
export function previewDocument(kbId: string, docId: string): Promise<DocumentPreview> {
  return request.post(`/v1/knowledge-bases/${kbId}/files/${docId}/preview`)
}

/** 获取一次原始解析文本，供浏览器本地实时清洗和切片。 */
export function getDocumentPreviewSource(kbId: string, docId: string): Promise<DocumentPreviewSource> {
  return request.get(`/v1/knowledge-bases/${kbId}/files/${docId}/preview-source`)
}

/** 分页获取数据库当前生效切片。 */
export function listDocumentChunks(
  kbId: string,
  docId: string,
  page = 1,
  pageSize = 20,
): Promise<PaginatedResponse<StoredChunk>> {
  return request.get(`/v1/knowledge-bases/${kbId}/files/${docId}/chunks`, {
    params: { page: String(page), page_size: String(pageSize) },
  })
}

/** 保存文件独立处理策略，或恢复继承知识库默认策略。 */
export function updateDocumentProcessingStrategy(
  kbId: string,
  docId: string,
  payload: DocumentStrategyPayload,
): Promise<DocumentListItem> {
  return request.put(`/v1/knowledge-bases/${kbId}/files/${docId}/processing-strategy`, payload)
}

// ── 批量操作 ────────────────────────────

export type BatchAction = 'enable' | 'disable' | 'delete'
export type BatchFileAction = 'delete'

export interface BatchResult {
  success_count: number
  fail_count: number
  failed_ids: string[]
}

/** 批量操作知识库 */
export function batchKnowledgeBases(ids: string[], action: BatchAction): Promise<BatchResult> {
  return request.post('/v1/knowledge-bases/batch', { ids, action })
}

/** 批量操作文件 */
export function batchFiles(kbId: string, ids: string[], action: BatchFileAction): Promise<BatchResult> {
  return request.post(`/v1/knowledge-bases/${kbId}/files/batch`, { ids, action })
}

// ── 文档处理 ────────────────────────────

export interface ProcessResult {
  processed: number
  total: number
}

/** 触发文档解析 */
export function parseDocuments(kbId: string, docIds: string[]): Promise<ProcessResult> {
  return request.post(`/v1/knowledge-bases/${kbId}/parse`, { doc_ids: docIds })
}

/** 触发文档分块 */
export function chunkDocuments(kbId: string, docIds: string[]): Promise<ProcessResult> {
  return request.post(`/v1/knowledge-bases/${kbId}/chunk`, { doc_ids: docIds })
}

/** 触发向量化（按 chunk_ids） */
export function vectorizeChunks(kbId: string, chunkIds: string[]): Promise<ProcessResult> {
  return request.post(`/v1/knowledge-bases/${kbId}/vectorize`, { chunk_ids: chunkIds })
}

/** 按文档批量向量化（选文档自动找其所有有效分块） */
export function vectorizeDocuments(kbId: string, docIds: string[]): Promise<ProcessResult> {
  return request.post(`/v1/knowledge-bases/${kbId}/vectorize-docs`, { doc_ids: docIds })
}

export type ProcessTarget = 'parse' | 'clean' | 'chunk' | 'vectorize'

/** 将文件入队处理至指定阶段；后端自动补齐前置阶段。 */
export function processDocuments(
  kbId: string,
  docIds: string[],
  algorithmVersion: number,
  targetStage: ProcessTarget = 'vectorize',
): Promise<ProcessResult> {
  return request.post(`/v1/knowledge-bases/${kbId}/files/process`, {
    doc_ids: docIds,
    target_stage: targetStage,
    algorithm_version: algorithmVersion,
  })
}

// ── 全局处理任务（处理浮窗轮询） ────────

export interface ProcessingTask {
  doc_id: string
  filename: string
  kb_id: string
  kb_name: string
  is_parsed: number
  is_cleaned: number
  is_chunked: number
  is_vectorized: number
  stage: 'queued' | 'parsing' | 'cleaning' | 'chunking' | 'vectorizing' | 'processing'
}

/** 全局处理中/排队任务列表（所有知识库） */
export function getProcessingTasks(): Promise<ProcessingTask[]> {
  return request.get('/v1/knowledge-bases/processing-tasks')
}
