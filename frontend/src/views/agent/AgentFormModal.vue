<template>
  <n-modal
    v-model:show="show"
    :title="editing ? '编辑 Agent' : '新建 Agent'"
    preset="card"
    style="width: 620px"
    :mask-closable="false"
    @after-leave="resetForm"
  >
    <n-form ref="formRef" :model="formData" :rules="rules" label-placement="left" label-width="120" require-mark-placement="right-hanging">
      <!-- ── 基础选项 ─────────────────────── -->
      <n-form-item label="类型" path="type">
        <n-radio-group v-model:value="formData.type" :disabled="!!editing">
          <n-radio-button value="simple_rag">简单 RAG Agent</n-radio-button>
          <n-radio-button value="general">综合 Agent</n-radio-button>
        </n-radio-group>
      </n-form-item>

      <n-form-item label="名称" path="name">
        <n-input v-model:value="formData.name" placeholder="请输入 Agent 名称" />
      </n-form-item>

      <n-form-item label="描述" path="description">
        <n-input v-model:value="formData.description" type="textarea" placeholder="可选" :autosize="{ minRows: 1, maxRows: 3 }" />
      </n-form-item>

      <n-form-item label="LLM 模型" path="llm_config_id">
        <n-select
          v-model:value="formData.llm_config_id"
          :options="llmOptions"
          placeholder="选择对话模型（需先在模型配置页创建 LLM 类型配置）"
        >
          <template #empty>
            <div style="padding: 8px">暂无 LLM 配置，请先到「模型配置」页创建</div>
          </template>
        </n-select>
      </n-form-item>

      <!-- 知识库（按类型） -->
      <n-form-item v-if="formData.type === 'simple_rag'" label="知识库" path="kb_id">
        <n-select v-model:value="formData.kb_id" :options="kbOptions" placeholder="选择绑定的知识库" />
      </n-form-item>
      <template v-else>
        <n-form-item label="工具 - 知识库" path="toolKbId">
          <n-select v-model:value="toolKbId" :options="kbOptions" placeholder="rag 工具绑定的知识库" />
        </n-form-item>
        <n-alert type="info" :show-icon="false" style="margin-bottom: 16px">
          general Agent 由 LLM 自主决定是否调用 rag 工具（知识库检索），可能多轮调用。
        </n-alert>
      </template>

      <!-- ── 高级选项（默认折叠）────────── -->
      <n-collapse>
        <!-- 检索配置：top_k / 阈值 / 检索增强开关 -->
        <n-collapse-item title="检索配置" name="retrieval">
          <n-alert type="warning" :show-icon="false" style="margin-bottom: 12px">
            开启 MQE / HyDE 查询增强会<b>额外消耗 token</b>，并<b>增加单次对话的查询时间</b>；请按需开启。
          </n-alert>
          <template v-if="formData.type === 'simple_rag'">
            <n-form-item label="检索块数 top_k">
              <n-input-number v-model:value="formData.top_k" :min="1" :max="50" style="width: 100%" placeholder="默认 5" />
            </n-form-item>
            <n-form-item label="相似度阈值">
              <n-input-number v-model:value="formData.score_threshold" :min="0" :max="1" :step="0.05" style="width: 100%" placeholder="默认 0.3" />
            </n-form-item>
            <!-- Phase 4.6 检索增强（独立开关，按需开启节省 token） -->
            <n-form-item label="多查询扩展 MQE">
              <n-switch v-model:value="formData.mqe_enabled" />
              <template #feedback>LLM 将问题改写为多个子问题多路检索，提升召回；额外消耗 token</template>
            </n-form-item>
            <n-form-item v-if="formData.mqe_enabled" label="MQE 子问题数">
              <n-input-number v-model:value="formData.mqe_query_count" :min="2" :max="5" style="width: 100%" placeholder="默认 3" />
            </n-form-item>
            <n-form-item label="假设文档嵌入 HyDE">
              <n-switch v-model:value="formData.hyde_enabled" />
              <template #feedback>LLM 先生成假设回答文档再检索，提升语义匹配；额外消耗 token</template>
            </n-form-item>
            <n-form-item label="Rerank 精排">
              <n-switch v-model:value="formData.rerank_enabled" />
              <template #feedback>粗召回后二次精排，提升相关性；需配置 Rerank 模型</template>
            </n-form-item>
          </template>
          <template v-else>
            <n-form-item label="工具 - top_k">
              <n-input-number v-model:value="toolTopK" :min="1" :max="50" style="width: 100%" placeholder="默认 5" />
            </n-form-item>
            <n-form-item label="工具 - 相似度阈值">
              <n-input-number v-model:value="toolThreshold" :min="0" :max="1" :step="0.05" style="width: 100%" placeholder="默认 0.3" />
            </n-form-item>
            <!-- Phase 4.6 检索增强（工具级独立开关） -->
            <n-form-item label="工具 - 多查询扩展 MQE">
              <n-switch v-model:value="toolMqeEnabled" />
              <template #feedback>LLM 改写多个子问题多路检索；额外消耗 token</template>
            </n-form-item>
            <n-form-item v-if="toolMqeEnabled" label="工具 - MQE 子问题数">
              <n-input-number v-model:value="toolMqeCount" :min="2" :max="5" style="width: 100%" placeholder="默认 3" />
            </n-form-item>
            <n-form-item label="工具 - 假设文档嵌入 HyDE">
              <n-switch v-model:value="toolHydeEnabled" />
              <template #feedback>LLM 生成假设回答文档再检索；额外消耗 token</template>
            </n-form-item>
            <n-form-item label="工具 - Rerank 精排">
              <n-switch v-model:value="toolRerankEnabled" />
              <template #feedback>粗召回后二次精排，提升相关性</template>
            </n-form-item>
          </template>
        </n-collapse-item>

        <!-- 意图路由 + 内置推理工具（仅 general） -->
        <n-collapse-item v-if="formData.type === 'general'" title="意图路由" name="intent">
          <n-alert type="info" :show-icon="false" style="margin-bottom: 12px">
            开启后简单问题（问候/感谢/闲聊）走<b>零工具直接回答</b>，省 token、降低延迟；
            复杂问题仍由 LLM 自主规划（plan）与反思（reflect）。规则可自定义。
          </n-alert>
          <n-form-item label="意图路由">
            <n-switch v-model:value="formData.intent_routing" />
            <template #feedback>关闭 = 纯 ReAct（所有问题由 LLM 自行判断）</template>
          </n-form-item>
          <n-form-item label="规划工具 plan">
            <n-switch v-model:value="formData.plan_enabled" />
            <template #feedback>复杂任务先制定分步计划再执行</template>
          </n-form-item>
          <n-form-item label="反思工具 reflect">
            <n-switch v-model:value="formData.reflect_enabled" />
            <template #feedback>生成答案前自动审查并修正</template>
          </n-form-item>

          <!-- 意图规则列表 -->
          <n-form-item label="识别规则" label-style="align-self: flex-start">
            <div style="width: 100%">
              <div
                v-for="(rule, i) in intentRules"
                :key="i"
                style="display: flex; gap: 6px; align-items: center; margin-bottom: 8px"
              >
                <n-input v-model:value="rule.name" size="small" placeholder="规则名" style="width: 90px" />
                <n-select
                  v-model:value="rule.target"
                  size="small"
                  style="width: 84px"
                  :options="[
                    { label: '→简单', value: 'simple' },
                    { label: '→复杂', value: 'general' },
                  ]"
                />
                <n-select
                  v-model:value="rule.kind"
                  size="small"
                  style="width: 90px"
                  :options="[
                    { label: '关键词', value: 'keyword' },
                    { label: '正则', value: 'regex' },
                    { label: '长度', value: 'length' },
                  ]"
                />
                <n-input
                  v-if="rule.kind === 'keyword'"
                  v-model:value="rule.keywordsText"
                  size="small"
                  placeholder="关键词，逗号分隔"
                  style="flex: 1"
                />
                <n-input
                  v-else-if="rule.kind === 'regex'"
                  v-model:value="rule.pattern"
                  size="small"
                  placeholder="正则表达式"
                  style="flex: 1"
                />
                <n-input-number
                  v-else
                  v-model:value="rule.max_length"
                  size="small"
                  :min="1"
                  placeholder="长度上限"
                  style="flex: 1"
                />
                <n-input-number v-model:value="rule.priority" size="small" :min="0" :max="10000" style="width: 72px" />
                <n-switch v-model:value="rule.enabled" size="small" />
                <n-button size="tiny" quaternary type="error" @click="removeIntentRule(i)">删</n-button>
              </div>
              <n-space>
                <n-button size="small" dashed @click="addIntentRule">+ 添加规则</n-button>
                <n-button size="small" dashed @click="resetIntentRules">恢复默认</n-button>
              </n-space>
              <div style="color: #888; font-size: 12px; margin-top: 8px">
                按优先级从小到大执行，命中即判定；简单规则请保持保守（仅问候/感谢等），复杂规则可放宽。
              </div>
            </div>
          </n-form-item>
        </n-collapse-item>

        <!-- 模型配置：总结 / 增强 / Rerank -->
        <n-collapse-item title="模型配置" name="models">
          <n-form-item label="总结模型">
            <n-select
              v-model:value="formData.summary_llm_config_id"
              :options="summaryOptions"
              placeholder="跟随对话模型"
            >
              <template #empty>
                <div style="padding: 8px">暂无 LLM 配置，请先到「模型配置」页创建</div>
              </template>
            </n-select>
            <template #feedback>长对话自动总结时使用的模型；不选则跟随对话模型</template>
          </n-form-item>

          <n-form-item label="增强模型">
            <n-select
              v-model:value="formData.enhance_llm_config_id"
              :options="enhanceOptions"
              placeholder="跟随对话模型"
            >
              <template #empty>
                <div style="padding: 8px">暂无 LLM 配置，请先到「模型配置」页创建</div>
              </template>
            </n-select>
            <template #feedback>查询增强（MQE/HyDE）改写时使用的模型；不选则跟随对话模型</template>
          </n-form-item>

          <n-form-item v-if="showRerankModel" label="Rerank 模型" path="rerank_config_id" require-mark="true">
            <n-select
              v-model:value="formData.rerank_config_id"
              :options="rerankOptions"
              placeholder="请选择 Rerank 模型"
            >
              <template #empty>
                <div style="padding: 8px">暂无 Rerank 配置，请先到「模型配置」页创建（模型类型选 Rerank）</div>
              </template>
            </n-select>
            <template #feedback>开启 Rerank 必须选择精排模型；暂无配置时请先到「模型配置」页添加</template>
          </n-form-item>
        </n-collapse-item>

        <!-- 生成参数：采样 / 欢迎语 / 提示词 -->
        <n-collapse-item title="生成参数" name="generation">
          <n-alert type="info" :show-icon="false" style="margin-bottom: 12px">
            采样参数<b>留空则使用模型配置</b>的值（模型也未配置时用默认 0.7 / 0.9）；Agent 单独设置时以 Agent 为准。
          </n-alert>
          <n-form-item label="采样 temperature">
            <n-input-number v-model:value="formData.temperature" :min="0" :max="2" :step="0.1" style="width: 100%" placeholder="默认 0.7（跟随模型配置）" />
          </n-form-item>
          <n-form-item label="采样 top_p">
            <n-input-number v-model:value="formData.top_p" :min="0" :max="1" :step="0.05" style="width: 100%" placeholder="默认 0.9（跟随模型配置）" />
          </n-form-item>
          <n-form-item label="最大 tokens">
            <n-input-number v-model:value="formData.max_tokens" :min="1" :max="1000000" style="width: 100%" placeholder="跟随模型配置/厂商默认" />
          </n-form-item>

          <n-form-item label="欢迎语">
            <n-input v-model:value="formData.welcome_message" placeholder="可选（浮窗展示用）" />
          </n-form-item>

          <n-form-item label="系统提示词">
            <n-input v-model:value="formData.system_prompt" type="textarea" :autosize="{ minRows: 5, maxRows: 10 }" placeholder="留空使用默认模板" />
          </n-form-item>
        </n-collapse-item>
      </n-collapse>
    </n-form>

    <template #footer>
      <n-space justify="end">
        <n-button @click="show = false">取消</n-button>
        <n-button type="primary" :loading="submitting" @click="handleSubmit">确定</n-button>
      </n-space>
    </template>
  </n-modal>
</template>

<script setup lang="ts">
import { ref, computed, watch } from 'vue'
import type { FormInst, FormRules, SelectOption } from 'naive-ui'
import {
  createAgent,
  updateAgent,
  getAgentDefaults,
  type AgentDetail,
  type AgentCreatePayload,
  type ToolConfig,
  type IntentRule,
} from '@/api/agent'
import { listKnowledgeBases, type KnowledgeBaseListItem } from '@/api/knowledge'
import { listMyConfigs, type UserModelConfigItem } from '@/api/model-config'

const props = defineProps<{
  show: boolean
  editing: AgentDetail | null
}>()
const emit = defineEmits<{
  'update:show': [value: boolean]
  saved: []
}>()

// v-model:show 桥接（props 只读，需经 emit 回写）
const show = computed({
  get: () => props.show,
  set: (val: boolean) => emit('update:show', val),
})

const message = useMessage()

// ── 选项数据 ────────────────────────────
const kbs = ref<KnowledgeBaseListItem[]>([])
const modelConfigs = ref<UserModelConfigItem[]>([])

const kbOptions = computed<SelectOption[]>(() =>
  kbs.value.filter(k => k.status === 1).map(k => ({ label: k.name, value: k.id })),
)
const llmOptions = computed<SelectOption[]>(() =>
  modelConfigs.value
    .filter(c => c.model_type === 2 && c.is_active)
    .map(c => ({ label: `${c.provider} / ${c.model_name}`, value: c.id })),
)

// 总结模型选项：跟随对话模型（''）+ LLM 配置列表（提交时 '' → null）
const summaryOptions = computed<SelectOption[]>(() => [
  { label: '跟随对话模型', value: '' },
  ...llmOptions.value,
])

// 增强模型选项（MQE/HyDE 改写用）：与总结模型同结构，空 = 跟随对话模型
const enhanceOptions = computed<SelectOption[]>(() => [
  { label: '跟随对话模型', value: '' },
  ...llmOptions.value,
])

// Rerank 模型选项（model_type=3 配置）：开启 Rerank 时必须选择
const rerankOptions = computed<SelectOption[]>(() =>
  modelConfigs.value
    .filter(c => c.model_type === 3 && c.is_active)
    .map(c => ({ label: `${c.provider} / ${c.model_name}`, value: c.id })),
)

// Rerank 模型选择器显隐：仅对应区块的 rerank 开关开启时显示
const showRerankModel = computed(() =>
  formData.value.type === 'simple_rag'
    ? !!formData.value.rerank_enabled
    : !!toolRerankEnabled.value,
)

// ── 表单状态 ────────────────────────────
const formRef = ref<FormInst>()
const submitting = ref(false)

const formData = ref<AgentCreatePayload & { description: string; welcome_message: string; system_prompt: string }>({
  type: 'simple_rag',
  name: '',
  description: '',
  llm_config_id: '',
  summary_llm_config_id: '',
  kb_id: null,
  top_k: null,
  score_threshold: null,
  temperature: null,
  top_p: null,
  max_tokens: null,
  welcome_message: '',
  system_prompt: '',
  // Phase 4.6 检索增强
  mqe_enabled: false,
  hyde_enabled: false,
  mqe_query_count: 3,
  rerank_enabled: false,
  enhance_llm_config_id: '',
  rerank_config_id: '',
  // Phase 4.10 意图路由
  intent_routing: false,
  plan_enabled: true,
  reflect_enabled: true,
})

// 意图规则编辑态（keywordsText 为逗号分隔的编辑中间态，提交时 split）
interface EditableIntentRule extends IntentRule {
  keywordsText: string
}

const intentRules = ref<EditableIntentRule[]>([])

/** 默认规则模板（与后端 DEFAULT_INTENT_RULES 对齐的展示副本，用于「恢复默认」） */
const DEFAULT_INTENT_RULE_TEMPLATE: Array<Omit<EditableIntentRule, 'keywordsText'> & { keywords: string[] }> = [
  { name: '检索意图', kind: 'keyword', keywords: ['查', '搜索', '检索', '看看', '找一下', '查询'], target: 'general', priority: 5, enabled: true },
  { name: '对比分析', kind: 'keyword', keywords: ['对比', '比较', '分析', '评估', '优缺点', '区别', '差异'], target: 'general', priority: 5, enabled: true },
  { name: '任务规划', kind: 'keyword', keywords: ['规划', '方案', '计划', '步骤', '流程', '怎么做', '如何', '帮我'], target: 'general', priority: 5, enabled: true },
  { name: '数据类', kind: 'keyword', keywords: ['数据', '统计', '报表', '指标', '趋势'], target: 'general', priority: 5, enabled: true },
  { name: '问候语', kind: 'keyword', keywords: ['你好', '您好', 'hi', 'hello', '嗨', '哈喽', '早上好', '中午好', '下午好', '晚上好'], target: 'simple', priority: 10, enabled: true },
  { name: '感谢语', kind: 'keyword', keywords: ['谢谢', '感谢', '辛苦了', '多谢'], target: 'simple', priority: 20, enabled: true },
  { name: '告别语', kind: 'keyword', keywords: ['再见', '拜拜', '晚安'], target: 'simple', priority: 30, enabled: true },
  { name: '简短肯定', kind: 'keyword', keywords: ['好的', '可以', '明白了', '知道了', 'ok', '嗯'], target: 'simple', priority: 40, enabled: true },
]

/** 后端 IntentRules → 编辑态 */
function toEditableRules(rules: IntentRule[]): EditableIntentRule[] {
  return rules.map(r => ({
    ...r,
    keywordsText: (r.keywords || []).join(','),
  }))
}

/** 编辑态 → 提交 payload（keywordsText 转数组，空规则剔除） */
function toPayloadRules(): IntentRule[] {
  return intentRules.value
    .map(r => ({
      id: r.id,
      name: r.name,
      kind: r.kind,
      keywords: r.kind === 'keyword' ? r.keywordsText.split(/[,，]/).map(s => s.trim()).filter(Boolean) : null,
      pattern: r.kind === 'regex' ? r.pattern || null : null,
      max_length: r.kind === 'length' ? r.max_length ?? null : null,
      target: r.target,
      enabled: r.enabled,
      priority: r.priority,
    }))
    .filter(r => r.name.trim())
}

function addIntentRule() {
  intentRules.value.push({
    id: null,
    name: '',
    kind: 'keyword',
    keywordsText: '',
    pattern: null,
    max_length: null,
    target: 'simple',
    enabled: true,
    priority: 100,
  })
}

function removeIntentRule(i: number) {
  intentRules.value.splice(i, 1)
}

function resetIntentRules() {
  intentRules.value = toEditableRules(
    DEFAULT_INTENT_RULE_TEMPLATE.map(r => ({ ...r })),
  )
}

// general 工具配置（独立 state，提交时组装进 tools）
const toolKbId = ref<string | null>(null)
const toolTopK = ref<number | null>(null)
const toolThreshold = ref<number | null>(null)
// Phase 4.6 检索增强（工具级独立开关）
const toolMqeEnabled = ref(false)
const toolHydeEnabled = ref(false)
const toolMqeCount = ref<number | null>(null)
const toolRerankEnabled = ref(false)

const rules: FormRules = {
  name: { required: true, message: '请输入名称', trigger: 'blur' },
  llm_config_id: { required: true, message: '请选择 LLM 模型', trigger: 'change' },
  kb_id: {
    validator: () => {
      if (formData.value.type === 'simple_rag' && !formData.value.kb_id) {
        return new Error('请选择知识库')
      }
      return true
    },
    trigger: 'change',
  },
  toolKbId: {
    validator: () => {
      if (formData.value.type === 'general' && !toolKbId.value) {
        return new Error('请选择工具绑定的知识库')
      }
      return true
    },
    trigger: 'change',
  },
  rerank_config_id: {
    validator: () => {
      const enabled = formData.value.type === 'simple_rag'
        ? formData.value.rerank_enabled
        : toolRerankEnabled.value
      if (enabled && !formData.value.rerank_config_id) {
        return new Error('开启 Rerank 必须选择 Rerank 模型')
      }
      return true
    },
    trigger: 'change',
  },
}

// 默认配置（新建时系统提示词默认填入默认模板）
const defaults = ref<{ system_prompt: string }>({ system_prompt: '' })

async function fetchDefaults() {
  try {
    defaults.value = await getAgentDefaults()
  } catch {
    /* 默认模板不可用则保持空 */
  }
}

// ── 弹窗开关：编辑时回填 ────────────────
watch(
  () => props.show,
  async (val) => {
    if (!val) return
    await Promise.all([fetchKbs(), fetchModelConfigs(), fetchDefaults()])
    if (props.editing) {
      const e = props.editing
      formData.value = {
        type: e.type,
        name: e.name,
        description: e.description || '',
        llm_config_id: e.llm_config_id,
        summary_llm_config_id: e.summary_llm_config_id || '',
        kb_id: e.kb_id,
        top_k: e.top_k,
        score_threshold: e.score_threshold,
        temperature: e.temperature,
        top_p: e.top_p,
        max_tokens: e.max_tokens,
        welcome_message: e.welcome_message || '',
        system_prompt: e.system_prompt || '',
        mqe_enabled: e.mqe_enabled,
        hyde_enabled: e.hyde_enabled,
        mqe_query_count: e.mqe_query_count,
        rerank_enabled: e.rerank_enabled,
        enhance_llm_config_id: e.enhance_llm_config_id || '',
        rerank_config_id: e.rerank_config_id || '',
        intent_routing: e.intent_routing ?? false,
        plan_enabled: e.plan_enabled ?? true,
        reflect_enabled: e.reflect_enabled ?? true,
      }
      intentRules.value = toEditableRules((e.intent_rules?.rules || []).map(r => ({ ...r })))
      if (e.type === 'general' && e.tools.length > 0) {
        toolKbId.value = e.tools[0].kb_id
        toolTopK.value = e.tools[0].top_k
        toolThreshold.value = e.tools[0].score_threshold
        toolMqeEnabled.value = e.tools[0].mqe_enabled ?? false
        toolHydeEnabled.value = e.tools[0].hyde_enabled ?? false
        toolMqeCount.value = e.tools[0].mqe_query_count ?? null
        toolRerankEnabled.value = e.tools[0].rerank_enabled ?? false
      }
    } else {
      formData.value = {
        type: 'simple_rag', name: '', description: '', llm_config_id: '',
        summary_llm_config_id: '',
        kb_id: null, top_k: null, score_threshold: null,
        temperature: null, top_p: null, max_tokens: null, welcome_message: '',
        system_prompt: defaults.value.system_prompt || '',
        mqe_enabled: false, hyde_enabled: false, mqe_query_count: 3,
        rerank_enabled: false, enhance_llm_config_id: '', rerank_config_id: '',
        intent_routing: false, plan_enabled: true, reflect_enabled: true,
      }
      intentRules.value = toEditableRules(
        DEFAULT_INTENT_RULE_TEMPLATE.map(r => ({ ...r })),
      )
      toolKbId.value = null
      toolTopK.value = null
      toolThreshold.value = null
      toolMqeEnabled.value = false
      toolHydeEnabled.value = false
      toolMqeCount.value = null
      toolRerankEnabled.value = false
    }
  },
)

// ── 提交 ────────────────────────────────
async function handleSubmit() {
  try {
    await formRef.value?.validate()
  } catch {
    return
  }

  const payload: AgentCreatePayload = {
    type: formData.value.type,
    name: formData.value.name,
    description: formData.value.description || null,
    llm_config_id: formData.value.llm_config_id,
    summary_llm_config_id: formData.value.summary_llm_config_id || null,
    temperature: formData.value.temperature,
    top_p: formData.value.top_p,
    max_tokens: formData.value.max_tokens,
    welcome_message: formData.value.welcome_message || null,
    system_prompt: formData.value.system_prompt || null,
    // Phase 4.6 检索增强（Agent 级模型引用）
    enhance_llm_config_id: formData.value.enhance_llm_config_id || null,
    rerank_config_id: formData.value.rerank_config_id || null,
  }

  if (formData.value.type === 'simple_rag') {
    payload.kb_id = formData.value.kb_id
    payload.top_k = formData.value.top_k
    payload.score_threshold = formData.value.score_threshold
    payload.mqe_enabled = formData.value.mqe_enabled
    payload.hyde_enabled = formData.value.hyde_enabled
    payload.mqe_query_count = formData.value.mqe_query_count
    payload.rerank_enabled = formData.value.rerank_enabled
  } else {
    const tool: ToolConfig = {
      type: 'rag',
      kb_id: toolKbId.value!,
      top_k: toolTopK.value,
      score_threshold: toolThreshold.value,
      mqe_enabled: toolMqeEnabled.value,
      hyde_enabled: toolHydeEnabled.value,
      mqe_query_count: toolMqeCount.value ?? undefined,
      rerank_enabled: toolRerankEnabled.value,
    }
    payload.tools = [tool]
    // Phase 4.10 意图路由 + 内置推理工具
    payload.intent_routing = formData.value.intent_routing
    payload.plan_enabled = formData.value.plan_enabled
    payload.reflect_enabled = formData.value.reflect_enabled
    payload.intent_rules = { rules: toPayloadRules() }
  }

  submitting.value = true
  try {
    if (props.editing) {
      await updateAgent(props.editing.id, payload)
      message.success('更新成功')
    } else {
      await createAgent(payload)
      message.success('创建成功')
    }
    emit('update:show', false)
    emit('saved')
  } catch (e) {
    message.error((e as Error).message || '操作失败')
  } finally {
    submitting.value = false
  }
}

function resetForm() {
  formRef.value?.restoreValidation()
}

async function fetchKbs() {
  try {
    const res = await listKnowledgeBases(1, 100)
    kbs.value = res.items
  } catch {
    kbs.value = []
  }
}

async function fetchModelConfigs() {
  try {
    modelConfigs.value = await listMyConfigs()
  } catch {
    modelConfigs.value = []
  }
}
</script>
