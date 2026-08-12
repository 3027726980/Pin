/**
 * 系统设置 API（通用设置：system_settings 表，JSON 配置存储）
 */
import request from './request'

export interface SystemSetting {
  key: string
  value: Record<string, unknown>
  description?: string | null
  updated_at?: string
}

export interface RedactRule {
  type: 'field_name' | 'value_pattern'
  pattern: string
  mask: 'keep_4_4' | 'full_mask'
}

export interface RedactRulesConfig {
  enabled: boolean
  rules: RedactRule[]
}

export function listSettings(): Promise<SystemSetting[]> {
  return request.get('/v1/settings')
}

export function updateSetting(
  key: string,
  value: Record<string, unknown>,
): Promise<{ key: string; value: Record<string, unknown> }> {
  return request.put(`/v1/settings/${key}`, { value })
}
