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

/** abort/网络断流后客户端收口；仅用于展示，不伪造服务端成功或日志。 */
export function interruptTurn(state: TurnState, status: 'failed' | 'cancelled', now = Date.now()): TurnState {
  if (state.terminalReceived) return state
  const started = state.metrics.startedAt || state.stages[state.stageOrder[0]]?.startedAt
  const elapsed = started ? now - Date.parse(started) : 0
  return reduceTurnEvent(state, {
    protocol_version: 2, event_id: `local-${state.lastSequence + 1}`, request_id: 'local',
    trace_id: state.traceId || '', turn_id: state.turnId, sequence: state.lastSequence + 1,
    type: status === 'failed' ? 'turn.failed' : 'turn.cancelled', status,
    stage: 'request', stage_id: 'request.1', visibility: 'public', sensitivity: 'normal',
    started_at: new Date(now).toISOString(), duration_ms: Number.isFinite(elapsed) ? Math.max(0, elapsed) : 0,
    detail: {},
  })
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
      startedAt: next.stages[event.stage_id]?.startedAt ?? event.started_at,
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
    if (typeof event.detail.answer_first_token_ms === 'number') {
      next.metrics.answerFirstTokenMs = event.detail.answer_first_token_ms
    }
    for (const id of next.stageOrder) {
      const stage = next.stages[id]
      if (stage.status !== 'running' && stage.status !== 'waiting') continue
      const elapsed = Date.parse(event.started_at) - Date.parse(stage.startedAt)
      next.stages[id] = {
        ...stage,
        status: next.status,
        durationMs: stage.durationMs ?? (Number.isFinite(elapsed) ? Math.max(0, elapsed) : 0),
      }
    }
  }
  return next
}
