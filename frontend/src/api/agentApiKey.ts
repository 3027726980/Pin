/** Agent 嵌入密钥 API */
import request from './request'

export interface AgentApiKeyItem {
  id: string
  agent_id: string
  name: string | null
  key_preview: string | null
  enabled: number
  last_used_at: string | null
  created_at: string
  updated_at: string
}

export interface AgentApiKeyCreated extends AgentApiKeyItem {
  /** 明文密钥，仅生成时返回一次 */
  api_key: string
}

/** 密钥列表 */
export function listApiKeys(agentId: string): Promise<AgentApiKeyItem[]> {
  return request.get(`/v1/agents/${agentId}/api-keys`)
}

/** 生成密钥（明文只返回一次） */
export function createApiKey(agentId: string, name?: string): Promise<AgentApiKeyCreated> {
  return request.post(`/v1/agents/${agentId}/api-keys`, { name: name || null })
}

/** 编辑密钥（备注/启停） */
export function updateApiKey(
  agentId: string,
  keyId: string,
  data: { name?: string | null; enabled?: number },
): Promise<AgentApiKeyItem> {
  return request.put(`/v1/agents/${agentId}/api-keys/${keyId}`, data)
}

/** 吊销密钥 */
export function deleteApiKey(agentId: string, keyId: string): Promise<void> {
  return request.delete(`/v1/agents/${agentId}/api-keys/${keyId}`)
}
