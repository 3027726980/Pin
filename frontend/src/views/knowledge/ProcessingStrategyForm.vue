<template>
  <n-form label-placement="top" size="small" :disabled="disabled">
    <div class="chunk-grid">
      <n-form-item label="单片长度（字符）">
        <n-input-number
          :value="modelValue.chunk_size"
          :min="50"
          :max="10000"
          style="width: 100%"
          @update:value="value => updateField('chunk_size', value ?? 50)"
        />
      </n-form-item>
      <n-form-item label="相邻片重叠（字符）">
        <n-input-number
          :value="modelValue.chunk_overlap"
          :min="0"
          :max="Math.max(0, modelValue.chunk_size - 1)"
          style="width: 100%"
          @update:value="value => updateField('chunk_overlap', value ?? 0)"
        />
      </n-form-item>
    </div>
    <n-form-item label="分隔符优先级（逗号分隔）">
      <n-input
        :value="modelValue.chunk_separators"
        type="textarea"
        :autosize="false"
        :resizable="false"
        :rows="4"
        placeholder="例如：标题、换行、句号、空格"
        @update:value="value => updateField('chunk_separators', value)"
      />
    </n-form-item>
    <n-form-item label="清洗规则">
      <div class="cleaning-rules">
        <n-space
          v-for="(rule, index) in modelValue.cleaning_config.rules"
          :key="index"
          vertical
          size="small"
          class="cleaning-rule-row"
        >
          <n-space align="center">
            <n-select
              :value="rule.type"
              :options="cleaningRuleOptions"
              style="width: 190px"
              @update:value="value => updateRule(index, { type: value })"
            />
            <n-switch
              :value="rule.enabled !== false"
              size="small"
              @update:value="value => updateRule(index, { enabled: value })"
            />
            <n-button quaternary type="error" @click="removeRule(index)">删除</n-button>
          </n-space>
          <n-input
            v-if="rule.type === 'replace_text' || rule.type === 'regex_remove'"
            :value="rule.value || ''"
            :placeholder="rule.type === 'regex_remove' ? '要删除的正则' : '要替换的文本'"
            @update:value="value => updateRule(index, { value })"
          />
          <n-input
            v-if="rule.type === 'replace_text' || rule.type === 'regex_remove'"
            :value="rule.replacement || ''"
            placeholder="替换为（留空即删除）"
            @update:value="value => updateRule(index, { replacement: value })"
          />
          <n-input-number
            v-if="rule.type === 'collapse_blank_lines'"
            :value="rule.max_consecutive || 1"
            :min="1"
            :max="5"
            style="width: 100%"
            @update:value="value => updateRule(index, { max_consecutive: value ?? 1 })"
          />
        </n-space>
        <n-button dashed size="small" @click="addRule">添加清洗规则</n-button>
      </div>
    </n-form-item>
  </n-form>
</template>

<script setup lang="ts">
import type {
  CleaningRule,
  CleaningRuleType,
  ProcessingConfig,
} from '@/api/knowledge'

const props = defineProps<{
  modelValue: ProcessingConfig
  disabled?: boolean
}>()

const emit = defineEmits<{
  'update:modelValue': [value: ProcessingConfig]
}>()

const cleaningRuleOptions: Array<{ label: string; value: CleaningRuleType }> = [
  { label: 'Unicode 规范化', value: 'normalize_unicode' },
  { label: '移除控制字符', value: 'remove_control_chars' },
  { label: '折叠连续空行', value: 'collapse_blank_lines' },
  { label: '去除行首尾空白', value: 'trim_lines' },
  { label: '折叠重复标点', value: 'collapse_punctuation' },
  { label: '文本替换', value: 'replace_text' },
  { label: '正则删除', value: 'regex_remove' },
]

function cloneConfig(): ProcessingConfig {
  return JSON.parse(JSON.stringify(props.modelValue)) as ProcessingConfig
}

function updateField<K extends keyof ProcessingConfig>(key: K, value: ProcessingConfig[K]) {
  const next = cloneConfig()
  next[key] = value
  emit('update:modelValue', next)
}

function updateRule(index: number, patch: Partial<CleaningRule>) {
  const next = cloneConfig()
  next.cleaning_config.rules[index] = {
    ...next.cleaning_config.rules[index],
    ...patch,
  }
  emit('update:modelValue', next)
}

function addRule() {
  const next = cloneConfig()
  next.cleaning_config.rules.push({
    type: 'trim_lines',
    enabled: true,
    replacement: '',
    max_consecutive: 1,
  })
  emit('update:modelValue', next)
}

function removeRule(index: number) {
  const next = cloneConfig()
  next.cleaning_config.rules.splice(index, 1)
  emit('update:modelValue', next)
}
</script>

<style scoped>
.chunk-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px;
}

.cleaning-rules,
.cleaning-rule-row {
  width: 100%;
}

.cleaning-rule-row {
  margin-bottom: 10px;
  padding: 8px;
  border: 1px solid var(--n-border-color);
  border-radius: 4px;
}

@media (max-width: 700px) {
  .chunk-grid {
    grid-template-columns: 1fr;
  }
}
</style>
