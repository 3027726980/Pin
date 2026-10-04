import { describe, expect, it } from 'vitest'

import type { AgentEvent } from './events'
import { stageElapsedMs } from './metrics'
import { createTurnState, reduceTurnEvent, interruptTurn } from './stage-reducer'

function event(overrides: Partial<AgentEvent>): AgentEvent {
  return {
    protocol_version: 2,
    event_id: `evt-${overrides.sequence ?? 1}`,
    request_id: 'req-1',
    trace_id: 'tr-1',
    turn_id: 'turn-1',
    sequence: 1,
    type: 'stage.started',
    stage: 'retrieval',
    stage_id: 'retrieval.1',
    status: 'running',
    visibility: 'public',
    sensitivity: 'normal',
    started_at: '2026-09-29T10:00:00Z',
    detail: {},
    ...overrides,
  } as AgentEvent
}

describe('Turn reducer', () => {
  it('freezes a cancelled local turn when abort prevents a server terminal', () => {
    let state = reduceTurnEvent(createTurnState(), event({ sequence: 1 }))
    state = interruptTurn(state, 'cancelled', Date.parse('2026-09-29T10:00:02Z'))
    expect(state.status).toBe('cancelled')
    expect(state.stages['retrieval.1'].durationMs).toBe(2000)
    expect(state.terminalReceived).toBe(true)
  })
  it('closes remaining running stages at the turn terminal', () => {
    let state = reduceTurnEvent(createTurnState(), event({ sequence: 1, stage: 'agent', stage_id: 'agent.1' }))
    state = reduceTurnEvent(state, event({
      sequence: 2, type: 'turn.failed', stage: 'request', stage_id: 'request.1',
      status: 'failed', started_at: '2026-09-29T10:00:03Z', duration_ms: 3000,
    }))
    expect(state.stages['agent.1'].status).toBe('failed')
    expect(state.stages['agent.1'].durationMs).toBe(3000)
  })
  it('updates parallel stages by stage_id and keeps their order', () => {
    let state = createTurnState('turn-1')
    state = reduceTurnEvent(state, event({ sequence: 1, stage: 'mqe', stage_id: 'mqe.1' }))
    state = reduceTurnEvent(state, event({ sequence: 2, stage: 'hyde', stage_id: 'hyde.1' }))
    state = reduceTurnEvent(state, event({
      sequence: 3,
      type: 'stage.completed',
      stage: 'mqe',
      stage_id: 'mqe.1',
      status: 'completed',
      duration_ms: 120,
    }))

    expect(state.stageOrder).toEqual(['mqe.1', 'hyde.1'])
    expect(state.stages['mqe.1'].status).toBe('completed')
    expect(state.stages['hyde.1'].status).toBe('running')
  })

  it('ignores duplicate sequence and normal events after terminal', () => {
    let state = createTurnState('turn-1')
    state = reduceTurnEvent(state, event({ sequence: 1 }))
    const duplicate = reduceTurnEvent(state, event({ sequence: 1, summary: 'duplicate' }))
    expect(duplicate).toBe(state)

    state = reduceTurnEvent(state, event({
      sequence: 2,
      type: 'turn.completed',
      stage: 'request',
      stage_id: 'request.1',
      status: 'completed',
    }))
    const afterTerminal = reduceTurnEvent(state, event({
      sequence: 3,
      type: 'answer.delta',
      stage: 'answer',
      stage_id: 'answer.1',
      status: 'running',
      content: 'late',
    }))
    expect(afterTerminal).toBe(state)
    expect(state.content).toBe('')
  })

  it('keeps debug details even when presentation mode is outside reducer', () => {
    let state = createTurnState('turn-1')
    state = reduceTurnEvent(state, event({
      sequence: 1,
      type: 'stage.completed',
      visibility: 'debug',
      status: 'completed',
      detail: { queries: ['q1', 'q2'] },
    }))

    expect(state.debugDetails['retrieval.1']).toEqual({ queries: ['q1', 'q2'] })
  })

  it('does not keep counting a completed stage without duration', () => {
    let state = createTurnState('turn-1')
    state = reduceTurnEvent(state, event({
      sequence: 1,
      type: 'stage.completed',
      stage: 'intent',
      stage_id: 'intent.1',
      status: 'completed',
      duration_ms: null,
    }))

    expect(stageElapsedMs(state.stages['intent.1'], Date.parse('2026-09-29T10:00:05Z'))).toBe(0)
  })
})
