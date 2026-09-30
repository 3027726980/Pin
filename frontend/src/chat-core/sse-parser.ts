import { isAgentEvent, isTerminalEvent, type AgentEvent } from './events'

export interface SseParser {
  readonly terminalReceived: boolean
  push(chunk: string): AgentEvent[]
  finish(): AgentEvent[]
}

/** 增量解析 SSE 帧，不包含任何 UI 或业务副作用。 */
export function createSseParser(): SseParser {
  let buffer = ''
  let terminalReceived = false
  const seenIds = new Set<string>()

  function parseFrame(frame: string): AgentEvent | null {
    const lines = frame.split('\n')
    const data = lines
      .filter(line => line.startsWith('data:'))
      .map(line => line.slice(5).trimStart())
      .join('\n')
    if (!data) return null
    try {
      const value: unknown = JSON.parse(data)
      if (!isAgentEvent(value)) return null
      if (terminalReceived || seenIds.has(value.event_id)) return null
      seenIds.add(value.event_id)
      if (isTerminalEvent(value)) terminalReceived = true
      return value
    } catch {
      return null
    }
  }

  function drain(includeTail: boolean): AgentEvent[] {
    buffer = buffer.replace(/\r\n/g, '\n').replace(/\r/g, '\n')
    const events: AgentEvent[] = []
    let boundary = buffer.indexOf('\n\n')
    while (boundary >= 0) {
      const frame = buffer.slice(0, boundary)
      buffer = buffer.slice(boundary + 2)
      const event = parseFrame(frame)
      if (event) events.push(event)
      boundary = buffer.indexOf('\n\n')
    }
    if (includeTail && buffer.trim()) {
      const event = parseFrame(buffer)
      if (event) events.push(event)
      buffer = ''
    }
    return events
  }

  return {
    get terminalReceived() {
      return terminalReceived
    },
    push(chunk: string) {
      buffer += chunk
      return drain(false)
    },
    finish() {
      return drain(true)
    },
  }
}
