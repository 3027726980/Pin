<!-- 作者：LHF；时间：2026-10-25；作用：管理端上下文容量圆环和悬浮详情。 -->
<template>
  <n-tooltip placement="top" trigger="hover">
    <template #trigger>
      <button class="context-ring" type="button" :aria-label="description" :style="{ color }">
        <svg viewBox="0 0 24 24" width="22" height="22" aria-hidden="true">
          <circle class="ring-track" cx="12" cy="12" r="8" />
          <circle v-if="usage" class="ring-value" cx="12" cy="12" r="8"
            pathLength="100" :stroke-dasharray="`${Math.min(100, percentage)} 100`" />
        </svg>
      </button>
    </template>
    <div class="context-tooltip">
      <div class="context-caption">上下文容量</div>
      <template v-if="usage">
        <div>已用 {{ percentage }}%（剩余 {{ Math.max(0, 100 - percentage) }}%）</div>
        <div class="context-count">约 {{ formatTokens(usage.used_tokens) }} / {{ formatTokens(usage.input_capacity) }} tokens</div>
        <div class="context-caption">{{ usage.model_name }}</div>
        <div v-if="usage.capacity_source === 'configured_fallback'" class="context-caption">总容量采用回退配置</div>
        <div v-else-if="usage.capacity_source === 'provider_models_api'" class="context-caption">容量来源：供应商模型接口</div>
        <div v-if="usage.token_encoding" class="context-caption">
          {{ usage.token_encoding }} 分词计数{{ usage.token_encoding_source === 'fallback' ? '（通用编码估算）' : '' }}
        </div>
        <div class="context-note">{{ busy ? '处理中，显示上次估算' : '已保存上下文估算，含系统提示词与工具' }}</div>
      </template>
      <div v-else>{{ loading ? '正在读取容量…' : '容量暂不可用' }}</div>
    </div>
  </n-tooltip>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import type { ContextUsage } from '@/api/conversation'

const props = defineProps<{ usage: ContextUsage | null; loading: boolean; busy: boolean }>()
const percentage = computed(() => props.usage
  ? Math.round(props.usage.used_tokens / props.usage.input_capacity * 100) : 0)
const color = computed(() => !props.usage ? '#9ca3af'
  : percentage.value >= 95 ? '#d03050' : percentage.value >= 80 ? '#f0a020' : '#808894')
const description = computed(() => props.usage
  ? `上下文已用 ${percentage.value}%，约 ${props.usage.used_tokens} / ${props.usage.input_capacity} tokens`
  : '上下文容量暂不可用')

/** 作者：LHF；2026-10-25；以带千位分隔符的精确整数展示估算值，避免 k 缩写损失细节。 */
function formatTokens(value: number): string {
  return value.toLocaleString('zh-CN')
}
</script>

<style scoped>
.context-ring {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 32px;
  height: 34px;
  padding: 0;
  border: 0;
  border-radius: 6px;
  background: transparent;
  cursor: help;
}
.context-ring:focus-visible { outline: 2px solid currentColor; outline-offset: 2px; }
.context-ring circle { fill: none; stroke-width: 3; }
.ring-track { stroke: currentColor; opacity: .18; }
.ring-value { stroke: currentColor; transform: rotate(-90deg); transform-origin: center; transition: stroke-dasharray .25s; }
.context-tooltip { padding: 4px 8px; text-align: center; line-height: 1.7; }
.context-caption { opacity: .65; font-size: 12px; }
.context-count { font-variant-numeric: tabular-nums; }
.context-note { opacity: .65; font-size: 11px; }
</style>
