import { describe, expect, it } from 'vitest'

import { createSseParser } from './sse-parser'

function event(sequence: number, type = 'stage.completed') {
  const payload: Record<string, unknown> = {
    protocol_version: 2,
    event_id: `evt-${sequence}`,
    request_id: 'req-1',
    trace_id: 'tr-1',
    turn_id: 'turn-1',
    sequence,
    type,
    stage: type.startsWith('turn.') ? 'request' : 'retrieval',
    stage_id: type.startsWith('turn.') ? 'request.1' : 'retrieval.1',
    status: type === 'turn.completed' ? 'completed' : 'completed',
    visibility: 'public',
    sensitivity: 'normal',
    started_at: '2026-09-29T10:00:00Z',
  }
  return `id: evt-${sequence}\ndata: ${JSON.stringify(payload)}\n\n`
}

describe('SSE parser', () => {
  it('handles one frame split across network chunks', () => {
    const parser = createSseParser()
    const frame = event(1)

    expect(parser.push(frame.slice(0, 20))).toEqual([])
    expect(parser.push(frame.slice(20))).toHaveLength(1)
  })

  it('handles multiple frames, CRLF and a final frame without blank line', () => {
    const parser = createSseParser()
    const input = (event(1) + event(2)).replaceAll('\n', '\r\n')
    expect(parser.push(input)).toHaveLength(2)

    const tail = event(3).trimEnd()
    expect(parser.push(tail)).toEqual([])
    expect(parser.finish()).toHaveLength(1)
  })

  it('ignores invalid json, duplicate ids and events after terminal', () => {
    const parser = createSseParser()
    const invalid = 'id: bad\ndata: {bad json}\n\n'
    const terminal = event(2, 'turn.completed')

    const result = parser.push(invalid + event(1) + event(1) + terminal + event(3))

    expect(result.map(item => item.event_id)).toEqual(['evt-1', 'evt-2'])
    expect(parser.terminalReceived).toBe(true)
  })
})
