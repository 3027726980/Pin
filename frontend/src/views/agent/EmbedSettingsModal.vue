<!--
嵌入设置弹窗：API Key 管理 + 治理参数 + 嵌入代码生成器
-->
<template>
  <n-modal
    :show="show"
    preset="card"
    title="嵌入设置"
    style="width: 640px"
    :on-update:show="(v: boolean) => !v && emit('close')"
  >
    <n-tabs type="line" animated>
      <!-- ── 密钥管理 ─────────────────────── -->
      <n-tab-pane name="keys" tab="API Key">
        <div class="key-toolbar">
          <n-input v-model:value="newKeyName" placeholder="备注（如：公司官网客服）" style="width: 220px" size="small" />
          <n-button size="small" type="primary" :loading="creating" @click="handleCreate">
            生成密钥
          </n-button>
        </div>

        <n-alert v-if="plainKey" type="success" title="密钥已生成（仅此一次显示，请立即复制保存）" style="margin: 12px 0">
          <n-code :code="plainKey" word-wrap />
          <n-button size="tiny" type="primary" style="margin-top: 8px" @click="copy(plainKey)">
            复制
          </n-button>
        </n-alert>

        <n-empty v-if="keys.length === 0 && !loading" description="暂无密钥，生成一个即可嵌入使用" size="small" style="margin: 24px 0" />
        <n-data-table
          v-else
          :columns="keyColumns"
          :data="keys"
          :loading="loading"
          size="small"
          :bordered="false"
        />
      </n-tab-pane>

      <!-- ── 治理参数 ─────────────────────── -->
      <n-tab-pane name="policy" tab="访问治理">
        <n-form label-placement="left" label-width="150" :model="policyForm">
          <n-form-item label="限流（次/分钟）">
            <n-input-number v-model:value="policyForm.rate_limit_per_min" :min="1" :max="10000" style="width: 160px" />
            <span class="hint">按 IP + Agent 维度限制公开接口访问频率</span>
          </n-form-item>
          <n-form-item label="域名白名单">
            <n-dynamic-input v-model:value="policyForm.allowed_domains" placeholder="如：example.com" />
            <span class="hint">允许嵌入的域名，留空 = 不限制（每行一个域名，不含协议）</span>
          </n-form-item>
          <n-form-item label="匿名会话保留（天）">
            <n-input-number v-model:value="policyForm.anonymous_retention_days" :min="0" :max="3650" style="width: 160px" />
            <span class="hint">匿名访客会话超过该天数无活动自动清理</span>
          </n-form-item>
          <n-button type="primary" :loading="savingPolicy" @click="handleSavePolicy">
            保存治理参数
          </n-button>
        </n-form>
      </n-tab-pane>

      <!-- ── 嵌入代码 ─────────────────────── -->
      <n-tab-pane name="embed" tab="嵌入代码">
        <n-alert type="info" title="嵌入前请先生成 API Key" v-if="keys.length === 0" style="margin-bottom: 12px" />
        <div class="embed-block">
          <div class="embed-label">① 浮窗 / 移动端（推荐，两行代码）</div>
          <n-input type="textarea" :value="floatCode" readonly :autosize="{ minRows: 3 }" />
          <n-button size="tiny" style="margin-top: 4px" @click="copy(floatCode)">复制</n-button>
        </div>
        <div class="embed-block">
          <div class="embed-label">② 全屏（iframe 方式）</div>
          <n-input type="textarea" :value="fullscreenCode" readonly :autosize="{ minRows: 3 }" />
          <n-button size="tiny" style="margin-top: 4px" @click="copy(fullscreenCode)">复制</n-button>
        </div>
        <div class="embed-block">
          <div class="embed-label">③ 全屏（JS 方式）</div>
          <n-input type="textarea" :value="fullscreenJsCode" readonly :autosize="{ minRows: 3 }" />
          <n-button size="tiny" style="margin-top: 4px" @click="copy(fullscreenJsCode)">复制</n-button>
        </div>
      </n-tab-pane>
    </n-tabs>
  </n-modal>
</template>

<script setup lang="ts">
import { computed, h, onMounted, reactive, ref } from 'vue'
import { NButton, NIcon, NSpace, NSwitch, NTag, useMessage } from 'naive-ui'
import { TrashOutline } from '@vicons/ionicons5'
import {
  createApiKey,
  deleteApiKey,
  listApiKeys,
  updateApiKey,
  type AgentApiKeyItem,
} from '@/api/agentApiKey'
import { getAgent, updateAgent } from '@/api/agent'

const props = defineProps<{ show: boolean; agentId: string }>()
const emit = defineEmits<{ close: [] }>()
const message = useMessage()

// ── 密钥 ─────────────────────────────
const keys = ref<AgentApiKeyItem[]>([])
const loading = ref(false)
const creating = ref(false)
const newKeyName = ref('')
const plainKey = ref('')

const keyColumns = [
  {
    title: '备注',
    key: 'name',
    render: (row: AgentApiKeyItem) => row.name || '—',
  },
  {
    title: '状态',
    key: 'enabled',
    width: 80,
    render: (row: AgentApiKeyItem) =>
      h(NTag, { type: row.enabled === 1 ? 'success' : 'default', size: 'small' }, {
        default: () => (row.enabled === 1 ? '启用' : '禁用'),
      }),
  },
  {
    title: '启用',
    key: 'enabledSwitch',
    width: 60,
    render: (row: AgentApiKeyItem) =>
      h(NSwitch, {
        size: 'small',
        value: row.enabled === 1,
        onUpdateValue: async (v: boolean) => {
          await handleToggle(row, v)
        },
      }),
  },
  {
    title: '最后使用',
    key: 'last_used_at',
    width: 140,
    render: (row: AgentApiKeyItem) => row.last_used_at ? new Date(row.last_used_at).toLocaleString() : '—',
  },
  {
    title: '操作',
    key: 'actions',
    width: 80,
    render: (row: AgentApiKeyItem) =>
      h(NButton, {
        size: 'tiny',
        type: 'error',
        quaternary: true,
        onClick: () => handleDelete(row),
      }, { icon: () => h(NIcon, null, { default: () => h(TrashOutline) }) }),
  },
]

async function loadKeys() {
  loading.value = true
  try {
    keys.value = await listApiKeys(props.agentId)
  } catch (e) {
    message.error((e as Error).message)
  } finally {
    loading.value = false
  }
}

async function handleCreate() {
  creating.value = true
  try {
    const res = await createApiKey(props.agentId, newKeyName.value || undefined)
    plainKey.value = res.api_key
    newKeyName.value = ''
    await loadKeys()
  } catch (e) {
    message.error((e as Error).message)
  } finally {
    creating.value = false
  }
}

async function handleToggle(row: AgentApiKeyItem, enabled: boolean) {
  try {
    await updateApiKey(props.agentId, row.id, { enabled: enabled ? 1 : 0 })
    await loadKeys()
  } catch (e) {
    message.error((e as Error).message)
  }
}

async function handleDelete(row: AgentApiKeyItem) {
  try {
    await deleteApiKey(props.agentId, row.id)
    message.success('密钥已吊销，使用该密钥的嵌入页面立即失效')
    await loadKeys()
  } catch (e) {
    message.error((e as Error).message)
  }
}

// ── 治理参数 ─────────────────────────
const policyForm = reactive({
  rate_limit_per_min: 60,
  allowed_domains: [''],
  anonymous_retention_days: 30,
})
const savingPolicy = ref(false)

async function loadPolicy() {
  try {
    const agent = await getAgent(props.agentId)
    policyForm.rate_limit_per_min = agent.rate_limit_per_min
    policyForm.allowed_domains = agent.allowed_domains.length > 0 ? [...agent.allowed_domains] : ['']
    policyForm.anonymous_retention_days = agent.anonymous_retention_days
  } catch (e) {
    message.error((e as Error).message)
  }
}

async function handleSavePolicy() {
  savingPolicy.value = true
  try {
    const domains = (policyForm.allowed_domains || [])
      .map((d: string) => d.trim())
      .filter(Boolean)
    await updateAgent(props.agentId, {
      rate_limit_per_min: policyForm.rate_limit_per_min,
      allowed_domains: domains,
      anonymous_retention_days: policyForm.anonymous_retention_days,
    })
    message.success('治理参数已保存')
  } catch (e) {
    message.error((e as Error).message)
  } finally {
    savingPolicy.value = false
  }
}

// ── 嵌入代码 ─────────────────────────
const floatCode = computed(() => `<script src="\${location.origin}/widget/widget.js"><\/script>
<script>
  PinWidget.init({
    agentId: '${props.agentId}',
    apiKey: '${plainKey.value || 'YOUR_API_KEY'}',
    mode: 'float', // 'float' | 'mobile' | 'fullscreen'
    theme: { primaryColor: '#2080f0', title: '智能助手' },
  })
<\/script>`)

const fullscreenCode = computed(() => `<iframe src="\${location.origin}/chat/embed/${props.agentId}?api_key=${plainKey.value || 'YOUR_API_KEY'}"
        style="width:100%; height:600px; border:none;"></iframe>`)

const fullscreenJsCode = computed(() => `<script src="\${location.origin}/widget/widget.js"><\/script>
<script>
  PinWidget.init({
    agentId: '${props.agentId}',
    apiKey: '${plainKey.value || 'YOUR_API_KEY'}',
    mode: 'fullscreen',
  })
<\/script>`)

async function copy(text: string) {
  try {
    await navigator.clipboard.writeText(text)
    message.success('已复制')
  } catch {
    message.error('复制失败，请手动选择复制')
  }
}

onMounted(() => {
  loadKeys()
  loadPolicy()
})
</script>

<style scoped>
.key-toolbar {
  display: flex;
  gap: 8px;
  align-items: center;
}
.hint {
  margin-left: 10px;
  font-size: 12px;
  color: #999;
}
.embed-block {
  margin-bottom: 14px;
}
.embed-label {
  font-size: 13px;
  font-weight: 600;
  color: #666;
  margin-bottom: 6px;
}
</style>
