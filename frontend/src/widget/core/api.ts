/** 公开接口客户端：X-API-Key 鉴权 + client_id/JWT 双身份 + SSE 流式
 *
 * baseUrl：Pin 后端地址（默认空=相对路径，与宿主同源；跨域嵌入时必传，
 * 如 'https://pin.example.com'）
 */

import { getClientId, getToken, type CitationBinding, type ConvItem, type Msg } from './state'
import { filterUsedCitations, type Citation } from './refs'
import { stripUnboundSourceMarkers } from '../../utils/citations'

export interface ChatEvent {
  type: 'delta' | 'citations' | 'done' | 'error'
  content?: string
  citations?: Citation[]
  /** 完整引用列表（未过滤，渲染时保留原始编号用；主站同款 rawCitations 语义） */
  rawCitations?: Citation[]
  /** 服务端验证后的来源绑定；不可由前端按数组下标推断。 */
  bindings?: CitationBinding[]
  message?: string
  code?: number
}

export interface ChatResult {
  conversation_id: string
  answer: string
  citations: Citation[]
  citation_bindings: CitationBinding[]
}

function isCitationBinding(value: unknown): value is CitationBinding {
  if (!value || typeof value !== 'object') return false
  const item = value as Record<string, unknown>
  return typeof item.source_id === 'string'
    && /^S[1-9]\d*$/.test(item.source_id)
    && typeof item.chunk_id === 'string'
    && typeof item.document_name === 'string'
    && typeof item.claim === 'string'
    && typeof item.quote === 'string'
    && typeof item.score === 'number'
}

/** 公开 SSE 同样不能直接信任 JSON；不完整 binding 不进入 Shadow DOM。 */
function isChatEvent(value: unknown): value is ChatEvent {
  if (!value || typeof value !== 'object' || typeof (value as { type?: unknown }).type !== 'string') return false
  const event = value as Record<string, unknown>
  if (event.type === 'delta') return typeof event.content === 'string'
  if (event.type === 'citations') {
    return Array.isArray(event.citations)
      && (event.bindings === undefined || (Array.isArray(event.bindings) && event.bindings.every(isCitationBinding)))
  }
  if (event.type === 'done') return true
  return event.type === 'error' && typeof event.message === 'string'
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

  /** 流式对话：SSE 解析（delta/citations/done/error），onEvent 回调 */
  async chatStream(
    agentId: string,
    conversationId: string,
    message: string,
    onEvent: (e: ChatEvent) => void,
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
    let buffer = ''
    let fullContent = ''
    let rawCitations: Citation[] = []
    let citationBindings: CitationBinding[] = []

    const emit = (e: ChatEvent) => {
      if (e.type === 'delta' && e.content) fullContent += e.content
      if (e.type === 'citations' && e.citations) rawCitations = e.citations
      if (e.type === 'citations' && e.bindings) citationBindings = e.bindings
      if (e.type === 'done') {
        const sanitizedContent = stripUnboundSourceMarkers(
          fullContent, citationBindings.map(binding => binding.source_id))
        onEvent({
          type: 'done',
          content: sanitizedContent,
          citations: citationBindings.length ? [] : filterUsedCitations(rawCitations, sanitizedContent),
          rawCitations,  // 完整列表：UI 渲染时按内容 [N] 过滤并保留原始编号
          bindings: citationBindings,
        })
      } else {
        onEvent(e)
      }
    }

    while (true) {
      const { done, value } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true })
      const lines = buffer.split('\n')
      buffer = lines.pop() || ''
      for (const line of lines) {
        const trimmed = line.trim()
        if (!trimmed.startsWith('data:')) continue
        const payload = trimmed.slice(5).trim()
        if (!payload) continue
        try {
          const event: unknown = JSON.parse(payload)
          if (isChatEvent(event)) emit(event)
        } catch { /* 忽略坏帧 */ }
      }
    }
    // 兜底：流结束但没收到 done（异常断流）
    if (rawCitations.length > 0 || citationBindings.length > 0 || fullContent) {
      const sanitizedContent = stripUnboundSourceMarkers(
        fullContent, citationBindings.map(binding => binding.source_id))
      onEvent({
        type: 'done', content: sanitizedContent,
        citations: citationBindings.length ? [] : filterUsedCitations(rawCitations, sanitizedContent),
        rawCitations,
        bindings: citationBindings,
      })
    }
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
