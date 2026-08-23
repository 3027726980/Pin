<template>
  <div class="page">
    <div class="page-header">
      <h2>模型配置</h2>
      <n-button type="primary" @click="openCreate">
        <template #icon><n-icon><AddOutline /></n-icon></template>
        添加配置
      </n-button>
    </div>

    <!-- 可选模型列表（按类型分组） -->
    <n-card title="可选模型" size="small" class="info-card">
      <template #header-extra>
        <span style="font-size: 12px; color: #999">由 config.yaml 定义，启动时同步；自定义模型请在下方手动创建</span>
      </template>
      <div v-for="group in groupedDefaults" :key="group.model_type" class="model-group">
        <div class="model-group-title">{{ group.name }}（{{ group.items.length }}）</div>
        <n-data-table
          :columns="defaultColumns"
          :data="group.items"
          :pagination="false"
          :row-key="(row: DefaultModelConfigItem) => row.id"
          size="small"
        />
      </div>
      <n-empty v-if="groupedDefaults.length === 0" description="暂无预置模型（config.yaml 未配置）" style="padding: 16px 0" />
    </n-card>

    <!-- 我的配置 -->
    <n-card title="我的配置" class="config-card">
      <n-data-table
        :columns="configColumns"
        :data="myConfigs"
        :pagination="false"
        :row-key="(row: UserModelConfigItem) => row.id"
      >
        <template #empty>
          <n-empty description="暂无配置，从上方可选模型中选择并添加" />
        </template>
      </n-data-table>
    </n-card>

    <!-- 创建/编辑弹窗 -->
    <n-modal v-model:show="modalShow" :title="modalTitle" preset="card" style="width: 520px" :mask-closable="false">
      <n-form ref="formRef" :model="form" :rules="rules" label-placement="left" label-width="100">
        <n-form-item label="厂商" path="provider">
          <n-space align="center" style="width: 100%">
            <template v-if="providerMode === 'preset'">
              <n-select
                v-model:value="form.provider"
                :options="providerOptions"
                placeholder="选择预置厂商"
                filterable
                style="flex: 1"
                @update:value="onProviderChange"
              />
              <n-button text type="primary" @click="switchToCustom">✏️ 自定义厂商</n-button>
            </template>
            <template v-else>
              <n-input
                v-model:value="form.provider"
                placeholder="输入厂商名，如 openrouter"
                style="flex: 1"
              />
              <n-button text @click="switchToPreset">使用预置</n-button>
            </template>
          </n-space>
          <template #feedback>预置厂商由 config.yaml 定义；自定义厂商需填写接口地址</template>
        </n-form-item>
        <n-form-item v-if="form.provider" label="模型类型" path="model_type">
          <n-select
            v-model:value="form.model_type"
            :options="typeOptions"
            placeholder="选择类型"
            @update:value="onTypeChange"
          />
        </n-form-item>
        <n-form-item v-if="form.provider" label="模型" path="model_name">
          <template v-if="providerMode === 'preset'">
            <n-select
              v-model:value="form.model_name"
              :options="filteredModelOptions"
              placeholder="选择模型"
              filterable
              style="width: 100%"
              @update:value="onModelChange"
            />
          </template>
          <template v-else>
            <n-input
              v-model:value="form.model_name"
              placeholder="输入模型名，如 gpt-4o"
              style="width: 100%"
            />
          </template>
        </n-form-item>
        <!-- 调用模式：仅自定义厂商可选（目前仅 OpenAI 兼容） -->
        <n-form-item v-if="providerMode === 'custom'" label="调用模式" path="protocol">
          <n-select
            v-model:value="form.protocol"
            :options="protocolOptions"
            placeholder="选择调用模式"
          />
          <template #feedback>目前仅支持 OpenAI 兼容模式；更多模式后续扩展</template>
        </n-form-item>
        <n-form-item v-if="form.provider && form.provider !== 'local'" label="接口地址" path="base_url">
          <n-input v-model:value="form.base_url" placeholder="自定义厂商必填，如 https://api.example.com/v1" />
          <template v-if="isCustomProvider" #feedback>自定义厂商必须填写接口地址</template>
        </n-form-item>
        <n-form-item v-if="form.provider && form.provider !== 'local'" label="API Key" path="api_key" require-mark="true">
          <n-input v-model:value="form.api_key" type="password" show-password-on="click" placeholder="请输入 API Key" />
        </n-form-item>
        <!-- Phase 4.8 采样参数（仅 LLM 类型；模型级默认，Agent 单独设置时以 Agent 为准） -->
        <template v-if="form.model_type === 2">
          <n-form-item label="采样 temperature">
            <n-input-number v-model:value="form.temperature" :min="0" :max="2" :step="0.1" style="width: 100%" placeholder="默认 0.7" />
          </n-form-item>
          <n-form-item label="采样 top_p">
            <n-input-number v-model:value="form.top_p" :min="0" :max="1" :step="0.05" style="width: 100%" placeholder="默认 0.9" />
          </n-form-item>
          <n-form-item label="最大 tokens">
            <n-input-number v-model:value="form.max_tokens" :min="1" :max="1000000" style="width: 100%" placeholder="厂商默认" />
          </n-form-item>
          <n-alert type="info" :show-icon="false" style="margin-bottom: 12px">
            采样参数为<b>模型级默认值</b>：Agent 单独设置采样参数时以 Agent 为准；均未设置时用此处的值。
          </n-alert>
        </template>
        <n-form-item v-if="form.provider && form.model_type === 1" label="向量维度">
          <n-input-number v-model:value="form.dimension" :min="1" :max="4096" style="width: 100%" placeholder="预置自动带出；自定义模型建议填写" />
        </n-form-item>
      </n-form>
      <template #footer>
        <n-space justify="end">
          <n-button :loading="formTesting" @click="handleTestForm">测试连接</n-button>
          <n-button @click="modalShow = false">取消</n-button>
          <n-button type="primary" :loading="submitting" @click="handleSubmit">确定</n-button>
        </n-space>
      </template>
    </n-modal>
  </div>
</template>

<script setup lang="ts">
import { h, ref, computed, onMounted } from 'vue'
import { NButton, NTag, NPopconfirm, NSpace, NIcon, NSwitch } from 'naive-ui'
import { AddOutline, CreateOutline, TrashOutline } from '@vicons/ionicons5'
import type { FormInst, FormRules, DataTableColumns, SelectOption } from 'naive-ui'
import {
  listDefaultModels,
  listMyConfigs,
  listModelTypes,
  createModelConfig,
  updateModelConfig,
  deleteModelConfig,
  testModelConfig,
  type DefaultModelConfigItem,
  type UserModelConfigItem,
  type ModelTypeItem,
} from '@/api/model-config'

const message = useMessage()

// ── 数据 ────────────────────────────
const defaultModels = ref<DefaultModelConfigItem[]>([])
const myConfigs = ref<UserModelConfigItem[]>([])

// ── 默认模型表格 ──────────────────────
const defaultColumns: DataTableColumns<DefaultModelConfigItem> = [
  { title: '厂商', key: 'provider', width: 120 },
  {
    title: '类别', key: 'model_type', width: 240,
    render(row) {
      const found = modelTypes.value.find(t => t.code === row.model_type)
      return found?.name || `类型${row.model_type}`
    },
  },
  { title: '模型', key: 'model_name', width: 260, ellipsis: { tooltip: true } },
]

// ── 我的配置表格 ──────────────────────
const configColumns: DataTableColumns<UserModelConfigItem> = [
  { title: '厂商', key: 'provider', width: 120 },
  { title: '模型', key: 'model_name', width: 260, ellipsis: { tooltip: true } },
  {
    title: '类别', key: 'model_type', width: 240,
    render(row) {
      const found = modelTypes.value.find(t => t.code === row.model_type)
      return found?.name || `类型${row.model_type}`
    },
  },
  {
    title: '启用', key: 'is_active', width: 70,
    render(row) {
      return h(NSwitch, {
        value: row.is_active,
        onUpdateValue: (val: boolean) => toggleActive(row.id, val),
      })
    },
  },
  {
    title: '操作', key: 'actions', width: 200,
    render(row) {
      return h(NSpace, null, {
        default: () => [
          h(NButton, {
            size: 'small', quaternary: true, type: 'info',
            loading: testingId.value === row.id,
            onClick: () => handleTest(row),
          }, { default: () => '测试' }),
          h(NButton, { size: 'small', quaternary: true, onClick: () => openEdit(row) },
            { icon: () => h(NIcon, null, { default: () => h(CreateOutline) }) }),
          h(NPopconfirm, { onPositiveClick: () => handleDelete(row.id) }, {
            trigger: () => h(NButton, { size: 'small', quaternary: true, type: 'error' },
              { icon: () => h(NIcon, null, { default: () => h(TrashOutline) }) }),
            default: () => '确定删除此配置？',
          }),
        ],
      })
    },
  },
]

// ── 弹窗表单 ──────────────────────────
const formRef = ref<FormInst>()
const modalShow = ref(false)
const submitting = ref(false)
const editingId = ref<string | null>(null)
const modalTitle = ref('添加配置')
// 测试连接状态
const testingId = ref<string | null>(null)
const formTesting = ref(false)

const form = ref({
  provider: '',
  model_name: '',
  model_type: 1,
  base_url: '' as string | null,
  api_key: '' as string | null,
  dimension: null as number | null,
  protocol: 'openai' as string | null,
  temperature: null as number | null,
  top_p: null as number | null,
  max_tokens: null as number | null,
})

// 调用模式选项（协议）：目前仅 OpenAI 兼容；新增模式 = 注册实现 + 这里加一项
const protocolOptions: SelectOption[] = [
  { label: 'OpenAI（兼容）', value: 'openai' },
]

// 厂商选择方式：preset=预置下拉 / custom=自定义输入（显式切换，避免看不出可输入）
const providerMode = ref<'preset' | 'custom'>('preset')

function switchToCustom() {
  providerMode.value = 'custom'
  form.value.provider = ''
  form.value.model_name = ''
  form.value.base_url = null
  form.value.dimension = null
  form.value.protocol = 'openai'
}

function switchToPreset() {
  providerMode.value = 'preset'
  form.value.provider = ''
  form.value.model_name = ''
  form.value.base_url = null
  form.value.dimension = null
  form.value.protocol = null  // 预置厂商协议由 config.yaml 推断，不落库
}

const rules: FormRules = {
  provider: { required: true, message: '请选择或输入厂商', trigger: 'change' },
  model_name: { required: true, message: '请选择或输入模型', trigger: 'change' },
  api_key: {
    message: '请输入 API Key',
    trigger: 'blur',
    validator: (_rule, value: string | null) => {
      if (form.value.provider === 'local') return true
      if (!value) return new Error('请输入 API Key')
      return true
    },
  },
  base_url: {
    message: '自定义厂商必须填写接口地址',
    trigger: 'blur',
    validator: (_rule, value: string | null) => {
      if (providerMode.value !== 'custom') return true
      if (!value) return new Error('自定义厂商必须填写接口地址')
      return true
    },
  },
}

// ── 厂商选项（仅预置厂商，去重；自定义走输入模式）──
const providerOptions = computed<SelectOption[]>(() => {
  const seen = new Set<string>()
  return defaultModels.value
    .filter(m => { const dup = seen.has(m.provider); seen.add(m.provider); return !dup })
    .map(m => ({ label: m.provider, value: m.provider }))
})

// ── 自定义厂商判定（自定义输入模式）───
const isCustomProvider = computed(() => providerMode.value === 'custom')

// ── 可选模型按类型分组（Embedding / LLM / Rerank）──
const groupedDefaults = computed(() => {
  const groups: { model_type: number; name: string; items: DefaultModelConfigItem[] }[] = []
  for (const t of modelTypes.value) {
    const items = defaultModels.value.filter(m => m.model_type === t.code)
    if (items.length) groups.push({ model_type: t.code, name: t.name, items })
  }
  return groups
})

// ── 模型类型标签 ────────────────────
const modelTypes = ref<ModelTypeItem[]>([])
const modelTypeLabel = computed(() => {
  const found = modelTypes.value.find(t => t.code === form.value.model_type)
  return found?.name || `未知 (${form.value.model_type})`
})

// ── 类型选项：始终展示全部类型（自定义厂商也能选类型）──
const typeOptions = computed<SelectOption[]>(() =>
  modelTypes.value.map(t => ({ label: t.name, value: t.code })),
)

// ── 根据选中厂商+类型过滤模型 ──────────
const filteredModelOptions = computed<SelectOption[]>(() => {
  return defaultModels.value
    .filter(m => m.provider === form.value.provider && m.model_type === form.value.model_type)
    .map(m => ({ label: m.model_name, value: m.model_name }))
})

// ── 根据厂商+模型查找默认配置 ──────────
function findDefault(provider: string, modelName: string): DefaultModelConfigItem | undefined {
  return defaultModels.value.find(m => m.provider === provider && m.model_name === modelName)
}

// ── 厂商变更：预置厂商默认选第一个类型；自定义厂商保持类型供手输模型 ──
function onProviderChange(_provider: string) {
  form.value.model_name = ''
  form.value.base_url = null
  form.value.dimension = null

  const types = defaultModels.value
    .filter(m => m.provider === form.value.provider)
    .map(m => m.model_type)
    .filter((v, i, a) => a.indexOf(v) === i)
  if (types.length > 0) {
    form.value.model_type = types[0]
    onTypeChange(form.value.model_type)
  } else {
    // 自定义厂商：类型保持（默认 1 Embedding），模型名等待手输
    if (!form.value.model_type) form.value.model_type = 1
  }
}

// ── 类型变更：预置模型自动带出；自定义则等待手输 ──
function onTypeChange(typeCode: number) {
  form.value.model_name = ''
  form.value.base_url = null
  form.value.dimension = null

  const models = defaultModels.value.filter(
    m => m.provider === form.value.provider && m.model_type === typeCode
  )
  if (models.length > 0) {
    form.value.model_name = models[0].model_name
    form.value.base_url = models[0].base_url
    form.value.dimension = models[0].dimension
  }
}

// ── 模型变更：自动填入 base_url / dimension ──
function onModelChange(modelName: string) {
  const def = findDefault(form.value.provider, modelName)
  if (def) {
    form.value.base_url = def.base_url
    form.value.model_type = def.model_type
    form.value.dimension = def.dimension
  }
}

// ── 获取数据 ──────────────────────────
async function fetchDefaults() {
  try { defaultModels.value = await listDefaultModels() } catch { /* */ }
}

async function fetchMyConfigs() {
  try { myConfigs.value = await listMyConfigs() } catch { /* */ }
}

// ── 创建 ────────────────────────────
function openCreate() {
  editingId.value = null
  modalTitle.value = '添加配置'
  providerMode.value = 'preset'
  form.value = {
    provider: '', model_name: '', model_type: 1, base_url: null, api_key: null,
    dimension: null, protocol: null, temperature: null, top_p: null, max_tokens: null,
  }
  modalShow.value = true
}

function openEdit(row: UserModelConfigItem) {
  editingId.value = row.id
  modalTitle.value = '编辑配置'
  // 编辑回显：预置厂商用下拉，自定义厂商自动切输入模式
  providerMode.value = defaultModels.value.some(m => m.provider === row.provider)
    ? 'preset'
    : 'custom'
  form.value = {
    provider: row.provider,
    model_name: row.model_name,
    model_type: row.model_type,
    base_url: row.base_url,
    api_key: row.api_key,
    dimension: row.dimension,
    protocol: row.protocol || (providerMode.value === 'custom' ? 'openai' : null),
    temperature: row.temperature,
    top_p: row.top_p,
    max_tokens: row.max_tokens,
  }
  modalShow.value = true
}

async function handleSubmit() {
  try { await formRef.value?.validate() } catch { return }
  submitting.value = true
  try {
    if (editingId.value) {
      await updateModelConfig(editingId.value, {
        provider: form.value.provider,
        model_name: form.value.model_name,
        model_type: form.value.model_type,
        base_url: form.value.base_url,
        api_key: form.value.api_key,
        dimension: form.value.dimension,
        protocol: providerMode.value === 'custom' ? form.value.protocol : null,
        temperature: form.value.temperature,
        top_p: form.value.top_p,
        max_tokens: form.value.max_tokens,
      })
      message.success('已更新')
    } else {
      await createModelConfig({
        provider: form.value.provider,
        model_name: form.value.model_name,
        model_type: form.value.model_type,
        base_url: form.value.base_url,
        api_key: form.value.api_key,
        dimension: form.value.dimension,
        protocol: providerMode.value === 'custom' ? form.value.protocol : null,
        temperature: form.value.temperature,
        top_p: form.value.top_p,
        max_tokens: form.value.max_tokens,
      })
      message.success('已添加')
    }
    modalShow.value = false
    fetchMyConfigs()
  } catch (e) {
    message.error((e as Error).message || '操作失败')
  } finally {
    submitting.value = false
  }
}

async function handleTest(row: UserModelConfigItem) {
  // 列表：用该行完整参数测试连通性
  testingId.value = row.id
  try {
    const r = await testModelConfig({
      provider: row.provider,
      model_name: row.model_name,
      model_type: row.model_type,
      base_url: row.base_url,
      api_key: row.api_key || undefined,
      dimension: row.dimension,
      protocol: row.protocol || undefined,
      temperature: row.temperature,
      top_p: row.top_p,
      max_tokens: row.max_tokens,
    })
    if (r.ok) {
      message.success(`✅ ${r.detail}（${r.latency_ms}ms）`)
    } else {
      message.error(`❌ ${r.detail}`, { duration: 8000 })
    }
  } catch (e) {
    message.error((e as Error).message || '测试失败')
  } finally {
    testingId.value = null
  }
}

async function handleTestForm() {
  // 弹窗：用表单当前值测试（未保存也能测）
  try {
    await formRef.value?.validate()
  } catch {
    return
  }
  formTesting.value = true
  try {
    const r = await testModelConfig({
      provider: form.value.provider,
      model_name: form.value.model_name,
      model_type: form.value.model_type,
      base_url: form.value.base_url,
      api_key: form.value.api_key,
      dimension: form.value.dimension,
      protocol: providerMode.value === 'custom' ? form.value.protocol : null,
      temperature: form.value.temperature,
      top_p: form.value.top_p,
      max_tokens: form.value.max_tokens,
    })
    if (r.ok) {
      message.success(`✅ ${r.detail}（${r.latency_ms}ms）`)
    } else {
      message.error(`❌ ${r.detail}`, { duration: 8000 })
    }
  } catch (e) {
    message.error((e as Error).message || '测试失败')
  } finally {
    formTesting.value = false
  }
}

async function toggleActive(id: string, val: boolean) {
  const item = myConfigs.value.find(c => c.id === id)
  if (!item) return
  const oldVal = item.is_active
  item.is_active = val
  try {
    await updateModelConfig(id, { is_active: val })
    message.success(val ? '已启用' : '已禁用')
  } catch (e) {
    item.is_active = oldVal
    message.error((e as Error).message || '操作失败')
  }
}

async function handleDelete(id: string) {
  try {
    await deleteModelConfig(id)
    message.success('已删除')
    fetchMyConfigs()
  } catch (e) {
    message.error((e as Error).message || '删除失败')
  }
}

onMounted(() => {
  fetchDefaults()
  fetchMyConfigs()
  listModelTypes().then(list => { modelTypes.value = list }).catch(() => {})
})
</script>

<style scoped>
.page-header {
  display: flex; justify-content: space-between; align-items: center;
  margin-bottom: 16px;
}
.page-header h2 { margin: 0; font-size: 20px; }
.info-card { margin-bottom: 16px; }
.model-group { margin-bottom: 12px; }
.model-group:last-child { margin-bottom: 0; }
.model-group-title {
  font-size: 13px; font-weight: 600;
  margin-bottom: 4px; color: #666;
}
</style>
