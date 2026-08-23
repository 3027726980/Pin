/**
 * 厂商管理 API（Phase 4.9 厂商实体化）
 */
import request from './request'

export interface ProviderItem {
  id: string | null
  name: string
  protocol: string
  description: string | null
  source: 'preset' | 'custom'
  model_count: number
  created_at: string | null
}

export interface ProviderCreatePayload {
  name: string
  protocol?: string
  description?: string | null
}

export interface ProviderUpdatePayload {
  name?: string
  protocol?: string
  description?: string | null
}

/** 厂商合并列表（预置 + 自定义） */
export function listProviders(): Promise<ProviderItem[]> {
  return request.get('/v1/settings/providers')
}

/** 添加自定义厂商 */
export function createProvider(data: ProviderCreatePayload): Promise<ProviderItem> {
  return request.post('/v1/settings/providers', data)
}

/** 编辑自定义厂商 */
export function updateProvider(id: string, data: ProviderUpdatePayload): Promise<ProviderItem> {
  return request.put(`/v1/settings/providers/${id}`, data)
}

/** 删除自定义厂商 */
export function deleteProvider(id: string): Promise<void> {
  return request.delete(`/v1/settings/providers/${id}`)
}
