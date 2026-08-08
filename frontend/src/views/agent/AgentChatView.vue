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
        </div>
        <div class="chat-header-right">
          <span class="stream-option">流式输出</span>
          <n-switch v-model:value="streamMode" size="small" />
          <n-button size="small" quaternary @click="clearChat">清空</n-button>
        </div>
      </div>
    </n-card>

    <!-- 消息区 -->
    <n-card class="chat-body" :bordered="true">
      <div v-if="messages.length === 0" class="chat-empty">
        <n-empty description="开始与 Agent 对话吧" />
      </div>

      <div v-for="(msg, idx) in messages" :key="idx" class="msg-row" :class="msg.role">
        <div class="msg-bubble" :class="msg.role">
          <!-- 内容分段渲染：文本 + [N] 可点击引用标注 -->
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
        </div>
      </div>

      <div v-if="streaming" class="msg-row assistant">
        <div class="msg-bubble assistant">
          <!-- 检索/处理阶段：加载圈 + 状态文字 -->
          <template v-if="currentStage === 'retrieving'">
            <n-spin size="small" />
            <span class="stage-text">正在检索知识库...</span>
          </template>
          <!-- 生成阶段：流式光标 -->
          <span v-else class="streaming-cursor">▍</span>
        </div>
      </div>

      <!-- 非流式：请求中加载圈 -->
      <div v-else-if="sending" class="msg-row assistant">
        <div class="msg-bubble assistant">
          <n-spin size="small" />
          <span class="stage-text">正在生成回答...</span>
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
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ArrowBackOutline, SendOutline, StopOutline } from '@vicons/ionicons5'
import { getAgent, chatAgent, chatAgentStream, type AgentDetail, type ChatMessage, type ChatCitation } from '@/api/agent'

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
// 无后端事件：发送后即 retrieving，收到首个 delta 自动切换 generating
const currentStage = ref<'idle' | 'retrieving' | 'generating'>('idle')
let abortCtrl: AbortController | null = null

// ── 加载 Agent 信息 ──────────────────────
onMounted(async () => {
  try {
    agent.value = await getAgent(agentId)
  } catch (e) {
    message.error((e as Error).message || 'Agent 不存在')
    router.replace('/agent')
  }
})

// ── 发送 ────────────────────────────────
async function send() {
  const text = inputText.value.trim()
  if (!text || streaming.value) return

  messages.value.push({ role: 'user', content: text, uid: ++msgUid })
  inputText.value = ''

  // 组装 history（最近 10 条，不含刚加入的这条）
  const history: ChatMessage[] = messages.value.slice(-11, -1).map(m => ({ role: m.role, content: m.content }))

  // 占位助手消息（reactive：push 的是代理本身，流式增量修改实时触发视图更新）
  const assistantMsg = reactive<DisplayMessage>({ role: 'assistant', content: '', citations: [], uid: ++msgUid })
  messages.value.push(assistantMsg)

  streaming.value = true
  sending.value = true
  currentStage.value = 'retrieving'
  abortCtrl = new AbortController()

  // 非流式：一次性返回 answer + citations
  if (!streamMode.value) {
    try {
      const res = await chatAgent(agentId, { message: text, history })
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
    }
    return
  }

  try {
    await chatAgentStream(
      agentId,
      { message: text, history, stream: true },
      (event) => {
        if (event.type === 'delta') {
          // 首个 delta 到达 → 检索完成，进入生成阶段（打字机）
          if (currentStage.value === 'retrieving') {
            currentStage.value = 'generating'
          }
          assistantMsg.content += event.content
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

function clearChat() {
  messages.value = []
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
  color: var(--n-text-color-3);
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
</style>
