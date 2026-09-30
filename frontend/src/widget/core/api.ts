/** 公开接口客户端：X-API-Key 鉴权 + client_id/JWT 双身份 + SSE 流式
 *
 * baseUrl：Pin 后端地址（默认空=相对路径，与宿主同源；跨域嵌入时必传，
 * 如 'https://pin.example.com'）
 */

import { getClientId, getToken, type CitationBinding, type ConvItem, type Msg } from './state'
import type { Citation } from './refs'
import { createSseParser } from '../../chat-core/sse-parser'
import type { AgentEvent } from '../../chat-core/events'

export interface ChatResult {
  conversation_id: string
  answer: string
  citations: Citation[]
  citation_bindings: CitationBinding[]
}

export class PublicApi {
  private apiKey: string
  private baseUrl: string

  constructor(apiKey: string, baseUrl = '') {
    this.apiKey = apiKey
    this.baseUrl = baseUrl.replace(/\/$/, '')
  }

  /** 拼后端地址 */
  private url(path: string): string {
    return `${this.baseUrl}${path}`
  }

  /** 统一请求头：API Key 必带；登录态带 JWT */
  private headers(extra?: Record<string, string>): Record<string, string> {
    const h: Record<string, string> = {
      'X-API-Key': this.apiKey,
      'Content-Type': 'application/json',
      ...extra,
    }
    const token = getToken()
    if (token) h.Authorization = `Bearer ${token}`
    return h
  }

  /** 会话维度参数：登录态不带 client_id（后端忽略），匿名带 client_id */
  private identityParams(params: Record<string, string>): Record<string, string> {
    if (!getToken()) params.client_id = getClientId()
    return params
  }

  async login(username: string, password: string): Promise<{ access_token: string; user: { id: string; username: string } }> {
    const resp = await fetch(this.url('/api/v1/public/auth/login'), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ username, password }),
    })
    const data = await resp.json()
    if (!resp.ok || data.code !== 200) {
      throw new Error(data.message || '登录失败')
    }
    return data.result
  }

  async createConversation(agentId: string): Promise<{ id: string; title: string | null }> {
    const body: Record<string, unknown> = { agent_id: agentId }
    if (!getToken()) body.client_id = getClientId()
    const resp = await fetch(this.url('/api/v1/public/conversations'), {
      method: 'POST',
      headers: this.headers(),
      body: JSON.stringify(body),
    })
    const data = await resp.json()
    if (!resp.ok || data.code !== 200) throw new Error(data.message || '创建会话失败')
    return data.result
  }

  async listConversations(agentId: string): Promise<ConvItem[]> {
    const params = this.identityParams({ agent_id: agentId })
    const resp = await fetch(this.url(`/api/v1/public/conversations?${new URLSearchParams(params)}`), {
      headers: this.headers(),
    })
    const data = await resp.json()
    if (!resp.ok || data.code !== 200) throw new Error(data.message || '会话列表加载失败')
    return data.result.items
  }

  /** 删除会话（登录态按 user 归属，匿名按 client_id） */
  async deleteConversation(convId: string): Promise<void> {
    const params = this.identityParams({})
    const qs = new URLSearchParams(params).toString()
    const resp = await fetch(this.url(`/api/v1/public/conversations/${convId}${qs ? `?${qs}` : ''}`), {
      method: 'DELETE',
      headers: this.headers(),
    })
    const data = await resp.json()
    if (!resp.ok || data.code !== 200) throw new Error(data.message || '删除会话失败')
  }

  async listMessages(convId: string): Promise<Msg[]> {
    const params = this.identityParams({ page: '1', page_size: '100' })
    const resp = await fetch(this.url(`/api/v1/public/conversations/${convId}/messages?${new URLSearchParams(params)}`), {
      headers: this.headers(),
    })
    const data = await resp.json()
    if (!resp.ok || data.code !== 200) throw new Error(data.message || '历史消息加载失败')
    return data.result.items.map((m: { role: string; content: string; citations: Citation[] | null; citation_bindings?: CitationBinding[] | null }) => ({
      role: m.role as 'user' | 'assistant',
      content: m.content,
      citations: m.citations || [],
      rawCitations: m.citations || [],
      citationBindings: m.citation_bindings || [],
    }))
  }

  /** 流式对话：与管理端共用 AgentEvent v2 增量解析器。 */
  async chatStream(
    agentId: string,
    conversationId: string,
    message: string,
    onEvent: (e: AgentEvent) => void,
    signal?: AbortSignal,
  ): Promise<void> {
    const body: Record<string, unknown> = {
      message,
      conversation_id: conversationId,
      stream: true,
    }
    if (!getToken()) body.client_id = getClientId()

    const resp = await fetch(this.url(`/api/v1/public/agents/${agentId}/chat`), {
      method: 'POST',
      headers: this.headers(),
      body: JSON.stringify(body),
      signal,
    })
    if (!resp.ok) {
      let detail = `HTTP ${resp.status}`
      try {
        const data = await resp.json()
        detail = data.message || detail
      } catch { /* 非 JSON */ }
      throw new Error(detail)
    }

    const reader = resp.body!.getReader()
    const decoder = new TextDecoder()
    const parser = createSseParser()

    while (true) {
      const { done, value } = await reader.read()
      if (done) break
      for (const event of parser.push(decoder.decode(value, { stream: true }))) onEvent(event)
    }
    for (const event of parser.finish()) onEvent(event)
    if (!parser.terminalReceived) throw new Error('连接已中断，未收到 Agent 终态')
  }

  /** 非流式对话 */
  async chat(agentId: string, conversationId: string, message: string): Promise<ChatResult> {
    const body: Record<string, unknown> = { message, conversation_id: conversationId, stream: false }
    if (!getToken()) body.client_id = getClientId()
    const resp = await fetch(this.url(`/api/v1/public/agents/${agentId}/chat`), {
      method: 'POST',
      headers: this.headers(),
      body: JSON.stringify(body),
    })
    const data = await resp.json()
    if (!resp.ok || data.code !== 200) throw new Error(data.message || '对话失败')
    const r = data.result
    return {
      conversation_id: r.conversation_id,
      answer: r.answer,
      citations: r.citations || [],
      citation_bindings: r.citation_bindings || [],
    }
  }
}
