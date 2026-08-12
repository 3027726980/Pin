<template>
  <div class="chat-page">
    <!-- 页头 -->
    <n-card class="chat-header" :bordered="true">
      <div class="chat-header-inner">
        <n-button quaternary size="small" @click="router.back()">
          <template #icon><n-icon><ArrowBackOutline /></n-icon></template>
          返回
        </n-button>
        <div class="chat-title">
          <n-tag size="small" :type="agent?.type === 'simple_rag' ? 'primary' : 'warning'" :bordered="false">
            {{ agent?.type === 'simple_rag' ? '简单 RAG' : '综合 Agent' }}
          </n-tag>
          <span class="chat-name">{{ agent?.name || '加载中...' }}</span>
          <span v-if="activeConv" class="chat-conv-title" :title="activeConv.title || ''">
            · {{ activeConv.title || '新会话' }}
          </span>
        </div>
        <div class="chat-header-right">
          <span class="stream-option">流式输出</span>
          <n-switch v-model:value="streamMode" size="small" />
          <n-button size="small" :disabled="streaming" @click="newConversation">
            <template #icon><n-icon><AddOutline /></n-icon></template>
            新会话
          </n-button>
          <n-button size="small" :disabled="streaming" @click="drawerShow = true">
            <template #icon><n-icon><ChatbubblesOutline /></n-icon></template>
            会话
          </n-button>
        </div>
      </div>
    </n-card>

    <!-- 消息区 -->
    <n-card class="chat-body" :bordered="true">
      <div v-if="messages.length === 0" class="chat-empty">
        <n-empty :description="agent?.welcome_message || '开始与 Agent 对话吧'" />
      </div>

      <div v-for="(msg, idx) in messages" :key="idx" class="msg-row" :class="msg.role">
        <div class="msg-bubble" :class="msg.role">
          <!-- 当前等待/生成中的助手消息：气泡内直接显示加载状态 -->
          <template v-if="isPendingMsg(msg)">
            <span class="stage-text">{{ loadingText }}</span>
          </template>
          <!-- 正常内容：分段渲染（文本 + [N] 可点击引用标注） -->
          <template v-else>
          <div class="msg-content">
            <template v-for="(part, i) in splitRefs(msg.content)" :key="i">
              <span v-if="part.type === 'text'">{{ part.value }}</span>
              <span
                v-else
                class="citation-ref"
                :class="{ disabled: !msg.rawCitations || part.index! < 1 || part.index! > msg.rawCitations.length }"
                @click="locateCitation(msg, part.index!)"
              >
                [{{ part.index }}]
              </span>
            </template>
          </div>
          <!-- 引用来源（仅展示回答中实际引用的条目） -->
          <div v-if="msg.role === 'assistant' && msg.citations && msg.citations.length" class="msg-citations">
            <n-collapse
              :expanded-names="msg.refPanelExpanded ? ['cits'] : []"
              @update:expanded-names="(names: string[]) => (msg.refPanelExpanded = names.includes('cits'))"
            >
              <n-collapse-item :title="`引用来源（${msg.citations.length} 条）`" name="cits">
                <div
                  v-for="(c, i) in msg.citations"
                  :key="i"
                  class="citation-item"
                  :data-citation-index="`${msg.uid}-${msg.rawCitations ? msg.rawCitations.indexOf(c) : i}`"
                >
                  <div class="citation-head">
                    <span class="citation-doc">[{{ msg.rawCitations ? msg.rawCitations.indexOf(c) + 1 : i + 1 }}]《{{ c.document_name }}》</span>
                    <n-tag size="tiny" type="info" :bordered="false">相似度 {{ c.score.toFixed(2) }}</n-tag>
                  </div>
                  <div class="citation-content" :class="{ expanded: isCitationExpanded(msg, msg.rawCitations ? msg.rawCitations.indexOf(c) : i) }">{{ c.content }}</div>
                  <div
                    v-if="c.content && c.content.length > 100"
                    class="citation-toggle"
                    @click="toggleCitation(msg, msg.rawCitations ? msg.rawCitations.indexOf(c) : i)"
                  >
                    {{ isCitationExpanded(msg, msg.rawCitations ? msg.rawCitations.indexOf(c) : i) ? '收起 ▲' : '展开 ▼' }}
                  </div>
                </div>
              </n-collapse-item>
            </n-collapse>
          </div>
          </template>
        </div>
      </div>
    </n-card>

    <!-- 输入区 -->
    <n-card class="chat-input-card" :bordered="true">
      <div class="chat-input-row">
        <n-input
          v-model:value="inputText"
          type="textarea"
          :autosize="{ minRows: 1, maxRows: 4 }"
          placeholder="输入消息，Enter 发送，Shift+Enter 换行"
          :disabled="streaming"
          @keydown="onInputKeydown"
        />
        <div class="chat-input-actions">
          <n-button v-if="streaming" type="error" @click="stopStream">
            <template #icon><n-icon><StopOutline /></n-icon></template>
            停止
          </n-button>
          <n-button v-else type="primary" :loading="sending" :disabled="!inputText.trim()" @click="send">
            <template #icon><n-icon><SendOutline /></n-icon></template>
            发送
          </n-button>
        </div>
      </div>
    </n-card>

    <!-- 会话抽屉 -->
    <n-drawer v-model:show="drawerShow" :width="340" placement="right">
      <n-drawer-content title="历史会话" closable>
        <div class="conv-toolbar">
          <n-button size="small" type="primary" :disabled="streaming" @click="newConversation">
            <template #icon><n-icon><AddOutline /></n-icon></template>
            新会话
          </n-button>
        </div>
        <n-scrollbar style="height: calc(100% - 44px)" @scroll="onConvScroll">
          <div v-if="conversations.length === 0" class="conv-empty">
            <n-empty description="暂无会话" size="small" />
          </div>
          <div
            v-for="conv in conversations"
            :key="conv.id"
            class="conv-item"
            :class="{ active: activeConv && activeConv.id === conv.id }"
            :disabled="streaming"
            @click="openConversation(conv)"
          >
            <div class="conv-item-main">
              <div class="conv-item-title">{{ conv.title || '新会话' }}</div>
              <div class="conv-item-meta">
                {{ conv.message_count }} 条消息 · {{ formatTime(conv.updated_at) }}
              </div>
            </div>
            <n-popconfirm
              :disabled="streaming"
              @positive-click="deleteConversation(conv)"
            >
              <template #trigger>
                <n-button
                  quaternary
                  circle
                  size="tiny"
                  class="conv-item-del"
                  :disabled="streaming"
                  @click.stop
                >
                  <template #icon><n-icon><TrashOutline /></n-icon></template>
                </n-button>
              </template>
              删除该会话？此操作不可恢复。
            </n-popconfirm>
          </div>
          <div v-if="convLoading" class="conv-loading"><n-spin size="small" /></div>
          <div v-else-if="conversations.length < convTotal" class="conv-more" @click="loadMoreConversations">加载更多</div>
        </n-scrollbar>
      </n-drawer-content>
    </n-drawer>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  AddOutline,
  ArrowBackOutline,
  ChatbubblesOutline,
  SendOutline,
  StopOutline,
  TrashOutline,
} from '@vicons/ionicons5'
import {
  getAgent,
  chatAgent,
  chatAgentStream,
  type AgentDetail,
  type ChatMessage,
  type ChatCitation,
} from '@/api/agent'
import {
  createConversation,
  listConversations,
  listConversationMessages,
  deleteConversation as apiDeleteConversation,
  type ConversationItem,
} from '@/api/conversation'

interface DisplayMessage extends ChatMessage {
  /** 消息唯一标识（引用定位锚点用） */
  uid: number
  citations?: ChatCitation[]
  /** 完整引用列表（过滤前，保留原始编号用） */
  rawCitations?: ChatCitation[]
  error?: boolean
  /** 每条引用的展开状态（原始索引 → 是否展开） */
  expandedCitations?: Record<number, boolean>
  /** 引用面板是否展开 */
  refPanelExpanded?: boolean
}

const route = useRoute()
const router = useRouter()
const message = useMessage()

const agentId = route.params.id as string
const agent = ref<AgentDetail | null>(null)

const messages = ref<DisplayMessage[]>([])
let msgUid = 0
const inputText = ref('')
const sending = ref(false)
const streaming = ref(false)
// 流式输出开关（默认开启；关闭时走非流式一次性返回）
const streamMode = ref(true)
// 当前阶段：retrieving=检索中（加载圈），generating=生成中（打字机）
const currentStage = ref<'idle' | 'retrieving' | 'generating'>('idle')
let abortCtrl: AbortController | null = null

// ── 会话状态 ────────────────────────────
const drawerShow = ref(false)
const conversations = ref<ConversationItem[]>([])
const activeConv = ref<ConversationItem | null>(null)
const convPage = ref(1)
const convTotal = ref(0)
const convLoading = ref(false)
const msgLoading = ref(false)

// ── 页面初始化 ──────────────────────────
onMounted(async () => {
  try {
    agent.value = await getAgent(agentId)
  } catch (e) {
    message.error((e as Error).message || 'Agent 不存在')
    router.replace('/agent')
    return
  }
  await loadConversations(1)
  if (conversations.value.length > 0) {
    // 有历史会话 → 打开最近一个
    await openConversation(conversations.value[0])
  } else {
    // 无会话 → 自动创建 + 欢迎语
    await newConversation()
  }
})

// ── 会话列表 ────────────────────────────
async function loadConversations(page: number) {
  convLoading.value = true
  try {
    const res = await listConversations(agentId, page, 20)
    if (page === 1) {
      conversations.value = res.items
    } else {
      conversations.value = [...conversations.value, ...res.items]
    }
    convTotal.value = res.total
    convPage.value = page
  } catch (e) {
    message.error((e as Error).message || '会话列表加载失败')
  } finally {
    convLoading.value = false
  }
}

function loadMoreConversations() {
  if (!convLoading.value && conversations.value.length < convTotal.value) {
    loadConversations(convPage.value + 1)
  }
}

function onConvScroll(e: Event) {
  const el = e.target as HTMLElement
  if (el.scrollTop + el.clientHeight >= el.scrollHeight - 40) {
    loadMoreConversations()
  }
}

// ── 会话切换 ────────────────────────────
async function openConversation(conv: ConversationItem) {
  if (streaming.value || msgLoading.value) return
  activeConv.value = conv
  msgLoading.value = true
  try {
    const res = await listConversationMessages(conv.id, 1, 100)
    messages.value = res.items.map(m => ({
      role: m.role,
      content: m.content,
      uid: ++msgUid,
      citations: m.citations || [],
      rawCitations: m.citations || [],
    }))
  } catch (e) {
    message.error((e as Error).message || '历史消息加载失败')
  } finally {
    msgLoading.value = false
    scrollBottom()
  }
}

// ── 新会话（自动创建 + 欢迎语）──────────
async function newConversation() {
  if (streaming.value) return
  try {
    const conv = await createConversation(agentId)
    activeConv.value = conv
    conversations.value.unshift(conv)
    convTotal.value += 1
    // 欢迎语不再作为消息气泡：由空状态占位文案显示（见 chat-empty）
    messages.value = []
    drawerShow.value = false
  } catch (e) {
    message.error((e as Error).message || '创建会话失败')
  }
}

// ── 删除会话 ────────────────────────────
async function deleteConversation(conv: ConversationItem) {
  try {
    await apiDeleteConversation(conv.id)
    conversations.value = conversations.value.filter(c => c.id !== conv.id)
    convTotal.value = Math.max(0, convTotal.value - 1)
    if (activeConv.value && activeConv.value.id === conv.id) {
      // 删除当前会话 → 自动新建
      await newConversation()
    }
    message.success('会话已删除')
  } catch (e) {
    message.error((e as Error).message || '删除失败')
  }
}

// ── 发送 ────────────────────────────────
async function send() {
  const text = inputText.value.trim()
  if (!text || streaming.value) return
  // 前置保证：先有会话再对话（新会话由 newConversation 创建）
  if (!activeConv.value) {
    await newConversation()
    if (!activeConv.value) return
  }

  messages.value.push({ role: 'user', content: text, uid: ++msgUid })
  inputText.value = ''
  scrollBottom()

  // 首轮对话自动命名：与后端 _persist_messages 逻辑一致（标题仍为默认值时，用第一条消息前 10 字，超过则加省略号）
  // activeConv 与会话列表同一对象引用，改这里列表同步生效，无需刷新
  if (!activeConv.value.title || activeConv.value.title === '新会话') {
    activeConv.value.title = text.length > 10 ? text.slice(0, 10) + '...' : text
  }

  // 占位助手消息（reactive：push 的是代理本身，流式增量修改实时触发视图更新）
  const assistantMsg = reactive<DisplayMessage>({ role: 'assistant', content: '', citations: [], uid: ++msgUid })
  messages.value.push(assistantMsg)
  scrollBottom()

  streaming.value = true
  sending.value = true
  currentStage.value = 'retrieving'
  abortCtrl = new AbortController()
  startLoadingText()
  const conversationId = activeConv.value.id

  // 非流式：一次性返回 answer + citations
  if (!streamMode.value) {
    try {
      const res = await chatAgent(agentId, { message: text, conversation_id: conversationId })
      assistantMsg.content = res.answer
      assistantMsg.citations = res.citations
    } catch (e) {
      assistantMsg.error = true
      assistantMsg.content = `[错误] ${(e as Error).message}`
    } finally {
      streaming.value = false
      sending.value = false
      currentStage.value = 'idle'
      abortCtrl = null
      stopLoadingText()
    }
    return
  }

  try {
    await chatAgentStream(
      agentId,
      { message: text, conversation_id: conversationId, stream: true },
      (event) => {
        if (event.type === 'delta') {
          // 首个 delta 到达 → 检索完成，进入生成阶段（打字机）
          if (currentStage.value === 'retrieving') {
            currentStage.value = 'generating'
          }
          assistantMsg.content += event.content
          scrollBottom()
        } else if (event.type === 'citations') {
          // 仅保留回答中实际引用（[N]）的条目，未引用的不展示
          assistantMsg.rawCitations = event.citations
          const used = extractRefIndexes(assistantMsg.content)
          assistantMsg.citations = event.citations.filter((_, i) => used.has(i + 1))
        } else if (event.type === 'error') {
          assistantMsg.error = true
          // 已有内容时换行分隔错误信息，空内容时不加换行
          const sep = assistantMsg.content ? '\n' : ''
          assistantMsg.content = assistantMsg.content + sep + `[错误] ${event.message}`
        }
      },
      abortCtrl.signal,
    )
  } catch (e) {
    if ((e as Error).name === 'AbortError') {
      // 用户主动停止：保留已输出内容
    } else {
      assistantMsg.error = true
      // 已有内容时换行分隔错误信息，空内容时不加换行
      const sep = assistantMsg.content ? '\n' : ''
      assistantMsg.content = assistantMsg.content + sep + `[错误] ${(e as Error).message}`
    }
  } finally {
    streaming.value = false
    sending.value = false
    currentStage.value = 'idle'
    abortCtrl = null
    stopLoadingText()
  }
}

function stopStream() {
  abortCtrl?.abort()
}

function onInputKeydown(e: KeyboardEvent) {
  // Enter 发送，Shift+Enter 换行
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault()
    send()
  }
}

// ── AI 加载状态文字（多文案轮换）────────────────────
const loadingTexts = ['正在思考…', '正在查阅资料…', '正在组织语言…', '正在生成回答…']
const loadingText = ref(loadingTexts[0])
let loadingTimer: number | null = null

/** 开始轮换加载文案（每 2 秒切换一条） */
function startLoadingText() {
  loadingText.value = loadingTexts[0]
  if (loadingTimer) window.clearInterval(loadingTimer)
  loadingTimer = window.setInterval(() => {
    const idx = loadingTexts.indexOf(loadingText.value)
    loadingText.value = loadingTexts[(idx + 1) % loadingTexts.length]
  }, 2000)
}

/** 停止轮换（发送完成/出错/停止时调用） */
function stopLoadingText() {
  if (loadingTimer) {
    window.clearInterval(loadingTimer)
    loadingTimer = null
  }
}

/** 是否为当前正在等待/生成中的消息（最后一条 + 请求中） */
function isPendingMsg(msg: DisplayMessage): boolean {
  const last = messages.value[messages.value.length - 1]
  return (streaming.value || sending.value) && last === msg
}

// ── 消息区滚动 ────────────────────────
/**
 * 消息区滚动到底部（发送新消息时自动滚动；流式输出时跟随生成内容）
 * 注意：Vue 异步渲染，需 nextTick 后再操作 DOM
 */
function scrollBottom() {
  nextTick(() => {
    const el = document.querySelector('.chat-body')
    if (el) el.scrollTop = el.scrollHeight
  })
}

// ── 工具函数 ────────────────────────────

function formatTime(iso: string): string {
  const d = new Date(iso)
  const now = new Date()
  const sameDay = d.toDateString() === now.toDateString()
  const pad = (n: number) => String(n).padStart(2, '0')
  const hm = `${pad(d.getHours())}:${pad(d.getMinutes())}`
  if (sameDay) return hm
  return `${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${hm}`
}

// ── 引用标注解析与定位 ───────────────────

/** 拆分消息内容：文本段 + [N] 引用标注段（避免 v-html，防 XSS） */
function splitRefs(content: string): Array<{ type: 'text' | 'ref'; value: string; index?: number }> {
  const parts = content.split(/(\[\d+\])/g)
  return parts
    .filter(p => p)
    .map(p => {
      const m = p.match(/^\[(\d+)\]$/)
      if (m) return { type: 'ref' as const, value: p, index: parseInt(m[1], 10) }
      return { type: 'text' as const, value: p }
    })
}

/** 提取内容中所有 [N] 引用序号 */
function extractRefIndexes(content: string): Set<number> {
  const set = new Set<number>()
  const re = /\[(\d+)\]/g
  let m: RegExpExecArray | null
  while ((m = re.exec(content)) !== null) {
    set.add(parseInt(m[1], 10))
  }
  return set
}

/** 点击 [N]：展开引用面板 + 展开对应条目 + 滚动定位 */
function locateCitation(msg: DisplayMessage, n: number) {
  if (!msg.rawCitations || n < 1 || n > msg.rawCitations.length) return
  msg.refPanelExpanded = true
  if (!msg.expandedCitations) {
    msg.expandedCitations = {}
  }
  msg.expandedCitations[n - 1] = true
  // 等折叠面板展开动画完成后再滚动定位（n-collapse 动画约 300ms）
  nextTick(() => {
    window.setTimeout(() => {
      const el = document.querySelector(`[data-citation-index="${msg.uid}-${n - 1}"]`)
      el?.scrollIntoView({ behavior: 'smooth', block: 'center' })
    }, 300)
  })
}

// ── 引用展开/收起 ───────────────────────
function isCitationExpanded(msg: DisplayMessage, idx: number): boolean {
  return !!msg.expandedCitations?.[idx]
}

function toggleCitation(msg: DisplayMessage, idx: number) {
  if (!msg.expandedCitations) {
    msg.expandedCitations = {}
  }
  msg.expandedCitations[idx] = !msg.expandedCitations[idx]
}
</script>

<style scoped>
.chat-page {
  display: flex;
  flex-direction: column;
  height: calc(100vh - 56px - 48px);
  max-width: 860px;
  margin: 0 auto;
  gap: 12px;
}

.chat-header-inner {
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.chat-header-right {
  display: flex;
  align-items: center;
  gap: 8px;
}
.stream-option {
  font-size: 13px;
  color: var(--n-text-color-3);
}
.chat-title {
  display: flex;
  align-items: center;
  gap: 8px;
}
.chat-name {
  font-size: 16px;
  font-weight: 600;
}
.chat-conv-title {
  font-size: 13px;
  color: var(--n-text-color-3);
  max-width: 200px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.chat-body {
  flex: 1;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
}
.chat-empty {
  display: flex;
  align-items: center;
  justify-content: center;
  height: 100%;
}

.msg-row {
  display: flex;
  margin-bottom: 12px;
}
.msg-row.user {
  justify-content: flex-end;
}
.msg-row.assistant {
  justify-content: flex-start;
}

.msg-bubble {
  max-width: 78%;
  padding: 10px 14px;
  border-radius: 8px;
  white-space: pre-wrap;
  word-break: break-word;
  font-size: 14px;
  line-height: 1.6;
}
.msg-bubble.user {
  background: #2080f0;
  color: #fff;
  border-top-right-radius: 2px;
}
.msg-bubble.assistant {
  background: var(--n-color-embedded);
  border-top-left-radius: 2px;
}

.msg-citations {
  margin-top: 8px;
  font-size: 13px;
}
.citation-ref {
  display: inline-block;
  padding: 0 3px;
  margin: 0 1px;
  font-size: 12px;
  font-weight: 600;
  color: #2080f0;
  background: rgba(32, 128, 240, 0.12);
  border-radius: 3px;
  cursor: pointer;
  user-select: none;
}
.citation-ref:hover {
  background: rgba(32, 128, 240, 0.25);
}
.citation-ref.disabled {
  color: var(--n-text-color-3);
  background: transparent;
  cursor: default;
}
.msg-bubble.user .citation-ref {
  color: #fff;
  background: rgba(255, 255, 255, 0.2);
}
.msg-bubble.user .citation-ref:hover {
  background: rgba(255, 255, 255, 0.35);
}
.citation-item {
  padding: 6px 0;
  border-bottom: 1px dashed var(--n-border-color);
}
.citation-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 4px;
}
.citation-doc {
  font-weight: 500;
}
.citation-content {
  font-size: 13px;
  color: var(--n-text-color-3);
  overflow: hidden;
  text-overflow: ellipsis;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
}
.citation-content.expanded {
  display: block;
  -webkit-line-clamp: unset;
  overflow: visible;
  white-space: pre-wrap;
}
.citation-toggle {
  margin-top: 4px;
  font-size: 12px;
  color: #2080f0;
  cursor: pointer;
  user-select: none;
}
.citation-toggle:hover {
  opacity: 0.8;
}

.streaming-cursor {
  animation: blink 1s infinite;
}
@keyframes blink {
  0%, 50% { opacity: 1; }
  51%, 100% { opacity: 0; }
}
.stage-text {
  margin-left: 8px;
  font-size: 13px;
  /* 加载状态文字：灰色（与嵌入端 pin-loading 一致） */
  color: #999;
}

.chat-input-row {
  display: flex;
  gap: 8px;
  align-items: flex-end;
}
.chat-input-row .n-input {
  flex: 1;
}
.chat-input-actions {
  display: flex;
}

/* ── 会话抽屉 ─────────────────────── */
.conv-toolbar {
  padding-bottom: 10px;
  border-bottom: 1px solid var(--n-border-color);
  margin-bottom: 8px;
}
.conv-empty {
  padding: 40px 0;
}
.conv-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  padding: 10px 12px;
  border-radius: 6px;
  cursor: pointer;
  transition: background 0.2s;
}
.conv-item:hover {
  background: var(--n-color-hover);
}
.conv-item.active {
  background: rgba(32, 128, 240, 0.1);
}
.conv-item[disabled='true'] {
  cursor: not-allowed;
  opacity: 0.6;
}
.conv-item-main {
  flex: 1;
  min-width: 0;
}
.conv-item-title {
  font-size: 14px;
  font-weight: 500;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.conv-item-meta {
  font-size: 12px;
  color: var(--n-text-color-3);
  margin-top: 2px;
}
.conv-item-del {
  visibility: hidden;
}
.conv-item:hover .conv-item-del {
  visibility: visible;
}
.conv-loading,
.conv-more {
  text-align: center;
  padding: 10px 0;
  font-size: 13px;
  color: var(--n-text-color-3);
}
.conv-more {
  cursor: pointer;
}
.conv-more:hover {
  color: #2080f0;
}
</style>
