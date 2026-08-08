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
          <div class="msg-content">{{ msg.content }}</div>
          <!-- 引用来源（助手消息附带） -->
          <div v-if="msg.role === 'assistant' && msg.citations && msg.citations.length" class="msg-citations">
            <n-collapse>
              <n-collapse-item :title="`引用来源（${msg.citations.length} 条）`" name="cits">
                <div v-for="(c, i) in msg.citations" :key="i" class="citation-item">
                  <div class="citation-head">
                    <span class="citation-doc">《{{ c.document_name }}》</span>
                    <n-tag size="tiny" type="info" :bordered="false">相似度 {{ c.score.toFixed(2) }}</n-tag>
                  </div>
                  <div class="citation-content" :class="{ expanded: isCitationExpanded(msg, i) }">{{ c.content }}</div>
                  <div
                    v-if="c.content && c.content.length > 100"
                    class="citation-toggle"
                    @click="toggleCitation(msg, i)"
                  >
                    {{ isCitationExpanded(msg, i) ? '收起 ▲' : '展开 ▼' }}
                  </div>
                </div>
              </n-collapse-item>
            </n-collapse>
          </div>
        </div>
      </div>

      <div v-if="streaming" class="msg-row assistant">
        <div class="msg-bubble assistant">
          <span class="streaming-cursor">▍</span>
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
import { ref, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ArrowBackOutline, SendOutline, StopOutline } from '@vicons/ionicons5'
import { getAgent, chatAgent, chatAgentStream, type AgentDetail, type ChatMessage, type ChatCitation } from '@/api/agent'

interface DisplayMessage extends ChatMessage {
  citations?: ChatCitation[]
  error?: boolean
  /** 每条引用的展开状态（索引 → 是否展开） */
  expandedCitations?: Record<number, boolean>
}

const route = useRoute()
const router = useRouter()
const message = useMessage()

const agentId = route.params.id as string
const agent = ref<AgentDetail | null>(null)

const messages = ref<DisplayMessage[]>([])
const inputText = ref('')
const sending = ref(false)
const streaming = ref(false)
// 流式输出开关（默认开启；关闭时走非流式一次性返回）
const streamMode = ref(true)
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

  messages.value.push({ role: 'user', content: text })
  inputText.value = ''

  // 组装 history（最近 10 条，不含刚加入的这条）
  const history: ChatMessage[] = messages.value.slice(-11, -1).map(m => ({ role: m.role, content: m.content }))

  // 占位助手消息（流式追加内容）
  const assistantMsg: DisplayMessage = { role: 'assistant', content: '', citations: [] }
  messages.value.push(assistantMsg)

  streaming.value = true
  sending.value = true
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
          assistantMsg.content += event.content
        } else if (event.type === 'citations') {
          assistantMsg.citations = event.citations
        } else if (event.type === 'error') {
          assistantMsg.error = true
          assistantMsg.content = (assistantMsg.content || '') + `\n[错误] ${event.message}`
        }
      },
      abortCtrl.signal,
    )
  } catch (e) {
    if ((e as Error).name === 'AbortError') {
      // 用户主动停止：保留已输出内容
    } else {
      assistantMsg.error = true
      assistantMsg.content = (assistantMsg.content || '') + `\n[错误] ${(e as Error).message}`
    }
  } finally {
    streaming.value = false
    sending.value = false
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
