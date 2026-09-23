/** 浏览器本地文档清洗与强制重叠切片；语义由共享 v1 契约约束。 */

export const PROCESSING_ALGORITHM_VERSION = 1

export type CleaningRuleType =
  | 'normalize_unicode'
  | 'remove_control_chars'
  | 'collapse_blank_lines'
  | 'trim_lines'
  | 'collapse_punctuation'
  | 'replace_text'
  | 'regex_remove'

export interface CleaningRule {
  type: CleaningRuleType
  enabled?: boolean
  value?: string | null
  replacement?: string
  max_consecutive?: number
}

export interface CleaningConfig {
  rules: CleaningRule[]
}

export interface ProcessingConfig {
  cleaning_config: CleaningConfig
  chunk_size: number
  chunk_overlap: number
  chunk_separators: string
}

export interface LocalPreviewChunk {
  index: number
  content: string
  char_count: number
  overlap_char_count: number
}

export interface LocalDocumentPreview {
  cleanedText: string
  chunks: LocalPreviewChunk[]
}

function codePointLength(value: string): number {
  return Array.from(value).length
}

/** 按顺序执行与后端相同的确定性清洗规则。 */
export function cleanDocumentText(raw: string, config: CleaningConfig): string {
  let text = raw.replace(/\r\n/g, '\n').replace(/\r/g, '\n')
  for (const rule of config.rules) {
    if (rule.enabled === false) continue
    switch (rule.type) {
      case 'normalize_unicode':
        text = text.normalize('NFC')
        break
      case 'remove_control_chars':
        text = Array.from(text)
          .filter(char => char === '\n' || char === '\r' || char === '\t' || !/\p{Cc}/u.test(char))
          .join('')
        break
      case 'collapse_blank_lines': {
        const max = rule.max_consecutive ?? 1
        text = text.replace(new RegExp(`\\n{${max + 1},}`, 'g'), '\n'.repeat(max))
        break
      }
      case 'trim_lines':
        text = text.split('\n').map(line => line.trim()).join('\n')
        break
      case 'collapse_punctuation':
        text = text.replace(/([，。！？；：,.!?;:])\1+/gu, '$1')
        break
      case 'replace_text':
        if (rule.value) text = text.split(rule.value).join(rule.replacement ?? '')
        break
      case 'regex_remove':
        if (rule.value) {
          const replacement = rule.replacement ?? ''
          text = text.replace(new RegExp(rule.value, 'gu'), () => replacement)
        }
        break
    }
  }
  return text
}

function findSeparatorEnd(
  chars: string[],
  separator: string[],
  position: number,
  maxEnd: number,
): number | null {
  if (separator.length === 0) return null
  for (let start = maxEnd - separator.length; start > position; start -= 1) {
    let matches = true
    for (let offset = 0; offset < separator.length; offset += 1) {
      if (chars[start + offset] !== separator[offset]) {
        matches = false
        break
      }
    }
    if (matches) return start + separator.length
  }
  return null
}

/** 按有序分隔符贪心生成主体，再显式前置上一最终块的尾部。 */
export function splitDocumentText(text: string, config: ProcessingConfig): LocalPreviewChunk[] {
  const chunkSize = Math.max(1, Math.trunc(config.chunk_size))
  const overlap = Math.min(Math.max(0, Math.trunc(config.chunk_overlap)), chunkSize - 1)
  const bodySize = Math.max(1, chunkSize - overlap)
  const separators = config.chunk_separators
    .split(',')
    .filter(separator => separator !== '')
    .map(separator => Array.from(separator))
  const chars = Array.from(text)
  const bodies: string[] = []

  let position = 0
  while (position < chars.length) {
    const maxEnd = Math.min(position + bodySize, chars.length)
    let chosenEnd = maxEnd
    if (maxEnd < chars.length) {
      for (const separator of separators) {
        const separatorEnd = findSeparatorEnd(chars, separator, position, maxEnd)
        if (separatorEnd !== null) {
          chosenEnd = separatorEnd
          break
        }
      }
    }
    const body = chars.slice(position, chosenEnd).join('')
    if (body.trim()) bodies.push(body)
    position = chosenEnd
  }

  const chunks: LocalPreviewChunk[] = []
  for (const body of bodies) {
    let content = body
    let overlapCount = 0
    if (chunks.length > 0 && overlap > 0) {
      const previousChars = Array.from(chunks[chunks.length - 1].content)
      overlapCount = Math.min(overlap, previousChars.length)
      content = previousChars.slice(-overlapCount).join('') + body
    }
    chunks.push({
      index: chunks.length,
      content,
      char_count: codePointLength(content),
      overlap_char_count: overlapCount,
    })
  }
  return chunks
}

/** 一次生成清洗文本和本地草稿切片。 */
export function buildDocumentPreview(
  raw: string,
  config: ProcessingConfig,
): LocalDocumentPreview {
  const cleanedText = cleanDocumentText(raw, config.cleaning_config)
  return {
    cleanedText,
    chunks: splitDocumentText(cleanedText, config),
  }
}
