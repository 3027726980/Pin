import { describe, expect, it } from 'vitest'
import { buildTraceState, compactTraceEvents, detailFields } from './trace-view'

describe('Trace presentation', () => {
  it('merges answer chunks without claiming each chunk is still running', () => {
    const rows = [
      { event: 'answer.delta', sequence: 1, content_length: 3, status: 'running' },
      { event: 'answer.delta', sequence: 2, content_length: 4, status: 'running' },
      { event: 'turn.completed', sequence: 3, status: 'completed', duration_ms: 500 },
    ]
    const compact = compactTraceEvents(rows)
    expect(compact).toHaveLength(2)
    expect(compact[0].detail).toEqual({ chunk_count: 2, character_count: 7 })
    expect(compact[0].status).toBe('completed')
    expect(compact[0].duration_ms).toBeNull()
  })

  it('replays terminal status even when summary has not been written yet', () => {
    const state = buildTraceState('tr', null, [
      { event: 'stage.started', stage: 'agent', stage_id: 'agent.1', status: 'running', sequence: 1, started_at: '2026-10-04T00:00:00Z' },
      { event: 'turn.completed', status: 'completed', sequence: 2, duration_ms: 1200, started_at: '2026-10-04T00:00:01.200Z' },
    ])
    expect(state.status).toBe('completed')
    expect(state.stages['agent.1'].status).toBe('completed')
    expect(state.stages['agent.1'].durationMs).toBe(1200)
  })

  it('renders nested diagnostics with Chinese labels and readable values', () => {
    const fields = detailFields({ strategy: 'base', queries: ['问题1', '问题2'], stats: { candidate_count: 5 } })
    expect(fields[0]).toMatchObject({ label: '检索策略', value: '基础检索' })
    expect(fields[1].value).toContain('问题1')
    expect(fields[2].value).toContain('候选数量：5')
  })
})
