/** 作者：LHF；时间：2026-10-25；作用：管理端与 Widget 共享能力提及和产物契约。 */

export interface CapabilityMention { kind: 'skill' | 'tool'; name: string }
export interface Capability extends CapabilityMention { description: string }
export interface Capabilities { skills: Capability[]; tools: Capability[] }
export interface SkillArtifact { run_id: string; path: string; name: string; size: number }
export interface MentionQuery { start: number; end: number; query: string }

/** 只匹配光标前独立的 @ 查询，邮箱及普通行内文字不触发。 */
export function mentionQuery(text: string, cursor = text.length): MentionQuery | null {
  const prefix = text.slice(0, cursor)
  const match = /(?:^|\s)@([\w\-\u3400-\u9fff]*)$/.exec(prefix)
  return match ? { start: prefix.lastIndexOf('@'), end: cursor, query: match[1] || '' } : null
}

/** 两端按相同规则搜索技能、工具，已选择项不重复显示。 */
export function mentionOptions(caps: Capabilities, query: string, selected: CapabilityMention[]): Capability[] {
  const term = query.toLocaleLowerCase()
  return [...caps.skills, ...caps.tools].filter(item =>
    !selected.some(value => value.kind === item.kind && value.name === item.name)
    && `${item.name} ${item.description}`.toLocaleLowerCase().includes(term))
}

/** 选择候选后移除输入中的查询片段，偏好由独立标签保存。 */
export function insertMention(text: string, query: MentionQuery): string {
  return text.slice(0, query.start) + text.slice(query.end)
}

/** 只接受完整产物定位字段，忽略不兼容事件载荷。 */
export function eventArtifacts(value: unknown): SkillArtifact[] {
  if (!Array.isArray(value)) return []
  return value.filter((item): item is SkillArtifact => item && typeof item.run_id === 'string'
    && typeof item.path === 'string' && typeof item.name === 'string' && typeof item.size === 'number')
}

/** 将鉴权请求取得的 Blob 交给浏览器保存，随后释放对象 URL。 */
export function saveDownload(blob: Blob, name: string): void {
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = name
  anchor.click()
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}
