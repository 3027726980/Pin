/**
 * axios 实例 + 拦截器
 *
 * - 请求拦截：自动添加 Authorization: Bearer xxx
 * - 响应拦截：解包 { code, message, result }，401 跳登录
 */
import axios from 'axios'
import { storage } from '@/utils/storage'

export const TOKEN_KEY = 'pin_access_token'
export const REFRESH_TOKEN_KEY = 'pin_refresh_token'

const request = axios.create({
  baseURL: '/api',
  timeout: 30000,
  headers: { 'Content-Type': 'application/json' },
})

// ── 请求拦截 ────────────────────────────
request.interceptors.request.use(
  (config) => {
    const token = storage.get<string>(TOKEN_KEY)
    if (token) {
      config.headers.Authorization = `Bearer ${token}`
    }
    return config
  },
  (error) => Promise.reject(error),
)

// ── 响应拦截 ────────────────────────────
request.interceptors.response.use(
  (response) => {
    const { code, message, result } = response.data

    if (code === 200) {
      return result // 直接返回 result，调用方不用解包
    }

    // 401 → 清除 token 跳登录
    if (code === 401) {
      storage.remove(TOKEN_KEY)
      storage.remove(REFRESH_TOKEN_KEY)
      window.location.href = '/login'
      return Promise.reject(new Error(message || '认证失败'))
    }

    return Promise.reject(new Error(message || '请求失败'))
  },
  (error) => {
    if (error.response?.status === 401) {
      storage.remove(TOKEN_KEY)
      storage.remove(REFRESH_TOKEN_KEY)
      window.location.href = '/login'
    }
    return Promise.reject(error)
  },
)

export default request
