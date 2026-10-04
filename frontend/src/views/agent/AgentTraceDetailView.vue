<template>
  <n-card :title="`链路 · ${traceId}`">
    <template #header-extra><n-button @click="router.back()">返回</n-button></template>
    <AgentTraceDetail :trace-id="traceId" />
  </n-card>
</template>
<script setup lang="ts">
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import AgentTraceDetail from './components/AgentTraceDetail.vue'
const route = useRoute()
const router = useRouter()
const traceId = computed(() => String(route.params.traceId))
</script>
