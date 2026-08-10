/**
 * 会话 API(Phase 4.5:checkpoint 记忆 + 会话系统)
 *
 * 会话 id 即服务端 checkpoint 的 thread_id;历史消息查看走 messages 表。
 */
import request from './request'
import type { ChatCitation } from './agent'

export interface ConversationItem {
  id: string
  agent_id: string
  title: string | null
  message_count: number
  created_at: string
  updated_at: string
}

export interface ConversationMessage {
  id: string
  role: 'user' | 'assistant'
  content: string
  citations: ChatCitation[] | null
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
