import type { CapabilityMention, SkillArtifact } from '@/chat-core/capabilities'
/** 作者：LHF；时间：2026-10-25；作用：提供会话上下文手动压缩交互。 */
/**
 * 会话 API(Phase 4.5:checkpoint 记忆 + 会话系统)
 *
 * 会话 id 即服务端 checkpoint 的 thread_id;历史消息查看走 messages 表。
 */
import request from './request'
import type { ChatCitation, CitationBinding } from './agent'

/** 作者：LHF；2026-10-25；已保存上下文估算，包含系统提示词与配置的工具。 */
export interface ContextUsage {
  used_tokens: number
  input_capacity: number
  capacity_source: string
  model_name: string
  token_count_method: 'approximate' | 'tiktoken_estimate' | 'local_tokenizer_estimate'
  token_encoding?: string
  token_encoding_source?: 'model' | 'configuration' | 'fallback' | 'local_tokenizer'
}

/** 作者：LHF；2026-10-25；只读查询管理端会话的模型输入占用。 */
export function getContextUsage(convId: string, draft?: { message: string; mentions: CapabilityMention[] }): Promise<ContextUsage> {
  return draft ? request.post(`/v1/conversations/${convId}/context-preview`, draft) : request.get(`/v1/conversations/${convId}/context-usage`)
}

/** 作者：LHF；2026-10-25；手动压缩结果，token 数为近似值。 */
export interface CompactionResult {
  compressed: boolean
  before_tokens: number
  after_tokens: number
  trace_id: string
}

/** 作者：LHF；2026-10-25；压缩记忆，不修改页面展示历史。 */
export function compactConversation(convId: string): Promise<CompactionResult> {
  return request.post(`/v1/conversations/${convId}/compact`, {}, { timeout: 180000 })
}

export interface ConversationItem {
  id: string
  agent_id: string
  title: string | null
  message_count: number
  created_at: string
  updated_at: string
}

export interface ConversationMessage {
  mentions?: CapabilityMention[]
  artifacts?: SkillArtifact[]
  role: 'user' | 'assistant'
  content: string
  citations: ChatCitation[] | null
  citation_bindings?: CitationBinding[] | null
  trace_id?: string | null
  created_at: string
}

export interface ConversationPage {
  items: ConversationItem[]
  total: number
  page: number
  page_size: number
}

export interface MessagePage {
  items: ConversationMessage[]
  total: number
  page: number
  page_size: number
}

/** 创建会话(后端自动生成标题) */
export function createConversation(agentId: string): Promise<ConversationItem> {
  return request.post('/v1/conversations', { agent_id: agentId })
}

/** 会话列表(按 Agent 过滤,分页) */
export function listConversations(
  agentId: string,
  page = 1,
  pageSize = 20,
): Promise<ConversationPage> {
  return request.get('/v1/conversations', {
    params: { agent_id: agentId, page: String(page), page_size: String(pageSize) },
  })
}

/** 历史消息(分页,含 citations) */
export function listConversationMessages(
  convId: string,
  page = 1,
  pageSize = 100,
): Promise<MessagePage> {
  return request.get(`/v1/conversations/${convId}/messages`, {
    params: { page: String(page), page_size: String(pageSize) },
  })
}

/** 删除会话(后端软删 + 清理 checkpoint) */
export function deleteConversation(convId: string): Promise<void> {
  return request.delete(`/v1/conversations/${convId}`)
}
