/** 作者：LHF；时间：2026-10-25；作用：验证两端共享 @ 搜索、偏好和产物契约。 */
import { describe, expect, it } from 'vitest'
import { mentionQuery, mentionOptions, insertMention, eventArtifacts } from './capabilities'

describe('能力提及', () => {
  it('只在独立 @ 和光标前搜索，邮箱保持普通文字', () => {
    expect(mentionQuery('user@example.com')).toBeNull()
    expect(mentionQuery('普通@文字')).toBeNull()
    expect(mentionQuery('请用 @报告')).toEqual({ start: 3, end: 6, query: '报告' })
    expect(mentionQuery('@rag 后面的文字', 4)?.query).toBe('rag')
  })
  it('技能与工具分组标识相同名称，并排除已选择项', () => {
    const caps = { skills: [{ kind: 'skill' as const, name: 'report', description: '中文报告' }], tools: [{ kind: 'tool' as const, name: 'report', description: '业务报表工具' }] }
    expect(mentionOptions(caps, '报告', [])).toHaveLength(1)
    expect(mentionOptions(caps, 'report', [{ kind: 'skill', name: 'report' }])).toEqual(caps.tools)
  })
  it('选中后只移除查询片段，不把强制执行指令写入正文', () => {
    const text = '请用 @report 帮我整理'
    const query = mentionQuery(text, 10)!
    expect(insertMention(text, query)).toBe('请用  帮我整理')
  })
  it('忽略缺少定位字段的附件事件', () => {
    expect(eventArtifacts([{ name: 'fake' }, { run_id: 'run', path: 'out/a.txt', name: 'a.txt', size: 2 }])).toHaveLength(1)
  })
})
