/** 作者：LHF；时间：2026-10-25；作用：验证 Markdown、流式片段、安全边界与来源引用共存。 */
import { describe, expect, it } from 'vitest'
import { renderMarkdown } from './markdown'

describe('shared answer Markdown', () => {
  it('renders headings, lists, emphasis, tables and quotes', () => {
    const html = renderMarkdown('# 标题\n\n**加粗**\n\n- 项目\n\n> 引用\n\n| 列 |\n| --- |\n| 值 |')
    for (const tag of ['h1', 'strong', 'ul', 'blockquote', 'table']) expect(html).toContain(`<${tag}>`)
  })

  it('renders accumulated streaming code and preserves literal citations in code', () => {
    expect(renderMarkdown('```ts\nconst a = "[S1]"', ['S1'])).toContain('<code class="language-ts">')
    expect(renderMarkdown('`[S1]`\n\n```\n[S1]\n```', ['S1'])).not.toContain('data-source-ref')
    expect(renderMarkdown('**回答')).toContain('回答')
    expect(renderMarkdown('**回答**')).toContain('<strong>回答</strong>')
  })

  it('keeps bound citations clickable within formatting without breaking links', () => {
    const html = renderMarkdown('**依据 [S1]** [2] [3] [S1](https://example.com)', ['S1', '2'])
    expect(html).toContain('data-source-ref="S1"')
    expect(html).toContain('data-source-ref="2"')
    expect(html).not.toContain('data-source-ref="3"')
    expect(html).toContain('href="https://example.com"')
    expect(html).toContain('rel="noopener noreferrer"')
    expect(html).toContain('<strong>依据 <span')
    expect(renderMarkdown('[站点][url]\n\n[url]: https://example.com', ['S1'])).toContain('href="https://example.com"')
  })

  it('escapes raw HTML and blocks executable link protocols', () => {
    const html = renderMarkdown('<img src=x onerror=alert(1)>\n<script>alert(1)</script>\n[x](javascript:alert(1))')
    expect(html).not.toContain('<img')
    expect(html).not.toContain('<script')
    expect(html).not.toContain('href="javascript:')
    expect(html).toContain('&lt;img')
  })
})
