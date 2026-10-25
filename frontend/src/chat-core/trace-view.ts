/** 作者：LHF；时间：2026-10-25；作用：新终态日志与旧日志兼容回放。 */
/** 链路回放、增量合并及终态记录兼容。 */
import { createTurnState, reduceTurnEvent, type TurnState } from './stage-reducer'
import { isAgentEvent } from './events'

export const STAGE_LABELS: Record<string, string> = {
  preparation: '执行准备',
  request: '请求', intent: '意图识别', plan: '执行计划', reflect: '回答反思',
  agent: 'Agent 执行', model: '模型调用', model_output: '模型输出', tool: '工具执行', answer: '回答生成',
  mqe: '多查询扩展', hyde: '假设文档', embedding: '向量生成', retrieval: '知识检索',
  rerank: '候选精排', rag_strategy: '检索策略', verify: '回答核验', citation_binding: '引用绑定',
}
export const STATUS_LABELS: Record<string, string> = {
  running: '进行中', waiting: '等待中', completed: '已完成', failed: '失败',
  cancelled: '已取消', degraded: '已降级', skipped: '已跳过',
}
/** 仅回放阶段和指标，完整输入输出由独立操作记录展示，避免向聊天重复插入回答。 */
export function buildTraceState(traceId: string, summary: Record<string, unknown> | null, rows: Record<string, unknown>[]): TurnState {
  let state = createTurnState(String(summary?.turn_id || ''))
  rows.forEach((original, index) => {
    // 终态操作记录转换为回放事件；实时 SSE 协议保持不变。
    const raw = original.record_version ? { ...original, event: 'stage.completed',
      stage: original.kind, stage_id: original.operation_id, detail: {} } : original
    const event = {
      ...raw, type: raw.event, trace_id: traceId, turn_id: raw.turn_id || state.turnId,
      protocol_version: 2, event_id: raw.event_id || `replay-${index}`,
      request_id: raw.request_id || traceId, sensitivity: raw.sensitivity || 'normal',
      sequence: typeof raw.sequence === 'number' ? raw.sequence : index + 1,
      stage: raw.stage || 'request', stage_id: raw.stage_id || 'request.1',
      started_at: raw.started_at || raw.timestamp || '', visibility: raw.visibility || 'public',
      detail: raw.detail || {}, content: '', citations: [],
    }
    if (isAgentEvent(event)) state = reduceTurnEvent(state, event)
  })
  if (summary && !state.terminalReceived && ['completed', 'failed', 'cancelled'].includes(String(summary.status))) {
    const event = {
      type: `turn.${summary.status}`, status: summary.status, trace_id: traceId,
      protocol_version: 2, event_id: 'replay-terminal', request_id: traceId,
      visibility: 'public', sensitivity: 'normal',
      turn_id: state.turnId, sequence: state.lastSequence + 1, stage: 'request', stage_id: 'request.1',
      started_at: summary.timestamp || '', duration_ms: summary.total_duration_ms,
      detail: { answer_first_token_ms: summary.answer_first_token_ms },
    }
    if (isAgentEvent(event)) state = reduceTurnEvent(state, event)
  }
  state.traceId = traceId
  if (typeof summary?.answer_first_token_ms === 'number') state.metrics.answerFirstTokenMs = summary.answer_first_token_ms
  if (typeof summary?.total_duration_ms === 'number') state.metrics.totalDurationMs = summary.total_duration_ms
  return state
}

/** 每批连续答案增量合并，保留中间的阶段/修订事件及原始日志顺序。 */
export function compactTraceEvents(rows: Record<string, unknown>[]): Record<string, unknown>[] {
  const result: Record<string, unknown>[] = []
  const terminal = [...rows].reverse().find(row => ['turn.completed', 'turn.failed', 'turn.cancelled'].includes(String(row.event)))
  for (const raw of rows) {
    if (raw.event !== 'answer.delta') { result.push(raw); continue }
    const last = result[result.length - 1]
    const length = Number(raw.content_length || 0)
    if (last?.event === 'answer.delta') {
      const detail = last.detail as Record<string, number>
      detail.chunk_count += 1
      detail.character_count += length
    } else {
      result.push({ ...raw, status: terminal?.status || 'running', duration_ms: null,
        summary: '回答流式输出', detail: { chunk_count: 1, character_count: length } })
    }
  }
  return result
}

/** 作者：LHF；2026-10-25；优先使用服务端终态记录，兼容旧服务的开始/完成事件配对。 */
export function completedTraceRecords(records: Record<string, unknown>[] | undefined, events: Record<string, unknown>[]): Record<string, unknown>[] {
  if (records) return [...records].sort((a, b) => String(a.started_at || '').localeCompare(String(b.started_at || '')))
  const starts = new Map<unknown, Record<string, unknown>>()
  const result: Record<string, unknown>[] = []
  for (const event of events) {
    if (event.event === 'stage.started' || event.event === 'turn.started') { starts.set(event.stage_id, event); continue }
    if (!['stage.completed', 'stage.failed', 'llm.context'].includes(String(event.event))) continue
    if (event.stage === 'preparation' || event.stage === 'model_output' || event.stage_id === 'agent.debug') continue
    const begin = starts.get(event.stage_id)
    const detail = event.detail as Record<string, unknown> || {}
    result.push({ ...event, kind: event.event === 'llm.context' ? 'model' : event.stage,
      operation_id: event.event_id || event.stage_id,
      started_at: begin?.started_at || event.started_at,
      input: event.event === 'llm.context' ? detail.request : detail.input,
      output: event.event === 'llm.context' ? null : detail.output ?? detail,
      metadata: { legacy: true } })
  }
  return result
}
