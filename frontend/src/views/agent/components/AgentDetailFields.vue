<template>
  <dl v-if="fields.length" class="fields">
    <template v-for="field in fields" :key="field.key">
      <dt>{{ field.label }}</dt><dd>{{ field.value }}</dd>
    </template>
  </dl>
  <div v-else class="empty">此阶段没有额外结果数据</div>
  <details class="raw"><summary>原始数据（开发排查）</summary><pre>{{ JSON.stringify(detail, null, 2) }}</pre></details>
</template>
<script setup lang="ts">
import { computed } from 'vue'
import { detailFields } from '@/chat-core/trace-view'
const props = defineProps<{ detail: Record<string, unknown> }>()
const fields = computed(() => detailFields(props.detail))
</script>
<style scoped>
.fields { display: grid; grid-template-columns: minmax(90px, 140px) minmax(0, 1fr); gap: 7px 12px; margin: 10px 0; }
dt { color: var(--n-text-color-3); } dd { margin: 0; white-space: pre-wrap; word-break: break-word; }
.raw, .empty { margin-top: 8px; color: var(--n-text-color-3); }
summary { cursor: pointer; } pre { max-height: 280px; overflow: auto; white-space: pre-wrap; word-break: break-word; }
</style>
