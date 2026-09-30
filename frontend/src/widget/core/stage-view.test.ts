import { describe, expect, it } from 'vitest'
import { createTurnState } from '../../chat-core/stage-reducer'
import { widgetStageText, widgetVisibleStages } from './stage-view'

describe('widget stage view', () => {
  it('只暴露 public 阶段并显示真实状态', () => {
    const state = createTurnState('t1')
    state.stageOrder = ['debug', 'rag']
    state.stages.debug = { stage: 'mqe', stageId: 'debug', status: 'completed', visibility: 'debug', startedAt: '', durationMs: 12, summary: 'secret', detail: {} }
    state.stages.rag = { stage: 'retrieval', stageId: 'rag', status: 'running', visibility: 'public', startedAt: '', durationMs: null, summary: null, detail: {} }
    expect(widgetVisibleStages(state).map(stage => stage.stageId)).toEqual(['rag'])
    expect(widgetStageText(state)).toBe('正在查找相关资料')
  })
})
