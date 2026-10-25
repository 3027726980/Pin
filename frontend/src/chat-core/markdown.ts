/** 作者：LHF；时间：2026-10-25；作用：管理端与 Widget 共用安全 Markdown 及来源引用渲染。 */
import MarkdownIt from 'markdown-it'

const markdown = new MarkdownIt({ html: false, breaks: true, linkify: true })

// 仅在普通行内文本中识别已绑定引用，代码块、行内代码和 Markdown 链接保持原义。
markdown.inline.ruler.after('link', 'source_reference', (state, silent) => {
  if (state.linkLevel > 0) return false
  const match = /^\[(S[1-9]\d*|[1-9]\d*)\]/.exec(state.src.slice(state.pos))
  if (!match || !(state.env.citationReferences as Set<string>)?.has(match[1])) return false
  if (!silent) {
    const token = state.push('source_reference', 'span', 0)
    token.content = match[1]
  }
  state.pos += match[0].length
  return true
})
/** 渲染器仅输出解析器校验过的数字或 S#，不插入模型提供的任意属性。 */
markdown.renderer.rules.source_reference = (tokens, index) => {
  const id = tokens[index].content
  return `<span class="markdown-citation" data-source-ref="${id}" role="button" tabindex="0">[${id}]</span>`
}
/** 外部链接隔离新窗口，URL 协议继续由 MarkdownIt 校验。 */
markdown.renderer.rules.link_open = (tokens, index, options, _env, renderer) => {
  tokens[index].attrSet('target', '_blank')
  tokens[index].attrSet('rel', 'noopener noreferrer')
  return renderer.renderToken(tokens, index, options)
}

/** 从完整累积文本渲染 Markdown，允许流式中未闭合的代码围栏自然展示。 */
export function renderMarkdown(content: string, references: Iterable<string> = []): string {
  return markdown.render(content, { citationReferences: new Set(references) })
}
