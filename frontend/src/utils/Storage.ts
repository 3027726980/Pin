/**
 * localStorage 工具 — 带 JSON 序列化 + 过期时间
 */

export const storage = {
  get<T>(key: string): T | null {
    try {
      const raw = localStorage.getItem(key)
      if (!raw) return null
      const data = JSON.parse(raw)
      // 带过期检查
      if (data.expires && Date.now() > data.expires) {
        localStorage.removeItem(key)
        return null
      }
      return data.value as T
    } catch {
      return null
    }
  },

  set(key: string, value: unknown, expiresInSeconds?: number): void {
    const data = {
      value,
      expires: expiresInSeconds ? Date.now() + expiresInSeconds * 1000 : undefined,
    }
    localStorage.setItem(key, JSON.stringify(data))
  },

  remove(key: string): void {
    localStorage.removeItem(key)
  },

  clear(): void {
    localStorage.clear()
  },
}
