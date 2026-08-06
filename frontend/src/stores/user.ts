import { defineStore } from 'pinia'
import { ref } from 'vue'
import {
  loginApi,
  refreshApi,
  getMeApi,
  type TokenResult,
  type UserInfo,
} from '@/api/auth'
import { storage } from '@/utils/storage'
import { TOKEN_KEY, REFRESH_TOKEN_KEY } from '@/api/request'

export const useUserStore = defineStore('user', () => {
  const token = ref<string>(storage.get<string>(TOKEN_KEY) || '')
  const refreshToken = ref<string>(storage.get<string>(REFRESH_TOKEN_KEY) || '')
  const userInfo = ref<UserInfo | null>(null)

  /** 是否已登录 */
  const isLoggedIn = () => !!token.value

  /** 登录 */
  async function login(username: string, password: string) {
    const result: TokenResult = await loginApi({ username, password })
    saveTokens(result)
    return result
  }

  /** 刷新 Token */
  async function refresh() {
    const result: TokenResult = await refreshApi(refreshToken.value)
    saveTokens(result)
    return result
  }

  /** 保存 Token */
  function saveTokens(result: TokenResult) {
    token.value = result.access_token
    refreshToken.value = result.refresh_token
    storage.set(TOKEN_KEY, result.access_token, result.expires_in)
    storage.set(REFRESH_TOKEN_KEY, result.refresh_token, 7 * 24 * 60 * 60)
  }

  /** 获取当前用户信息 */
  async function fetchUserInfo() {
    userInfo.value = await getMeApi()
    return userInfo.value
  }

  /** 登出 */
  function logout() {
    token.value = ''
    refreshToken.value = ''
    userInfo.value = null
    storage.remove(TOKEN_KEY)
    storage.remove(REFRESH_TOKEN_KEY)
  }

  return {
    token,
    refreshToken,
    userInfo,
    isLoggedIn,
    login,
    refresh,
    fetchUserInfo,
    logout,
  }
})
