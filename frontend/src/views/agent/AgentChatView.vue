<!-- 作者：LHF；时间：2026-10-25；作用：会话手动压缩与模型输入上下文查看。 -->
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
          <n-tag size="small" :type="'primary'" :bordered="false">
            {{ 'Agent' }}
          </n-tag>
          <span class="chat-name">{{ agent?.name || '加载中...' }}</span>
          <span v-if="activeConv" class="chat-conv-title" :title="activeConv.title || ''">
            · {{ activeConv.title || '新会话' }}
          </span>
        </div>
        <div class="chat-header-right">
          <n-button size="small" :loading="compacting" :disabled="streaming || sending || !activeConv" @click="compactContext">
            压缩上下文
          </n-button>
          <span class="stream-option">流式输出</span>
          <n-switch v-model:value="streamMode" size="small" />
          <n-button size="small" :disabled="streaming || compacting" @click="newConversation">
            <template #icon><n-icon><AddOutline /></n-icon></template>
            新会话
          </n-button>
          <n-button size="small" :disabled="streaming || compacting" @click="drawerShow = true">
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
          <n-space v-if="msg.mentions?.length" size="small" style="margin-bottom: 6px"><n-tag v-for="item in msg.mentions" :key="item.kind + item.name" size="small">@{{ item.name }}</n-tag></n-space>
          <n-space v-if="msg.artifacts?.length" size="small" style="margin-bottom: 8px"><n-button v-for="file in msg.artifacts" :key="file.run_id + file.path" size="small" @click="saveArtifact(file)">下载 {{ file.name }}</n-button></n-space>
          <AgentProcessTimeline
            v-if="msg.role === 'assistant' && msg.turnState"
            :state="msg.turnState"
          />
          <!-- 正常内容：分段渲染（文本 + [N] 可点击引用标注） -->
          <template v-if="!isPendingMsg(msg) || msg.content">
          <div v-if="msg.intentLabel" class="intent-tag-row"><n-tag size="tiny" :bordered="false">{{ msg.intentLabel === 'complex' ? '复杂任务' : '常规任务' }}</n-tag></div>
          <!-- Phase 4.10：规划 / 反思过程展示（可折叠） -->
          <div v-if="msg.plan || msg.reflect" class="msg-process">
            <n-collapse>
              <n-collapse-item v-if="msg.plan" title="📋 执行计划" name="plan">
                <pre class="process-content">{{ msg.plan }}</pre>
              </n-collapse-item>
              <n-collapse-item v-if="msg.reflect" title="🔍 反思建议" name="reflect">
                <pre class="process-content">{{ msg.reflect }}</pre>
              </n-collapse-item>
            </n-collapse>
          </div>
          <!-- 助手回答共用安全 Markdown 渲染，用户消息保留原文。 -->
          <div v-if="msg.role === 'assistant'" class="msg-content pin-markdown"
            v-html="renderMarkdown(msg.content, citationIds(msg))"
            @click="onMarkdownCitation(msg, $event)"
            @keydown.enter="onMarkdownCitation(msg, $event)"
            @keydown.space="onMarkdownCitation(msg, $event)"
          />
          <div v-else class="msg-content">{{ msg.content }}</div>
          <!-- 可靠引用：服务端已校验回答中的 [S#] 与检索候选的对应关系。 -->
          <div v-if="msg.role === 'assistant' && msg.citationBindings?.length" class="msg-citations">
            <n-collapse
              :expanded-names="msg.refPanelExpanded ? ['cits'] : []"
              @update:expanded-names="(names: string[]) => (msg.refPanelExpanded = names.includes('cits'))"
            >
              <n-collapse-item :title="`引用来源（${msg.citationBindings.length} 条）`" name="cits">
                <div
                  v-for="binding in msg.citationBindings"
                  :key="binding.source_id"
                  class="citation-item"
                  :data-citation-index="`${msg.uid}-${binding.source_id}`"
                >
                  <div class="citation-head">
                    <span class="citation-doc">[{{ binding.source_id }}]《{{ binding.document_name }}》</span>
                    <n-tag size="tiny" type="info" :bordered="false">相似度 {{ binding.score.toFixed(2) }}</n-tag>
                  </div>
                  <div class="citation-claim">依据：{{ binding.claim }}</div>
                  <div class="citation-content" :class="{ expanded: isCitationExpanded(msg, binding.source_id) }">{{ binding.quote }}</div>
                  <div
                    v-if="binding.quote && binding.quote.length > 100"
                    class="citation-toggle"
                    @click="toggleCitation(msg, binding.source_id)"
                  >
                    {{ isCitationExpanded(msg, binding.source_id) ? '收起 ▲' : '展开 ▼' }}
                  </div>
                </div>
              </n-collapse-item>
            </n-collapse>
          </div>
          <!-- 旧会话兼容：仍按历史 [N] 编号渲染。 -->
          <div v-else-if="msg.role === 'assistant' && msg.citations && msg.citations.length" class="msg-citations">
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
                    <n-tag size="tiny" type="info" :bordered="false">
                      {{ c.original_score != null && Math.abs(c.original_score - c.score) > 0.001
                        ? `向量 ${c.original_score.toFixed(2)} → 精排 ${c.score.toFixed(2)}`
                        : `相似度 ${c.score.toFixed(2)}` }}
                    </n-tag>
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
          <n-button
            v-if="msg.role === 'assistant' && (msg.traceId || msg.turnState?.traceId)"
            text
            size="tiny"
            class="trace-link"
            @click="selectedTraceId = msg.traceId || msg.turnState!.traceId!"
          >
            查看完整链路日志
          </n-button>
        </div>
      </div>
    </n-card>

    <!-- 输入区 -->
    <n-card class="chat-input-card" :bordered="true">
      <n-space v-if="selectedMentions.length" size="small" style="margin-bottom: 8px">
        <n-tag v-for="(item, index) in selectedMentions" :key="item.kind + item.name" closable @close="selectedMentions.splice(index, 1)">@{{ item.name }}</n-tag>
      </n-space>
      <div v-if="mentionCandidates.length" class="mention-options" role="listbox">
        <button v-for="(item, index) in mentionCandidates" :key="item.kind + item.name" :class="{ active: index === mentionIndex }" type="button" @mousedown.prevent="chooseMention(item)">
          <strong>{{ item.kind === 'skill' ? '技能' : '工具' }} · {{ item.name }}</strong><span>{{ item.description }}</span>
        </button>
      </div>
      <div class="chat-input-row">
        <n-input
          v-model:value="inputText"
          type="textarea"
          :autosize="{ minRows: 1, maxRows: 4 }"
          placeholder="输入消息，@ 选择技能或工具，Enter 发送"
          :disabled="streaming || compacting"
          @keydown="onInputKeydown" @keyup="onMentionCursor" @click="onMentionCursor"
        />
        <div class="chat-input-actions">
          <ContextUsageRing :usage="contextUsage" :loading="contextLoading" :busy="streaming || compacting" />
          <n-button v-if="streaming" type="error" @click="stopStream">
            <template #icon><n-icon><StopOutline /></n-icon></template>
            停止
          </n-button>
          <n-button v-else type="primary" :loading="sending" :disabled="!inputText.trim() || compacting" @click="send">
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
          <n-button size="small" type="primary" :disabled="streaming || compacting" @click="newConversation">
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
            :disabled="streaming || compacting"
            @click="openConversation(conv)"
          >
            <div class="conv-item-main">
              <div class="conv-item-title">{{ conv.title || '新会话' }}</div>
              <div class="conv-item-meta">
                {{ conv.message_count }} 条消息 · {{ formatTime(conv.updated_at) }}
              </div>
            </div>
            <n-popconfirm
              :disabled="streaming || compacting"
              @positive-click="deleteConversation(conv)"
            >
              <template #trigger>
                <n-button
                  quaternary
                  circle
                  size="tiny"
                  class="conv-item-del"
                  :disabled="streaming || compacting"
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
    <n-drawer :show="!!selectedTraceId" :width="Math.min(900, viewportWidth)" @update:show="(show: boolean) => { if (!show) selectedTraceId = null }">
      <n-drawer-content title="完整链路日志" closable>
        <AgentTraceDetail v-if="selectedTraceId" :trace-id="selectedTraceId" />
      </n-drawer-content>
    </n-drawer>
  </div>
</template>

<script setup lang="ts">
/** 作者：LHF；时间：2026-10-25；作用：共享能力提及、临时偏好与脚本产物展示。 */
import { getCapabilities, downloadArtifact } from '@/api/skills'
import { mentionQuery, mentionOptions, insertMention, eventArtifacts, type Capability, type CapabilityMention, type Capabilities, type SkillArtifact } from '@/chat-core/capabilities'

import { computed, ref, reactive, watch, onMounted, onUnmounted, onDeactivated } from 'vue'
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
  updateAgent,
  type AgentDetail,
  type ChatMessage,
  type ChatCitation,
  type CitationBinding,
  type ChatDebug,
  type ChatSuggestion,
} from '@/api/agent'
import {
  createConversation,
  compactConversation,
  getContextUsage,
  listConversations,
  listConversationMessages,
  deleteConversation as apiDeleteConversation,
  type ConversationItem,
  type ContextUsage,
} from '@/api/conversation'
import { renderMarkdown } from '@/chat-core/markdown'
import '@/chat-core/markdown.css'
import { stripUnboundSourceMarkers } from '@/utils/citations'
import { createTurnState, reduceTurnEvent, interruptTurn, type TurnState } from '@/chat-core/stage-reducer'
import AgentProcessTimeline from './components/AgentProcessTimeline.vue'
import AgentTraceDetail from './components/AgentTraceDetail.vue'
import ContextUsageRing from './components/ContextUsageRing.vue'

defineOptions({ name: 'AgentChatView' })
const selectedTraceId = ref<string | null>(null)
const viewportWidth = window.innerWidth
onDeactivated(() => { selectedTraceId.value = null })

interface DisplayMessage extends ChatMessage {
  /** 检索调试信息（Debug 模式） */
  debug?: ChatDebug | null
  /** 消息唯一标识（引用定位锚点用） */
  uid: number
  citations?: ChatCitation[]
  /** 经过服务端候选来源校验的稳定引用绑定（新会话） */
  citationBindings?: CitationBinding[]
  /** 完整引用列表（过滤前，保留原始编号用） */
  rawCitations?: ChatCitation[]
  error?: boolean
  /** 每条引用的展开状态（原始索引 → 是否展开） */
  expandedCitations?: Record<string, boolean>
  /** 引用面板是否展开 */
  refPanelExpanded?: boolean
  // ── Phase 4.10 意图路由展示 ──
  /** 意图类别，只影响可选规划和核验。 */
  intentLabel?: string | null
  requestMentions?: CapabilityMention[]
  /** plan 工具输出（计划内容） */
  plan?: string | null
  /** reflect 工具输出（反思建议） */
  reflect?: string | null
  /** AgentEvent v2 累积状态；完整诊断始终采集，通过链路抽屉查看。 */
  turnState?: TurnState
  traceId?: string | null
}

const route = useRoute()
const router = useRouter()
const message = useMessage()
const dialog = useDialog()

const agentId = route.params.id as string
const agent = ref<AgentDetail | null>(null)

const messages = ref<DisplayMessage[]>([])
let msgUid = 0
const inputText = ref('')
const capabilities = ref<Capabilities>({ skills: [], tools: [] })
const selectedMentions = ref<CapabilityMention[]>([])
const mentionIndex = ref(0)
const mentionCursor = ref<number | null>(null)
const mentionDismissed = ref(false)
const activeMention = computed(() => mentionDismissed.value ? null : mentionQuery(inputText.value, mentionCursor.value ?? inputText.value.length))
const mentionCandidates = computed(() => activeMention.value ? mentionOptions(capabilities.value, activeMention.value.query, selectedMentions.value) : [])
watch(inputText, () => { mentionIndex.value = 0; mentionCursor.value = null; mentionDismissed.value = false })
watch(() => !!activeMention.value, open => { if (open) refreshCapabilities() })

/** 每次开始 @ 时刷新动态候选，加载失败不扩大可用能力。 */
async function refreshCapabilities() {
  try { capabilities.value = await getCapabilities(agentId) }
  catch (error) { capabilities.value = { skills: [], tools: [] }; message.error((error as Error).message) }
}
/** 选择仅增加用户偏好，不直接执行对应能力。 */
function chooseMention(item: Capability) {
  if (!activeMention.value) return
  inputText.value = insertMention(inputText.value, activeMention.value)
  selectedMentions.value.push({ kind: item.kind, name: item.name })
  mentionCursor.value = null
}
/** 光标位于文本中间时仍按当前位置搜索。 */
function onMentionCursor(event: Event) { const target = event.target as HTMLTextAreaElement; mentionCursor.value = target.selectionStart }
/** 使用当前会话身份下载脚本产物。 */
async function saveArtifact(file: SkillArtifact) {
  try { await downloadArtifact(agentId, file) } catch (error) { message.error((error as Error).message) }
}
const sending = ref(false)
const streaming = ref(false)
const compacting = ref(false)

/** 作者：LHF；2026-10-25；手动压缩当前会话并开放本次压缩的完整链路。 */
async function compactContext() {
  if (!activeConv.value || streaming.value || sending.value || compacting.value) return
  const convId = activeConv.value.id
  compacting.value = true
  try {
    const result = await compactConversation(convId)
    message.success(result.compressed
      ? `上下文已压缩：约 ${result.before_tokens} → ${result.after_tokens} token`
      : '当前上下文无需压缩，已保留原记忆')
    selectedTraceId.value = result.trace_id
  } catch (error) {
    message.error((error as Error).message || '压缩失败，原记忆已保留')
  } finally {
    compacting.value = false
  }
}
// 流式输出开关（默认开启；关闭时走非流式一次性返回）
const streamMode = ref(true)
let abortCtrl: AbortController | null = null
onUnmounted(() => abortCtrl?.abort())

// ── 会话状态 ────────────────────────────
const drawerShow = ref(false)
const conversations = ref<ConversationItem[]>([])
const activeConv = ref<ConversationItem | null>(null)
const contextUsage = ref<ContextUsage | null>(null)
const contextLoading = ref(false)
let contextRequest = 0

/** 作者：LHF；2026-10-25；切换会话及回复/压缩结束后刷新估算，忽略过期请求。 */
watch([() => activeConv.value?.id, streaming, compacting], async ([convId, isStreaming, isCompacting], old) => {
  const requestId = ++contextRequest
  if (convId !== old?.[0]) contextUsage.value = null
  contextLoading.value = false
  if (!convId || isStreaming || isCompacting) return
  contextLoading.value = true
  try {
    const usage = await getContextUsage(convId)
    if (requestId === contextRequest) contextUsage.value = usage
  } catch {
    // 容量辅助信息加载失败不影响对话，也不继续展示过期数值。
    if (requestId === contextRequest) contextUsage.value = null
  } finally {
    if (requestId === contextRequest) contextLoading.value = false
  }
})
let previewTimer: ReturnType<typeof setTimeout> | undefined
watch([inputText, () => selectedMentions.value.map(item => item.kind + ':' + item.name).join(',')], () => {
  clearTimeout(previewTimer)
  previewTimer = setTimeout(async () => {
    if (!activeConv.value || streaming.value || compacting.value) return
    const requestId = ++contextRequest
    try {
      const usage = await getContextUsage(activeConv.value.id, { message: inputText.value, mentions: selectedMentions.value })
      if (requestId === contextRequest) contextUsage.value = usage
    } catch { if (requestId === contextRequest) contextUsage.value = null }
  }, 300)
})
onUnmounted(() => clearTimeout(previewTimer))
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
  if (streaming.value || compacting.value || msgLoading.value) return
  activeConv.value = conv
  msgLoading.value = true
  try {
    const res = await listConversationMessages(conv.id, 1, 100)
    messages.value = res.items.map(m => {
      // 引用过滤：后端存的是完整检索列表，仅展示回答中实际引用（[N] 标注）的条目，
      // 与流式逻辑/widget 的 filterUsedCitations 一致；rawCitations 保留完整列表供原始编号
      const raw = m.citations || []
      const bindings = m.citation_bindings || []
      const used = extractRefIndexes(m.content || '')
      return {
        role: m.role,
        content: m.content,
        mentions: m.mentions || [],
        artifacts: m.artifacts || [],
        uid: ++msgUid,
        citations: bindings.length ? [] : raw.filter((_, i) => used.has(i + 1)),
        rawCitations: raw,
        citationBindings: bindings,
        // 作者：LHF；2026-10-25；重载历史时恢复持久化链路入口，不依赖实时 SSE 内存。
        traceId: m.trace_id || null,
      }
    })
  } catch (e) {
    message.error((e as Error).message || '历史消息加载失败')
  } finally {
    msgLoading.value = false
    scrollBottom()
  }
}

// ── 新会话（自动创建 + 欢迎语）──────────
async function newConversation() {
  if (streaming.value || compacting.value) return
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
  if (!text || streaming.value || compacting.value) return
  // 前置保证：先有会话再对话（新会话由 newConversation 创建）
  if (!activeConv.value) {
    await newConversation()
    if (!activeConv.value) return
  }

  const mentions = selectedMentions.value.map(item => ({ ...item }))
  selectedMentions.value = []
  messages.value.push({ role: 'user', content: text, uid: ++msgUid, mentions })
  inputText.value = ''
  scrollBottom()

  // 首轮对话自动命名：与后端 _persist_messages 逻辑一致（标题仍为默认值时，用第一条消息前 10 字，超过则加省略号）
  // activeConv 与会话列表同一对象引用，改这里列表同步生效，无需刷新
  if (!activeConv.value.title || activeConv.value.title === '新会话') {
    activeConv.value.title = text.length > 10 ? text.slice(0, 10) + '...' : text
  }

  // 占位助手消息（reactive：push 的是代理本身，流式增量修改实时触发视图更新）
  const assistantMsg = reactive<DisplayMessage>({
    role: 'assistant',
    content: '',
    citations: [],
    uid: ++msgUid,
    turnState: createTurnState(),
    requestMentions: mentions,
  })
  messages.value.push(assistantMsg)
  scrollBottom()

  await doRequest(assistantMsg, text, activeConv.value.id)
}

/**
 * 实际请求逻辑（非流式 / 流式 + 错误处理）
 * 独立出来以便 temperature 限制弹窗确认后复用占位消息重试
 */
async function doRequest(
  assistantMsg: DisplayMessage,
  text: string,
  conversationId: string,
) {
  streaming.value = true
  sending.value = true
  abortCtrl = new AbortController()

  // 非流式：一次性返回 answer + citations
  if (!streamMode.value) {
    assistantMsg.turnState = undefined
    try {
      const res = await chatAgent(agentId, { mentions: assistantMsg.requestMentions || [], message: text, conversation_id: conversationId })
      assistantMsg.artifacts = res.artifacts || []
      assistantMsg.content = res.answer
      assistantMsg.citations = res.citations
      assistantMsg.citationBindings = res.citation_bindings || []
      assistantMsg.debug = res.debug || null
      assistantMsg.intentLabel = res.debug?.intent || null
      assistantMsg.traceId = res.trace_id || null
    } catch (e) {
      const err = e as Error & { suggestion?: ChatSuggestion | null }
      handleChatError(assistantMsg, err.message, err.suggestion, text, conversationId)
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
      { mentions: assistantMsg.requestMentions || [], message: text, conversation_id: conversationId, stream: true },
      (event) => {
        assistantMsg.turnState = reduceTurnEvent(assistantMsg.turnState || createTurnState(), event)
        if (event.stage === 'artifacts') assistantMsg.artifacts = eventArtifacts(event.detail.artifacts)
        if (event.type === 'answer.delta') {
          assistantMsg.content = assistantMsg.turnState.content
          scrollBottom()
        } else if (event.type === 'answer.revision_started') {
          assistantMsg.content = ''
        } else if (event.type === 'citations.completed') {
          const bindings = Array.isArray(event.detail.bindings)
            ? event.detail.bindings as unknown as CitationBinding[]
            : []
          assistantMsg.citationBindings = bindings
          assistantMsg.rawCitations = event.citations
          const used = extractRefIndexes(assistantMsg.content)
          assistantMsg.citations = bindings.length
            ? []
            : event.citations.filter((_, i) => used.has(i + 1))
          assistantMsg.content = stripUnboundSourceMarkers(
            assistantMsg.content,
            bindings.map(binding => binding.source_id),
          )
        } else if (event.type === 'stage.completed' && event.stage === 'intent') {
          const intent = event.detail.intent
          if (typeof intent === 'string') assistantMsg.intentLabel = intent
        } else if (event.type === 'turn.failed') {
          handleChatError(assistantMsg, event.summary || event.code || 'Agent 处理失败', null, text, conversationId)
        }
      },
      abortCtrl.signal,
    )
  } catch (e) {
    if ((e as Error).name === 'AbortError') {
      // 用户主动停止：保留已输出内容
      if (assistantMsg.turnState) assistantMsg.turnState = interruptTurn(assistantMsg.turnState, 'cancelled')
    } else {
      if (assistantMsg.turnState) assistantMsg.turnState = interruptTurn(assistantMsg.turnState, 'failed')
      const err = e as Error & { suggestion?: ChatSuggestion | null }
      handleChatError(assistantMsg, err.message, err.suggestion, text, conversationId)
    }
  } finally {
    streaming.value = false
    sending.value = false
    abortCtrl = null
  }
}

/**
 * 统一错误处理：带 suggestion（如推理模型 temperature 限制）→ 弹窗让用户确认；否则常规错误展示
 */
function handleChatError(
  assistantMsg: DisplayMessage,
  errMsg: string,
  suggestion: ChatSuggestion | null | undefined,
  text: string,
  conversationId: string,
) {
  if (suggestion?.action === 'set_temperature') {
    // 清掉错误占位，弹窗确认后复用重试
    assistantMsg.content = ''
    assistantMsg.error = false
    showTemperatureDialog(errMsg, suggestion.value, assistantMsg, text, conversationId)
  } else {
    assistantMsg.error = true
    // 已有内容时换行分隔错误信息，空内容时不加换行
    const sep = assistantMsg.content ? '\n' : ''
    assistantMsg.content = assistantMsg.content + sep + `[错误] ${errMsg}`
  }
}

/**
 * 推理模型 temperature 限制弹窗：自动修改 temperature=1 并重试 / 取消（自行换模型）
 */
function showTemperatureDialog(
  errMsg: string,
  value: number | string | undefined,
  assistantMsg: DisplayMessage,
  text: string,
  conversationId: string,
) {
  const temp = value ?? 1
  dialog.warning({
    title: '模型不支持当前采样温度',
    content: `${errMsg}\n\n是否将本 Agent 的 temperature 自动修改为 ${temp} 并重试？\n也可以到「编辑 Agent」更换其他模型。`,
    positiveText: '自动修改并重试',
    negativeText: '取消',
    onPositiveClick: async () => {
      try {
        await updateAgent(agentId, { temperature: Number(temp) })
        message.success(`已修改 temperature=${temp}，正在重试...`)
        await doRequest(assistantMsg, text, conversationId)
      } catch (e) {
        message.error((e as Error).message || '修改 temperature 失败')
      }
    },
  })
}

function stopStream() {
  abortCtrl?.abort()
}

function onInputKeydown(e: KeyboardEvent) {
  if (e.isComposing) return
  if (mentionCandidates.value.length) {
    if (e.key === 'Escape') { mentionDismissed.value = true; e.preventDefault(); return }
    if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
      e.preventDefault(); mentionIndex.value = (mentionIndex.value + (e.key === 'ArrowDown' ? 1 : -1) + mentionCandidates.value.length) % mentionCandidates.value.length; return
    }
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); chooseMention(mentionCandidates.value[mentionIndex.value]!); return }
  }
  // Enter 发送，Shift+Enter 换行
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault()
    send()
  }
}

/**
 * 是否为当前正在等待/生成中的消息（最后一条 + 请求中 + 尚无内容）
 *
 * 注意：必须同时满足「无内容」——首个 delta 到达后立即切换为渲染 content（打字机），
 * 否则流式期间永远命中此分支，内容要等结束才一次性显示（与 widget 的 pending 字段语义一致）。
 */
function isPendingMsg(msg: DisplayMessage): boolean {
  const last = messages.value[messages.value.length - 1]
  return (streaming.value || sending.value) && last === msg && !msg.content
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

/** 提供本条回答可定位的来源 ID，保留历史数字引用。 */
function citationIds(msg: DisplayMessage): string[] {
  return [...(msg.citationBindings || []).map(binding => binding.source_id),
    ...(msg.rawCitations || []).map((_, index) => String(index + 1))]
}

/** 委托处理 Markdown 中的来源标记，不拦截普通链接。 */
function onMarkdownCitation(msg: DisplayMessage, event: Event): void {
  const element = (event.target as HTMLElement).closest<HTMLElement>('[data-source-ref]')
  const id = element?.dataset.sourceRef
  if (!id) return
  event.preventDefault()
  if (id.startsWith('S')) locateCitationBinding(msg, id)
  else locateCitation(msg, Number(id))
}

/** 点击 [N]：展开历史引用面板 + 展开对应条目 + 滚动定位 */
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

/** 点击 [S#]：仅按服务端验证过的 source_id 定位，绝不以展示顺序猜测来源。 */
function locateCitationBinding(msg: DisplayMessage, sourceId: string) {
  if (!msg.citationBindings?.some(binding => binding.source_id === sourceId)) return
  msg.refPanelExpanded = true
  if (!msg.expandedCitations) msg.expandedCitations = {}
  msg.expandedCitations[sourceId] = true
  nextTick(() => {
    window.setTimeout(() => {
      const el = document.querySelector(`[data-citation-index="${msg.uid}-${sourceId}"]`)
      el?.scrollIntoView({ behavior: 'smooth', block: 'center' })
    }, 300)
  })
}

// ── 引用展开/收起 ───────────────────────
function isCitationExpanded(msg: DisplayMessage, idx: string | number): boolean {
  return !!msg.expandedCitations?.[idx]
}

function toggleCitation(msg: DisplayMessage, idx: string | number) {
  if (!msg.expandedCitations) {
    msg.expandedCitations = {}
  }
  msg.expandedCitations[idx] = !msg.expandedCitations[idx]
}
</script>

<style scoped>
.mention-options { display: flex; flex-direction: column; max-height: 220px; overflow: auto; margin-bottom: 10px; border: 1px solid #ddd; border-radius: 8px; }
.mention-options button { text-align: left; border: 0; background: transparent; padding: 8px 12px; cursor: pointer; color: inherit; }
.mention-options button.active, .mention-options button:hover { background: rgba(24,160,88,.1); }
.mention-options span { display: block; font-size: 12px; opacity: .7; }

/* ── Phase 4.10：意图标签 / 规划反思过程展示 ── */
.intent-tag-row {
  margin-bottom: 6px;
}
.msg-process {
  margin-bottom: 8px;
}
.process-content {
  margin: 0;
  white-space: pre-wrap;
  word-break: break-word;
  font-size: 12px;
  line-height: 1.6;
  color: #666;
  background: rgba(128, 128, 128, 0.06);
  border-radius: 6px;
  padding: 8px 10px;
}

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

.citation-claim {
  margin: 6px 0;
  color: var(--n-text-color-2);
  font-size: 13px;
  line-height: 1.6;
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
  align-items: center;
  gap: 8px;
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
