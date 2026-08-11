/**
 * Pin Widget 入口：window.PinWidget
 *
 * 用法：
 *   PinWidget.init({ agentId, apiKey, mode: 'float'|'mobile'|'fullscreen', theme, root, baseUrl })
 *   - agentId / apiKey：必填（Agent 嵌入设置里生成）
 *   - baseUrl：Pin 后端地址（默认空 = 相对路径；跨域嵌入必传，如 'https://pin.example.com'）
 *   - float：右下角悬浮球 + 弹窗面板（桌面端）
 *   - mobile：响应式（小屏底部抽屉全屏滑出，同一内核）
 *   - fullscreen：生成 iframe 指向 /chat/embed/{agentId}?api_key=...，或传入 root 直接全屏渲染
 */
import { ChatWidget } from './ui/chat'
import type { WidgetTheme } from './core/theme'

export interface PinWidgetConfig {
  agentId: string
  apiKey: string
  mode?: 'float' | 'mobile' | 'fullscreen'
  theme?: WidgetTheme
  /** Pin 后端地址（默认空 = 相对路径；跨域嵌入必传） */
  baseUrl?: string
  /** fullscreen 模式的可选挂载容器（默认生成 iframe） */
  root?: string
}

/**
 * 全局状态（挂在 window 上而非模块闭包）
 *
 * 原因：宿主可能重复加载 widget.js（如 test.html 反复点击、SPA 动态注入）。
 * 若注册表在模块闭包内，script 重新执行后闭包被新闭包覆盖，旧实例信息丢失，
 * 再次 init 将叠加浮窗。挂 window 后新旧闭包共享同一份实例表。
 */
interface WidgetState {
  /** key = agentId；float/mobile/fullscreen+root 共用的 ChatWidget 实例 */
  instances: Map<string, ChatWidget>
  /** fullscreen iframe 模式引用 */
  iframes: Map<string, HTMLIFrameElement>
}

const STATE_KEY = '__PIN_WIDGET_STATE__'

function getState(): WidgetState {
  const g = window as unknown as Record<string, unknown>
  if (!g[STATE_KEY]) {
    g[STATE_KEY] = { instances: new Map(), iframes: new Map() }
  }
  return g[STATE_KEY] as WidgetState
}

/** 清理同 agentId 的遗留 DOM（注册表不可用时的兜底；不依赖实例对象即可删除） */
function removeStaleDom(agentId: string): void {
  document.querySelectorAll(`.pin-widget-host[data-pin-agent="${agentId}"]`)
    .forEach(el => el.remove())
  document.querySelectorAll(`iframe[data-pin-agent="${agentId}"]`)
    .forEach(el => el.remove())
}

function init(config: PinWidgetConfig): void {
  if (!config.agentId || !config.apiKey) {
    console.error('[PinWidget] init 需要 agentId 和 apiKey')
    return
  }
  const mode = config.mode || 'float'
  const baseUrl = detectBaseUrl(config.baseUrl)
  const state = getState()

  // ① 注册表去重：同 agentId 先销毁旧实例（解绑 document 监听器）
  const prev = state.instances.get(config.agentId)
  if (prev) {
    prev.destroy()
    state.instances.delete(config.agentId)
  }
  const prevFrame = state.iframes.get(config.agentId)
  if (prevFrame) {
    prevFrame.remove()
    state.iframes.delete(config.agentId)
  }
  // ② DOM 兜底：即使注册表被覆盖/清空，也确保同 agentId 不残留旧浮窗
  removeStaleDom(config.agentId)

  if (mode === 'fullscreen' && !config.root) {
    // 全屏模式默认生成 iframe（宿主零依赖）
    const frame = document.createElement('iframe')
    frame.src = `${baseUrl}/chat/embed/${encodeURIComponent(config.agentId)}?api_key=${encodeURIComponent(config.apiKey)}`
    frame.style.cssText = 'width:100%;height:100%;border:none;display:block;'
    frame.title = 'AI 助手'
    frame.setAttribute('data-pin-agent', config.agentId)
    document.body.appendChild(frame)
    state.iframes.set(config.agentId, frame)
    return
  }

  try {
    // float / mobile / fullscreen(root) 共用同一 Shadow DOM 内核
    const widget = new ChatWidget(config.agentId, config.apiKey, config.theme || {}, config.root, baseUrl)
    state.instances.set(config.agentId, widget)
  } catch (e) {
    console.error('[PinWidget] 初始化失败:', e)
  }
}

/** 销毁指定 Agent 的实例（移除浮窗/面板/iframe，宿主路由切换等场景可用） */
function destroy(agentId: string): void {
  const state = getState()
  const w = state.instances.get(agentId)
  if (w) {
    w.destroy()
    state.instances.delete(agentId)
  }
  const f = state.iframes.get(agentId)
  if (f) {
    f.remove()
    state.iframes.delete(agentId)
  }
  // DOM 兜底同步清理
  removeStaleDom(agentId)
}

/** 销毁页面全部 widget 实例（重新加载/切换宿主页面时清理） */
function destroyAll(): void {
  const state = getState()
  for (const w of state.instances.values()) w.destroy()
  state.instances.clear()
  for (const f of state.iframes.values()) f.remove()
  state.iframes.clear()
  // DOM 兜底同步清理
  document.querySelectorAll('.pin-widget-host').forEach(el => el.remove())
  document.querySelectorAll('iframe[data-pin-agent]').forEach(el => el.remove())
}

/**
 * 推导后端地址：显式 baseUrl 优先；否则从 widget.js 自身加载地址推导
 * （脚本托管在后端 → 脚本来源即后端地址，用户无需填写）；
 * 都失败时回退当前页面地址。
 */
function detectBaseUrl(explicit?: string): string {
  if (explicit) return explicit.replace(/\/$/, '')
  try {
    const scripts = document.getElementsByTagName('script')
    for (let i = scripts.length - 1; i >= 0; i--) {
      const src = scripts[i].src || ''
      if (src && src.includes('/widget/widget.js')) {
        return new URL(src).origin
      }
    }
  } catch { /* 忽略 */ }
  return location.origin
}

declare global {
  interface Window {
    PinWidget: {
      init: typeof init
      destroy: typeof destroy
      destroyAll: typeof destroyAll
    }
  }
}

window.PinWidget = { init, destroy, destroyAll }
