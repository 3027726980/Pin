/** 链路回放、增量合并及面向用户的诊断字段。 */
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
const FIELD_LABELS: Record<string, string> = {
  pid: '后端进程 ID', first_import: '首次加载 Agent 依赖', openai_first_import: '首次加载模型依赖',
  tool_count: '绑定工具数量', message_count: '历史消息数量',
  output: '输出或错误详情', output_truncated: '内容已截断', error_type: '异常类型',
  is_error: '工具返回错误', tool_call_id: '工具调用编号', tool_calls: '模型工具调用', usage: 'Token 用量',
  strategy: '检索策略', queries: '检索问题', original_query: '原始问题',
  hyde: '假设文档', hyde_text: '假设文档', reason_codes: '决策依据',
  candidate_count: '候选数量', result_count: '结果数量', query_count: '问题数量',
  top_k: '返回条数', score_threshold: '相似度阈值', score: '最终分数',
  original_score: '原始分数', document_name: '文档名称', chunk_id: '片段编号',
  intent: '执行路由', intent_code: '意图类别', status: '状态', duration_ms: '耗时（毫秒）',
  model: '模型', model_name: '模型', tool: '工具', args: '工具参数',
  stats: '检索统计', signals: '召回信号', modes: '增强开关',
  mqe_mode: 'MQE 模式', hyde_mode: 'HyDE 模式', rerank_mode: '精排模式',
  mqe: '多查询扩展', rerank: '精排', before: '精排前', after: '精排后',
  passed: '核验通过', reasons: '核验依据', revision_required: '需要修订',
  plan: '执行计划', suggestions: '改进建议', chunk_count: '增量次数',
  character_count: '输出字符数', content_length: '输出字符数',
  queue_wait_ms: '排队耗时（毫秒）', first_token_ms: '模型首 Token（毫秒）',
  answer_first_token_ms: '首答案 Token（毫秒）', total_duration_ms: '总耗时（毫秒）',
  tool_call_count: '工具调用次数', citations: '来源候选', matches: '召回片段',
  'rag.strategy.selected': '自适应检索决策', provider: '模型厂商', enabled: '已启用',
  top1_score: '最高召回分数', top3_avg: '前三条平均分',
  above_threshold_count: '达到阈值的条数', document_diversity: '来源文档数量',
  query_length: '问题长度', is_follow_up: '属于追问', is_multi_part: '包含多个条件',
  is_conceptual: '概念性问题', threshold: '召回阈值', query: '检索问题',
}
const VALUE_LABELS: Record<string, string> = {
  base: '基础检索', hybrid: '混合增强', mqe: '多查询扩展', hyde: '假设文档增强',
  off: '关闭', auto: '自动', always: '始终开启', simple: '轻量直答', general: '完整 Agent',
  complex: '复杂任务', ...STATUS_LABELS,
  confidence_high: '原始召回置信度高', confidence_low: '原始召回置信度低',
  confidence_medium: '原始召回置信度中等', query_multi_or_follow_up: '多条件问题或上下文追问',
  query_conceptual_or_short: '概念性或简短问题', low_recall_expand: '召回不足，扩展查询',
  low_recall_hypothesis: '召回不足，生成假设文档', auto_budget_exhausted: '预算或模型配额不足',
  rerank_for_competing_candidates: '候选资料需要精排',
}
function readable(value: unknown, depth = 0): string {
  if (value == null) return '未记录'
  if (typeof value === 'boolean') return value ? '是' : '否'
  if (typeof value === 'string') {
    if (value.startsWith('[') || value.startsWith('{')) {
      try { return readable(JSON.parse(value), depth + 1) } catch { /* 普通文本 */ }
    }
    return VALUE_LABELS[value] || value
  }
  if (Array.isArray(value)) return value.map(item => readable(item, depth + 1)).join('\n') || '无'
  if (typeof value === 'object') {
    if (depth > 8) return '嵌套详情请查看原始数据'
    return Object.entries(value).map(([key, item]) => `${FIELD_LABELS[key] || key}：${readable(item, depth + 1)}`).join('\n') || '无'
  }
  return String(value)
}
export function detailFields(detail: Record<string, unknown>) {
  return Object.entries(detail).map(([key, value]) => ({ key, label: FIELD_LABELS[key] || key, value: readable(value) }))
}

/** 日志不保存答案正文；以空 content/citations 回放状态而不恢复不存在的正文。 */
export function buildTraceState(traceId: string, summary: Record<string, unknown> | null, rows: Record<string, unknown>[]): TurnState {
  let state = createTurnState(String(summary?.turn_id || ''))
  rows.forEach((raw, index) => {
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
