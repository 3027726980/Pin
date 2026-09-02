/**
 * 知识库 + 文件管理 API
 */
import request from './request'

// ── 类型定义 ────────────────────────────

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
  chunk_size: number
  chunk_overlap: number
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
  is_chunked: number
  is_vectorized: number
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
  is_chunked: number
  is_vectorized: number
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

// ── 全局处理任务（处理浮窗轮询） ────────

export interface ProcessingTask {
  doc_id: string
  filename: string
  kb_id: string
  kb_name: string
  stage: 'queued' | 'parsing' | 'chunking' | 'vectorizing' | 'processing'
}

/** 全局处理中/排队任务列表（所有知识库） */
export function getProcessingTasks(): Promise<ProcessingTask[]> {
  return request.get('/v1/knowledge-bases/processing-tasks')
}
