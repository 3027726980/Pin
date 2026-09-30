import { isTerminalEvent, type AgentEvent, type Citation, type EventStatus } from './events'

export interface StageView {
  stage: string
  stageId: string
  status: EventStatus
  visibility: AgentEvent['visibility']
  startedAt: string
  durationMs: number | null
  summary: string | null
  detail: Record<string, unknown>
}

export interface TurnMetrics {
  startedAt: string | null
  totalDurationMs: number | null
  answerFirstTokenMs: number | null
}

export interface TurnState {
  turnId: string
  traceId: string | null
  conversationId: string | null
  content: string
  status: 'running' | 'completed' | 'failed' | 'cancelled'
  stages: Record<string, StageView>
  stageOrder: string[]
  metrics: TurnMetrics
  citations: Citation[]
  citationBindings: unknown[]
  debugDetails: Record<string, unknown>
  terminalReceived: boolean
  lastSequence: number
}

export function createTurnState(turnId = ''): TurnState {
  return {
    turnId,
    traceId: null,
    conversationId: null,
    content: '',
    status: 'running',
    stages: {},
    stageOrder: [],
    metrics: { startedAt: null, totalDurationMs: null, answerFirstTokenMs: null },
    citations: [],
    citationBindings: [],
    debugDetails: {},
    terminalReceived: false,
    lastSequence: 0,
  }
}

/** 纯 reducer：sequence 去重、stage_id 更新、终态后冻结普通事件。 */
export function reduceTurnEvent(state: TurnState, event: AgentEvent): TurnState {
  if (event.sequence <= state.lastSequence || state.terminalReceived) return state

  const next: TurnState = {
    ...state,
    turnId: event.turn_id,
    traceId: event.trace_id,
    conversationId: event.conversation_id ?? state.conversationId,
    stages: { ...state.stages },
    stageOrder: [...state.stageOrder],
    metrics: { ...state.metrics },
    citations: [...state.citations],
    citationBindings: [...state.citationBindings],
    debugDetails: { ...state.debugDetails },
    lastSequence: event.sequence,
  }

  if (event.type === 'turn.started') next.metrics.startedAt = event.started_at
  if (event.type === 'answer.delta') {
    next.content += event.content
    if (next.metrics.answerFirstTokenMs === null && next.metrics.startedAt) {
      next.metrics.answerFirstTokenMs = Math.max(
        0,
        Date.parse(event.started_at) - Date.parse(next.metrics.startedAt),
      )
    }
  }
  if (event.type === 'answer.revision_started') {
    next.content = ''
  }
  if (event.type === 'citations.completed') {
    next.citations = event.citations
    next.citationBindings = Array.isArray(event.detail.bindings)
      ? event.detail.bindings
      : []
  }

  if (event.type.startsWith('stage.')) {
    const existed = !!next.stages[event.stage_id]
    next.stages[event.stage_id] = {
      stage: event.stage,
      stageId: event.stage_id,
      status: event.status,
      visibility: event.visibility,
      startedAt: event.started_at,
      durationMs: event.duration_ms
        ?? (event.status === 'running' || event.status === 'waiting' ? null : 0),
      summary: event.summary ?? null,
      detail: event.detail,
    }
    if (!existed) next.stageOrder.push(event.stage_id)
    if (event.visibility === 'debug') {
      next.debugDetails[event.stage_id] = event.detail
    }
  }

  if (isTerminalEvent(event)) {
    next.terminalReceived = true
    next.metrics.totalDurationMs = event.duration_ms ?? null
    next.status = event.type === 'turn.completed'
      ? 'completed'
      : event.type === 'turn.cancelled' ? 'cancelled' : 'failed'
  }
  return next
}
