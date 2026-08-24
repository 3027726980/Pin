<template>
  <n-modal
    v-model:show="show"
    :title="editing ? '编辑 Agent' : '新建 Agent'"
    preset="card"
    style="width: 780px"
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

      <!-- 工具配置（Schema 驱动动态表单：simple_rag 仅 rag 卡片强制启用，general 全部可选） -->
      <n-form-item label="工具" label-style="align-self: flex-start">
        <div class="tool-config-area">
          <n-alert type="info" :show-icon="false" style="margin-bottom: 12px">
            {{ formData.type === 'simple_rag'
              ? '绑定知识库检索：在下方 rag 工具中配置知识库与检索参数。'
              : '工具列表由后端自动发现；启用后按需填写参数，新增工具无需升级前端。' }}
          </n-alert>
          <div
            v-for="def in (formData.type === 'simple_rag' ? (ragDef ? [ragDef] : []) : toolDefs)"
            :key="def.type"
            class="tool-card"
          >
            <div class="tool-card-head">
              <n-switch
                v-if="formData.type === 'general'"
                v-model:value="enabledTools[def.type]"
                size="small"
                @update:value="(v: boolean) => toggleTool(def, v)"
              />
              <n-tag v-else size="small" type="primary" :bordered="false">必选</n-tag>
              <span class="tool-card-name">{{ def.type }}</span>
              <span class="tool-card-desc">{{ def.description }}</span>
            </div>
            <div v-if="(formData.type === 'simple_rag' || enabledTools[def.type]) && toolValues[def.type]" class="tool-card-params">
              <ToolParamForm v-model="toolValues[def.type]" :def="def" />
            </div>
          </div>
          <div v-if="!toolDefs.length" style="color: #999; font-size: 13px">
            暂无可用工具（后端工具注册表为空）
          </div>
        </div>
      </n-form-item>

      <!-- ── 高级选项（默认折叠）────────── -->
      <n-collapse>

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
              <!-- 每条规则：第一行属性（名称/判定/类型/优先级/开关），第二行条件输入占满 -->
              <div
                v-for="(rule, i) in intentRules"
                :key="i"
                class="intent-rule-card"
              >
                <div class="intent-rule-row">
                  <span class="intent-rule-idx">{{ i + 1 }}</span>
                  <n-input v-model:value="rule.name" size="small" placeholder="规则名" style="width: 130px" />
                  <n-select
                    v-model:value="rule.target"
                    size="small"
                    style="width: 92px"
                    :options="[
                      { label: '→ 简单', value: 'simple' },
                      { label: '→ 复杂', value: 'general' },
                    ]"
                  />
                  <n-select
                    v-model:value="rule.kind"
                    size="small"
                    style="width: 100px"
                    :options="[
                      { label: '关键词', value: 'keyword' },
                      { label: '正则', value: 'regex' },
                      { label: '长度', value: 'length' },
                    ]"
                  />
                  <n-input-number v-model:value="rule.priority" size="small" :min="0" :max="10000" style="width: 88px" placeholder="优先级" />
                  <span class="intent-rule-hint">启用</span>
                  <n-switch v-model:value="rule.enabled" size="small" />
                  <n-button size="tiny" quaternary type="error" @click="removeIntentRule(i)">删除</n-button>
                </div>
                <div class="intent-rule-row">
                  <span class="intent-rule-idx"></span>
                  <span class="cond-label">条件</span>
                  <n-input
                    v-if="rule.kind === 'keyword'"
                    v-model:value="rule.keywordsText"
                    size="small"
                    placeholder="关键词，逗号分隔，任一命中即中（如：你好,hi,早上好）"
                    style="flex: 1"
                  />
                  <n-input
                    v-else-if="rule.kind === 'regex'"
                    v-model:value="rule.pattern"
                    size="small"
                    placeholder="正则表达式（如：^\\d+$ 表示纯数字）"
                    style="flex: 1"
                  />
                  <template v-else>
                    <n-input-number v-model:value="rule.max_length" size="small" :min="1" placeholder="如 20" style="width: 200px" />
                    <span class="cond-hint">消息长度 ≤ 该值即命中</span>
                  </template>
                </div>
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
  getToolDefs,
  type AgentDetail,
  type AgentCreatePayload,
  type ToolConfig,
  type ToolDef,
  type IntentRule,
} from '@/api/agent'
import { listKnowledgeBases, type KnowledgeBaseListItem } from '@/api/knowledge'
import { listMyConfigs, type UserModelConfigItem } from '@/api/model-config'
import ToolParamForm from './ToolParamForm.vue'

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

// rag 工具定义（simple_rag 强制启用；找不到时 simple_rag 表单提示无可用工具）
const ragDef = computed(() => toolDefs.value.find(d => d.type === 'rag') || null)

// Rerank 模型选择器显隐：两种类型都看 rag 工具参数 rerank_enabled
const showRerankModel = computed(() =>
  !!(toolValues.value['rag'] as any)?.rerank_enabled,
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
  temperature: null,
  top_p: null,
  max_tokens: null,
  welcome_message: '',
  system_prompt: '',
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

// ── 工具配置（general：Schema 驱动动态表单）──
const toolDefs = ref<ToolDef[]>([])
// 工具启用状态：{ [toolType]: boolean }
const enabledTools = ref<Record<string, boolean>>({})
// 工具参数值：{ [toolType]: { [paramKey]: value } }
const toolValues = ref<Record<string, Record<string, any>>>({})

/** 启用工具时用 param.default 初始化参数值 */
function initToolValues(def: ToolDef) {
  const values: Record<string, any> = {}
  for (const p of def.params) {
    if (p.default !== undefined) values[p.key] = p.default
    else if (p.type === 'boolean') values[p.key] = false
  }
  toolValues.value[def.type] = values
}

/** 切换工具启用：开启时初始化默认值 */
function toggleTool(def: ToolDef, on: boolean) {
  if (on && !toolValues.value[def.type]) {
    initToolValues(def)
  }
}

async function fetchToolDefs() {
  try {
    toolDefs.value = await getToolDefs()
  } catch {
    toolDefs.value = []
  }
}

const rules: FormRules = {
  name: { required: true, message: '请输入名称', trigger: 'blur' },
  llm_config_id: { required: true, message: '请选择 LLM 模型', trigger: 'change' },
  rerank_config_id: {
    validator: () => {
      if (showRerankModel.value && !formData.value.rerank_config_id) {
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
    await Promise.all([fetchKbs(), fetchModelConfigs(), fetchDefaults(), fetchToolDefs()])
    if (props.editing) {
      const e = props.editing
      formData.value = {
        type: e.type,
        name: e.name,
        description: e.description || '',
        llm_config_id: e.llm_config_id,
        summary_llm_config_id: e.summary_llm_config_id || '',
        temperature: e.temperature,
        top_p: e.top_p,
        max_tokens: e.max_tokens,
        welcome_message: e.welcome_message || '',
        system_prompt: e.system_prompt || '',
        enhance_llm_config_id: e.enhance_llm_config_id || '',
        rerank_config_id: e.rerank_config_id || '',
        intent_routing: e.intent_routing ?? false,
        plan_enabled: e.plan_enabled ?? true,
        reflect_enabled: e.reflect_enabled ?? true,
      }
      intentRules.value = toEditableRules((e.intent_rules?.rules || []).map(r => ({ ...r })))
      // 工具回填（Schema 驱动：按 tool-defs 匹配，未知工具提示将被移除）
      enabledTools.value = {}
      toolValues.value = {}
      const unknownTools: string[] = []
      if (e.type === 'simple_rag') {
        // simple_rag：表字段映射到 rag 工具参数
        const def = ragDef.value
        if (def) {
          const values: Record<string, any> = {}
          for (const p of def.params) {
            const v = (e as any)[p.key]
            if (v !== undefined && v !== null) values[p.key] = v
            else if (p.default !== undefined) values[p.key] = p.default
            else if (p.type === 'boolean') values[p.key] = false
          }
          toolValues.value['rag'] = values
        }
      } else {
        for (const t of e.tools || []) {
          const def = toolDefs.value.find(d => d.type === t.type)
          if (!def) {
            unknownTools.push(t.type)
            continue
          }
          enabledTools.value[def.type] = true
          const values: Record<string, any> = {}
          for (const p of def.params) {
            const v = (t as any)[p.key]
            if (v !== undefined && v !== null) values[p.key] = v
            else if (p.default !== undefined) values[p.key] = p.default
            else if (p.type === 'boolean') values[p.key] = false
          }
          toolValues.value[def.type] = values
        }
      }
      if (unknownTools.length) {
        message.warning(`工具已不存在，保存后将移除：${unknownTools.join(', ')}`)
      }
    } else {
      formData.value = {
        type: 'simple_rag', name: '', description: '', llm_config_id: '',
        summary_llm_config_id: '',
        temperature: null, top_p: null, max_tokens: null, welcome_message: '',
        system_prompt: defaults.value.system_prompt || '',
        enhance_llm_config_id: '', rerank_config_id: '',
        intent_routing: false, plan_enabled: true, reflect_enabled: true,
      }
      intentRules.value = toEditableRules(
        DEFAULT_INTENT_RULE_TEMPLATE.map(r => ({ ...r })),
      )
      enabledTools.value = {}
      toolValues.value = {}
      // 新建默认 simple_rag：初始化 rag 工具默认参数（ToolParamForm 也有 default 兑底）
      if (ragDef.value) {
        initToolValues(ragDef.value)
      }
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
    // rag 工具参数 → 表字段映射（kb_id 必填校验）
    const values = toolValues.value['rag'] || {}
    if (!values.kb_id) {
      message.error('请选择绑定的知识库')
      return
    }
    payload.kb_id = values.kb_id
    payload.top_k = values.top_k ?? null
    payload.score_threshold = values.score_threshold ?? null
    payload.mqe_enabled = values.mqe_enabled ?? false
    payload.hyde_enabled = values.hyde_enabled ?? false
    payload.mqe_query_count = values.mqe_query_count ?? 3
    payload.rerank_enabled = values.rerank_enabled ?? false
  } else {
    // Schema 驱动组装：仅提交启用的工具（含必填参数校验）
    const tools: ToolConfig[] = []
    for (const def of toolDefs.value) {
      if (!enabledTools.value[def.type]) continue
      const values = toolValues.value[def.type] || {}
      for (const p of def.params) {
        if (p.required && (values[p.key] === undefined || values[p.key] === null || values[p.key] === '')) {
          message.error(`工具「${def.type}」参数「${p.label}」为必填项`)
          return
        }
      }
      tools.push({ type: def.type, ...values } as ToolConfig)
    }
    payload.tools = tools
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

<style scoped>
/* ── Phase 4.10：意图规则编辑器排版 ── */
.intent-rule-card {
  border: 1px solid rgba(128, 128, 128, 0.2);
  border-radius: 6px;
  padding: 8px 10px;
  margin-bottom: 10px;
  background: rgba(128, 128, 128, 0.04);
}
.intent-rule-row {
  display: flex;
  gap: 8px;
  align-items: center;
}
.intent-rule-row + .intent-rule-row {
  margin-top: 8px;
}
.intent-rule-idx {
  width: 20px;
  flex-shrink: 0;
  text-align: center;
  color: #999;
  font-size: 12px;
  font-weight: 600;
}
.intent-rule-hint {
  flex-shrink: 0;
  font-size: 12px;
  color: #888;
}
.cond-label {
  flex-shrink: 0;
  width: 30px;
  font-size: 12px;
  color: #888;
}
.cond-hint {
  flex-shrink: 0;
  font-size: 12px;
  color: #aaa;
}
/* ── Phase 4.10：工具配置区（Schema 驱动动态表单）── */
.tool-config-area {
  width: 100%;
}
.tool-card {
  border: 1px solid rgba(128, 128, 128, 0.2);
  border-radius: 6px;
  padding: 10px 12px;
  margin-bottom: 10px;
  background: rgba(128, 128, 128, 0.04);
}
.tool-card-head {
  display: flex;
  gap: 10px;
  align-items: center;
}
.tool-card-name {
  font-weight: 600;
  font-size: 13px;
  flex-shrink: 0;
}
.tool-card-desc {
  color: #888;
  font-size: 12px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.tool-card-params {
  margin-top: 10px;
  padding-top: 10px;
  border-top: 1px dashed rgba(128, 128, 128, 0.25);
}
</style>
