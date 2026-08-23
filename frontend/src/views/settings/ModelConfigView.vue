<template>
  <div class="page">
    <div class="page-header">
      <h2>模型配置</h2>
      <n-space>
        <n-button @click="openProviderCreate">
          <template #icon><n-icon><AddOutline /></n-icon></template>
          添加厂商
        </n-button>
        <n-button type="primary" @click="openModelCreate">
          <template #icon><n-icon><AddOutline /></n-icon></template>
          添加模型
        </n-button>
      </n-space>
    </div>

    <!-- ── 厂商卡片 ─────────────────────── -->
    <n-card title="厂商" size="small" class="section-card">
      <template #header-extra>
        <span style="font-size: 12px; color: #999">预置由 config.yaml 定义；自定义可直接添加，效果等同预置</span>
      </template>
      <n-grid cols="1 s:2 m:3 l:4" :x-gap="12" :y-gap="12" responsive="screen">
        <n-gi v-for="p in providers" :key="p.id || p.name">
          <n-card size="small" class="provider-card" :bordered="true">
            <div class="card-name">{{ p.name }}</div>
            <n-space size="small" style="margin: 6px 0">
              <n-tag size="small" :type="p.source === 'custom' ? 'info' : 'default'" :bordered="false">
                {{ p.source === 'custom' ? '自定义' : '预置' }}
              </n-tag>
              <n-tag size="small" :bordered="false">{{ p.protocol }}</n-tag>
            </n-space>
            <div class="card-desc">{{ p.description || `${p.model_count} 个模型配置` }}</div>
            <template v-if="p.source === 'custom'" #footer>
              <n-space justify="end" style="margin-top: 4px">
                <n-button size="tiny" quaternary @click="openProviderEdit(p)">编辑</n-button>
                <n-popconfirm @positive-click="handleProviderDelete(p.id!)">
                  <template #trigger>
                    <n-button size="tiny" quaternary type="error">删除</n-button>
                  </template>
                  删除后已有配置保留，但不可新建该厂商配置。确定删除？
                </n-popconfirm>
              </n-space>
            </template>
          </n-card>
        </n-gi>
      </n-grid>
      <n-empty v-if="providers.length === 0" description="暂无厂商" style="padding: 16px 0" />
    </n-card>

    <!-- ── 我的模型卡片 ─────────────────── -->
    <n-card title="我的模型" size="small" class="section-card">
      <n-grid cols="1 s:2 m:3 l:4" :x-gap="12" :y-gap="12" responsive="screen">
        <n-gi v-for="m in myConfigs" :key="m.id">
          <n-card size="small" class="model-card">
            <div class="card-name">{{ m.model_name }}</div>
            <n-space size="small" align="center" style="margin: 6px 0">
              <span class="model-provider">{{ m.provider }}</span>
              <n-tag size="small" :bordered="false" :type="typeTagType(m.model_type)">
                {{ typeLabel(m.model_type) }}
              </n-tag>
              <n-switch size="small" :value="m.is_active" @update:value="(v: boolean) => toggleActive(m.id, v)" />
            </n-space>
            <div class="card-desc">
              采样 {{ m.temperature ?? '默认' }} / {{ m.top_p ?? '默认' }} / max {{ m.max_tokens ?? '厂商默认' }}
            </div>
            <template #footer>
              <n-space justify="end" style="margin-top: 4px">
                <n-button size="tiny" quaternary type="info" :loading="testingId === m.id" @click="handleTest(m)">
                  测试
                </n-button>
                <n-button size="tiny" quaternary @click="openModelEdit(m)">编辑</n-button>
                <n-popconfirm @positive-click="handleDelete(m.id)">
                  <template #trigger>
                    <n-button size="tiny" quaternary type="error">删除</n-button>
                  </template>
                  确定删除此配置？
                </n-popconfirm>
              </n-space>
            </template>
          </n-card>
        </n-gi>
      </n-grid>
      <n-empty v-if="myConfigs.length === 0" description="暂无模型配置，点击右上角「添加模型」" style="padding: 16px 0" />
    </n-card>

    <!-- ── 模型弹窗 ─────────────────────── -->
    <n-modal v-model:show="modalShow" :title="modalTitle" preset="card" style="width: 520px" :mask-closable="false">
      <n-form ref="formRef" :model="form" :rules="rules" label-placement="left" label-width="100">
        <n-form-item label="厂商" path="provider">
          <n-select
            v-model:value="form.provider"
            :options="providerOptions"
            placeholder="选择支持的厂商"
            filterable
            @update:value="onProviderChange"
          />
          <template #feedback>支持预置（config.yaml）与自定义厂商；没有想要的厂商可先「添加厂商」</template>
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
          <n-select
            v-model:value="form.model_name"
            :options="modelNameOptions"
            placeholder="选择预置模型，或输入新模型名"
            filterable
            tag
            @update:value="onModelNameChange"
          />
          <template #feedback>可直接选择厂商预置模型，也可输入自定义模型名</template>
        </n-form-item>
        <n-form-item v-if="form.provider" label="调用模式" path="protocol">
          <n-select v-model:value="form.protocol" :options="protocolTypeOptions" placeholder="选择调用方式" />
          <template #feedback>OpenAI 兼容（/chat/completions、/embeddings）或 DashScope 原生（/services/...）；按模型实际接入方式选择</template>
        </n-form-item>
        <n-form-item v-if="form.provider && form.provider !== 'local'" label="接口地址" path="base_url">
          <n-input v-model:value="form.base_url" placeholder="预置厂商可留空用默认；自定义厂商必填" />
          <template v-if="isCustomProvider" #feedback>自定义厂商必须填写接口地址</template>
        </n-form-item>
        <n-form-item v-if="form.provider && form.provider !== 'local'" label="API Key" path="api_key" require-mark="true">
          <n-input v-model:value="form.api_key" type="password" show-password-on="click" placeholder="请输入 API Key" />
        </n-form-item>
        <!-- 采样参数（仅已选厂商 + LLM；模型级默认，Agent 单独设置时以 Agent 为准） -->
        <template v-if="form.provider && form.model_type === 2">
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

    <!-- ── 厂商弹窗 ─────────────────────── -->
    <n-modal v-model:show="providerModalShow" :title="providerModalTitle" preset="card" style="width: 420px" :mask-closable="false">
      <n-form ref="providerFormRef" :model="providerForm" :rules="providerRules" label-placement="left" label-width="80">
        <n-form-item label="名称" path="name">
          <n-input v-model:value="providerForm.name" placeholder="如 openrouter / siliconflow" />
        </n-form-item>
        <n-form-item label="调用模式" path="protocol">
          <n-select v-model:value="providerForm.protocol" :options="protocolOptions" />
          <template #feedback>目前仅支持 OpenAI 兼容模式；更多模式后续扩展</template>
        </n-form-item>
        <n-form-item label="接口地址" path="base_url">
          <n-input v-model:value="providerForm.base_url" placeholder="如 https://api.example.com/v1" />
          <template #feedback>添加模型时自动继承，可在模型配置中修改</template>
        </n-form-item>
        <n-form-item label="描述">
          <n-input v-model:value="providerForm.description" placeholder="可选" />
        </n-form-item>
      </n-form>
      <template #footer>
        <n-space justify="end">
          <n-button @click="providerModalShow = false">取消</n-button>
          <n-button type="primary" :loading="providerSubmitting" @click="handleProviderSubmit">确定</n-button>
        </n-space>
      </template>
    </n-modal>
  </div>
</template>

<script setup lang="ts">
import { h, ref, computed, onMounted } from 'vue'
import { NButton, NTag, NPopconfirm, NSpace, NIcon, NSwitch } from 'naive-ui'
import { AddOutline, TrashOutline } from '@vicons/ionicons5'
import type { FormInst, FormRules, SelectOption } from 'naive-ui'
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
import {
  listProviders,
  createProvider,
  updateProvider,
  deleteProvider,
  type ProviderItem,
} from '@/api/providers'

const message = useMessage()

// ── 数据 ────────────────────────────
const defaultModels = ref<DefaultModelConfigItem[]>([])
const myConfigs = ref<UserModelConfigItem[]>([])
const providers = ref<ProviderItem[]>([])

// ── 模型类型 ────────────────────────
const modelTypes = ref<ModelTypeItem[]>([])
const typeLabel = (code: number) => modelTypes.value.find(t => t.code === code)?.name || `类型${code}`
const typeTagType = (code: number): 'success' | 'info' | 'warning' =>
  code === 1 ? 'success' : code === 2 ? 'info' : 'warning'

// ── 厂商 ────────────────────────────
const providerOptions = computed<SelectOption[]>(() =>
  providers.value.map(p => ({
    label: `${p.name}${p.source === 'custom' ? '（自定义）' : ''}`,
    value: p.name,
  })),
)

// 自定义厂商（非预置）→ base_url 必填
const isCustomProvider = computed(() =>
  providers.value.find(p => p.name === form.value.provider)?.source === 'custom',
)

// 调用模式选项（按模型类型过滤：LLM 无 local，Rerank 无 openai）
const protocolTypeOptions = computed<SelectOption[]>(() => {
  const all = [
    { label: 'OpenAI 兼容', value: 'openai' },
    { label: 'DashScope 原生', value: 'dashscope' },
    { label: '本地', value: 'local' },
  ]
  if (form.value.model_type === 1) return all  // Embedding：全部
  if (form.value.model_type === 2) return all.filter(o => o.value !== 'local')  // LLM：无本地
  return all.filter(o => o.value !== 'openai')  // Rerank：无 OpenAI
})

// 选中厂商时带出默认调用模式（aliyun→dashscope / local→local / 其他→openai）
function defaultProtocolFor(providerName: string): string {
  if (providerName === 'aliyun') return 'dashscope'
  if (providerName === 'local') return 'local'
  return 'openai'
}

// ── 模型弹窗 ────────────────────────
const formRef = ref<FormInst>()
const modalShow = ref(false)
const submitting = ref(false)
const editingId = ref<string | null>(null)
const modalTitle = ref('添加模型')
const testingId = ref<string | null>(null)
const formTesting = ref(false)

const form = ref({
  provider: '',
  model_name: '',
  model_type: 1,
  protocol: 'openai' as string | null,
  base_url: '' as string | null,
  api_key: '' as string | null,
  dimension: null as number | null,
  temperature: null as number | null,
  top_p: null as number | null,
  max_tokens: null as number | null,
})

const rules: FormRules = {
  provider: { required: true, message: '请选择厂商', trigger: 'change' },
  model_name: { required: true, message: '请填写模型名', trigger: 'blur' },
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
      if (!isCustomProvider.value) return true
      if (!value) return new Error('自定义厂商必须填写接口地址')
      return true
    },
  },
}

const typeOptions = computed<SelectOption[]>(() =>
  modelTypes.value.map(t => ({ label: t.name, value: t.code })),
)

// 模型名选项：该厂商 + 类型的预置模型（可搜可手输新值）
const modelNameOptions = computed<SelectOption[]>(() =>
  defaultModels.value
    .filter(m => m.provider === form.value.provider && m.model_type === form.value.model_type)
    .map(m => ({ label: m.model_name, value: m.model_name })),
)

// 选中预置模型时自动带出 base_url / dimension；手输新模型名不干预
function onModelNameChange(name: string) {
  const def = defaultModels.value.find(
    m => m.provider === form.value.provider && m.model_name === name)
  if (def) {
    form.value.base_url = def.base_url
    form.value.dimension = def.dimension
  }
}

function onProviderChange(_provider: string) {
  form.value.model_name = ''
  form.value.dimension = null
  // 自定义厂商自动继承厂商 base_url（可修改）；预置厂商留空（选预置模型时带出）
  const p = providers.value.find(x => x.name === form.value.provider)
  form.value.base_url = p?.base_url || null
  // 带出默认调用模式（可修改）
  form.value.protocol = defaultProtocolFor(form.value.provider)
  // 统一默认 LLM 类型（所有厂商行为一致）
  form.value.model_type = 2
  // 自动带出该厂商第一个预置 LLM 模型（无预置则留空手输）
  const preset = defaultModels.value.find(
    m => m.provider === form.value.provider && m.model_type === 2)
  if (preset) {
    form.value.model_name = preset.model_name
    form.value.base_url = preset.base_url || form.value.base_url
    form.value.dimension = preset.dimension
  }
}

function onTypeChange(_typeCode: number) {
  // 仅清空模型名与维度（预置选项随类型变化）；已填的 base_url / api_key 保留
  form.value.model_name = ''
  form.value.dimension = null
  // 调用模式若不在当前类型选项内 → 重置为默认
  const options = protocolTypeOptions.value.map(o => o.value)
  if (form.value.protocol && !options.includes(form.value.protocol)) {
    form.value.protocol = defaultProtocolFor(form.value.provider)
  }
}

// ── 厂商弹窗 ────────────────────────
const providerFormRef = ref<FormInst>()
const providerModalShow = ref(false)
const providerSubmitting = ref(false)
const providerEditingId = ref<string | null>(null)
const providerModalTitle = ref('添加厂商')

const providerForm = ref({
  name: '',
  protocol: 'openai',
  base_url: '',
  description: null as string | null,
})
const protocolOptions: SelectOption[] = [
  { label: 'OpenAI（兼容）', value: 'openai' },
]
const providerRules: FormRules = {
  name: { required: true, message: '请输入厂商名', trigger: 'blur' },
  protocol: { required: true, message: '请选择调用模式', trigger: 'change' },
  base_url: { required: true, message: '请输入接口地址', trigger: 'blur' },
}

function openProviderCreate() {
  providerEditingId.value = null
  providerModalTitle.value = '添加厂商'
  providerForm.value = { name: '', protocol: 'openai', base_url: '', description: null }
  providerModalShow.value = true
}

function openProviderEdit(p: ProviderItem) {
  providerEditingId.value = p.id
  providerModalTitle.value = '编辑厂商'
  providerForm.value = {
    name: p.name, protocol: p.protocol,
    base_url: p.base_url || '', description: p.description,
  }
  providerModalShow.value = true
}

async function handleProviderSubmit() {
  try {
    await providerFormRef.value?.validate()
  } catch {
    return
  }
  providerSubmitting.value = true
  try {
    if (providerEditingId.value) {
      await updateProvider(providerEditingId.value, {
        name: providerForm.value.name,
        protocol: providerForm.value.protocol,
        base_url: providerForm.value.base_url,
        description: providerForm.value.description,
      })
      message.success('厂商已更新')
    } else {
      const p = await createProvider({
        name: providerForm.value.name,
        protocol: providerForm.value.protocol,
        base_url: providerForm.value.base_url,
        description: providerForm.value.description,
      })
      message.success('厂商已添加')
      // 添加后自动选中，方便立即配置模型
      form.value.provider = p.name
      onProviderChange(p.name)
    }
    providerModalShow.value = false
    fetchProviders()
  } catch (e) {
    message.error((e as Error).message || '操作失败')
  } finally {
    providerSubmitting.value = false
  }
}

async function handleProviderDelete(id: string) {
  try {
    await deleteProvider(id)
    message.success('厂商已删除')
    fetchProviders()
  } catch (e) {
    message.error((e as Error).message || '删除失败')
  }
}

// ── 模型弹窗操作 ────────────────────
function openModelCreate() {
  editingId.value = null
  modalTitle.value = '添加模型'
  form.value = {
    provider: '', model_name: '', model_type: 2, protocol: 'openai',
    base_url: null, api_key: null,
    dimension: null, temperature: null, top_p: null, max_tokens: null,
  }
  modalShow.value = true
}

function openModelEdit(row: UserModelConfigItem) {
  editingId.value = row.id
  modalTitle.value = '编辑模型'
  form.value = {
    provider: row.provider,
    model_name: row.model_name,
    model_type: row.model_type,
    protocol: row.protocol || 'openai',
    base_url: row.base_url,
    api_key: row.api_key,
    dimension: row.dimension,
    temperature: row.temperature,
    top_p: row.top_p,
    max_tokens: row.max_tokens,
  }
  modalShow.value = true
}

async function handleSubmit() {
  try {
    await formRef.value?.validate()
  } catch {
    return
  }
  submitting.value = true
  try {
    const payload = {
      provider: form.value.provider,
      model_name: form.value.model_name,
      model_type: form.value.model_type,
      protocol: form.value.protocol,
      base_url: form.value.base_url,
      api_key: form.value.api_key,
      dimension: form.value.dimension,
      temperature: form.value.temperature,
      top_p: form.value.top_p,
      max_tokens: form.value.max_tokens,
    }
    if (editingId.value) {
      await updateModelConfig(editingId.value, payload)
      message.success('已更新')
    } else {
      await createModelConfig(payload)
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

// ── 测试 ────────────────────────────
async function handleTest(row: UserModelConfigItem) {
  testingId.value = row.id
  try {
    const r = await testModelConfig({
      provider: row.provider,
      model_name: row.model_name,
      model_type: row.model_type,
      base_url: row.base_url,
      api_key: row.api_key || undefined,
      dimension: row.dimension,
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

// ── 数据加载 ────────────────────────
async function fetchProviders() {
  try {
    providers.value = await listProviders()
  } catch {
    providers.value = []
  }
}

async function fetchDefaults() {
  try {
    defaultModels.value = await listDefaultModels()
  } catch {
    defaultModels.value = []
  }
}

async function fetchMyConfigs() {
  try {
    myConfigs.value = await listMyConfigs()
  } catch {
    myConfigs.value = []
  }
}

onMounted(() => {
  fetchProviders()
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
.section-card { margin-bottom: 16px; }
.card-name { font-size: 15px; font-weight: 600; word-break: break-all; }
.card-desc {
  font-size: 12px; color: #999;
  overflow: hidden; text-overflow: ellipsis;
  display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical;
}
.model-provider { font-size: 12px; color: #666; }
</style>
