/** AgentEvent v2 前端契约与运行时校验。 */

export type EventStatus =
  | 'waiting'
  | 'running'
  | 'completed'
  | 'degraded'
  | 'failed'
  | 'skipped'
  | 'cancelled'

export type EventVisibility = 'public' | 'debug' | 'internal'
export type EventSensitivity = 'normal' | 'user_content'

export interface Citation {
  source_id?: string | null
  chunk_id: string
  document_name: string
  content: string
  score: number
  original_score?: number | null
}

interface AgentEventBase {
  protocol_version: 2
  event_id: string
  request_id: string
  trace_id: string
  turn_id: string
  conversation_id?: string | null
  agent_id?: string | null
  sequence: number
  stage: string
  stage_id: string
  status: EventStatus
  visibility: EventVisibility
  sensitivity: EventSensitivity
  started_at: string
  duration_ms?: number | null
  summary?: string | null
  detail: Record<string, unknown>
  code?: string | null
}

export type AgentEvent =
  | (AgentEventBase & { type: 'turn.started' })
  | (AgentEventBase & { type: 'stage.started' })
  | (AgentEventBase & { type: 'stage.progress' })
  | (AgentEventBase & { type: 'stage.completed' })
  | (AgentEventBase & { type: 'stage.failed'; code: string })
  | (AgentEventBase & { type: 'answer.delta'; content: string })
  | (AgentEventBase & { type: 'answer.revision_started' })
  | (AgentEventBase & { type: 'citations.completed'; citations: Citation[] })
  | (AgentEventBase & { type: 'turn.completed' })
  | (AgentEventBase & { type: 'turn.failed'; code?: string | null })
  | (AgentEventBase & { type: 'turn.cancelled'; code?: string | null })

export interface TransportError {
  type: 'transport_error'
  message: string
}

const EVENT_TYPES = new Set([
  'turn.started',
  'stage.started',
  'stage.progress',
  'stage.completed',
  'stage.failed',
  'answer.delta',
  'answer.revision_started',
  'citations.completed',
  'turn.completed',
  'turn.failed',
  'turn.cancelled',
])
const STATUSES = new Set<EventStatus>([
  'waiting', 'running', 'completed', 'degraded', 'failed', 'skipped', 'cancelled',
])
const VISIBILITIES = new Set<EventVisibility>(['public', 'debug', 'internal'])
const SENSITIVITIES = new Set<EventSensitivity>(['normal', 'user_content'])

function isRecord(value: unknown): value is Record<string, unknown> {
  return !!value && typeof value === 'object' && !Array.isArray(value)
}

/** 收紧来自网络的未知 JSON，secret 事件在前端也会被拒绝。 */
export function isAgentEvent(value: unknown): value is AgentEvent {
  if (!isRecord(value)) return false
  if (value.protocol_version !== 2) return false
  if (typeof value.event_id !== 'string' || !value.event_id) return false
  if (typeof value.request_id !== 'string' || typeof value.trace_id !== 'string') return false
  if (typeof value.turn_id !== 'string' || typeof value.sequence !== 'number') return false
  if (!Number.isInteger(value.sequence) || value.sequence < 1) return false
  if (typeof value.type !== 'string' || !EVENT_TYPES.has(value.type)) return false
  if (typeof value.stage !== 'string' || typeof value.stage_id !== 'string') return false
  if (!STATUSES.has(value.status as EventStatus)) return false
  if (!VISIBILITIES.has(value.visibility as EventVisibility)) return false
  if (!SENSITIVITIES.has(value.sensitivity as EventSensitivity)) return false
  if (typeof value.started_at !== 'string') return false
  if (value.detail !== undefined && !isRecord(value.detail)) return false
  if (value.type === 'answer.delta' && typeof value.content !== 'string') return false
  if (value.type === 'stage.failed' && typeof value.code !== 'string') return false
  if (value.type === 'citations.completed' && !Array.isArray(value.citations)) return false
  return true
}

export function isTerminalEvent(event: AgentEvent): boolean {
  return event.type === 'turn.completed'
    || event.type === 'turn.failed'
    || event.type === 'turn.cancelled'
}
