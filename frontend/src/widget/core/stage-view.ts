import { PUBLIC_STAGE_TEXT } from '../../chat-core/formatters'
import type { TurnState } from '../../chat-core/stage-reducer'

/** Widget 只展示 public 阶段；debug/internal 即使误传也不会进入 Shadow DOM。 */
export function widgetVisibleStages(state: TurnState) {
  return state.stageOrder
    .map(id => state.stages[id])
    .filter(stage => stage.visibility === 'public')
}

export function widgetStageText(state: TurnState): string {
  if (state.status === 'failed') return '处理失败'
  if (state.status === 'cancelled') return '已停止生成'
  if (state.status === 'completed') return '处理完成'
  const stage = [...widgetVisibleStages(state)].reverse().find(item => item.status === 'running')
  return stage?.summary || (stage && PUBLIC_STAGE_TEXT[stage.stage]) || '正在准备回答'
}
