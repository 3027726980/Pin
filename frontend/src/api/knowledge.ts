/**
 * 知识库 + 文件管理 API
 */
import request from './request'

// ── 类型定义 ────────────────────────────

export interface KnowledgeBaseListItem {
  id: string
  name: string
  allowed_extensions: string | null
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
  status: number
  created_at: string
}

export interface KnowledgeBaseCreate {
  name: string
  description?: string | null
  allowed_extensions?: string | null
  max_file_size?: number | null
  allow_multiple?: boolean
}

export interface KnowledgeBaseUpdate {
  name?: string | null
  description?: string | null
  allowed_extensions?: string | null
  max_file_size?: number | null
  allow_multiple?: boolean | null
  status?: number | null
}

export interface DocumentListItem {
  id: string
  filename: string
  file_size: number
  file_type: string | null
  status: number
  is_chunked: number
  is_vectorized: number
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
