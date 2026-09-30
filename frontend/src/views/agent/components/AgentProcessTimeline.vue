<template>
  <details class="process" :open="!state.content && !state.terminalReceived">
    <summary>
      <span class="pulse" :class="state.status" />
      <span>{{ headline }}</span>
      <span class="elapsed">{{ formatDuration(turnElapsedMs(state, now)) }}</span>
    </summary>
    <div class="stages">
      <div v-for="stage in publicStages" :key="stage.stageId" class="stage">
        <span class="dot" :class="stage.status" />
        <span class="label">{{ stage.summary || PUBLIC_STAGE_TEXT[stage.stage] || stage.stage }}</span>
        <span class="elapsed">{{ formatDuration(stageElapsedMs(stage, now)) }}</span>
      </div>
    </div>
  </details>
</template>

<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { PUBLIC_STAGE_TEXT, formatDuration } from '@/chat-core/formatters'
import { stageElapsedMs, turnElapsedMs } from '@/chat-core/metrics'
import type { TurnState } from '@/chat-core/stage-reducer'

const props = defineProps<{ state: TurnState }>()
const now = ref(Date.now())
let timer: number | undefined

const publicStages = computed(() => props.state.stageOrder
  .map(id => props.state.stages[id])
  .filter(stage => stage.visibility === 'public'))

const headline = computed(() => {
  if (props.state.status === 'failed') return '处理失败'
  if (props.state.status === 'cancelled') return '已停止生成'
  if (props.state.status === 'completed') return '处理完成'
  const running = [...publicStages.value].reverse().find(stage => stage.status === 'running')
  return running?.summary || (running && PUBLIC_STAGE_TEXT[running.stage]) || '正在准备回答'
})

onMounted(() => {
  timer = window.setInterval(() => { now.value = Date.now() }, 100)
})
onUnmounted(() => {
  if (timer !== undefined) window.clearInterval(timer)
})
</script>

<style scoped>
.process { margin-bottom: 8px; color: var(--n-text-color-2); }
.process summary { display: flex; align-items: center; gap: 7px; cursor: pointer; list-style: none; font-size: 13px; }
.process summary::-webkit-details-marker { display: none; }
.stages { margin: 7px 0 0 5px; padding-left: 10px; border-left: 1px solid var(--n-border-color); }
.stage { display: grid; grid-template-columns: 8px minmax(0, 1fr) auto; align-items: center; gap: 7px; padding: 3px 0; font-size: 12px; }
.dot, .pulse { width: 7px; height: 7px; border-radius: 50%; background: #18a058; }
.running { background: #2080f0; animation: pulse 1.2s infinite; }
.failed { background: #d03050; }
.cancelled, .skipped { background: #999; }
.degraded { background: #f0a020; }
.elapsed { margin-left: auto; color: var(--n-text-color-3); font-variant-numeric: tabular-nums; }
@keyframes pulse { 50% { opacity: .35; } }
</style>
