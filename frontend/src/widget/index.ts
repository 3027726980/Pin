/**
 * Pin Widget 入口：window.PinWidget
 *
 * 用法：
 *   PinWidget.init({ agentId, apiKey, mode: 'float'|'mobile'|'fullscreen', theme, root })
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
  /** fullscreen 模式的可选挂载容器（默认生成 iframe） */
  root?: string
}

function init(config: PinWidgetConfig): void {
  if (!config.agentId || !config.apiKey) {
    console.error('[PinWidget] init 需要 agentId 和 apiKey')
    return
  }
  const mode = config.mode || 'float'

  if (mode === 'fullscreen' && !config.root) {
    // 全屏模式默认生成 iframe（宿主零依赖）
    const frame = document.createElement('iframe')
    frame.src = `/chat/embed/${encodeURIComponent(config.agentId)}?api_key=${encodeURIComponent(config.apiKey)}`
    frame.style.cssText = 'width:100%;height:100%;border:none;display:block;'
    frame.title = 'AI 助手'
    document.body.appendChild(frame)
    return
  }

  try {
    // float / mobile / fullscreen(root) 共用同一 Shadow DOM 内核
    new ChatWidget(config.agentId, config.apiKey, config.theme || {}, config.root)
  } catch (e) {
    console.error('[PinWidget] 初始化失败:', e)
  }
}

declare global {
  interface Window {
    PinWidget: { init: typeof init }
  }
}

window.PinWidget = { init }
