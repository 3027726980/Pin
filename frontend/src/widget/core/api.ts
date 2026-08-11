/** 公开接口客户端：X-API-Key 鉴权 + client_id/JWT 双身份 + SSE 流式 */

import { getClientId, getToken } from './state'
import { filterUsedCitations, type Citation } from './refs'

export interface ChatEvent {
  type: 'delta' | 'citations' | 'done' | 'error'
  content?: string
  citations?: Citation[]
  message?: string
  code?: number
}

export interface ChatResult {
  conversation_id: string
  answer: string
  citations: Citation[]
}

export class PublicApi {
  private apiKey: string

  constructor(apiKey: string) {
    this.apiKey = apiKey
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
    const resp = await fetch('/api/v1/public/auth/login', {
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
    const resp = await fetch('/api/v1/public/conversations', {
      method: 'POST',
      headers: this.headers(),
      body: JSON.stringify({ agent_id: agentId }),
    })
    const data = await resp.json()
    if (!resp.ok || data.code !== 200) throw new Error(data.message || '创建会话失败')
    return data.result
  }

  async listConversations(agentId: string): Promise<ConvItem[]> {
    const params = this.identityParams({ agent_id: agentId })
    const resp = await fetch(`/api/v1/public/conversations?${new URLSearchParams(params)}`, {
      headers: this.headers(),
    })
    const data = await resp.json()
    if (!resp.ok || data.code !== 200) throw new Error(data.message || '会话列表加载失败')
    return data.result.items
  }

  async listMessages(convId: string): Promise<Msg[]> {
    const params = this.identityParams({ page: '1', page_size: '100' })
    const resp = await fetch(`/api/v1/public/conversations/${convId}/messages?${new URLSearchParams(params)}`, {
      headers: this.headers(),
    })
    const data = await resp.json()
    if (!resp.ok || data.code !== 200) throw new Error(data.message || '历史消息加载失败')
    return data.result.items.map((m: { role: string; content: string; citations: Citation[] | null }) => ({
      role: m.role as 'user' | 'assistant',
      content: m.content,
      citations: m.citations || [],
      rawCitations: m.citations || [],
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

    const resp = await fetch(`/api/v1/public/agents/${agentId}/chat`, {
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

    const emit = (e: ChatEvent) => {
      if (e.type === 'delta' && e.content) fullContent += e.content
      if (e.type === 'citations' && e.citations) rawCitations = e.citations
      if (e.type === 'done') {
        onEvent({
          type: 'done',
          content: fullContent,
          citations: filterUsedCitations(rawCitations, fullContent),
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
          emit(JSON.parse(payload))
        } catch { /* 忽略坏帧 */ }
      }
    }
    // 兜底：流结束但没收到 done（异常断流）
    if (rawCitations.length > 0 || fullContent) {
      onEvent({ type: 'done', content: fullContent, citations: filterUsedCitations(rawCitations, fullContent) })
    }
  }

  /** 非流式对话 */
  async chat(agentId: string, conversationId: string, message: string): Promise<ChatResult> {
    const body: Record<string, unknown> = { message, conversation_id: conversationId, stream: false }
    if (!getToken()) body.client_id = getClientId()
    const resp = await fetch(`/api/v1/public/agents/${agentId}/chat`, {
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
    }
  }
}

// 引用类型占位（与 state.Msg 对齐）
import type { ConvItem, Msg } from './state'
