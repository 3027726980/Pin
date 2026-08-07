<template>
  <div class="page">
    <div class="page-header">
      <h2>模型配置</h2>
      <n-button type="primary" @click="openCreate">
        <template #icon><n-icon><AddOutline /></n-icon></template>
        添加配置
      </n-button>
    </div>

    <!-- 可选模型列表 -->
    <n-card title="可选模型" size="small" class="info-card">
      <n-data-table
        :columns="defaultColumns"
        :data="defaultModels"
        :pagination="false"
        :row-key="(row: DefaultModelConfigItem) => row.id"
        size="small"
      />
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
          <n-select
            v-model:value="form.provider"
            :options="providerOptions"
            placeholder="选择厂商"
            @update:value="onProviderChange"
          />
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
            :options="filteredModelOptions"
            placeholder="选择模型"
            @update:value="onModelChange"
          />
        </n-form-item>
        <n-form-item v-if="form.provider && form.provider !== 'local'" label="接口地址">
          <n-input v-model:value="form.base_url" placeholder="留空使用默认地址" />
        </n-form-item>
        <n-form-item v-if="form.provider && form.provider !== 'local'" label="API Key" path="api_key">
          <n-input v-model:value="form.api_key" type="password" show-password-on="click" placeholder="请输入 API Key" />
        </n-form-item>
        <n-form-item v-if="form.dimension" label="向量维度">
          <n-input :value="String(form.dimension)" disabled />
        </n-form-item>
      </n-form>
      <template #footer>
        <n-space justify="end">
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
  { title: '厂商', key: 'provider', width: 100 },
  {
    title: '类别', key: 'model_type', width: 200,
    render(row) {
      const found = modelTypes.value.find(t => t.code === row.model_type)
      return found?.name || `类型${row.model_type}`
    },
  },
  { title: '模型', key: 'model_name', ellipsis: { tooltip: true } },
]

// ── 我的配置表格 ──────────────────────
const configColumns: DataTableColumns<UserModelConfigItem> = [
  { title: '厂商', key: 'provider', width: 70 },
  { title: '模型', key: 'model_name', width: 160, ellipsis: { tooltip: true } },
  {
    title: '类别', key: 'model_type', width: 140,
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
    title: '操作', key: 'actions', width: 120,
    render(row) {
      return h(NSpace, null, {
        default: () => [
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

const form = ref({
  provider: '',
  model_name: '',
  model_type: 1,
  base_url: '' as string | null,
  api_key: '' as string | null,
  dimension: null as number | null,
})

const rules: FormRules = {
  provider: { required: true, message: '请选择厂商', trigger: 'change' },
  model_name: { required: true, message: '请选择模型', trigger: 'change' },
  api_key: {
    message: '请输入 API Key',
    trigger: 'blur',
    validator: (_rule, value: string | null) => {
      if (form.value.provider === 'local') return true
      if (!value) return new Error('请输入 API Key')
      return true
    },
  },
}

// ── 厂商选项（去重）───────────────────
const providerOptions = computed<SelectOption[]>(() => {
  const seen = new Set<string>()
  return defaultModels.value
    .filter(m => { const dup = seen.has(m.provider); seen.add(m.provider); return !dup })
    .map(m => ({ label: m.provider, value: m.provider }))
})

// ── 模型类型标签 ────────────────────
const modelTypes = ref<ModelTypeItem[]>([])
const modelTypeLabel = computed(() => {
  const found = modelTypes.value.find(t => t.code === form.value.model_type)
  return found?.name || `未知 (${form.value.model_type})`
})

// ── 根据选中厂商过滤可选类型 ──────────
const typeOptions = computed<SelectOption[]>(() => {
  const seen = new Set<number>()
  return defaultModels.value
    .filter(m => m.provider === form.value.provider)
    .filter(m => { const dup = seen.has(m.model_type); seen.add(m.model_type); return !dup })
    .map(m => {
      const found = modelTypes.value.find(t => t.code === m.model_type)
      return { label: found?.name || `类型${m.model_type}`, value: m.model_type }
    })
})

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

// ── 厂商变更：默认选第一个类型 ──
function onProviderChange(_provider: string) {
  form.value.model_name = ''
  form.value.base_url = null
  form.value.dimension = null

  const types = defaultModels.value
    .filter(m => m.provider === form.value.provider)
    .map(m => m.model_type)
    .filter((v, i, a) => a.indexOf(v) === i)
  form.value.model_type = types.length > 0 ? types[0] : 0
  if (form.value.model_type > 0) onTypeChange(form.value.model_type)
}

// ── 类型变更：默认选第一个模型 ──
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
  form.value = { provider: '', model_name: '', model_type: 0, base_url: null, api_key: null, dimension: null }
  modalShow.value = true
}

function openEdit(row: UserModelConfigItem) {
  editingId.value = row.id
  modalTitle.value = '编辑配置'
  form.value = {
    provider: row.provider,
    model_name: row.model_name,
    model_type: row.model_type,
    base_url: row.base_url,
    api_key: row.api_key,
    dimension: row.dimension,
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
</style>
