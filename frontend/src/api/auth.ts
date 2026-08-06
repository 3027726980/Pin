/**
 * 认证 API：登录 / 刷新 / 获取当前用户
 */
import request from './request'

export interface LoginParams {
  username: string
  password: string
}

export interface TokenResult {
  access_token: string
  refresh_token: string
  token_type: string
  expires_in: number
}

export interface UserInfo {
  id: string
  username: string
  is_superuser: boolean
  is_active: boolean
}

/** POST /v1/auth/login */
export function loginApi(params: LoginParams): Promise<TokenResult> {
  return request.post('/v1/auth/login', params)
}

/** POST /v1/auth/refresh */
export function refreshApi(refreshToken: string): Promise<TokenResult> {
  return request.post('/v1/auth/refresh', { refresh_token: refreshToken })
}

/** GET /v1/auth/me — 获取当前用户信息（后端待实现） */
export function getMeApi(): Promise<UserInfo> {
  return request.get('/v1/auth/me')
}
