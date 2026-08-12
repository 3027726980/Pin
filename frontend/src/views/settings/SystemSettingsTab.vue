<!--
系统设置 Tab：通用设置项管理
- logging.redact_rules：脱敏规则结构化表单（enabled + 规则列表逐条增删改）
- 其他设置项：JSON 文本编辑（textarea + 校验）
保存后后端立即生效（刷新缓存 + 重建 Filter）
-->
<template>
  <div class="system-settings">
    <n-spin :show="loading">
      <div v-if="settings.length === 0" class="empty">
        <n-empty description="暂无设置项" />
      </div>

      <!-- 脱敏规则：结构化表单 -->
      <n-card v-if="redactConfig" title="日志脱敏规则（logging.redact_rules）" size="small" class="item-card">
        <n-form label-placement="left" label-width="120">
          <n-form-item label="启用脱敏">
            <n-switch v-model:value="redactConfig.enabled" />
          </n-form-item>
          <n-form-item label="匹配规则">
            <n-dynamic-input
              v-model:value="redactConfig.rules"
              #default="{ value }"
              #create-default="() => ({ type: 'field_name', pattern: '', mask: 'keep_4_4' })"
            >
              <div class="rule-row">
                <n-select
                  v-model:value="value.type"
                  :options="[
                    { label: '字段名匹配', value: 'field_name' },
                    { label: '值模式匹配', value: 'value_pattern' },
                  ]"
                  style="width: 130px"
                />
                <n-input v-model:value="value.pattern" placeholder="正则表达式，如 sk-[A-Za-z0-9]+" />
                <n-select
                  v-model:value="value.mask"
                  :options="[
                    { label: '保留前4后4', value: 'keep_4_4' },
                    { label: '整体掩码', value: 'full_mask' },
                  ]"
                  style="width: 130px"
                />
              </div>
            </n-dynamic-input>
            <span class="hint">示例：sk-3cb94abcd → sk-3***bcd；字段名 api_key/token/password 等自动匹配</span>
          </n-form-item>
        </n-form>
        <div class="save-row">
          <n-button type="primary" :loading="saving" @click="saveRedactRules">
            保存脱敏规则
          </n-button>
        </div>
      </n-card>

      <!-- 其他设置项：JSON 文本编辑 -->
      <n-card
        v-for="item in otherSettings"
        :key="item.key"
        :title="item.key"
        size="small"
        class="item-card"
      >
        <div v-if="item.description" class="hint" style="margin-bottom: 8px">{{ item.description }}</div>
        <n-input
          v-model:value="jsonDrafts[item.key]"
          type="textarea"
          :autosize="{ minRows: 4, maxRows: 12 }"
          placeholder="JSON 配置内容"
        />
        <div class="save-row">
          <span v-if="jsonErrors[item.key]" class="json-error">{{ jsonErrors[item.key] }}</span>
          <n-button type="primary" size="small" @click="saveJsonItem(item.key)">
            保存
          </n-button>
        </div>
      </n-card>
    </n-spin>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { useMessage } from 'naive-ui'
import {
  listSettings,
  updateSetting,
  type RedactRule,
  type RedactRulesConfig,
  type SystemSetting,
} from '@/api/settings'

const message = useMessage()
const loading = ref(false)
const saving = ref(false)
const settings = ref<SystemSetting[]>([])
const jsonDrafts = reactive<Record<string, string>>({})
const jsonErrors = reactive<Record<string, string>>({})

/** 脱敏规则（结构化编辑） */
const redactConfig = ref<RedactRulesConfig | null>(null)
const redactKey = 'logging.redact_rules'

const otherSettings = computed(() =>
  settings.value.filter((s) => s.key !== redactKey),
)

onMounted(async () => {
  await load()
})

async function load() {
  loading.value = true
  try {
    settings.value = await listSettings()
    const rs = settings.value.find((s) => s.key === redactKey)
    if (rs) {
      const cfg = rs.value as unknown as RedactRulesConfig
      redactConfig.value = {
        enabled: Boolean(cfg.enabled),
        // 防御：过滤历史遗留的 null 项（DynamicInput 旧版添加默认值可能为 null）
        rules: (cfg.rules || []).filter(
          (r) => r && typeof r === 'object' && r.type,
        ) as RedactRule[],
      }
    }
    for (const s of otherSettings.value) {
      jsonDrafts[s.key] = JSON.stringify(s.value, null, 2)
    }
  } catch (e) {
    message.error((e as Error).message || '设置加载失败')
  } finally {
    loading.value = false
  }
}

async function saveRedactRules() {
  if (!redactConfig.value) return
  saving.value = true
  try {
    await updateSetting(redactKey, redactConfig.value as unknown as Record<string, unknown>)
    message.success('脱敏规则已保存并立即生效')
  } catch (e) {
    message.error((e as Error).message || '保存失败')
  } finally {
    saving.value = false
  }
}

async function saveJsonItem(key: string) {
  const raw = jsonDrafts[key] || ''
  try {
    const parsed = JSON.parse(raw)
    if (typeof parsed !== 'object' || parsed === null || Array.isArray(parsed)) {
      throw new Error('配置值必须是 JSON 对象')
    }
    jsonErrors[key] = ''
    await updateSetting(key, parsed)
    message.success(`「${key}」已保存并立即生效`)
  } catch (e) {
    jsonErrors[key] = `JSON 格式错误: ${(e as Error).message}`
  }
}
</script>

<style scoped>
.system-settings {
  max-width: 960px;
}
.empty {
  padding: 40px 0;
}
.item-card {
  margin-bottom: 16px;
}
.rule-row {
  display: flex;
  gap: 8px;
  align-items: center;
  width: 100%;
}
.hint {
  font-size: 12px;
  color: var(--n-text-color-3);
  line-height: 1.6;
}
.save-row {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  margin-top: 4px;
}
.json-error {
  font-size: 12px;
  color: #d03050;
  margin-right: auto;
}
</style>
