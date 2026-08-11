/** 引用标注解析：与主站 AgentChatView 逻辑一致 */

export interface Citation {
  chunk_id: string
  document_name: string
  content: string
  score: number
}

/** 拆分消息内容：文本段 + [N] 引用标注段（避免 innerHTML，防 XSS） */
export function splitRefs(content: string): Array<{ type: 'text' | 'ref'; value: string; index?: number }> {
  const parts = content.split(/(\[\d+\])/g)
  return parts
    .filter(p => p)
    .map(p => {
      const m = p.match(/^\[(\d+)\]$/)
      if (m) return { type: 'ref' as const, value: p, index: parseInt(m[1], 10) }
      return { type: 'text' as const, value: p }
    })
}

/** 提取内容中所有 [N] 引用序号 */
export function extractRefIndexes(content: string): Set<number> {
  const set = new Set<number>()
  const re = /\[(\d+)\]/g
  let m: RegExpExecArray | null
  while ((m = re.exec(content)) !== null) {
    set.add(parseInt(m[1], 10))
  }
  return set
}

/** 过滤未实际引用的条目（与主站一致：保留原始编号） */
export function filterUsedCitations(
  citations: Citation[],
  content: string,
): Citation[] {
  const used = extractRefIndexes(content)
  return citations.filter((_, i) => used.has(i + 1))
}
