/** 主题系统：注入 CSS 变量到 Shadow Root */

export interface WidgetTheme {
  primaryColor?: string
  title?: string
  logo?: string
  bubble?: {
    position?: 'left' | 'right'
    bottom?: number
  }
}

export const DEFAULT_THEME: Required<Pick<WidgetTheme, 'primaryColor' | 'title'>> & WidgetTheme = {
  primaryColor: '#2080f0',
  title: '智能助手',
}

export function normalizeTheme(theme: WidgetTheme = {}): WidgetTheme {
  return { ...DEFAULT_THEME, ...theme }
}

/** 生成主题 CSS 变量字符串（注入 shadow style，必须挂在 :host 选择器下才生效）
 *
 * 注意：裸声明（无选择器）是无效 CSS，浏览器会忽略，导致 --pin-primary 未定义、
 * 所有 var(--pin-primary) 失效，白字元素背景变透明不可见（历史 bug，勿回退）。
 */
export function themeVars(theme: WidgetTheme): string {
  const t = normalizeTheme(theme)
  const vars = [
    `--pin-primary: ${t.primaryColor};`,
  ]
  if (t.bubble?.bottom !== undefined) {
    vars.push(`--pin-bubble-bottom: ${t.bubble.bottom}px;`)
  }
  return `:host {\n  ${vars.join('\n  ')}\n}`
}
