import type { StageView, TurnState } from './stage-reducer'

export function stageElapsedMs(stage: StageView, now = Date.now()): number {
  if (stage.durationMs !== null) return stage.durationMs
  return Math.max(0, now - Date.parse(stage.startedAt))
}

export function turnElapsedMs(state: TurnState, now = Date.now()): number {
  if (state.metrics.totalDurationMs !== null) return state.metrics.totalDurationMs
  return state.metrics.startedAt
    ? Math.max(0, now - Date.parse(state.metrics.startedAt))
    : 0
}
