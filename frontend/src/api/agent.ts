/**
 * Agent 管理 + 对话 API
 */
import request from './request'
import { storage } from '@/utils/storage'
import { TOKEN_KEY } from './request'

// ── 类型定义 ────────────────────────────

export type AgentType = 'simple_rag' | 'general'

export interface ToolConfig {
  type: 'rag'
  kb_id: string
  top_k: number | null
  score_threshold: number | null
  // Phase 4.6 检索增强（可空 → config.yaml 默认）
  mqe_enabled?: boolean | null
  hyde_enabled?: boolean | null
  mqe_query_count?: number | null
  rerank_enabled?: boolean | null
  kb_name?: string | null
}

export interface AgentListItem {
  id: string
  type: AgentType
  name: string
  description: string | null
  llm_model: string | null
  kb_id: string | null
  kb_name: string | null
  tools: ToolConfig[]
  status: number
  created_at: string
}

export interface AgentDetail extends AgentListItem {
  llm_config_id: string
  llm_provider: string | null
  summary_llm_config_id: string | null
  system_prompt: string
  temperature: number | null
  top_p: number | null
  max_tokens: number | null
  top_k: number | null
  score_threshold: number | null
  welcome_message: string | null
  // ── Phase 4.6 检索增强 ──
  mqe_enabled: boolean
  hyde_enabled: boolean
  mqe_query_count: number
  rerank_enabled: boolean
  enhance_llm_config_id: string | null
  rerank_config_id: string | null
  // ── 嵌入治理参数（agent_index 表）──
  rate_limit_per_min: number
  allowed_domains: string[]
  anonymous_retention_days: number
  updated_at: string
}

export interface AgentCreatePayload {
  type: AgentType
  name: string
  description?: string | null
  llm_config_id: string
  summary_llm_config_id?: string | null
  kb_id?: string | null
  top_k?: number | null
  score_threshold?: number | null
  tools?: ToolConfig[]
  system_prompt?: string | null
  temperature?: number | null
  top_p?: number | null
  max_tokens?: number | null
  welcome_message?: string | null
  // ── Phase 4.6 检索增强（Agent 级）──
  mqe_enabled?: boolean
  hyde_enabled?: boolean
  mqe_query_count?: number
  rerank_enabled?: boolean
  enhance_llm_config_id?: string | null
  rerank_config_id?: string | null
}

export type AgentUpdatePayload = Partial<AgentCreatePayload> & {
  status?: number
  // 嵌入治理参数
  rate_limit_per_min?: number
  allowed_domains?: string[]
  anonymous_retention_days?: number
}

export interface BatchAgentResult {
  success_count: number
  fail_count: number
  failed_ids: string[]
}

export interface ChatMessage {
  role: 'user' | 'assistant'
  content: string
}

export interface ChatCitation {
  chunk_id: string
  document_name: string
  content: string
  score: number
  original_score?: number | null
}

export interface ChatDebug {
  queries?: string[]
  rerank?: { enabled: boolean; provider?: string | null; model?: string | null }
}

export interface ChatResult {
  answer: string
  citations: ChatCitation[]
  debug?: ChatDebug | null
}

export interface ChatSuggestion {
  action: string
  value?: number | string
}

export type ChatEvent =
  | { type: 'delta'; content: string }
  | { type: 'citations'; citations: ChatCitation[] }
  | { type: 'debug'; debug: ChatDebug }
  | { type: 'done' }
  | { type: 'error'; code: number; message: string; suggestion?: ChatSuggestion | null }

// ── Agent CRUD ──────────────────────────

/** 获取 Agent 默认配置（默认系统提示词模板 + 默认检索参数 + 检索增强默认值） */
export function getAgentDefaults(): Promise<{
  system_prompt: string
  default_top_k: number
  default_score_threshold: number
  default_mqe_enabled: boolean
  default_hyde_enabled: boolean
  default_mqe_query_count: number
  default_rerank_enabled: boolean
}> {
  return request.get('/v1/agents/defaults')
}

/** 获取 Agent 列表（type 可选筛选） */
export function listAgents(page = 1, pageSize = 20, type?: AgentType): Promise<{ items: AgentListItem[]; total: number; page: number; page_size: number }> {
  return request.get('/v1/agents', {
    params: { page: String(page), page_size: String(pageSize), type: type || undefined },
  })
}

/** 获取 Agent 详情 */
export function getAgent(id: string): Promise<AgentDetail> {
  return request.get(`/v1/agents/${id}`)
}

/** 创建 Agent */
export function createAgent(data: AgentCreatePayload): Promise<AgentDetail> {
  return request.post('/v1/agents', data)
}

/** 编辑 Agent */
export function updateAgent(id: string, data: AgentUpdatePayload): Promise<AgentDetail> {
  return request.put(`/v1/agents/${id}`, data)
}

/** 删除 Agent */
export function deleteAgent(id: string): Promise<void> {
  return request.delete(`/v1/agents/${id}`)
}

/** 批量操作（enable / disable / delete） */
export function batchAgents(ids: string[], action: 'enable' | 'disable' | 'delete'): Promise<BatchAgentResult> {
  return request.post('/v1/agents/batch', { ids, action })
}

// ── 对话 ────────────────────────────────

/** 非流式对话(记忆由服务端 checkpoint 管理,前端不传 history) */
export function chatAgent(agentId: string, body: { message: string; conversation_id?: string | null; stream?: boolean; debug?: boolean }): Promise<ChatResult & { conversation_id: string }> {
  return request.post(`/v1/agents/${agentId}/chat`, body)
}

/**
 * 流式对话（SSE）：fetch + ReadableStream 解析 data: 帧
 * 事件通过 onEvent 回调分发（delta / citations / done / error）
 */
export async function chatAgentStream(
  agentId: string,
  body: { message: string; conversation_id?: string | null; stream: true; debug?: boolean },
  onEvent: (e: ChatEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  const token = storage.get<string>(TOKEN_KEY)
  const res = await fetch(`/api/v1/agents/${agentId}/chat`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    body: JSON.stringify(body),
    signal,
  })

  if (!res.ok) {
    let detail = `HTTP ${res.status}`
    try {
      const data = await res.json()
      detail = data.message || detail
    } catch {
      /* 非 JSON 响应 */
    }
    throw new Error(detail)
  }

  const reader = res.body!.getReader()
  const decoder = new TextDecoder()
  let buffer = ''

  while (true) {
    const { done, value } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })

    const frames = buffer.split('\n\n')
    buffer = frames.pop() ?? ''

    for (const frame of frames) {
      if (frame.startsWith('data: ')) {
        onEvent(JSON.parse(frame.slice(6)) as ChatEvent)
      }
    }
  }
}
