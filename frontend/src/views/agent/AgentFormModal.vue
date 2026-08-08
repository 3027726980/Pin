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

      <!-- simple_rag：知识库直接绑定 -->
      <template v-if="formData.type === 'simple_rag'">
        <n-form-item label="知识库" path="kb_id">
          <n-select v-model:value="formData.kb_id" :options="kbOptions" placeholder="选择绑定的知识库" />
        </n-form-item>
        <n-form-item label="检索块数 top_k">
          <n-input-number v-model:value="formData.top_k" :min="1" :max="50" style="width: 100%" placeholder="默认 5" />
        </n-form-item>
        <n-form-item label="相似度阈值">
          <n-input-number v-model:value="formData.score_threshold" :min="0" :max="1" :step="0.05" style="width: 100%" placeholder="默认 0.3" />
        </n-form-item>
      </template>

      <!-- general：rag 工具注册 -->
      <template v-else>
        <n-form-item label="工具 - 知识库" path="toolKbId">
          <n-select v-model:value="toolKbId" :options="kbOptions" placeholder="rag 工具绑定的知识库" />
        </n-form-item>
        <n-form-item label="工具 - top_k">
          <n-input-number v-model:value="toolTopK" :min="1" :max="50" style="width: 100%" placeholder="默认 5" />
        </n-form-item>
        <n-form-item label="工具 - 相似度阈值">
          <n-input-number v-model:value="toolThreshold" :min="0" :max="1" :step="0.05" style="width: 100%" placeholder="默认 0.3" />
        </n-form-item>
        <n-alert type="info" :show-icon="false" style="margin-bottom: 16px">
          general Agent 由 LLM 自主决定是否调用 rag 工具（知识库检索），可能多轮调用。
        </n-alert>
      </template>

      <n-form-item label="采样 temperature">
        <n-input-number v-model:value="formData.temperature" :min="0" :max="2" :step="0.1" style="width: 100%" placeholder="默认 0.7" />
      </n-form-item>
      <n-form-item label="采样 top_p">
        <n-input-number v-model:value="formData.top_p" :min="0" :max="1" :step="0.05" style="width: 100%" placeholder="默认 0.9" />
      </n-form-item>

      <n-form-item label="欢迎语">
        <n-input v-model:value="formData.welcome_message" placeholder="可选（浮窗展示用）" />
      </n-form-item>

      <n-collapse>
        <n-collapse-item title="系统提示词（默认 RAG 模板）" name="prompt">
          <n-input v-model:value="formData.system_prompt" type="textarea" :autosize="{ minRows: 5, maxRows: 10 }" placeholder="留空使用默认模板" />
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

// ── 表单状态 ────────────────────────────
const formRef = ref<FormInst>()
const submitting = ref(false)

const formData = ref<AgentCreatePayload & { description: string; welcome_message: string; system_prompt: string }>({
  type: 'simple_rag',
  name: '',
  description: '',
  llm_config_id: '',
  kb_id: null,
  top_k: null,
  score_threshold: null,
  temperature: 0.7,
  top_p: 0.9,
  welcome_message: '',
  system_prompt: '',
})

// general 工具配置（独立 state，提交时组装进 tools）
const toolKbId = ref<string | null>(null)
const toolTopK = ref<number | null>(null)
const toolThreshold = ref<number | null>(null)

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
        kb_id: e.kb_id,
        top_k: e.top_k,
        score_threshold: e.score_threshold,
        temperature: e.temperature,
        top_p: e.top_p,
        welcome_message: e.welcome_message || '',
        system_prompt: e.system_prompt || '',
      }
      if (e.type === 'general' && e.tools.length > 0) {
        toolKbId.value = e.tools[0].kb_id
        toolTopK.value = e.tools[0].top_k
        toolThreshold.value = e.tools[0].score_threshold
      }
    } else {
      formData.value = {
        type: 'simple_rag', name: '', description: '', llm_config_id: '',
        kb_id: null, top_k: null, score_threshold: null,
        temperature: 0.7, top_p: 0.9, welcome_message: '',
        system_prompt: defaults.value.system_prompt || '',
      }
      toolKbId.value = null
      toolTopK.value = null
      toolThreshold.value = null
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
    temperature: formData.value.temperature,
    top_p: formData.value.top_p,
    welcome_message: formData.value.welcome_message || null,
    system_prompt: formData.value.system_prompt || null,
  }

  if (formData.value.type === 'simple_rag') {
    payload.kb_id = formData.value.kb_id
    payload.top_k = formData.value.top_k
    payload.score_threshold = formData.value.score_threshold
  } else {
    const tool: ToolConfig = {
      type: 'rag',
      kb_id: toolKbId.value!,
      top_k: toolTopK.value,
      score_threshold: toolThreshold.value,
    }
    payload.tools = [tool]
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
