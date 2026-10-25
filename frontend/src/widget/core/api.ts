import { saveDownload, type CapabilityMention, type SkillArtifact, type Capabilities } from '../../chat-core/capabilities'
/** 作者：LHF；时间：2026-10-25；作用：提供会话上下文手动压缩交互。 */
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
  artifacts?: SkillArtifact[]
  conversation_id: string
  answer: string
  citations: Citation[]
  citation_bindings: CitationBinding[]
}

export class PublicApi {
  /** 读取 Key 绑定 Agent 的 @ 候选。 */
  async capabilities(agentId: string): Promise<Capabilities> {
    const response = await fetch(this.url(`/api/v1/public/agents/${agentId}/capabilities`), { headers: this.headers() })
    const data = await response.json()
    if (!response.ok || data.code !== 200) throw new Error(data.message || '能力列表读取失败')
    return data.result
  }
  /** 产物下载同时带上 Key 和会话身份。 */
  async downloadArtifact(agentId: string, artifact: SkillArtifact): Promise<void> {
    const params = this.identityParams({ path: artifact.path })
    const response = await fetch(this.url(`/api/v1/public/agents/${agentId}/skill-runs/${artifact.run_id}/artifacts?${new URLSearchParams(params)}`), { headers: this.headers() })
    if (!response.ok) { const data = await response.json(); throw new Error(data.message || '产物不存在或已过期') }
    saveDownload(await response.blob(), artifact.name)
  }

  private apiKey: string
  private baseUrl: string

  /** 作者：LHF；2026-10-25；带 Agent 和访客身份手动压缩会话。 */
  async compactConversation(agentId: string, convId: string): Promise<{ compressed: boolean; before_tokens: number; after_tokens: number }> {
    const params = this.identityParams({ agent_id: agentId })
    const resp = await fetch(this.url(`/api/v1/public/conversations/${convId}/compact?${new URLSearchParams(params)}`), {
      method: 'POST', headers: this.headers(),
    })
    const data = await resp.json()
    if (!resp.ok || data.code !== 200) throw new Error(data.message || '上下文压缩失败')
    return data.result
  }

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
    return data.result.items.map((m: { role: string; content: string; citations: Citation[] | null; citation_bindings?: CitationBinding[] | null; mentions?: CapabilityMention[]; artifacts?: SkillArtifact[] }) => ({
      role: m.role as 'user' | 'assistant',
      content: m.content,
      mentions: m.mentions || [],
      artifacts: m.artifacts || [],
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
    mentions: CapabilityMention[] = [],
  ): Promise<void> {
    const body: Record<string, unknown> = {
      message,
      mentions,
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
