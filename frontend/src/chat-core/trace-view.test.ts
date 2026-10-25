import { describe, expect, it } from 'vitest'
import { buildTraceState, compactTraceEvents, completedTraceRecords } from './trace-view'

describe('Trace presentation', () => {
  it('uses completed operation records with full payload and start order', () => {
    const large = '完整输入'.repeat(2000)
    const rows = completedTraceRecords([
      { record_version: 1, operation_id: 'child', kind: 'model', started_at: '2026-10-25T00:00:01Z', input: large, output: [] },
      { record_version: 1, operation_id: 'parent', kind: 'request', started_at: '2026-10-25T00:00:00Z' },
    ], [])
    expect(rows.map(row => row.operation_id)).toEqual(['parent', 'child'])
    expect(rows[1].input).toBe(large)
    expect(rows[1].output).toEqual([])
  })

  it('merges old starts without inventing missing input', () => {
    const rows = completedTraceRecords(undefined, [
      { event: 'stage.started', stage_id: 'intent.1', started_at: 'begin' },
      { event: 'stage.completed', stage: 'intent', stage_id: 'intent.1', detail: { intent: 'simple' } },
      { event: 'answer.delta' },
    ])
    expect(rows).toHaveLength(1)
    expect(rows[0].started_at).toBe('begin')
    expect(rows[0].input).toBeUndefined()
    expect(rows[0].metadata).toEqual({ legacy: true })
  })

  it('replays terminal operation timings using the existing waterfall reducer', () => {
    const state = buildTraceState('tr', { status: 'completed', total_duration_ms: 100 }, [
      { record_version: 1, operation_id: 'model-1', kind: 'model', status: 'completed', started_at: '2026-10-25T00:00:00Z', duration_ms: 90 },
    ])
    expect(state.terminalReceived).toBe(true)
    expect(state.stages['model-1'].durationMs).toBe(90)
  })
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

})
