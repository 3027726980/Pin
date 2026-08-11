<!--
嵌入设置弹窗：API Key 管理 + 治理参数 + 嵌入代码生成器
-->
<template>
  <n-modal
    :show="show"
    preset="card"
    title="嵌入设置"
    style="width: 680px"
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
        <n-alert v-if="keys.length === 0" type="info" title="嵌入前请先生成 API Key" style="margin-bottom: 12px" />
        <div class="embed-block">
          <div class="embed-label">API Key（自行填写，用于生成嵌入代码）</div>
          <n-input
            v-model:value="embedApiKey"
            placeholder="粘贴密钥明文 pin_xxx（仅生成时展示过一次）"
            style="margin-bottom: 12px"
          />
          <span class="hint">不填写则代码中显示 YOUR_API_KEY 占位，需自行替换；密钥不落库、不做任何存储</span>
        </div>
        <div class="embed-block">
          <div class="embed-label">Pin 后端地址</div>
          <n-input v-model:value="embedBaseUrl" placeholder="https://pin.example.com" style="margin-bottom: 12px" />
          <span class="hint">widget 请求后端所用的地址（会显式写入嵌入代码）。默认取当前站点；</span>
          <span class="hint">同域部署无需修改；独立部署（前后端不同域名，如开发环境 8000/8001）时改为实际后端地址。</span>
        </div>
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
      </n-tab-pane>
    </n-tabs>
  </n-modal>

  <!-- 密钥生成结果（独立弹窗，关闭后不再显示） -->
  <n-modal
    :show="plainModalVisible"
    preset="card"
    title="密钥已生成"
    style="width: 520px"
    @update:show="(v: boolean) => { if (!v) clearPlain() }"
  >
    <n-alert type="success" title="请立即复制保存，明文只显示这一次！">
      <n-code :code="plainKey" word-wrap />
    </n-alert>
    <div style="margin-top: 12px; display: flex; gap: 8px; justify-content: flex-end">
      <n-button type="primary" @click="copy(plainKey)">复制密钥</n-button>
      <n-button @click="clearPlain">我已保存，关闭</n-button>
    </div>
  </n-modal>

  <!-- 备注编辑弹窗 -->
  <n-modal
    :show="remarkModalVisible"
    preset="card"
    title="修改备注"
    style="width: 420px"
    @update:show="(v: boolean) => { remarkModalVisible = v }"
  >
    <n-input v-model:value="remarkValue" placeholder="如：公司官网客服" @keydown.enter="saveRemark" />
    <div style="margin-top: 12px; display: flex; gap: 8px; justify-content: flex-end">
      <n-button type="primary" :loading="savingRemark" @click="saveRemark">保存</n-button>
      <n-button @click="remarkModalVisible = false">取消</n-button>
    </div>
  </n-modal>
</template>

<script setup lang="ts">
import { computed, h, onMounted, reactive, ref, watch } from 'vue'
import { NButton, NIcon, NSpace, NSwitch, NTag, NInput, useDialog, useMessage } from 'naive-ui'
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
const dialog = useDialog()

// ── 密钥 ─────────────────────────────
const keys = ref<AgentApiKeyItem[]>([])
const loading = ref(false)
const creating = ref(false)
const newKeyName = ref('')
const plainKey = ref('')
const plainKeyId = ref('')
const plainModalVisible = ref(false)
// 备注编辑
const remarkModalVisible = ref(false)
const remarkValue = ref('')
const remarkRowId = ref('')
const savingRemark = ref(false)

/** 明文仅保存在内存（ref），关闭弹窗即清空，不做任何持久化 */
function clearPlain() {
  plainKey.value = ''
  plainKeyId.value = ''
  plainModalVisible.value = false
}

const keyColumns = [
  {
    title: '密钥',
    key: 'key_preview',
    width: 150,
    render: (row: AgentApiKeyItem) => row.key_preview || '—',
  },
  {
    title: '备注',
    key: 'name',
    render: (row: AgentApiKeyItem) =>
      h(
        'span',
        {
          style: 'cursor: pointer; color: #2080f0;',
          title: '点击修改备注',
          onClick: () => handleEditName(row),
        },
        row.name || '点击添加备注',
      ),
  },
  {
    title: '状态',
    key: 'enabled',
    width: 70,
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
    width: 130,
    render: (row: AgentApiKeyItem) => row.last_used_at ? new Date(row.last_used_at).toLocaleString() : '—',
  },
  {
    title: '操作',
    key: 'actions',
    width: 70,
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
    // 明文仅内存展示（独立弹窗），不做任何存储
    plainKey.value = res.api_key
    plainKeyId.value = res.id
    plainModalVisible.value = true
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

async function handleEditName(row: AgentApiKeyItem) {
  remarkRowId.value = row.id
  remarkValue.value = row.name || ''
  remarkModalVisible.value = true
}

async function saveRemark() {
  if (!remarkRowId.value) return
  savingRemark.value = true
  try {
    await updateApiKey(props.agentId, remarkRowId.value, { name: remarkValue.value.trim() || null })
    message.success('备注已更新')
    remarkModalVisible.value = false
    await loadKeys()
  } catch (e) {
    message.error((e as Error).message)
  } finally {
    savingRemark.value = false
  }
}

async function handleDelete(row: AgentApiKeyItem) {
  dialog.warning({
    title: '吊销确认',
    content: `确定吊销密钥「${row.key_preview || row.id}」？使用该密钥的嵌入页面立即失效。`,
    positiveText: '吊销',
    negativeText: '取消',
    onPositiveClick: async () => {
      try {
        await deleteApiKey(props.agentId, row.id)
        message.success('密钥已吊销')
        await loadKeys()
      } catch (e) {
        message.error((e as Error).message)
      }
    },
  })
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
const embedApiKey = ref('')
const embedBaseUrl = ref(location.origin)

function buildBaseUrl(): string {
  return embedBaseUrl.value.replace(/\/$/, '')
}

/** 嵌入代码中的 apiKey：用户自填，留空显示占位 */
function embedKey(): string {
  return embedApiKey.value.trim() || 'YOUR_API_KEY'
}

const floatCode = computed(() => `<script src="${buildBaseUrl()}/widget/widget.js"><\/script>
<script>
  PinWidget.init({
    agentId: '${props.agentId}',
    apiKey: '${embedKey()}',
    baseUrl: '${buildBaseUrl()}',
    mode: 'float', // 'float' | 'mobile' | 'fullscreen'
    theme: { primaryColor: '#2080f0', title: '智能助手' },
  })
<\/script>`)

const fullscreenCode = computed(() => `<iframe src="${buildBaseUrl()}/chat/embed/${props.agentId}?api_key=${embedKey()}"
        style="width:100%; height:600px; border:none;"></iframe>`)

async function copy(text: string) {
  try {
    if (navigator.clipboard && window.isSecureContext) {
      await navigator.clipboard.writeText(text)
    } else {
      // 非安全上下文（http）fallback
      const ta = document.createElement('textarea')
      ta.value = text
      ta.style.position = 'fixed'
      ta.style.opacity = '0'
      document.body.appendChild(ta)
      ta.select()
      document.execCommand('copy')
      document.body.removeChild(ta)
    }
    // 复制不中断：含占位符时警告提示，不含则正常成功提示
    if (text.includes('YOUR_API_KEY')) {
      message.warning('已复制（含 YOUR_API_KEY 占位符，请替换为真实密钥后再使用）')
    } else {
      message.success('已复制到剪贴板')
    }
  } catch {
    message.error('复制失败，请手动选择复制')
  }
}

watch(() => props.show, (v) => {
  if (v) {
    loadKeys()
    loadPolicy()
  }
})

onMounted(() => {
  if (props.show) {
    loadKeys()
    loadPolicy()
  }
})
</script>

<style scoped>
.key-toolbar {
  display: flex;
  gap: 8px;
  align-items: center;
  margin-bottom: 12px;
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
