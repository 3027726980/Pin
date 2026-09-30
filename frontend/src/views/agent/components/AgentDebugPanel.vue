<template>
  <n-collapse v-if="show && debugStages.length" class="debug-panel">
    <n-collapse-item title="调试详情与耗时" name="debug">
      <AgentWaterfall :state="state" />
      <div v-for="stage in debugStages" :key="stage.stageId" class="detail">
        <div class="title">{{ stage.summary || stage.stage }} · {{ formatDuration(stage.durationMs) }}</div>
        <pre>{{ JSON.stringify(stage.detail, null, 2) }}</pre>
      </div>
    </n-collapse-item>
  </n-collapse>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { formatDuration } from '@/chat-core/formatters'
import type { TurnState } from '@/chat-core/stage-reducer'
import AgentWaterfall from './AgentWaterfall.vue'

const props = defineProps<{ state: TurnState; show: boolean }>()
const debugStages = computed(() => props.state.stageOrder
  .map(id => props.state.stages[id])
  .filter(stage => stage.visibility === 'debug'))
</script>

<style scoped>
.debug-panel { margin-top: 8px; font-size: 12px; }
.detail { margin-top: 10px; }
.title { color: var(--n-text-color-2); }
pre { max-height: 240px; overflow: auto; margin: 5px 0 0; padding: 8px; border-radius: 6px; background: rgba(128,128,128,.08); white-space: pre-wrap; word-break: break-word; }
</style>
