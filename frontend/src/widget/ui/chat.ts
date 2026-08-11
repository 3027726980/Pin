/**
 * widget 对话组件：Shadow DOM 渲染（浮球 + 面板 + 会话列表 + 登录表单）
 * 事件委托 + 局部更新；样式完全隔离在 shadow root 内
 */
import { PublicApi } from '../core/api'
import { splitRefs } from '../core/refs'
import { getToken, getUser, setToken, setUser, type ConvItem, type Msg } from '../core/state'
import { themeVars, type WidgetTheme } from '../core/theme'

const STYLE = `
:host { all: initial; }
* { box-sizing: border-box; margin: 0; padding: 0; font-family: -apple-system, "PingFang SC", "Microsoft YaHei", sans-serif; }
.pin-bubble {
  position: fixed; right: 24px; bottom: var(--pin-bubble-bottom, 24px);
  width: 56px; height: 56px; border-radius: 50%;
  background: var(--pin-primary); color: #fff;
  display: flex; align-items: center; justify-content: center;
  cursor: pointer; box-shadow: 0 4px 16px rgba(0,0,0,.18);
  font-size: 26px; z-index: 2147483000; user-select: none;
  transition: transform .15s;
}
.pin-bubble:hover { transform: scale(1.06); }
.pin-bubble .dot {
  position: absolute; top: 2px; right: 2px; width: 14px; height: 14px;
  background: #f5222d; border: 2px solid #fff; border-radius: 50%; display: none;
}
.pin-bubble .dot.show { display: block; }

.pin-panel {
  position: fixed; right: 24px; bottom: calc(var(--pin-bubble-bottom, 24px) + 68px);
  width: 380px; height: 560px; max-height: calc(100vh - 120px);
  background: #fff; border-radius: 12px; box-shadow: 0 8px 40px rgba(0,0,0,.2);
  display: none; flex-direction: column; overflow: hidden;
  z-index: 2147483001; border: 1px solid rgba(0,0,0,.08);
}
.pin-panel.open { display: flex; }
.pin-header {
  display: flex; align-items: center; gap: 10px; padding: 12px 16px;
  background: var(--pin-primary); color: #fff; flex-shrink: 0;
}
.pin-header img { width: 30px; height: 30px; border-radius: 50%; object-fit: cover; background: rgba(255,255,255,.2); }
.pin-header .title { flex: 1; font-size: 15px; font-weight: 600; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.pin-header .btn { background: none; border: none; color: #fff; font-size: 16px; cursor: pointer; padding: 2px 6px; opacity: .9; }
.pin-header .btn:hover { opacity: 1; }

.pin-body { flex: 1; overflow-y: auto; padding: 14px; background: #f7f8fa; }
.pin-empty { text-align: center; color: #999; padding: 40px 0; font-size: 13px; }
.pin-msg { margin-bottom: 12px; display: flex; }
.pin-msg.user { justify-content: flex-end; }
.pin-bubble-msg { max-width: 82%; padding: 9px 12px; border-radius: 10px; font-size: 14px; line-height: 1.6; white-space: pre-wrap; word-break: break-word; }
.pin-msg.user .pin-bubble-msg { background: var(--pin-primary); color: #fff; border-bottom-right-radius: 2px; }
.pin-msg.assistant .pin-bubble-msg { background: #fff; color: #333; border: 1px solid #eee; border-bottom-left-radius: 2px; }
.pin-msg .err { color: #cf1322; }
.pin-ref { display: inline-block; padding: 0 3px; margin: 0 1px; font-size: 12px; font-weight: 600; color: var(--pin-primary); cursor: pointer; }
.pin-cites { margin-top: 8px; border-top: 1px dashed #eee; padding-top: 8px; }
.pin-cite-item { font-size: 12px; color: #666; margin-bottom: 6px; display: none; }
.pin-cite-item.open { display: block; }
.pin-cite-item .doc { color: var(--pin-primary); font-weight: 600; margin-bottom: 2px; }
.pin-cite-item .txt { max-height: 80px; overflow: hidden; text-overflow: ellipsis; }

.pin-input-row { display: flex; gap: 8px; padding: 10px 12px; border-top: 1px solid #eee; background: #fff; flex-shrink: 0; }
.pin-input-row textarea {
  flex: 1; border: 1px solid #e5e5e5; border-radius: 8px; padding: 8px 10px;
  font-size: 14px; resize: none; outline: none; max-height: 90px; font-family: inherit;
}
.pin-input-row textarea:focus { border-color: var(--pin-primary); }
.pin-send {
  border: none; border-radius: 8px; background: var(--pin-primary); color: #fff;
  padding: 0 16px; cursor: pointer; font-size: 14px;
}
.pin-send:disabled { opacity: .5; cursor: not-allowed; }
/* 轻提示：导航操作失败等场景的一次性提示（不污染消息列表） */
.pin-toast {
  position: absolute; left: 50%; bottom: 76px; transform: translateX(-50%);
  background: rgba(0,0,0,.78); color: #fff; font-size: 13px;
  padding: 8px 14px; border-radius: 8px; z-index: 5;
  display: none; max-width: 82%; text-align: center;
  pointer-events: none; overflow: hidden; text-overflow: ellipsis;
}
.pin-toast.show { display: block; }

.pin-stop {
  border: none; border-radius: 8px; background: #ff4d4f; color: #fff;
  padding: 0 14px; cursor: pointer; font-size: 13px;
}

.pin-drawer {
  position: absolute; inset: 0; background: #fff; display: none; flex-direction: column; z-index: 2;
}
.pin-drawer.open { display: flex; }
.pin-drawer-header { display: flex; align-items: center; padding: 12px 16px; border-bottom: 1px solid #eee; font-weight: 600; font-size: 15px; }
.pin-drawer-header .btn { margin-left: auto; background: none; border: none; font-size: 15px; cursor: pointer; color: #666; }
.pin-drawer-body { flex: 1; overflow-y: auto; padding: 8px 0; }
.pin-conv-item { padding: 10px 16px; cursor: pointer; font-size: 14px; color: #333; border-bottom: 1px solid #f5f5f5; }
.pin-conv-item:hover { background: #f7f8fa; }
.pin-conv-item .t { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.pin-conv-item .meta { font-size: 12px; color: #999; margin-top: 2px; }
.pin-new-conv { margin: 12px 16px; padding: 8px 0; text-align: center; background: var(--pin-primary); color: #fff; border-radius: 8px; cursor: pointer; font-size: 14px; }

.pin-login { padding: 16px; display: flex; flex-direction: column; gap: 10px; }
.pin-login input { padding: 9px 10px; border: 1px solid #e5e5e5; border-radius: 8px; font-size: 14px; outline: none; }
.pin-login input:focus { border-color: var(--pin-primary); }
.pin-login .submit { padding: 9px 0; background: var(--pin-primary); color: #fff; border: none; border-radius: 8px; cursor: pointer; font-size: 14px; }
.pin-login .err { color: #cf1322; font-size: 12px; }
.pin-login .hint { font-size: 12px; color: #999; text-align: center; }

@media (max-width: 640px) {
  .pin-bubble { right: 16px; bottom: 16px; width: 50px; height: 50px; }
  .pin-panel { right: 0; bottom: 0; left: 0; width: 100%; height: 100%; max-height: none; border-radius: 0; }
}

/* 全屏模式：容器占满宿主给定区域 */
.pin-root-full .pin-panel { position: absolute; inset: 0; right: auto; bottom: auto; width: 100%; height: 100%; max-height: none; border-radius: 0; display: flex; }
.pin-root-full .pin-bubble { display: none; }
`

export class ChatWidget {
  private api: PublicApi
  private theme: WidgetTheme
  private agentId: string
  private shadow: ShadowRoot
  private rootEl: HTMLElement
  private msgs: Msg[] = []
  private convs: ConvItem[] = []
  private activeConv: ConvItem | null = null
  private streaming = false
  private drawerOpen = false
  private loginOpen = false
  private abortCtrl: AbortController | null = null
  /** shadow host 元素（destroy 时移除） */
  private hostEl!: HTMLElement
  /** document 级点击监听（需保存引用以便 destroy 时解绑） */
  private outsideClickHandler: ((e: MouseEvent) => void) | null = null
  /** 销毁标记：销毁后所有渲染/交互短路（防异步回调操作已移除 DOM） */
  private destroyed = false
  /** toast 轻提示元素 + 自动消失计时器 */
  private toastEl: HTMLElement | null = null
  private toastTimer: number | null = null

  // DOM 引用
  private el: Record<string, HTMLElement> = {}
  private bubble!: HTMLElement
  private panel!: HTMLElement
  private bodyEl!: HTMLElement
  private inputEl!: HTMLTextAreaElement
  private sendBtn!: HTMLButtonElement
  private stopBtn!: HTMLButtonElement
  private loginBtn!: HTMLButtonElement
  private convBtn!: HTMLButtonElement
  private drawerEl!: HTMLElement
  private drawerBodyEl!: HTMLElement
  private headerEl!: HTMLElement

  constructor(agentId: string, apiKey: string, theme: WidgetTheme,
              mountRoot?: string, baseUrl = '') {
    this.agentId = agentId
    this.theme = theme
    this.api = new PublicApi(apiKey, baseUrl)

    // 挂载点：fullscreen 指定 root，float/mobile 挂 body
    if (mountRoot) {
      const root = document.querySelector(mountRoot) as HTMLElement | null
      if (!root) throw new Error(`PinWidget: 挂载点不存在 ${mountRoot}`)
      this.rootEl = root
    } else {
      this.rootEl = document.body
    }
    const host = document.createElement('div')
    host.className = 'pin-widget-host'
    // DOM 级标记：供重复 init 时兜底扫描（即使注册表闭包被新 script 覆盖也能找到旧 DOM）
    host.setAttribute('data-pin-agent', agentId)
    this.hostEl = host
    this.rootEl.appendChild(host)
    this.shadow = host.attachShadow({ mode: 'open' })
    this.shadow.innerHTML = `<style>${STYLE}\n${themeVars(theme)}</style>`
    this.renderShell()
    this.bindEvents()
    this.initConversation()
  }

  // ── 外壳渲染 ────────────────────────────
  private renderShell() {
    const t = this.theme
    this.shadow.innerHTML = `
      <style>${STYLE}\n${themeVars(t)}</style>
      <div class="pin-bubble" data-action="toggle">💬<span class="dot"></span></div>
      <div class="pin-panel">
        <div class="pin-header">
          ${t.logo ? `<img src="${escapeHtml(t.logo)}" alt="logo">` : ''}
          <span class="title">${escapeHtml(t.title || '智能助手')}</span>
          <button class="btn" data-action="login" title="登录">👤</button>
          <button class="btn" data-action="drawer" title="历史会话">☰</button>
          <button class="btn" data-action="close" title="关闭">✕</button>
        </div>
        <div class="pin-body"></div>
        <div class="pin-input-row">
          <textarea placeholder="输入消息，Enter 发送" rows="1"></textarea>
          <button class="pin-send">发送</button>
        </div>
        <div class="pin-drawer">
          <div class="pin-drawer-header">
            <span>历史会话</span>
            <button class="btn" data-action="close-drawer">✕</button>
          </div>
          <div class="pin-drawer-body"></div>
          <div class="pin-new-conv" data-action="new-conv">+ 新会话</div>
        </div>
      </div>
    `
    this.bubble = this.shadow.querySelector('.pin-bubble')!
    this.panel = this.shadow.querySelector('.pin-panel')!
    this.bodyEl = this.shadow.querySelector('.pin-body')!
    this.inputEl = this.shadow.querySelector('textarea')!
    this.sendBtn = this.shadow.querySelector('.pin-send')!
    this.stopBtn = document.createElement('button')
    this.stopBtn.className = 'pin-stop'
    this.stopBtn.textContent = '停止'
    this.stopBtn.setAttribute('data-action', 'stop')
    this.loginBtn = this.shadow.querySelector('[data-action="login"]')!
    this.convBtn = this.shadow.querySelector('[data-action="drawer"]')!
    this.drawerEl = this.shadow.querySelector('.pin-drawer')!
    this.drawerBodyEl = this.shadow.querySelector('.pin-drawer-body')!
    this.headerEl = this.shadow.querySelector('.pin-header')!
    // 全屏模式标记
    if (this.rootEl !== document.body) {
      this.shadow.host.classList.add('pin-root-full')
      this.panel.classList.add('open')
      this.bubble.style.display = 'none'
    }
  }

  // ── 事件绑定（委托） ─────────────────────
  private bindEvents() {
    this.shadow.addEventListener('click', (e) => {
      const target = (e.target as HTMLElement).closest('[data-action]') as HTMLElement | null
      if (!target) return
      const action = target.dataset.action
      if (action === 'toggle') this.togglePanel()
      else if (action === 'close') this.panel.classList.remove('open')
      else if (action === 'drawer') this.toggleDrawer()
      else if (action === 'close-drawer') this.toggleDrawer(false)
      else if (action === 'new-conv') this.newConversation()
      else if (action === 'login') this.toggleLogin()
      else if (action === 'logout') this.logout()
      else if (action === 'stop') this.stopStream()
      else if (action === 'open-conv') this.openConversation((target as HTMLElement).dataset.convId!)
      else if (action === 'cite') this.toggleCite((target as HTMLElement).dataset.msg!, (target as HTMLElement).dataset.idx!)
      else if (action === 'send') this.send()
    })
    this.inputEl.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault()
        this.send()
      }
    })
    // 点击面板外部区域 → 关闭（浮窗/移动端模式）；保存引用供 destroy 解绑
    this.outsideClickHandler = (e: MouseEvent) => {
      if (this.rootEl === document.body && this.panel.classList.contains('open')) {
        const host = this.shadow.host
        if (host !== (e.target as Node) && !host.contains(e.target as Node)) {
          this.panel.classList.remove('open')
          this.drawerEl.classList.remove('open')
        }
      }
    }
    document.addEventListener('click', this.outsideClickHandler)
  }

  // ── 面板开关 ────────────────────────────
  private togglePanel() {
    const open = this.panel.classList.toggle('open')
    if (open) this.refreshLoginBtn()
  }

  private toggleDrawer(force?: boolean) {
    this.drawerOpen = force === undefined ? !this.drawerOpen : force
    this.drawerEl.classList.toggle('open', this.drawerOpen)
    if (this.drawerOpen) {
      this.loginOpen = false
      this.renderDrawerBody()
    }
  }

  private toggleLogin() {
    if (getToken()) {
      this.logout()
      return
    }
    this.loginOpen = !this.loginOpen
    this.drawerOpen = false
    this.drawerEl.classList.remove('open')
    this.renderBody()
  }

  private refreshLoginBtn() {
    this.loginBtn.textContent = getToken() ? '⏻' : '👤'
  }

  // ── 初始化会话 ──────────────────────────
  private async initConversation() {
    try {
      const convs = await this.api.listConversations(this.agentId)
      this.convs = convs
      if (convs.length > 0) {
        await this.openConversation(convs[0].id)
      } else {
        await this.newConversation()
      }
    } catch (e) {
      this.msgs = [{ role: 'assistant', content: `[错误] ${(e as Error).message}`, citations: [], rawCitations: [] }]
      this.renderBody()
    }
  }

  // ── 会话操作 ────────────────────────────
  private async newConversation() {
    try {
      const conv = await this.api.createConversation(this.agentId)
      this.activeConv = { ...conv, agent_id: this.agentId, message_count: 0, created_at: '', updated_at: '' }
      this.convs.unshift(this.activeConv)
      this.msgs = []
      this.drawerOpen = false
      this.drawerEl.classList.remove('open')
      this.renderBody()
    } catch (e) {
      // 写操作失败（如限流 429）：轻提示，不污染当前消息列表
      this.showToast((e as Error).message)
    }
  }

  private async openConversation(convId: string) {
    try {
      const conv = this.convs.find(c => c.id === convId) || null
      this.activeConv = conv
      const msgs = await this.api.listMessages(convId)
      this.msgs = msgs
      this.drawerOpen = false
      this.drawerEl.classList.remove('open')
      this.renderBody()
      if (this.panel.classList.contains('open') || this.rootEl !== document.body) {
        this.scrollBottom()
      }
    } catch (e) {
      // 读操作失败（Key 失效/网络等）：轻提示，不污染当前消息列表
      this.showToast((e as Error).message)
    }
  }

  // ── 发送消息 ────────────────────────────
  private async send() {
    const text = this.inputEl.value.trim()
    if (!text || this.streaming || !this.activeConv) return
    this.inputEl.value = ''
    this.msgs.push({ role: 'user', content: text, citations: [], rawCitations: [] })
    const assistantMsg: Msg = { role: 'assistant', content: '', citations: [], rawCitations: [], pending: true }
    this.msgs.push(assistantMsg)
    this.renderBody()
    this.scrollBottom()

    this.streaming = true
    this.abortCtrl = new AbortController()
    this.renderInputRow()
    try {
      await this.api.chatStream(
        this.agentId,
        this.activeConv.id,
        text,
        (e) => {
          if (e.type === 'delta' && e.content !== undefined) {
            assistantMsg.content += e.content
            assistantMsg.pending = false
            this.updateLastAssistant()
          } else if (e.type === 'done') {
            assistantMsg.content = e.content || assistantMsg.content
            assistantMsg.citations = e.citations || []
            assistantMsg.rawCitations = assistantMsg.citations
            assistantMsg.pending = false
            this.updateLastAssistant()
            // 首轮命名同步（后端一致：前 10 字 + 省略号）
            if (!this.activeConv!.title || this.activeConv!.title === '新会话') {
              this.activeConv!.title = text.length > 10 ? text.slice(0, 10) + '...' : text
            }
          } else if (e.type === 'error') {
            assistantMsg.error = true
            const sep = assistantMsg.content ? '\n' : ''
            assistantMsg.content += sep + `[错误] ${e.message}`
            assistantMsg.pending = false
            this.updateLastAssistant()
          }
        },
        this.abortCtrl.signal,
      )
    } catch (e) {
      if ((e as Error).name !== 'AbortError') {
        assistantMsg.error = true
        const sep = assistantMsg.content ? '\n' : ''
        assistantMsg.content += sep + `[错误] ${(e as Error).message}`
        assistantMsg.pending = false
        this.updateLastAssistant()
      }
    } finally {
      this.streaming = false
      this.abortCtrl = null
      this.renderInputRow()
      this.scrollBottom()
    }
  }

  private stopStream() {
    this.abortCtrl?.abort()
  }

  // ── 登录/登出 ───────────────────────────
  private renderLoginForm() {
    this.bodyEl.innerHTML = `
      <div class="pin-login">
        <input type="text" placeholder="用户名" class="u">
        <input type="password" placeholder="密码" class="p">
        <div class="err"></div>
        <button class="submit" data-action="login-submit">登 录</button>
        <div class="hint">登录后可跨设备同步你的会话记录</div>
      </div>
    `
    this.shadow.querySelector('[data-action="login-submit"]')!.addEventListener('click', async () => {
      const u = (this.bodyEl.querySelector('.u') as HTMLInputElement).value.trim()
      const p = (this.bodyEl.querySelector('.p') as HTMLInputElement).value
      const errEl = this.bodyEl.querySelector('.err') as HTMLElement
      try {
        const res = await this.api.login(u, p)
        setToken(res.access_token)
        setUser(res.user)
        this.loginOpen = false
        this.refreshLoginBtn()
        // 登录后切换到自己的会话维度
        const convs = await this.api.listConversations(this.agentId)
        this.convs = convs
        if (convs.length > 0) {
          await this.openConversation(convs[0].id)
        } else {
          await this.newConversation()
        }
      } catch (e) {
        errEl.textContent = (e as Error).message
      }
    })
  }

  private logout() {
    setToken(null)
    setUser(null)
    this.refreshLoginBtn()
    // 登出后回到匿名维度
    this.initConversation()
  }

  // ── 渲染 ────────────────────────────────
  private renderBody() {
    if (this.destroyed) return
    // 登录表单显示时隐藏输入区（表单替换消息区，输入框/按钮不应残留）
    const inputRow = this.shadow.querySelector('.pin-input-row') as HTMLElement | null
    if (inputRow) inputRow.style.display = this.loginOpen ? 'none' : ''
    if (this.loginOpen) {
      this.renderLoginForm()
      return
    }
    if (this.msgs.length === 0) {
      this.bodyEl.innerHTML = `<div class="pin-empty">新会话，开始提问吧</div>`
      return
    }
    this.bodyEl.innerHTML = this.msgs.map((m, i) => this.renderMsg(m, i)).join('')
    this.renderInputRow()
  }

  private renderMsg(m: Msg, idx: number): string {
    if (m.pending) {
      return `<div class="pin-msg assistant"><div class="pin-bubble-msg"><span class="cursor">▍</span></div></div>`
    }
    const parts = splitRefs(m.content)
      .map(p => p.type === 'ref'
        ? `<span class="pin-ref" data-action="cite" data-msg="${idx}" data-idx="${p.index}">[${p.index}]</span>`
        : escapeHtml(p.value))
      .join('')
    const cites = m.citations && m.citations.length > 0
      ? `<div class="pin-cites">${m.citations.map((c, i) => `
          <div class="pin-cite-item" data-cite="${idx}-${i + 1}">
            <div class="doc">[${i + 1}] 《${escapeHtml(c.document_name)}》</div>
            <div class="txt">${escapeHtml(c.content)}</div>
          </div>`).join('')}</div>`
      : ''
    const errCls = m.error ? ' err' : ''
    return `<div class="pin-msg ${m.role}"><div class="pin-bubble-msg${errCls}">${parts}</div>${cites}</div>`
  }

  /** 流式打字机：更新最后一条助手消息（气泡 + 引用面板一起整条替换） */
  private updateLastAssistant() {
    if (this.destroyed) return
    const last = this.msgs[this.msgs.length - 1]
    if (!last || last.role !== 'assistant') return
    const items = this.bodyEl.querySelectorAll('.pin-msg')
    const lastEl = items[items.length - 1]
    if (lastEl) {
      // outerHTML 整条替换：renderMsg 同时生成气泡和 .pin-cites 引用面板，
      // 确保流式完成（done）后引用列表随 [N] 标注一起出现（此前只更新气泡，引用面板永不渲染）
      lastEl.outerHTML = this.renderMsg(last, this.msgs.length - 1)
    }
    this.scrollBottom()
  }

  private renderInputRow() {
    if (this.destroyed) return
    const row = this.shadow.querySelector('.pin-input-row')!
    if (this.streaming) {
      row.innerHTML = '<button class="pin-stop" data-action="stop">停止生成</button>'
      return
    }
    row.innerHTML = `
      <textarea placeholder="输入消息，Enter 发送" rows="1"></textarea>
      <button class="pin-send" data-action="send">发送</button>
    `
    this.inputEl = row.querySelector('textarea')!
    this.sendBtn = row.querySelector('.pin-send')!
    this.inputEl.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault()
        this.send()
      }
    })
  }

  private renderDrawerBody() {
    if (this.convs.length === 0) {
      this.drawerBodyEl.innerHTML = '<div class="pin-empty">暂无会话</div>'
      return
    }
    this.drawerBodyEl.innerHTML = this.convs.map(c => `
      <div class="pin-conv-item" data-action="open-conv" data-conv-id="${c.id}">
        <div class="t">${escapeHtml(c.title || '新会话')}</div>
        <div class="meta">${c.message_count} 条消息</div>
      </div>`).join('')
  }

  private toggleCite(msgIdx: string, citeIdx: string) {
    const el = this.shadow.querySelector(`[data-cite="${msgIdx}-${citeIdx}"]`)
    el?.classList.toggle('open')
  }

  /**
   * 轻提示：面板底部一次性 toast，3 秒自动消失（重复调用重置计时）
   *
   * 用于导航操作（新建/切换会话）失败场景——只提示、不污染消息列表。
   */
  private showToast(msg: string) {
    if (this.destroyed) return
    if (!this.toastEl) {
      this.toastEl = document.createElement('div')
      this.toastEl.className = 'pin-toast'
      this.panel.appendChild(this.toastEl)
    }
    this.toastEl.textContent = msg
    this.toastEl.classList.add('show')
    if (this.toastTimer) window.clearTimeout(this.toastTimer)
    this.toastTimer = window.setTimeout(() => {
      this.toastEl?.classList.remove('show')
    }, 3000)
  }

  private scrollBottom() {
    if (this.destroyed) return
    this.bodyEl.scrollTop = this.bodyEl.scrollHeight
  }

  /**
   * 销毁实例：中断流式 + 解绑 document 监听 + 移除 shadow host
   *
   * 用于：同 agentId 重复 init 时替换旧实例；宿主主动清理（PinWidget.destroy）。
   */
  destroy() {
    this.destroyed = true
    if (this.toastTimer) {
      window.clearTimeout(this.toastTimer)
      this.toastTimer = null
    }
    this.abortCtrl?.abort()
    if (this.outsideClickHandler) {
      document.removeEventListener('click', this.outsideClickHandler)
      this.outsideClickHandler = null
    }
    this.hostEl.remove()
  }
}

/** HTML 转义（防 XSS） */
function escapeHtml(s: string): string {
  return s
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;')
}
