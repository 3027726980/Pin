<!-- 作者：LHF；时间：2026-10-25；作用：直接展示诊断原始 JSON，保留字段名和值。 -->
<template>
  <pre class="raw-json">{{ JSON.stringify(detail, null, 2) }}</pre>
</template>
<script setup lang="ts">
defineProps<{ detail: Record<string, unknown> }>()
</script>
<style scoped>
.raw-json {
  min-width: 0;
  max-height: 65vh;
  margin: 10px 0;
  padding: 12px;
  overflow: auto;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
  font-size: 12px;
}
</style>
