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

// ── 动态日志级别 ─────────────────────────────

export interface LogLevelInfo {
  current: string
  initial: string
}

/** 查看各 logger 当前/初始级别 */
export function getLogLevels(): Promise<Record<string, LogLevelInfo>> {
  return request.get('/v1/debug/log-level')
}

/** 切换日志级别（expireMinutes 可选：到期自动还原为初始值） */
export function setLogLevel(
  logger: string,
  level: string,
  expireMinutes?: number,
): Promise<{ logger: string; level: string; expire_minutes?: number }> {
  return request.post('/v1/debug/log-level', {
    logger,
    level,
    expire_minutes: expireMinutes,
  })
}
