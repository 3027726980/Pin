/**
 * axios 实例 + 拦截器
 *
 * - 请求拦截：自动添加 Authorization: Bearer xxx
 * - 响应拦截：解包 { code, message, result }
 * - 401 自动刷新 token，刷新失败跳登录
 */
import axios, { type AxiosRequestConfig } from 'axios'
import { storage } from '@/utils/storage'

export const TOKEN_KEY = 'pin_access_token'
export const REFRESH_TOKEN_KEY = 'pin_refresh_token'

const request = axios.create({
  baseURL: '/api',
  timeout: 30000,
  headers: { 'Content-Type': 'application/json' },
})

// ── 刷新锁 ──────────────────────────────
let isRefreshing = false
let pendingQueue: Array<{
  resolve: (token: string) => void
  reject: (err: Error) => void
}> = []

function addPending(resolve: (token: string) => void, reject: (err: Error) => void) {
  pendingQueue.push({ resolve, reject })
}

function flushPending(token: string) {
  pendingQueue.forEach((p) => p.resolve(token))
  pendingQueue = []
}

function rejectPending(err: Error) {
  pendingQueue.forEach((p) => p.reject(err))
  pendingQueue = []
}

/** 退出登录 */
function forceLogout() {
  storage.remove(TOKEN_KEY)
  storage.remove(REFRESH_TOKEN_KEY)
  isRefreshing = false
  rejectPending(new Error('Token 已过期，请重新登录'))
  window.location.href = '/login'
}

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
      return result
    }

    // 401 → 尝试刷新 token
    if (code === 401) {
      return handle401(response.config)
    }

    return Promise.reject(new Error(message || '请求失败'))
  },
  async (error) => {
    // HTTP 状态码 401（如未走统一响应格式的接口）
    if (error.response?.status === 401) {
      return handle401(error.response.config)
    }
    return Promise.reject(error)
  },
)

// ── 401 处理：刷新 → 重试 ────────────────
async function handle401(failedConfig: AxiosRequestConfig): Promise<unknown> {
  // 如果本身就是 refresh 请求且失败了，直接登出（避免死循环）
  if (failedConfig.url?.includes('/v1/auth/refresh')) {
    forceLogout()
    return Promise.reject(new Error('Token 已过期，请重新登录'))
  }

  const refreshToken = storage.get<string>(REFRESH_TOKEN_KEY)
  if (!refreshToken) {
    forceLogout()
    return Promise.reject(new Error('Token 已过期，请重新登录'))
  }

  // 正在刷新 → 排队等待
  if (isRefreshing) {
    return new Promise((resolve, reject) => {
      addPending(
        (newToken: string) => {
          if (failedConfig.headers) {
            failedConfig.headers.Authorization = `Bearer ${newToken}`
          }
          resolve(request(failedConfig))
        },
        reject,
      )
    })
  }

  // 发起刷新
  isRefreshing = true

  try {
    const res = await axios.post('/api/v1/auth/refresh', {
      refresh_token: refreshToken,
    })

    const { code, result } = res.data
    if (code !== 200 || !result) {
      throw new Error('刷新失败')
    }

    const { access_token, refresh_token, expires_in } = result
    storage.set(TOKEN_KEY, access_token, expires_in)
    storage.set(REFRESH_TOKEN_KEY, refresh_token, 7 * 24 * 60 * 60)

    isRefreshing = false
    flushPending(access_token)

    // 重试原请求
    if (failedConfig.headers) {
      failedConfig.headers.Authorization = `Bearer ${access_token}`
    }
    return request(failedConfig)
  } catch {
    forceLogout()
    return Promise.reject(new Error('Token 已过期，请重新登录'))
  }
}

export default request
