<template>
  <div v-if="rows.length" class="waterfall">
    <div v-for="row in rows" :key="row.stageId" class="row">
      <span class="name">{{ row.stage }}</span>
      <span class="track"><i :style="barStyle(row)" /></span>
      <span class="duration">{{ formatDuration(row.durationMs) }}</span>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { formatDuration } from '@/chat-core/formatters'
import type { StageView, TurnState } from '@/chat-core/stage-reducer'

const props = defineProps<{ state: TurnState }>()
const rows = computed(() => props.state.stageOrder.map(id => props.state.stages[id]))
const maxDuration = computed(() => Math.max(1, ...rows.value.map(row => row.durationMs || 1)))
function barStyle(row: StageView) {
  return { width: `${Math.max(3, ((row.durationMs || 1) / maxDuration.value) * 100)}%` }
}
</script>

<style scoped>
.waterfall { display: grid; gap: 5px; margin-top: 10px; }
.row { display: grid; grid-template-columns: 86px minmax(80px, 1fr) 55px; gap: 7px; align-items: center; font-size: 11px; }
.name { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.track { height: 6px; border-radius: 4px; background: rgba(128,128,128,.12); overflow: hidden; }
.track i { display: block; height: 100%; border-radius: inherit; background: #2080f0; }
.duration { text-align: right; color: var(--n-text-color-3); font-variant-numeric: tabular-nums; }
</style>
