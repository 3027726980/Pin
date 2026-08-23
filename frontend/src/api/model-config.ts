/**
 * 模型配置 API
 */
import request from './request'

export interface DefaultModelConfigItem {
  id: string
  provider: string
  model_name: string
  model_type: number
  base_url: string
  dimension: number | null
}

export interface UserModelConfigItem {
  id: string
  user_id: string
  provider: string
  model_name: string
  model_type: number
  base_url: string | null
  api_key: string | null
  dimension: number | null
  protocol: string | null
  is_active: boolean
  created_at: string
  updated_at: string
}

export interface ModelConfigCreate {
  provider: string
  model_name: string
  model_type: number
  base_url?: string | null
  api_key?: string | null
  dimension?: number | null
  protocol?: string | null
  is_active?: boolean
}

export interface ModelConfigUpdate {
  provider?: string | null
  model_name?: string | null
  model_type?: number | null
  base_url?: string | null
  api_key?: string | null
  dimension?: number | null
  protocol?: string | null
  is_active?: boolean | null
}

export interface ModelTypeItem {
  code: number
  name: string
}

/** 获取模型类型对照表 */
export function listModelTypes(): Promise<ModelTypeItem[]> {
  return request.get('/v1/settings/user-model-config/model-types')
}

/** 获取所有默认模型 */
export function listDefaultModels(): Promise<DefaultModelConfigItem[]> {
  return request.get('/v1/settings/user-model-config/defaults')
}

/** 获取我的配置 */
export function listMyConfigs(): Promise<UserModelConfigItem[]> {
  return request.get('/v1/settings/user-model-config')
}

/** 创建配置 */
export function createModelConfig(data: ModelConfigCreate): Promise<UserModelConfigItem> {
  return request.post('/v1/settings/user-model-config', data)
}

/** 编辑配置 */
export function updateModelConfig(id: string, data: ModelConfigUpdate): Promise<UserModelConfigItem> {
  return request.put(`/v1/settings/user-model-config/${id}`, data)
}

/** 删除配置 */
export function deleteModelConfig(id: string): Promise<void> {
  return request.delete(`/v1/settings/user-model-config/${id}`)
}
