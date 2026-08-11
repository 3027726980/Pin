/** widget 状态：访客身份 + 会话 + 消息（localStorage 持久化） */

export interface ConvItem {
  id: string
  agent_id: string
  title: string | null
  message_count: number
  created_at: string
  updated_at: string
}

export interface Msg {
  role: 'user' | 'assistant'
  content: string
  citations: Citation[]
  rawCitations: Citation[]
  error?: boolean
  pending?: boolean
}

export interface Citation {
  chunk_id: string
  document_name: string
  content: string
  score: number
}

const CLIENT_ID_KEY = 'pin_client_id'
const TOKEN_KEY = 'pin_widget_token'
const USER_KEY = 'pin_widget_user'

export function getClientId(): string {
  let cid = localStorage.getItem(CLIENT_ID_KEY)
  if (!cid) {
    // crypto.randomUUID 需安全上下文，兜底手动生成
    cid = 'c_' + Math.random().toString(36).slice(2, 10) + Date.now().toString(36)
    localStorage.setItem(CLIENT_ID_KEY, cid)
  }
  return cid
}

export function getToken(): string | null {
  return localStorage.getItem(TOKEN_KEY)
}

export function setToken(token: string | null): void {
  if (token) localStorage.setItem(TOKEN_KEY, token)
  else localStorage.removeItem(TOKEN_KEY)
}

export interface WidgetUser {
  id: string
  username: string
}

export function getUser(): WidgetUser | null {
  const raw = localStorage.getItem(USER_KEY)
  return raw ? JSON.parse(raw) as WidgetUser : null
}

export function setUser(user: WidgetUser | null): void {
  if (user) localStorage.setItem(USER_KEY, JSON.stringify(user))
  else localStorage.removeItem(USER_KEY)
}
