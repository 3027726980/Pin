export const PUBLIC_STAGE_TEXT: Record<string, string> = {
  intent: '正在理解你的问题',
  plan: '正在规划处理步骤',
  mqe: '正在扩展检索范围',
  hyde: '正在扩展检索范围',
  embedding: '正在查找相关资料',
  retrieval: '正在查找相关资料',
  rerank: '正在优化检索结果',
  agent: '正在生成回答',
  answer: '正在生成回答',
  verify: '正在复核回答',
}

export function formatDuration(durationMs: number | null | undefined): string {
  if (durationMs == null) return '进行中'
  return durationMs < 1000
    ? `${durationMs}ms`
    : `${(durationMs / 1000).toFixed(1)}s`
}
